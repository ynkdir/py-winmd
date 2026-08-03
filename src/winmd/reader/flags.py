"""The flags columns, as impl/winmd_reader/flags.h has them.

One class per column that holds a bit field, each with an accessor per flag,
returning a bool for the single bits and an enum from `enum.py` for the fields
that are wider.
"""

from __future__ import annotations

from .enum import (
    CallConv,
    CharSet,
    CodeType,
    GenericParamSpecialConstraint,
    GenericParamVariance,
    Managed,
    MemberAccess,
    StringFormat,
    TypeLayout,
    TypeSemantics,
    TypeVisibility,
    VtableLayout,
)


# --- the flag structs -----------------------------------------------------
class _Flags:
    """One metadata flags column: a value, and an accessor per field of it.

    The C++ spells these as methods over a bitfield - AttributesBase, with
    get_enum for the fields of several bits and get_bit for the rest - and so
    do these. ExportedType and ManifestResource use this class as it is: the
    C++ has no accessors for their flags either.
    """

    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value

    def __int__(self) -> int:
        return self.value

    def __index__(self) -> int:
        return self.value

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.value:#x}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Flags) and self.value == other.value


class TypeAttributes(_Flags):
    """The Flags column of a TypeDef."""

    __slots__ = ()

    def Visibility(self) -> TypeVisibility:
        return TypeVisibility(self.value & 0x00000007)

    def Layout(self) -> TypeLayout:
        return TypeLayout(self.value & 0x00000018)

    def Semantics(self) -> TypeSemantics:
        return TypeSemantics(self.value & 0x00000020)

    def Abstract(self) -> bool:
        return bool(self.value & 0x00000080)

    def Sealed(self) -> bool:
        return bool(self.value & 0x00000100)

    def SpecialName(self) -> bool:
        return bool(self.value & 0x00000400)

    def RTSpecialName(self) -> bool:
        return bool(self.value & 0x00000800)

    def Import(self) -> bool:
        return bool(self.value & 0x00001000)

    def Serializable(self) -> bool:
        return bool(self.value & 0x00002000)

    def WindowsRuntime(self) -> bool:
        return bool(self.value & 0x00004000)

    # Three accessors are named as the enum they return - StringFormat here,
    # CodeType and Managed below - so inside the class the name means the
    # method. The annotation is a string, which is resolved against the
    # module and finds the enum. The C++ writes reader::StringFormat.
    def StringFormat(self) -> "StringFormat":
        return StringFormat(self.value & 0x00030000)

    def HasSecurity(self) -> bool:
        return bool(self.value & 0x00040000)

    def BeforeFieldInit(self) -> bool:
        return bool(self.value & 0x00100000)

    def IsTypeForwarder(self) -> bool:
        return bool(self.value & 0x00200000)


class MethodAttributes(_Flags):
    """The Flags column of a MethodDef."""

    __slots__ = ()

    def Access(self) -> MemberAccess:
        return MemberAccess(self.value & 0x0007)

    def UnmanagedExport(self) -> bool:
        return bool(self.value & 0x0008)

    def Static(self) -> bool:
        return bool(self.value & 0x0010)

    def Final(self) -> bool:
        return bool(self.value & 0x0020)

    def Virtual(self) -> bool:
        return bool(self.value & 0x0040)

    def HideBySig(self) -> bool:
        return bool(self.value & 0x0080)

    def Layout(self) -> VtableLayout:
        return VtableLayout(self.value & 0x0100)

    def Strict(self) -> bool:
        return bool(self.value & 0x0200)

    def Abstract(self) -> bool:
        return bool(self.value & 0x0400)

    def SpecialName(self) -> bool:
        return bool(self.value & 0x0800)

    def RTSpecialName(self) -> bool:
        return bool(self.value & 0x1000)

    def PInvokeImpl(self) -> bool:
        return bool(self.value & 0x2000)

    def HasSecurity(self) -> bool:
        return bool(self.value & 0x4000)

    def RequireSecObject(self) -> bool:
        return bool(self.value & 0x8000)


class MethodImplAttributes(_Flags):
    """The ImplFlags column of a MethodDef."""

    __slots__ = ()

    def CodeType(self) -> "CodeType":
        return CodeType(self.value & 0x0003)

    def Managed(self) -> "Managed":
        return Managed(self.value & 0x0004)

    def NoInlining(self) -> bool:
        return bool(self.value & 0x0008)

    def ForwardRef(self) -> bool:
        return bool(self.value & 0x0010)

    def Synchronized(self) -> bool:
        return bool(self.value & 0x0020)

    def NoOptimization(self) -> bool:
        return bool(self.value & 0x0040)

    def PreserveSig(self) -> bool:
        return bool(self.value & 0x0080)

    def InternalCall(self) -> bool:
        return bool(self.value & 0x1000)


