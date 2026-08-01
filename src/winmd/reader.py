"""A .winmd reader in nothing but the standard library.

The same ground as the C++ winmd::reader: the PE and CLI headers, the metadata
root and its heaps, the 38 tables with named accessors, the 13 coded indexes,
the signature blobs, the custom attribute decoder, the flag structs and a cache
that indexes types by namespace.

    from winmd.reader import cache, get_category

    db = cache(["Windows.Win32.winmd"])
    type = db.find_required("Windows.Win32.UI.WindowsAndMessaging", "MSG")

    print(type.TypeNamespace(), type.TypeName(), get_category(type))
    for method in type.MethodList():
        print(method.Name(), [p.Type().Type() for p in method.Signature().Params()])

Names and shapes follow the C++ interface, so the two can be compared row for
row; tests/test_reference.py does exactly that. Layout is ECMA-335 partition II
and the table schemas were taken from impl/winmd_reader/database.h.
"""

from __future__ import annotations

import bisect
import mmap
import struct
from enum import IntEnum, IntFlag
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple, TypeVar

# --- the 38 tables, by their ECMA-335 number ------------------------------
class TableNumber(IntEnum):
    """The 38 tables, by the number ECMA-335 gives them.

    A member is named as its row class is, which is how a row says which
    table it is from. The C++ has no such thing: a table is a type there,
    and the numbers appear once, in the switch that reads the row counts.
    """

    Module = 0x00
    TypeRef = 0x01
    TypeDef = 0x02
    Field = 0x04
    MethodDef = 0x06
    Param = 0x08
    InterfaceImpl = 0x09
    MemberRef = 0x0A
    Constant = 0x0B
    CustomAttribute = 0x0C
    FieldMarshal = 0x0D
    DeclSecurity = 0x0E
    ClassLayout = 0x0F
    FieldLayout = 0x10
    StandAloneSig = 0x11
    EventMap = 0x12
    Event = 0x14
    PropertyMap = 0x15
    Property = 0x17
    MethodSemantics = 0x18
    MethodImpl = 0x19
    ModuleRef = 0x1A
    TypeSpec = 0x1B
    ImplMap = 0x1C
    FieldRVA = 0x1D
    Assembly = 0x20
    AssemblyProcessor = 0x21
    AssemblyOS = 0x22
    AssemblyRef = 0x23
    AssemblyRefProcessor = 0x24
    AssemblyRefOS = 0x25
    File = 0x26
    ExportedType = 0x27
    ManifestResource = 0x28
    NestedClass = 0x29
    GenericParam = 0x2A
    MethodSpec = 0x2B
    GenericParamConstraint = 0x2C


# --- what a column holds --------------------------------------------------
# A row class states its columns as `_schema`. A plain int is that many bytes
# of value; the rest are indexes, and how wide they are depends on the file:
# a heap index on how big the heap is, a table index on how many rows the
# table has, a coded index - `coded_index[TypeDefOrRef]`, the class itself -
# on both. The tables are numbered rather than named here because a column
# often points at a table whose class is defined further down than this one.
class _HeapIndex(NamedTuple):
    """An offset into one of the heaps."""

    heap: str


class _TableIndex(NamedTuple):
    """A row index into one table, counting from 1."""

    table: TableNumber


_STRING = _HeapIndex("string")
_BLOB = _HeapIndex("blob")
_GUID = _HeapIndex("guid")


# --- enums ----------------------------------------------------------------
class ElementType(IntEnum):
    End = 0x00
    Void = 0x01
    Boolean = 0x02
    Char = 0x03
    I1 = 0x04
    U1 = 0x05
    I2 = 0x06
    U2 = 0x07
    I4 = 0x08
    U4 = 0x09
    I8 = 0x0A
    U8 = 0x0B
    R4 = 0x0C
    R8 = 0x0D
    String = 0x0E
    Ptr = 0x0F
    ByRef = 0x10
    ValueType = 0x11
    Class = 0x12
    Var = 0x13
    Array = 0x14
    GenericInst = 0x15
    TypedByRef = 0x16
    I = 0x18
    U = 0x19
    FnPtr = 0x1B
    Object = 0x1C
    SZArray = 0x1D
    MVar = 0x1E
    CModReqd = 0x1F
    CModOpt = 0x20
    Internal = 0x21
    Modifier = 0x40
    Sentinel = 0x41
    Pinned = 0x45
    Type = 0x50
    TaggedObject = 0x51
    Field = 0x53
    Property = 0x54
    Enum = 0x55


class CallingConvention(IntFlag):
    Default = 0x00
    VarArg = 0x05
    Field = 0x06
    LocalSig = 0x07
    Property = 0x08
    Mask = 0x0F
    GenericInst = 0x10
    Generic = 0x10
    HasThis = 0x20
    ExplicitThis = 0x40


class ConstantType(IntEnum):
    Boolean = 0x02
    Char = 0x03
    Int8 = 0x04
    UInt8 = 0x05
    Int16 = 0x06
    UInt16 = 0x07
    Int32 = 0x08
    UInt32 = 0x09
    Int64 = 0x0A
    UInt64 = 0x0B
    Float32 = 0x0C
    Float64 = 0x0D
    String = 0x0E
    Class = 0x12


class MemberAccess(IntEnum):
    CompilerControlled = 0
    Private = 1
    FamANDAssem = 2
    Assembly = 3
    Family = 4
    FamORAssem = 5
    Public = 6


class TypeVisibility(IntEnum):
    NotPublic = 0
    Public = 1
    NestedPublic = 2
    NestedPrivate = 3
    NestedFamily = 4
    NestedAssembly = 5
    NestedFamANDAssem = 6
    NestedFamORAssem = 7


class TypeLayout(IntEnum):
    AutoLayout = 0
    SequentialLayout = 1
    ExplicitLayout = 2


class TypeSemantics(IntEnum):
    Class = 0
    Interface = 1


class StringFormat(IntEnum):
    AnsiClass = 0
    UnicodeClass = 1
    AutoClass = 2
    CustomFormatClass = 3


class CodeType(IntEnum):
    IL = 0
    Native = 1
    OPTIL = 2
    Runtime = 3


class Managed(IntEnum):
    Managed = 0
    Unmanaged = 1


class VtableLayout(IntEnum):
    ReuseSlot = 0
    NewSlot = 1


class GenericParamVariance(IntEnum):
    NonVariant = 0
    Covariant = 1
    Contravariant = 2


class category(IntEnum):
    interface_type = 0
    class_type = 1
    enum_type = 2
    struct_type = 3
    delegate_type = 4


# One enum per coded index, as the C++ has, naming the tables that kind can
# point at. `coded_index.type()` returns a table number, so these are table
# numbers rather than the tag values the C++ enums hold, and
# `index.type() == TypeDefOrRef.TypeSpec` reads as it does in C++. The enum is
# also the kind: `coded_index[TypeDefOrRef]` is the class of such a column.
class TypeDefOrRef(IntEnum):
    """The tables a TypeDefOrRef column can point at."""

    TypeDef = TableNumber.TypeDef
    TypeRef = TableNumber.TypeRef
    TypeSpec = TableNumber.TypeSpec


class HasConstant(IntEnum):
    """The tables a HasConstant column can point at."""

    Field = TableNumber.Field
    Param = TableNumber.Param
    Property = TableNumber.Property


class HasCustomAttribute(IntEnum):
    """The tables a HasCustomAttribute column can point at."""

    MethodDef = TableNumber.MethodDef
    Field = TableNumber.Field
    TypeRef = TableNumber.TypeRef
    TypeDef = TableNumber.TypeDef
    Param = TableNumber.Param
    InterfaceImpl = TableNumber.InterfaceImpl
    MemberRef = TableNumber.MemberRef
    Module = TableNumber.Module
    Permission = TableNumber.DeclSecurity
    Property = TableNumber.Property
    Event = TableNumber.Event
    StandAloneSig = TableNumber.StandAloneSig
    ModuleRef = TableNumber.ModuleRef
    TypeSpec = TableNumber.TypeSpec
    Assembly = TableNumber.Assembly
    AssemblyRef = TableNumber.AssemblyRef
    File = TableNumber.File
    ExportedType = TableNumber.ExportedType
    ManifestResource = TableNumber.ManifestResource
    GenericParam = TableNumber.GenericParam
    GenericParamConstraint = TableNumber.GenericParamConstraint
    MethodSpec = TableNumber.MethodSpec


class HasFieldMarshal(IntEnum):
    """The tables a HasFieldMarshal column can point at."""

    Field = TableNumber.Field
    Param = TableNumber.Param


class HasDeclSecurity(IntEnum):
    """The tables a HasDeclSecurity column can point at."""

    TypeDef = TableNumber.TypeDef
    MethodDef = TableNumber.MethodDef
    Assembly = TableNumber.Assembly


class MemberRefParent(IntEnum):
    """The tables a MemberRefParent column can point at."""

    TypeDef = TableNumber.TypeDef
    TypeRef = TableNumber.TypeRef
    ModuleRef = TableNumber.ModuleRef
    MethodDef = TableNumber.MethodDef
    TypeSpec = TableNumber.TypeSpec


class HasSemantics(IntEnum):
    """The tables a HasSemantics column can point at."""

    Event = TableNumber.Event
    Property = TableNumber.Property


class MethodDefOrRef(IntEnum):
    """The tables a MethodDefOrRef column can point at."""

    MethodDef = TableNumber.MethodDef
    MemberRef = TableNumber.MemberRef


class MemberForwarded(IntEnum):
    """The tables a MemberForwarded column can point at."""

    Field = TableNumber.Field
    MethodDef = TableNumber.MethodDef


class Implementation(IntEnum):
    """The tables an Implementation column can point at."""

    File = TableNumber.File
    AssemblyRef = TableNumber.AssemblyRef
    ExportedType = TableNumber.ExportedType


class CustomAttributeType(IntEnum):
    """The tables a CustomAttributeType column can point at.

    The C++ starts this one at tag 2, the tags below it being reserved; here
    the values are tables, so only the two that name one are here.
    """

    MethodDef = TableNumber.MethodDef
    MemberRef = TableNumber.MemberRef


class ResolutionScope(IntEnum):
    """The tables a ResolutionScope column can point at."""

    Module = TableNumber.Module
    ModuleRef = TableNumber.ModuleRef
    AssemblyRef = TableNumber.AssemblyRef
    TypeRef = TableNumber.TypeRef


class TypeOrMethodDef(IntEnum):
    """The tables a TypeOrMethodDef column can point at."""

    TypeDef = TableNumber.TypeDef
    MethodDef = TableNumber.MethodDef


def enum_mask(value, mask):
    """The C++ enum_mask: the bits of `value` that `mask` selects."""
    return type(value)(int(value) & int(mask))


