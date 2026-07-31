"""Describing metadata in text, in the words tests/reference.cpp uses.

The reference is the C++ reader: tests/reference.cpp walks a set of .winmd
files and prints every type it finds; this prints the same thing with the Python
reader, and test_reference.py compares the two line for line. Anything the two
could spell differently - a float, a string, a char, an enum member - is spelled
here the way the C++ spells it.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The NuGet packages scripts/fetch-vendor.ps1 installs: the metadata the tests
# read, and the C++ reader they are checked against.
VENDOR = os.environ.get("WINMD_VENDOR") or os.path.join(ROOT, "vendor")

SDK = os.path.join(VENDOR, "Microsoft.Windows.SDK.Contracts", "ref", "netstandard2.0")
WIN32 = os.path.join(VENDOR, "Microsoft.Windows.SDK.Win32Metadata")
HEADERS = os.path.join(VENDOR, "Microsoft.Windows.WinMD")


# --- values ---------------------------------------------------------------
def quoted(value):
    """A string as reference.cpp quotes it: \\x for bytes, \\u for UTF-16."""
    out = ['"']
    for character in value:
        code = ord(character)
        if character == "\\":
            out.append("\\\\")
        elif character == '"':
            out.append('\\"')
        elif character == "\n":
            out.append("\\n")
        elif character == "\r":
            out.append("\\r")
        elif character == "\t":
            out.append("\\t")
        elif code < 0x20 or code >= 0x7F:
            # The C++ side sees UTF-8 bytes for a string and UTF-16 units for a
            # constant, and escapes what it has; this matches both.
            out.append("".join(f"\\x{byte:02x}" for byte in character.encode("utf-8"))
                       if _utf8_context else f"\\u{code:04x}")
        else:
            out.append(character)
    out.append('"')
    return "".join(out)


_utf8_context = True


def utf8(value):
    """A string from the #Strings heap, which C++ escapes byte by byte."""
    global _utf8_context
    _utf8_context = True
    return quoted(value)


def utf16(value):
    """A string constant, which C++ escapes unit by unit."""
    global _utf8_context
    _utf8_context = False
    try:
        return quoted(value)
    finally:
        _utf8_context = True


def number(value):
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, str):                       # a char constant
        return f"char(0x{ord(value):04x})"
    if value is None:
        return "None"
    return str(value)


def constant_value(constant, module):
    value = constant.Value()
    if constant.Type() == module.ConstantType.String:
        return utf16(value)
    if constant.Type() == module.ConstantType.Char:
        return f"char(0x{ord(value):04x})"
    return number(value)


# --- names ----------------------------------------------------------------
def reference_name(index, module):
    """A TypeDefOrRef by name; a TypeSpec has none, in either reader."""
    if not index or index.type() == module.TypeDefOrRef.TypeSpec:
        return "<TypeSpec>"
    return ".".join(module.get_type_namespace_and_name(index))


def type_name(sig, module):
    value = sig.Type()
    if isinstance(value, module.ElementType):
        name = value.name
    elif isinstance(value, module.coded_index[module.TypeDefOrRef]):
        name = reference_name(value, module)
    elif isinstance(value, module.GenericTypeInstSig):
        arguments = ", ".join(type_name(argument, module)
                              for argument in value.GenericArgs())
        name = f"{reference_name(value.GenericType(), module)}<{arguments}>"
    elif isinstance(value, module.GenericTypeIndex):
        name = f"!{value.index}"
    elif isinstance(value, module.GenericMethodTypeIndex):
        name = f"!!{value.index}"
    else:
        name = "?"
    return name + "[]" * sig.is_szarray() + "*" * sig.ptr_count()


# --- custom attributes ----------------------------------------------------
def element(elem, module):
    value = elem.value
    if isinstance(value, module.ElemSig.SystemType):
        return f"typeof({value.name})"
    if isinstance(value, module.ElemSig.EnumValue):
        return f"enum({value.type.m_typedef.TypeName()}, {number(value.value)})"
    if isinstance(value, str) and len(value) != 1:
        return utf8(value)
    if isinstance(value, str):
        # One character is ambiguous: a Char argument or a one letter string.
        return utf8(value)
    return number(value)


def argument(arg, module):
    value = arg.value
    if isinstance(value, list):
        return "[" + ", ".join(element(item, module) for item in value) + "]"
    return element(value, module)


def attributes(row, module, indent):
    out = []
    for attribute in row.CustomAttribute():
        namespace, name = attribute.TypeNamespaceAndName()
        try:
            signature = attribute.Value()
            parts = [argument(fixed, module) for fixed in signature.FixedArgs()]
            parts += [f"{named.name}={argument(named.value, module)}"
                      for named in signature.NamedArgs()]
            arguments = ", ".join(parts)
        except Exception:
            arguments = "<error>"
        out.append(f"{indent}attribute {namespace}.{name}({arguments})")
    return out


# --- one type -------------------------------------------------------------
def describe(type, module):
    out = [f"type {type.TypeNamespace()}.{type.TypeName()}"]

    flags = type.Flags()
    out.append(f"  flags 0x{flags.value:x} {module.get_category(type).name} "
               f"visibility={flags.Visibility().name} layout={flags.Layout().name} "
               f"semantics={flags.Semantics().name} "
               f"abstract={number(flags.Abstract())} sealed={number(flags.Sealed())} "
               f"special={number(flags.SpecialName())}")

    base = ".".join(module.get_base_class_namespace_and_name(type)) \
        if type.Extends() else ""
    out.append(f"  extends {base}")
    out.append(f"  nested {number(module.is_nested(type))}")

    for impl in type.InterfaceImpl():
        out.append(f"  implements {reference_name(impl.Interface(), module)}")
    for parameter in type.GenericParam():
        out.append(f"  generic {parameter.Number()} {parameter.Name()}")
    out += attributes(type, module, "  ")

    for field in type.FieldList():
        line = f"  field {field.Name()} : {type_name(field.Signature().Type(), module)}"
        if field.Flags().Literal():
            line += f" = {constant_value(field.Constant(), module)}"
        out.append(line)
        out += attributes(field, module, "    ")

    for method in type.MethodList():
        signature = method.Signature()
        returns = type_name(signature.ReturnType().Type(), module) \
            if signature.ReturnType() else "void"
        rows = {row.Sequence(): row for row in method.ParamList()}
        parameters = []
        for index, param in enumerate(signature.Params(), start=1):
            row = rows.get(index)
            described = f"{row.Name()}[in={number(row.Flags().In())} " \
                        f"out={number(row.Flags().Out())}]" if row else "?"
            parameters.append(f"{type_name(param.Type(), module)}"
                              f"{'&' if param.ByRef() else ''} {described}")
        out.append(f"  method {returns} {method.Name()}({', '.join(parameters)}) "
                   f"conv=0x{int(signature.CallConvention()):x} "
                   f"generic={signature.GenericParamCount()} "
                   f"flags=0x{method.Flags().value:x}")
        out += attributes(method, module, "    ")

    for property in type.PropertyList():
        out.append(f"  property {property.Name()} : "
                   f"{type_name(property.Type().Type(), module)}")
    for event in type.EventList():
        out.append(f"  event {event.Name()} : "
                   f"{reference_name(event.EventType(), module)}")
    return out


def describe_all(paths, module):
    """Every type of a set of files, in the order reference.cpp walks them."""
    db = module.cache(list(paths))
    types = sorted((namespace, name)
                   for namespace, members in db.namespaces().items()
                   for name in members.types)
    out = []
    for namespace, name in types:
        out += describe(db.find_required(namespace, name), module)
    return out

