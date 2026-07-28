"""Dumps Win32 API signatures from the Win32 metadata (Windows.Win32.winmd).

    python examples/dumpwin32.py --list
    python examples/dumpwin32.py --namespace Windows.Win32.UI.WindowsAndMessaging
    python examples/dumpwin32.py --search CreateWindow
    python examples/dumpwin32.py --search MSG --kind struct

Everything is read through the winmd bindings: functions come from the static
`Apis` class of each namespace (the DLL and entry point are looked up in the
ImplMap table), structs/enums/callbacks/COM interfaces from the type
definitions, and constants from the literal fields of `Apis`.
"""

import argparse
import glob
import os
import re
import sys

from winmd.reader import (
    ElementType,
    GenericMethodTypeIndex,
    GenericTypeIndex,
    GenericTypeInstSig,
    TypeDefOrRef,
    TypeLayout,
    cache,
    category,
    coded_index_TypeDefOrRef,
    get_attribute,
    get_category,
    get_type_namespace_and_name,
)

METADATA = "Windows.Win32.Foundation.Metadata"

# ELEMENT_TYPE_* as it is spelled in the Windows headers.
PRIMITIVES = {
    ElementType.Void: "void",
    ElementType.Boolean: "bool",
    ElementType.Char: "char16",
    ElementType.I1: "sbyte",
    ElementType.U1: "byte",
    ElementType.I2: "short",
    ElementType.U2: "ushort",
    ElementType.I4: "int",
    ElementType.U4: "uint",
    ElementType.I8: "long",
    ElementType.U8: "ulong",
    ElementType.R4: "float",
    ElementType.R8: "double",
    ElementType.String: "string",
    ElementType.Object: "object",
    ElementType.I: "nint",
    ElementType.U: "nuint",
}


def elem_value(value):
    """Unwraps ElemSig / FixedArgSig values of a custom attribute argument."""
    for attribute in ("value",):
        while hasattr(value, attribute):
            value = getattr(value, attribute)
    return value


def attribute_args(attribute):
    fixed = [elem_value(arg) for arg in attribute.Value().FixedArgs()]
    named = {arg.name: elem_value(arg.value) for arg in attribute.Value().NamedArgs()}
    return fixed, named


def format_guid(attribute):
    args, _ = attribute_args(attribute)
    if len(args) != 11:
        return None
    return "{:08x}-{:04x}-{:04x}-{}-{}".format(
        args[0],
        args[1],
        args[2],
        "".join(f"{b:02x}" for b in args[3:5]),
        "".join(f"{b:02x}" for b in args[5:]),
    )


def format_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return hex(value) if abs(value) > 9 else str(value)
    if isinstance(value, str):
        return f'"{value}"'
    if value is None:
        return "null"
    return str(value)


