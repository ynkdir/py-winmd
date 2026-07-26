"""The Win32 API, resolved from the metadata when an attribute is looked up.

    import win32api as win32

    win32.MessageBoxW(None, "hello", "winmd", win32.MB_OK | win32.MB_ICONINFORMATION)
    win32.MessageBoxA(None, b"hello", b"winmd", win32.MB_OK)

    point = win32.POINT()
    win32.GetCursorPos(win32.byref(point))
    print(point.x, point.y)

Nothing is generated ahead of time: the first attribute access loads the Win32
metadata, and every name (function, struct, union, enum, enum member, constant,
callback or COM interface) is turned into the matching ctypes object on demand
and cached in the module. `examples/ctypes_gen.py` does the same thing as a code
generator when a static module is preferable.

The metadata is looked up in WINMD_METADATA or next to the repository; call
`configure(*files)` before anything else to point somewhere else.
"""

import ctypes
import glob
import keyword
import os
import re
import sys
from ctypes import (  # noqa: F401  (re-exported for convenience)
    CFUNCTYPE,
    POINTER,
    WINFUNCTYPE,
    Structure,
    Union,
    addressof,
    byref,
    cast,
    create_string_buffer,
    create_unicode_buffer,
    get_last_error,
    pointer,
    sizeof,
)
from enum import IntEnum, IntFlag

from winmd.reader import (
    ElementType,
    TypeDefOrRef,
    TypeLayout,
    cache,
    category,
    coded_index_TypeDefOrRef,
    find,
    get_attribute,
    get_category,
)

METADATA_ATTRIBUTES = "Windows.Win32.Foundation.Metadata"

PRIMITIVES = {
    ElementType.Void: None,
    ElementType.Boolean: ctypes.c_bool,
    ElementType.Char: ctypes.c_wchar,
    ElementType.I1: ctypes.c_int8,
    ElementType.U1: ctypes.c_uint8,
    ElementType.I2: ctypes.c_int16,
    ElementType.U2: ctypes.c_uint16,
    ElementType.I4: ctypes.c_int32,
    ElementType.U4: ctypes.c_uint32,
    ElementType.I8: ctypes.c_int64,
    ElementType.U8: ctypes.c_uint64,
    ElementType.R4: ctypes.c_float,
    ElementType.R8: ctypes.c_double,
    ElementType.I: ctypes.c_ssize_t,
    ElementType.U: ctypes.c_size_t,
    ElementType.String: ctypes.c_wchar_p,
    ElementType.Object: ctypes.c_void_p,
}

# PInvokeAttributes (ECMA-335 II.23.1.8)
CALL_CONV_MASK = 0x0700
CALL_CONV_CDECL = 0x0200
SUPPORTS_LAST_ERROR = 0x0040


class GUID(Structure):
    """System.Guid / REFIID"""

    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]

    def __init__(self, value=None):
        super().__init__()
        if value:
            text = value.strip("{}").replace("-", "")
            self.Data1 = int(text[0:8], 16)
            self.Data2 = int(text[8:12], 16)
            self.Data3 = int(text[12:16], 16)
            for index in range(8):
                self.Data4[index] = int(text[16 + index * 2 : 18 + index * 2], 16)

    def __str__(self):
        data4 = bytes(self.Data4)
        return "{{{:08x}-{:04x}-{:04x}-{}-{}}}".format(
            self.Data1, self.Data2, self.Data3, data4[:2].hex(), data4[2:].hex()
        )

    def __eq__(self, other):
        return isinstance(other, GUID) and bytes(self) == bytes(other)

    def __hash__(self):
        return hash(bytes(self))


class _Interface(ctypes.c_void_p):
    """A COM interface pointer; methods are called through the vtable."""

    _iid_ = None

    def __repr__(self):
        return f"<{type(self).__name__} at {self.value and hex(self.value)}>"


# Types that ctypes already models better than their metadata definition.
OVERRIDES = {
    ("Windows.Win32.Foundation", "PWSTR"): ctypes.c_wchar_p,
    ("Windows.Win32.Foundation", "PCWSTR"): ctypes.c_wchar_p,
    ("Windows.Win32.Foundation", "PSTR"): ctypes.c_char_p,
    ("Windows.Win32.Foundation", "PCSTR"): ctypes.c_char_p,
    ("Windows.Win32.Foundation", "BSTR"): ctypes.c_wchar_p,
    ("System", "Guid"): GUID,
}

