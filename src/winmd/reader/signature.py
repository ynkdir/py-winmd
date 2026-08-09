"""The signature blobs, as impl/winmd_reader/signature.h has them.

A signature is not a table: it is a small recursive grammar written into
#Blob, read front to back. Custom attribute values are here too, since
decoding one means reading its constructor's signature first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias

from .enum import CallingConvention, ElementType, TypeDefOrRef, enum_mask
from .helpers import EnumDefinition, find_required, get_type_namespace_and_name
from .table import coded_index, table_base
from .view import byte_view

if TYPE_CHECKING:
    from .database import database
    from .index import coded_index_TypeDefOrRef


def _coded_index(table: table_base, blob: byte_view) -> coded_index_TypeDefOrRef:
    """The next compressed value, as a TypeDefOrRef.

    signature.h spells this `coded_index<TypeDefOrRef>{ table, uncompress_
    unsigned(data) }`, and carries the table beside the view rather than in
    it, as every signature here carries the database. Only signatures hold a
    coded index in a blob, and only ever of this kind.
    """
    return coded_index.of(TypeDefOrRef, table, blob.unsigned())


# --- signatures -----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class GenericTypeIndex:
    """Which type parameter of the enclosing type this is: !0, !1, ..."""

    index: int

    def __repr__(self) -> str:
        return f"<GenericTypeIndex {self.index}>"


@dataclass(frozen=True, slots=True)
class GenericMethodTypeIndex:
    """Which type parameter of the enclosing method this is: !!0, !!1, ..."""

    index: int

    def __repr__(self) -> str:
        return f"<GenericMethodTypeIndex {self.index}>"


class CustomModSig:
    __slots__ = ("_kind", "_type")

    def __init__(self, table: table_base, blob: byte_view) -> None:
        self._kind: ElementType = blob.element_type()
        self._type: coded_index_TypeDefOrRef = _coded_index(table, blob)

    def CustomMod(self) -> ElementType:
        return self._kind

    def Type(self) -> coded_index_TypeDefOrRef:
        return self._type


def _parse_cmods(table: table_base, blob: byte_view) -> list[CustomModSig]:
    mods = []
    while blob.peek_element_type() in (
        ElementType.CModOpt,
        ElementType.CModReqd,
    ):
        mods.append(CustomModSig(table, blob))
    return mods


class GenericTypeInstSig:
    __slots__ = ("_class_or_value", "_type", "_args")

    def __init__(self, table: table_base, blob: byte_view) -> None:
        self._class_or_value: ElementType = blob.element_type()
        if self._class_or_value not in (
            ElementType.Class,
            ElementType.ValueType,
        ):
            raise ValueError("a generic instantiation starts with Class or ValueType")
        self._type: coded_index_TypeDefOrRef = _coded_index(table, blob)
        count = blob.unsigned()
        self._args: list[TypeSig] = [TypeSig(table, blob) for _ in range(count)]

    def ClassOrValueType(self) -> ElementType:
        return self._class_or_value

    def GenericType(self) -> coded_index_TypeDefOrRef:
        return self._type

    def GenericArgCount(self) -> int:
        return len(self._args)

    def GenericArgs(self) -> list["TypeSig"]:
        return self._args


class TypeSig:
    """A type as a signature spells it; Type() is the interesting part."""

    # The five things Type() can hand back, as the C++ std::variant that
    # TypeSig::value_type names. Written here rather than five lines at each
    # of the three places it is said. For the checker alone: a variant is
    # not a type to test against in C++ either - that is holds_alternative -
    # and coded_index_TypeDefOrRef is a name signature.py has no other use
    # for at run time.
    if TYPE_CHECKING:
        value_type: TypeAlias = (
            ElementType
            | coded_index_TypeDefOrRef
            | GenericTypeInstSig
            | GenericTypeIndex
            | GenericMethodTypeIndex
        )

    __slots__ = (
        "_szarray",
        "_array",
        "_ptr_count",
        "_cmod",
        "_element_type",
        "_type",
        "_array_rank",
        "_array_sizes",
    )

    def __init__(self, table: table_base, blob: byte_view) -> None:
        self._szarray: bool = False
        self._array: bool = False
        self._ptr_count: int = 0
        self._array_rank: int = 0
        self._array_sizes: list[int] = []

        if blob.peek_element_type() == ElementType.SZArray:
            blob.element_type()
            self._szarray = True
        if blob.peek_element_type() == ElementType.Array:
            blob.element_type()
            self._array = True
        while blob.peek_element_type() == ElementType.Ptr:
            blob.element_type()
            self._ptr_count += 1
        self._cmod: list[CustomModSig] = _parse_cmods(table, blob)
        self._element_type: ElementType = blob.peek_element_type()
        self._type: TypeSig.value_type = self._parse(table, blob)
        if self._array:
            self._array_rank = blob.unsigned()
            count = blob.unsigned()
            self._array_sizes = [blob.unsigned() for _ in range(count)]

    @staticmethod
    def _parse(table: table_base, blob: byte_view) -> TypeSig.value_type:
        element_type = blob.element_type()
        if element_type in _PRIMITIVE_TYPES:
            return element_type
        if element_type in (ElementType.Class, ElementType.ValueType):
            return _coded_index(table, blob)
        if element_type == ElementType.GenericInst:
            return GenericTypeInstSig(table, blob)
        if element_type == ElementType.Var:
            return GenericTypeIndex(blob.unsigned())
        if element_type == ElementType.MVar:
            return GenericMethodTypeIndex(blob.unsigned())
        raise ValueError(f"unrecognised element type {element_type!r}")

    def Type(self) -> TypeSig.value_type:
        return self._type

    def element_type(self) -> ElementType:
        return self._element_type

    def is_szarray(self) -> bool:
        return self._szarray

    def is_array(self) -> bool:
        return self._array

    def array_rank(self) -> int:
        return self._array_rank

    def array_sizes(self) -> list[int]:
        return self._array_sizes

    def ptr_count(self) -> int:
        return self._ptr_count

    def CustomMod(self) -> list[CustomModSig]:
        return self._cmod


_PRIMITIVE_TYPES = frozenset(
    (
        ElementType.Boolean,
        ElementType.Char,
        ElementType.I1,
        ElementType.U1,
        ElementType.I2,
        ElementType.U2,
        ElementType.I4,
        ElementType.U4,
        ElementType.I8,
        ElementType.U8,
        ElementType.R4,
        ElementType.R8,
        ElementType.String,
        ElementType.Object,
        ElementType.U,
        ElementType.I,
        ElementType.Void,
    )
)


class ParamSig:
    __slots__ = ("_cmod", "_byref", "_type")

    def __init__(self, table: table_base, blob: byte_view) -> None:
        self._cmod: list[CustomModSig] = _parse_cmods(table, blob)
        self._byref: bool = _is_by_ref(blob)
        self._type: TypeSig = TypeSig(table, blob)

    def CustomMod(self) -> list[CustomModSig]:
        return self._cmod

    def ByRef(self) -> bool:
        return self._byref

    def Type(self) -> TypeSig:
        return self._type


class RetTypeSig:
    __slots__ = ("_cmod", "_byref", "_type")

    def __init__(self, table: table_base, blob: byte_view) -> None:
        self._cmod: list[CustomModSig] = _parse_cmods(table, blob)
        self._byref: bool = _is_by_ref(blob)
        self._type: TypeSig | None
        if blob.peek_element_type() == ElementType.Void:
            blob.element_type()
            self._type = None
        else:
            self._type = TypeSig(table, blob)

    def CustomMod(self) -> list[CustomModSig]:
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

    def __init__(self, table: table_base, blob: byte_view) -> None:
        self._convention: CallingConvention = CallingConvention(blob.unsigned())
        self._generic_count: int = (
            blob.unsigned()
            if enum_mask(self._convention, CallingConvention.Generic)
            == CallingConvention.Generic
            else 0
        )
        count = blob.unsigned()
        self._return: RetTypeSig = RetTypeSig(table, blob)
        self._params: list[ParamSig] = [ParamSig(table, blob) for _ in range(count)]

    def CallConvention(self) -> CallingConvention:
        return self._convention

    def GenericParamCount(self) -> int:
        return self._generic_count

    def ReturnType(self) -> RetTypeSig:
        return self._return

    def Params(self) -> list[ParamSig]:
        return self._params


class FieldSig:
    __slots__ = ("_convention", "_cmod", "_type")

    def __init__(self, table: table_base, blob: byte_view) -> None:
        self._convention: CallingConvention = CallingConvention(blob.unsigned())
        if (
            enum_mask(self._convention, CallingConvention.Field)
            != CallingConvention.Field
        ):
            raise ValueError("a field signature starts with the Field convention")
        self._cmod: list[CustomModSig] = _parse_cmods(table, blob)
        self._type: TypeSig = TypeSig(table, blob)

    def CustomMod(self) -> list[CustomModSig]:
        return self._cmod

    def Type(self) -> TypeSig:
        return self._type


class PropertySig:
    __slots__ = ("_convention", "_cmod", "_type", "_params")

    def CallConvention(self) -> CallingConvention:
        return self._convention

    def __init__(self, table: table_base, blob: byte_view) -> None:
        self._convention: CallingConvention = CallingConvention(blob.unsigned())
        if (
            enum_mask(self._convention, CallingConvention.Property)
            != CallingConvention.Property
        ):
            raise ValueError("a property signature starts with the Property convention")
        count = blob.unsigned()
        self._cmod: list[CustomModSig] = _parse_cmods(table, blob)
        self._type: TypeSig = TypeSig(table, blob)
        self._params: list[ParamSig] = [ParamSig(table, blob) for _ in range(count)]

    def CustomMod(self) -> list[CustomModSig]:
        return self._cmod

    def Type(self) -> TypeSig:
        return self._type

    def Params(self) -> list[ParamSig]:
        return self._params


class TypeSpecSig:
    __slots__ = ("_type",)

    def __init__(self, table: table_base, blob: byte_view) -> None:
        if blob.peek_element_type() != ElementType.GenericInst:
            raise ValueError("a TypeSpec signature is a generic instantiation")
        blob.element_type()
        self._type: GenericTypeInstSig = GenericTypeInstSig(table, blob)

    def GenericTypeInst(self) -> GenericTypeInstSig:
        return self._type


# --- custom attributes ----------------------------------------------------
@dataclass(frozen=True, slots=True)
class SystemType:
    """A typeof() argument, which the metadata holds by name."""

    name: str

    def __repr__(self) -> str:
        return f"<ElemSig.SystemType {self.name!r}>"


@dataclass(frozen=True, slots=True)
class EnumValue:
    """An argument whose type is an enum, and the enum it belongs to."""

    type: EnumDefinition
    value: Any

    def equals_enumerator(self, name: str) -> bool:
        return self.type.get_enumerator(name).Constant().Value() == self.value

    def __repr__(self) -> str:
        return f"<ElemSig.EnumValue {self.value}>"


@dataclass(frozen=True, slots=True)
class ElemSig:
    """One decoded argument of a custom attribute.

    A primitive, a SystemType or an EnumValue; the two are reached as
    `ElemSig.SystemType` and `ElemSig.EnumValue`, as the C++ nests them.
    """

    SystemType = SystemType  # not annotated, so not a field
    EnumValue = EnumValue

    value: Any

    def __repr__(self) -> str:
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


def _read_primitive(kind: ElementType, blob: byte_view) -> bool | int | float | str:
    if kind == ElementType.String:
        return blob.string()
    try:
        format, special = _PRIMITIVE_READERS[kind]
    except KeyError:
        raise ValueError(f"non-primitive type {kind!r} in a custom attribute") from None
    value = blob.read(format)
    return chr(value) if special == "char" else value


@dataclass(frozen=True, slots=True)
class FixedArgSig:
    """One positional argument: an ElemSig, or a tuple of them for an array."""

    value: Any


@dataclass(frozen=True, slots=True)
class NamedArgSig:
    """One named argument, which is a positional one under a name."""

    name: str
    value: FixedArgSig


class CustomAttributeSig:
    __slots__ = ("_fixed", "_named")

    def __init__(
        self, database: database, blob: byte_view, signature: MethodDefSig
    ) -> None:
        if blob.read("<H") != 0x0001:
            raise ValueError("a custom attribute blob starts with the prolog 0x0001")
        self._fixed: list[FixedArgSig] = [
            FixedArgSig(_read_argument(database, param, blob))
            for param in signature.Params()
        ]
        self._named: list[NamedArgSig] = [
            _read_named(database, blob) for _ in range(blob.read("<H"))
        ]

    def FixedArgs(self) -> list[FixedArgSig]:
        return self._fixed

    def NamedArgs(self) -> list[NamedArgSig]:
        return self._named


def _read_argument(
    database: database, param: ParamSig, blob: byte_view
) -> ElemSig | tuple[ElemSig, ...]:
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
            raise ValueError(
                "a custom attribute argument must be an enum or System.Type"
            )
        enum = definition.get_enum_definition()
        return ElemSig(EnumValue(enum, _read_enum(enum.m_underlying_type, blob)))
    raise ValueError(
        "a custom attribute argument must be a primitive, an enum or System.Type"
    )


def _read_array(kind: ElementType, blob: byte_view) -> tuple[ElemSig, ...]:
    """The elements of an array argument. A count of -1 is a null array."""
    count = blob.read("<I")
    if count == 0xFFFFFFFF:
        return ()
    return tuple(ElemSig(_read_primitive(kind, blob)) for _ in range(count))


def _read_enum(kind: ElementType, blob: byte_view) -> bool | int | float | str:
    if kind not in _PRIMITIVE_READERS or kind in (
        ElementType.R4,
        ElementType.R8,
    ):
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
        return NamedArgSig(
            name,
            FixedArgSig(
                ElemSig(EnumValue(enum, _read_enum(enum.m_underlying_type, blob)))
            ),
        )

    is_array = kind == ElementType.SZArray
    if is_array:
        kind = blob.element_type()
    if not ElementType.Boolean <= kind <= ElementType.String:
        raise ValueError("a named argument must be a primitive, System.Type or an enum")
    name = blob.string()
    if is_array:
        return NamedArgSig(name, FixedArgSig(_read_array(kind, blob)))
    return NamedArgSig(name, FixedArgSig(ElemSig(_read_primitive(kind, blob))))