class Win32Dumper:
    def __init__(self, db, qualified=False):
        self.cache = db
        self.qualified = qualified
        self._imports = {}
        for database in db.databases():
            self._imports[database.path()] = self._read_imports(database)

    # --- ImplMap: the DLL and entry point of a P/Invoke ----------------------
    @staticmethod
    def _read_imports(database):
        """{MethodDef row index: (dll, entry point)} from the ImplMap table."""
        modules = [
            database.get_string(row.get_value(0)) for row in database.ModuleRef
        ]
        imports = {}
        for row in database.ImplMap:
            member = row.get_value(1)  # MemberForwarded: 1 bit tag, 1 == MethodDef
            if member & 1:
                scope = row.get_value(3)
                imports[(member >> 1) - 1] = (
                    modules[scope - 1] if 0 < scope <= len(modules) else "?",
                    database.get_string(row.get_value(2)),
                )
        return imports

    def imported_from(self, method):
        entry = self._imports[method.get_database().path()].get(method.index())
        if entry is None:
            return None
        dll, name = entry
        return dll if name == method.Name() else f"{dll}!{name}"

    # --- type names ----------------------------------------------------------
    def type_name(self, value):
        """Formats the value of TypeSig.Type() / a coded_index."""
        if isinstance(value, ElementType):
            return PRIMITIVES.get(value, str(value))
        if isinstance(value, coded_index_TypeDefOrRef):
            if value.type() == TypeDefOrRef.TypeSpec:
                return self.type_name(value.TypeSpec().Signature().GenericTypeInst())
            namespace, name = get_type_namespace_and_name(value)
            return f"{namespace}.{name}" if self.qualified else name
        if isinstance(value, GenericTypeInstSig):
            namespace, name = get_type_namespace_and_name(value.GenericType())
            arguments = ", ".join(self.type_name(a.Type()) for a in value.GenericArgs())
            name = f"{namespace}.{name}" if self.qualified else name
            return f"{name.split('`')[0]}<{arguments}>"
        if isinstance(value, GenericTypeIndex):
            return f"T{value.index}"
        if isinstance(value, GenericMethodTypeIndex):
            return f"M{value.index}"
        return str(value)

    def signature_name(self, sig, count=None):
        name = self.type_name(sig.Type()) + "*" * sig.ptr_count()
        if sig.is_szarray():
            name += f"[{count}]" if count else "[]"
        elif sig.is_array():
            name += "[" + "," * max(sig.array_rank() - 1, 0) + "]"
        return name

    @staticmethod
    def array_count(row):
        """The fixed element count of a NativeArrayInfoAttribute, if any."""
        attribute = get_attribute(row, METADATA, "NativeArrayInfoAttribute")
        if attribute:
            _, named = attribute_args(attribute)
            return named.get("CountConst")
        return None

    # --- declarations --------------------------------------------------------
    def function(self, method):
        signature = method.Signature()
        returns = (
            self.signature_name(signature.ReturnType().Type())
            if signature.ReturnType()
            else "void"
        )
        names = {p.Sequence(): p for p in method.ParamList()}
        parameters = []
        for index, param in enumerate(signature.Params(), start=1):
            row = names.get(index)
            annotations = []
            count = None
            name = f"param{index}"
            if row is not None:
                name = row.Name() or name
                count = self.array_count(row)
                if row.Flags().In():
                    annotations.append("in")
                if row.Flags().Out():
                    annotations.append("out")
                if row.Flags().Optional():
                    annotations.append("opt")
            prefix = f"[{', '.join(annotations)}] " if annotations else ""
            parameters.append(f"{prefix}{self.signature_name(param.Type(), count)} {name}")
        declaration = f"{returns} {method.Name()}({', '.join(parameters)});"
        origin = self.imported_from(method)
        return f"{declaration:<100} // {origin}" if origin else declaration

    def field(self, field, indent="    "):
        count = self.array_count(field)
        return f"{indent}{self.signature_name(field.Signature().Type(), count)} {field.Name()};"

    def struct(self, type, indent="", seen=None):
        seen = seen if seen is not None else set()
        seen.add(type)

        typedef = get_attribute(type, METADATA, "NativeTypedefAttribute")
        if typedef:
            inner = next(iter(type.FieldList()))
            return (
                f"{indent}typedef {self.signature_name(inner.Signature().Type())} "
                f"{type.TypeName()};"
            )

        keyword = "union" if type.Flags().Layout() == TypeLayout.ExplicitLayout else "struct"
        lines = [f"{indent}{keyword} {type.TypeName()} {{"]
        for nested in self.cache.nested_types(type):
            if nested not in seen:
                lines.append(self.struct(nested, indent + "    ", seen))
        for field in type.FieldList():
            lines.append(self.field(field, indent + "    "))
        lines.append(f"{indent}}};")
        return "\n".join(lines)

    def enum(self, type):
        definition = type.get_enum_definition()
        flags = " // [Flags]" if get_attribute(type, "System", "FlagsAttribute") else ""
        underlying = PRIMITIVES.get(definition.m_underlying_type, "int")
        lines = [f"enum {type.TypeName()} : {underlying} {{{flags}"]
        for field in type.FieldList():
            if field.Flags().Literal():
                lines.append(f"    {field.Name()} = {format_value(field.Constant().Value())},")
        lines.append("};")
        return "\n".join(lines)

    def callback(self, type):
        invoke = next((m for m in type.MethodList() if m.Name() == "Invoke"), None)
        if invoke is None:
            return f"typedef {type.TypeName()};"
        signature = invoke.Signature()
        returns = (
            self.signature_name(signature.ReturnType().Type())
            if signature.ReturnType()
            else "void"
        )
        names = {p.Sequence(): p.Name() for p in invoke.ParamList()}
        parameters = ", ".join(
            f"{self.signature_name(p.Type())} {names.get(i, '') or f'param{i}'}".strip()
            for i, p in enumerate(signature.Params(), start=1)
        )
        return f"typedef {returns} (*{type.TypeName()})({parameters});"

    def interface(self, type):
        bases = [
            self.type_name(impl.Interface()) for impl in type.InterfaceImpl()
        ]
        guid = get_attribute(type, METADATA, "GuidAttribute")
        header = f"interface {type.TypeName()}"
        if bases:
            header += " : " + ", ".join(bases)
        if guid:
            header += f" {{ // {{{format_guid(guid)}}}"
        else:
            header += " {"
        lines = [header]
        for method in type.MethodList():
            lines.append("    " + self.function(method))
        lines.append("};")
        return "\n".join(lines)

    def constant(self, field):
        type = self.signature_name(field.Signature().Type())
        if field.Flags().Literal():
            return f"const {type} {field.Name()} = {format_value(field.Constant().Value())};"
        guid = get_attribute(field, METADATA, "GuidAttribute")
        if guid:
            return f"const {type} {field.Name()} = {{{format_guid(guid)}}};"
        constant = get_attribute(field, METADATA, "ConstantAttribute")
        if constant:
            args, _ = attribute_args(constant)
            return f"const {type} {field.Name()} = {args[0]};"
        return f"const {type} {field.Name()};"