# --- the flag structs -----------------------------------------------------
class _Flags:
    """One metadata flags column, with an accessor per field.

    Fields are declared as name -> (mask, shift, type); a type of None gives a
    bool. The C++ side spells these as methods, and so do these.
    """

    _fields: Dict[str, Tuple[int, int, Any]] = {}

    __slots__ = ("value",)

    def __init__(self, value: int):
        self.value = value

    def __int__(self) -> int:
        return self.value

    def __index__(self) -> int:
        return self.value

    def __repr__(self):
        return f"<{type(self).__name__} {self.value:#x}>"

    def __eq__(self, other):
        return isinstance(other, _Flags) and self.value == other.value

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for name, (mask, shift, kind) in cls._fields.items():
            def accessor(self, mask=mask, shift=shift, kind=kind):
                raw = (self.value & mask) >> shift
                return bool(raw) if kind is None else kind(raw)
            setattr(cls, name, accessor)


class TypeAttributes(_Flags):
    _fields = {
        "Visibility": (0x00000007, 0, TypeVisibility),
        "Layout": (0x00000018, 3, TypeLayout),
        "Semantics": (0x00000020, 5, TypeSemantics),
        "Abstract": (0x00000080, 7, None),
        "Sealed": (0x00000100, 8, None),
        "SpecialName": (0x00000400, 10, None),
        "Import": (0x00001000, 12, None),
        "Serializable": (0x00002000, 13, None),
        "WindowsRuntime": (0x00004000, 14, None),
        "StringFormat": (0x00030000, 16, StringFormat),
        "BeforeFieldInit": (0x00100000, 20, None),
        "RTSpecialName": (0x00000800, 11, None),
        "HasSecurity": (0x00040000, 18, None),
        "IsTypeForwarder": (0x00200000, 21, None),
    }


class MethodAttributes(_Flags):
    _fields = {
        "Access": (0x0007, 0, MemberAccess),
        "UnmanagedExport": (0x0008, 3, None),
        "Static": (0x0010, 4, None),
        "Final": (0x0020, 5, None),
        "Virtual": (0x0040, 6, None),
        "HideBySig": (0x0080, 7, None),
        "VtableLayout": (0x0100, 8, VtableLayout),
        "Strict": (0x0200, 9, None),
        "Abstract": (0x0400, 10, None),
        "SpecialName": (0x0800, 11, None),
        "PInvokeImpl": (0x2000, 13, None),
        "RTSpecialName": (0x1000, 12, None),
        "HasSecurity": (0x4000, 14, None),
        "RequireSecObject": (0x8000, 15, None),
    }


class MethodImplAttributes(_Flags):
    _fields = {
        "CodeType": (0x0003, 0, CodeType),
        "Managed": (0x0004, 2, Managed),
        "ForwardRef": (0x0010, 4, None),
        "PreserveSig": (0x0080, 7, None),
        "InternalCall": (0x1000, 12, None),
        "Synchronized": (0x0020, 5, None),
        "NoInlining": (0x0008, 3, None),
        "NoOptimization": (0x0040, 6, None),
    }


class FieldAttributes(_Flags):
    _fields = {
        "Access": (0x0007, 0, MemberAccess),
        "Static": (0x0010, 4, None),
        "InitOnly": (0x0020, 5, None),
        "Literal": (0x0040, 6, None),
        "NotSerialized": (0x0080, 7, None),
        "SpecialName": (0x0200, 9, None),
        "PInvokeImpl": (0x2000, 13, None),
        "RTSpecialName": (0x0400, 10, None),
        "HasFieldMarshal": (0x1000, 12, None),
        "HasDefault": (0x8000, 15, None),
        "HasFieldRVA": (0x0100, 8, None),
    }


class ParamAttributes(_Flags):
    _fields = {
        "In": (0x0001, 0, None),
        "Out": (0x0002, 1, None),
        "Optional": (0x0010, 4, None),
        "HasDefault": (0x1000, 12, None),
        "HasFieldMarshal": (0x2000, 13, None),
    }


class PropertyAttributes(_Flags):
    _fields = {
        "SpecialName": (0x0200, 9, None),
        "RTSpecialName": (0x0400, 10, None),
        "HasDefault": (0x1000, 12, None),
    }


class EventAttributes(_Flags):
    _fields = {
        "SpecialName": (0x0200, 9, None),
        "RTSpecialName": (0x0400, 10, None),
    }


class MethodSemanticsAttributes(_Flags):
    _fields = {
        "Setter": (0x0001, 0, None),
        "Getter": (0x0002, 1, None),
        "Other": (0x0004, 2, None),
        "AddOn": (0x0008, 3, None),
        "RemoveOn": (0x0010, 4, None),
        "Fire": (0x0020, 5, None),
    }


class GenericParamAttributes(_Flags):
    _fields = {
        "Variance": (0x0003, 0, GenericParamVariance),
        "SpecialConstraint": (0x001C, 2, None),
    }


class AssemblyAttributes(_Flags):
    _fields = {
        "PublicKey": (0x0001, 0, None),
        "Retargetable": (0x0100, 8, None),
        "WindowsRuntime": (0x0200, 9, None),
        "DisableJITcompileOptimizer": (0x4000, 14, None),
        "EnableJITcompileTracking": (0x8000, 15, None),
    }


class PInvokeAttributes(_Flags):
    _fields = {
        "NoMangle": (0x0001, 0, None),
        "CharSet": (0x0006, 1, None),
        "SupportsLastError": (0x0040, 6, None),
        "CallConv": (0x0700, 8, None),
    }


# --- blob reading ---------------------------------------------------------
def uncompress_unsigned(data: bytes, position: int) -> Tuple[int, int]:
    first = data[position]
    if not first & 0x80:
        return first, position + 1
    if first & 0xC0 == 0x80:
        return ((first & 0x3F) << 8) | data[position + 1], position + 2
    if first & 0xE0 == 0xC0:
        return (((first & 0x1F) << 24) | (data[position + 1] << 16) |
                (data[position + 2] << 8) | data[position + 3]), position + 4
    raise ValueError("invalid compressed integer in blob")


class byte_view:
    """A bounded view of bytes, and the cursor every signature is read with.

    Named as the C++ names it: `as_uint32(offset)`, `seek(offset)` and
    `sub(offset, size)` do what they do there, and it is also a sequence of
    bytes, so `len()`, `[]` and `bytes()` work. A blob out of the #Blob heap
    is one of these, and knows the database it came from.
    """

    __slots__ = ("data", "position", "end", "table")

    def __init__(self, data: bytes, position: int = 0, size: int = None,
                 table: database = None):
        self.data = data
        self.position = position
        self.end = position + (len(data) - position if size is None else size)
        self.table = table

    # --- as a view
    def as_uint8(self, offset: int = 0) -> int:
        return self._read("<B", offset)

    def as_uint16(self, offset: int = 0) -> int:
        return self._read("<H", offset)

    def as_uint32(self, offset: int = 0) -> int:
        return self._read("<I", offset)

    def as_uint64(self, offset: int = 0) -> int:
        return self._read("<Q", offset)

    def _read(self, format: str, offset: int) -> int:
        if offset < 0 or self.position + offset + struct.calcsize(format) > self.end:
            raise ValueError("reading past the end of the view")
        return struct.unpack_from(format, self.data, self.position + offset)[0]

    def seek(self, offset: int) -> byte_view:
        """The same view, `offset` bytes further in."""
        if offset < 0 or self.position + offset > self.end:
            raise ValueError("seeking past the end of the view")
        return byte_view(self.data, self.position + offset, self.end - self.position - offset,
                    self.table)

    def sub(self, offset: int, size: int) -> byte_view:
        if offset < 0 or size < 0 or self.position + offset + size > self.end:
            raise ValueError("the sub view does not fit")
        return byte_view(self.data, self.position + offset, size, self.table)

    def as_bytes(self) -> bytes:
        return self.data[self.position:self.end]

    def unsigned(self) -> int:
        value, self.position = uncompress_unsigned(self.data, self.position)
        return value

    def element_type(self) -> ElementType:
        return ElementType(self.unsigned())

    def peek_element_type(self) -> ElementType:
        value, _ = uncompress_unsigned(self.data, self.position)
        return ElementType(value)

    def read(self, format: str) -> Any:
        value = struct.unpack_from(format, self.data, self.position)[0]
        self.position += struct.calcsize(format)
        return value

    def string(self) -> str:
        length = self.unsigned()
        value = self.data[self.position:self.position + length].decode("utf-8")
        self.position += length
        return value

    def coded_index(self, kind: type) -> coded_index:
        """The next compressed value, as `coded_index[TypeDefOrRef]` or such."""
        return kind(self.table, self.unsigned())

    def __bool__(self) -> bool:
        return self.position < self.end

    # It is also just bytes, which is what the C++ offers.
    def __len__(self) -> int:
        return self.end - self.position

    def __bytes__(self) -> bytes:
        return self.data[self.position:self.end]

    def __getitem__(self, index):
        if isinstance(index, slice):
            return bytes(self)[index]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return self.data[self.position + index]


# --- signatures -----------------------------------------------------------
class GenericTypeIndex:
    __slots__ = ("index",)

    def __init__(self, index: int):
        self.index = index

    def __repr__(self):
        return f"<GenericTypeIndex {self.index}>"

    def __eq__(self, other):
        return isinstance(other, GenericTypeIndex) and self.index == other.index


class GenericMethodTypeIndex:
    __slots__ = ("index",)

    def __init__(self, index: int):
        self.index = index

    def __repr__(self):
        return f"<GenericMethodTypeIndex {self.index}>"

    def __eq__(self, other):
        return isinstance(other, GenericMethodTypeIndex) and self.index == other.index


class CustomModSig:
    __slots__ = ("_kind", "_type")

    def __init__(self, blob: byte_view):
        self._kind = blob.element_type()
        self._type = blob.coded_index(coded_index[TypeDefOrRef])

    def CustomMod(self) -> ElementType:
        return self._kind

    def Type(self) -> coded_index:
        return self._type


def _parse_cmods(blob: byte_view) -> List[CustomModSig]:
    mods = []
    while blob.peek_element_type() in (ElementType.CModOpt, ElementType.CModReqd):
        mods.append(CustomModSig(blob))
    return mods


class GenericTypeInstSig:
    __slots__ = ("_class_or_value", "_type", "_args")

    def __init__(self, blob: byte_view):
        self._class_or_value = blob.element_type()
        if self._class_or_value not in (ElementType.Class, ElementType.ValueType):
            raise ValueError("a generic instantiation starts with Class or ValueType")
        self._type = blob.coded_index(coded_index[TypeDefOrRef])
        count = blob.unsigned()
        self._args = [TypeSig(blob) for _ in range(count)]

    def ClassOrValueType(self) -> ElementType:
        return self._class_or_value

    def GenericType(self) -> coded_index:
        return self._type

    def GenericArgCount(self) -> int:
        return len(self._args)

    def GenericArgs(self) -> List["TypeSig"]:
        return self._args


