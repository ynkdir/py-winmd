"""The rows, as schema.h and column.h have them.

One class per table, holding that table's accessors and no others, plus the
ranges a list column hands back.
"""

from __future__ import annotations

import collections.abc
import struct
from collections.abc import Sequence
from typing import TYPE_CHECKING, NamedTuple, TypeVar, overload

from .enum import (
    AssemblyHashAlgorithm,
    ConstantType,
    CustomAttributeType,
    TableNumber,
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
from .index import (
    CodedT,
    coded_index,
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
from .signature import (
    CustomAttributeSig,
    EnumDefinition,
    FieldSig,
    MethodDefSig,
    PropertySig,
    TypeSpecSig,
)
from .view import byte_view

if TYPE_CHECKING:
    from .cache import cache
    from .database import database


# --- rows -----------------------------------------------------------------
# What a range, a list and a table hold: `RowRange[MethodDef]` is what
# `TypeDef.MethodList()` returns, as `std::pair<MethodDef, MethodDef>` is in C++.
RowT = TypeVar("RowT", bound="Row")


class RowRange(Sequence[RowT]):
    """A member list: the rows of a table from one index to another."""

    __slots__ = ("_database", "_class", "_first", "_last")

    def __init__(
        self, database: database, row_class: type[RowT], first: int, last: int
    ) -> None:
        self._database = database
        self._class = row_class
        self._first = first
        self._last = last

    def __len__(self) -> int:
        return max(0, self._last - self._first)

    def size(self) -> int:
        return len(self)

    def empty(self) -> bool:
        return not len(self)

    @property
    def first(self) -> RowT:
        return self._class(self._database, self._first)

    @property
    def second(self) -> RowT:
        return self._class(self._database, self._last)

    @overload
    def __getitem__(self, index: int) -> RowT: ...
    @overload
    def __getitem__(self, index: slice) -> list[RowT]: ...

    def __getitem__(self, index: int | slice) -> RowT | list[RowT]:
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return self._class(self._database, self._first + index)

    def __repr__(self) -> str:
        return f"<{self._class.__name__}_range {len(self)}>"


class AssemblyVersion(NamedTuple):
    """The four numbers of an assembly version, as the C++ struct has them."""

    MajorVersion: int
    MinorVersion: int
    BuildNumber: int
    RevisionNumber: int


class RowList(Sequence[RowT]):
    """Rows of a table that are not next to each other."""

    __slots__ = ("_database", "_class", "_indexes")

    def __init__(
        self, database: database, row_class: type[RowT], indexes: list[int]
    ) -> None:
        self._database = database
        self._class = row_class
        self._indexes = indexes

    def __len__(self) -> int:
        return len(self._indexes)

    @overload
    def __getitem__(self, index: int) -> RowT: ...
    @overload
    def __getitem__(self, index: slice) -> list[RowT]: ...

    def __getitem__(self, index: int | slice) -> RowT | list[RowT]:
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        return self._class(self._database, self._indexes[index])

    def __repr__(self) -> str:
        return f"<{self._class.__name__}_list {len(self)}>"


# The class of each table, filled in by the subclasses below.
_ROW_CLASSES: dict[TableNumber, type] = {}


class Row:
    """One row of one table.

    A row is a value: the database and the index. Which table it is from is
    the class it is - one per table below, holding the accessors that table
    has, as the C++ has a struct per table.
    """

    __slots__ = ("_database", "_index", "_columns")

    _table: TableNumber

    def __init_subclass__(cls, **kwargs) -> None:
        """A subclass is one table, and is the class of that table's rows."""
        super().__init_subclass__(**kwargs)
        assert cls._table.name == cls.__name__, cls.__name__
        _ROW_CLASSES[cls._table] = cls

    def __init__(self, database: database, index: int) -> None:
        self._database = database
        self._index = index
        self._columns: tuple[int, ...] | None = None

    # --- the basics
    def index(self) -> int:
        return self._index

    def get_database(self) -> database:
        return self._database

    def get_cache(self) -> cache:
        return self._database.get_cache()

    def get_value(self, column: int) -> int:
        if self._columns is None:
            if not self:
                raise RuntimeError(f"{self._table.name}[{self._index}] is not a row")
            self._columns = self._database.row(self._table, self._index)
        return self._columns[column]

    def __bool__(self) -> bool:
        return self._index >= 0 and self._index < self._database.rows(self._table)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Row)
            and self._table == other._table
            and self._index == other._index
            and self._database is other._database
        )

    def __lt__(self, other: Row) -> bool:
        return self._index < other._index

    def __le__(self, other: Row) -> bool:
        return self._index <= other._index

    def __gt__(self, other: Row) -> bool:
        return self._index > other._index

    def __ge__(self, other: Row) -> bool:
        return self._index >= other._index

    # A row is an iterator over its own table in C++, and these come with that.
    def __add__(self, offset: int) -> Row:
        return type(self)(self._database, self._index + offset)

    def __sub__(self, other: Row | int) -> int | Row:
        if isinstance(other, Row):
            return self._index - other._index
        return type(self)(self._database, self._index - other)

    def __hash__(self) -> int:
        return hash((id(self._database), self._table, self._index))

    def __repr__(self) -> str:
        return f"<{self._table.name}[{self._index}]>"

    # --- what the columns mean
    def _string(self, column: int) -> str:
        return self._database.string(self.get_value(column))

    def _blob(self, column: int) -> byte_view:
        return self._database.blob(self.get_value(column))

    def _coded(self, column: int, kind: type[CodedT]) -> CodedT:
        """One column, as `coded_index_TypeDefOrRef` or whichever kind it is."""
        return kind(self._database, self.get_value(column))

    def _row(self, column: int, row_class: type[RowT]) -> RowT:
        return row_class(self._database, self.get_value(column) - 1)

    def _list(self, column: int, row_class: type[RowT]) -> RowRange[RowT]:
        """my first child until the next row's first child."""
        first = self.get_value(column) - 1
        if self._index + 1 < self._database.rows(self._table):
            last = self._database.row(self._table, self._index + 1)[column] - 1
        else:
            last = self._database.rows(row_class._table)
        return RowRange(self._database, row_class, first, last)

    # --- the other direction: rows whose coded index column points at me
    def _referrers(
        self, kind: type[coded_index], row_class: "type[RowT]", column: int
    ) -> Sequence[RowT]:
        return self._database.equal_range(
            row_class, column, kind.encode(self._table, self._index)
        )

    def _referrer(
        self, kind: type[coded_index], row_class: "type[RowT]", column: int
    ) -> RowT | None:
        return self._database.find_row(
            row_class, column, kind.encode(self._table, self._index)
        )

    def _attributes(self) -> Sequence[CustomAttribute]:
        """The attributes applied to me, which most tables can carry."""
        return self._referrers(coded_index_HasCustomAttribute, CustomAttribute, 0)

    def _constant(self) -> Constant:
        row = self._referrer(coded_index_HasConstant, Constant, 1)
        if not row:
            raise RuntimeError("there is no constant for this row")
        return row

    def _version(self, column: int) -> AssemblyVersion:
        """Four uint16 in one column, which no accessor of ours can read."""
        offset, _ = self._database._columns[self._table][column]
        start = (
            self._database._start[self._table]
            + self._index * self._database._row_size[self._table]
            + offset
        )
        return AssemblyVersion(
            *struct.unpack_from("<HHHH", self._database._tables, start)
        )


