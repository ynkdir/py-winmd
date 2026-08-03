"""The free functions, as helpers.h and type_helpers.h have them.

Resolving a coded index to a namespace and a name, following it to the
definition, and asking a type what kind of thing it is.
"""

from __future__ import annotations

from typing import Any

from .enum import ResolutionScope, TypeDefOrRef, TypeSemantics, TypeVisibility, category
from .schema import CustomAttribute, Row, TypeDef, TypeRef, coded_index
from .signature import ParamSig


# --- the free functions ---------------------------------------------------
def get_type_namespace_and_name(index: coded_index) -> tuple[str, str]:
    """(namespace, name) of what a TypeDefOrRef points at.

    A TypeSpec is a signature rather than a name, and raises here as it does in
    C++; resolve it through Signature().GenericTypeInst().GenericType() if that
    is what you meant.
    """
    if index.type() is TypeDefOrRef.TypeSpec:
        raise ValueError("a TypeSpec has no namespace and name")
    # Memoised for the same reason attribute names are: a base class or an
    # interface is named over and over. System.ValueType alone accounts for
    # thousands of the resolutions the cache does.
    names = index._database._type_names
    key = (index._enum, index._value)
    found = names.get(key)
    if found is None:
        row = (
            TypeDef(index._database, index.index())
            if index.type() is TypeDefOrRef.TypeDef
            else TypeRef(index._database, index.index())
        )
        found = names[key] = (row.TypeNamespace(), row.TypeName())
    return found


def get_base_class_namespace_and_name(type: TypeDef) -> tuple[str, str]:
    return get_type_namespace_and_name(type.Extends())


def extends_type(type: TypeDef, namespace: str, name: str) -> bool:
    return get_base_class_namespace_and_name(type) == (namespace, name)


def is_nested(type: TypeDef | TypeRef) -> bool:
    if isinstance(type, TypeDef):
        return type.Flags().Visibility() >= TypeVisibility.NestedPublic
    return type.ResolutionScope().type() is ResolutionScope.TypeRef


def get_category(type: TypeDef) -> category:
    if type.Flags().Semantics() == TypeSemantics.Interface or get_attribute(
        type, "System.Runtime.InteropServices", "GuidAttribute"
    ):
        return category.interface_type
    namespace, name = get_base_class_namespace_and_name(type)
    if (namespace, name) == ("System", "Enum"):
        return category.enum_type
    if (namespace, name) == ("System", "ValueType"):
        return category.struct_type
    if (namespace, name) == ("System", "MulticastDelegate"):
        return category.delegate_type
    return category.class_type


def get_attribute(
    row: Row | coded_index, namespace: str, name: str
) -> CustomAttribute | None:
    """The attribute of that name on any row that carries attributes."""
    carrier: Any = row.get_row() if isinstance(row, coded_index) else row
    for attribute in carrier.CustomAttribute():
        if attribute.TypeNamespaceAndName() == (namespace, name):
            return attribute
    return None


def find(type: coded_index | TypeRef) -> TypeDef | None:
    """The definition a TypeRef or a TypeDefOrRef column points at."""
    if isinstance(type, coded_index):
        if type.type() is TypeDefOrRef.TypeDef:
            return TypeDef(type.get_database(), type.index())
        if type.type() is TypeDefOrRef.TypeSpec:
            raise ValueError("a TypeSpec cannot be resolved to a TypeDef")
        reference = TypeRef(type.get_database(), type.index())
    else:
        reference = type
    scope = reference.ResolutionScope()
    if scope.type() is ResolutionScope.TypeRef:  # nested
        enclosing = find(TypeRef(scope.get_database(), scope.index()))
        if not enclosing:
            return None
        for nested in enclosing.get_cache().nested_types(enclosing):
            if nested.TypeName() == reference.TypeName():
                return nested
        return None
    return reference.get_cache().find(reference.TypeNamespace(), reference.TypeName())


def find_required(type: coded_index | TypeRef) -> TypeDef:
    definition = find(type)
    if not definition:
        namespace, name = (
            get_type_namespace_and_name(type)
            if isinstance(type, coded_index)
            else (type.TypeNamespace(), type.TypeName())
        )
        raise ValueError(f"the type {namespace}.{name} could not be found")
    return definition


def is_const(param: ParamSig) -> bool:
    for mod in param.CustomMod():
        namespace, name = get_type_namespace_and_name(mod.Type())
        if name == "IsConst":
            return True
    return False
