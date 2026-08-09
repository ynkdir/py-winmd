"""The machinery the rows and the coded indexes are made of, as table.h has it.

`row_base<Row>`, `index_base<T>`, `coded_index<T>` and `table_base` in the C++:
a row is an index into a table, a coded index is a tag and a row number, and a
table is a sequence of rows. What each of them holds is written out here; which
tables and which kinds there are is written out in schema.py and index.py, and
the two registries below are what those fill in.
"""

from __future__ import annotations

import bisect
import builtins
import struct
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, NamedTuple, TypeVar, overload

from .enum import (
    CodedIndexKind,
    HasConstant,
    HasCustomAttribute,
    TableNumber,
)
from .view import byte_view

if TYPE_CHECKING:
    from .cache import cache
    from .database import database
    from .schema import Constant, CustomAttribute


# --- coded indexes --------------------------------------------------------
# The class of each kind, filled in by the subclasses below.
_CODED_CLASSES: dict["builtins.type[CodedIndexKind]", "builtins.type[coded_index]"] = {}


class coded_index:
    """A column that may point at one of several tables.

    The C++ side is a template, `coded_index<TypeDefOrRef>`, instantiated
    once per kind. Each instantiation is written out below as a class of its
    own: `coded_index_TypeDefOrRef` and the twelve others, each stating its
    tables and its tag width and carrying an accessor per table it can name.
    That is the class a column's values are; the base holds no kind and is
    not one of them.

    A kind is a value here, not a type parameter: the base is not generic,
    and `type()` on it is any of the thirteen. Each kind narrows that to its
    own enum, which is the only thing a parameter would have bought - the
    subscript was never written anywhere but the thirteen class statements,
    and never as an annotation. The class is reached by its name.
    """

    __slots__ = ("_table", "_value")

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
    _enum: builtins.type[CodedIndexKind]  # the tags, as the C++ enum;
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

    def __init__(self, table: table_base, value: int) -> None:
        if type(self) is coded_index:
            raise TypeError(
                "the base holds no kind; instantiate one of "
                "coded_index_TypeDefOrRef and the rest"
            )
        self._table = table
        self._value = value

    @staticmethod
    def of(kind: builtins.type[CodedIndexKind], table: table_base, value: int) -> Any:
        """A column of that kind, holding that value.

        The C++ names the kind as the template argument and constructs the
        class it gets - coded_index<TypeDefOrRef>{ table, value }. Naming it
        as an argument here means a caller needs the kind, which is an enum,
        rather than the class of that kind, which the registry answers for.
        """
        return _CODED_CLASSES[kind](table, value)

    def type(self) -> CodedIndexKind:
        """The tag this column holds, as the C++ returns it: this kind's enum.

        Compare it with `is`. Two kinds give the same tag to different
        tables, so `==` cannot tell HasCustomAttribute.MethodDef, which is
        tag 0, from TypeDefOrRef.TypeDef, which is tag 0 as well.
        """
        return self._enum(self._value & self._mask)

    def _target(self) -> TableNumber:
        """The table that tag names. The C++ picks it with a template."""
        tag = self._value & self._mask
        table = self._tables[tag]
        if table is None:
            raise ValueError(f"tag {tag} of {self._enum.__name__} names no table")
        return table

    def index(self) -> int:
        return (self._value >> self._bits) - 1

    @classmethod
    def encode(cls, table: TableNumber, index: int) -> int:
        """What a column of this kind holds to point at that row of that table."""
        return ((index + 1) << cls._bits) | cls._tags[table]

    def kind(self) -> str:
        return self._enum.__name__

    @overload
    def get_row(self) -> Any: ...
    @overload
    def get_row(self, row_class: builtins.type[RowT]) -> RowT: ...
    def get_row(self, row_class: Any = None) -> Any:
        """The row this index points at, which `index.TypeRef()` calls.

        Told a row class, this is get_row<TypeRef>() with the template
        argument passed rather than written, and asking for a table the
        index does not point at raises where the C++ asserts.

        Told nothing, it hands back the row of whatever table the tag names.
        That form is an addition: a template argument has to be known where
        it is written, so the C++ has no way to ask it. Which table it is of
        is a run-time answer, so nothing useful can be said about the type -
        it is Any, as _get_coded_index and of() are for the same reason. Name
        the row class and take the other form to have it checked.
        """
        if not self:
            raise RuntimeError(f"the {self._enum.__name__} index is not set")
        if row_class is None:
            row_class = _ROW_CLASSES[self._target()]
        elif self._target() is not row_class._number:
            raise TypeError(
                f"the index points at {self._target().name}, not {row_class.__name__}"
            )
        return row_class(
            self._table._database.table_of(row_class._number), self.index()
        )

    def get_database(self) -> database:
        return self._table._database

    def __bool__(self) -> bool:
        return self._value != 0

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, coded_index)
            and self._enum is other._enum
            and self._value == other._value
            and self._table is other._table
        )

    def __hash__(self) -> int:
        return hash((self._enum, self._value))

    def __repr__(self) -> str:
        if not self:
            return f"<coded_index {self._enum.__name__} (invalid)>"
        return (
            f"<coded_index {self._enum.__name__} -> "
            f"{self._target().name}[{self.index()}]>"
        )


