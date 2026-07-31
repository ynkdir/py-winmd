"""Checks the pure Python reader against the C++ one, on everything.

    python research/agree.py metadata/.../Windows.Win32.winmd

Both readers are asked to describe every type in the file as text - name,
category, base class, flags, interfaces, generic parameters, nested types,
fields with their signatures and constants, methods with their signatures and
parameters, properties, events, and every custom attribute with its decoded
arguments - and the two descriptions are compared line by line.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import purewinmd
from winmd import reader


# --- rendering, in the same words for both readers ------------------------
def pure_type_name(sig, pure):
    value = sig.Type()
    if isinstance(value, purewinmd.ElementType):
        name = value.name
    elif isinstance(value, purewinmd.coded_index):
        name = ".".join(purewinmd.get_type_namespace_and_name(value))
    elif isinstance(value, purewinmd.GenericTypeInstSig):
        arguments = ", ".join(pure_type_name(argument, pure)
                              for argument in value.GenericArgs())
        name = f"{'.'.join(purewinmd.get_type_namespace_and_name(value.GenericType()))}<{arguments}>"
    elif isinstance(value, purewinmd.GenericTypeIndex):
        name = f"!{value.index}"
    elif isinstance(value, purewinmd.GenericMethodTypeIndex):
        name = f"!!{value.index}"
    else:
        name = f"?{value!r}"
    return name + "[]" * sig.is_szarray() + "*" * sig.ptr_count()


def cpp_type_name(sig):
    value = sig.Type()
    if isinstance(value, reader.ElementType):
        name = value.name
    elif isinstance(value, reader.coded_index_TypeDefOrRef):
        name = ".".join(reader.get_type_namespace_and_name(value))
    elif isinstance(value, reader.GenericTypeInstSig):
        arguments = ", ".join(cpp_type_name(argument) for argument in value.GenericArgs())
        name = f"{'.'.join(reader.get_type_namespace_and_name(value.GenericType()))}<{arguments}>"
    elif isinstance(value, reader.GenericTypeIndex):
        name = f"!{value.index}"
    elif isinstance(value, reader.GenericMethodTypeIndex):
        name = f"!!{value.index}"
    else:
        name = f"?{value!r}"
    return name + "[]" * sig.is_szarray() + "*" * sig.ptr_count()


def value_text(value):
    """Attribute and constant values, printed the same way on both sides."""
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return repr(value)


def pure_argument(argument):
    value = argument.value
    if isinstance(value, list):
        return "[" + ", ".join(pure_argument(item) for item in value) + "]"
    if isinstance(value, purewinmd.ElemSig):
        value = value.value
    if isinstance(value, purewinmd.SystemType):
        return f"typeof({value.name})"
    if isinstance(value, purewinmd.EnumValue):
        return f"enum({value.type.m_typedef.TypeName()}, {value_text(value.value)})"
    return value_text(value)


def cpp_argument(argument):
    value = argument.value
    if isinstance(value, list):
        return "[" + ", ".join(cpp_argument(item) for item in value) + "]"
    if isinstance(value, reader.ElemSig):
        value = value.value
    if isinstance(value, reader.ElemSig.SystemType):
        return f"typeof({value.name})"
    if isinstance(value, reader.ElemSig.EnumValue):
        return f"enum({value.type.m_typedef.TypeName()}, {value_text(value.value)})"
    return value_text(value)


def pure_attributes(row):
    out = []
    for attribute in row.CustomAttribute():
        namespace, name = attribute.TypeNamespaceAndName()
        try:
            args = attribute.Value()
            fixed = [pure_argument(argument) for argument in args.FixedArgs()]
            named = [f"{argument.name}={pure_argument(argument.value)}"
                     for argument in args.NamedArgs()]
            out.append(f"{namespace}.{name}({', '.join(fixed + named)})")
        except Exception as error:                     # unresolvable argument
            out.append(f"{namespace}.{name}(<{type(error).__name__}>)")
    return out


def cpp_attributes(row):
    out = []
    for attribute in row.CustomAttribute():
        namespace, name = attribute.TypeNamespaceAndName()
        try:
            args = attribute.Value()
            fixed = [cpp_argument(argument) for argument in args.FixedArgs()]
            named = [f"{argument.name}={cpp_argument(argument.value)}"
                     for argument in args.NamedArgs()]
            out.append(f"{namespace}.{name}({', '.join(fixed + named)})")
        except Exception as error:
            out.append(f"{namespace}.{name}(<{type(error).__name__}>)")
    return out


def safe_name(index, module):
    """Both readers raise on a TypeSpec, which an interface or event can be."""
    try:
        return ".".join(module.get_type_namespace_and_name(index))
    except (ValueError, RuntimeError):
        return "<TypeSpec>"


def pure_base(type):
    # Both readers raise on the base class of a type that extends nothing.
    return ".".join(purewinmd.get_base_class_namespace_and_name(type)) \
        if type.Extends() else ""


def cpp_base(type):
    return ".".join(reader.get_base_class_namespace_and_name(type)) \
        if type.Extends() else ""


def describe_pure(type, pure):
    out = [f"type {type.TypeNamespace()}.{type.TypeName()}"]
    flags = type.Flags()
    out.append(f"  flags {flags.value:#x} {purewinmd.get_category(type).name} "
               f"visibility={flags.Visibility().name} layout={flags.Layout().name} "
               f"semantics={flags.Semantics().name} abstract={flags.Abstract()} "
               f"sealed={flags.Sealed()} special={flags.SpecialName()}")
    out.append(f"  extends {pure_base(type)}")
    out.append(f"  nested {purewinmd.is_nested(type)}")
    for impl in type.InterfaceImpl():
        out.append(f"  implements {safe_name(impl.Interface(), purewinmd)}")
    for parameter in type.GenericParam():
        out.append(f"  generic {parameter.Number()} {parameter.Name()}")
    for attribute in pure_attributes(type):
        out.append(f"  attribute {attribute}")
    for field in type.FieldList():
        line = f"  field {field.Name()} : {pure_type_name(field.Signature().Type(), pure)}"
        if field.Flags().Literal():
            line += f" = {value_text(field.Constant().Value())}"
        out.append(line)
        for attribute in pure_attributes(field):
            out.append(f"    attribute {attribute}")
    for method in type.MethodList():
        signature = method.Signature()
        returns = pure_type_name(signature.ReturnType().Type(), pure) \
            if signature.ReturnType() else "void"
        parameters = []
        rows = {row.Sequence(): row for row in method.ParamList()}
        for index, param in enumerate(signature.Params(), start=1):
            row = rows.get(index)
            name = row.Name() if row else "?"
            direction = ""
            if row:
                direction = f"[in={row.Flags().In()} out={row.Flags().Out()}]"
            parameters.append(
                f"{pure_type_name(param.Type(), pure)}{'&' if param.ByRef() else ''} "
                f"{name}{direction}")
        out.append(f"  method {returns} {method.Name()}({', '.join(parameters)}) "
                   f"conv={signature.CallConvention().value:#x} "
                   f"generic={signature.GenericParamCount()} "
                   f"flags={method.Flags().value:#x}")
        for attribute in pure_attributes(method):
            out.append(f"    attribute {attribute}")
    for property in type.PropertyList():
        out.append(f"  property {property.Name()} : "
                   f"{pure_type_name(property.Signature().Type(), pure)}")
    for event in type.EventList():
        out.append(f"  event {event.Name()} : "
                   f"{safe_name(event.EventType(), purewinmd)}")
    return out


def describe_cpp(type):
    out = [f"type {type.TypeNamespace()}.{type.TypeName()}"]
    flags = type.Flags()
    out.append(f"  flags {flags.value:#x} {reader.get_category(type).name} "
               f"visibility={flags.Visibility().name} layout={flags.Layout().name} "
               f"semantics={flags.Semantics().name} abstract={flags.Abstract()} "
               f"sealed={flags.Sealed()} special={flags.SpecialName()}")
    out.append(f"  extends {cpp_base(type)}")
    out.append(f"  nested {reader.is_nested(type)}")
    for impl in type.InterfaceImpl():
        out.append(f"  implements {safe_name(impl.Interface(), reader)}")
    for parameter in type.GenericParam():
        out.append(f"  generic {parameter.Number()} {parameter.Name()}")
    for attribute in cpp_attributes(type):
        out.append(f"  attribute {attribute}")
    for field in type.FieldList():
        line = f"  field {field.Name()} : {cpp_type_name(field.Signature().Type())}"
        if field.Flags().Literal():
            line += f" = {value_text(field.Constant().Value())}"
        out.append(line)
        for attribute in cpp_attributes(field):
            out.append(f"    attribute {attribute}")
    for method in type.MethodList():
        signature = method.Signature()
        returns = cpp_type_name(signature.ReturnType().Type()) \
            if signature.ReturnType() else "void"
        parameters = []
        rows = {row.Sequence(): row for row in method.ParamList()}
        for index, param in enumerate(signature.Params(), start=1):
            row = rows.get(index)
            name = row.Name() if row else "?"
            direction = ""
            if row:
                direction = f"[in={row.Flags().In()} out={row.Flags().Out()}]"
            parameters.append(
                f"{cpp_type_name(param.Type())}{'&' if param.ByRef() else ''} "
                f"{name}{direction}")
        out.append(f"  method {returns} {method.Name()}({', '.join(parameters)}) "
                   f"conv={signature.CallConvention().value:#x} "
                   f"generic={signature.GenericParamCount()} "
                   f"flags={method.Flags().value:#x}")
        for attribute in cpp_attributes(method):
            out.append(f"    attribute {attribute}")
    for property in type.PropertyList():
        out.append(f"  property {property.Name()} : {cpp_type_name(property.Type().Type())}")
    for event in type.EventList():
        out.append(f"  event {event.Name()} : "
                   f"{safe_name(event.EventType(), reader)}")
    return out


def compare(paths, limit=None, verbose=False):
    pure = purewinmd.cache(paths)
    cpp = reader.cache(paths)

    pure_names = {(namespace, name)
                  for namespace, members in pure.namespaces().items()
                  for name in members.types}
    cpp_names = {(namespace, name)
                 for namespace, members in cpp.namespaces().items()
                 for name in members.types}
    if pure_names != cpp_names:
        only_pure = sorted(pure_names - cpp_names)[:5]
        only_cpp = sorted(cpp_names - pure_names)[:5]
        raise SystemExit(f"the indexes differ: only in pure {only_pure}, "
                         f"only in the bindings {only_cpp}")
    print(f"{len(pure_names)} types indexed the same way")

    checked = 0
    failures = 0
    for namespace, name in sorted(pure_names):
        mine = describe_pure(pure.find_required(namespace, name), pure)
        theirs = describe_cpp(cpp.find_required(namespace, name))
        checked += 1
        if mine != theirs:
            failures += 1
            print(f"\n{namespace}.{name} differs")
            for left, right in zip(mine, theirs):
                if left != right:
                    print(f"  pure: {left}")
                    print(f"  cpp : {right}")
            if len(mine) != len(theirs):
                print(f"  ({len(mine)} lines against {len(theirs)})")
            if failures > 10:
                raise SystemExit("too many differences")
        if limit and checked >= limit:
            break

    print(f"{checked} types described identically by both readers")
    if failures:
        raise SystemExit(f"{failures} differ")


if __name__ == "__main__":
    arguments = [value for value in sys.argv[1:] if not value.startswith("--")]
    limit = next((int(value.split("=")[1]) for value in sys.argv[1:]
                  if value.startswith("--limit=")), None)
    compare(arguments, limit)
    print("OK")
