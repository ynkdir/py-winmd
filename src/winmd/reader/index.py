"""The coded indexes, as table.h, enum_traits.h and index.h have them.

A column that may point at one of several tables: a tag and a one-based row
number packed together. One class per kind, each stating its tables and its
tag width and carrying an accessor per table it can name.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, TypeAlias

from .enum import (
    CustomAttributeType,
    HasConstant,
    HasCustomAttribute,
    HasDeclSecurity,
    HasFieldMarshal,
    HasSemantics,
    Implementation,
    MemberForwarded,
    MemberRefParent,
    MethodDefOrRef,
    ResolutionScope,
    TableNumber,
    TypeDefOrRef,
    TypeOrMethodDef,
)
from .table import coded_index

if TYPE_CHECKING:
    from .schema import (
        Assembly,
        AssemblyRef,
        CustomAttribute,
        DeclSecurity,
        Event,
        ExportedType,
        Field,
        File,
        GenericParam,
        GenericParamConstraint,
        InterfaceImpl,
        ManifestResource,
        MemberRef,
        MethodDef,
        MethodSpec,
        Module,
        ModuleRef,
        Param,
        Property,
        StandAloneSig,
        TypeDef,
        TypeRef,
        TypeSpec,
    )

    # The rows each tag can name, which is what get_row() hands back.
    # One per kind, in tag order, skipping the tags that name no table.
    _TypeDefOrRefRows: TypeAlias = TypeDef | TypeRef | TypeSpec
    _HasConstantRows: TypeAlias = Field | Param | Property
    _HasCustomAttributeRows: TypeAlias = (
        MethodDef
        | Field
        | TypeRef
        | TypeDef
        | Param
        | InterfaceImpl
        | MemberRef
        | Module
        | DeclSecurity
        | Property
        | Event
        | StandAloneSig
        | ModuleRef
        | TypeSpec
        | Assembly
        | AssemblyRef
        | File
        | ExportedType
        | ManifestResource
        | GenericParam
        | GenericParamConstraint
        | MethodSpec
    )
    _HasFieldMarshalRows: TypeAlias = Field | Param
    _HasDeclSecurityRows: TypeAlias = TypeDef | MethodDef | Assembly
    _MemberRefParentRows: TypeAlias = (
        TypeDef | TypeRef | ModuleRef | MethodDef | TypeSpec
    )
    _HasSemanticsRows: TypeAlias = Event | Property
    _MethodDefOrRefRows: TypeAlias = MethodDef | MemberRef
    _MemberForwardedRows: TypeAlias = Field | MethodDef
    _ImplementationRows: TypeAlias = File | AssemblyRef | ExportedType
    _CustomAttributeTypeRows: TypeAlias = MethodDef | MemberRef
    _ResolutionScopeRows: TypeAlias = Module | ModuleRef | AssemblyRef | TypeRef
    _TypeOrMethodDefRows: TypeAlias = TypeDef | MethodDef


# One class per kind, as the C++ template gives one type per kind:
# coded_index<TypeDefOrRef> is coded_index_TypeDefOrRef.
class coded_index_TypeDefOrRef(coded_index[TypeDefOrRef, "_TypeDefOrRefRows"]):
    """A TypeDefOrRef column: a TypeDef, a TypeRef or a TypeSpec."""

    __slots__ = ()
    _enum = TypeDefOrRef
    _tables = (TableNumber.TypeDef, TableNumber.TypeRef, TableNumber.TypeSpec)
    _bits = 2
    _mask = 0b11
    _tags = {
        TableNumber.TypeDef: TypeDefOrRef.TypeDef,
        TableNumber.TypeRef: TypeDefOrRef.TypeRef,
        TableNumber.TypeSpec: TypeDefOrRef.TypeSpec,
    }

    def TypeDef(self) -> "TypeDef":
        return self.get_row(TableNumber.TypeDef)

    def TypeRef(self) -> "TypeRef":
        return self.get_row(TableNumber.TypeRef)

    def TypeSpec(self) -> "TypeSpec":
        return self.get_row(TableNumber.TypeSpec)

    def CustomAttribute(self) -> "Sequence[CustomAttribute]":
        """The attributes of whichever of the three this names.

        The only accessor a kind has that is not a row of one table.
        The C++ has it on this kind alone, and branches as this does.
        """
        tag = self.type()
        if tag is TypeDefOrRef.TypeDef:
            return self.TypeDef().CustomAttribute()
        if tag is TypeDefOrRef.TypeRef:
            return self.TypeRef().CustomAttribute()
        return self.TypeSpec().CustomAttribute()


class coded_index_HasConstant(coded_index[HasConstant, "_HasConstantRows"]):
    """A HasConstant column: what a Constant row belongs to."""

    __slots__ = ()
    _enum = HasConstant
    _tables = (TableNumber.Field, TableNumber.Param, TableNumber.Property)
    _bits = 2
    _mask = 0b11
    _tags = {
        TableNumber.Field: HasConstant.Field,
        TableNumber.Param: HasConstant.Param,
        TableNumber.Property: HasConstant.Property,
    }

    def Field(self) -> "Field":
        return self.get_row(TableNumber.Field)

    def Param(self) -> "Param":
        return self.get_row(TableNumber.Param)

    def Property(self) -> "Property":
        return self.get_row(TableNumber.Property)


class coded_index_HasCustomAttribute(
    coded_index[HasCustomAttribute, "_HasCustomAttributeRows"]
):
    """A HasCustomAttribute column: what an attribute is attached to."""

    __slots__ = ()
    _enum = HasCustomAttribute
    _tables = (
        TableNumber.MethodDef,
        TableNumber.Field,
        TableNumber.TypeRef,
        TableNumber.TypeDef,
        TableNumber.Param,
        TableNumber.InterfaceImpl,
        TableNumber.MemberRef,
        TableNumber.Module,
        TableNumber.DeclSecurity,
        TableNumber.Property,
        TableNumber.Event,
        TableNumber.StandAloneSig,
        TableNumber.ModuleRef,
        TableNumber.TypeSpec,
        TableNumber.Assembly,
        TableNumber.AssemblyRef,
        TableNumber.File,
        TableNumber.ExportedType,
        TableNumber.ManifestResource,
        TableNumber.GenericParam,
        TableNumber.GenericParamConstraint,
        TableNumber.MethodSpec,
    )
    _bits = 5
    _mask = 0b11111
    # Sized on 21 tables, as composite_index_size is called in the C++:
    # Permission, which tag 8 names, is not among them.
    _sizing_tables = (
        TableNumber.MethodDef,
        TableNumber.Field,
        TableNumber.TypeRef,
        TableNumber.TypeDef,
        TableNumber.Param,
        TableNumber.InterfaceImpl,
        TableNumber.MemberRef,
        TableNumber.Module,
        TableNumber.Property,
        TableNumber.Event,
        TableNumber.StandAloneSig,
        TableNumber.ModuleRef,
        TableNumber.TypeSpec,
        TableNumber.Assembly,
        TableNumber.AssemblyRef,
        TableNumber.File,
        TableNumber.ExportedType,
        TableNumber.ManifestResource,
        TableNumber.GenericParam,
        TableNumber.GenericParamConstraint,
        TableNumber.MethodSpec,
    )
    _tags = {
        TableNumber.MethodDef: HasCustomAttribute.MethodDef,
        TableNumber.Field: HasCustomAttribute.Field,
        TableNumber.TypeRef: HasCustomAttribute.TypeRef,
        TableNumber.TypeDef: HasCustomAttribute.TypeDef,
        TableNumber.Param: HasCustomAttribute.Param,
        TableNumber.InterfaceImpl: HasCustomAttribute.InterfaceImpl,
        TableNumber.MemberRef: HasCustomAttribute.MemberRef,
        TableNumber.Module: HasCustomAttribute.Module,
        TableNumber.DeclSecurity: HasCustomAttribute.DeclSecurity,
        TableNumber.Property: HasCustomAttribute.Property,
        TableNumber.Event: HasCustomAttribute.Event,
        TableNumber.StandAloneSig: HasCustomAttribute.StandAloneSig,
        TableNumber.ModuleRef: HasCustomAttribute.ModuleRef,
        TableNumber.TypeSpec: HasCustomAttribute.TypeSpec,
        TableNumber.Assembly: HasCustomAttribute.Assembly,
        TableNumber.AssemblyRef: HasCustomAttribute.AssemblyRef,
        TableNumber.File: HasCustomAttribute.File,
        TableNumber.ExportedType: HasCustomAttribute.ExportedType,
        TableNumber.ManifestResource: HasCustomAttribute.ManifestResource,
        TableNumber.GenericParam: HasCustomAttribute.GenericParam,
        TableNumber.GenericParamConstraint: HasCustomAttribute.GenericParamConstraint,
        TableNumber.MethodSpec: HasCustomAttribute.MethodSpec,
    }

    def MethodDef(self) -> "MethodDef":
        return self.get_row(TableNumber.MethodDef)

    def Field(self) -> "Field":
        return self.get_row(TableNumber.Field)

    def TypeRef(self) -> "TypeRef":
        return self.get_row(TableNumber.TypeRef)

    def TypeDef(self) -> "TypeDef":
        return self.get_row(TableNumber.TypeDef)

    def Param(self) -> "Param":
        return self.get_row(TableNumber.Param)

    def InterfaceImpl(self) -> "InterfaceImpl":
        return self.get_row(TableNumber.InterfaceImpl)

    def MemberRef(self) -> "MemberRef":
        return self.get_row(TableNumber.MemberRef)

    def Module(self) -> "Module":
        return self.get_row(TableNumber.Module)

    def DeclSecurity(self) -> "DeclSecurity":
        return self.get_row(TableNumber.DeclSecurity)

    def Property(self) -> "Property":
        return self.get_row(TableNumber.Property)

    def Event(self) -> "Event":
        return self.get_row(TableNumber.Event)

    def StandAloneSig(self) -> "StandAloneSig":
        return self.get_row(TableNumber.StandAloneSig)

    def ModuleRef(self) -> "ModuleRef":
        return self.get_row(TableNumber.ModuleRef)

    def TypeSpec(self) -> "TypeSpec":
        return self.get_row(TableNumber.TypeSpec)

    def Assembly(self) -> "Assembly":
        return self.get_row(TableNumber.Assembly)

    def AssemblyRef(self) -> "AssemblyRef":
        return self.get_row(TableNumber.AssemblyRef)

    def File(self) -> "File":
        return self.get_row(TableNumber.File)

    def ExportedType(self) -> "ExportedType":
        return self.get_row(TableNumber.ExportedType)

    def ManifestResource(self) -> "ManifestResource":
        return self.get_row(TableNumber.ManifestResource)

    def GenericParam(self) -> "GenericParam":
        return self.get_row(TableNumber.GenericParam)

    def GenericParamConstraint(self) -> "GenericParamConstraint":
        return self.get_row(TableNumber.GenericParamConstraint)

    def MethodSpec(self) -> "MethodSpec":
        return self.get_row(TableNumber.MethodSpec)


class coded_index_HasFieldMarshal(coded_index[HasFieldMarshal, "_HasFieldMarshalRows"]):
    """A HasFieldMarshal column: a Field or a Param."""

    __slots__ = ()
    _enum = HasFieldMarshal
    _tables = (TableNumber.Field, TableNumber.Param)
    _bits = 1
    _mask = 0b1
    _tags = {
        TableNumber.Field: HasFieldMarshal.Field,
        TableNumber.Param: HasFieldMarshal.Param,
    }

    def Field(self) -> "Field":
        return self.get_row(TableNumber.Field)

    def Param(self) -> "Param":
        return self.get_row(TableNumber.Param)


class coded_index_HasDeclSecurity(coded_index[HasDeclSecurity, "_HasDeclSecurityRows"]):
    """A HasDeclSecurity column: a TypeDef, a MethodDef or the Assembly."""

    __slots__ = ()
    _enum = HasDeclSecurity
    _tables = (
        TableNumber.TypeDef,
        TableNumber.MethodDef,
        TableNumber.Assembly,
    )
    _bits = 2
    _mask = 0b11
    _tags = {
        TableNumber.TypeDef: HasDeclSecurity.TypeDef,
        TableNumber.MethodDef: HasDeclSecurity.MethodDef,
        TableNumber.Assembly: HasDeclSecurity.Assembly,
    }

    def TypeDef(self) -> "TypeDef":
        return self.get_row(TableNumber.TypeDef)

    def MethodDef(self) -> "MethodDef":
        return self.get_row(TableNumber.MethodDef)

    def Assembly(self) -> "Assembly":
        return self.get_row(TableNumber.Assembly)


class coded_index_MemberRefParent(coded_index[MemberRefParent, "_MemberRefParentRows"]):
    """A MemberRefParent column: what a MemberRef is a member of."""

    __slots__ = ()
    _enum = MemberRefParent
    _tables = (
        TableNumber.TypeDef,
        TableNumber.TypeRef,
        TableNumber.ModuleRef,
        TableNumber.MethodDef,
        TableNumber.TypeSpec,
    )
    _bits = 3
    _mask = 0b111
    _tags = {
        TableNumber.TypeDef: MemberRefParent.TypeDef,
        TableNumber.TypeRef: MemberRefParent.TypeRef,
        TableNumber.ModuleRef: MemberRefParent.ModuleRef,
        TableNumber.MethodDef: MemberRefParent.MethodDef,
        TableNumber.TypeSpec: MemberRefParent.TypeSpec,
    }

    def TypeDef(self) -> "TypeDef":
        return self.get_row(TableNumber.TypeDef)

    def TypeRef(self) -> "TypeRef":
        return self.get_row(TableNumber.TypeRef)

    def ModuleRef(self) -> "ModuleRef":
        return self.get_row(TableNumber.ModuleRef)

    def MethodDef(self) -> "MethodDef":
        return self.get_row(TableNumber.MethodDef)

    def TypeSpec(self) -> "TypeSpec":
        return self.get_row(TableNumber.TypeSpec)


class coded_index_HasSemantics(coded_index[HasSemantics, "_HasSemanticsRows"]):
    """A HasSemantics column: an Event or a Property."""

    __slots__ = ()
    _enum = HasSemantics
    _tables = (TableNumber.Event, TableNumber.Property)
    _bits = 1
    _mask = 0b1
    _tags = {
        TableNumber.Event: HasSemantics.Event,
        TableNumber.Property: HasSemantics.Property,
    }

    def Event(self) -> "Event":
        return self.get_row(TableNumber.Event)

    def Property(self) -> "Property":
        return self.get_row(TableNumber.Property)


class coded_index_MethodDefOrRef(coded_index[MethodDefOrRef, "_MethodDefOrRefRows"]):
    """A MethodDefOrRef column: a MethodDef or a MemberRef."""

    __slots__ = ()
    _enum = MethodDefOrRef
    _tables = (TableNumber.MethodDef, TableNumber.MemberRef)
    _bits = 1
    _mask = 0b1
    _tags = {
        TableNumber.MethodDef: MethodDefOrRef.MethodDef,
        TableNumber.MemberRef: MethodDefOrRef.MemberRef,
    }

    def MethodDef(self) -> "MethodDef":
        return self.get_row(TableNumber.MethodDef)

    def MemberRef(self) -> "MemberRef":
        return self.get_row(TableNumber.MemberRef)


class coded_index_MemberForwarded(coded_index[MemberForwarded, "_MemberForwardedRows"]):
    """A MemberForwarded column: what an ImplMap row forwards."""

    __slots__ = ()
    _enum = MemberForwarded
    _tables = (TableNumber.Field, TableNumber.MethodDef)
    _bits = 1
    _mask = 0b1
    _tags = {
        TableNumber.Field: MemberForwarded.Field,
        TableNumber.MethodDef: MemberForwarded.MethodDef,
    }

    def Field(self) -> "Field":
        return self.get_row(TableNumber.Field)

    def MethodDef(self) -> "MethodDef":
        return self.get_row(TableNumber.MethodDef)


class coded_index_Implementation(coded_index[Implementation, "_ImplementationRows"]):
    """An Implementation column: a File, an AssemblyRef or an ExportedType."""

    __slots__ = ()
    _enum = Implementation
    _tables = (
        TableNumber.File,
        TableNumber.AssemblyRef,
        TableNumber.ExportedType,
    )
    _bits = 2
    _mask = 0b11
    _tags = {
        TableNumber.File: Implementation.File,
        TableNumber.AssemblyRef: Implementation.AssemblyRef,
        TableNumber.ExportedType: Implementation.ExportedType,
    }

    def File(self) -> "File":
        return self.get_row(TableNumber.File)

    def AssemblyRef(self) -> "AssemblyRef":
        return self.get_row(TableNumber.AssemblyRef)

    def ExportedType(self) -> "ExportedType":
        return self.get_row(TableNumber.ExportedType)


class coded_index_CustomAttributeType(
    coded_index[CustomAttributeType, "_CustomAttributeTypeRows"]
):
    """A CustomAttributeType column: the attribute's constructor."""

    __slots__ = ()
    _enum = CustomAttributeType
    _tables = (None, None, TableNumber.MethodDef, TableNumber.MemberRef, None)
    _bits = 3
    _mask = 0b111
    _tags = {
        TableNumber.MethodDef: CustomAttributeType.MethodDef,
        TableNumber.MemberRef: CustomAttributeType.MemberRef,
    }

    def MethodDef(self) -> "MethodDef":
        return self.get_row(TableNumber.MethodDef)

    def MemberRef(self) -> "MemberRef":
        return self.get_row(TableNumber.MemberRef)