class FieldAttributes(_Flags):
    """The Flags column of a Field."""

    __slots__ = ()

    def Access(self) -> MemberAccess:
        return MemberAccess(self.value & 0x0007)

    def Static(self) -> bool:
        return bool(self.value & 0x0010)

    def InitOnly(self) -> bool:
        return bool(self.value & 0x0020)

    def Literal(self) -> bool:
        return bool(self.value & 0x0040)

    def NotSerialized(self) -> bool:
        return bool(self.value & 0x0080)

    def HasFieldRVA(self) -> bool:
        return bool(self.value & 0x0100)

    def SpecialName(self) -> bool:
        return bool(self.value & 0x0200)

    def RTSpecialName(self) -> bool:
        return bool(self.value & 0x0400)

    def HasFieldMarshal(self) -> bool:
        return bool(self.value & 0x1000)

    def PInvokeImpl(self) -> bool:
        return bool(self.value & 0x2000)

    def HasDefault(self) -> bool:
        return bool(self.value & 0x8000)


class ParamAttributes(_Flags):
    """The Flags column of a Param."""

    __slots__ = ()

    def In(self) -> bool:
        return bool(self.value & 0x0001)

    def Out(self) -> bool:
        return bool(self.value & 0x0002)

    def Optional(self) -> bool:
        return bool(self.value & 0x0010)

    def HasDefault(self) -> bool:
        return bool(self.value & 0x1000)

    def HasFieldMarshal(self) -> bool:
        return bool(self.value & 0x2000)


class PropertyAttributes(_Flags):
    """The Flags column of a Property."""

    __slots__ = ()

    def SpecialName(self) -> bool:
        return bool(self.value & 0x0200)

    def RTSpecialName(self) -> bool:
        return bool(self.value & 0x0400)

    def HasDefault(self) -> bool:
        return bool(self.value & 0x1000)


class EventAttributes(_Flags):
    """The EventFlags column of an Event."""

    __slots__ = ()

    def SpecialName(self) -> bool:
        return bool(self.value & 0x0200)

    def RTSpecialName(self) -> bool:
        return bool(self.value & 0x0400)


class MethodSemanticsAttributes(_Flags):
    """The Semantic column of a MethodSemantics row."""

    __slots__ = ()

    def Setter(self) -> bool:
        return bool(self.value & 0x0001)

    def Getter(self) -> bool:
        return bool(self.value & 0x0002)

    def Other(self) -> bool:
        return bool(self.value & 0x0004)

    def AddOn(self) -> bool:
        return bool(self.value & 0x0008)

    def RemoveOn(self) -> bool:
        return bool(self.value & 0x0010)

    def Fire(self) -> bool:
        return bool(self.value & 0x0020)


class GenericParamAttributes(_Flags):
    """The Flags column of a GenericParam."""

    __slots__ = ()

    def Variance(self) -> GenericParamVariance:
        return GenericParamVariance(self.value & 0x0003)

    def SpecialConstraint(self) -> GenericParamSpecialConstraint:
        return GenericParamSpecialConstraint(self.value & 0x001C)


class AssemblyAttributes(_Flags):
    """The Flags column of an Assembly or an AssemblyRef."""

    __slots__ = ()

    def PublicKey(self) -> bool:
        return bool(self.value & 0x00000001)

    def Retargetable(self) -> bool:
        return bool(self.value & 0x00000100)

    def WindowsRuntime(self) -> bool:
        return bool(self.value & 0x00000200)

    def DisableJITcompileOptimizer(self) -> bool:
        return bool(self.value & 0x00004000)

    def EnableJITcompileTracking(self) -> bool:
        return bool(self.value & 0x00008000)


class PInvokeAttributes(_Flags):
    """The MappingFlags column of an ImplMap row.

    Ours: the C++ has no accessors for that table.
    """

    __slots__ = ()

    def NoMangle(self) -> bool:
        return bool(self.value & 0x0001)

    def CharSet(self) -> "CharSet":
        return CharSet(self.value & 0x0006)

    def SupportsLastError(self) -> bool:
        return bool(self.value & 0x0040)

    def CallConv(self) -> "CallConv":
        return CallConv(self.value & 0x0700)
