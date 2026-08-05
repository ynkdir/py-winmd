"""The enums, as impl/winmd_reader/enum.h has them.

The 38 table numbers, the element types a signature can hold, the tags of
each coded index, and the fields of the flags columns that are wider than a
bit. Nothing here depends on anything else in the package.
"""

from __future__ import annotations

from enum import IntEnum, IntFlag
from typing import TypeAlias, TypeVar


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


# --- enums ----------------------------------------------------------------
# What enum_mask is handed, and hands back: one of the enums below.
_EnumT = TypeVar("_EnumT", bound=int)


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
    I = 0x18  # noqa: E741 - the name the standard and the C++ give it
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
    FamAndAssem = 2
    Assembly = 3
    Family = 4
    FamOrAssem = 5
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
    AutoLayout = 0x00000000
    SequentialLayout = 0x00000008
    ExplicitLayout = 0x00000010


class TypeSemantics(IntEnum):
    Class = 0x00000000
    Interface = 0x00000020


class StringFormat(IntEnum):
    AnsiClass = 0x00000000
    UnicodeClass = 0x00010000
    AutoClass = 0x00020000
    CustomFormatClass = 0x00030000
    CustomFormatMask = 0x00C00000  # outside the column's own mask


class CodeType(IntEnum):
    IL = 0
    Native = 1
    OPTIL = 2
    Runtime = 3


class Managed(IntEnum):
    Unmanaged = 0x0004
    Managed = 0x0000


class VtableLayout(IntEnum):
    ReuseSlot = 0x0000
    NewSlot = 0x0100


# The two fields of MappingFlags that are wider than a bit (ECMA-335 II.23.1.8).
# The C++ has no accessors for ImplMap, so it has no enums for these either.
class CharSet(IntEnum):
    CharSetNotSpec = 0x0000
    CharSetAnsi = 0x0002
    CharSetUnicode = 0x0004
    CharSetAuto = 0x0006


class CallConv(IntEnum):
    CallConvWinapi = 0x0100
    CallConvCdecl = 0x0200
    CallConvStdcall = 0x0300
    CallConvThiscall = 0x0400
    CallConvFastcall = 0x0500


class GenericParamVariance(IntEnum):
    None_ = 0
    Covariant = 1
    Contravariant = 2


# The constraints a generic parameter can carry, any of them at once, so the
# values are the bits of the column and are not shifted down to it.
class GenericParamSpecialConstraint(IntFlag):
    ReferenceTypeConstraint = 0x0004
    NotNullableValueTypeConstraint = 0x0008
    DefaultConstructorConstraint = 0x0010


class AssemblyHashAlgorithm(IntEnum):
    None_ = 0x0000
    Reserved_MD5 = 0x8003
    SHA1 = 0x8004


class AssemblyFlags(IntFlag):
    """The bits of an Assembly or AssemblyRef Flags column.

    AssemblyAttributes reads them one at a time, as the C++ does; this is the
    same set of bits under the name the standard gives them.
    """

    PublicKey = 0x0001
    Retargetable = 0x0100
    WindowsRuntime = 0x0200
    DisableJITcompileOptimizer = 0x4000
    EnableJITcompileTracking = 0x8000


class category(IntEnum):
    interface_type = 0
    class_type = 1
    enum_type = 2
    struct_type = 3
    delegate_type = 4


# One enum per coded index, as the C++ has: the tag a column of that kind
# holds, and the table that tag names. `coded_index.type()` returns one of
# these, so `index.type() is TypeDefOrRef.TypeSpec` reads as it does in C++.
# Compare them with `is`: two kinds give the same tag to different tables,
# and only identity tells HasCustomAttribute.MethodDef from
# TypeDefOrRef.TypeDef. The enum names the kind as well, so
# `coded_index_TypeDefOrRef` is the class of such a column.
class TypeDefOrRef(IntEnum):
    """The tables a TypeDefOrRef column can point at, by their tag."""

    TypeDef = 0
    TypeRef = 1
    TypeSpec = 2


class HasConstant(IntEnum):
    """The tables a HasConstant column can point at, by their tag."""

    Field = 0
    Param = 1
    Property = 2