# --- one class per table, with the accessors that table has ----------------
class Module(Row):
    """A row of the Module table."""

    __slots__ = ()
    _table = TableNumber.Module

    def Generation(self) -> int:
        return self.get_value(0)

    def Name(self) -> str:
        return self._string(1)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class TypeRef(Row):
    """A row of the TypeRef table."""

    __slots__ = ()
    _table = TableNumber.TypeRef

    def ResolutionScope(self) -> coded_index_ResolutionScope:
        return self._coded(0, coded_index_ResolutionScope)

    def TypeName(self) -> str:
        return self._string(1)

    def TypeNamespace(self) -> str:
        return self._string(2)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class TypeDef(Row):
    """A row of the TypeDef table."""

    __slots__ = ()
    _table = TableNumber.TypeDef

    def Flags(self) -> TypeAttributes:
        return TypeAttributes(self.get_value(0))

    def TypeName(self) -> str:
        return self._string(1)

    def TypeNamespace(self) -> str:
        return self._string(2)

    def Extends(self) -> coded_index_TypeDefOrRef:
        return self._coded(3, coded_index_TypeDefOrRef)

    def FieldList(self) -> RowRange[Field]:
        return self._list(4, Field)

    def MethodList(self) -> RowRange[MethodDef]:
        return self._list(5, MethodDef)

    def InterfaceImpl(self) -> Sequence[InterfaceImpl]:
        return self._database.equal_range(InterfaceImpl, 0, self._index + 1)

    def MethodImplList(self) -> Sequence[MethodImpl]:
        return self._database.equal_range(MethodImpl, 0, self._index + 1)

    def PropertyList(self) -> RowRange[Property]:
        mapping = self._database.find_row(PropertyMap, 0, self._index + 1)
        return (
            mapping.PropertyList()
            if mapping
            else RowRange(self._database, Property, 0, 0)
        )

    def EventList(self) -> RowRange[Event]:
        mapping = self._database.find_row(EventMap, 0, self._index + 1)
        return mapping.EventList() if mapping else RowRange(self._database, Event, 0, 0)

    def GenericParam(self) -> Sequence[GenericParam]:
        return self._referrers(coded_index_TypeOrMethodDef, GenericParam, 2)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()

    def EnclosingType(self) -> TypeDef:
        nested = self._database.find_row(NestedClass, 0, self._index + 1)
        if not nested:
            raise RuntimeError("the type is not nested")
        return nested.EnclosingType()

    def is_enum(self) -> bool:
        # helpers.py is built on the rows here, so the two only meet at a
        # call, which is where the import goes.
        from .helpers import extends_type

        return extends_type(self, "System", "Enum")

    def get_enum_definition(self) -> EnumDefinition:
        return EnumDefinition(self)


