"""A .winmd reader in nothing but the standard library.

The same ground as the C++ winmd::reader the bindings wrap: the PE and CLI
headers, the metadata root and its heaps, the 38 tables with named accessors,
the 13 coded indexes, the signature blobs, the custom attribute decoder, the
flag structs and a cache that indexes types by namespace.

    from purewinmd import cache, get_category

    db = cache(["Windows.Win32.winmd"])
    type = db.find_required("Windows.Win32.UI.WindowsAndMessaging", "MSG")

    print(type.TypeNamespace(), type.TypeName(), get_category(type))
    for method in type.MethodList():
        print(method.Name(), [p.Type().Type() for p in method.Signature().Params()])

Names and shapes follow the C++ interface, so the two can be compared row for
row; research/agree.py does exactly that. Layout is ECMA-335 partition II and
the table schemas were taken from impl/winmd_reader/database.h.
"""

import bisect
import mmap
import struct
from enum import IntEnum, IntFlag
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

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

TABLE_NAMES = {
    MODULE: "Module", TYPE_REF: "TypeRef", TYPE_DEF: "TypeDef", FIELD: "Field",
    METHOD_DEF: "MethodDef", PARAM: "Param", INTERFACE_IMPL: "InterfaceImpl",
    MEMBER_REF: "MemberRef", CONSTANT: "Constant",
    CUSTOM_ATTRIBUTE: "CustomAttribute", FIELD_MARSHAL: "FieldMarshal",
    DECL_SECURITY: "DeclSecurity", CLASS_LAYOUT: "ClassLayout",
    FIELD_LAYOUT: "FieldLayout", STANDALONE_SIG: "StandAloneSig",
    EVENT_MAP: "EventMap", EVENT: "Event", PROPERTY_MAP: "PropertyMap",
    PROPERTY: "Property", METHOD_SEMANTICS: "MethodSemantics",
    METHOD_IMPL: "MethodImpl", MODULE_REF: "ModuleRef", TYPE_SPEC: "TypeSpec",
    IMPL_MAP: "ImplMap", FIELD_RVA: "FieldRVA", ASSEMBLY: "Assembly",
    ASSEMBLY_PROCESSOR: "AssemblyProcessor", ASSEMBLY_OS: "AssemblyOS",
    ASSEMBLY_REF: "AssemblyRef",
    ASSEMBLY_REF_PROCESSOR: "AssemblyRefProcessor",
    ASSEMBLY_REF_OS: "AssemblyRefOS", FILE: "File",
    EXPORTED_TYPE: "ExportedType", MANIFEST_RESOURCE: "ManifestResource",
    NESTED_CLASS: "NestedClass", GENERIC_PARAM: "GenericParam",
    METHOD_SPEC: "MethodSpec", GENERIC_PARAM_CONSTRAINT: "GenericParamConstraint",
}

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

    TypeDef = TYPE_DEF
    TypeRef = TYPE_REF
    TypeSpec = TYPE_SPEC


class HasConstant(IntEnum):
    """The tables a HasConstant column can point at."""

    Field = FIELD
    Param = PARAM
    Property = PROPERTY


class HasCustomAttribute(IntEnum):
    """The tables a HasCustomAttribute column can point at."""

    MethodDef = METHOD_DEF
    Field = FIELD
    TypeRef = TYPE_REF
    TypeDef = TYPE_DEF
    Param = PARAM
    InterfaceImpl = INTERFACE_IMPL
    MemberRef = MEMBER_REF
    Module = MODULE
    Permission = DECL_SECURITY
    Property = PROPERTY
    Event = EVENT
    StandAloneSig = STANDALONE_SIG
    ModuleRef = MODULE_REF
    TypeSpec = TYPE_SPEC
    Assembly = ASSEMBLY
    AssemblyRef = ASSEMBLY_REF
    File = FILE
    ExportedType = EXPORTED_TYPE
    ManifestResource = MANIFEST_RESOURCE
    GenericParam = GENERIC_PARAM
    GenericParamConstraint = GENERIC_PARAM_CONSTRAINT
    MethodSpec = METHOD_SPEC


class HasFieldMarshal(IntEnum):
    """The tables a HasFieldMarshal column can point at."""

    Field = FIELD
    Param = PARAM


class HasDeclSecurity(IntEnum):
    """The tables a HasDeclSecurity column can point at."""

    TypeDef = TYPE_DEF
    MethodDef = METHOD_DEF
    Assembly = ASSEMBLY


class MemberRefParent(IntEnum):
    """The tables a MemberRefParent column can point at."""

    TypeDef = TYPE_DEF
    TypeRef = TYPE_REF
    ModuleRef = MODULE_REF
    MethodDef = METHOD_DEF
    TypeSpec = TYPE_SPEC


class HasSemantics(IntEnum):
    """The tables a HasSemantics column can point at."""

    Event = EVENT
    Property = PROPERTY


class MethodDefOrRef(IntEnum):
    """The tables a MethodDefOrRef column can point at."""

    MethodDef = METHOD_DEF
    MemberRef = MEMBER_REF