class coded_index_ResolutionScope(coded_index[ResolutionScope, "_ResolutionScopeRows"]):
    """A ResolutionScope column: where a TypeRef is to be looked for."""

    __slots__ = ()
    _enum = ResolutionScope
    _tables = (
        TableNumber.Module,
        TableNumber.ModuleRef,
        TableNumber.AssemblyRef,
        TableNumber.TypeRef,
    )
    _bits = 2
    _mask = 0b11
    _tags = {
        TableNumber.Module: ResolutionScope.Module,
        TableNumber.ModuleRef: ResolutionScope.ModuleRef,
        TableNumber.AssemblyRef: ResolutionScope.AssemblyRef,
        TableNumber.TypeRef: ResolutionScope.TypeRef,
    }

    def Module(self) -> "Module":
        return self.get_row(TableNumber.Module)

    def ModuleRef(self) -> "ModuleRef":
        return self.get_row(TableNumber.ModuleRef)

    def AssemblyRef(self) -> "AssemblyRef":
        return self.get_row(TableNumber.AssemblyRef)

    def TypeRef(self) -> "TypeRef":
        return self.get_row(TableNumber.TypeRef)


class coded_index_TypeOrMethodDef(coded_index[TypeOrMethodDef, "_TypeOrMethodDefRows"]):
    """A TypeOrMethodDef column: what a GenericParam belongs to."""

    __slots__ = ()
    _enum = TypeOrMethodDef
    _tables = (TableNumber.TypeDef, TableNumber.MethodDef)
    _bits = 1
    _mask = 0b1
    _tags = {
        TableNumber.TypeDef: TypeOrMethodDef.TypeDef,
        TableNumber.MethodDef: TypeOrMethodDef.MethodDef,
    }

    def TypeDef(self) -> "TypeDef":
        return self.get_row(TableNumber.TypeDef)

    def MethodDef(self) -> "MethodDef":
        return self.get_row(TableNumber.MethodDef)