class TypeSig:
    """A type as a signature spells it; Type() is the interesting part."""

    __slots__ = ("_szarray", "_array", "_ptr_count", "_cmod", "_element_type",
                 "_type", "_array_rank", "_array_sizes")

    def __init__(self, blob: byte_view):
        self._szarray = False
        self._array = False
        self._ptr_count = 0
        self._array_rank = 0
        self._array_sizes: List[int] = []

        if blob.peek_element_type() == ElementType.SZArray:
            blob.element_type()
            self._szarray = True
        if blob.peek_element_type() == ElementType.Array:
            blob.element_type()
            self._array = True
        while blob.peek_element_type() == ElementType.Ptr:
            blob.element_type()
            self._ptr_count += 1
        self._cmod = _parse_cmods(blob)
        self._element_type = blob.peek_element_type()
        self._type = self._parse(blob)
        if self._array:
            self._array_rank = blob.unsigned()
            count = blob.unsigned()
            self._array_sizes = [blob.unsigned() for _ in range(count)]

    @staticmethod
    def _parse(blob: byte_view):
        element_type = blob.element_type()
        if element_type in _PRIMITIVE_TYPES:
            return element_type
        if element_type in (ElementType.Class, ElementType.ValueType):
            return blob.coded_index(coded_index[TypeDefOrRef])
        if element_type == ElementType.GenericInst:
            return GenericTypeInstSig(blob)
        if element_type == ElementType.Var:
            return GenericTypeIndex(blob.unsigned())
        if element_type == ElementType.MVar:
            return GenericMethodTypeIndex(blob.unsigned())
        raise ValueError(f"unrecognised element type {element_type!r}")

    def Type(self):
        return self._type

    def element_type(self) -> ElementType:
        return self._element_type

    def is_szarray(self) -> bool:
        return self._szarray

    def is_array(self) -> bool:
        return self._array

    def array_rank(self) -> int:
        return self._array_rank

    def array_sizes(self) -> List[int]:
        return self._array_sizes

    def ptr_count(self) -> int:
        return self._ptr_count

    def CustomMod(self) -> List[CustomModSig]:
        return self._cmod


_PRIMITIVE_TYPES = frozenset((
    ElementType.Boolean, ElementType.Char, ElementType.I1, ElementType.U1,
    ElementType.I2, ElementType.U2, ElementType.I4, ElementType.U4,
    ElementType.I8, ElementType.U8, ElementType.R4, ElementType.R8,
    ElementType.String, ElementType.Object, ElementType.U, ElementType.I,
    ElementType.Void,
))


class ParamSig:
    __slots__ = ("_cmod", "_byref", "_type")

    def __init__(self, blob: byte_view):
        self._cmod = _parse_cmods(blob)
        self._byref = _is_by_ref(blob)
        self._type = TypeSig(blob)

    def CustomMod(self) -> List[CustomModSig]:
        return self._cmod

    def ByRef(self) -> bool:
        return self._byref

    def Type(self) -> TypeSig:
        return self._type


class RetTypeSig:
    __slots__ = ("_cmod", "_byref", "_type")

    def __init__(self, blob: byte_view):
        self._cmod = _parse_cmods(blob)
        self._byref = _is_by_ref(blob)
        if blob.peek_element_type() == ElementType.Void:
            blob.element_type()
            self._type = None
        else:
            self._type = TypeSig(blob)

    def CustomMod(self) -> List[CustomModSig]:
        return self._cmod

    def ByRef(self) -> bool:
        return self._byref

    def Type(self) -> TypeSig:
        if self._type is None:
            raise RuntimeError("the return type is void")
        return self._type

    def __bool__(self) -> bool:
        return self._type is not None


def _is_by_ref(blob: byte_view) -> bool:
    if blob.peek_element_type() == ElementType.ByRef:
        blob.element_type()
        return True
    return False


class MethodDefSig:
    __slots__ = ("_convention", "_generic_count", "_return", "_params")

    def __init__(self, blob: byte_view):
        self._convention = CallingConvention(blob.unsigned())
        self._generic_count = blob.unsigned() if enum_mask(
            self._convention, CallingConvention.Generic) == CallingConvention.Generic else 0
        count = blob.unsigned()
        self._return = RetTypeSig(blob)
        self._params = [ParamSig(blob) for _ in range(count)]

    def CallConvention(self) -> CallingConvention:
        return self._convention

    def GenericParamCount(self) -> int:
        return self._generic_count

    def ReturnType(self) -> RetTypeSig:
        return self._return

    def Params(self) -> List[ParamSig]:
        return self._params


class FieldSig:
    __slots__ = ("_convention", "_cmod", "_type")

    def __init__(self, blob: byte_view):
        self._convention = CallingConvention(blob.unsigned())
        if enum_mask(self._convention, CallingConvention.Field) != CallingConvention.Field:
            raise ValueError("a field signature starts with the Field convention")
        self._cmod = _parse_cmods(blob)
        self._type = TypeSig(blob)

    def CustomMod(self) -> List[CustomModSig]:
        return self._cmod

    def Type(self) -> TypeSig:
        return self._type


class PropertySig:
    __slots__ = ("_convention", "_cmod", "_type", "_params")

    def CallConvention(self) -> CallingConvention:
        return self._convention

    def __init__(self, blob: byte_view):
        self._convention = CallingConvention(blob.unsigned())
        if enum_mask(self._convention, CallingConvention.Property) != CallingConvention.Property:
            raise ValueError("a property signature starts with the Property convention")
        count = blob.unsigned()
        self._cmod = _parse_cmods(blob)
        self._type = TypeSig(blob)
        self._params = [ParamSig(blob) for _ in range(count)]

    def CustomMod(self) -> List[CustomModSig]:
        return self._cmod

    def Type(self) -> TypeSig:
        return self._type

    def Params(self) -> List[ParamSig]:
        return self._params


class TypeSpecSig:
    __slots__ = ("_type",)

    def __init__(self, blob: byte_view):
        if blob.peek_element_type() != ElementType.GenericInst:
            raise ValueError("a TypeSpec signature is a generic instantiation")
        blob.element_type()
        self._type = GenericTypeInstSig(blob)

    def GenericTypeInst(self) -> GenericTypeInstSig:
        return self._type


# --- custom attributes ----------------------------------------------------
class SystemType:
    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return f"<ElemSig.SystemType {self.name!r}>"


class EnumValue:
    __slots__ = ("type", "value")

    def __init__(self, definition: EnumDefinition, value):
        self.type = definition
        self.value = value

    def equals_enumerator(self, name: str) -> bool:
        return self.type.get_enumerator(name).Constant().Value() == self.value

    def __repr__(self):
        return f"<ElemSig.EnumValue {self.value}>"


class ElemSig:
    """One decoded argument of a custom attribute."""

    SystemType = SystemType
    EnumValue = EnumValue

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"<ElemSig {self.value!r}>"


_PRIMITIVE_READERS = {
    ElementType.Boolean: ("<?", None),
    ElementType.Char: ("<H", "char"),
    ElementType.I1: ("<b", None),
    ElementType.U1: ("<B", None),
    ElementType.I2: ("<h", None),
    ElementType.U2: ("<H", None),
    ElementType.I4: ("<i", None),
    ElementType.U4: ("<I", None),
    ElementType.I8: ("<q", None),
    ElementType.U8: ("<Q", None),
    ElementType.R4: ("<f", None),
    ElementType.R8: ("<d", None),
}


def _read_primitive(kind: ElementType, blob: byte_view):
    if kind == ElementType.String:
        return blob.string()
    try:
        format, special = _PRIMITIVE_READERS[kind]
    except KeyError:
        raise ValueError(f"non-primitive type {kind!r} in a custom attribute") from None
    value = blob.read(format)
    return chr(value) if special == "char" else value


class FixedArgSig:
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class NamedArgSig:
    __slots__ = ("name", "value")

    def __init__(self, name: str, value: FixedArgSig):
        self.name = name
        self.value = value


class CustomAttributeSig:
    __slots__ = ("_fixed", "_named")

    def __init__(self, database: database, blob: byte_view, signature: MethodDefSig):
        if blob.read("<H") != 0x0001:
            raise ValueError("a custom attribute blob starts with the prolog 0x0001")
        self._fixed = [FixedArgSig(_read_argument(database, param, blob))
                       for param in signature.Params()]
        self._named = [_read_named(database, blob) for _ in range(blob.read("<H"))]

    def FixedArgs(self) -> List[FixedArgSig]:
        return self._fixed

    def NamedArgs(self) -> List[NamedArgSig]:
        return self._named


def _read_argument(database: database, param: ParamSig, blob: byte_view):
    """One positional argument, whose type comes from the constructor."""
    type = param.Type()
    value = type.Type()
    if isinstance(value, ElementType):
        if type.is_szarray():
            return _read_array(value, blob)
        return ElemSig(_read_primitive(value, blob))
    if isinstance(value, coded_index):
        namespace, name = get_type_namespace_and_name(value)
        if namespace == "System" and name == "Type":
            return ElemSig(SystemType(blob.string()))
        definition = find_required(value)
        if not definition.is_enum():
            raise ValueError("a custom attribute argument must be an enum or System.Type")
        enum = definition.get_enum_definition()
        return ElemSig(EnumValue(enum, _read_enum(enum.m_underlying_type, blob)))
    raise ValueError("a custom attribute argument must be a primitive, an enum or System.Type")


def _read_array(kind: ElementType, blob: byte_view):
    count = blob.read("<I")
    if count == 0xFFFFFFFF:
        return []
    return [ElemSig(_read_primitive(kind, blob)) for _ in range(count)]


def _read_enum(kind: ElementType, blob: byte_view):
    if kind not in _PRIMITIVE_READERS or kind in (ElementType.R4, ElementType.R8):
        raise ValueError(f"{kind!r} cannot be the underlying type of an enum")
    return _read_primitive(kind, blob)


def _read_named(database: database, blob: byte_view) -> NamedArgSig:
    kind = blob.element_type()
    if kind not in (ElementType.Field, ElementType.Property):
        raise ValueError("a named argument is either a field or a property")
    kind = blob.element_type()

    if kind == ElementType.Type:
        name = blob.string()
        return NamedArgSig(name, FixedArgSig(ElemSig(SystemType(blob.string()))))
    if kind == ElementType.Enum:
        type_name = blob.string()
        name = blob.string()
        definition = database.get_cache().find(type_name)
        if not definition:
            raise ValueError(f"a named argument names the unknown enum {type_name}")
        enum = definition.get_enum_definition()
        return NamedArgSig(name, FixedArgSig(
            ElemSig(EnumValue(enum, _read_enum(enum.m_underlying_type, blob)))))

    is_array = kind == ElementType.SZArray
    if is_array:
        kind = blob.element_type()
    if not ElementType.Boolean <= kind <= ElementType.String:
        raise ValueError("a named argument must be a primitive, System.Type or an enum")
    name = blob.string()
    if is_array:
        return NamedArgSig(name, FixedArgSig(_read_array(kind, blob)))
    return NamedArgSig(name, FixedArgSig(ElemSig(_read_primitive(kind, blob))))


