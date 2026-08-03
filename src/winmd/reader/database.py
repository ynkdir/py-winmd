"""One .winmd file, as impl/winmd_reader/database.h has it.

The PE and CLI headers, the metadata root and its heaps, the row counts and
the column widths they decide, and a Table per table number.
"""

from __future__ import annotations

import bisect
import builtins
import mmap
import struct
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, BinaryIO, overload

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
from .index import _CODED_CLASSES
from .schema import (
    _ROW_CLASSES,
    Assembly,
    AssemblyOS,
    AssemblyProcessor,
    AssemblyRef,
    AssemblyRefOS,
    AssemblyRefProcessor,
    ClassLayout,
    Constant,
    CustomAttribute,
    DeclSecurity,
    Event,
    EventMap,
    ExportedType,
    Field,
    FieldLayout,
    FieldMarshal,
    FieldRVA,
    File,
    GenericParam,
    GenericParamConstraint,
    ImplMap,
    InterfaceImpl,
    ManifestResource,
    MemberRef,
    MethodDef,
    MethodImpl,
    MethodSemantics,
    MethodSpec,
    Module,
    ModuleRef,
    NestedClass,
    Param,
    Property,
    PropertyMap,
    Row,
    RowList,
    RowRange,
    RowT,
    StandAloneSig,
    TypeDef,
    TypeRef,
    TypeSpec,
)
from .view import byte_view, uncompress_unsigned

if TYPE_CHECKING:
    from .cache import cache


# --- the database ---------------------------------------------------------
class Table(Sequence[RowT]):
    """One table, as a sequence of rows."""

    __slots__ = ("_database", "_class")

    def __init__(self, database: database, row_class: type[RowT]) -> None:
        self._database = database
        self._class = row_class

    def __len__(self) -> int:
        return self._database.rows(self._class._table)

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
        return self._class(self._database, index)

    def size(self) -> int:
        return len(self)

    def row_size(self) -> int:
        """How many bytes one row takes, which depends on the whole file."""
        return self._database._row_size[self._class._table]

    def column_size(self, column: int) -> int:
        return self._database._columns[self._class._table][column][1]

    def get_value(self, row: int, column: int) -> int:
        return self._database.row(self._class._table, row)[column]

    def get_database(self) -> database:
        return self._database

    def __repr__(self) -> str:
        return f"<{self._class.__name__}_table {len(self)}>"