# --- rows -----------------------------------------------------------------
# What a range, a list and a table hold: `RowRange[MethodDef]` is what
# `TypeDef.MethodList()` returns, as `std::pair<MethodDef, MethodDef>` is in C++.
RowT = TypeVar("RowT", bound="Row")


class RowRange(Sequence[RowT]):
    """A member list: the rows of a table from one index to another."""

    __slots__ = ("_table", "_class", "_first", "_last")

    def __init__(
        self, table: table_base, row_class: type[RowT], first: int, last: int
    ) -> None:
        self._table = table
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
        return self._class(self._table, self._first)

    @property
    def second(self) -> RowT:
        return self._class(self._table, self._last)

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
        return self._class(self._table, self._first + index)

    def __repr__(self) -> str:
        return f"<{self._class.__name__}_range {len(self)}>"


class RowList(Sequence[RowT]):
    """Rows of a table that are not next to each other."""

    __slots__ = ("_table", "_class", "_indexes")

    def __init__(
        self, table: table_base, row_class: type[RowT], indexes: list[int]
    ) -> None:
        self._table = table
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
        return self._class(self._table, self._indexes[index])

    def __repr__(self) -> str:
        return f"<{self._class.__name__}_list {len(self)}>"


# The class of each table, filled in by the subclasses below.
_ROW_CLASSES: dict[TableNumber, type] = {}


class AssemblyVersion(NamedTuple):
    """The four numbers of an assembly version, as the C++ struct has them."""

    MajorVersion: int
    MinorVersion: int
    BuildNumber: int
    RevisionNumber: int