class Field(Row):
    """A row of the Field table."""

    __slots__ = ()
    _table = TableNumber.Field

    def Flags(self) -> FieldAttributes:
        return FieldAttributes(self.get_value(0))

    def Name(self) -> str:
        return self._string(1)

    def Signature(self) -> FieldSig:
        return FieldSig(self._blob(2))

    def Parent(self) -> TypeDef:
        return self._database.parent_row(TypeDef, 4, self._index)

    def Constant(self) -> Constant:
        return self._constant()

    def FieldMarshal(self) -> FieldMarshal | None:
        return self._referrer(coded_index_HasFieldMarshal, FieldMarshal, 0)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class MethodDef(Row):
    """A row of the MethodDef table."""

    __slots__ = ()
    _table = TableNumber.MethodDef

    def RVA(self) -> int:
        return self.get_value(0)

    def ImplFlags(self) -> MethodImplAttributes:
        return MethodImplAttributes(self.get_value(1))

    def Flags(self) -> MethodAttributes:
        return MethodAttributes(self.get_value(2))

    def Name(self) -> str:
        return self._string(3)

    def Signature(self) -> MethodDefSig:
        return MethodDefSig(self._blob(4))

    def ParamList(self) -> RowRange[Param]:
        return self._list(5, Param)

    def Parent(self) -> TypeDef:
        return self._database.parent_row(TypeDef, 5, self._index)

    def GenericParam(self) -> Sequence[GenericParam]:
        return self._referrers(coded_index_TypeOrMethodDef, GenericParam, 2)

    def SpecialName(self) -> bool:
        """MethodDef.Flags().SpecialName(), which the C++ side also shortens."""
        return self.Flags().SpecialName()

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class Param(Row):
    """A row of the Param table."""

    __slots__ = ()
    _table = TableNumber.Param

    def Flags(self) -> ParamAttributes:
        return ParamAttributes(self.get_value(0))

    def Sequence(self) -> int:
        return self.get_value(1)

    def Name(self) -> str:
        return self._string(2)

    def Parent(self) -> MethodDef:
        return self._database.parent_row(MethodDef, 5, self._index)

    def Constant(self) -> Constant:
        return self._constant()

    def FieldMarshal(self) -> FieldMarshal | None:
        return self._referrer(coded_index_HasFieldMarshal, FieldMarshal, 0)

    # Sequence is this row's own accessor, so the one meant is spelled out.
    def CustomAttribute(self) -> collections.abc.Sequence[CustomAttribute]:
        return self._attributes()