_files = None
_cache = None
_index = None          # name -> ("function" | "type" | "constant" | "member", ...)
_types = {}            # TypeDef -> ctypes type
_libraries = {}        # (dll, flags) -> CDLL/WinDLL
_imports = {}          # database path -> {MethodDef index: (dll, entry point, flags)}
_pending = []          # COM interfaces whose methods are not bound yet
_incomplete = set()    # records whose _fields_ are not assigned yet
_deferred = []         # (record, fields, anonymous, dependencies) waiting for those
_enum_ctype = {}       # IntEnum class -> the ctypes integer type it is stored as


# --- metadata ---------------------------------------------------------------
def configure(*files):
    """Uses these .winmd files instead of the default ones."""
    global _files, _cache, _index
    _files, _cache, _index = list(files), None, None
    _types.clear()
    _enum_ctype.clear()
    _incomplete.clear()
    _deferred.clear()
    _libraries.clear()
    _imports.clear()


def _metadata_files():
    if _files:
        return _files
    root = os.environ.get("WINMD_METADATA") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "metadata"
    )
    files = sorted(glob.glob(os.path.join(root, "**", "Windows.Win32*.winmd"), recursive=True))
    if not files:
        raise RuntimeError(
            f"no Win32 metadata under {root}; run fetch-packages.ps1 or call configure()"
        )
    return files


def metadata():
    """The winmd cache everything is resolved from."""
    global _cache
    if _cache is None:
        _cache = cache(_metadata_files())
        for database in _cache.databases():
            _imports[database.path()] = _read_imports(database)
    return _cache


def _read_imports(database):
    """{MethodDef row: (dll, entry point, flags)} from the ImplMap table."""
    modules = [database.get_string(row.get_value(0)) for row in database.ModuleRef]
    imports = {}
    for row in database.ImplMap:
        member = row.get_value(1)
        if member & 1:  # MemberForwarded: 1 == MethodDef
            scope = row.get_value(3)
            imports[(member >> 1) - 1] = (
                modules[scope - 1] if 0 < scope <= len(modules) else None,
                database.get_string(row.get_value(2)),
                row.get_value(0),
            )
    return imports


def _build_index():
    """name -> what it is. Built once, on the first lookup."""
    global _index
    if _index is not None:
        return _index

    _index = {}
    for namespace, members in metadata().namespaces().items():
        if not namespace.startswith("Windows.Win32"):
            continue
        apis = members.types.get("Apis")
        if apis:
            for method in apis.MethodList():
                _index.setdefault(method.Name(), ("function", method))
            for field in apis.FieldList():
                _index.setdefault(field.Name(), ("constant", field))
        for name, type in members.types.items():
            if name != "Apis":
                _index.setdefault(name, ("type", type))
        for type in members.enums:
            for field in type.FieldList():
                if field.Flags().Literal():
                    _index.setdefault(field.Name(), ("member", type, field.Name()))
    return _index


# --- type resolution --------------------------------------------------------
def _identifier(name):
    name = re.sub(r"\W", "_", name)
    if keyword.iskeyword(name) or not name or name[0].isdigit():
        name = "_" + name
    return name


def _array_count(row):
    attribute = row and get_attribute(row, METADATA_ATTRIBUTES, "NativeArrayInfoAttribute")
    if attribute:
        try:
            for named in attribute.Value().NamedArgs():
                if named.name == "CountConst":
                    return named.value.value.value
        except ValueError:
            pass  # an argument of a type that is not in the cache
    return None


def _iid_of(type):
    attribute = get_attribute(type, METADATA_ATTRIBUTES, "GuidAttribute")
    if not attribute:
        return None
    try:
        args = [argument.value.value for argument in attribute.Value().FixedArgs()]
    except ValueError:
        return None
    if len(args) != 11:
        return None
    return GUID(
        "{{{:08x}-{:04x}-{:04x}-{}-{}}}".format(
            args[0],
            args[1],
            args[2],
            "".join(f"{b:02x}" for b in args[3:5]),
            "".join(f"{b:02x}" for b in args[5:]),
        )
    )


def _type_of(sig, count=None):
    result = _element_of(sig.Type())
    for _ in range(sig.ptr_count()):
        result = ctypes.c_void_p if result is None else POINTER(result)
    if sig.is_szarray() or sig.is_array():
        result = (result * count) if count else POINTER(result)
    return result


def _element_of(value):
    if isinstance(value, ElementType):
        return PRIMITIVES.get(value, ctypes.c_void_p)
    if isinstance(value, coded_index_TypeDefOrRef):
        if value.type() == TypeDefOrRef.TypeSpec:
            return ctypes.c_void_p
        definition = find(value)
        if definition:
            resolved = _resolve_type(definition)
            # An IntEnum carries the values; ctypes needs the integer type.
            return _enum_ctype.get(resolved, resolved)
        return ctypes.c_void_p
    return ctypes.c_void_p