class Row:
    """One row of one table.

    A row is a value: the database and the index. Which table it is from is
    the class it is - one per table below, holding the accessors that table
    has, as the C++ has a struct per table.
    """

    __slots__ = ("_table", "_index", "_columns")

    _number: TableNumber

    def __init_subclass__(cls, **kwargs) -> None:
        """A subclass is one table, and is the class of that table's rows."""
        super().__init_subclass__(**kwargs)
        assert cls._number.name == cls.__name__, cls.__name__
        _ROW_CLASSES[cls._number] = cls

    def __init__(self, table: table_base, index: int) -> None:
        self._table = table
        self._index = index
        self._columns: tuple[int, ...] | None = None

    # --- the basics
    def index(self) -> int:
        return self._index

    def get_database(self) -> database:
        return self._table._database

    def get_cache(self) -> cache:
        return self._table._database.get_cache()

    def get_value(self, column: int) -> int:
        if self._columns is None:
            if not self:
                raise RuntimeError(f"{self._number.name}[{self._index}] is not a row")
            self._columns = self._table.row(self._index)
        return self._columns[column]

    def __bool__(self) -> bool:
        return 0 <= self._index < self._table._count

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Row)
            and self._number == other._number
            and self._index == other._index
            and self._table is other._table
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
        return type(self)(self._table, self._index + offset)

    def __sub__(self, other: Row | int) -> int | Row:
        if isinstance(other, Row):
            return self._index - other._index
        return type(self)(self._table, self._index - other)

    def __hash__(self) -> int:
        return hash((id(self._table), self._index))

    def __repr__(self) -> str:
        return f"<{self._number.name}[{self._index}]>"

    # --- what the columns mean
    def _get_string(self, column: int) -> str:
        return self._table._database.string(self.get_value(column))

    def _get_blob(self, column: int) -> byte_view:
        return self._table._database.blob(self.get_value(column))

    def _get_coded_index(self, kind: builtins.type[CodedIndexKind], column: int) -> Any:
        """One column, as the C++ spells _get_coded_index<TypeDefOrRef>(3).

        The kind is the enum, where the C++ has the template argument, and
        the class of a column of that kind is what the registry answers.
        This is coded_index.of with the database and the value filled in, but
        it reads the registry itself: going through of() costs 11% of what
        resolving Extends() on every type in the Win32 metadata takes.
        """
        return _CODED_CLASSES[kind](self._table, self.get_value(column))

    def get_target_row(self, column: int, row_class: type[RowT]) -> RowT:
        """The row that column points at, which is a plain index into it."""
        target = self._table._database.table_of(row_class._number)
        return row_class(target, self.get_value(column) - 1)

    def get_list(self, column: int, row_class: type[RowT]) -> RowRange[RowT]:
        """My first child until the next row's first child."""
        target = self._table._database.table_of(row_class._number)
        first = self.get_value(column) - 1
        if self._index + 1 < self._table._count:
            last = self._table.row(self._index + 1)[column] - 1
        else:
            last = target._count
        return RowRange(target, row_class, first, last)

    def get_parent_row(self, column: int, row_class: type[RowT]) -> RowT:
        """The row of that table whose list column covers me.

        A list column is monotonic by construction, so this one is a search;
        the C++ writes the comparison out at each of the four uses.
        """
        target = self._table._database.table_of(row_class._number)
        return target.parent_row(column, self._index)

    # --- the other direction: rows whose coded index column points at me
    def coded_index(self, kind: builtins.type[CodedIndexKind]) -> int:
        """Me, as the value a column of that kind holds to point at me.

        row_base::coded_index<T>() in the C++, which hands back an index
        rather than the number in one; nothing here wants the index, and
        equal_range and find_row both search on the number.
        """
        return _CODED_CLASSES[kind].encode(self._number, self._index)

    def _referrers(
        self, kind: builtins.type[CodedIndexKind], row_class: "type[RowT]", column: int
    ) -> Sequence[RowT]:
        target = self._table._database.table_of(row_class._number)
        return target.equal_range(column, self.coded_index(kind))

    def _referrer(
        self, kind: builtins.type[CodedIndexKind], row_class: "type[RowT]", column: int
    ) -> RowT | None:
        target = self._table._database.table_of(row_class._number)
        return target.find_row(column, self.coded_index(kind))

    def _attributes(self) -> Sequence[CustomAttribute]:
        """The attributes applied to me, which most tables can carry.

        Which class holds the kind and which holds the table is a concrete
        answer, and the concrete classes are built on this one. The two
        registries are how a class here names a class defined on top of it.
        """
        return self._referrers(
            HasCustomAttribute, _ROW_CLASSES[TableNumber.CustomAttribute], 0
        )

    def _constant(self) -> Constant:
        row = self._referrer(HasConstant, _ROW_CLASSES[TableNumber.Constant], 1)
        if not row:
            raise RuntimeError("there is no constant for this row")
        return row

    def _version(self, column: int) -> AssemblyVersion:
        """Four uint16 in one column, which no accessor of ours can read."""
        offset, _ = self._table._offsets[column]
        start = self._table._start + self._index * self._table._row_size + offset
        return AssemblyVersion(
            *struct.unpack_from("<HHHH", self._table._database._tables, start)
        )


def make_row(database: database, table: TableNumber, index: int) -> Row:
    """A row of any table, for when the table is only known at run time."""
    return _ROW_CLASSES[table](database, index)