class MemberForwarded(IntEnum):
    """The tables a MemberForwarded column can point at."""

    Field = FIELD
    MethodDef = METHOD_DEF


class Implementation(IntEnum):
    """The tables an Implementation column can point at."""

    File = FILE
    AssemblyRef = ASSEMBLY_REF
    ExportedType = EXPORTED_TYPE


class CustomAttributeType(IntEnum):
    """The tables a CustomAttributeType column can point at.

    The C++ starts this one at tag 2, the tags below it being reserved; here
    the values are tables, so only the two that name one are here.
    """

    MethodDef = METHOD_DEF
    MemberRef = MEMBER_REF


class ResolutionScope(IntEnum):
    """The tables a ResolutionScope column can point at."""

    Module = MODULE
    ModuleRef = MODULE_REF
    AssemblyRef = ASSEMBLY_REF
    TypeRef = TYPE_REF


class TypeOrMethodDef(IntEnum):
    """The tables a TypeOrMethodDef column can point at."""

    TypeDef = TYPE_DEF
    MethodDef = METHOD_DEF


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


class Blob:
    """A bounded view of bytes, and the cursor every signature is read with.

    This is the C++ byte_view: `as_uint32(offset)`, `seek(offset)` and
    `sub(offset, size)` do what they do there, and it is also a sequence of
    bytes, so `len()`, `[]` and `bytes()` work.
    """

    __slots__ = ("data", "position", "end", "table")

    def __init__(self, data: bytes, position: int = 0, size: int = None,
                 table: "Database" = None):
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

    def seek(self, offset: int) -> "Blob":
        """The same view, `offset` bytes further in."""
        if offset < 0 or self.position + offset > self.end:
            raise ValueError("seeking past the end of the view")
        return Blob(self.data, self.position + offset, self.end - self.position - offset,
                    self.table)

    def sub(self, offset: int, size: int) -> "Blob":
        if offset < 0 or size < 0 or self.position + offset + size > self.end:
            raise ValueError("the sub view does not fit")
        return Blob(self.data, self.position + offset, size, self.table)

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

    def coded_index(self, kind: type) -> "coded_index":
        """The next compressed value, as `coded_index[TypeDefOrRef]` or such."""
        return kind(self.table, self.unsigned())

    def __bool__(self) -> bool:
        return self.position < self.end

    # A blob is also just bytes, which is what the C++ byte_view offers.
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

    def __init__(self, blob: Blob):
        self._kind = blob.element_type()
        self._type = blob.coded_index(coded_index[TypeDefOrRef])

    def CustomMod(self) -> ElementType:
        return self._kind

    def Type(self) -> "coded_index":
        return self._type


def _parse_cmods(blob: Blob) -> List[CustomModSig]:
    mods = []
    while blob.peek_element_type() in (ElementType.CModOpt, ElementType.CModReqd):
        mods.append(CustomModSig(blob))
    return mods


class GenericTypeInstSig:
    __slots__ = ("_class_or_value", "_type", "_args")

    def __init__(self, blob: Blob):
        self._class_or_value = blob.element_type()
        if self._class_or_value not in (ElementType.Class, ElementType.ValueType):
            raise ValueError("a generic instantiation starts with Class or ValueType")
        self._type = blob.coded_index(coded_index[TypeDefOrRef])
        count = blob.unsigned()
        self._args = [TypeSig(blob) for _ in range(count)]

    def ClassOrValueType(self) -> ElementType:
        return self._class_or_value

    def GenericType(self) -> "coded_index":
        return self._type

    def GenericArgCount(self) -> int:
        return len(self._args)

    def GenericArgs(self) -> List["TypeSig"]:
        return self._args


class TypeSig:
    """A type as a signature spells it; Type() is the interesting part."""

    __slots__ = ("_szarray", "_array", "_ptr_count", "_cmod", "_element_type",
                 "_type", "_array_rank", "_array_sizes")

    def __init__(self, blob: Blob):
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
    def _parse(blob: Blob):
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

    def __init__(self, blob: Blob):
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

    def __init__(self, blob: Blob):
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


def _is_by_ref(blob: Blob) -> bool:
    if blob.peek_element_type() == ElementType.ByRef:
        blob.element_type()
        return True
    return False


class MethodDefSig:
    __slots__ = ("_convention", "_generic_count", "_return", "_params")

    def __init__(self, blob: Blob):
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

    def __init__(self, blob: Blob):
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

    def __init__(self, blob: Blob):
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

    def __init__(self, blob: Blob):
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

    def __init__(self, definition: "EnumDefinition", value):
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


def _read_primitive(kind: ElementType, blob: Blob):
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

    def __init__(self, database: "Database", blob: Blob, signature: MethodDefSig):
        if blob.read("<H") != 0x0001:
            raise ValueError("a custom attribute blob starts with the prolog 0x0001")
        self._fixed = [FixedArgSig(_read_argument(database, param, blob))
                       for param in signature.Params()]
        self._named = [_read_named(database, blob) for _ in range(blob.read("<H"))]

    def FixedArgs(self) -> List[FixedArgSig]:
        return self._fixed

    def NamedArgs(self) -> List[NamedArgSig]:
        return self._named


