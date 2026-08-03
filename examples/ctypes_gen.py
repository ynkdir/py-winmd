"""Generates ready to use ctypes declarations from the Win32 metadata.

    python examples/ctypes_gen.py --function MessageBoxW --function GetSystemMetrics
    python examples/ctypes_gen.py -o user32.py \
        --namespace Windows.Win32.UI.WindowsAndMessaging
    python examples/ctypes_gen.py --function "CreateFileW" --type OVERLAPPED

Everything a selected function or type needs (structs, unions, typedefs, enums,
callbacks) is pulled in recursively, so the generated module imports and runs on
its own:

    import ctypes
    from generated import MessageBoxW, MB_ICONINFORMATION
    MessageBoxW(None, "hello", "winmd", MB_ICONINFORMATION)

COM interfaces become classes whose methods are dispatched through the vtable:

    stream = SHCreateMemStream(None, 0)
    written = c_uint32()
    stream.Write(b"hello", 5, byref(written))
    stream.Seek(0, STREAM_SEEK.STREAM_SEEK_SET, None)
    stream.QueryInterface(byref(IUnknown._iid_), byref(unknown))
    stream.Release()                                # inherited from IUnknown

What it emits, and what that took:

    structs, unions     Structure / Union. The classes are declared before their
                        _fields_ are assigned, the metadata having cycles;
                        by-value dependencies are sorted topologically and the
                        PackingSize of ClassLayout becomes _pack_
    anonymous unions    registered in _anonymous_, so their members are reachable
                        directly
    enums               IntEnum / IntFlag (following [Flags]) plus a module
                        constant per member; argtypes uses the underlying ctypes
                        type, since an enum class has no from_param
    functions           WinDLL / CDLL and use_last_error follow the MappingFlags
                        of ImplMap; restype and argtypes are set at import time
    callbacks           WINFUNCTYPE / CFUNCTYPE
    fixed size arrays   type * N, from the CountConst of NativeArrayInfoAttribute
    GUID constants      instances of the GUID structure the generated module ships
    COM interfaces      classes deriving from c_void_p whose methods go through
                        their vtable slot; the hierarchy (IStream ->
                        ISequentialStream -> IUnknown) and the IID (_iid_) are
                        preserved
    PWSTR / PSTR        c_wchar_p / c_char_p, which ctypes handles better
    per architecture    a few hundred names have one definition per CPU, marked
                        with SupportedArchitectureAttribute; --architecture picks
                        which, and defaults to the one this process runs on

The DLLs are loaded when the generated module is imported. A whole namespace
generated with --namespace can name DLLs that are not installed (dxcompiler.dll,
say) or functions the installed version does not export, and then the import
fails; generating the functions actually needed with --function avoids that.
"""

import argparse
import glob
import keyword
import os
import platform
import re
import sys
from collections import namedtuple

from winmd.reader import (
    CallConv,
    ElementType,
    MemberForwarded,
    TypeDefOrRef,
    TypeLayout,
    cache,
    category,
    coded_index_TypeDefOrRef,
    find,
    get_attribute,
    get_category,
    get_type_namespace_and_name,
)

METADATA = "Windows.Win32.Foundation.Metadata"

# Win32 metadata defines a name more than once where it differs by architecture,
# marking each with SupportedArchitectureAttribute: CONTEXT and the rest of the
# unwinding family have one definition per CPU. Filtering to one leaves exactly
# one of every name, and never two.
#
# It goes in two places, because a type and a method are reached differently. A
# type is pointed at - a field of PSS_THREAD_ENTRY is a CONTEXT - so it has to
# go where a name is resolved, which is the cache's index. A method is never
# pointed at, only listed, so it is filtered there.
X86, X64, ARM64 = 1, 2, 4  # Architecture, in the metadata's own enum
ARCHITECTURES = {"x86": X86, "x64": X64, "arm64": ARM64}
NATIVE = ARM64 if platform.machine().upper().startswith(("ARM", "AARCH")) else X64