class EnumDefinition:
    __slots__ = ("m_typedef", "m_underlying_type")

    def __init__(self, type: TypeDef):
        self.m_typedef = type
        self.m_underlying_type = ElementType.End
        for field in type.FieldList():
            flags = field.Flags()
            if not flags.Literal() and not flags.Static():
                self.m_underlying_type = field.Signature().Type().Type()

    def get_enumerator(self, name: str) -> Field:
        for field in self.m_typedef.FieldList():
            if field.Name() == name:
                return field
        raise KeyError(name)

    def __repr__(self):
        return (f"<EnumDefinition {self.m_typedef.TypeNamespace()}."
                f"{self.m_typedef.TypeName()}>")


# --- coded indexes --------------------------------------------------------
# The class of each kind, filled in by the subclasses below.
_CODED_CLASSES: Dict[str, type] = {}


class coded_index:
    """A column that may point at one of several tables.

    The C++ side is a template, `coded_index<TypeDefOrRef>`, and so is this:
    write `coded_index[TypeDefOrRef]`, or `coded_index[HasSemantics]` for the
    kinds that have no enum of their own. That is the class a column's values
    are; the base holds no kind and is not one of them. Each kind states its
    tables and its tag width in its own class, `coded_index_TypeDefOrRef` and
    the rest, defined below.
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
    # is 2 or 4 bytes wide. This follows the C++ reader exactly, which leaves
    # Permission out of HasCustomAttribute; the tag count is what sets the
    # number of bits either way. It is the tag order unless a class says so.
    _kind: str = None                            # the name in the standard
    _tables: Tuple[Optional[int], ...] = ()
    _bits = 0                                    # how many bits the tag takes
    _mask = 0                                    # (1 << _bits) - 1
    _sizing_tables: Tuple[Optional[int], ...] = None
    _tags: Dict[int, int] = {}                   # _tables, table -> tag

    def __init_subclass__(cls, **kwargs):
        """A subclass states one kind, and is the class of that kind here."""
        super().__init_subclass__(**kwargs)
        if cls._sizing_tables is None:
            cls._sizing_tables = cls._tables
        # _tables read the other way round, for encode().
        cls._tags = {table: tag for tag, table in enumerate(cls._tables)
                     if table is not None}
        _CODED_CLASSES[cls._kind] = cls

    def __class_getitem__(cls, kind):
        """The class for one kind, by its name or by the enum of that name."""
        return _CODED_CLASSES[getattr(kind, "__name__", kind)]

    def __init__(self, database: database, value: int):
        if self._kind is None:
            raise TypeError("coded_index[kind] is the class to instantiate")
        self._database = database
        self._value = value

    def type(self) -> int:
        """The table this points at, as a table number."""
        return self._tables[self._value & self._mask]

    def index(self) -> int:
        return (self._value >> self._bits) - 1

    @classmethod
    def encode(cls, table: TableNumber, index: int) -> int:
        """What a column of this kind holds to point at that row of that table."""
        return ((index + 1) << cls._bits) | cls._tags[table]

    def kind(self) -> str:
        return self._kind

    def get_row(self) -> Row:
        return make_row(self._database, self.type(), self.index())

    def __getattr__(self, name: str) -> Row:
        """`index.TypeRef()` and friends, as the C++ side spells get_row().

        The name has to be the table the index actually points at; asking for
        another one is the mistake the C++ assert catches.
        """
        try:
            table = TableNumber[name]
        except KeyError:
            raise AttributeError(name) from None

        def get(table=table):
            if not self:
                raise RuntimeError(f"the {self._kind} index is not set")
            if self.type() != table:
                raise TypeError(f"the index points at {self.type().name}, "
                                f"not {table.name}")
            return self.get_row()
        return get

    def get_database(self) -> database:
        return self._database

    def __bool__(self) -> bool:
        return self._value != 0

    def __eq__(self, other):
        return (isinstance(other, coded_index) and self._kind == other._kind
                and self._value == other._value and self._database is other._database)

    def __hash__(self):
        return hash((self._kind, self._value))

    def __repr__(self):
        if not self:
            return f"<coded_index {self._kind} (invalid)>"
        return f"<coded_index {self._kind} -> {self.type().name}[{self.index()}]>"


# One class per kind, as the C++ template gives one type per kind:
# coded_index<TypeDefOrRef> is coded_index_TypeDefOrRef.
class coded_index_TypeDefOrRef(coded_index):
    """A TypeDefOrRef column: a TypeDef, a TypeRef or a TypeSpec."""

    __slots__ = ()
    _kind = "TypeDefOrRef"
    _tables = (TableNumber.TypeDef, TableNumber.TypeRef, TableNumber.TypeSpec)
    _bits = 2
    _mask = 0b11


class coded_index_HasConstant(coded_index):
    """A HasConstant column: what a Constant row belongs to."""

    __slots__ = ()
    _kind = "HasConstant"
    _tables = (TableNumber.Field, TableNumber.Param, TableNumber.Property)
    _bits = 2
    _mask = 0b11


class coded_index_HasCustomAttribute(coded_index):
    """A HasCustomAttribute column: what an attribute is attached to."""

    __slots__ = ()
    _kind = "HasCustomAttribute"
    _tables = (
        TableNumber.MethodDef, TableNumber.Field, TableNumber.TypeRef, TableNumber.TypeDef, TableNumber.Param, TableNumber.InterfaceImpl, TableNumber.MemberRef,
        TableNumber.Module, TableNumber.DeclSecurity, TableNumber.Property, TableNumber.Event, TableNumber.StandAloneSig, TableNumber.ModuleRef,
        TableNumber.TypeSpec, TableNumber.Assembly, TableNumber.AssemblyRef, TableNumber.File, TableNumber.ExportedType,
        TableNumber.ManifestResource, TableNumber.GenericParam, TableNumber.GenericParamConstraint, TableNumber.MethodSpec)
    _bits = 5
    _mask = 0b11111
    # The C++ reader sizes this one on 21 tables, leaving Permission out.
    _sizing_tables = tuple(table for table in _tables if table != TableNumber.DeclSecurity)


class coded_index_HasFieldMarshal(coded_index):
    """A HasFieldMarshal column: a Field or a Param."""

    __slots__ = ()
    _kind = "HasFieldMarshal"
    _tables = (TableNumber.Field, TableNumber.Param)
    _bits = 1
    _mask = 0b1


class coded_index_HasDeclSecurity(coded_index):
    """A HasDeclSecurity column: a TypeDef, a MethodDef or the Assembly."""

    __slots__ = ()
    _kind = "HasDeclSecurity"
    _tables = (TableNumber.TypeDef, TableNumber.MethodDef, TableNumber.Assembly)
    _bits = 2
    _mask = 0b11


class coded_index_MemberRefParent(coded_index):
    """A MemberRefParent column: what a MemberRef is a member of."""

    __slots__ = ()
    _kind = "MemberRefParent"
    _tables = (TableNumber.TypeDef, TableNumber.TypeRef, TableNumber.ModuleRef, TableNumber.MethodDef, TableNumber.TypeSpec)
    _bits = 3
    _mask = 0b111


class coded_index_HasSemantics(coded_index):
    """A HasSemantics column: an Event or a Property."""

    __slots__ = ()
    _kind = "HasSemantics"
    _tables = (TableNumber.Event, TableNumber.Property)
    _bits = 1
    _mask = 0b1


class coded_index_MethodDefOrRef(coded_index):
    """A MethodDefOrRef column: a MethodDef or a MemberRef."""

    __slots__ = ()
    _kind = "MethodDefOrRef"
    _tables = (TableNumber.MethodDef, TableNumber.MemberRef)
    _bits = 1
    _mask = 0b1


class coded_index_MemberForwarded(coded_index):
    """A MemberForwarded column: what an ImplMap row forwards."""

    __slots__ = ()
    _kind = "MemberForwarded"
    _tables = (TableNumber.Field, TableNumber.MethodDef)
    _bits = 1
    _mask = 0b1


class coded_index_Implementation(coded_index):
    """An Implementation column: a File, an AssemblyRef or an ExportedType."""

    __slots__ = ()
    _kind = "Implementation"
    _tables = (TableNumber.File, TableNumber.AssemblyRef, TableNumber.ExportedType)
    _bits = 2
    _mask = 0b11


class coded_index_CustomAttributeType(coded_index):
    """A CustomAttributeType column: the attribute's constructor."""

    __slots__ = ()
    _kind = "CustomAttributeType"
    _tables = (None, None, TableNumber.MethodDef, TableNumber.MemberRef, None)
    _bits = 3
    _mask = 0b111


class coded_index_ResolutionScope(coded_index):
    """A ResolutionScope column: where a TypeRef is to be looked for."""

    __slots__ = ()
    _kind = "ResolutionScope"
    _tables = (TableNumber.Module, TableNumber.ModuleRef, TableNumber.AssemblyRef, TableNumber.TypeRef)
    _bits = 2
    _mask = 0b11


class coded_index_TypeOrMethodDef(coded_index):
    """A TypeOrMethodDef column: what a GenericParam belongs to."""

    __slots__ = ()
    _kind = "TypeOrMethodDef"
    _tables = (TableNumber.TypeDef, TableNumber.MethodDef)
    _bits = 1
    _mask = 0b1


# --- rows -----------------------------------------------------------------
# What a range, a list and a table hold: `RowRange[MethodDef]` is what
# `TypeDef.MethodList()` returns, as `std::pair<MethodDef, MethodDef>` is in C++.
RowT = TypeVar("RowT", bound="Row")


class RowRange(Sequence[RowT]):
    """A member list: the rows of a table from one index to another."""

    __slots__ = ("_database", "_table", "_first", "_last")

    def __init__(self, database: database, table: TableNumber, first: int, last: int):
        self._database = database
        self._table = table
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
        return make_row(self._database, self._table, self._first)

    @property
    def second(self) -> RowT:
        return make_row(self._database, self._table, self._last)

    def __getitem__(self, index) -> RowT:
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return make_row(self._database, self._table, self._first + index)

    def __repr__(self):
        return f"<{self._table.name}_range {len(self)}>"


class AssemblyVersion(NamedTuple):
    """The four numbers of an assembly version, as the C++ struct has them."""

    MajorVersion: int
    MinorVersion: int
    BuildNumber: int
    RevisionNumber: int


class RowList(Sequence[RowT]):
    """Rows of a table that are not next to each other."""

    __slots__ = ("_database", "_table", "_indexes")

    def __init__(self, database: database, table: TableNumber, indexes: List[int]):
        self._database = database
        self._table = table
        self._indexes = indexes

    def __len__(self) -> int:
        return len(self._indexes)

    def __getitem__(self, index) -> RowT:
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        return make_row(self._database, self._table, self._indexes[index])

    def __repr__(self):
        return f"<{self._table.name}_list {len(self)}>"


# The class of each table, filled in by the subclasses below.
_ROW_CLASSES: Dict[TableNumber, type] = {}