def _read_argument(database: "Database", param: ParamSig, blob: Blob):
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


def _read_array(kind: ElementType, blob: Blob):
    count = blob.read("<I")
    if count == 0xFFFFFFFF:
        return []
    return [ElemSig(_read_primitive(kind, blob)) for _ in range(count)]


def _read_enum(kind: ElementType, blob: Blob):
    if kind not in _PRIMITIVE_READERS or kind in (ElementType.R4, ElementType.R8):
        raise ValueError(f"{kind!r} cannot be the underlying type of an enum")
    return _read_primitive(kind, blob)


def _read_named(database: "Database", blob: Blob) -> NamedArgSig:
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

    def __init__(self, type: "Row"):
        self.m_typedef = type
        self.m_underlying_type = ElementType.End
        for field in type.FieldList():
            flags = field.Flags()
            if not flags.Literal() and not flags.Static():
                self.m_underlying_type = field.Signature().Type().Type()

    def get_enumerator(self, name: str) -> "Row":
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

    def __init_subclass__(cls, **kwargs):
        """A subclass states one kind, and is the class of that kind here."""
        super().__init_subclass__(**kwargs)
        if cls._sizing_tables is None:
            cls._sizing_tables = cls._tables
        _CODED_CLASSES[cls._kind] = cls

    def __class_getitem__(cls, kind):
        """The class for one kind, by its name or by the enum of that name."""
        return _CODED_CLASSES[getattr(kind, "__name__", kind)]

    def __init__(self, database: "Database", value: int):
        if self._kind is None:
            raise TypeError("coded_index[kind] is the class to instantiate")
        self._database = database
        self._value = value

    def type(self) -> int:
        """The table this points at, as a table number."""
        return self._tables[self._value & self._mask]

    def index(self) -> int:
        return (self._value >> self._bits) - 1

    def kind(self) -> str:
        return self._kind

    def get_row(self) -> "Row":
        return make_row(self._database, self.type(), self.index())

    def __getattr__(self, name: str) -> "Row":
        """`index.TypeRef()` and friends, as the C++ side spells get_row().

        The name has to be the table the index actually points at; asking for
        another one is the mistake the C++ assert catches.
        """
        table = next((number for number, spelling in TABLE_NAMES.items()
                      if spelling == name), None)
        if table is None:
            raise AttributeError(name)

        def get(table=table):
            if not self:
                raise RuntimeError(f"the {self._kind} index is not set")
            if self.type() != table:
                raise TypeError(f"the index points at {TABLE_NAMES[self.type()]}, "
                                f"not {TABLE_NAMES[table]}")
            return self.get_row()
        return get

    def get_database(self) -> "Database":
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
        return f"<coded_index {self._kind} -> {TABLE_NAMES[self.type()]}[{self.index()}]>"


# One class per kind, as the C++ template gives one type per kind:
# coded_index<TypeDefOrRef> is coded_index_TypeDefOrRef.
class coded_index_TypeDefOrRef(coded_index):
    """A TypeDefOrRef column: a TypeDef, a TypeRef or a TypeSpec."""

    __slots__ = ()
    _kind = "TypeDefOrRef"
    _tables = (TYPE_DEF, TYPE_REF, TYPE_SPEC)
    _bits = 2
    _mask = 0b11


class coded_index_HasConstant(coded_index):
    """A HasConstant column: what a Constant row belongs to."""

    __slots__ = ()
    _kind = "HasConstant"
    _tables = (FIELD, PARAM, PROPERTY)
    _bits = 2
    _mask = 0b11


class coded_index_HasCustomAttribute(coded_index):
    """A HasCustomAttribute column: what an attribute is attached to."""

    __slots__ = ()
    _kind = "HasCustomAttribute"
    _tables = (
        METHOD_DEF, FIELD, TYPE_REF, TYPE_DEF, PARAM, INTERFACE_IMPL, MEMBER_REF,
        MODULE, DECL_SECURITY, PROPERTY, EVENT, STANDALONE_SIG, MODULE_REF,
        TYPE_SPEC, ASSEMBLY, ASSEMBLY_REF, FILE, EXPORTED_TYPE,
        MANIFEST_RESOURCE, GENERIC_PARAM, GENERIC_PARAM_CONSTRAINT, METHOD_SPEC)
    _bits = 5
    _mask = 0b11111
    # The C++ reader sizes this one on 21 tables, leaving Permission out.
    _sizing_tables = tuple(table for table in _tables if table != DECL_SECURITY)


class coded_index_HasFieldMarshal(coded_index):
    """A HasFieldMarshal column: a Field or a Param."""

    __slots__ = ()
    _kind = "HasFieldMarshal"
    _tables = (FIELD, PARAM)
    _bits = 1
    _mask = 0b1


