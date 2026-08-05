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
from .table import coded_index


# One class per kind, as the C++ template gives one type per kind:
# coded_index<TypeDefOrRef> is coded_index_TypeDefOrRef.
class coded_index_TypeDefOrRef(coded_index):
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

    if TYPE_CHECKING:

        def type(self) -> TypeDefOrRef: ...

    def TypeDef(self) -> "TypeDef":
        return self.get_row(TypeDef)

    def TypeRef(self) -> "TypeRef":
        return self.get_row(TypeRef)

    def TypeSpec(self) -> "TypeSpec":
        return self.get_row(TypeSpec)

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


class coded_index_HasConstant(coded_index):
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

    if TYPE_CHECKING:

        def type(self) -> HasConstant: ...

    def Field(self) -> "Field":
        return self.get_row(Field)

    def Param(self) -> "Param":
        return self.get_row(Param)

    def Property(self) -> "Property":
        return self.get_row(Property)


class coded_index_HasCustomAttribute(coded_index):
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

    if TYPE_CHECKING:

        def type(self) -> HasCustomAttribute: ...

    def MethodDef(self) -> "MethodDef":
        return self.get_row(MethodDef)

    def Field(self) -> "Field":
        return self.get_row(Field)

    def TypeRef(self) -> "TypeRef":
        return self.get_row(TypeRef)

    def TypeDef(self) -> "TypeDef":
        return self.get_row(TypeDef)

    def Param(self) -> "Param":
        return self.get_row(Param)

    def InterfaceImpl(self) -> "InterfaceImpl":
        return self.get_row(InterfaceImpl)

    def MemberRef(self) -> "MemberRef":
        return self.get_row(MemberRef)

    def Module(self) -> "Module":
        return self.get_row(Module)

    def DeclSecurity(self) -> "DeclSecurity":
        return self.get_row(DeclSecurity)

    def Property(self) -> "Property":
        return self.get_row(Property)

    def Event(self) -> "Event":
        return self.get_row(Event)

    def StandAloneSig(self) -> "StandAloneSig":
        return self.get_row(StandAloneSig)

    def ModuleRef(self) -> "ModuleRef":
        return self.get_row(ModuleRef)

    def TypeSpec(self) -> "TypeSpec":
        return self.get_row(TypeSpec)

    def Assembly(self) -> "Assembly":
        return self.get_row(Assembly)

    def AssemblyRef(self) -> "AssemblyRef":
        return self.get_row(AssemblyRef)

    def File(self) -> "File":
        return self.get_row(File)

    def ExportedType(self) -> "ExportedType":
        return self.get_row(ExportedType)

    def ManifestResource(self) -> "ManifestResource":
        return self.get_row(ManifestResource)

    def GenericParam(self) -> "GenericParam":
        return self.get_row(GenericParam)

    def GenericParamConstraint(self) -> "GenericParamConstraint":
        return self.get_row(GenericParamConstraint)

    def MethodSpec(self) -> "MethodSpec":
        return self.get_row(MethodSpec)


class coded_index_HasFieldMarshal(coded_index):
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

    if TYPE_CHECKING:

        def type(self) -> HasFieldMarshal: ...

    def Field(self) -> "Field":
        return self.get_row(Field)

    def Param(self) -> "Param":
        return self.get_row(Param)


class coded_index_HasDeclSecurity(coded_index):
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

    if TYPE_CHECKING:

        def type(self) -> HasDeclSecurity: ...

    def TypeDef(self) -> "TypeDef":
        return self.get_row(TypeDef)

    def MethodDef(self) -> "MethodDef":
        return self.get_row(MethodDef)

    def Assembly(self) -> "Assembly":
        return self.get_row(Assembly)


class coded_index_MemberRefParent(coded_index):
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

    if TYPE_CHECKING:

        def type(self) -> MemberRefParent: ...

    def TypeDef(self) -> "TypeDef":
        return self.get_row(TypeDef)

    def TypeRef(self) -> "TypeRef":
        return self.get_row(TypeRef)

    def ModuleRef(self) -> "ModuleRef":
        return self.get_row(ModuleRef)

    def MethodDef(self) -> "MethodDef":
        return self.get_row(MethodDef)

    def TypeSpec(self) -> "TypeSpec":
        return self.get_row(TypeSpec)


class coded_index_HasSemantics(coded_index):
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

    if TYPE_CHECKING:

        def type(self) -> HasSemantics: ...

    def Event(self) -> "Event":
        return self.get_row(Event)

    def Property(self) -> "Property":
        return self.get_row(Property)


class coded_index_MethodDefOrRef(coded_index):
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

    if TYPE_CHECKING:

        def type(self) -> MethodDefOrRef: ...

    def MethodDef(self) -> "MethodDef":
        return self.get_row(MethodDef)

    def MemberRef(self) -> "MemberRef":
        return self.get_row(MemberRef)


class coded_index_MemberForwarded(coded_index):
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

    if TYPE_CHECKING:

        def type(self) -> MemberForwarded: ...

    def Field(self) -> "Field":
        return self.get_row(Field)

    def MethodDef(self) -> "MethodDef":
        return self.get_row(MethodDef)


class coded_index_Implementation(coded_index):
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

    if TYPE_CHECKING:

        def type(self) -> Implementation: ...

    def File(self) -> "File":
        return self.get_row(File)

    def AssemblyRef(self) -> "AssemblyRef":
        return self.get_row(AssemblyRef)

    def ExportedType(self) -> "ExportedType":
        return self.get_row(ExportedType)


class coded_index_CustomAttributeType(coded_index):
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

    if TYPE_CHECKING:

        def type(self) -> CustomAttributeType: ...

    def MethodDef(self) -> "MethodDef":
        return self.get_row(MethodDef)

    def MemberRef(self) -> "MemberRef":
        return self.get_row(MemberRef)


class coded_index_ResolutionScope(coded_index):
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

    if TYPE_CHECKING:

        def type(self) -> ResolutionScope: ...

    def Module(self) -> "Module":
        return self.get_row(Module)

    def ModuleRef(self) -> "ModuleRef":
        return self.get_row(ModuleRef)

    def AssemblyRef(self) -> "AssemblyRef":
        return self.get_row(AssemblyRef)

    def TypeRef(self) -> "TypeRef":
        return self.get_row(TypeRef)


class coded_index_TypeOrMethodDef(coded_index):
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

    if TYPE_CHECKING:

        def type(self) -> TypeOrMethodDef: ...

    def TypeDef(self) -> "TypeDef":
        return self.get_row(TypeDef)

    def MethodDef(self) -> "MethodDef":
        return self.get_row(MethodDef)
