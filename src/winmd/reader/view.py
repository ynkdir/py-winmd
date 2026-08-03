"""A bounded view of bytes, as impl/winmd_reader/view.h has one.

The cursor every blob is read with: compressed integers, element types and the
compressed coded indexes a signature carries.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from .enum import ElementType

if TYPE_CHECKING:
    from .database import database
    from .index import CodedT


# --- blob reading ---------------------------------------------------------
def uncompress_unsigned(data: bytes, position: int) -> tuple[int, int]:
    first = data[position]
    if not first & 0x80:
        return first, position + 1
    if first & 0xC0 == 0x80:
        return ((first & 0x3F) << 8) | data[position + 1], position + 2
    if first & 0xE0 == 0xC0:
        return (
            ((first & 0x1F) << 24)
            | (data[position + 1] << 16)
            | (data[position + 2] << 8)
            | data[position + 3]
        ), position + 4
    raise ValueError("invalid compressed integer in blob")


class byte_view:
    """A bounded view of bytes, and the cursor every signature is read with.

    Named as the C++ names it: `as_uint32(offset)`, `seek(offset)` and
    `sub(offset, size)` do what they do there, and it is also a sequence of
    bytes, so `len()`, `[]` and `bytes()` work. A blob out of the #Blob heap
    is one of these, and knows the database it came from.
    """

    __slots__ = ("data", "position", "end", "table")

    def __init__(
        self,
        data: bytes,
        position: int = 0,
        size: int | None = None,
        table: database | None = None,
    ) -> None:
        self.data = data
        self.position = position
        self.end: int = position + (len(data) - position if size is None else size)
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
        return byte_view(
            self.data,
            self.position + offset,
            self.end - self.position - offset,
            self.table,
        )

    def sub(self, offset: int, size: int) -> byte_view:
        if offset < 0 or size < 0 or self.position + offset + size > self.end:
            raise ValueError("the sub view does not fit")
        return byte_view(self.data, self.position + offset, size, self.table)

    def as_bytes(self) -> bytes:
        return self.data[self.position : self.end]

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
        value = self.data[self.position : self.position + length].decode("utf-8")
        self.position += length
        return value

    def coded_index(self, kind: type[CodedT]) -> CodedT:
        """The next compressed value, as `coded_index_TypeDefOrRef` or such."""
        if self.table is None:
            raise RuntimeError("this blob does not know its database")
        return kind(self.table, self.unsigned())

    def __bool__(self) -> bool:
        return self.position < self.end

    # It is also just bytes, which is what the C++ offers.
    def __len__(self) -> int:
        return self.end - self.position

    def __bytes__(self) -> bytes:
        return self.data[self.position : self.end]

    def __getitem__(self, index: int | slice) -> int | bytes:
        if isinstance(index, slice):
            return bytes(self)[index]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return self.data[self.position + index]