class coded_index_HasDeclSecurity(coded_index):
    """A HasDeclSecurity column: a TypeDef, a MethodDef or the Assembly."""

    __slots__ = ()
    _kind = "HasDeclSecurity"
    _tables = (TYPE_DEF, METHOD_DEF, ASSEMBLY)
    _bits = 2
    _mask = 0b11


class coded_index_MemberRefParent(coded_index):
    """A MemberRefParent column: what a MemberRef is a member of."""

    __slots__ = ()
    _kind = "MemberRefParent"
    _tables = (TYPE_DEF, TYPE_REF, MODULE_REF, METHOD_DEF, TYPE_SPEC)
    _bits = 3
    _mask = 0b111


class coded_index_HasSemantics(coded_index):
    """A HasSemantics column: an Event or a Property."""

    __slots__ = ()
    _kind = "HasSemantics"
    _tables = (EVENT, PROPERTY)
    _bits = 1
    _mask = 0b1


class coded_index_MethodDefOrRef(coded_index):
    """A MethodDefOrRef column: a MethodDef or a MemberRef."""

    __slots__ = ()
    _kind = "MethodDefOrRef"
    _tables = (METHOD_DEF, MEMBER_REF)
    _bits = 1
    _mask = 0b1


class coded_index_MemberForwarded(coded_index):
    """A MemberForwarded column: what an ImplMap row forwards."""

    __slots__ = ()
    _kind = "MemberForwarded"
    _tables = (FIELD, METHOD_DEF)
    _bits = 1
    _mask = 0b1


class coded_index_Implementation(coded_index):
    """An Implementation column: a File, an AssemblyRef or an ExportedType."""

    __slots__ = ()
    _kind = "Implementation"
    _tables = (FILE, ASSEMBLY_REF, EXPORTED_TYPE)
    _bits = 2
    _mask = 0b11


class coded_index_CustomAttributeType(coded_index):
    """A CustomAttributeType column: the attribute's constructor."""

    __slots__ = ()
    _kind = "CustomAttributeType"
    _tables = (None, None, METHOD_DEF, MEMBER_REF, None)
    _bits = 3
    _mask = 0b111


class coded_index_ResolutionScope(coded_index):
    """A ResolutionScope column: where a TypeRef is to be looked for."""

    __slots__ = ()
    _kind = "ResolutionScope"
    _tables = (MODULE, MODULE_REF, ASSEMBLY_REF, TYPE_REF)
    _bits = 2
    _mask = 0b11


class coded_index_TypeOrMethodDef(coded_index):
    """A TypeOrMethodDef column: what a GenericParam belongs to."""

    __slots__ = ()
    _kind = "TypeOrMethodDef"
    _tables = (TYPE_DEF, METHOD_DEF)
    _bits = 1
    _mask = 0b1


# --- rows -----------------------------------------------------------------
class RowRange(Sequence):
    """A member list: the rows of a table from one index to another."""

    __slots__ = ("_database", "_table", "_first", "_last")

    def __init__(self, database: "Database", table: int, first: int, last: int):
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
    def first(self) -> "Row":
        return make_row(self._database, self._table, self._first)

    @property
    def second(self) -> "Row":
        return make_row(self._database, self._table, self._last)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return make_row(self._database, self._table, self._first + index)

    def __repr__(self):
        return f"<{TABLE_NAMES[self._table]}_range {len(self)}>"


class AssemblyVersion(NamedTuple):
    """The four numbers of an assembly version, as the C++ struct has them."""

    MajorVersion: int
    MinorVersion: int
    BuildNumber: int
    RevisionNumber: int


class RowList(Sequence):
    """Rows of a table that are not next to each other."""

    __slots__ = ("_database", "_table", "_indexes")

    def __init__(self, database: "Database", table: int, indexes: List[int]):
        self._database = database
        self._table = table
        self._indexes = indexes

    def __len__(self) -> int:
        return len(self._indexes)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        return make_row(self._database, self._table, self._indexes[index])

    def __repr__(self):
        return f"<{TABLE_NAMES[self._table]}_list {len(self)}>"