def _resolve_type(typedef):
    """The ctypes counterpart of a TypeDef, built once."""
    known = _types.get(typedef)
    if known is not None:
        return known

    override = OVERRIDES.get((typedef.TypeNamespace(), typedef.TypeName()))
    if override is not None:
        _types[typedef] = override
        return override

    kind = get_category(typedef)
    name = _identifier(typedef.TypeName())

    if kind == category.enum_type:
        result = _build_enum(typedef, name)
    elif kind == category.interface_type:
        result = _interface_class(typedef, name)
    elif kind == category.delegate_type:
        result = _build_callback(typedef)
    elif kind == category.struct_type:
        if get_attribute(typedef, METADATA_ATTRIBUTES, "NativeTypedefAttribute"):
            inner = next(iter(typedef.FieldList()))
            result = _type_of(inner.Signature().Type())
            _types[typedef] = result
        else:
            result = _build_record(typedef, name)
    else:
        result = ctypes.c_void_p
        _types[typedef] = result
    return result


def _build_enum(typedef, name):
    base = IntFlag if get_attribute(typedef, "System", "FlagsAttribute") else IntEnum
    members = {}
    for field in typedef.FieldList():
        if field.Flags().Literal():
            members[_identifier(field.Name())] = field.Constant().Value()
    result = base(name, members) if members else base(name, {"_none": 0})
    _enum_ctype[result] = PRIMITIVES.get(
        typedef.get_enum_definition().m_underlying_type, ctypes.c_int32
    )
    _types[typedef] = result
    return result


def _build_record(typedef, name):
    keyword_ = Union if typedef.Flags().Layout() == TypeLayout.ExplicitLayout else Structure
    result = type(name, (keyword_,), {})
    _types[typedef] = result  # registered before the fields: the metadata has cycles
    _incomplete.add(result)

    layout = next(
        (row for row in typedef.get_database().ClassLayout if row.Parent() == typedef), None
    )
    if layout and layout.PackingSize():
        result._pack_ = layout.PackingSize()

    fields, anonymous, embedded = [], [], set()
    for field in typedef.FieldList():
        ctype = _type_of(field.Signature().Type(), _array_count(field))
        fields.append((_identifier(field.Name()), ctype))
        if field.Name().startswith("Anonymous"):
            anonymous.append(_identifier(field.Name()))
        # Held by value: its layout has to be known before ours is set.
        element = getattr(ctype, "_type_", ctype) if _is_array(ctype) else ctype
        if isinstance(element, type) and issubclass(element, (Structure, Union)):
            embedded.add(element)

    _assign_fields(result, fields, anonymous, embedded)
    return result


def _is_array(ctype):
    return isinstance(ctype, type) and issubclass(ctype, ctypes.Array)


def _assign_fields(record, fields, anonymous, embedded):
    """Sets _fields_, or waits until every embedded record is complete."""
    if embedded & _incomplete:
        _deferred.append((record, fields, anonymous, embedded))
        return
    if anonymous:
        record._anonymous_ = tuple(anonymous)
    record._fields_ = fields
    _incomplete.discard(record)


def _drain_deferred_fields():
    progress = True
    while progress and _deferred:
        progress = False
        for item in list(_deferred):
            if not item[3] & _incomplete:
                _deferred.remove(item)
                _assign_fields(*item)
                progress = True


def _build_callback(typedef):
    invoke = next((m for m in typedef.MethodList() if m.Name() == "Invoke"), None)
    if invoke is None:
        result = ctypes.c_void_p
        _types[typedef] = result
        return result
    signature = invoke.Signature()
    restype = _type_of(signature.ReturnType().Type()) if signature.ReturnType() else None
    argtypes = [_type_of(param.Type()) for param in signature.Params()]
    result = WINFUNCTYPE(restype, *argtypes)
    _types[typedef] = result
    return result


# --- COM --------------------------------------------------------------------
def _base_interface(typedef):
    for impl in typedef.InterfaceImpl():
        base = find(impl.Interface())
        if base:
            return base
    return None


def _vtable_size(typedef):
    base = _base_interface(typedef)
    return (_vtable_size(base) if base else 0) + len(typedef.MethodList())


def _interface_class(typedef, name):
    """Creates the class; the methods are bound once the recursion unwinds."""
    known = _types.get(typedef)
    if known is not None:
        return known
    base = _base_interface(typedef)
    base_class = _interface_class(base, _identifier(base.TypeName())) if base else _Interface
    result = type(name, (base_class,), {"_iid_": _iid_of(typedef)})
    _types[typedef] = result
    _pending.append((typedef, result))
    return result