def dump_namespace(dumper, name, members, kinds, pattern, out):
    apis = members.types.get("Apis")
    functions = [m for m in apis.MethodList()] if apis else []
    constants = [f for f in apis.FieldList()] if apis else []

    def keep(named):
        return pattern is None or pattern.search(named)

    sections = []
    if "function" in kinds:
        sections.append(
            ("functions", [dumper.function(m) for m in functions if keep(m.Name())])
        )
    if "constant" in kinds:
        sections.append(
            ("constants", [dumper.constant(f) for f in constants if keep(f.Name())])
        )
    if "struct" in kinds:
        sections.append(
            ("structs", [dumper.struct(t) for t in members.structs if keep(t.TypeName())])
        )
    if "enum" in kinds:
        sections.append(("enums", [dumper.enum(t) for t in members.enums if keep(t.TypeName())]))
    if "callback" in kinds:
        sections.append(
            ("callbacks", [dumper.callback(t) for t in members.delegates if keep(t.TypeName())])
        )
    if "interface" in kinds:
        sections.append(
            (
                "COM interfaces",
                [dumper.interface(t) for t in members.interfaces if keep(t.TypeName())],
            )
        )

    if not any(items for _, items in sections):
        return False

    print(f"\n// ===== {name} " + "=" * max(0, 60 - len(name)), file=out)
    for title, items in sections:
        if not items:
            continue
        print(f"\n// --- {title} ({len(items)})\n", file=out)
        for item in items:
            print(item, file=out)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Win32 .winmd files (default: metadata/Microsoft.Windows.SDK.Win32Metadata/*.winmd)",
    )
    parser.add_argument("--namespace", help="dump this namespace (substring match)")
    parser.add_argument("--search", help="only names matching this regular expression")
    parser.add_argument(
        "--kind",
        action="append",
        choices=["function", "struct", "enum", "constant", "callback", "interface"],
        help="what to dump (repeatable, default: everything)",
    )
    parser.add_argument("--list", action="store_true", help="list the namespaces")
    parser.add_argument(
        "--qualified", action="store_true", help="print namespace qualified type names"
    )
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
        parser.error("no .winmd file found - run fetch-metadata.py first")

    db = cache(files)
    namespaces = {
        name: members
        for name, members in db.namespaces().items()
        if name.startswith("Windows.Win32")
        and (args.namespace is None or args.namespace.lower() in name.lower())
    }

    if args.list:
        for name, members in namespaces.items():
            apis = members.types.get("Apis")
            print(
                f"{name}: {len(list(apis.MethodList())) if apis else 0} functions, "
                f"{len(list(apis.FieldList())) if apis else 0} constants, "
                f"{len(members.structs)} structs, {len(members.enums)} enums, "
                f"{len(members.delegates)} callbacks, {len(members.interfaces)} interfaces"
            )
        return 0

    if not namespaces:
        print(f"no namespace matched '{args.namespace}'", file=sys.stderr)
        return 1

    kinds = set(args.kind or ["function", "struct", "enum", "constant", "callback", "interface"])
    pattern = re.compile(args.search, re.IGNORECASE) if args.search else None
    dumper = Win32Dumper(db, qualified=args.qualified)

    found = False
    for name, members in namespaces.items():
        found |= dump_namespace(dumper, name, members, kinds, pattern, sys.stdout)

    if not found:
        print("nothing matched", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