class HasCustomAttribute(IntEnum):
    """The tables a HasCustomAttribute column can point at, by their tag."""

    MethodDef = 0
    Field = 1
    TypeRef = 2
    TypeDef = 3
    Param = 4
    InterfaceImpl = 5
    MemberRef = 6
    Module = 7
    DeclSecurity = 8
    Property = 9
    Event = 10
    StandAloneSig = 11
    ModuleRef = 12
    TypeSpec = 13
    Assembly = 14
    AssemblyRef = 15
    File = 16
    ExportedType = 17
    ManifestResource = 18
    GenericParam = 19
    GenericParamConstraint = 20
    MethodSpec = 21


class HasFieldMarshal(IntEnum):
    """The tables a HasFieldMarshal column can point at, by their tag."""

    Field = 0
    Param = 1


class HasDeclSecurity(IntEnum):
    """The tables a HasDeclSecurity column can point at, by their tag."""

    TypeDef = 0
    MethodDef = 1
    Assembly = 2


class MemberRefParent(IntEnum):
    """The tables a MemberRefParent column can point at, by their tag."""

    TypeDef = 0
    TypeRef = 1
    ModuleRef = 2
    MethodDef = 3
    TypeSpec = 4


class HasSemantics(IntEnum):
    """The tables a HasSemantics column can point at, by their tag."""

    Event = 0
    Property = 1


class MethodDefOrRef(IntEnum):
    """The tables a MethodDefOrRef column can point at, by their tag."""

    MethodDef = 0
    MemberRef = 1


class MemberForwarded(IntEnum):
    """The tables a MemberForwarded column can point at, by their tag."""

    Field = 0
    MethodDef = 1


class Implementation(IntEnum):
    """The tables a Implementation column can point at, by their tag."""

    File = 0
    AssemblyRef = 1
    ExportedType = 2


class CustomAttributeType(IntEnum):
    """The tables a CustomAttributeType column can point at, by their tag."""

    MethodDef = 2
    MemberRef = 3


class ResolutionScope(IntEnum):
    """The tables a ResolutionScope column can point at, by their tag."""

    Module = 0
    ModuleRef = 1
    AssemblyRef = 2
    TypeRef = 3


class TypeOrMethodDef(IntEnum):
    """The tables a TypeOrMethodDef column can point at, by their tag."""

    TypeDef = 0
    MethodDef = 1


# The kinds there are: the thirteen enums above and no other enum. The C++
# constrains nothing - coded_index<T> takes whatever T it is given, and a T
# with no coded_index_bits specialisation simply gets 0 - so this is where
# the two differ. Everything keyed by a kind is keyed by one of these.
CodedIndexT: TypeAlias = (
    TypeDefOrRef
    | HasConstant
    | HasCustomAttribute
    | HasFieldMarshal
    | HasDeclSecurity
    | MemberRefParent
    | HasSemantics
    | MethodDefOrRef
    | MemberForwarded
    | Implementation
    | CustomAttributeType
    | ResolutionScope
    | TypeOrMethodDef
)


# How wide the tag of each kind is, as `coded_index_bits<T>` states it in
# enum.h and `coded_index_bits_v<T>` reads it. The C++ writes one traits
# specialisation under each enum above, because a C++ enum cannot hold a
# member; a dict says the same thing once, in the same order.
coded_index_bits_v: dict[type[CodedIndexT], int] = {
    TypeDefOrRef: 2,
    HasConstant: 2,
    HasCustomAttribute: 5,
    HasFieldMarshal: 1,
    HasDeclSecurity: 2,
    MemberRefParent: 3,
    HasSemantics: 1,
    MethodDefOrRef: 1,
    MemberForwarded: 1,
    Implementation: 2,
    CustomAttributeType: 3,
    ResolutionScope: 2,
    TypeOrMethodDef: 1,
}


def enum_mask(value: _EnumT, mask: _EnumT) -> _EnumT:
    """The C++ enum_mask: the bits of `value` that `mask` selects."""
    return type(value)(int(value) & int(mask))