class database:
    """One .winmd file, mapped and laid out; rows are decoded on demand."""

    # One attribute per table, set in __init__ and declared here so that
    # db.TypeDef is known to be a Table of TypeDef rows.
    Module: Table[Module]
    TypeRef: Table[TypeRef]
    TypeDef: Table[TypeDef]
    Field: Table[Field]
    MethodDef: Table[MethodDef]
    Param: Table[Param]
    InterfaceImpl: Table[InterfaceImpl]
    MemberRef: Table[MemberRef]
    Constant: Table[Constant]
    CustomAttribute: Table[CustomAttribute]
    FieldMarshal: Table[FieldMarshal]
    DeclSecurity: Table[DeclSecurity]
    ClassLayout: Table[ClassLayout]
    FieldLayout: Table[FieldLayout]
    StandAloneSig: Table[StandAloneSig]
    EventMap: Table[EventMap]
    Event: Table[Event]
    PropertyMap: Table[PropertyMap]
    Property: Table[Property]
    MethodSemantics: Table[MethodSemantics]
    MethodImpl: Table[MethodImpl]
    ModuleRef: Table[ModuleRef]
    TypeSpec: Table[TypeSpec]
    ImplMap: Table[ImplMap]
    FieldRVA: Table[FieldRVA]
    Assembly: Table[Assembly]
    AssemblyProcessor: Table[AssemblyProcessor]
    AssemblyOS: Table[AssemblyOS]
    AssemblyRef: Table[AssemblyRef]
    AssemblyRefProcessor: Table[AssemblyRefProcessor]
    AssemblyRefOS: Table[AssemblyRefOS]
    File: Table[File]
    ExportedType: Table[ExportedType]
    ManifestResource: Table[ManifestResource]
    NestedClass: Table[NestedClass]
    GenericParam: Table[GenericParam]
    MethodSpec: Table[MethodSpec]
    GenericParamConstraint: Table[GenericParamConstraint]

    def __init__(
        self, path: str | bytes | bytearray, cache: cache | None = None
    ) -> None:
        """A path to map, or the bytes of a file already in hand."""
        self._path: str
        self._file: BinaryIO | None
        self._data: bytes | mmap.mmap
        if isinstance(path, (bytes, bytearray)):
            self._path = ""
            self._file = None
            self._data = bytes(path)
        else:
            self._path = path
            self._file = open(path, "rb")
            self._data = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        self._cache = cache
        view = memoryview(self._data)

        metadata = self._find_metadata(view)
        streams = self._read_streams(view, metadata)

        # The heaps are copied out once: slicing bytes is faster than going
        # through the mapping, and this is where the reader spends its time.
        self._strings_range: tuple[int, int] = streams["#Strings"]
        self._strings: bytes = bytes(
            view[streams["#Strings"][0] : sum(streams["#Strings"])]
        )
        self._blobs: bytes = (
            bytes(view[streams["#Blob"][0] : sum(streams["#Blob"])])
            if "#Blob" in streams
            else b""
        )
        self._guids: bytes = (
            bytes(view[streams["#GUID"][0] : sum(streams["#GUID"])])
            if "#GUID" in streams
            else b""
        )

        name = "#~" if "#~" in streams else "#-"
        self._tables: memoryview = view[streams[name][0] : sum(streams[name])]
        self._layout(self._tables)
        self._sorted_columns: dict[tuple[int, int], Any] = {}
        self._attribute_names: dict[int, tuple[str, str]] = {}
        self._type_names: dict[
            "tuple[builtins.type[IntEnum], int]", tuple[str, str]
        ] = {}

        for table in TableNumber:
            setattr(self, table.name, Table(self, _ROW_CLASSES[table]))

    # --- PE and the metadata root
    def _find_metadata(self, view: memoryview) -> int:
        if view[:2] != b"MZ":
            raise ValueError(f"{self._path} is not a PE image")
        pe = struct.unpack_from("<I", view, 0x3C)[0]
        if view[pe : pe + 4] != b"PE\0\0":
            raise ValueError(f"{self._path} has no PE signature")

        coff = pe + 4
        sections = struct.unpack_from("<H", view, coff + 2)[0]
        optional_size = struct.unpack_from("<H", view, coff + 16)[0]
        optional = coff + 20
        magic = struct.unpack_from("<H", view, optional)[0]
        directories = optional + (96 if magic == 0x10B else 112)  # PE32 / PE32+
        cli_rva = struct.unpack_from("<I", view, directories + 14 * 8)[0]
        if not cli_rva:
            raise ValueError(f"{self._path} carries no CLI header")

        self._sections = []
        first = optional + optional_size
        for index in range(sections):
            header = first + index * 40
            virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from(
                "<IIII", view, header + 8
            )
            self._sections.append(
                (virtual_address, max(virtual_size, raw_size), raw_pointer)
            )

        cli = self._offset(cli_rva)
        return self._offset(struct.unpack_from("<I", view, cli + 8)[0])

    def _offset(self, rva: int) -> int:
        for virtual_address, size, raw in self._sections:
            if virtual_address <= rva < virtual_address + size:
                return rva - virtual_address + raw
        raise ValueError(f"RVA {rva:#x} is in no section")

    def _read_streams(self, view: memoryview, root: int) -> dict[str, tuple[int, int]]:
        if view[root : root + 4] != b"BSJB":
            raise ValueError(f"{self._path} has no metadata root")
        version_length = struct.unpack_from("<I", view, root + 12)[0]
        position = root + 16 + version_length + 2  # + flags
        count = struct.unpack_from("<H", view, position)[0]
        position += 2

        streams = {}
        for _ in range(count):
            offset, size = struct.unpack_from("<II", view, position)
            position += 8
            end = bytes(view[position : position + 32]).index(b"\0")
            streams[bytes(view[position : position + end]).decode("ascii")] = (
                root + offset,
                size,
            )
            position += end + 1
            position += -position % 4  # padded to 4
        return streams

    # --- the table layout
    def _layout(self, tables: memoryview) -> None:
        """What each column of each table is, and how wide it is in this file.

        The same 38 lines as the C++, which lays the tables out in its
        constructor rather than declaring them on the row types; see
        impl/winmd_reader/database.h. A column is a number of bytes, an index
        into a heap, an index into a table, or a coded index, and the last
        three depend on how big this file's heaps and tables are.
        """
        heap_sizes = tables[6]
        string = 4 if heap_sizes & 1 else 2
        guid = 4 if heap_sizes & 2 else 2
        blob = 4 if heap_sizes & 4 else 2

        # One row count per bit of the valid mask, in table number order. The
        # C++ throws on a number it has no table for and so does this; every
        # count after an unknown one would be read against the wrong table.
        valid = struct.unpack_from("<Q", tables, 8)[0]
        position = 24
        self.row_counts: dict[TableNumber, int] = {}
        for number in range(64):
            if valid >> number & 1:
                try:
                    table = TableNumber(number)
                except ValueError:
                    raise ValueError(f"unknown metadata table 0x{number:02x}") from None
                self.row_counts[table] = struct.unpack_from("<I", tables, position)[0]
                position += 4

        def index(row_class: type[Row]) -> int:
            """How wide an index into that table is here."""
            return 2 if self.row_counts.get(row_class._table, 0) < (1 << 16) else 4

        def coded(kind: builtins.type[IntEnum]) -> int:
            """How wide a coded index of that kind is here."""
            cls = _CODED_CLASSES[kind]
            limit = 1 << (16 - cls._bits)
            sizing = cls._sizing_tables or cls._tables
            return (
                2
                if all(
                    self.row_counts.get(table, 0) < limit
                    for table in sizing
                    if table is not None
                )
                else 4
            )

        self._columns: dict[TableNumber, list[tuple[int, int]]] = {}
        self._row_size: dict[TableNumber, int] = {}
        self._format: dict[TableNumber, str] = {}

        def columns(row_class: type[Row], *widths: int) -> None:
            offset = 0
            laid = []
            for width in widths:
                laid.append((offset, width))
                offset += width
            table = row_class._table
            self._columns[table] = laid
            self._row_size[table] = offset
            self._format[table] = "<" + "".join(
                {1: "B", 2: "H", 4: "I", 8: "Q"}[width] for width in widths
            )

        columns(Assembly, 4, 8, 4, blob, string, string)
        columns(AssemblyOS, 4, 4, 4)
        columns(AssemblyProcessor, 4)
        columns(AssemblyRef, 8, 4, blob, string, string, blob)
        columns(AssemblyRefOS, 4, 4, 4, index(AssemblyRef))
        columns(AssemblyRefProcessor, 4, index(AssemblyRef))
        columns(ClassLayout, 2, 4, index(TypeDef))
        columns(Constant, 2, coded(HasConstant), blob)
        columns(
            CustomAttribute,
            coded(HasCustomAttribute),
            coded(CustomAttributeType),
            blob,
        )
        columns(DeclSecurity, 2, coded(HasDeclSecurity), blob)
        columns(EventMap, index(TypeDef), index(Event))
        columns(Event, 2, string, coded(TypeDefOrRef))
        columns(ExportedType, 4, 4, string, string, coded(Implementation))
        columns(Field, 2, string, blob)
        columns(FieldLayout, 4, index(Field))
        columns(FieldMarshal, coded(HasFieldMarshal), blob)
        columns(FieldRVA, 4, index(Field))
        columns(File, 4, string, blob)
        columns(GenericParam, 2, 2, coded(TypeOrMethodDef), string)
        columns(GenericParamConstraint, index(GenericParam), coded(TypeDefOrRef))
        columns(ImplMap, 2, coded(MemberForwarded), string, index(ModuleRef))
        columns(InterfaceImpl, index(TypeDef), coded(TypeDefOrRef))
        columns(ManifestResource, 4, 4, string, coded(Implementation))
        columns(MemberRef, coded(MemberRefParent), string, blob)
        columns(MethodDef, 4, 2, 2, string, blob, index(Param))
        columns(
            MethodImpl,
            index(TypeDef),
            coded(MethodDefOrRef),
            coded(MethodDefOrRef),
        )
        columns(MethodSemantics, 2, index(MethodDef), coded(HasSemantics))
        columns(MethodSpec, coded(MethodDefOrRef), blob)
        columns(Module, 2, string, guid, guid, guid)
        columns(ModuleRef, string)
        columns(NestedClass, index(TypeDef), index(TypeDef))
        columns(Param, 2, 2, string)
        columns(Property, 2, string, blob)
        columns(PropertyMap, index(TypeDef), index(Property))
        columns(StandAloneSig, blob)
        columns(
            TypeDef,
            4,
            string,
            string,
            coded(TypeDefOrRef),
            index(Field),
            index(MethodDef),
        )
        columns(TypeRef, coded(ResolutionScope), string, string)
        columns(TypeSpec, blob)

        # The rows follow one another in table number order, which is the
        # order the enum declares them in.
        self._start: dict[TableNumber, int] = {}
        for table in TableNumber:
            self._start[table] = position
            position += self._row_size[table] * self.row_counts.get(table, 0)

    # --- reading
    def rows(self, table: TableNumber) -> int:
        return self.row_counts.get(table, 0)

    def row(self, table: TableNumber, index: int) -> tuple[int, ...]:
        if not 0 <= index < self.rows(table):
            raise IndexError(f"{TableNumber(table).name}[{index}]")
        return struct.unpack_from(
            self._format[table],
            self._tables,
            self._start[table] + index * self._row_size[table],
        )

    def table(self, table: TableNumber) -> list[tuple[int, ...]]:
        """Every row of a table at once, which is much faster than one by one."""
        count = self.rows(table)
        if not count:
            return []
        start = self._start[table]
        size = self._row_size[table]
        return list(
            struct.iter_unpack(
                self._format[table], self._tables[start : start + size * count]
            )
        )

    def path(self) -> str:
        return self._path

    def get_string(self, index: int) -> str:
        """A string from the #Strings heap, spelled as the C++ reader does."""
        return self.string(index)

    def get_blob(self, index: int) -> byte_view:
        return self.blob(index)

    def string(self, index: int) -> str:
        """A string from the #Strings heap.

        Deliberately not cached: names are nearly all distinct, and a dict
        lookup that misses costs more than decoding eight bytes again. Where a
        column repeats, the caller caches - see cache().
        """
        heap = self._strings
        return heap[index : heap.index(b"\0", index)].decode("utf-8")

    def blob(self, index: int) -> byte_view:
        size, position = uncompress_unsigned(self._blobs, index)
        return byte_view(self._blobs, position, size, self)

    def guid(self, index: int) -> bytes:
        if not index:
            return b""
        return self._guids[(index - 1) * 16 : index * 16]

    def get_cache(self) -> cache:
        if self._cache is None:
            raise RuntimeError("this database was opened without a cache")
        return self._cache

    # --- the searches the back references need
    #
    # Most of these tables are sorted by the column that points back, and are
    # searched for. Some are not: PropertyMap and EventMap come out of the
    # compiler in the order the types were emitted, so
    # Windows.Foundation.UniversalApiContract has ... 7680, 7681, 7679 ... in
    # its PropertyMap.Parent. A binary search there silently finds nothing,
    # which is why the C++ reader scans those two linearly. Whether the column
    # is sorted is checked once, and an unsorted one is grouped into a dict.
    def _column(
        self, table: TableNumber, column: int
    ) -> tuple[list[int], dict[int, list[int]] | None]:
        key = (table, column)
        found = self._sorted_columns.get(key)
        if found is None:
            values = [row[column] for row in self.table(table)]
            grouped = None
            if any(values[i] > values[i + 1] for i in range(len(values) - 1)):
                grouped = {}
                for index, value in enumerate(values):
                    grouped.setdefault(value, []).append(index)
            found = self._sorted_columns[key] = (values, grouped)
        return found

    def equal_range(
        self, row_class: type[RowT], column: int, value: int
    ) -> Sequence[RowT]:
        """The rows whose column equals `value`."""
        values, grouped = self._column(row_class._table, column)
        if grouped is not None:
            return RowList(self, row_class, grouped.get(value, []))
        first = bisect.bisect_left(values, value)
        last = bisect.bisect_right(values, value, first)
        return RowRange(self, row_class, first, last)

    def find_row(self, row_class: type[RowT], column: int, value: int) -> RowT | None:
        values, grouped = self._column(row_class._table, column)
        if grouped is not None:
            indexes = grouped.get(value)
            return row_class(self, indexes[0]) if indexes else None
        position = bisect.bisect_left(values, value)
        if position < len(values) and values[position] == value:
            return row_class(self, position)
        return None

    def parent_row(self, row_class: type[RowT], column: int, index: int) -> RowT:
        """The row of `table` whose list column covers `index`.

        A list column is monotonic by construction, so this one is a search.
        """
        values, _ = self._column(row_class._table, column)
        position = bisect.bisect_right(values, index + 1) - 1
        if position < 0:
            raise RuntimeError("no parent row")
        return row_class(self, position)

    @staticmethod
    def is_database(path: str) -> bool:
        """Whether the file is metadata at all. Cheap, and does not raise."""
        try:
            with open(path, "rb") as file:
                if file.read(2) != b"MZ":
                    return False
            database(path).close()
            return True
        except (OSError, ValueError, struct.error, IndexError):
            return False

    def close(self) -> None:
        # A mmap refuses to close while a memoryview of it is alive.
        tables = getattr(self, "_tables", None)
        if tables is not None:
            tables.release()
            self._tables = memoryview(b"")
        data = getattr(self, "_data", None)
        if isinstance(data, mmap.mmap):
            data.close()
            self._data = b""
        file = getattr(self, "_file", None)
        if file is not None:
            file.close()
            self._file = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # nothing useful to do at teardown
            pass

    def __enter__(self) -> database:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<database {self._path}>"
