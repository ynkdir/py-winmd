"""The coded indexes, as table.h, enum_traits.h and index.h have them.

A column that may point at one of several tables: a tag and a one-based row
number packed together. One class per kind, each stating its tables and its
tag width and carrying an accessor per table it can name.
"""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from .enum import (
    CustomAttributeType,
    HasConstant,
    HasCustomAttribute,
    HasDeclSecurity,
    HasFieldMarshal,
    HasSemantics,
    Implementation,
    IntEnum,
    MemberForwarded,
    MemberRefParent,
    MethodDefOrRef,
    ResolutionScope,
    TableNumber,
    TypeDefOrRef,
    TypeOrMethodDef,
)

if TYPE_CHECKING:
    from .database import database
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
        Row,
        RowT,
        StandAloneSig,
        TypeDef,
        TypeRef,
        TypeSpec,
    )


# --- coded indexes --------------------------------------------------------
# The class of each kind, filled in by the subclasses below.
_CODED_CLASSES: dict["builtins.type[IntEnum]", "builtins.type[coded_index[Any]]"] = {}

# The kind a column is of, and the class of a column of that kind:
# `TypeDefOrRef` and `coded_index_TypeDefOrRef`, and the twelve others.
KindT = TypeVar("KindT", bound=IntEnum)
CodedT = TypeVar("CodedT", bound="coded_index")