class Row:
    """One row of one table, with the accessors that table has.

    A row is a value: the database, the table and the index, nothing more. The
    accessors are named as in C++ and defined per table below.
    """

    __slots__ = ("_database", "_table", "_index", "_columns")

    def __init__(self, database: "Database", table: int, index: int):
        self._database = database
        self._table = table
        self._index = index
        self._columns = None

    # --- the basics
    def index(self) -> int:
        return self._index

    def get_database(self) -> "Database":
        return self._database

    def get_cache(self) -> "cache":
        return self._database.get_cache()

    def get_value(self, column: int) -> int:
        if self._columns is None:
            if not self:
                raise RuntimeError(
                    f"{TABLE_NAMES[self._table]}[{self._index}] is not a row")
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
    def __add__(self, offset: int) -> "Row":
        return make_row(self._database, self._table, self._index + offset)

    def __sub__(self, other):
        if isinstance(other, Row):
            return self._index - other._index
        return make_row(self._database, self._table, self._index - other)

    def __hash__(self):
        return hash((id(self._database), self._table, self._index))

    def __repr__(self):
        return f"<{TABLE_NAMES[self._table]}[{self._index}]>"

    # --- what the columns mean
    def _string(self, column: int) -> str:
        return self._database.string(self.get_value(column))

    def _blob(self, column: int) -> Blob:
        return self._database.blob(self.get_value(column))

    def _coded(self, column: int, kind: type) -> coded_index:
        """One column, as `coded_index[TypeDefOrRef]` or whichever kind it is."""
        return kind(self._database, self.get_value(column))

    def _row(self, column: int, table: int) -> "Row":
        return make_row(self._database, table, self.get_value(column) - 1)

    def _list(self, column: int, table: int) -> RowRange:
        """my first child until the next row's first child."""
        first = self.get_value(column) - 1
        if self._index + 1 < self._database.rows(self._table):
            last = self._database.row(self._table, self._index + 1)[column] - 1
        else:
            last = self._database.rows(table)
        return RowRange(self._database, table, first, last)

    # --- Module
    def Generation(self) -> int:
        return self.get_value(0)

    # --- names, which several tables have in different columns
    def Name(self) -> str:
        return self._string(_NAME_COLUMN[self._table])

    def TypeName(self) -> str:
        return self._string(1 if self._table == TYPE_REF else 1)

    def TypeNamespace(self) -> str:
        return self._string(2)

    def Flags(self):
        return _FLAGS[self._table](self.get_value(_FLAGS_COLUMN[self._table]))

    # --- TypeDef
    def Extends(self) -> coded_index:
        return self._coded(3, coded_index[TypeDefOrRef])

    def FieldList(self) -> RowRange:
        return self._list(4, FIELD)

    def MethodList(self) -> RowRange:
        return self._list(5, METHOD_DEF)

    def InterfaceImpl(self) -> RowRange:
        return self._database.equal_range(INTERFACE_IMPL, 0, self._index + 1)

    def MethodImplList(self) -> RowRange:
        return self._database.equal_range(METHOD_IMPL, 0, self._index + 1)

    def PropertyList(self) -> RowRange:
        mapping = self._database.find_row(PROPERTY_MAP, 0, self._index + 1)
        return mapping._list(1, PROPERTY) if mapping else RowRange(
            self._database, PROPERTY, 0, 0)

    def EventList(self) -> RowRange:
        mapping = self._database.find_row(EVENT_MAP, 0, self._index + 1)
        return mapping._list(1, EVENT) if mapping else RowRange(
            self._database, EVENT, 0, 0)

    def EnclosingType(self) -> "Row":
        nested = self._database.find_row(NESTED_CLASS, 0, self._index + 1)
        if not nested:
            raise RuntimeError("the type is not nested")
        return nested._row(1, TYPE_DEF)

    def is_enum(self) -> bool:
        return extends_type(self, "System", "Enum")

    def get_enum_definition(self) -> EnumDefinition:
        return EnumDefinition(self)

    # --- MethodDef and Field
    def RVA(self) -> int:
        return self.get_value(0)

    def ImplFlags(self) -> MethodImplAttributes:
        return MethodImplAttributes(self.get_value(1))

    def Signature(self):
        if self._table == METHOD_DEF:
            return MethodDefSig(self._blob(4))
        if self._table == FIELD:
            return FieldSig(self._blob(2))
        if self._table == PROPERTY:
            return PropertySig(self._blob(2))
        if self._table == TYPE_SPEC:
            return TypeSpecSig(self._blob(0))
        if self._table == STANDALONE_SIG:
            return self._blob(0)
        raise AttributeError(f"{TABLE_NAMES[self._table]} has no Signature")

    def ParamList(self) -> RowRange:
        return self._list(5, PARAM)

    def SpecialName(self) -> bool:
        """MethodDef.Flags().SpecialName(), which the C++ side also shortens."""
        return self.Flags().SpecialName()

    def Parent(self) -> "Row":
        if self._table == METHOD_DEF:
            return self._database.parent_row(TYPE_DEF, 5, self._index)
        if self._table == FIELD:
            return self._database.parent_row(TYPE_DEF, 4, self._index)
        if self._table == PARAM:
            return self._database.parent_row(METHOD_DEF, 5, self._index)
        if self._table == PROPERTY:
            mapping = self._database.parent_row(PROPERTY_MAP, 1, self._index)
            return mapping._row(0, TYPE_DEF)
        if self._table == EVENT:
            mapping = self._database.parent_row(EVENT_MAP, 1, self._index)
            return mapping._row(0, TYPE_DEF)
        if self._table == CUSTOM_ATTRIBUTE:
            return self._coded(0, coded_index[HasCustomAttribute])
        if self._table == CONSTANT:
            return self._coded(1, coded_index[HasConstant])
        if self._table == FIELD_MARSHAL:
            return self._coded(0, coded_index[HasFieldMarshal])
        if self._table == CLASS_LAYOUT:
            return self._row(2, TYPE_DEF)
        raise AttributeError(f"{TABLE_NAMES[self._table]} has no Parent")

    def Sequence(self) -> int:
        return self.get_value(1)

    # --- rows that carry attributes
    def CustomAttribute(self) -> RowRange:
        tag = _HAS_CUSTOM_ATTRIBUTE_TAG[self._table]
        bits = coded_index[HasCustomAttribute]._bits
        return self._database.equal_range(
            CUSTOM_ATTRIBUTE, 0, ((self._index + 1) << bits) | tag)

    def Constant(self) -> "Row":
        tag = {FIELD: 0, PARAM: 1, PROPERTY: 2}[self._table]
        bits = coded_index[HasConstant]._bits
        row = self._database.find_row(CONSTANT, 1, ((self._index + 1) << bits) | tag)
        if not row:
            raise RuntimeError("there is no constant for this row")
        return row

    def FieldMarshal(self) -> "Row":
        tag = {FIELD: 0, PARAM: 1}[self._table]
        bits = coded_index[HasFieldMarshal]._bits
        return self._database.find_row(
            FIELD_MARSHAL, 0, ((self._index + 1) << bits) | tag)

    def GenericParam(self) -> RowRange:
        tag = {TYPE_DEF: 0, METHOD_DEF: 1}[self._table]
        bits = coded_index[TypeOrMethodDef]._bits
        return self._database.equal_range(
            GENERIC_PARAM, 2, ((self._index + 1) << bits) | tag)

    # --- Constant
    def Type(self):
        if self._table == CONSTANT:
            return ConstantType(self.get_value(0))
        if self._table == CUSTOM_ATTRIBUTE:
            return self._coded(1, coded_index[CustomAttributeType])
        if self._table == EVENT:
            return self._coded(2, coded_index[TypeDefOrRef])
        if self._table == PROPERTY:
            return self.Signature()
        raise AttributeError(f"{TABLE_NAMES[self._table]} has no Type")

    def Value(self):
        if self._table == CONSTANT:
            return _constant_value(ConstantType(self.get_value(0)), self._blob(2))
        if self._table == CUSTOM_ATTRIBUTE:
            constructor = self.Type()
            if constructor.type() == MEMBER_REF:
                signature = MethodDefSig(constructor.get_row()._blob(2))
            else:
                signature = constructor.get_row().Signature()
            return CustomAttributeSig(self._database, self._blob(2), signature)
        raise AttributeError(f"{TABLE_NAMES[self._table]} has no Value")

    def ValueBoolean(self) -> bool:
        return self._blob(2).read("<?")

    def ValueInt32(self) -> int:
        return self._blob(2).read("<i")

    def ValueUInt32(self) -> int:
        return self._blob(2).read("<I")

    def ValueString(self) -> str:
        blob = self._blob(2)
        return blob.data[blob.position:blob.end].decode("utf-16-le")

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
            if index.type() == MEMBER_REF:
                parent = row._coded(0, coded_index[MemberRefParent])
                found = get_type_namespace_and_name(parent)
            else:
                parent = row.Parent()
                found = (parent.TypeNamespace(), parent.TypeName())
            names[constructor] = found
        return found

    # --- InterfaceImpl, NestedClass, ImplMap, MethodSemantics, ...
    def Class(self) -> "Row":
        return self._row(0, TYPE_DEF)

    def Interface(self) -> coded_index:
        return self._coded(1, coded_index[TypeDefOrRef])

    def NestedType(self) -> "Row":
        return self._row(0, TYPE_DEF)

    def EnclosingTypeRow(self) -> "Row":
        return self._row(1, TYPE_DEF)

    def MappingFlags(self) -> PInvokeAttributes:
        return PInvokeAttributes(self.get_value(0))

    def MemberForwarded(self) -> coded_index:
        return self._coded(1, coded_index[MemberForwarded])

    def ImportName(self) -> str:
        return self._string(2)

    def ImportScope(self) -> "Row":
        return self._row(3, MODULE_REF)

    # Event spells its two columns differently, as the C++ side does.
    def EventFlags(self) -> EventAttributes:
        return EventAttributes(self.get_value(0))

    def EventType(self) -> coded_index:
        return self._coded(2, coded_index[TypeDefOrRef])

    def Semantic(self) -> MethodSemanticsAttributes:
        return MethodSemanticsAttributes(self.get_value(0))

    def Method(self) -> "Row":
        return self._row(1, METHOD_DEF)

    def Association(self) -> coded_index:
        return self._coded(2, coded_index[HasSemantics])

    def MethodSemantic(self) -> RowRange:
        tag = {EVENT: 0, PROPERTY: 1}[self._table]
        bits = coded_index[HasSemantics]._bits
        return self._database.equal_range(
            METHOD_SEMANTICS, 2, ((self._index + 1) << bits) | tag)

    def PackingSize(self) -> int:
        return self.get_value(0)

    def ClassSize(self) -> int:
        return self.get_value(1)

    def ResolutionScope(self) -> coded_index:
        return self._coded(0, coded_index[ResolutionScope])

    def Number(self) -> int:
        return self.get_value(0)

    def Owner(self) -> coded_index:
        return self._coded(2, coded_index[TypeOrMethodDef])

    def MethodSignature(self) -> MethodDefSig:
        return MethodDefSig(self._blob(2))

    # --- Assembly, AssemblyRef
    def Version(self) -> "AssemblyVersion":
        column = 1 if self._table == ASSEMBLY else 0
        offset, _ = self._database._columns[self._table][column]
        start = (self._database._start[self._table]
                 + self._index * self._database._row_size[self._table] + offset)
        return AssemblyVersion(*struct.unpack_from(
            "<HHHH", self._database._tables, start))

    def Culture(self) -> str:
        return self._string(5 if self._table == ASSEMBLY else 4)

    def PublicKey(self) -> Blob:
        return self._blob(3 if self._table == ASSEMBLY else 2)

    def HashAlgId(self) -> int:
        return self.get_value(0)