def supports(row, architecture):
    """Whether a type or a method is for that architecture.

    A row with no attribute is for all of them, which is all but a few hundred.
    """
    attribute = get_attribute(row, METADATA, "SupportedArchitectureAttribute")
    if not attribute:
        return True
    return bool(int(attribute.Value().FixedArgs()[0].value.value.value) & architecture)


def functions_of(apis, architecture):
    """The methods of an Apis class that are for that architecture."""
    return [method for method in apis.MethodList() if supports(method, architecture)]


def array_length(sig, count=None):
    """How many elements a fixed size array field holds, if it says.

    Win32 metadata writes nearly all of them as ELEMENT_TYPE_ARRAY with a shape
    - `WCHAR DeviceName[32]` is rank 1 with one size - and a handful as an
    SZARRAY carrying NativeArrayInfoAttribute, which is where `count` comes
    from. Neither appears with the other, and none of the shapes has a rank
    above one.
    """
    sizes = sig.array_sizes() if sig.is_array() else []
    return sizes[0] if sizes else count


# Where the Win32 metadata is when nothing names it: what scripts/fetch-vendor.ps1
# installs, in the repository this example lives in.
REPOSITORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_METADATA = os.path.join(
    "vendor", "Microsoft.Windows.SDK.Win32Metadata", "*.winmd"
)

PRIMITIVES = {
    ElementType.Boolean: "c_bool",
    ElementType.Char: "c_wchar",
    ElementType.I1: "c_int8",
    ElementType.U1: "c_uint8",
    ElementType.I2: "c_int16",
    ElementType.U2: "c_uint16",
    ElementType.I4: "c_int32",
    ElementType.U4: "c_uint32",
    ElementType.I8: "c_int64",
    ElementType.U8: "c_uint64",
    ElementType.R4: "c_float",
    ElementType.R8: "c_double",
    ElementType.I: "c_ssize_t",
    ElementType.U: "c_size_t",
    ElementType.String: "c_wchar_p",
    ElementType.Object: "c_void_p",
    ElementType.Void: "None",
}

# Types that ctypes already models better than their metadata definition.
OVERRIDES = {
    ("Windows.Win32.Foundation", "PWSTR"): "c_wchar_p",
    ("Windows.Win32.Foundation", "PCWSTR"): "c_wchar_p",
    ("Windows.Win32.Foundation", "PSTR"): "c_char_p",
    ("Windows.Win32.Foundation", "PCSTR"): "c_char_p",
    ("Windows.Win32.Foundation", "BSTR"): "c_wchar_p",
    ("System", "Guid"): "GUID",
}

GUID_DEFINITION = '''class GUID(Structure):
    """System.Guid / REFIID"""

    _fields_ = [
        ("Data1", c_uint32),
        ("Data2", c_uint16),
        ("Data3", c_uint16),
        ("Data4", c_uint8 * 8),
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
'''

# A COM interface pointer plus the vtable dispatch its methods are bound to.
COM_RUNTIME = '''
# --- COM support
class _Interface(c_void_p):
    """A COM interface pointer; methods are called through the vtable."""

    _iid_ = None

    def __repr__(self):
        return f"<{type(self).__name__} at {self.value and hex(self.value)}>"


def _com_method(name, index, restype, argtypes):
    """Binds slot `index` of the vtable (`this` is passed implicitly)."""
    prototype = WINFUNCTYPE(restype, c_void_p, *argtypes)

    def call(self, *arguments):
        if not self.value:
            raise ValueError(f"{type(self).__name__}.{name} on a null interface")
        vtable = ctypes.cast(self, POINTER(POINTER(c_void_p)))
        return prototype(vtable[0][index])(self, *arguments)

    call.__name__ = name
    call.__qualname__ = name
    return call
'''

Record = namedtuple("Record", "name keyword fields packing anonymous embedded")
Interface = namedtuple("Interface", "name base iid methods")


def elem_value(value):
    while hasattr(value, "value"):
        value = value.value
    return value


