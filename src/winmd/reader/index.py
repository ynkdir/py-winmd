"""The coded indexes, as table.h, enum_traits.h and index.h have them.

A column that may point at one of several tables: a tag and a one-based row
number packed together. One class per kind, each stating its tables and its
tag width and carrying an accessor per table it can name.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

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


# One class per kind, as the C++ template gives one type per kind:
# coded_index<TypeDefOrRef> is coded_index_TypeDefOrRef.
class coded_index_TypeDefOrRef(coded_index[TypeDefOrRef]):
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
        return self._as(schema.TypeDef)

    def TypeRef(self) -> "TypeRef":
        return self._as(schema.TypeRef)

    def TypeSpec(self) -> "TypeSpec":
        return self._as(schema.TypeSpec)

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


class coded_index_HasConstant(coded_index[HasConstant]):
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
        return self._as(schema.Field)

    def Param(self) -> "Param":
        return self._as(schema.Param)

    def Property(self) -> "Property":
        return self._as(schema.Property)


class coded_index_HasCustomAttribute(coded_index[HasCustomAttribute]):
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
        return self._as(schema.MethodDef)

    def Field(self) -> "Field":
        return self._as(schema.Field)

    def TypeRef(self) -> "TypeRef":
        return self._as(schema.TypeRef)

    def TypeDef(self) -> "TypeDef":
        return self._as(schema.TypeDef)

    def Param(self) -> "Param":
        return self._as(schema.Param)

    def InterfaceImpl(self) -> "InterfaceImpl":
        return self._as(schema.InterfaceImpl)

    def MemberRef(self) -> "MemberRef":
        return self._as(schema.MemberRef)

    def Module(self) -> "Module":
        return self._as(schema.Module)

    def DeclSecurity(self) -> "DeclSecurity":
        return self._as(schema.DeclSecurity)

    def Property(self) -> "Property":
        return self._as(schema.Property)

    def Event(self) -> "Event":
        return self._as(schema.Event)

    def StandAloneSig(self) -> "StandAloneSig":
        return self._as(schema.StandAloneSig)

    def ModuleRef(self) -> "ModuleRef":
        return self._as(schema.ModuleRef)

    def TypeSpec(self) -> "TypeSpec":
        return self._as(schema.TypeSpec)

    def Assembly(self) -> "Assembly":
        return self._as(schema.Assembly)

    def AssemblyRef(self) -> "AssemblyRef":
        return self._as(schema.AssemblyRef)

    def File(self) -> "File":
        return self._as(schema.File)

    def ExportedType(self) -> "ExportedType":
        return self._as(schema.ExportedType)

    def ManifestResource(self) -> "ManifestResource":
        return self._as(schema.ManifestResource)

    def GenericParam(self) -> "GenericParam":
        return self._as(schema.GenericParam)

    def GenericParamConstraint(self) -> "GenericParamConstraint":
        return self._as(schema.GenericParamConstraint)

    def MethodSpec(self) -> "MethodSpec":
        return self._as(schema.MethodSpec)


class coded_index_HasFieldMarshal(coded_index[HasFieldMarshal]):
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
        return self._as(schema.Field)

    def Param(self) -> "Param":
        return self._as(schema.Param)


class coded_index_HasDeclSecurity(coded_index[HasDeclSecurity]):
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
        return self._as(schema.TypeDef)

    def MethodDef(self) -> "MethodDef":
        return self._as(schema.MethodDef)

    def Assembly(self) -> "Assembly":
        return self._as(schema.Assembly)


class coded_index_MemberRefParent(coded_index[MemberRefParent]):
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
        return self._as(schema.TypeDef)

    def TypeRef(self) -> "TypeRef":
        return self._as(schema.TypeRef)

    def ModuleRef(self) -> "ModuleRef":
        return self._as(schema.ModuleRef)

    def MethodDef(self) -> "MethodDef":
        return self._as(schema.MethodDef)

    def TypeSpec(self) -> "TypeSpec":
        return self._as(schema.TypeSpec)


class coded_index_HasSemantics(coded_index[HasSemantics]):
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
        return self._as(schema.Event)

    def Property(self) -> "Property":
        return self._as(schema.Property)


class coded_index_MethodDefOrRef(coded_index[MethodDefOrRef]):
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
        return self._as(schema.MethodDef)

    def MemberRef(self) -> "MemberRef":
        return self._as(schema.MemberRef)


class coded_index_MemberForwarded(coded_index[MemberForwarded]):
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
        return self._as(schema.Field)

    def MethodDef(self) -> "MethodDef":
        return self._as(schema.MethodDef)


class coded_index_Implementation(coded_index[Implementation]):
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
        return self._as(schema.File)

    def AssemblyRef(self) -> "AssemblyRef":
        return self._as(schema.AssemblyRef)

    def ExportedType(self) -> "ExportedType":
        return self._as(schema.ExportedType)


class coded_index_CustomAttributeType(coded_index[CustomAttributeType]):
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
        return self._as(schema.MethodDef)

    def MemberRef(self) -> "MemberRef":
        return self._as(schema.MemberRef)


class coded_index_ResolutionScope(coded_index[ResolutionScope]):
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
        return self._as(schema.Module)

    def ModuleRef(self) -> "ModuleRef":
        return self._as(schema.ModuleRef)

    def AssemblyRef(self) -> "AssemblyRef":
        return self._as(schema.AssemblyRef)

    def TypeRef(self) -> "TypeRef":
        return self._as(schema.TypeRef)


class coded_index_TypeOrMethodDef(coded_index[TypeOrMethodDef]):
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
        return self._as(schema.TypeDef)

    def MethodDef(self) -> "MethodDef":
        return self._as(schema.MethodDef)


# The rows a tag can name are defined on schema.py, which is built on the
# classes above. Taking the module rather than the names means this works
# whichever of the two is imported first: a partially initialised module can
# still be bound, and every use below is a call, by which time it is whole.
from . import schema  # noqa: E402