class coded_index(Generic[KindT]):
    """A column that may point at one of several tables.

    The C++ side is a template, `coded_index<TypeDefOrRef>`, instantiated
    once per kind. Each instantiation is written out below as a class of its
    own: `coded_index_TypeDefOrRef` and the twelve others, each stating its
    tables and its tag width and carrying an accessor per table it can name.
    That is the class a column's values are; the base holds no kind and is
    not one of them.

    The base is generic in the kind, so `type()` is that kind's enum and not
    IntEnum. `coded_index[TypeDefOrRef]` is therefore what it is anywhere
    else in Python - a parameterisation, for annotations - and not a way to
    reach the class. The class is reached by its name.
    """

    __slots__ = ("_database", "_value")

    # A kind has two lists of tables, and they are not the same one.
    #
    # _tables is the tag order: which table each tag value names, `None` for
    # the tags the standard reserves without one. HasCustomAttribute has 22 of
    # them - tag 8 is Permission, the DeclSecurity table - and
    # CustomAttributeType starts at 2. Decode with this.
    #
    # _sizing_tables is the tables whose row counts decide whether the column
    # is 2 or 4 bytes wide, which the C++ writes out per kind as the arguments
    # to composite_index_size. Only HasCustomAttribute states one, because
    # only there do the two lists differ; None means the tag order.
    _enum: builtins.type[KindT]  # the tags, as the C++ enum;
    # its name is the kind's
    _tables: tuple[TableNumber | None, ...]
    _bits: int  # how many bits the tag takes
    _mask: int  # (1 << _bits) - 1
    _sizing_tables: "tuple[TableNumber, ...] | None" = None
    _tags: dict[TableNumber, int]  # _tables the other way
    # round, for encode(); the
    # values are this kind's
    # enumerators, which are ints

    def __init_subclass__(cls, **kwargs) -> None:
        """A subclass states one kind, and is the class of that kind here."""
        super().__init_subclass__(**kwargs)
        # The enum this class states, not one it inherited, and not read
        # off the class object, which is declared in terms of the kind.
        _CODED_CLASSES[cls.__dict__["_enum"]] = cls

    def __init__(self, database: database, value: int) -> None:
        if type(self) is coded_index:
            raise TypeError(
                "the base holds no kind; instantiate one of "
                "coded_index_TypeDefOrRef and the rest"
            )
        self._database = database
        self._value = value

    def type(self) -> KindT:
        """The tag this column holds, as the C++ returns it: this kind's enum.

        Compare it with `is`. Two kinds give the same tag to different
        tables, so `==` cannot tell HasCustomAttribute.MethodDef, which is
        tag 0, from TypeDefOrRef.TypeDef, which is tag 0 as well.
        """
        return self._enum(self._value & self._mask)

    def _table(self) -> TableNumber:
        """The table that tag names. The C++ picks it with a template."""
        table = self._tables[self._value & self._mask]
        if table is None:
            raise ValueError(
                f"tag {self._value & self._mask} of "
                f"{self._enum.__name__} names no table"
            )
        return table

    def index(self) -> int:
        return (self._value >> self._bits) - 1

    @classmethod
    def encode(cls, table: TableNumber, index: int) -> int:
        """What a column of this kind holds to point at that row of that table."""
        return ((index + 1) << cls._bits) | cls._tags[table]

    def kind(self) -> str:
        return self._enum.__name__

    def get_row(self) -> Row:
        return make_row(self._database, self._table(), self.index())

    def _as(self, row_class: builtins.type[RowT]) -> "RowT":
        """What `index.TypeRef()` and the rest below do.

        The C++ spells this get_row<TypeRef>(), and asserts when the index
        points at another table; this raises.
        """
        if not self:
            raise RuntimeError(f"the {self._enum.__name__} index is not set")
        if self._table() is not row_class._table:
            raise TypeError(
                f"the index points at {self._table().name}, not {row_class.__name__}"
            )
        return row_class(self._database, self.index())

    def get_database(self) -> database:
        return self._database

    def __bool__(self) -> bool:
        return self._value != 0

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, coded_index)
            and self._enum is other._enum
            and self._value == other._value
            and self._database is other._database
        )

    def __hash__(self) -> int:
        return hash((self._enum, self._value))

    def __repr__(self) -> str:
        if not self:
            return f"<coded_index {self._enum.__name__} (invalid)>"
        return (
            f"<coded_index {self._enum.__name__} -> "
            f"{self._table().name}[{self.index()}]>"
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
        return self._as(TypeDef)

    def TypeRef(self) -> "TypeRef":
        return self._as(TypeRef)

    def TypeSpec(self) -> "TypeSpec":
        return self._as(TypeSpec)

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
        return self._as(Field)

    def Param(self) -> "Param":
        return self._as(Param)

    def Property(self) -> "Property":
        return self._as(Property)


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
        return self._as(MethodDef)

    def Field(self) -> "Field":
        return self._as(Field)

    def TypeRef(self) -> "TypeRef":
        return self._as(TypeRef)

    def TypeDef(self) -> "TypeDef":
        return self._as(TypeDef)

    def Param(self) -> "Param":
        return self._as(Param)

    def InterfaceImpl(self) -> "InterfaceImpl":
        return self._as(InterfaceImpl)

    def MemberRef(self) -> "MemberRef":
        return self._as(MemberRef)

    def Module(self) -> "Module":
        return self._as(Module)

    def DeclSecurity(self) -> "DeclSecurity":
        return self._as(DeclSecurity)

    def Property(self) -> "Property":
        return self._as(Property)

    def Event(self) -> "Event":
        return self._as(Event)

    def StandAloneSig(self) -> "StandAloneSig":
        return self._as(StandAloneSig)

    def ModuleRef(self) -> "ModuleRef":
        return self._as(ModuleRef)

    def TypeSpec(self) -> "TypeSpec":
        return self._as(TypeSpec)

    def Assembly(self) -> "Assembly":
        return self._as(Assembly)

    def AssemblyRef(self) -> "AssemblyRef":
        return self._as(AssemblyRef)

    def File(self) -> "File":
        return self._as(File)

    def ExportedType(self) -> "ExportedType":
        return self._as(ExportedType)

    def ManifestResource(self) -> "ManifestResource":
        return self._as(ManifestResource)

    def GenericParam(self) -> "GenericParam":
        return self._as(GenericParam)

    def GenericParamConstraint(self) -> "GenericParamConstraint":
        return self._as(GenericParamConstraint)

    def MethodSpec(self) -> "MethodSpec":
        return self._as(MethodSpec)


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
        return self._as(Field)

    def Param(self) -> "Param":
        return self._as(Param)


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
        return self._as(TypeDef)

    def MethodDef(self) -> "MethodDef":
        return self._as(MethodDef)

    def Assembly(self) -> "Assembly":
        return self._as(Assembly)


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
        return self._as(TypeDef)

    def TypeRef(self) -> "TypeRef":
        return self._as(TypeRef)

    def ModuleRef(self) -> "ModuleRef":
        return self._as(ModuleRef)

    def MethodDef(self) -> "MethodDef":
        return self._as(MethodDef)

    def TypeSpec(self) -> "TypeSpec":
        return self._as(TypeSpec)


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
        return self._as(Event)

    def Property(self) -> "Property":
        return self._as(Property)


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
        return self._as(MethodDef)

    def MemberRef(self) -> "MemberRef":
        return self._as(MemberRef)


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
        return self._as(Field)

    def MethodDef(self) -> "MethodDef":
        return self._as(MethodDef)


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
        return self._as(File)

    def AssemblyRef(self) -> "AssemblyRef":
        return self._as(AssemblyRef)

    def ExportedType(self) -> "ExportedType":
        return self._as(ExportedType)


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
        return self._as(MethodDef)

    def MemberRef(self) -> "MemberRef":
        return self._as(MemberRef)


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
        return self._as(Module)

    def ModuleRef(self) -> "ModuleRef":
        return self._as(ModuleRef)

    def AssemblyRef(self) -> "AssemblyRef":
        return self._as(AssemblyRef)

    def TypeRef(self) -> "TypeRef":
        return self._as(TypeRef)


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
        return self._as(TypeDef)

    def MethodDef(self) -> "MethodDef":
        return self._as(MethodDef)


# The rows a tag can name are defined on schema.py, which is built on the
# classes above, so the names they hand back arrive once both are in place.
# This is the C++'s key.h: the bodies come after everything is declared.
from .schema import (  # noqa: E402
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
    Row,
    StandAloneSig,
    TypeDef,
    TypeRef,
    TypeSpec,
    make_row,
)