class InterfaceImpl(Row):
    """A row of the InterfaceImpl table."""

    __slots__ = ()
    _table = TableNumber.InterfaceImpl

    def Class(self) -> TypeDef:
        return self._row(0, TypeDef)

    def Interface(self) -> coded_index_TypeDefOrRef:
        return self._coded(1, coded_index_TypeDefOrRef)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class MemberRef(Row):
    """A row of the MemberRef table."""

    __slots__ = ()
    _table = TableNumber.MemberRef

    def Class(self) -> coded_index_MemberRefParent:
        return self._coded(0, coded_index_MemberRefParent)

    def Name(self) -> str:
        return self._string(1)

    def MethodSignature(self) -> MethodDefSig:
        return MethodDefSig(self._blob(2))

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class Constant(Row):
    """A row of the Constant table."""

    __slots__ = ()
    _table = TableNumber.Constant

    def Type(self) -> ConstantType:
        return ConstantType(self.get_value(0))

    def Parent(self) -> coded_index_HasConstant:
        return self._coded(1, coded_index_HasConstant)

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
    _table = TableNumber.CustomAttribute

    def Parent(self) -> coded_index_HasCustomAttribute:
        return self._coded(0, coded_index_HasCustomAttribute)

    def Type(self) -> coded_index_CustomAttributeType:
        return self._coded(1, coded_index_CustomAttributeType)

    def Value(self) -> CustomAttributeSig:
        constructor = self.Type()
        if constructor.type() is CustomAttributeType.MemberRef:
            reference = MemberRef(self._database, constructor.index())
            signature = MethodDefSig(reference._blob(2))
        else:
            signature = MethodDef(self._database, constructor.index()).Signature()
        return CustomAttributeSig(self._database, self._blob(2), signature)

    def TypeNamespaceAndName(self) -> tuple[str, str]:
        """The namespace and name of the attribute this row applies.

        Cached by the constructor it names. A file applies far more attributes
        than it has kinds of them, so remembering the answer is most of what
        makes building a cache of the Win32 metadata quick.
        """
        constructor = self.get_value(1)
        names = self._database._attribute_names
        found = names.get(constructor)
        if found is None:
            index = coded_index_CustomAttributeType(self._database, constructor)
            if index.type() is CustomAttributeType.MemberRef:
                from .helpers import get_type_namespace_and_name

                member = MemberRef(self._database, index.index())
                found = get_type_namespace_and_name(member.Class())
            else:
                parent = MethodDef(self._database, index.index()).Parent()
                found = (parent.TypeNamespace(), parent.TypeName())
            names[constructor] = found
        return found


class FieldMarshal(Row):
    """A row of the FieldMarshal table."""

    __slots__ = ()
    _table = TableNumber.FieldMarshal

    def Parent(self) -> coded_index_HasFieldMarshal:
        return self._coded(0, coded_index_HasFieldMarshal)


class DeclSecurity(Row):
    """A row of the DeclSecurity table."""

    __slots__ = ()
    _table = TableNumber.DeclSecurity


class ClassLayout(Row):
    """A row of the ClassLayout table."""

    __slots__ = ()
    _table = TableNumber.ClassLayout

    def PackingSize(self) -> int:
        return self.get_value(0)

    def ClassSize(self) -> int:
        return self.get_value(1)

    def Parent(self) -> TypeDef:
        return self._row(2, TypeDef)


class FieldLayout(Row):
    """A row of the FieldLayout table."""

    __slots__ = ()
    _table = TableNumber.FieldLayout


class StandAloneSig(Row):
    """A row of the StandAloneSig table."""

    __slots__ = ()
    _table = TableNumber.StandAloneSig

    def Signature(self) -> byte_view:
        return self._blob(0)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class EventMap(Row):
    """A row of the EventMap table."""

    __slots__ = ()
    _table = TableNumber.EventMap

    def Parent(self) -> TypeDef:
        return self._row(0, TypeDef)

    def EventList(self) -> RowRange[Event]:
        return self._list(1, Event)


class Event(Row):
    """A row of the Event table."""

    __slots__ = ()
    _table = TableNumber.Event

    def EventFlags(self) -> EventAttributes:
        return EventAttributes(self.get_value(0))

    def Name(self) -> str:
        return self._string(1)

    def EventType(self) -> coded_index_TypeDefOrRef:
        return self._coded(2, coded_index_TypeDefOrRef)

    def Parent(self) -> TypeDef:
        mapping = self._database.parent_row(EventMap, 1, self._index)
        return mapping.Parent()

    def MethodSemantic(self) -> Sequence[MethodSemantics]:
        return self._referrers(coded_index_HasSemantics, MethodSemantics, 2)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class PropertyMap(Row):
    """A row of the PropertyMap table."""

    __slots__ = ()
    _table = TableNumber.PropertyMap

    def Parent(self) -> TypeDef:
        return self._row(0, TypeDef)

    def PropertyList(self) -> RowRange[Property]:
        return self._list(1, Property)


class Property(Row):
    """A row of the Property table."""

    __slots__ = ()
    _table = TableNumber.Property

    def Flags(self) -> PropertyAttributes:
        return PropertyAttributes(self.get_value(0))

    def Name(self) -> str:
        return self._string(1)

    def Type(self) -> PropertySig:
        return PropertySig(self._blob(2))

    def Parent(self) -> TypeDef:
        mapping = self._database.parent_row(PropertyMap, 1, self._index)
        return mapping.Parent()

    def Constant(self) -> Constant:
        return self._constant()

    def MethodSemantic(self) -> Sequence[MethodSemantics]:
        return self._referrers(coded_index_HasSemantics, MethodSemantics, 2)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class MethodSemantics(Row):
    """A row of the MethodSemantics table."""

    __slots__ = ()
    _table = TableNumber.MethodSemantics

    def Semantic(self) -> MethodSemanticsAttributes:
        return MethodSemanticsAttributes(self.get_value(0))

    def Method(self) -> MethodDef:
        return self._row(1, MethodDef)

    def Association(self) -> coded_index_HasSemantics:
        return self._coded(2, coded_index_HasSemantics)


