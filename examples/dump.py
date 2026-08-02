"""Dumps metadata using the winmd bindings.

    python examples/dump.py vendor/Microsoft.Windows.SDK.Contracts/ref/*/*.winmd
    python examples/dump.py --type Windows.Foundation.Uri vendor/**/*.winmd
    python examples/dump.py --namespace Windows.Foundation vendor/**/*.winmd

This mirrors what the same program would look like in C++: build a `cache`,
look types up by namespace/name and walk the rows. It reads any metadata, WinRT
or Win32, and is the only example here that is not Windows only.
"""

import argparse
import glob
import sys

from winmd.reader import (
    ElementType,
    GenericMethodTypeIndex,
    GenericTypeIndex,
    GenericTypeInstSig,
    ParamSig,
    TypeDef,
    TypeDefOrRef,
    cache,
    category,
    coded_index,
    coded_index_TypeDefOrRef,
    get_category,
    get_type_namespace_and_name,
)

PRIMITIVES = {
    ElementType.Boolean: "bool",
    ElementType.Char: "char",
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
    ElementType.Void: "void",
}


def type_name(value):
    """Formats the value of TypeSig.Type()."""
    if isinstance(value, ElementType):
        return PRIMITIVES.get(value, str(value))
    if isinstance(value, coded_index_TypeDefOrRef):
        if value.type() is TypeDefOrRef.TypeSpec:
            return type_name(value.TypeSpec().Signature().GenericTypeInst())
        namespace, name = get_type_namespace_and_name(value)
        return f"{namespace}.{name}"
    if isinstance(value, GenericTypeInstSig):
        namespace, name = get_type_namespace_and_name(value.GenericType())
        arguments = ", ".join(type_name(arg.Type()) for arg in value.GenericArgs())
        return f"{namespace}.{name.split('`')[0]}<{arguments}>"
    if isinstance(value, GenericTypeIndex):
        return f"T{value.index}"
    if isinstance(value, GenericMethodTypeIndex):
        return f"M{value.index}"
    return str(value)


def signature_name(sig):
    """Formats a TypeSig, including its ref/array/pointer decorations."""
    name = type_name(sig.Type())
    name += "*" * sig.ptr_count()
    if sig.is_szarray():
        name += "[]"
    elif sig.is_array():
        name += "[" + "," * max(sig.array_rank() - 1, 0) + "]"
    return name


def parameter_name(param: ParamSig):
    return ("ref " if param.ByRef() else "") + signature_name(param.Type())


def dump_type(type: TypeDef, indent=""):
    kind = get_category(type)
    keyword = {
        category.interface_type: "interface",
        category.class_type: "class",
        category.enum_type: "enum",
        category.struct_type: "struct",
        category.delegate_type: "delegate",
    }[kind]

    print(f"{indent}{keyword} {type.TypeNamespace()}.{type.TypeName()}")

    for impl in type.InterfaceImpl():
        print(f"{indent}    : {type_name(impl.Interface())}")

    if kind == category.enum_type:
        definition = type.get_enum_definition()
        print(f"{indent}    // underlying: {type_name(definition.m_underlying_type)}")
        for field in type.FieldList():
            if field.Flags().Literal():
                print(f"{indent}    {field.Name()} = {field.Constant().Value()}")
        return

    for field in type.FieldList():
        print(f"{indent}    {signature_name(field.Signature().Type())} {field.Name()}")

    for property in type.PropertyList():
        accessors = "".join(
            " get;" if s.Semantic().Getter() else " set;"
            for s in property.MethodSemantic()
        )
        print(
            f"{indent}    {signature_name(property.Type().Type())} "
            f"{property.Name()} {{{accessors} }}"
        )

    for event in type.EventList():
        print(f"{indent}    event {type_name(event.EventType())} {event.Name()}")

    for method in type.MethodList():
        if method.SpecialName() and (
            method.Name().startswith(("get_", "put_", "set_", "add_", "remove_"))
        ):
            continue  # accessors are printed with their property/event
        sig = method.Signature()
        returns = signature_name(sig.ReturnType().Type()) if sig.ReturnType() else "void"
        names = [p.Name() for p in method.ParamList() if p.Sequence() != 0]
        params = ", ".join(
            f"{parameter_name(p)} {n}".strip()
            for p, n in zip(sig.Params(), names + [""] * len(sig.Params()))
        )
        static = "static " if method.Flags().Static() else ""
        print(f"{indent}    {static}{returns} {method.Name()}({params})")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help=".winmd files (globs are expanded)")
    parser.add_argument("--namespace", help="dump every type of this namespace")
    parser.add_argument("--type", help="dump a single Namespace.TypeName")
    parser.add_argument("--summary", action="store_true", help="list namespaces only")
    args = parser.parse_args(argv)

    files = sorted({path for pattern in args.files for path in glob.glob(pattern)})
    if not files:
        parser.error("no .winmd file matched")

    db = cache(files)
    print(f"// {len(db.databases())} databases, {len(db.namespaces())} namespaces")

    if args.summary or not (args.namespace or args.type):
        for name, members in db.namespaces().items():
            print(
                f"{name}: {len(members.types)} types "
                f"({len(members.interfaces)} interfaces, {len(members.classes)} classes, "
                f"{len(members.enums)} enums, {len(members.structs)} structs, "
                f"{len(members.delegates)} delegates, {len(members.attributes)} attributes, "
                f"{len(members.contracts)} contracts)"
            )
        return 0

    if args.type:
        dump_type(db.find_required(args.type))
        return 0

    members = db.namespaces().get(args.namespace)
    if members is None:
        print(f"namespace '{args.namespace}' not found", file=sys.stderr)
        return 1

    for _, type in members.types.items():
        dump_type(type)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