# --- the database ---------------------------------------------------------
class table_base:
    """One table of one file: where its rows are, and how wide they are.

    table.h keeps this on the table rather than on the database, and a row or
    a coded index holds one of these and reaches the file through it. What is
    in here is filled in by database._layout, the only thing that knows how
    wide a column is in this particular file.
    """

    __slots__ = (
        "_database",
        "number",
        "_start",
        "_count",
        "_row_size",
        "_format",
        "_offsets",
        "_sorted",
    )

    def __init__(self, database: database, number: TableNumber) -> None:
        self._database = database
        self.number = number
        self._start = 0
        self._count = 0
        self._row_size = 0
        self._format = "<"
        self._offsets: list[tuple[int, int]] = []
        self._sorted: dict[int, Any] = {}

    def get_database(self) -> database:
        return self._database

    def size(self) -> int:
        return self._count

    def row_size(self) -> int:
        """How many bytes one row takes, which depends on the whole file."""
        return self._row_size

    def column_size(self, column: int) -> int:
        return self._offsets[column][1]

    def index_size(self) -> int:
        """How wide an index into this table is in this file."""
        return 2 if self._count < (1 << 16) else 4

    def row(self, index: int) -> tuple[int, ...]:
        if not 0 <= index < self._count:
            raise IndexError(f"{self.number.name}[{index}]")
        return struct.unpack_from(
            self._format, self._database._tables, self._start + index * self._row_size
        )

    def rows(self) -> list[tuple[int, ...]]:
        """Every row at once, which is much faster than one by one."""
        if not self._count:
            return []
        return list(
            struct.iter_unpack(
                self._format,
                self._database._tables[
                    self._start : self._start + self._row_size * self._count
                ],
            )
        )

    def get_value(self, row: int, column: int) -> int:
        return self.row(row)[column]

    def __repr__(self) -> str:
        return f"<{self.number.name}_table {self._count}>"


class Table(table_base, Sequence[RowT]):
    """One table, as a sequence of rows: the C++ table<Row> over table_base."""

    __slots__ = ("_class",)

    def __init__(self, database: database, row_class: type[RowT]) -> None:
        super().__init__(database, row_class._number)
        self._class = row_class

    def __len__(self) -> int:
        return self._count

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
        return self._class(self, index)

    # --- the searches the back references need
    #
    # Most of these columns are sorted by the one that points back, and are
    # searched for. Some are not: PropertyMap and EventMap come out of the
    # compiler in the order the types were emitted, so
    # Windows.Foundation.UniversalApiContract has ... 7680, 7681, 7679 ... in
    # its PropertyMap.Parent. A binary search there silently finds nothing,
    # which is why the C++ reader scans those two linearly. Whether a column
    # is sorted is checked once, and an unsorted one is grouped into a dict.
    #
    # The C++ writes equal_range as two lines over std::equal_range, in
    # view.h, and hands it the table: `equal_range(get_database().GenericParam,
    # coded_index<TypeOrMethodDef>())`. The table is the subject there too;
    # what cannot be a free function here is the column cache these keep.
    def _column(self, column: int) -> tuple[list[int], dict[int, list[int]] | None]:
        found = self._sorted.get(column)
        if found is None:
            values = [row[column] for row in self.rows()]
            grouped = None
            if any(values[i] > values[i + 1] for i in range(len(values) - 1)):
                grouped = {}
                for index, value in enumerate(values):
                    grouped.setdefault(value, []).append(index)
            found = self._sorted[column] = (values, grouped)
        return found

    def equal_range(self, column: int, value: int) -> Sequence[RowT]:
        """The rows whose column equals `value`."""
        values, grouped = self._column(column)
        if grouped is not None:
            return RowList(self, self._class, grouped.get(value, []))
        first = bisect.bisect_left(values, value)
        last = bisect.bisect_right(values, value, first)
        return RowRange(self, self._class, first, last)

    def find_row(self, column: int, value: int) -> RowT | None:
        """The first row whose column equals `value`, if there is one."""
        values, grouped = self._column(column)
        if grouped is not None:
            indexes = grouped.get(value)
            return self._class(self, indexes[0]) if indexes else None
        position = bisect.bisect_left(values, value)
        if position < len(values) and values[position] == value:
            return self._class(self, position)
        return None

    def parent_row(self, column: int, index: int) -> RowT:
        """My row whose list column covers `index`.

        A list column is monotonic by construction, so this one is a search.
        """
        values, _ = self._column(column)
        position = bisect.bisect_right(values, index + 1) - 1
        if position < 0:
            raise RuntimeError("no parent row")
        return self._class(self, position)

    def __repr__(self) -> str:
        return f"<{self._class.__name__}_table {len(self)}>"