def attribute_args(attribute):
    """(fixed, named) arguments of a custom attribute, ([], {}) if undecodable.

    Decoding an argument whose type is an enum from an assembly that is not in
    the cache (mscorlib, for instance) raises, exactly like the C++ reader.
    """
    try:
        signature = attribute.Value()
    except ValueError:
        return [], {}
    fixed = [elem_value(arg) for arg in signature.FixedArgs()]
    named = {arg.name: elem_value(arg.value) for arg in signature.NamedArgs()}
    return fixed, named


def identifier(name):
    name = re.sub(r"\W", "_", name)
    if keyword.iskeyword(name) or not name or name[0].isdigit():
        name = "_" + name
    return name


class Generator:
    def __init__(self, db):
        self.cache = db
        self.names = {}  # TypeDef -> python identifier
        self.taken = set()
        self.aliases = []  # (name, expression)
        self.enums = []  # (name, underlying, [(field, value)], is_flags)
        self.records = []  # (name, keyword, fields, packing, anonymous)
        self.callbacks = []  # (name, expression)
        self.interfaces = []  # Interface(name, base, iid, methods)
        self.functions = []  # (name, dll, entry, restype, argtypes, flags)
        self.needs_guid = False
        self.comments = []
        self._imports = {
            database.path(): self._read_imports(database) for database in db.databases()
        }
        self._pending = []

    # --- ImplMap -------------------------------------------------------------
    @staticmethod
    def _read_imports(database):
        """{MethodDef row index: (dll, entry point, flags)} from ImplMap."""
        imports = {}
        for row in database.ImplMap:
            member = row.MemberForwarded()
            if member.type() is MemberForwarded.MethodDef:
                imports[member.MethodDef().index()] = (
                    row.ImportScope().Name(),
                    row.ImportName(),
                    row.MappingFlags(),
                )
        return imports

    def import_of(self, method):
        return self._imports[method.get_database().path()].get(method.index())

    # --- names ---------------------------------------------------------------
    def unique(self, name):
        name = identifier(name)
        candidate, index = name, 1
        while candidate in self.taken:
            index += 1
            candidate = f"{name}{index}"
        self.taken.add(candidate)
        return candidate

    # --- type expressions ----------------------------------------------------
    def type_expression(self, sig, count=None):
        """The ctypes expression for a TypeSig."""
        inner = self.element_expression(sig.Type())
        for _ in range(sig.ptr_count()):
            inner = "c_void_p" if inner == "None" else f"POINTER({inner})"
        if sig.is_szarray() or sig.is_array():
            count = array_length(sig, count)
            inner = f"({inner} * {count})" if count else f"POINTER({inner})"
        return inner

    def element_expression(self, value):
        if isinstance(value, ElementType):
            return PRIMITIVES.get(value, "c_void_p")
        if isinstance(value, coded_index_TypeDefOrRef):
            if value.type() is TypeDefOrRef.TypeSpec:
                return "c_void_p"  # generics do not exist in the Win32 metadata
            namespace, name = get_type_namespace_and_name(value)
            override = OVERRIDES.get((namespace, name))
            if override:
                if override == "GUID":
                    self.needs_guid = True
                return override
            definition = find(value) if value else None
            if definition:
                return self.declare(definition)
            self.comments.append(f"unresolved type {namespace}.{name} -> c_void_p")
            return "c_void_p"
        return "c_void_p"

    @staticmethod
    def array_count(row):
        attribute = get_attribute(row, METADATA, "NativeArrayInfoAttribute")
        if attribute:
            _, named = attribute_args(attribute)
            return named.get("CountConst")
        return None

    # --- declarations --------------------------------------------------------
    def declare(self, type):
        """Emits `type` (and everything it needs) once, returns its name."""
        if type in self.names:
            return self.names[type]

        namespace, name = type.TypeNamespace(), type.TypeName()
        override = OVERRIDES.get((namespace, name))
        if override:
            if override == "GUID":
                self.needs_guid = True
            self.names[type] = override
            return override

        kind = get_category(type)
        python_name = self.unique(name)

        if kind == category.interface_type:
            self.names[type] = python_name
            self.declare_interface(type, python_name)
            return python_name

        self.names[type] = python_name  # registered first: the metadata has cycles

        if kind == category.enum_type:
            # The IntEnum class carries the values, but ctypes needs the
            # underlying integer type in argtypes/_fields_.
            underlying = self.declare_enum(type, python_name)
            self.names[type] = underlying
            return underlying
        if kind == category.delegate_type:
            self.declare_callback(type, python_name)
        elif kind == category.struct_type:
            if get_attribute(type, METADATA, "NativeTypedefAttribute"):
                inner = next(iter(type.FieldList()))
                self.aliases.append(
                    (
                        python_name,
                        self.type_expression(inner.Signature().Type()),
                    )
                )
            else:
                self.declare_record(type, python_name)
        else:
            self.aliases.append((python_name, "c_void_p"))
        return python_name

    def declare_enum(self, type, python_name):
        definition = type.get_enum_definition()
        underlying = PRIMITIVES.get(definition.m_underlying_type, "c_int32")
        values = []
        for field in type.FieldList():
            if not field.Flags().Literal():
                continue
            name = identifier(field.Name())
            # A leading double underscore would be name mangled inside the class
            # body, so the member is renamed and aliased under its real name.
            member = name.lstrip("_") if name.startswith("__") else name
            values.append((member or "value", name, field.Constant().Value()))
        flags = bool(get_attribute(type, "System", "FlagsAttribute"))
        self.enums.append((python_name, underlying, values, flags))
        return underlying

    def declare_record(self, type, python_name):
        for inner in self.cache.nested_types(type):
            if inner in self.names:
                continue  # already emitted through a field reference
            inner_name = self.unique(f"{python_name}_{inner.TypeName().lstrip('_')}")
            self.names[inner] = inner_name
            self.declare_nested(inner, inner_name)

        fields, anonymous, embedded = [], [], set()
        for field in type.FieldList():
            signature = field.Signature().Type()
            expression = self.type_expression(signature, self.array_count(field))
            fields.append((identifier(field.Name()), expression))
            if field.Name().startswith("Anonymous"):
                anonymous.append(identifier(field.Name()))
            # A field held by value needs its layout before this one is set.
            embedded.add(re.sub(r"^\((\w+) \* \d+\)$", r"\1", expression))

        keyword_ = (
            "Union"
            if type.Flags().Layout() == TypeLayout.ExplicitLayout
            else "Structure"
        )
        layout = next(
            (row for row in type.get_database().ClassLayout if row.Parent() == type),
            None,
        )
        packing = layout.PackingSize() if layout else 0
        self.records.append(
            Record(python_name, keyword_, fields, packing, anonymous, embedded)
        )

    def declare_nested(self, type, python_name):
        if get_category(type) == category.enum_type:
            self.declare_enum(type, python_name)
        else:
            self.declare_record(type, python_name)

    @staticmethod
    def base_interface(type):
        """The interface a COM interface derives from, if any."""
        for impl in type.InterfaceImpl():
            base = find(impl.Interface())
            if base:
                return base
        return None

    def vtable_size(self, type):
        """How many slots the interface occupies, its bases included."""
        base = self.base_interface(type)
        return (self.vtable_size(base) if base else 0) + len(type.MethodList())

    def declare_interface(self, type, python_name):
        base = self.base_interface(type)
        base_name = self.declare(base) if base else None
        slot = self.vtable_size(base) if base else 0

        iid = None
        guid = get_attribute(type, METADATA, "GuidAttribute")
        if guid:
            args, _ = attribute_args(guid)
            if len(args) == 11:
                self.needs_guid = True
                iid = "{{{:08x}-{:04x}-{:04x}-{}-{}}}".format(
                    args[0],
                    args[1],
                    args[2],
                    "".join(f"{b:02x}" for b in args[3:5]),
                    "".join(f"{b:02x}" for b in args[5:]),
                )

        # Registered before the methods are parsed: a method signature can
        # mention an interface that derives from this one.
        methods = []
        self.interfaces.append(Interface(python_name, base_name, iid, methods))

        for method in type.MethodList():
            signature = method.Signature()
            restype = (
                self.type_expression(signature.ReturnType().Type())
                if signature.ReturnType()
                else "None"
            )
            rows = {p.Sequence(): p for p in method.ParamList()}
            argtypes = [
                self.type_expression(param.Type(), self.array_count(rows.get(index)))
                for index, param in enumerate(signature.Params(), start=1)
            ]
            methods.append((identifier(method.Name()), slot, restype, argtypes))
            slot += 1

    def declare_callback(self, type, python_name):
        invoke = next((m for m in type.MethodList() if m.Name() == "Invoke"), None)
        if invoke is None:
            self.aliases.append((python_name, "c_void_p"))
            return
        signature = invoke.Signature()
        restype = (
            self.type_expression(signature.ReturnType().Type())
            if signature.ReturnType()
            else "None"
        )
        argtypes = [self.type_expression(p.Type()) for p in signature.Params()]
        attribute = get_attribute(
            type,
            "System.Runtime.InteropServices",
            "UnmanagedFunctionPointerAttribute",
        )
        factory = "CFUNCTYPE" if self._is_cdecl_attribute(attribute) else "WINFUNCTYPE"
        self.callbacks.append(
            (python_name, f"{factory}({', '.join([restype] + argtypes)})")
        )

    @staticmethod
    def _is_cdecl_attribute(attribute):
        if not attribute:
            return False
        args, _ = attribute_args(attribute)
        return bool(args) and args[0] == 2  # CallingConvention.Cdecl

    def declare_function(self, method):
        entry = self.import_of(method)
        if entry is None:
            return False
        dll, symbol, flags = entry
        if not dll:
            return False

        signature = method.Signature()
        restype = (
            self.type_expression(signature.ReturnType().Type())
            if signature.ReturnType()
            else "None"
        )
        rows = {p.Sequence(): p for p in method.ParamList()}
        argtypes = [
            self.type_expression(param.Type(), self.array_count(rows.get(index)))
            for index, param in enumerate(signature.Params(), start=1)
        ]
        self.functions.append(
            (identifier(method.Name()), dll, symbol, restype, argtypes, flags)
        )
        return True

    def declare_constant(self, field):
        if field.Flags().Literal():
            value = field.Constant().Value()
            self.aliases.append((identifier(field.Name()), repr(value)))
            return True
        guid = get_attribute(field, METADATA, "GuidAttribute")
        if guid:
            args, _ = attribute_args(guid)
            if len(args) == 11:
                self.needs_guid = True
                text = "{{{:08x}-{:04x}-{:04x}-{}-{}}}".format(
                    args[0],
                    args[1],
                    args[2],
                    "".join(f"{b:02x}" for b in args[3:5]),
                    "".join(f"{b:02x}" for b in args[5:]),
                )
                self.aliases.append((identifier(field.Name()), f'GUID("{text}")'))
                return True
        constant = get_attribute(field, METADATA, "ConstantAttribute")
        if constant:
            args, _ = attribute_args(constant)
            self.aliases.append((identifier(field.Name()), repr(args[0])))
            return True
        return False

    # --- rendering -----------------------------------------------------------
    def render(self, source):
        out = []
        out.append('"""Generated from the Win32 metadata by examples/ctypes_gen.py.')
        out.append("")
        out.append(f"source: {source}")
        out.append('"""')
        out.append("")
        out.append("import ctypes")
        out.append("from ctypes import (")
        out.append(
            "    CFUNCTYPE, POINTER, Structure, Union, WINFUNCTYPE, c_bool, c_char_p,"
        )
        out.append(
            "    c_double, c_float, c_int8, c_int16, c_int32, c_int64, c_size_t,"
        )
        out.append(
            "    c_ssize_t, c_uint8, c_uint16, c_uint32, c_uint64, c_void_p, c_wchar,"
        )
        out.append("    c_wchar_p,")
        out.append(")")
        if self.enums:
            out.append("from enum import IntEnum, IntFlag")
        out.append("")
        for comment in dict.fromkeys(self.comments):
            out.append(f"# {comment}")
        if self.comments:
            out.append("")

        if self.needs_guid:
            out.append("")
            out.append(GUID_DEFINITION)

        if self.interfaces:
            out.append(COM_RUNTIME)

        if self.aliases:
            out.append("")
            out.append("# --- typedefs and constants")
            for name, expression in self.aliases:
                out.append(f"{name} = {expression}")

        for name, underlying, values, flags in self.enums:
            out.append("")
            out.append(f"class {name}({'IntFlag' if flags else 'IntEnum'}):")
            out.append(f"    # native type: {underlying}")
            for member, _, value in values:
                out.append(f"    {member} = {value!r}")
            if not values:
                out.append("    pass")
            out.append("")
            for member, original, _ in values:
                out.append(f"{original} = {name}.{member}")

        if self.records:
            out.append("")
            out.append(
                "# --- structs and unions (declared first: the metadata has cycles)"
            )
            for record in self.records:
                out.append(f"class {record.name}({record.keyword}):")
                out.append("    pass")
                out.append("")

        if self.interfaces:
            out.append("# --- COM interfaces (bases first)")
            for interface in self.sorted_interfaces():
                out.append(f"class {interface.name}({interface.base or '_Interface'}):")
                if interface.iid:
                    out.append(f'    _iid_ = GUID("{interface.iid}")')
                else:
                    out.append("    pass")
                out.append("")

        # Callbacks come between the class statements and the field lists: they
        # may take structs, and structs may have callback members.
        if self.callbacks:
            out.append("# --- callbacks")
            for name, expression in self.callbacks:
                out.append(f"{name} = {expression}")
            out.append("")

        for record in self.sorted_records():
            if record.packing:
                out.append(f"{record.name}._pack_ = {record.packing}")
            if record.anonymous:
                out.append(f"{record.name}._anonymous_ = {tuple(record.anonymous)!r}")
            out.append(f"{record.name}._fields_ = [")
            for field, expression in record.fields:
                out.append(f'    ("{field}", {expression}),')
            out.append("]")
            out.append("")

        if self.interfaces:
            out.append(
                "# --- COM methods (assigned after the classes:"
                " signatures may be circular)"
            )
            for interface in self.interfaces:
                for name, slot, restype, argtypes in interface.methods:
                    out.append(
                        f"{interface.name}.{name} = _com_method("
                        f'"{name}", {slot}, {restype}, '
                        f"[{', '.join(argtypes)}])"
                    )
            out.append("")

        if self.functions:
            out.append("# --- libraries")
            libraries = {}
            for _, dll, _, _, _, flags in self.functions:
                key = (dll, flags.CallConv(), flags.SupportsLastError())
                if key not in libraries:
                    # The same DLL can need several handles: SetLastError and the
                    # calling convention are per function.
                    name = "_" + dll.split(".")[0].lower()
                    if key[1] is CallConv.CallConvCdecl:
                        name += "_cdecl"
                    if key[2]:
                        name += "_lasterror"
                    libraries[key] = self.unique(name)
            for (dll, convention, last_error), variable in libraries.items():
                loader = "CDLL" if convention is CallConv.CallConvCdecl else "WinDLL"
                arguments = f'"{dll}"'
                if last_error:
                    arguments += ", use_last_error=True"
                out.append(f"{variable} = ctypes.{loader}({arguments})")
            out.append("")

            out.append("# --- functions")
            for name, dll, symbol, restype, argtypes, flags in self.functions:
                variable = libraries[(dll, flags.CallConv(), flags.SupportsLastError())]
                out.append(f'{name} = {variable}["{symbol}"]')
                out.append(f"{name}.restype = {restype}")
                out.append(f"{name}.argtypes = [{', '.join(argtypes)}]")
                out.append("")

        return "\n".join(out) + "\n"

    def sorted_interfaces(self):
        """Interfaces ordered so that a base class is always defined first.

        Declaration order is not enough: an interface method can mention a type
        that derives from the interface being declared.
        """
        by_name = {interface.name: interface for interface in self.interfaces}
        order, state = [], {}

        def visit(name):
            interface = by_name.get(name)
            if interface is None or state.get(name):
                return
            state[name] = 1
            visit(interface.base)
            state[name] = 2
            order.append(interface)

        for interface in self.interfaces:
            visit(interface.name)
        return order

    def sorted_records(self):
        """Records ordered so that a struct held by value is complete first."""
        by_name = {record.name: record for record in self.records}
        order, state = [], {}

        def visit(name):
            if state.get(name) or name not in by_name:
                return
            state[name] = 1
            for dependency in by_name[name].embedded:
                if dependency != name:
                    visit(dependency)
            state[name] = 2
            order.append(by_name[name])

        for record in self.records:
            visit(record.name)
        return order


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "files",
        nargs="*",
        help=f"Win32 .winmd files (default: {DEFAULT_METADATA})",
    )
    parser.add_argument(
        "--function",
        action="append",
        default=[],
        help="function name (repeatable)",
    )
    parser.add_argument(
        "--type", action="append", default=[], help="type name (repeatable)"
    )
    parser.add_argument(
        "--constant",
        action="append",
        default=[],
        help="constant name (repeatable)",
    )
    parser.add_argument("--namespace", help="take everything from this namespace")
    parser.add_argument(
        "--architecture",
        choices=sorted(ARCHITECTURES),
        default="arm64" if NATIVE == ARM64 else "x64",
        help="which definition to take where a name has one per CPU",
    )
    parser.add_argument("-o", "--output", help="write to this file instead of stdout")
    args = parser.parse_args(argv)

    patterns = args.files or [os.path.join(REPOSITORY, DEFAULT_METADATA)]
    files = sorted({path for pattern in patterns for path in glob.glob(pattern)})
    if not files:
        parser.error(
            f"no .winmd file found - name one, or put the Win32 metadata "
            f"in {DEFAULT_METADATA} (scripts/fetch-vendor.ps1 does)"
        )
    if not (args.function or args.type or args.constant or args.namespace):
        parser.error(
            "nothing selected: pass --function/--type/--constant or --namespace"
        )

    architecture = ARCHITECTURES[args.architecture]
    db = cache(files, lambda type: supports(type, architecture))
    generator = Generator(db)

    namespaces = [
        (name, members)
        for name, members in db.namespaces().items()
        if name.startswith("Windows.Win32")
        and (args.namespace is None or args.namespace.lower() in name.lower())
    ]

    wanted_functions = set(args.function)
    wanted_types = set(args.type)
    wanted_constants = set(args.constant)
    found_functions, found_types, found_constants = set(), set(), set()

    for name, members in namespaces:
        take_all = args.namespace is not None
        apis = members.types.get("Apis")
        if apis:
            for method in functions_of(apis, architecture):
                if take_all or method.Name() in wanted_functions:
                    if generator.declare_function(method):
                        found_functions.add(method.Name())
            for field in apis.FieldList():
                if take_all or field.Name() in wanted_constants:
                    if generator.declare_constant(field):
                        found_constants.add(field.Name())
        for type_name, type in members.types.items():
            if type_name == "Apis":
                continue
            if take_all or type_name in wanted_types:
                generator.declare(type)
                found_types.add(type_name)

    for missing in sorted(wanted_functions - found_functions):
        print(f"warning: function '{missing}' not found", file=sys.stderr)
    for missing in sorted(wanted_types - found_types):
        print(f"warning: type '{missing}' not found", file=sys.stderr)
    for missing in sorted(wanted_constants - found_constants):
        print(f"warning: constant '{missing}' not found", file=sys.stderr)

    source = args.namespace or ", ".join(
        sorted(found_functions | found_types | found_constants)
    )
    text = generator.render(source or "nothing")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            file.write(text)
        print(
            f"{args.output}: {len(generator.functions)} functions, "
            f"{len(generator.records)} structs, {len(generator.enums)} enums, "
            f"{len(generator.callbacks)} callbacks, "
            f"{len(generator.interfaces)} interfaces",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
