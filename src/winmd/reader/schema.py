"""The rows, as schema.h and column.h have them.

One class per table, holding that table's accessors and no others, plus the
ranges a list column hands back.
"""

from __future__ import annotations

import collections.abc
from collections.abc import Sequence
from typing import TYPE_CHECKING

from .enum import (
    AssemblyHashAlgorithm,
    ConstantType,
    CustomAttributeType,
    HasConstant,
    HasCustomAttribute,
    HasFieldMarshal,
    HasSemantics,
    MemberForwarded,
    MemberRefParent,
    ResolutionScope,
    TableNumber,
    TypeDefOrRef,
    TypeOrMethodDef,
)
from .flags import (
    AssemblyAttributes,
    EventAttributes,
    FieldAttributes,
    GenericParamAttributes,
    MethodAttributes,
    MethodImplAttributes,
    MethodSemanticsAttributes,
    ParamAttributes,
    PInvokeAttributes,
    PropertyAttributes,
    TypeAttributes,
    _Flags,
)
from .helpers import extends_type
from .signature import (
    CustomAttributeSig,
    EnumDefinition,
    FieldSig,
    MethodDefSig,
    PropertySig,
    TypeSpecSig,
)
from .table import AssemblyVersion, Row, RowRange
from .view import byte_view

if TYPE_CHECKING:
    # Only the return types of the twelve accessors that read a coded index
    # column. What each of them reads is the kind, which is an enum above.
    from .index import (
        coded_index_CustomAttributeType,
        coded_index_HasConstant,
        coded_index_HasCustomAttribute,
        coded_index_HasFieldMarshal,
        coded_index_HasSemantics,
        coded_index_MemberForwarded,
        coded_index_MemberRefParent,
        coded_index_ResolutionScope,
        coded_index_TypeDefOrRef,
        coded_index_TypeOrMethodDef,
    )


# --- one class per table, with the accessors that table has ----------------
class Module(Row):
    """A row of the Module table."""

    __slots__ = ()
    _number = TableNumber.Module

    def Generation(self) -> int:
        return self.get_value(0)

    def Name(self) -> str:
        return self._string(1)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class TypeRef(Row):
    """A row of the TypeRef table."""

    __slots__ = ()
    _number = TableNumber.TypeRef

    def ResolutionScope(self) -> coded_index_ResolutionScope:
        return self.get_coded_index(ResolutionScope, 0)

    def TypeName(self) -> str:
        return self._string(1)

    def TypeNamespace(self) -> str:
        return self._string(2)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class TypeDef(Row):
    """A row of the TypeDef table."""

    __slots__ = ()
    _number = TableNumber.TypeDef

    def Flags(self) -> TypeAttributes:
        return TypeAttributes(self.get_value(0))

    def TypeName(self) -> str:
        return self._string(1)

    def TypeNamespace(self) -> str:
        return self._string(2)

    def Extends(self) -> coded_index_TypeDefOrRef:
        return self.get_coded_index(TypeDefOrRef, 3)

    def FieldList(self) -> RowRange[Field]:
        return self.get_list(4, Field)

    def MethodList(self) -> RowRange[MethodDef]:
        return self.get_list(5, MethodDef)

    def InterfaceImpl(self) -> Sequence[InterfaceImpl]:
        return self._table._database.equal_range(InterfaceImpl, 0, self._index + 1)

    def MethodImplList(self) -> Sequence[MethodImpl]:
        return self._table._database.equal_range(MethodImpl, 0, self._index + 1)

    def PropertyList(self) -> RowRange[Property]:
        mapping = self._table._database.find_row(PropertyMap, 0, self._index + 1)
        return (
            mapping.PropertyList()
            if mapping
            else RowRange(
                self._table._database.table_of(TableNumber.Property), Property, 0, 0
            )
        )

    def EventList(self) -> RowRange[Event]:
        mapping = self._table._database.find_row(EventMap, 0, self._index + 1)
        if mapping:
            return mapping.EventList()
        return RowRange(self._table._database.table_of(TableNumber.Event), Event, 0, 0)

    def GenericParam(self) -> Sequence[GenericParam]:
        return self._referrers(TypeOrMethodDef, GenericParam, 2)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()

    def EnclosingType(self) -> TypeDef:
        nested = self._table._database.find_row(NestedClass, 0, self._index + 1)
        if not nested:
            raise RuntimeError("the type is not nested")
        return nested.EnclosingType()

    def is_enum(self) -> bool:
        return extends_type(self, "System", "Enum")

    def get_enum_definition(self) -> EnumDefinition:
        return EnumDefinition(self)