class MethodImpl(Row):
    """A row of the MethodImpl table."""

    __slots__ = ()
    _table = TableNumber.MethodImpl

    def Class(self) -> TypeDef:
        return self._row(0, TypeDef)


class ModuleRef(Row):
    """A row of the ModuleRef table."""

    __slots__ = ()
    _table = TableNumber.ModuleRef

    def Name(self) -> str:
        return self._string(0)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class TypeSpec(Row):
    """A row of the TypeSpec table."""

    __slots__ = ()
    _table = TableNumber.TypeSpec

    def Signature(self) -> TypeSpecSig:
        return TypeSpecSig(self._blob(0))

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class ImplMap(Row):
    """A row of the ImplMap table.

    The C++ reader has no accessors for this table; these are ours.
    """

    __slots__ = ()
    _table = TableNumber.ImplMap

    def MappingFlags(self) -> PInvokeAttributes:
        return PInvokeAttributes(self.get_value(0))

    def MemberForwarded(self) -> coded_index_MemberForwarded:
        return self._coded(1, coded_index_MemberForwarded)

    def ImportName(self) -> str:
        return self._string(2)

    def ImportScope(self) -> ModuleRef:
        return self._row(3, ModuleRef)


class FieldRVA(Row):
    """A row of the FieldRVA table."""

    __slots__ = ()
    _table = TableNumber.FieldRVA


class Assembly(Row):
    """A row of the Assembly table."""

    __slots__ = ()
    _table = TableNumber.Assembly

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
    _table = TableNumber.AssemblyProcessor


class AssemblyOS(Row):
    """A row of the AssemblyOS table."""

    __slots__ = ()
    _table = TableNumber.AssemblyOS


class AssemblyRef(Row):
    """A row of the AssemblyRef table."""

    __slots__ = ()
    _table = TableNumber.AssemblyRef

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
    _table = TableNumber.AssemblyRefProcessor


class AssemblyRefOS(Row):
    """A row of the AssemblyRefOS table."""

    __slots__ = ()
    _table = TableNumber.AssemblyRefOS


class File(Row):
    """A row of the File table."""

    __slots__ = ()
    _table = TableNumber.File

    def Name(self) -> str:
        return self._string(1)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class ExportedType(Row):
    """A row of the ExportedType table."""

    __slots__ = ()
    _table = TableNumber.ExportedType

    def Flags(self) -> _Flags:
        return _Flags(self.get_value(0))

    def Name(self) -> str:
        return self._string(3)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class ManifestResource(Row):
    """A row of the ManifestResource table."""

    __slots__ = ()
    _table = TableNumber.ManifestResource

    def Flags(self) -> _Flags:
        return _Flags(self.get_value(1))

    def Name(self) -> str:
        return self._string(2)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class NestedClass(Row):
    """A row of the NestedClass table."""

    __slots__ = ()
    _table = TableNumber.NestedClass

    def NestedType(self) -> TypeDef:
        return self._row(0, TypeDef)

    def EnclosingType(self) -> TypeDef:
        return self._row(1, TypeDef)


class GenericParam(Row):
    """A row of the GenericParam table."""

    __slots__ = ()
    _table = TableNumber.GenericParam

    def Number(self) -> int:
        return self.get_value(0)

    def Flags(self) -> GenericParamAttributes:
        return GenericParamAttributes(self.get_value(1))

    def Owner(self) -> coded_index_TypeOrMethodDef:
        return self._coded(2, coded_index_TypeOrMethodDef)

    def Name(self) -> str:
        return self._string(3)

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class MethodSpec(Row):
    """A row of the MethodSpec table."""

    __slots__ = ()
    _table = TableNumber.MethodSpec

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


class GenericParamConstraint(Row):
    """A row of the GenericParamConstraint table."""

    __slots__ = ()
    _table = TableNumber.GenericParamConstraint

    def CustomAttribute(self) -> Sequence[CustomAttribute]:
        return self._attributes()


def make_row(database: database, table: TableNumber, index: int) -> Row:
    """A row of any table, for when the table is only known at run time."""
    return _ROW_CLASSES[table](database, index)


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