class Row:
    """One row of one table.

    A row is a value: the database and the index. Which table it is from is
    the class it is - one per table below, holding the accessors that table
    has, as the C++ has a struct per table.
    """

    __slots__ = ("_database", "_index", "_columns")

    _table: TableNumber = None
    _schema: Tuple[Any, ...] = ()                # what each column holds

    def __init_subclass__(cls, **kwargs):
        """A subclass is one table, and is the class of that table's rows."""
        super().__init_subclass__(**kwargs)
        assert cls._table.name == cls.__name__, cls.__name__
        _ROW_CLASSES[cls._table] = cls

    def __init__(self, database: database, index: int):
        self._database = database
        self._index = index
        self._columns = None

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
                raise RuntimeError(
                    f"{self._table.name}[{self._index}] is not a row")
            self._columns = self._database.row(self._table, self._index)
        return self._columns[column]

    def __bool__(self) -> bool:
        return self._index >= 0 and self._index < self._database.rows(self._table)

    def __eq__(self, other):
        return (isinstance(other, Row) and self._table == other._table
                and self._index == other._index
                and self._database is other._database)

    def __lt__(self, other):
        return self._index < other._index

    def __le__(self, other):
        return self._index <= other._index

    def __gt__(self, other):
        return self._index > other._index

    def __ge__(self, other):
        return self._index >= other._index

    # A row is an iterator over its own table in C++, and these come with that.
    def __add__(self, offset: int) -> Row:
        return type(self)(self._database, self._index + offset)

    def __sub__(self, other):
        if isinstance(other, Row):
            return self._index - other._index
        return type(self)(self._database, self._index - other)

    def __hash__(self):
        return hash((id(self._database), self._table, self._index))

    def __repr__(self):
        return f"<{self._table.name}[{self._index}]>"

    # --- what the columns mean
    def _string(self, column: int) -> str:
        return self._database.string(self.get_value(column))

    def _blob(self, column: int) -> byte_view:
        return self._database.blob(self.get_value(column))

    def _coded(self, column: int, kind: type) -> coded_index:
        """One column, as `coded_index[TypeDefOrRef]` or whichever kind it is."""
        return kind(self._database, self.get_value(column))

    def _row(self, column: int, table: TableNumber) -> Row:
        return make_row(self._database, table, self.get_value(column) - 1)

    def _list(self, column: int, table: TableNumber) -> RowRange:
        """my first child until the next row's first child."""
        first = self.get_value(column) - 1
        if self._index + 1 < self._database.rows(self._table):
            last = self._database.row(self._table, self._index + 1)[column] - 1
        else:
            last = self._database.rows(table)
        return RowRange(self._database, table, first, last)

    # --- the other direction: rows whose coded index column points at me
    def _referrers(self, kind: type, table: TableNumber, column: int) -> RowRange:
        return self._database.equal_range(
            table, column, kind.encode(self._table, self._index))

    def _referrer(self, kind: type, table: TableNumber, column: int) -> Row:
        return self._database.find_row(
            table, column, kind.encode(self._table, self._index))

    def _attributes(self) -> RowRange[CustomAttribute]:
        """The attributes applied to me, which most tables can carry."""
        return self._referrers(coded_index[HasCustomAttribute], TableNumber.CustomAttribute, 0)

    def _constant(self) -> Constant:
        row = self._referrer(coded_index[HasConstant], TableNumber.Constant, 1)
        if not row:
            raise RuntimeError("there is no constant for this row")
        return row

    def _version(self, column: int) -> AssemblyVersion:
        """Four uint16 in one column, which no accessor of ours can read."""
        offset, _ = self._database._columns[self._table][column]
        start = (self._database._start[self._table]
                 + self._index * self._database._row_size[self._table] + offset)
        return AssemblyVersion(*struct.unpack_from(
            "<HHHH", self._database._tables, start))


# --- one class per table, with the accessors that table has ----------------
class Module(Row):
    """A row of the Module table."""

    __slots__ = ()
    _table = TableNumber.Module
    _schema = (2, _STRING, _GUID, _GUID, _GUID)

    def Generation(self) -> int:
        return self.get_value(0)

    def Name(self) -> str:
        return self._string(1)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class TypeRef(Row):
    """A row of the TypeRef table."""

    __slots__ = ()
    _table = TableNumber.TypeRef
    _schema = (coded_index[ResolutionScope], _STRING, _STRING)

    def ResolutionScope(self) -> coded_index:
        return self._coded(0, coded_index[ResolutionScope])

    def TypeName(self) -> str:
        return self._string(1)

    def TypeNamespace(self) -> str:
        return self._string(2)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class TypeDef(Row):
    """A row of the TypeDef table."""

    __slots__ = ()
    _table = TableNumber.TypeDef
    _schema = (4, _STRING, _STRING, coded_index[TypeDefOrRef],
               _TableIndex(TableNumber.Field), _TableIndex(TableNumber.MethodDef))

    def Flags(self) -> TypeAttributes:
        return TypeAttributes(self.get_value(0))

    def TypeName(self) -> str:
        return self._string(1)

    def TypeNamespace(self) -> str:
        return self._string(2)

    def Extends(self) -> coded_index:
        return self._coded(3, coded_index[TypeDefOrRef])

    def FieldList(self) -> RowRange[Field]:
        return self._list(4, TableNumber.Field)

    def MethodList(self) -> RowRange[MethodDef]:
        return self._list(5, TableNumber.MethodDef)

    def InterfaceImpl(self) -> RowRange[InterfaceImpl]:
        return self._database.equal_range(TableNumber.InterfaceImpl, 0, self._index + 1)

    def MethodImplList(self) -> RowRange[MethodImpl]:
        return self._database.equal_range(TableNumber.MethodImpl, 0, self._index + 1)

    def PropertyList(self) -> RowRange[Property]:
        mapping = self._database.find_row(TableNumber.PropertyMap, 0, self._index + 1)
        return mapping.PropertyList() if mapping else RowRange(
            self._database, TableNumber.Property, 0, 0)

    def EventList(self) -> RowRange[Event]:
        mapping = self._database.find_row(TableNumber.EventMap, 0, self._index + 1)
        return mapping.EventList() if mapping else RowRange(
            self._database, TableNumber.Event, 0, 0)

    def GenericParam(self) -> RowRange[GenericParam]:
        return self._referrers(coded_index[TypeOrMethodDef], TableNumber.GenericParam, 2)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()

    def EnclosingType(self) -> TypeDef:
        nested = self._database.find_row(TableNumber.NestedClass, 0, self._index + 1)
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
    _table = TableNumber.Field
    _schema = (2, _STRING, _BLOB)

    def Flags(self) -> FieldAttributes:
        return FieldAttributes(self.get_value(0))

    def Name(self) -> str:
        return self._string(1)

    def Signature(self) -> FieldSig:
        return FieldSig(self._blob(2))

    def Parent(self) -> TypeDef:
        return self._database.parent_row(TableNumber.TypeDef, 4, self._index)

    def Constant(self) -> Constant:
        return self._constant()

    def FieldMarshal(self) -> FieldMarshal:
        return self._referrer(coded_index[HasFieldMarshal], TableNumber.FieldMarshal, 0)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class MethodDef(Row):
    """A row of the MethodDef table."""

    __slots__ = ()
    _table = TableNumber.MethodDef
    _schema = (4, 2, 2, _STRING, _BLOB, _TableIndex(TableNumber.Param))

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
        return self._list(5, TableNumber.Param)

    def Parent(self) -> TypeDef:
        return self._database.parent_row(TableNumber.TypeDef, 5, self._index)

    def GenericParam(self) -> RowRange[GenericParam]:
        return self._referrers(coded_index[TypeOrMethodDef], TableNumber.GenericParam, 2)

    def SpecialName(self) -> bool:
        """MethodDef.Flags().SpecialName(), which the C++ side also shortens."""
        return self.Flags().SpecialName()

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class Param(Row):
    """A row of the Param table."""

    __slots__ = ()
    _table = TableNumber.Param
    _schema = (2, 2, _STRING)

    def Flags(self) -> ParamAttributes:
        return ParamAttributes(self.get_value(0))

    def Sequence(self) -> int:
        return self.get_value(1)

    def Name(self) -> str:
        return self._string(2)

    def Parent(self) -> MethodDef:
        return self._database.parent_row(TableNumber.MethodDef, 5, self._index)

    def Constant(self) -> Constant:
        return self._constant()

    def FieldMarshal(self) -> FieldMarshal:
        return self._referrer(coded_index[HasFieldMarshal], TableNumber.FieldMarshal, 0)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class InterfaceImpl(Row):
    """A row of the InterfaceImpl table."""

    __slots__ = ()
    _table = TableNumber.InterfaceImpl
    _schema = (_TableIndex(TableNumber.TypeDef), coded_index[TypeDefOrRef])

    def Class(self) -> TypeDef:
        return self._row(0, TableNumber.TypeDef)

    def Interface(self) -> coded_index:
        return self._coded(1, coded_index[TypeDefOrRef])

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class MemberRef(Row):
    """A row of the MemberRef table."""

    __slots__ = ()
    _table = TableNumber.MemberRef
    _schema = (coded_index[MemberRefParent], _STRING, _BLOB)

    def Class(self) -> coded_index:
        return self._coded(0, coded_index[MemberRefParent])

    def Name(self) -> str:
        return self._string(1)

    def MethodSignature(self) -> MethodDefSig:
        return MethodDefSig(self._blob(2))

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class Constant(Row):
    """A row of the Constant table."""

    __slots__ = ()
    _table = TableNumber.Constant
    _schema = (2, coded_index[HasConstant], _BLOB)

    def Type(self) -> ConstantType:
        return ConstantType(self.get_value(0))

    def Parent(self) -> coded_index:
        return self._coded(1, coded_index[HasConstant])

    def Value(self):
        return _constant_value(ConstantType(self.get_value(0)), self._blob(2))

    def ValueBoolean(self) -> bool:
        return self._blob(2).read("<?")

    def ValueInt32(self) -> int:
        return self._blob(2).read("<i")

    def ValueUInt32(self) -> int:
        return self._blob(2).read("<I")

    def ValueString(self) -> str:
        blob = self._blob(2)
        return blob.data[blob.position:blob.end].decode("utf-16-le")


class CustomAttribute(Row):
    """A row of the CustomAttribute table."""

    __slots__ = ()
    _table = TableNumber.CustomAttribute
    _schema = (coded_index[HasCustomAttribute],
               coded_index[CustomAttributeType], _BLOB)

    def Parent(self) -> coded_index:
        return self._coded(0, coded_index[HasCustomAttribute])

    def Type(self) -> coded_index:
        return self._coded(1, coded_index[CustomAttributeType])

    def Value(self) -> CustomAttributeSig:
        constructor = self.Type()
        if constructor.type() == TableNumber.MemberRef:
            signature = MethodDefSig(constructor.get_row()._blob(2))
        else:
            signature = constructor.get_row().Signature()
        return CustomAttributeSig(self._database, self._blob(2), signature)

    def TypeNamespaceAndName(self) -> Tuple[str, str]:
        """The namespace and name of the attribute this row applies.

        Cached by the constructor it names. A file applies tens of thousands of
        attributes and has a few hundred kinds of them, so this is the one
        column where memoising pays for itself many times over: it takes the
        cache of Windows.Win32.winmd from 350 ms to 80 ms.
        """
        constructor = self.get_value(1)
        names = self._database._attribute_names
        found = names.get(constructor)
        if found is None:
            index = coded_index[CustomAttributeType](self._database, constructor)
            row = index.get_row()
            if index.type() == TableNumber.MemberRef:
                found = get_type_namespace_and_name(row.Class())
            else:
                parent = row.Parent()
                found = (parent.TypeNamespace(), parent.TypeName())
            names[constructor] = found
        return found