class Field(Row):
    """A row of the Field table."""

    __slots__ = ()
    _number = TableNumber.Field

    def Flags(self) -> FieldAttributes:
        return FieldAttributes(self.get_value(0))

    def Name(self) -> str:
        return self._string(1)

    def Signature(self) -> FieldSig:
        return FieldSig(self._table, self._blob(2))

    def Parent(self) -> TypeDef:
        return self.get_parent_row(4, TypeDef)

    def Constant(self) -> Constant:
        return self._constant()

    def FieldMarshal(self) -> FieldMarshal | None:
        return self._referrer(HasFieldMarshal, FieldMarshal, 0)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class MethodDef(Row):
    """A row of the MethodDef table."""

    __slots__ = ()
    _number = TableNumber.MethodDef

    def RVA(self) -> int:
        return self.get_value(0)

    def ImplFlags(self) -> MethodImplAttributes:
        return MethodImplAttributes(self.get_value(1))

    def Flags(self) -> MethodAttributes:
        return MethodAttributes(self.get_value(2))

    def Name(self) -> str:
        return self._string(3)

    def Signature(self) -> MethodDefSig:
        return MethodDefSig(self._table, self._blob(4))

    def ParamList(self) -> RowRange[Param]:
        return self.get_list(5, Param)

    def Parent(self) -> TypeDef:
        return self.get_parent_row(5, TypeDef)

    def GenericParam(self) -> Sequence[GenericParam]:
        return self._referrers(TypeOrMethodDef, GenericParam, 2)

    def SpecialName(self) -> bool:
        """MethodDef.Flags().SpecialName(), which the C++ side also shortens."""
        return self.Flags().SpecialName()

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class Param(Row):
    """A row of the Param table."""

    __slots__ = ()
    _number = TableNumber.Param

    def Flags(self) -> ParamAttributes:
        return ParamAttributes(self.get_value(0))

    def Sequence(self) -> int:
        return self.get_value(1)

    def Name(self) -> str:
        return self._string(2)

    def Parent(self) -> MethodDef:
        return self.get_parent_row(5, MethodDef)

    def Constant(self) -> Constant:
        return self._constant()

    def FieldMarshal(self) -> FieldMarshal | None:
        return self._referrer(HasFieldMarshal, FieldMarshal, 0)

    # Sequence is this row's own accessor, so the one meant is spelled out.
    def CustomAttribute(self) -> collections.abc.Sequence[CustomAttribute]:
        return self._attributes()


class InterfaceImpl(Row):
    """A row of the InterfaceImpl table."""

    __slots__ = ()
    _number = TableNumber.InterfaceImpl

    def Class(self) -> TypeDef:
        return self.get_target_row(0, TypeDef)

    def Interface(self) -> coded_index_TypeDefOrRef:
        return self.get_coded_index(TypeDefOrRef, 1)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class MemberRef(Row):
    """A row of the MemberRef table."""

    __slots__ = ()
    _number = TableNumber.MemberRef

    def Class(self) -> coded_index_MemberRefParent:
        return self.get_coded_index(MemberRefParent, 0)

    def Name(self) -> str:
        return self._string(1)

    def MethodSignature(self) -> MethodDefSig:
        return MethodDefSig(self._table, self._blob(2))

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class Constant(Row):
    """A row of the Constant table."""

    __slots__ = ()
    _number = TableNumber.Constant

    def Type(self) -> ConstantType:
        return ConstantType(self.get_value(0))

    def Parent(self) -> coded_index_HasConstant:
        return self.get_coded_index(HasConstant, 1)

    def Value(self) -> bool | int | float | str | None:
        return _constant_value(ConstantType(self.get_value(0)), self._blob(2))

    def ValueBoolean(self) -> bool:
        return self._blob(2).read("<?")

    def ValueInt32(self) -> int:
        return self._blob(2).read("<i")

    def ValueUInt32(self) -> int:
        return self._blob(2).read("<I")

    def ValueString(self) -> str:
        blob = self._blob(2)
        return blob.data[blob.position : blob.end].decode("utf-16-le")