# One class per table, so a row says which table it is from and isinstance
# works, as it does with the C++ types. They differ in name only: the accessors
# a table has are the ones Row defines for it.
_ROW_CLASSES = {number: type(name, (Row,), {"__slots__": (), "__doc__":
                                            f"A row of the {name} table."})
                for number, name in TABLE_NAMES.items()}
globals().update({TABLE_NAMES[number]: cls for number, cls in _ROW_CLASSES.items()})


def make_row(database: "Database", table: int, index: int) -> Row:
    return _ROW_CLASSES[table](database, table, index)


_NAME_COLUMN = {
    MODULE: 1, TYPE_REF: 1, TYPE_DEF: 1, FIELD: 1, METHOD_DEF: 3, PARAM: 2,
    MEMBER_REF: 1, EVENT: 1, PROPERTY: 1, MODULE_REF: 0, IMPL_MAP: 2,
    ASSEMBLY: 4, ASSEMBLY_REF: 3, FILE: 1, EXPORTED_TYPE: 3,
    MANIFEST_RESOURCE: 2, GENERIC_PARAM: 3,
}

_FLAGS_COLUMN = {
    TYPE_DEF: 0, METHOD_DEF: 2, FIELD: 0, PARAM: 0, PROPERTY: 0, EVENT: 0,
    GENERIC_PARAM: 1, ASSEMBLY: 2, ASSEMBLY_REF: 1, EXPORTED_TYPE: 0,
    MANIFEST_RESOURCE: 1, IMPL_MAP: 0, METHOD_SEMANTICS: 0,
}

