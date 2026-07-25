"""Generates ready to use ctypes declarations from the Win32 metadata.

    python examples/ctypes_gen.py --function MessageBoxW --function GetSystemMetrics
    python examples/ctypes_gen.py --namespace Windows.Win32.UI.WindowsAndMessaging -o user32.py
    python examples/ctypes_gen.py --function "CreateFileW" --type OVERLAPPED

Everything a selected function or type needs (structs, unions, typedefs, enums,
callbacks) is pulled in recursively, so the generated module imports and runs on
its own:

    import ctypes
    from generated import MessageBoxW, MB_ICONINFORMATION
    MessageBoxW(None, "hello", "winmd", MB_ICONINFORMATION)

COM interfaces are emitted as c_void_p; use comtypes or pywin32 for those.
"""

import argparse
import glob
import keyword
import os
import re
import sys
from collections import namedtuple

Record = namedtuple("Record", "name keyword fields packing anonymous embedded")

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
    get_type_namespace_and_name,
)

METADATA = "Windows.Win32.Foundation.Metadata"

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

# PInvokeAttributes (ECMA-335 II.23.1.8)
CALL_CONV_MASK = 0x0700
CALL_CONV_CDECL = 0x0200
SUPPORTS_LAST_ERROR = 0x0040

# Functions are bound on first use: a namespace can name DLLs that are not
# installed, and loading every one of them up front would fail the import.
LOADER = '''
# --- function loader
_libraries = {}


def _library(dll, flags):
    library = _libraries.get((dll, flags))
    if library is None:
        loader = ctypes.CDLL if (flags & 0x700) == 0x200 else ctypes.WinDLL
        library = loader(dll, use_last_error=bool(flags & 0x40))
        _libraries[dll, flags] = library
    return library


def __getattr__(name):
    """Binds a function the first time it is used (PEP 562)."""
    try:
        dll, flags, symbol, restype, argtypes = _prototypes[name]
    except KeyError:
        raise AttributeError(name) from None
    function = _library(dll, flags)[symbol]
    function.restype = restype
    function.argtypes = argtypes
    globals()[name] = function
    return function


def __dir__():
    return sorted(set(globals()) | set(_prototypes))
'''


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
        self.names = {}            # TypeDef -> python identifier
        self.taken = set()
        self.aliases = []          # (name, expression)
        self.enums = []            # (name, underlying, [(field, value)], is_flags)
        self.records = []          # (name, keyword, fields, packing, anonymous)
        self.callbacks = []        # (name, expression)
        self.functions = []        # (name, dll, entry, restype, argtypes, flags)
        self.needs_guid = False
        self.comments = []
        self._imports = {
            database.path(): self._read_imports(database)
            for database in db.databases()
        }
        self._pending = []

    # --- ImplMap -------------------------------------------------------------
    @staticmethod
    def _read_imports(database):
        modules = [database.get_string(row.get_value(0)) for row in database.ModuleRef]
        imports = {}
        for row in database.ImplMap:
            member = row.get_value(1)
            if member & 1:  # MemberForwarded: 1 == MethodDef
                scope = row.get_value(3)
                imports[(member >> 1) - 1] = (
                    modules[scope - 1] if 0 < scope <= len(modules) else None,
                    database.get_string(row.get_value(2)),
                    row.get_value(0),  # MappingFlags
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
            inner = f"({inner} * {count})" if count else f"POINTER({inner})"
        return inner

    def element_expression(self, value):
        if isinstance(value, ElementType):
            return PRIMITIVES.get(value, "c_void_p")
        if isinstance(value, coded_index_TypeDefOrRef):
            if value.type() == TypeDefOrRef.TypeSpec:
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
        if kind == category.interface_type:
            # A COM interface is passed around as an opaque pointer.
            self.names[type] = "c_void_p"
            return "c_void_p"

        python_name = self.unique(name)
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
                self.aliases.append((python_name, self.type_expression(inner.Signature().Type())))
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

        keyword_ = "Union" if type.Flags().Layout() == TypeLayout.ExplicitLayout else "Structure"
        layout = next(
            (row for row in type.get_database().ClassLayout if row.Parent() == type), None
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
            type, "System.Runtime.InteropServices", "UnmanagedFunctionPointerAttribute"
        )
        factory = "CFUNCTYPE" if self._is_cdecl_attribute(attribute) else "WINFUNCTYPE"
        self.callbacks.append((python_name, f"{factory}({', '.join([restype] + argtypes)})"))

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
        out.append("    CFUNCTYPE, POINTER, Structure, Union, WINFUNCTYPE, c_bool, c_char_p,")
        out.append("    c_double, c_float, c_int8, c_int16, c_int32, c_int64, c_size_t,")
        out.append("    c_ssize_t, c_uint8, c_uint16, c_uint32, c_uint64, c_void_p, c_wchar,")
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
            out.append("# --- structs and unions (declared first: the metadata has cycles)")
            for record in self.records:
                out.append(f"class {record.name}({record.keyword}):")
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

        if self.functions:
            out.append(LOADER)
            out.append("")
            out.append("# --- functions: (dll, PInvoke flags, entry point, restype, argtypes)")
            out.append("_prototypes = {")
            for name, dll, symbol, restype, argtypes, flags in self.functions:
                out.append(
                    f'    "{name}": ("{dll}", {hex(flags)}, "{symbol}", {restype}, '
                    f"[{', '.join(argtypes)}]),"
                )
            out.append("}")

        return "\n".join(out) + "\n"

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
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Win32 .winmd files (default: metadata/Microsoft.Windows.SDK.Win32Metadata/*.winmd)",
    )
    parser.add_argument("--function", action="append", default=[], help="function name (repeatable)")
    parser.add_argument("--type", action="append", default=[], help="type name (repeatable)")
    parser.add_argument("--constant", action="append", default=[], help="constant name (repeatable)")
    parser.add_argument("--namespace", help="take everything from this namespace")
    parser.add_argument("-o", "--output", help="write to this file instead of stdout")
    args = parser.parse_args(argv)

    patterns = args.files or [
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "metadata",
            "Microsoft.Windows.SDK.Win32Metadata",
            "*.winmd",
        )
    ]
    files = sorted({path for pattern in patterns for path in glob.glob(pattern)})
    if not files:
        parser.error("no .winmd file found - run fetch-packages.ps1 -Kind metadata")
    if not (args.function or args.type or args.constant or args.namespace):
        parser.error("nothing selected: pass --function/--type/--constant or --namespace")

    db = cache(files)
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
            for method in apis.MethodList():
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
            f"{len(generator.callbacks)} callbacks",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