class FieldMarshal(Row):
    """A row of the FieldMarshal table."""

    __slots__ = ()
    _table = TableNumber.FieldMarshal
    _schema = (coded_index[HasFieldMarshal], _BLOB)

    def Parent(self) -> coded_index:
        return self._coded(0, coded_index[HasFieldMarshal])


class DeclSecurity(Row):
    """A row of the DeclSecurity table."""

    __slots__ = ()
    _table = TableNumber.DeclSecurity
    _schema = (2, coded_index[HasDeclSecurity], _BLOB)


class ClassLayout(Row):
    """A row of the ClassLayout table."""

    __slots__ = ()
    _table = TableNumber.ClassLayout
    _schema = (2, 4, _TableIndex(TableNumber.TypeDef))

    def PackingSize(self) -> int:
        return self.get_value(0)

    def ClassSize(self) -> int:
        return self.get_value(1)

    def Parent(self) -> TypeDef:
        return self._row(2, TableNumber.TypeDef)


class FieldLayout(Row):
    """A row of the FieldLayout table."""

    __slots__ = ()
    _table = TableNumber.FieldLayout
    _schema = (4, _TableIndex(TableNumber.Field))


class StandAloneSig(Row):
    """A row of the StandAloneSig table."""

    __slots__ = ()
    _table = TableNumber.StandAloneSig
    _schema = (_BLOB,)

    def Signature(self) -> byte_view:
        return self._blob(0)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class EventMap(Row):
    """A row of the EventMap table."""

    __slots__ = ()
    _table = TableNumber.EventMap
    _schema = (_TableIndex(TableNumber.TypeDef), _TableIndex(TableNumber.Event))

    def Parent(self) -> TypeDef:
        return self._row(0, TableNumber.TypeDef)

    def EventList(self) -> RowRange[Event]:
        return self._list(1, TableNumber.Event)


class Event(Row):
    """A row of the Event table."""

    __slots__ = ()
    _table = TableNumber.Event
    _schema = (2, _STRING, coded_index[TypeDefOrRef])

    def EventFlags(self) -> EventAttributes:
        return EventAttributes(self.get_value(0))

    def Flags(self) -> EventAttributes:
        """EventFlags(), under the name the other tables use."""
        return EventAttributes(self.get_value(0))

    def Name(self) -> str:
        return self._string(1)

    def EventType(self) -> coded_index:
        return self._coded(2, coded_index[TypeDefOrRef])

    def Type(self) -> coded_index:
        """EventType(), under the name the other tables use."""
        return self._coded(2, coded_index[TypeDefOrRef])

    def Parent(self) -> TypeDef:
        mapping = self._database.parent_row(TableNumber.EventMap, 1, self._index)
        return mapping.Parent()

    def MethodSemantic(self) -> RowRange[MethodSemantics]:
        return self._referrers(coded_index[HasSemantics], TableNumber.MethodSemantics, 2)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class PropertyMap(Row):
    """A row of the PropertyMap table."""

    __slots__ = ()
    _table = TableNumber.PropertyMap
    _schema = (_TableIndex(TableNumber.TypeDef), _TableIndex(TableNumber.Property))

    def Parent(self) -> TypeDef:
        return self._row(0, TableNumber.TypeDef)

    def PropertyList(self) -> RowRange[Property]:
        return self._list(1, TableNumber.Property)


class Property(Row):
    """A row of the Property table."""

    __slots__ = ()
    _table = TableNumber.Property
    _schema = (2, _STRING, _BLOB)

    def Flags(self) -> PropertyAttributes:
        return PropertyAttributes(self.get_value(0))

    def Name(self) -> str:
        return self._string(1)

    def Signature(self) -> PropertySig:
        return PropertySig(self._blob(2))

    def Type(self) -> PropertySig:
        """Signature(), which is what a property's type is."""
        return PropertySig(self._blob(2))

    def Parent(self) -> TypeDef:
        mapping = self._database.parent_row(TableNumber.PropertyMap, 1, self._index)
        return mapping.Parent()

    def Constant(self) -> Constant:
        return self._constant()

    def MethodSemantic(self) -> RowRange[MethodSemantics]:
        return self._referrers(coded_index[HasSemantics], TableNumber.MethodSemantics, 2)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class MethodSemantics(Row):
    """A row of the MethodSemantics table."""

    __slots__ = ()
    _table = TableNumber.MethodSemantics
    _schema = (2, _TableIndex(TableNumber.MethodDef), coded_index[HasSemantics])

    def Semantic(self) -> MethodSemanticsAttributes:
        return MethodSemanticsAttributes(self.get_value(0))

    def Flags(self) -> MethodSemanticsAttributes:
        """Semantic(), under the name the other tables use."""
        return MethodSemanticsAttributes(self.get_value(0))

    def Method(self) -> MethodDef:
        return self._row(1, TableNumber.MethodDef)

    def Association(self) -> coded_index:
        return self._coded(2, coded_index[HasSemantics])


class MethodImpl(Row):
    """A row of the MethodImpl table."""

    __slots__ = ()
    _table = TableNumber.MethodImpl
    _schema = (_TableIndex(TableNumber.TypeDef), coded_index[MethodDefOrRef],
               coded_index[MethodDefOrRef])

    def Class(self) -> TypeDef:
        return self._row(0, TableNumber.TypeDef)


class ModuleRef(Row):
    """A row of the ModuleRef table."""

    __slots__ = ()
    _table = TableNumber.ModuleRef
    _schema = (_STRING,)

    def Name(self) -> str:
        return self._string(0)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class TypeSpec(Row):
    """A row of the TypeSpec table."""

    __slots__ = ()
    _table = TableNumber.TypeSpec
    _schema = (_BLOB,)

    def Signature(self) -> TypeSpecSig:
        return TypeSpecSig(self._blob(0))

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class ImplMap(Row):
    """A row of the ImplMap table.

    The C++ reader has no accessors for this table; these are ours.
    """

    __slots__ = ()
    _table = TableNumber.ImplMap
    _schema = (2, coded_index[MemberForwarded], _STRING,
               _TableIndex(TableNumber.ModuleRef))

    def MappingFlags(self) -> PInvokeAttributes:
        return PInvokeAttributes(self.get_value(0))

    def Flags(self) -> PInvokeAttributes:
        """MappingFlags(), under the name the other tables use."""
        return PInvokeAttributes(self.get_value(0))

    def MemberForwarded(self) -> coded_index:
        return self._coded(1, coded_index[MemberForwarded])

    def ImportName(self) -> str:
        return self._string(2)

    def Name(self) -> str:
        """ImportName(), under the name the other tables use."""
        return self._string(2)

    def ImportScope(self) -> ModuleRef:
        return self._row(3, TableNumber.ModuleRef)


class FieldRVA(Row):
    """A row of the FieldRVA table."""

    __slots__ = ()
    _table = TableNumber.FieldRVA
    _schema = (4, _TableIndex(TableNumber.Field))


class Assembly(Row):
    """A row of the Assembly table."""

    __slots__ = ()
    _table = TableNumber.Assembly
    _schema = (4, 8, 4, _BLOB, _STRING, _STRING)

    def HashAlgId(self) -> int:
        return self.get_value(0)

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

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class AssemblyProcessor(Row):
    """A row of the AssemblyProcessor table."""

    __slots__ = ()
    _table = TableNumber.AssemblyProcessor
    _schema = (4,)


class AssemblyOS(Row):
    """A row of the AssemblyOS table."""

    __slots__ = ()
    _table = TableNumber.AssemblyOS
    _schema = (4, 4, 4)


class AssemblyRef(Row):
    """A row of the AssemblyRef table."""

    __slots__ = ()
    _table = TableNumber.AssemblyRef
    _schema = (8, 4, _BLOB, _STRING, _STRING, _BLOB)

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

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class AssemblyRefProcessor(Row):
    """A row of the AssemblyRefProcessor table."""

    __slots__ = ()
    _table = TableNumber.AssemblyRefProcessor
    _schema = (4, _TableIndex(TableNumber.AssemblyRef))


class AssemblyRefOS(Row):
    """A row of the AssemblyRefOS table."""

    __slots__ = ()
    _table = TableNumber.AssemblyRefOS
    _schema = (4, 4, 4, _TableIndex(TableNumber.AssemblyRef))


class File(Row):
    """A row of the File table."""

    __slots__ = ()
    _table = TableNumber.File
    _schema = (4, _STRING, _BLOB)

    def Name(self) -> str:
        return self._string(1)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class ExportedType(Row):
    """A row of the ExportedType table."""

    __slots__ = ()
    _table = TableNumber.ExportedType
    _schema = (4, 4, _STRING, _STRING, coded_index[Implementation])

    def Flags(self) -> _Flags:
        return _Flags(self.get_value(0))

    def Name(self) -> str:
        return self._string(3)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class ManifestResource(Row):
    """A row of the ManifestResource table."""

    __slots__ = ()
    _table = TableNumber.ManifestResource
    _schema = (4, 4, _STRING, coded_index[Implementation])

    def Flags(self) -> _Flags:
        return _Flags(self.get_value(1))

    def Name(self) -> str:
        return self._string(2)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class NestedClass(Row):
    """A row of the NestedClass table."""

    __slots__ = ()
    _table = TableNumber.NestedClass
    _schema = (_TableIndex(TableNumber.TypeDef), _TableIndex(TableNumber.TypeDef))

    def NestedType(self) -> TypeDef:
        return self._row(0, TableNumber.TypeDef)

    def EnclosingType(self) -> TypeDef:
        return self._row(1, TableNumber.TypeDef)


class GenericParam(Row):
    """A row of the GenericParam table."""

    __slots__ = ()
    _table = TableNumber.GenericParam
    _schema = (2, 2, coded_index[TypeOrMethodDef], _STRING)

    def Number(self) -> int:
        return self.get_value(0)

    def Flags(self) -> GenericParamAttributes:
        return GenericParamAttributes(self.get_value(1))

    def Owner(self) -> coded_index:
        return self._coded(2, coded_index[TypeOrMethodDef])

    def Name(self) -> str:
        return self._string(3)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class MethodSpec(Row):
    """A row of the MethodSpec table."""

    __slots__ = ()
    _table = TableNumber.MethodSpec
    _schema = (coded_index[MethodDefOrRef], _BLOB)

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


class GenericParamConstraint(Row):
    """A row of the GenericParamConstraint table."""

    __slots__ = ()
    _table = TableNumber.GenericParamConstraint
    _schema = (_TableIndex(TableNumber.GenericParam), coded_index[TypeDefOrRef])

    def CustomAttribute(self) -> RowRange[CustomAttribute]:
        return self._attributes()