_FLAGS = {
    TYPE_DEF: TypeAttributes, METHOD_DEF: MethodAttributes,
    FIELD: FieldAttributes, PARAM: ParamAttributes,
    PROPERTY: PropertyAttributes, EVENT: EventAttributes,
    GENERIC_PARAM: GenericParamAttributes, IMPL_MAP: PInvokeAttributes,
    METHOD_SEMANTICS: MethodSemanticsAttributes,
    ASSEMBLY: AssemblyAttributes, ASSEMBLY_REF: AssemblyAttributes,
    EXPORTED_TYPE: _Flags, MANIFEST_RESOURCE: _Flags,
}

# The tag of each table inside the HasCustomAttribute coded index.
_HAS_CUSTOM_ATTRIBUTE_TAG = {
    table: tag for tag, table in enumerate(coded_index[HasCustomAttribute]._tables)
    if table is not None
}


def _constant_value(kind: ConstantType, blob: Blob):
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
class Table(Sequence):
    """One table, as a sequence of rows."""

    __slots__ = ("_database", "_table")

    def __init__(self, database: "Database", table: int):
        self._database = database
        self._table = table

    def __len__(self) -> int:
        return self._database.rows(self._table)

    def __getitem__(self, index):
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

    def get_database(self) -> "Database":
        return self._database

    def __repr__(self):
        return f"<{TABLE_NAMES[self._table]}_table {len(self)}>"