class CustomAttribute(Row):
    """A row of the CustomAttribute table."""

    __slots__ = ()
    _number = TableNumber.CustomAttribute

    def Parent(self) -> coded_index_HasCustomAttribute:
        return self.get_coded_index(HasCustomAttribute, 0)

    def Type(self) -> coded_index_CustomAttributeType:
        return self.get_coded_index(CustomAttributeType, 1)

    def Value(self) -> CustomAttributeSig:
        constructor = self.Type()
        if constructor.type() is CustomAttributeType.MemberRef:
            reference = constructor.get_row(MemberRef)
            signature = MethodDefSig(reference._table, reference._blob(2))
        else:
            signature = constructor.get_row(MethodDef).Signature()
        return CustomAttributeSig(self._table._database, self._blob(2), signature)

    def TypeNamespaceAndName(self) -> tuple[str, str]:
        """The namespace and name of the attribute this row applies.

        Cached by the constructor it names. A file applies far more attributes
        than it has kinds of them, so remembering the answer is most of what
        makes building a cache of the Win32 metadata quick.
        """
        constructor = self.get_value(1)
        names = self._table._database._attribute_names
        found = names.get(constructor)
        if found is None:
            # Only on a miss, which is 41 of the 152,119 attributes a file of
            # Win32 metadata carries, so the second read of the column costs
            # nothing worth keeping a hand-built index for.
            index = self.Type()
            parent: TypeDef | TypeRef
            if index.type() is CustomAttributeType.MemberRef:
                # custom_attribute.h picks the two tables apart here rather
                # than calling get_type_namespace_and_name, because the kind
                # is MemberRefParent and that function takes a TypeDefOrRef.
                # Two kinds' tags are never comparable, so the question has
                # to be asked in MemberRefParent's own enumerators.
                owner = index.get_row(MemberRef).Class()
                if owner.type() is MemberRefParent.TypeDef:
                    parent = owner.TypeDef()
                elif owner.type() is MemberRefParent.TypeRef:
                    parent = owner.TypeRef()
                else:
                    raise ValueError(
                        "a CustomAttribute MemberRef should only be a "
                        "TypeDef or TypeRef"
                    )
            else:
                parent = index.get_row(MethodDef).Parent()
            found = names[constructor] = (parent.TypeNamespace(), parent.TypeName())
        return found


class FieldMarshal(Row):
    """A row of the FieldMarshal table."""

    __slots__ = ()
    _number = TableNumber.FieldMarshal

    def Parent(self) -> coded_index_HasFieldMarshal:
        return self.get_coded_index(HasFieldMarshal, 0)


class DeclSecurity(Row):
    """A row of the DeclSecurity table."""

    __slots__ = ()
    _number = TableNumber.DeclSecurity


class ClassLayout(Row):
    """A row of the ClassLayout table."""

    __slots__ = ()
    _number = TableNumber.ClassLayout

    def PackingSize(self) -> int:
        return self.get_value(0)

    def ClassSize(self) -> int:
        return self.get_value(1)

    def Parent(self) -> TypeDef:
        return self.get_target_row(2, TypeDef)


class FieldLayout(Row):
    """A row of the FieldLayout table."""

    __slots__ = ()
    _number = TableNumber.FieldLayout


class StandAloneSig(Row):
    """A row of the StandAloneSig table."""

    __slots__ = ()
    _number = TableNumber.StandAloneSig

    def Signature(self) -> byte_view:
        return self._blob(0)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class EventMap(Row):
    """A row of the EventMap table."""

    __slots__ = ()
    _number = TableNumber.EventMap

    def Parent(self) -> TypeDef:
        return self.get_target_row(0, TypeDef)

    def EventList(self) -> RowRange[Event]:
        return self.get_list(1, Event)