def make_row(database: database, table: TableNumber, index: int) -> Row:
    """A row of any table, for when the table is only known at run time."""
    return _ROW_CLASSES[table](database, index)


def _constant_value(kind: ConstantType, blob: byte_view):
    if kind == ConstantType.String:
        return blob.data[blob.position:blob.end].decode("utf-16-le")
    if kind == ConstantType.Class:
        return None
    formats = {
        ConstantType.Boolean: "<?", ConstantType.Char: "<H",
        ConstantType.Int8: "<b", ConstantType.UInt8: "<B",
        ConstantType.Int16: "<h", ConstantType.UInt16: "<H",
        ConstantType.Int32: "<i", ConstantType.UInt32: "<I",
        ConstantType.Int64: "<q", ConstantType.UInt64: "<Q",
        ConstantType.Float32: "<f", ConstantType.Float64: "<d",
    }
    value = blob.read(formats[kind])
    return chr(value) if kind == ConstantType.Char else value


# --- the database ---------------------------------------------------------
class Table(Sequence[RowT]):
    """One table, as a sequence of rows."""

    __slots__ = ("_database", "_table")

    def __init__(self, database: database, table: TableNumber):
        self._database = database
        self._table = table

    def __len__(self) -> int:
        return self._database.rows(self._table)

    def __getitem__(self, index) -> RowT:
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return make_row(self._database, self._table, index)

    def size(self) -> int:
        return len(self)

    def row_size(self) -> int:
        """How many bytes one row takes, which depends on the whole file."""
        return self._database._row_size[self._table]

    def column_size(self, column: int) -> int:
        return self._database._columns[self._table][column][1]

    def get_value(self, row: int, column: int) -> int:
        return self._database.row(self._table, row)[column]

    def get_database(self) -> database:
        return self._database

    def __repr__(self):
        return f"<{self._table.name}_table {len(self)}>"


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

    def __init__(self, path, cache: cache = None):
        """A path to map, or the bytes of a file already in hand."""
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
        self._strings_range = streams["#Strings"]
        self._strings = bytes(view[streams["#Strings"][0]:sum(streams["#Strings"])])
        self._blobs = bytes(view[streams["#Blob"][0]:sum(streams["#Blob"])]) \
            if "#Blob" in streams else b""
        self._guids = bytes(view[streams["#GUID"][0]:sum(streams["#GUID"])]) \
            if "#GUID" in streams else b""

        name = "#~" if "#~" in streams else "#-"
        self._tables = view[streams[name][0]:sum(streams[name])]
        self._layout(self._tables)
        self._sorted_columns: Dict[Tuple[int, int], Any] = {}
        self._attribute_names: Dict[int, Tuple[str, str]] = {}
        self._type_names: Dict[Tuple[str, int], Tuple[str, str]] = {}

        for table in TableNumber:
            setattr(self, table.name, Table(self, table))

    # --- PE and the metadata root
    def _find_metadata(self, view: memoryview) -> int:
        if view[:2] != b"MZ":
            raise ValueError(f"{self._path} is not a PE image")
        pe = struct.unpack_from("<I", view, 0x3C)[0]
        if view[pe:pe + 4] != b"PE\0\0":
            raise ValueError(f"{self._path} has no PE signature")

        coff = pe + 4
        sections = struct.unpack_from("<H", view, coff + 2)[0]
        optional_size = struct.unpack_from("<H", view, coff + 16)[0]
        optional = coff + 20
        magic = struct.unpack_from("<H", view, optional)[0]
        directories = optional + (96 if magic == 0x10B else 112)   # PE32 / PE32+
        cli_rva = struct.unpack_from("<I", view, directories + 14 * 8)[0]
        if not cli_rva:
            raise ValueError(f"{self._path} carries no CLI header")

        self._sections = []
        first = optional + optional_size
        for index in range(sections):
            header = first + index * 40
            virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from(
                "<IIII", view, header + 8)
            self._sections.append((virtual_address, max(virtual_size, raw_size), raw_pointer))

        cli = self._offset(cli_rva)
        return self._offset(struct.unpack_from("<I", view, cli + 8)[0])

    def _offset(self, rva: int) -> int:
        for virtual_address, size, raw in self._sections:
            if virtual_address <= rva < virtual_address + size:
                return rva - virtual_address + raw
        raise ValueError(f"RVA {rva:#x} is in no section")

    def _read_streams(self, view: memoryview, root: int) -> Dict[str, Tuple[int, int]]:
        if view[root:root + 4] != b"BSJB":
            raise ValueError(f"{self._path} has no metadata root")
        version_length = struct.unpack_from("<I", view, root + 12)[0]
        position = root + 16 + version_length + 2                  # + flags
        count = struct.unpack_from("<H", view, position)[0]
        position += 2

        streams = {}
        for _ in range(count):
            offset, size = struct.unpack_from("<II", view, position)
            position += 8
            end = bytes(view[position:position + 32]).index(b"\0")
            streams[bytes(view[position:position + end]).decode("ascii")] = (
                root + offset, size)
            position += end + 1
            position += -position % 4                              # padded to 4
        return streams

    # --- the table layout
    def _layout(self, tables: memoryview) -> None:
        heap_sizes = tables[6]
        heaps = {"string": 4 if heap_sizes & 1 else 2,
                 "guid": 4 if heap_sizes & 2 else 2,
                 "blob": 4 if heap_sizes & 4 else 2}

        # One row count per bit of the valid mask, in table number order. The
        # C++ throws on a number it has no table for and so does this; every
        # count after an unknown one would be read against the wrong table.
        valid = struct.unpack_from("<Q", tables, 8)[0]
        position = 24
        self.row_counts: Dict[TableNumber, int] = {}
        for number in range(64):
            if valid >> number & 1:
                try:
                    table = TableNumber(number)
                except ValueError:
                    raise ValueError(f"unknown metadata table 0x{number:02x}") from None
                self.row_counts[table] = struct.unpack_from("<I", tables, position)[0]
                position += 4

        def index_size(table: TableNumber) -> int:
            return 2 if self.row_counts.get(table, 0) < (1 << 16) else 4

        def coded_size(kind: type) -> int:
            limit = 1 << (16 - kind._bits)
            return 2 if all(self.row_counts.get(table, 0) < limit
                            for table in kind._sizing_tables if table is not None) else 4

        self._columns: Dict[TableNumber, List[Tuple[int, int]]] = {}
        self._row_size: Dict[TableNumber, int] = {}
        self._format: Dict[TableNumber, str] = {}
        for table in TableNumber:
            row_class = _ROW_CLASSES[table]
            offset = 0
            columns = []
            fields = []
            for column in row_class._schema:
                if isinstance(column, int):
                    size = column
                elif isinstance(column, _HeapIndex):
                    size = heaps[column.heap]
                elif isinstance(column, _TableIndex):
                    size = index_size(column.table)
                else:
                    size = coded_size(column)
                columns.append((offset, size))
                fields.append({1: "B", 2: "H", 4: "I", 8: "Q"}[size])
                offset += size
            self._columns[table] = columns
            self._row_size[table] = offset
            self._format[table] = "<" + "".join(fields)

        # The rows follow one another in table number order, which is the
        # order the enum declares them in.
        self._start: Dict[TableNumber, int] = {}
        for table in TableNumber:
            self._start[table] = position
            position += self._row_size[table] * self.row_counts.get(table, 0)

    # --- reading
    def rows(self, table: TableNumber) -> int:
        return self.row_counts.get(table, 0)

    def row(self, table: TableNumber, index: int) -> Tuple[int, ...]:
        if not 0 <= index < self.rows(table):
            raise IndexError(f"{TableNumber(table).name}[{index}]")
        return struct.unpack_from(
            self._format[table], self._tables,
            self._start[table] + index * self._row_size[table])

    def table(self, table: TableNumber) -> List[Tuple[int, ...]]:
        """Every row of a table at once, which is much faster than one by one."""
        count = self.rows(table)
        if not count:
            return []
        start = self._start[table]
        size = self._row_size[table]
        return list(struct.iter_unpack(
            self._format[table], self._tables[start:start + size * count]))

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
        return heap[index:heap.index(b"\0", index)].decode("utf-8")

    def blob(self, index: int) -> byte_view:
        size, position = uncompress_unsigned(self._blobs, index)
        return byte_view(self._blobs, position, size, self)

    def guid(self, index: int) -> bytes:
        if not index:
            return b""
        return self._guids[(index - 1) * 16:index * 16]

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
    def _column(self, table: TableNumber, column: int) -> Tuple[List[int], Optional[Dict[int, List[int]]]]:
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

    def equal_range(self, table: TableNumber, column: int, value: int) -> Sequence[Row]:
        """The rows whose column equals `value`."""
        values, grouped = self._column(table, column)
        if grouped is not None:
            return RowList(self, table, grouped.get(value, []))
        first = bisect.bisect_left(values, value)
        last = bisect.bisect_right(values, value, first)
        return RowRange(self, table, first, last)

    def find_row(self, table: TableNumber, column: int, value: int) -> Optional[Row]:
        values, grouped = self._column(table, column)
        if grouped is not None:
            indexes = grouped.get(value)
            return make_row(self, table, indexes[0]) if indexes else None
        position = bisect.bisect_left(values, value)
        if position < len(values) and values[position] == value:
            return make_row(self, table, position)
        return None

    def parent_row(self, table: TableNumber, column: int, index: int) -> Row:
        """The row of `table` whose list column covers `index`.

        A list column is monotonic by construction, so this one is a search.
        """
        values, _ = self._column(table, column)
        position = bisect.bisect_right(values, index + 1) - 1
        if position < 0:
            raise RuntimeError("no parent row")
        return make_row(self, table, position)

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
        if getattr(self, "_tables", None) is not None:
            self._tables.release()
            self._tables = None
        if isinstance(getattr(self, "_data", None), mmap.mmap):
            self._data.close()
            self._data = None
        if getattr(self, "_file", None) is not None:
            self._file.close()
            self._file = None

    def __del__(self):
        try:
            self.close()
        except Exception:                     # nothing useful to do at teardown
            pass

    def __enter__(self) -> database:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self):
        return f"<database {self._path}>"


# --- the cache ------------------------------------------------------------
class namespace_members:
    __slots__ = ("types", "interfaces", "classes", "enums", "structs",
                 "delegates", "attributes", "contracts")

    def __init__(self):
        self.types: Dict[str, Row] = {}
        self.interfaces: List[Row] = []
        self.classes: List[Row] = []
        self.enums: List[Row] = []
        self.structs: List[Row] = []
        self.delegates: List[Row] = []
        self.attributes: List[Row] = []
        self.contracts: List[Row] = []

    def __repr__(self):
        return f"<namespace_members types={len(self.types)}>"