class Database:
    """One .winmd file, mapped and laid out; rows are decoded on demand."""

    def __init__(self, path, cache: "cache" = None):
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

        for table, attribute in TABLE_NAMES.items():
            setattr(self, attribute, Table(self, table))

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
            kind = coded_index[name]
            limit = 1 << (16 - kind._bits)
            return 2 if all(self.row_counts.get(table, 0) < limit
                            for table in kind._sizing_tables if table is not None) else 4

        self._columns: Dict[int, List[Tuple[int, int]]] = {}
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

    # --- reading
    def rows(self, table: int) -> int:
        return self.row_counts.get(table, 0)

    def row(self, table: int, index: int) -> Tuple[int, ...]:
        if not 0 <= index < self.rows(table):
            raise IndexError(f"{TABLE_NAMES[table]}[{index}]")
        return struct.unpack_from(
            self._format[table], self._tables,
            self._start[table] + index * self._row_size[table])

    def table(self, table: int) -> List[Tuple[int, ...]]:
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

    def get_blob(self, index: int) -> Blob:
        return self.blob(index)

    def string(self, index: int) -> str:
        """A string from the #Strings heap.

        Deliberately not cached: names are nearly all distinct, and a dict
        lookup that misses costs more than decoding eight bytes again. Where a
        column repeats, the caller caches - see cache().
        """
        heap = self._strings
        return heap[index:heap.index(b"\0", index)].decode("utf-8")

    def blob(self, index: int) -> Blob:
        size, position = uncompress_unsigned(self._blobs, index)
        return Blob(self._blobs, position, size, self)

    def guid(self, index: int) -> bytes:
        if not index:
            return b""
        return self._guids[(index - 1) * 16:index * 16]

    def get_cache(self) -> "cache":
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
    def _column(self, table: int, column: int) -> Tuple[List[int], Optional[Dict[int, List[int]]]]:
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

    def equal_range(self, table: int, column: int, value: int) -> Sequence:
        """The rows whose column equals `value`."""
        values, grouped = self._column(table, column)
        if grouped is not None:
            return RowList(self, table, grouped.get(value, []))
        first = bisect.bisect_left(values, value)
        last = bisect.bisect_right(values, value, first)
        return RowRange(self, table, first, last)

    def find_row(self, table: int, column: int, value: int) -> Optional[Row]:
        values, grouped = self._column(table, column)
        if grouped is not None:
            indexes = grouped.get(value)
            return make_row(self, table, indexes[0]) if indexes else None
        position = bisect.bisect_left(values, value)
        if position < len(values) and values[position] == value:
            return make_row(self, table, position)
        return None

    def parent_row(self, table: int, column: int, index: int) -> Row:
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
            Database(path).close()
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

    def __enter__(self) -> "Database":
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
        self._databases: List[Database] = []
        self._namespaces: Dict[str, namespace_members] = {}
        self._nested: Dict[Row, List[Row]] = {}
        for file in files:
            self.add_database(file, filter)

    def add_database(self, file: str, filter=None) -> None:
        database = Database(file, self)
        self._databases.append(database)

        heap = database._strings
        namespaces: Dict[int, str] = {}
        for index, row in enumerate(database.table(TYPE_DEF)):
            if not row[0]:                                   # the <Module> row
                continue
            type = make_row(database, TYPE_DEF, index)
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

        for row in database.NestedClass:
            self._nested.setdefault(row.EnclosingTypeRow(), []).append(row.NestedType())

    def _add_to_members(self, type: Row, members: namespace_members) -> None:
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

    def find(self, namespace: str, name: str = None) -> Optional[Row]:
        if name is None:
            namespace, _, name = namespace.rpartition(".")
            if not namespace:
                raise ValueError("a type name needs a namespace")
        members = self._namespaces.get(namespace)
        return members.types.get(name) if members else None

    def find_required(self, namespace: str, name: str = None) -> Row:
        type = self.find(namespace, name)
        if not type:
            raise ValueError(f"the type {namespace}.{name} could not be found")
        return type

    def namespaces(self) -> Dict[str, namespace_members]:
        return self._namespaces

    def databases(self) -> List[Database]:
        return self._databases

    def nested_types(self, enclosing: Row) -> List[Row]:
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
    if index.type() == TYPE_SPEC:
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


def get_base_class_namespace_and_name(type: Row) -> Tuple[str, str]:
    return get_type_namespace_and_name(type.Extends())


def extends_type(type: Row, namespace: str, name: str) -> bool:
    return get_base_class_namespace_and_name(type) == (namespace, name)


def is_nested(type: Row) -> bool:
    if type._table == TYPE_DEF:
        return type.Flags().Visibility() >= TypeVisibility.NestedPublic
    return type.ResolutionScope().type() == TYPE_REF     # a TypeRef


def get_category(type: Row) -> category:
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


def get_attribute(row, namespace: str, name: str) -> Optional[Row]:
    if isinstance(row, coded_index):
        row = row.get_row()
    for attribute in row.CustomAttribute():
        if attribute.TypeNamespaceAndName() == (namespace, name):
            return attribute
    return None


def find(type) -> Optional[Row]:
    """The definition a TypeRef or a TypeDefOrRef column points at."""
    if isinstance(type, coded_index):
        if type.type() == TYPE_DEF:
            return type.get_row()
        if type.type() == TYPE_SPEC:
            raise ValueError("a TypeSpec cannot be resolved to a TypeDef")
        type = type.get_row()
    if type.ResolutionScope().type() == TYPE_REF:          # a nested TypeRef
        enclosing = find(type.ResolutionScope().get_row())
        if not enclosing:
            return None
        for nested in enclosing.get_cache().nested_types(enclosing):
            if nested.TypeName() == type.TypeName():
                return nested
        return None
    return type.get_cache().find(type.TypeNamespace(), type.TypeName())


def find_required(type) -> Row:
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


# --- names the C++ interface uses -----------------------------------------
# The bindings spell a coded index after the kind it holds and the database
# class in lower case; the same programs should read either module.
database = Database
byte_view = Blob