def _com_method(name, index, restype, argtypes):
    prototype = WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)

    def call(self, *arguments):
        if not self.value:
            raise ValueError(f"{type(self).__name__}.{name} on a null interface")
        vtable = cast(self, POINTER(POINTER(ctypes.c_void_p)))
        return prototype(vtable[0][index])(self, *arguments)

    call.__name__ = name
    call.__qualname__ = name
    return call


def _bind_pending_methods():
    while _pending:
        typedef, result = _pending.pop()
        base = _base_interface(typedef)
        slot = _vtable_size(base) if base else 0
        for method in typedef.MethodList():
            signature = method.Signature()
            restype = _type_of(signature.ReturnType().Type()) if signature.ReturnType() else None
            rows = {p.Sequence(): p for p in method.ParamList()}
            argtypes = [
                _type_of(param.Type(), _array_count(rows.get(index)))
                for index, param in enumerate(signature.Params(), start=1)
            ]
            name = _identifier(method.Name())
            setattr(result, name, _com_method(name, slot, restype, argtypes))
            slot += 1


# --- functions and constants ------------------------------------------------
def _library(dll, flags):
    key = (dll, flags & CALL_CONV_MASK, bool(flags & SUPPORTS_LAST_ERROR))
    library = _libraries.get(key)
    if library is None:
        loader = ctypes.CDLL if key[1] == CALL_CONV_CDECL else ctypes.WinDLL
        library = loader(dll, use_last_error=key[2])
        _libraries[key] = library
    return library


def _resolve_function(method):
    entry = _imports[method.get_database().path()].get(method.index())
    if entry is None or not entry[0]:
        raise AttributeError(f"{method.Name()} is not a DLL import")
    dll, symbol, flags = entry

    signature = method.Signature()
    restype = _type_of(signature.ReturnType().Type()) if signature.ReturnType() else None
    rows = {p.Sequence(): p for p in method.ParamList()}
    argtypes = [
        _type_of(param.Type(), _array_count(rows.get(index)))
        for index, param in enumerate(signature.Params(), start=1)
    ]

    function = _library(dll, flags)[symbol]
    function.restype = restype
    function.argtypes = argtypes
    return function


def _resolve_constant(field):
    if field.Flags().Literal():
        return field.Constant().Value()
    guid = get_attribute(field, METADATA_ATTRIBUTES, "GuidAttribute")
    if guid:
        value = _iid_of_field(guid)
        if value is not None:
            return value
    constant = get_attribute(field, METADATA_ATTRIBUTES, "ConstantAttribute")
    if constant:
        try:
            return constant.Value().FixedArgs()[0].value.value
        except (ValueError, IndexError):
            pass
    raise AttributeError(f"{field.Name()} has no value in the metadata")


def _iid_of_field(attribute):
    try:
        args = [argument.value.value for argument in attribute.Value().FixedArgs()]
    except ValueError:
        return None
    if len(args) != 11:
        return None
    return GUID(
        "{{{:08x}-{:04x}-{:04x}-{}-{}}}".format(
            args[0],
            args[1],
            args[2],
            "".join(f"{b:02x}" for b in args[3:5]),
            "".join(f"{b:02x}" for b in args[5:]),
        )
    )


# --- module protocol --------------------------------------------------------
def __getattr__(name):
    """Resolves a Win32 name the first time it is used (PEP 562)."""
    entry = _build_index().get(name)
    if entry is None:
        raise AttributeError(f"no Win32 function, type or constant named {name!r}")

    kind = entry[0]
    if kind == "function":
        value = _resolve_function(entry[1])
    elif kind == "type":
        value = _resolve_type(entry[1])
    elif kind == "constant":
        value = _resolve_constant(entry[1])
    else:  # an enum member
        value = getattr(_resolve_type(entry[1]), _identifier(entry[2]))
    _bind_pending_methods()
    _drain_deferred_fields()

    globals()[name] = value  # only resolved once
    return value


def __dir__():
    return sorted(set(globals()) | set(_build_index()))


def namespace_of(name):
    """The namespace a name was taken from, useful when names collide."""
    entry = _build_index().get(name)
    if entry is None:
        raise AttributeError(name)
    row = entry[1]
    return row.TypeNamespace() if entry[0] == "type" else row.Parent().TypeNamespace()


if __name__ == "__main__":
    index = _build_index()
    kinds = {}
    for entry in index.values():
        kinds[entry[0]] = kinds.get(entry[0], 0) + 1
    print(f"{len(index)} names:", ", ".join(f"{count} {kind}s" for kind, count in kinds.items()))
    for name in sys.argv[1:]:
        value = getattr(sys.modules[__name__], name)
        print(f"{name}: {value!r}")