class filter:
    """Include and exclude prefixes, longest first."""

    def __init__(self, includes: Sequence[str] = (), excludes: Sequence[str] = ()):
        self._rules = [(prefix, True) for prefix in includes]
        self._rules += [(prefix, False) for prefix in excludes]
        self._rules.sort(key=lambda rule: (len(rule[0]), not rule[1]), reverse=True)

    def includes(self, value) -> bool:
        if isinstance(value, Row):
            return self._match(value.TypeNamespace(), value.TypeName())
        if isinstance(value, namespace_members):
            return any(self._match(row.TypeNamespace(), row.TypeName())
                       for row in value.types.values())
        if isinstance(value, str):
            namespace, _, name = value.rpartition(".")
            return self._match(namespace, name)
        return any(self.includes(row) for row in value)

    def _match(self, namespace: str, name: str) -> bool:
        if not self._rules:
            return True
        full = f"{namespace}.{name}"
        for prefix, included in self._rules:
            if full == prefix or full.startswith(prefix + "."):
                return included
        return False

    def empty(self) -> bool:
        return not self._rules

    def __call__(self, type: Row) -> bool:
        return self.includes(type)


class cache:
    """A set of .winmd files, with their types indexed by namespace and name."""

    def __init__(self, files=(), filter=None):
        if isinstance(files, str):
            files = [files]
        self._databases: List[database] = []
        self._namespaces: Dict[str, namespace_members] = {}
        self._nested: Dict[Row, List[Row]] = {}
        for file in files:
            self.add_database(file, filter)

    def add_database(self, file: str, filter=None) -> None:
        db = database(file, self)
        self._databases.append(db)

        heap = db._strings
        namespaces: Dict[int, str] = {}
        for index, row in enumerate(db.table(TableNumber.TypeDef)):
            if not row[0]:                                   # the <Module> row
                continue
            type = make_row(db, TableNumber.TypeDef, index)
            if is_nested(type) or (filter is not None and not filter(type)):
                continue
            at = row[2]
            namespace = namespaces.get(at)
            if namespace is None:
                namespace = namespaces[at] = heap[at:heap.index(b"\0", at)].decode("utf-8")
            at = row[1]
            name = heap[at:heap.index(b"\0", at)].decode("utf-8")
            members = self._namespaces.get(namespace)
            if members is None:
                members = self._namespaces[namespace] = namespace_members()
            if name not in members.types:
                members.types[name] = type
                self._add_to_members(type, members)

        for row in db.NestedClass:
            self._nested.setdefault(row.EnclosingType(), []).append(row.NestedType())

    def _add_to_members(self, type: TypeDef, members: namespace_members) -> None:
        kind = get_category(type)
        if kind == category.interface_type:
            members.interfaces.append(type)
        elif kind == category.class_type:
            if extends_type(type, "System", "Attribute"):
                members.attributes.append(type)
            else:
                members.classes.append(type)
        elif kind == category.enum_type:
            members.enums.append(type)
        elif kind == category.struct_type:
            if get_attribute(type, "Windows.Foundation.Metadata", "ApiContractAttribute"):
                members.contracts.append(type)
            else:
                members.structs.append(type)
        elif kind == category.delegate_type:
            members.delegates.append(type)

    def find(self, namespace: str, name: str = None) -> Optional[TypeDef]:
        if name is None:
            namespace, _, name = namespace.rpartition(".")
            if not namespace:
                raise ValueError("a type name needs a namespace")
        members = self._namespaces.get(namespace)
        return members.types.get(name) if members else None

    def find_required(self, namespace: str, name: str = None) -> TypeDef:
        type = self.find(namespace, name)
        if not type:
            raise ValueError(f"the type {namespace}.{name} could not be found")
        return type

    def namespaces(self) -> Dict[str, namespace_members]:
        return self._namespaces

    def databases(self) -> List[database]:
        return self._databases

    def nested_types(self, enclosing: TypeDef) -> List[TypeDef]:
        return self._nested.get(enclosing, [])

    def remove_type(self, namespace: str, name: str) -> None:
        members = self._namespaces.get(namespace)
        if not members:
            return
        for collection in (members.interfaces, members.classes, members.enums,
                           members.structs, members.delegates):
            for index, type in enumerate(collection):
                if type.TypeName() == name:
                    del collection[index]
                    break

    def close(self) -> None:
        for database in self._databases:
            database.close()

    def __repr__(self):
        return (f"<cache databases={len(self._databases)} "
                f"namespaces={len(self._namespaces)}>")


# --- the free functions ---------------------------------------------------
def get_type_namespace_and_name(index: coded_index) -> Tuple[str, str]:
    """(namespace, name) of what a TypeDefOrRef points at.

    A TypeSpec is a signature rather than a name, and raises here as it does in
    C++; resolve it through Signature().GenericTypeInst().GenericType() if that
    is what you meant.
    """
    if index.type() == TableNumber.TypeSpec:
        raise ValueError("a TypeSpec has no namespace and name")
    # Memoised for the same reason attribute names are: a base class or an
    # interface is named over and over. System.ValueType alone accounts for
    # thousands of the resolutions the cache does.
    names = index._database._type_names
    key = (index._kind, index._value)
    found = names.get(key)
    if found is None:
        row = index.get_row()
        found = names[key] = (row.TypeNamespace(), row.TypeName())
    return found


def get_base_class_namespace_and_name(type: TypeDef) -> Tuple[str, str]:
    return get_type_namespace_and_name(type.Extends())


def extends_type(type: TypeDef, namespace: str, name: str) -> bool:
    return get_base_class_namespace_and_name(type) == (namespace, name)


def is_nested(type: TypeDef) -> bool:
    if type._table == TableNumber.TypeDef:
        return type.Flags().Visibility() >= TypeVisibility.NestedPublic
    return type.ResolutionScope().type() == TableNumber.TypeRef     # a TypeRef


def get_category(type: TypeDef) -> category:
    if (type.Flags().Semantics() == TypeSemantics.Interface
            or get_attribute(type, "System.Runtime.InteropServices", "GuidAttribute")):
        return category.interface_type
    namespace, name = get_base_class_namespace_and_name(type)
    if (namespace, name) == ("System", "Enum"):
        return category.enum_type
    if (namespace, name) == ("System", "ValueType"):
        return category.struct_type
    if (namespace, name) == ("System", "MulticastDelegate"):
        return category.delegate_type
    return category.class_type


def get_attribute(row: Row, namespace: str, name: str) -> Optional[CustomAttribute]:
    if isinstance(row, coded_index):
        row = row.get_row()
    for attribute in row.CustomAttribute():
        if attribute.TypeNamespaceAndName() == (namespace, name):
            return attribute
    return None


def find(type) -> Optional[TypeDef]:
    """The definition a TypeRef or a TypeDefOrRef column points at."""
    if isinstance(type, coded_index):
        if type.type() == TableNumber.TypeDef:
            return type.get_row()
        if type.type() == TableNumber.TypeSpec:
            raise ValueError("a TypeSpec cannot be resolved to a TypeDef")
        type = type.get_row()
    if type.ResolutionScope().type() == TableNumber.TypeRef:          # a nested TypeRef
        enclosing = find(type.ResolutionScope().get_row())
        if not enclosing:
            return None
        for nested in enclosing.get_cache().nested_types(enclosing):
            if nested.TypeName() == type.TypeName():
                return nested
        return None
    return type.get_cache().find(type.TypeNamespace(), type.TypeName())


def find_required(type) -> TypeDef:
    definition = find(type)
    if not definition:
        namespace, name = get_type_namespace_and_name(type) \
            if isinstance(type, coded_index) else (type.TypeNamespace(), type.TypeName())
        raise ValueError(f"the type {namespace}.{name} could not be found")
    return definition


def is_const(param: ParamSig) -> bool:
    for mod in param.CustomMod():
        namespace, name = get_type_namespace_and_name(mod.Type())
        if name == "IsConst":
            return True
    return False


__all__ = [
    # the 38 tables, and a row of each
    "TableNumber", "Row", "make_row", "Module", "TypeRef", "TypeDef", "Field",
    "MethodDef", "Param", "InterfaceImpl", "MemberRef", "Constant",
    "CustomAttribute", "FieldMarshal", "DeclSecurity", "ClassLayout",
    "FieldLayout", "StandAloneSig", "EventMap", "Event", "PropertyMap",
    "Property", "MethodSemantics", "MethodImpl", "ModuleRef", "TypeSpec",
    "ImplMap", "FieldRVA", "Assembly", "AssemblyProcessor", "AssemblyOS",
    "AssemblyRef", "AssemblyRefProcessor", "AssemblyRefOS", "File",
    "ExportedType", "ManifestResource", "NestedClass", "GenericParam",
    "MethodSpec", "GenericParamConstraint",
    # what holds rows
    "Table", "RowRange", "RowList", "AssemblyVersion",
    # the enums of the metadata
    "ElementType", "CallingConvention", "ConstantType", "category",
    "TypeVisibility", "TypeLayout", "TypeSemantics", "StringFormat",
    "MemberAccess", "VtableLayout", "CodeType", "Managed",
    "GenericParamVariance",
    # the flags columns
    "TypeAttributes", "MethodAttributes", "FieldAttributes",
    "ParamAttributes", "PropertyAttributes", "EventAttributes",
    "MethodImplAttributes", "MethodSemanticsAttributes",
    "GenericParamAttributes", "AssemblyAttributes", "PInvokeAttributes",
    # blobs, and the signatures in them
    "byte_view", "TypeSig", "ParamSig", "RetTypeSig", "MethodDefSig", "FieldSig",
    "PropertySig", "TypeSpecSig", "CustomModSig", "GenericTypeInstSig",
    "GenericTypeIndex", "GenericMethodTypeIndex",
    # custom attributes, and the enum definitions they name
    "CustomAttributeSig", "FixedArgSig", "NamedArgSig", "ElemSig",
    "SystemType", "EnumValue", "EnumDefinition",
    # coded indexes: one class per kind, reached as coded_index[TypeDefOrRef]
    "coded_index", "coded_index_TypeDefOrRef", "coded_index_HasConstant",
    "coded_index_HasCustomAttribute", "coded_index_HasFieldMarshal",
    "coded_index_HasDeclSecurity", "coded_index_MemberRefParent",
    "coded_index_HasSemantics", "coded_index_MethodDefOrRef",
    "coded_index_MemberForwarded", "coded_index_Implementation",
    "coded_index_CustomAttributeType", "coded_index_ResolutionScope",
    "coded_index_TypeOrMethodDef", "TypeDefOrRef", "HasConstant",
    "HasCustomAttribute", "HasFieldMarshal", "HasDeclSecurity",
    "MemberRefParent", "HasSemantics", "MethodDefOrRef", "MemberForwarded",
    "Implementation", "CustomAttributeType", "ResolutionScope",
    "TypeOrMethodDef",
    # a file, and a set of them
    "database", "cache", "filter", "namespace_members",
    # the free functions
    "get_type_namespace_and_name", "get_base_class_namespace_and_name",
    "extends_type", "is_nested", "get_category", "get_attribute", "find",
    "find_required", "is_const", "enum_mask", "uncompress_unsigned",
]