class Event(Row):
    """A row of the Event table."""

    __slots__ = ()
    _number = TableNumber.Event

    def EventFlags(self) -> EventAttributes:
        return EventAttributes(self.get_value(0))

    def Name(self) -> str:
        return self._string(1)

    def EventType(self) -> coded_index_TypeDefOrRef:
        return self.get_coded_index(TypeDefOrRef, 2)

    def Parent(self) -> TypeDef:
        mapping = self.get_parent_row(1, EventMap)
        return mapping.Parent()

    def MethodSemantic(self) -> Sequence[MethodSemantics]:
        return self._referrers(HasSemantics, MethodSemantics, 2)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class PropertyMap(Row):
    """A row of the PropertyMap table."""

    __slots__ = ()
    _number = TableNumber.PropertyMap

    def Parent(self) -> TypeDef:
        return self.get_target_row(0, TypeDef)

    def PropertyList(self) -> RowRange[Property]:
        return self.get_list(1, Property)


class Property(Row):
    """A row of the Property table."""

    __slots__ = ()
    _number = TableNumber.Property

    def Flags(self) -> PropertyAttributes:
        return PropertyAttributes(self.get_value(0))

    def Name(self) -> str:
        return self._string(1)

    def Type(self) -> PropertySig:
        return PropertySig(self._table, self._blob(2))

    def Parent(self) -> TypeDef:
        mapping = self.get_parent_row(1, PropertyMap)
        return mapping.Parent()

    def Constant(self) -> Constant:
        return self._constant()

    def MethodSemantic(self) -> Sequence[MethodSemantics]:
        return self._referrers(HasSemantics, MethodSemantics, 2)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class MethodSemantics(Row):
    """A row of the MethodSemantics table."""

    __slots__ = ()
    _number = TableNumber.MethodSemantics

    def Semantic(self) -> MethodSemanticsAttributes:
        return MethodSemanticsAttributes(self.get_value(0))

    def Method(self) -> MethodDef:
        return self.get_target_row(1, MethodDef)

    def Association(self) -> coded_index_HasSemantics:
        return self.get_coded_index(HasSemantics, 2)


class MethodImpl(Row):
    """A row of the MethodImpl table."""

    __slots__ = ()
    _number = TableNumber.MethodImpl

    def Class(self) -> TypeDef:
        return self.get_target_row(0, TypeDef)


class ModuleRef(Row):
    """A row of the ModuleRef table."""

    __slots__ = ()
    _number = TableNumber.ModuleRef

    def Name(self) -> str:
        return self._string(0)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class TypeSpec(Row):
    """A row of the TypeSpec table."""

    __slots__ = ()
    _number = TableNumber.TypeSpec

    def Signature(self) -> TypeSpecSig:
        return TypeSpecSig(self._table, self._blob(0))

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class ImplMap(Row):
    """A row of the ImplMap table.

    The C++ reader has no accessors for this table; these are ours.
    """

    __slots__ = ()
    _number = TableNumber.ImplMap

    def MappingFlags(self) -> PInvokeAttributes:
        return PInvokeAttributes(self.get_value(0))

    def MemberForwarded(self) -> coded_index_MemberForwarded:
        return self.get_coded_index(MemberForwarded, 1)

    def ImportName(self) -> str:
        return self._string(2)

    def ImportScope(self) -> ModuleRef:
        return self.get_target_row(3, ModuleRef)


class FieldRVA(Row):
    """A row of the FieldRVA table."""

    __slots__ = ()
    _number = TableNumber.FieldRVA


class Assembly(Row):
    """A row of the Assembly table."""

    __slots__ = ()
    _number = TableNumber.Assembly

    def HashAlgId(self) -> AssemblyHashAlgorithm:
        return AssemblyHashAlgorithm(self.get_value(0))

    def Version(self) -> AssemblyVersion:
        return self._version(1)

    def Flags(self) -> AssemblyAttributes:
        return AssemblyAttributes(self.get_value(2))

    def PublicKey(self) -> byte_view:
        return self._blob(3)

    def Name(self) -> str:
        return self._string(4)

    def Culture(self) -> str:
        return self._string(5)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class AssemblyProcessor(Row):
    """A row of the AssemblyProcessor table."""

    __slots__ = ()
    _number = TableNumber.AssemblyProcessor


