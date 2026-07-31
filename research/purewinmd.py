"""A .winmd reader in nothing but the standard library, for comparison.

The point of this file is to measure what a pure Python parser of the same
metadata costs, against the nanobind bindings of the C++ reader. It covers the
same ground the C++ `database` does - PE to CLI header to metadata root, the
heaps, the 38 table schemas and the coded indexes - and stops there: no
signature blobs, no custom attribute decoding, no `cache` semantics beyond a
namespace index.

    db = Database("Windows.Win32.winmd")
    print(db.rows(TYPE_DEF), "types")

    for row in db.table(TYPE_DEF):
        print(db.string(row[NAMESPACE]), db.string(row[NAME]))

Layout follows ECMA-335 partition II, and the schemas were taken from
`impl/winmd_reader/database.h` of Microsoft.Windows.WinMD so that the two agree
by construction.
"""

import mmap
import struct
from typing import Dict, List, Optional, Sequence, Tuple

# --- the 38 tables, by their ECMA-335 number ------------------------------
MODULE = 0x00
TYPE_REF = 0x01
TYPE_DEF = 0x02
FIELD = 0x04
METHOD_DEF = 0x06
PARAM = 0x08
INTERFACE_IMPL = 0x09
MEMBER_REF = 0x0A
CONSTANT = 0x0B
CUSTOM_ATTRIBUTE = 0x0C
FIELD_MARSHAL = 0x0D
DECL_SECURITY = 0x0E
CLASS_LAYOUT = 0x0F
FIELD_LAYOUT = 0x10
STANDALONE_SIG = 0x11
EVENT_MAP = 0x12
EVENT = 0x14
PROPERTY_MAP = 0x15
PROPERTY = 0x17
METHOD_SEMANTICS = 0x18
METHOD_IMPL = 0x19
MODULE_REF = 0x1A
TYPE_SPEC = 0x1B
IMPL_MAP = 0x1C
FIELD_RVA = 0x1D
ASSEMBLY = 0x20
ASSEMBLY_PROCESSOR = 0x21
ASSEMBLY_OS = 0x22
ASSEMBLY_REF = 0x23
ASSEMBLY_REF_PROCESSOR = 0x24
ASSEMBLY_REF_OS = 0x25
FILE = 0x26
EXPORTED_TYPE = 0x27
MANIFEST_RESOURCE = 0x28
NESTED_CLASS = 0x29
GENERIC_PARAM = 0x2A
METHOD_SPEC = 0x2B
GENERIC_PARAM_CONSTRAINT = 0x2C

# The order the tables are laid out in, which is the order of their numbers.
TABLE_ORDER = [
    MODULE, TYPE_REF, TYPE_DEF, FIELD, METHOD_DEF, PARAM, INTERFACE_IMPL,
    MEMBER_REF, CONSTANT, CUSTOM_ATTRIBUTE, FIELD_MARSHAL, DECL_SECURITY,
    CLASS_LAYOUT, FIELD_LAYOUT, STANDALONE_SIG, EVENT_MAP, EVENT, PROPERTY_MAP,
    PROPERTY, METHOD_SEMANTICS, METHOD_IMPL, MODULE_REF, TYPE_SPEC, IMPL_MAP,
    FIELD_RVA, ASSEMBLY, ASSEMBLY_PROCESSOR, ASSEMBLY_OS, ASSEMBLY_REF,
    ASSEMBLY_REF_PROCESSOR, ASSEMBLY_REF_OS, FILE, EXPORTED_TYPE,
    MANIFEST_RESOURCE, NESTED_CLASS, GENERIC_PARAM, METHOD_SPEC,
    GENERIC_PARAM_CONSTRAINT,
]

# --- coded indexes: the tables they may point at, in tag order ------------
# `None` is a tag the standard reserves without giving it a table.
CODED_INDEXES = {
    "TypeDefOrRef": (TYPE_DEF, TYPE_REF, TYPE_SPEC),
    "HasConstant": (FIELD, PARAM, PROPERTY),
    "HasCustomAttribute": (
        METHOD_DEF, FIELD, TYPE_REF, TYPE_DEF, PARAM, INTERFACE_IMPL, MEMBER_REF,
        MODULE, PROPERTY, EVENT, STANDALONE_SIG, MODULE_REF, TYPE_SPEC, ASSEMBLY,
        ASSEMBLY_REF, FILE, EXPORTED_TYPE, MANIFEST_RESOURCE, GENERIC_PARAM,
        GENERIC_PARAM_CONSTRAINT, METHOD_SPEC),
    "HasFieldMarshal": (FIELD, PARAM),
    "HasDeclSecurity": (TYPE_DEF, METHOD_DEF, ASSEMBLY),
    "MemberRefParent": (TYPE_DEF, TYPE_REF, MODULE_REF, METHOD_DEF, TYPE_SPEC),
    "HasSemantics": (EVENT, PROPERTY),
    "MethodDefOrRef": (METHOD_DEF, MEMBER_REF),
    "MemberForwarded": (FIELD, METHOD_DEF),
    "Implementation": (FILE, ASSEMBLY_REF, EXPORTED_TYPE),
    "CustomAttributeType": (METHOD_DEF, MEMBER_REF, None, None, None),
    "ResolutionScope": (MODULE, MODULE_REF, ASSEMBLY_REF, TYPE_REF),
    "TypeOrMethodDef": (TYPE_DEF, METHOD_DEF),
}

# --- the columns of every table -------------------------------------------
# An int is that many bytes; a string is either a heap ("string", "blob",
# "guid"), a table index ("#<table>") or the name of a coded index.
SCHEMA = {
    ASSEMBLY: (4, 8, 4, "blob", "string", "string"),
    ASSEMBLY_OS: (4, 4, 4),
    ASSEMBLY_PROCESSOR: (4,),
    ASSEMBLY_REF: (8, 4, "blob", "string", "string", "blob"),
    ASSEMBLY_REF_OS: (4, 4, 4, "#" + str(ASSEMBLY_REF)),
    ASSEMBLY_REF_PROCESSOR: (4, "#" + str(ASSEMBLY_REF)),
    CLASS_LAYOUT: (2, 4, "#" + str(TYPE_DEF)),
    CONSTANT: (2, "HasConstant", "blob"),
    CUSTOM_ATTRIBUTE: ("HasCustomAttribute", "CustomAttributeType", "blob"),
    DECL_SECURITY: (2, "HasDeclSecurity", "blob"),
    EVENT_MAP: ("#" + str(TYPE_DEF), "#" + str(EVENT)),
    EVENT: (2, "string", "TypeDefOrRef"),
    EXPORTED_TYPE: (4, 4, "string", "string", "Implementation"),
    FIELD: (2, "string", "blob"),
    FIELD_LAYOUT: (4, "#" + str(FIELD)),
    FIELD_MARSHAL: ("HasFieldMarshal", "blob"),
    FIELD_RVA: (4, "#" + str(FIELD)),
    FILE: (4, "string", "blob"),
    GENERIC_PARAM: (2, 2, "TypeOrMethodDef", "string"),
    GENERIC_PARAM_CONSTRAINT: ("#" + str(GENERIC_PARAM), "TypeDefOrRef"),
    IMPL_MAP: (2, "MemberForwarded", "string", "#" + str(MODULE_REF)),
    INTERFACE_IMPL: ("#" + str(TYPE_DEF), "TypeDefOrRef"),
    MANIFEST_RESOURCE: (4, 4, "string", "Implementation"),
    MEMBER_REF: ("MemberRefParent", "string", "blob"),
    METHOD_DEF: (4, 2, 2, "string", "blob", "#" + str(PARAM)),
    METHOD_IMPL: ("#" + str(TYPE_DEF), "MethodDefOrRef", "MethodDefOrRef"),
    METHOD_SEMANTICS: (2, "#" + str(METHOD_DEF), "HasSemantics"),
    METHOD_SPEC: ("MethodDefOrRef", "blob"),
    MODULE: (2, "string", "guid", "guid", "guid"),
    MODULE_REF: ("string",),
    NESTED_CLASS: ("#" + str(TYPE_DEF), "#" + str(TYPE_DEF)),
    PARAM: (2, 2, "string"),
    PROPERTY: (2, "string", "blob"),
    PROPERTY_MAP: ("#" + str(TYPE_DEF), "#" + str(PROPERTY)),
    STANDALONE_SIG: ("blob",),
    TYPE_DEF: (4, "string", "string", "TypeDefOrRef", "#" + str(FIELD), "#" + str(METHOD_DEF)),
    TYPE_REF: ("ResolutionScope", "string", "string"),
    TYPE_SPEC: ("blob",),
}