class AssemblyOS(Row):
    """A row of the AssemblyOS table."""

    __slots__ = ()
    _number = TableNumber.AssemblyOS


class AssemblyRef(Row):
    """A row of the AssemblyRef table."""

    __slots__ = ()
    _number = TableNumber.AssemblyRef

    def Version(self) -> AssemblyVersion:
        return self._version(0)

    def Flags(self) -> AssemblyAttributes:
        return AssemblyAttributes(self.get_value(1))

    def PublicKey(self) -> byte_view:
        """PublicKeyOrToken, as the standard calls this column."""
        return self._blob(2)

    def Name(self) -> str:
        return self._string(3)

    def Culture(self) -> str:
        return self._string(4)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class AssemblyRefProcessor(Row):
    """A row of the AssemblyRefProcessor table."""

    __slots__ = ()
    _number = TableNumber.AssemblyRefProcessor


class AssemblyRefOS(Row):
    """A row of the AssemblyRefOS table."""

    __slots__ = ()
    _number = TableNumber.AssemblyRefOS


class File(Row):
    """A row of the File table."""

    __slots__ = ()
    _number = TableNumber.File

    def Name(self) -> str:
        return self._string(1)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class ExportedType(Row):
    """A row of the ExportedType table."""

    __slots__ = ()
    _number = TableNumber.ExportedType

    def Flags(self) -> _Flags:
        return _Flags(self.get_value(0))

    def Name(self) -> str:
        return self._string(3)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class ManifestResource(Row):
    """A row of the ManifestResource table."""

    __slots__ = ()
    _number = TableNumber.ManifestResource

    def Flags(self) -> _Flags:
        return _Flags(self.get_value(1))

    def Name(self) -> str:
        return self._string(2)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class NestedClass(Row):
    """A row of the NestedClass table."""

    __slots__ = ()
    _number = TableNumber.NestedClass

    def NestedType(self) -> TypeDef:
        return self.get_target_row(0, TypeDef)

    def EnclosingType(self) -> TypeDef:
        return self.get_target_row(1, TypeDef)


class GenericParam(Row):
    """A row of the GenericParam table."""

    __slots__ = ()
    _number = TableNumber.GenericParam

    def Number(self) -> int:
        return self.get_value(0)

    def Flags(self) -> GenericParamAttributes:
        return GenericParamAttributes(self.get_value(1))

    def Owner(self) -> coded_index_TypeOrMethodDef:
        return self.get_coded_index(TypeOrMethodDef, 2)

    def Name(self) -> str:
        return self._string(3)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class MethodSpec(Row):
    """A row of the MethodSpec table."""

    __slots__ = ()
    _number = TableNumber.MethodSpec

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class GenericParamConstraint(Row):
    """A row of the GenericParamConstraint table."""

    __slots__ = ()
    _number = TableNumber.GenericParamConstraint

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


def _constant_value(
    kind: ConstantType, blob: byte_view
) -> bool | int | float | str | None:
    if kind == ConstantType.String:
        return blob.data[blob.position : blob.end].decode("utf-16-le")
    if kind == ConstantType.Class:
        return None
    formats = {
        ConstantType.Boolean: "<?",
        ConstantType.Char: "<H",
        ConstantType.Int8: "<b",
        ConstantType.UInt8: "<B",
        ConstantType.Int16: "<h",
        ConstantType.UInt16: "<H",
        ConstantType.Int32: "<i",
        ConstantType.UInt32: "<I",
        ConstantType.Int64: "<q",
        ConstantType.UInt64: "<Q",
        ConstantType.Float32: "<f",
        ConstantType.Float64: "<d",
    }
    value = blob.read(formats[kind])
    return chr(value) if kind == ConstantType.Char else value