# TypeDef columns, by name, for readers of this module.
FLAGS, NAME, NAMESPACE, EXTENDS, FIELD_LIST, METHOD_LIST = range(6)


def _bits_needed(count: int) -> int:
    """How many tag bits a coded index over `count` tables takes."""
    bits = 0
    value = count - 1
    while value:
        bits += 1
        value >>= 1
    return bits


class Database:
    """One .winmd file, mapped and laid out; rows are decoded on demand."""

    def __init__(self, path: str):
        self.path = path
        self._file = open(path, "rb")
        self._data = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        view = memoryview(self._data)

        metadata = self._find_metadata(view)
        streams = self._read_streams(view, metadata)

        # The string heap is copied out once. It is the one heap read over and
        # over, and slicing bytes is markedly faster than slicing a memoryview
        # of the mapping - see research/README.md.
        self._strings_range = streams["#Strings"]
        self._strings = bytes(view[streams["#Strings"][0]:sum(streams["#Strings"])])
        self._blobs = view[streams["#Blob"][0]:sum(streams["#Blob"])] if "#Blob" in streams else None
        self._guids = view[streams["#GUID"][0]:sum(streams["#GUID"])] if "#GUID" in streams else None

        tables = view[streams["#~"][0]:sum(streams["#~"])] if "#~" in streams \
            else view[streams["#-"][0]:sum(streams["#-"])]
        self._layout(tables)

        self._string_cache: Dict[int, str] = {}

    # --- PE and the metadata root -----------------------------------------
    def _find_metadata(self, view: memoryview) -> int:
        if view[:2] != b"MZ":
            raise ValueError(f"{self.path} is not a PE image")
        pe = struct.unpack_from("<I", view, 0x3C)[0]
        if view[pe:pe + 4] != b"PE\0\0":
            raise ValueError(f"{self.path} has no PE signature")

        coff = pe + 4
        sections, optional_size = struct.unpack_from("<H", view, coff + 2)[0], \
            struct.unpack_from("<H", view, coff + 16)[0]
        optional = coff + 20
        magic = struct.unpack_from("<H", view, optional)[0]
        directories = optional + (96 if magic == 0x10B else 112)   # PE32 / PE32+
        cli_rva = struct.unpack_from("<I", view, directories + 14 * 8)[0]
        if not cli_rva:
            raise ValueError(f"{self.path} carries no CLI header")

        self._sections = []
        first = optional + optional_size
        for index in range(sections):
            header = first + index * 40
            virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from(
                "<IIII", view, header + 8)
            self._sections.append((virtual_address, max(virtual_size, raw_size), raw_pointer))

        cli = self._offset(cli_rva)
        metadata_rva = struct.unpack_from("<I", view, cli + 8)[0]
        return self._offset(metadata_rva)

    def _offset(self, rva: int) -> int:
        for virtual_address, size, raw in self._sections:
            if virtual_address <= rva < virtual_address + size:
                return rva - virtual_address + raw
        raise ValueError(f"RVA {rva:#x} is in no section")

    def _read_streams(self, view: memoryview, root: int) -> Dict[str, Tuple[int, int]]:
        if view[root:root + 4] != b"BSJB":
            raise ValueError(f"{self.path} has no metadata root")
        version_length = struct.unpack_from("<I", view, root + 12)[0]
        position = root + 16 + version_length + 2                  # + flags
        count = struct.unpack_from("<H", view, position)[0]
        position += 2

        streams = {}
        for _ in range(count):
            offset, size = struct.unpack_from("<II", view, position)
            position += 8
            end = bytes(view[position:position + 32]).index(b"\0")
            name = bytes(view[position:position + end]).decode("ascii")
            position += end + 1
            position += -position % 4                              # padded to 4
            streams[name] = (root + offset, size)
        return streams

    # --- the table layout --------------------------------------------------
    def _layout(self, tables: memoryview) -> None:
        heap_sizes = tables[6]
        string_index = 4 if heap_sizes & 1 else 2
        guid_index = 4 if heap_sizes & 2 else 2
        blob_index = 4 if heap_sizes & 4 else 2

        valid = struct.unpack_from("<Q", tables, 8)[0]
        position = 24
        self.row_counts = {}
        for number in range(64):
            if valid >> number & 1:
                self.row_counts[number] = struct.unpack_from("<I", tables, position)[0]
                position += 4

        def index_size(table: int) -> int:
            return 2 if self.row_counts.get(table, 0) < (1 << 16) else 4

        def coded_size(name: str) -> int:
            targets = CODED_INDEXES[name]
            bits = _bits_needed(len(targets))
            limit = 1 << (16 - bits)
            fits = all(self.row_counts.get(table, 0) < limit
                       for table in targets if table is not None)
            return 2 if fits else 4

        heaps = {"string": string_index, "guid": guid_index, "blob": blob_index}
        self._columns: Dict[int, List[Tuple[int, int]]] = {}   # table -> [(offset, size)]
        self._row_size: Dict[int, int] = {}
        self._format: Dict[int, str] = {}
        for table, schema in SCHEMA.items():
            offset = 0
            columns = []
            fields = []
            for column in schema:
                if isinstance(column, int):
                    size = column
                elif column in heaps:
                    size = heaps[column]
                elif column.startswith("#"):
                    size = index_size(int(column[1:]))
                else:
                    size = coded_size(column)
                columns.append((offset, size))
                fields.append({1: "B", 2: "H", 4: "I", 8: "Q"}[size])
                offset += size
            self._columns[table] = columns
            self._row_size[table] = offset
            self._format[table] = "<" + "".join(fields)

        self._start: Dict[int, int] = {}
        for table in TABLE_ORDER:
            self._start[table] = position
            position += self._row_size[table] * self.row_counts.get(table, 0)
        self._tables = tables

    # --- reading ------------------------------------------------------------
    def rows(self, table: int) -> int:
        return self.row_counts.get(table, 0)

    def row(self, table: int, index: int) -> Tuple[int, ...]:
        """One row, as a tuple of its columns."""
        offset = self._start[table] + index * self._row_size[table]
        return struct.unpack_from(self._format[table], self._tables, offset)

    def table(self, table: int) -> List[Tuple[int, ...]]:
        """Every row of a table at once, which is much faster than one by one."""
        count = self.row_counts.get(table, 0)
        if not count:
            return []
        start = self._start[table]
        size = self._row_size[table]
        return list(struct.iter_unpack(
            self._format[table], self._tables[start:start + size * count]))

    def column(self, table: int, index: int) -> List[int]:
        """One column of a whole table."""
        return [row[index] for row in self.table(table)]

    def string(self, index: int) -> str:
        """A string from the #Strings heap.

        Deliberately not cached. Type and member names are nearly all distinct,
        and a dict lookup that misses costs more than decoding the eight or so
        bytes again; caching every string made building an index 1.6x slower.
        Where a column repeats - namespaces, 326 distinct over 37,311 rows - the
        caller caches, as namespaces() does.
        """
        heap = self._strings
        return heap[index:heap.index(b"\0", index)].decode("utf-8")

    def close(self) -> None:
        # mmap refuses to close while a memoryview of it is alive.
        for name in ("_tables", "_blobs", "_guids"):
            view = getattr(self, name, None)
            if view is not None:
                view.release()
                setattr(self, name, None)
        self._data.close()
        self._file.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def namespaces(self) -> Dict[str, Dict[str, int]]:
        """{namespace: {name: TypeDef row}}, which is what a cache is for."""
        index: Dict[str, Dict[str, int]] = {}
        heap = self._strings
        namespaces: Dict[int, str] = {}                     # this one repeats
        for row_index, row in enumerate(self.table(TYPE_DEF)):
            if not row[FLAGS]:
                continue                                    # the <Module> row
            at = row[NAMESPACE]
            namespace = namespaces.get(at)
            if namespace is None:
                namespace = namespaces[at] = heap[at:heap.index(b"\0", at)].decode("utf-8")
            at = row[NAME]
            index.setdefault(namespace, {})[
                heap[at:heap.index(b"\0", at)].decode("utf-8")] = row_index
        return index
