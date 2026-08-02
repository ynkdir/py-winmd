# The shape of a `.winmd` file

Enough of the format to write a reader against, from the first byte to a decoded signature.
[ECMA-335](https://ecma-international.org/publications-and-standards/standards/ecma-335/)
partition II is the standard, and is the place to go for anything not here; this is the
working subset a `.winmd` actually uses, in the order a parser needs it, with the byte
layouts and the full tables written out. `docs/winmd-reader.md` is the companion piece
about the C++ reader's interface; this one is about the bytes underneath it.

Everything here was checked against `Windows.Win32.winmd` and
`Windows.Foundation.FoundationContract.winmd`, and the tables were generated from the
schema this repository's reader is built on.

Written with [Claude](https://claude.com/claude-code).

## Contents

- [The order to read it in](#the-order-to-read-it-in)
- [The PE wrapper](#the-pe-wrapper)
- [The CLI header](#the-cli-header)
- [The metadata root and its streams](#the-metadata-root-and-its-streams)
- [The `#~` header](#the--header)
- [How wide is a column](#how-wide-is-a-column)
- [The tables](#the-tables)
- [The coded indexes](#the-coded-indexes)
- [Heaps](#heaps)
- [Signatures](#signatures)
- [Constants](#constants)
- [Custom attribute values](#custom-attribute-values)
- [Lists, and the arrows that only point one way](#lists-and-the-arrows-that-only-point-one-way)
- [Sorted tables](#sorted-tables)
- [A worked read](#a-worked-read)
- [Pitfalls](#pitfalls)
- [Where this lives in the code](#where-this-lives-in-the-code)

## The order to read it in

A `.winmd` is a Windows executable that cannot be executed: it has a PE wrapper and a
section whose entire content is metadata - no code, no imports, no entry point. That is why
it can be read on any platform. Nothing in it is loaded or called, it is parsed.

Nothing in the file can be found without the thing before it, so a reader has no choice
about the order:

```
 1. byte 0x3c holds the offset of the PE signature
 2. the optional header's data directory 14 gives the CLI header, as an RVA
 3. the section table turns that RVA into a file offset
 4. the CLI header gives the metadata root, again as an RVA
 5. the metadata root lists the streams: #~, #Strings, #US, #GUID, #Blob
 6. the #~ header gives HeapSizes, which tables are present, and their row counts
 7. only now can column widths be computed - they depend on 6
 8. row sizes follow from the widths, and table offsets from the row sizes
 9. only now can row N of table T be read
10. what a row points at is a heap offset, a row number, or a signature blob
```

Steps 6 to 8 are the part that makes metadata different from most binary formats. There is
no table of contents and no fixed row size: the shape of the file is computed from the file.

```
+--------------------------------------------------+  0
|  MZ  DOS header, and the stub that prints         |
|      "This program cannot be run in DOS mode"     |
+--------------------------------------------------+  the offset at 0x3c
|  PE\0\0  COFF header      (machine, sections)     |
|          optional header  (16 data directories)   |
|          section table                            |
+--------------------------------------------------+
|  .text                                            |
|    +--------------------------------------------+ |
|    |  CLI header                                | |
|    |  metadata root                             | |
|    |    #~        the tables                    | |
|    |    #Strings  names                         | |
|    |    #US       empty, there is no code        | |
|    |    #GUID     the module's MVID              | |
|    |    #Blob     signatures, attribute values   | |
|    +--------------------------------------------+ |
+--------------------------------------------------+
|  .reloc   a few bytes, because the format wants   |
|           a relocation section                    |
+--------------------------------------------------+
```

## The PE wrapper

Offsets are from the start of the structure unless said otherwise. Everything is
little-endian, everywhere, all the way down.

**Finding the PE header.** The file starts with `MZ`. At **0x3c** is a four byte offset,
and at that offset is `PE\0\0`. Call that offset `pe`.

**COFF header**, at `pe + 4`, 20 bytes:

| Offset | Size | Field | Why you care |
| --- | --- | --- | --- |
| 0 | 2 | Machine | 0x014c is i386, 0x8664 is x64. A `.winmd` is usually 0x014c whatever it describes |
| 2 | 2 | NumberOfSections | how many section headers follow the optional header |
| 4 | 4 | TimeDateStamp | |
| 8 | 4 | PointerToSymbolTable | |
| 12 | 4 | NumberOfSymbols | |
| 16 | 2 | SizeOfOptionalHeader | where the section table starts |
| 18 | 2 | Characteristics | |

**Optional header**, at `pe + 24`. Only three things in it matter:

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 2 | Magic: **0x10b** is PE32, **0x20b** is PE32+ |
| 92 (PE32) / 108 (PE32+) | 4 | NumberOfRvaAndSizes |
| 96 (PE32) / 112 (PE32+) | 8 each | the data directories |

The magic is what decides the two offsets, because PE32+ widens several fields before them.
Data directory **14** (counting from zero) is the CLI header: four bytes of RVA, four of
size.

**Section table**, at `pe + 24 + SizeOfOptionalHeader`, 40 bytes per section:

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 8 | Name, NUL padded |
| 8 | 4 | VirtualSize |
| 12 | 4 | VirtualAddress - the section's RVA |
| 16 | 4 | SizeOfRawData |
| 20 | 4 | PointerToRawData - the section's file offset |
| 24 | 16 | relocations, line numbers, characteristics |

**Turning an RVA into a file offset.** An RVA is an address in the image once the loader
has spread the sections out in memory; a parser has the file, not the image. Find the
section whose `[VirtualAddress, VirtualAddress + VirtualSize)` contains the RVA, and:

```
file offset = rva - section.VirtualAddress + section.PointerToRawData
```

Every RVA in the file needs this, and there are only two that matter: the CLI header and the
metadata root.

## The CLI header

At the RVA from data directory 14, 72 bytes:

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 4 | Cb - the size of this header, 72 |
| 4 | 2 | MajorRuntimeVersion |
| 6 | 2 | MinorRuntimeVersion |
| **8** | **8** | **MetaData: RVA and size** |
| 16 | 4 | Flags |
| 20 | 4 | EntryPointToken |
| 24 | 8 | Resources |
| 32 | 8 | StrongNameSignature |
| 40 | 8 | CodeManagerTable |
| 48 | 8 | VTableFixups |
| 56 | 8 | ExportAddressTableJumps |
| 64 | 8 | ManagedNativeHeader |

The presence of this header is what makes the file managed. In a `.winmd` everything after
`Flags` is zero.

## The metadata root and its streams

At the RVA in `MetaData`. Call its file offset `root`; **every stream offset below is
relative to `root`**, not to the file.

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 4 | Signature: `0x424a5342`, the bytes `BSJB` |
| 4 | 2 | MajorVersion |
| 6 | 2 | MinorVersion |
| 8 | 4 | Reserved |
| 12 | 4 | Length of the version string, including its NUL, rounded up to a multiple of 4 |
| 16 | Length | Version, e.g. `v4.0.30319` |
| 16+Length | 2 | Flags |
| 18+Length | 2 | Number of streams |
| 20+Length | | the stream headers |

**Stream header**, one per stream:

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 4 | Offset from `root` |
| 4 | 4 | Size |
| 8 | | Name, NUL terminated, then padded with NULs to a multiple of 4 |

The padding is the part that trips up a hand-written walk: after the terminating NUL,
advance to the next four byte boundary before reading the next header.

| Stream | What is in it |
| --- | --- |
| `#~` | the tables. This is the metadata; the rest is storage the tables point into |
| `#Strings` | names: UTF-8, NUL terminated, addressed by byte offset |
| `#Blob` | length-prefixed byte strings: signatures, and attribute arguments |
| `#GUID` | 16 byte values, addressed by a **one-based index** rather than an offset |
| `#US` | user strings, the operands of `ldstr`. A `.winmd` has no code, so this is empty |

A file may also carry `#-` instead of `#~`, which is the uncompressed, edit-and-continue
form. `.winmd` files do not; a reader that meets one can refuse.

## The `#~` header

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 4 | Reserved, 0 |
| 4 | 1 | MajorVersion |
| 5 | 1 | MinorVersion |
| **6** | **1** | **HeapSizes** |
| 7 | 1 | Reserved, 1 |
| **8** | **8** | **Valid** - a bitmap of the tables present |
| 16 | 8 | Sorted - a bitmap of the tables that are ordered |
| 24 | 4 each | one row count per bit set in `Valid`, in ascending table number |
| ... | | the rows themselves, table by table, in the same order |

**HeapSizes** is three bits, and each says a heap's offsets are four bytes rather than two:

```
bit 0 (0x01)   #Strings
bit 1 (0x02)   #GUID
bit 2 (0x04)   #Blob
```

**Valid** is indexed by table number: bit *n* is set when table *n* is present. Tables
appear in ascending order of number with nothing between them, so the row counts arrive in
that order too, and the rows after them.

## How wide is a column

Every column is one of five kinds, and only the first has a width the standard states
outright:

| Kind | Width |
| --- | --- |
| a fixed integer | as the table says: 1, 2, 4 or 8 bytes |
| a `#Strings` offset | 2, or 4 if `HeapSizes & 0x01` |
| a `#GUID` index | 2, or 4 if `HeapSizes & 0x02` |
| a `#Blob` offset | 2, or 4 if `HeapSizes & 0x04` |
| an index into table *T* | 2 if `rows(T) < 65536`, else 4 |
| a coded index of kind *K* | 2 if every table *K* names has `rows < (1 << (16 - bits(K)))`, else 4 |

The coded index rule is the one to get right. A coded index spends `bits(K)` of its value on
the tag, so a two byte column has `16 - bits(K)` left for the row number; if any table the
kind can name has more rows than that can address, every column of that kind in the file
becomes four bytes. With `HasCustomAttribute` at five tag bits, that threshold is 2,048 rows.

So the same table is a different size in every file:

```
Windows.Win32.winmd                          TypeDef is 24 bytes per row   <IIIIII
Windows.Foundation.FoundationContract.winmd  TypeDef is 14 bytes per row   <IHHHHH
```

and a reader has to compute, in this order:

```
row counts  ->  column widths  ->  row size per table  ->  where each table starts
```

The last step is a running sum: table *n* starts where table *n-1* ended, the first starts
after the row counts.

## The tables

All thirty-eight, by number. `str` is a `#Strings` offset, `blob` a `#Blob` offset, `guid` a
`#GUID` index, `→T` an index into table T, and `«K»` a coded index of kind K. A number is
that many bytes of plain integer.

| # | Table | Columns |
| --- | --- | --- |
| 0x00 | Module | 2 Generation, str Name, guid Mvid, guid EncId, guid EncBaseId |
| 0x01 | TypeRef | «ResolutionScope» ResolutionScope, str TypeName, str TypeNamespace |
| 0x02 | TypeDef | 4 Flags, str TypeName, str TypeNamespace, «TypeDefOrRef» Extends, →Field FieldList, →MethodDef MethodList |
| 0x04 | Field | 2 Flags, str Name, blob Signature |
| 0x06 | MethodDef | 4 RVA, 2 ImplFlags, 2 Flags, str Name, blob Signature, →Param ParamList |
| 0x08 | Param | 2 Flags, 2 Sequence, str Name |
| 0x09 | InterfaceImpl | →TypeDef Class, «TypeDefOrRef» Interface |
| 0x0a | MemberRef | «MemberRefParent» Class, str Name, blob Signature |
| 0x0b | Constant | 2 Type, «HasConstant» Parent, blob Value |
| 0x0c | CustomAttribute | «HasCustomAttribute» Parent, «CustomAttributeType» Type, blob Value |
| 0x0d | FieldMarshal | «HasFieldMarshal» Parent, blob NativeType |
| 0x0e | DeclSecurity | 2 Action, «HasDeclSecurity» Parent, blob PermissionSet |
| 0x0f | ClassLayout | 2 PackingSize, 4 ClassSize, →TypeDef Parent |
| 0x10 | FieldLayout | 4 Offset, →Field Field |
| 0x11 | StandAloneSig | blob Signature |
| 0x12 | EventMap | →TypeDef Parent, →Event EventList |
| 0x14 | Event | 2 EventFlags, str Name, «TypeDefOrRef» EventType |
| 0x15 | PropertyMap | →TypeDef Parent, →Property PropertyList |
| 0x17 | Property | 2 Flags, str Name, blob Type |
| 0x18 | MethodSemantics | 2 Semantics, →MethodDef Method, «HasSemantics» Association |
| 0x19 | MethodImpl | →TypeDef Class, «MethodDefOrRef» MethodBody, «MethodDefOrRef» MethodDeclaration |
| 0x1a | ModuleRef | str Name |
| 0x1b | TypeSpec | blob Signature |
| 0x1c | ImplMap | 2 MappingFlags, «MemberForwarded» MemberForwarded, str ImportName, →ModuleRef ImportScope |
| 0x1d | FieldRVA | 4 RVA, →Field Field |
| 0x20 | Assembly | 4 HashAlgId, 8 Version, 4 Flags, blob PublicKey, str Name, str Culture |
| 0x21 | AssemblyProcessor | 4 Processor |
| 0x22 | AssemblyOS | 4 OSPlatformID, 4 OSMajorVersion, 4 OSMinorVersion |
| 0x23 | AssemblyRef | 8 Version, 4 Flags, blob PublicKeyOrToken, str Name, str Culture, blob HashValue |
| 0x24 | AssemblyRefProcessor | 4 Processor, →AssemblyRef AssemblyRef |
| 0x25 | AssemblyRefOS | 4 OSPlatformId, 4 OSMajorVersion, 4 OSMinorVersion, →AssemblyRef AssemblyRef |
| 0x26 | File | 4 Flags, str Name, blob HashValue |
| 0x27 | ExportedType | 4 Flags, 4 TypeDefId, str TypeName, str TypeNamespace, «Implementation» Implementation |
| 0x28 | ManifestResource | 4 Offset, 4 Flags, str Name, «Implementation» Implementation |
| 0x29 | NestedClass | →TypeDef NestedClass, →TypeDef EnclosingClass |
| 0x2a | GenericParam | 2 Number, 2 Flags, «TypeOrMethodDef» Owner, str Name |
| 0x2b | MethodSpec | «MethodDefOrRef» Method, blob Instantiation |
| 0x2c | GenericParamConstraint | →GenericParam Owner, «TypeDefOrRef» Constraint |

Numbers 0x03, 0x05, 0x07, 0x13, 0x16, 0x1e, 0x1f and everything above 0x2c are unassigned.
`Assembly.Version` and `AssemblyRef.Version` are four `uint16` fields - major, minor, build,
revision - which a reader may as well take as eight bytes and split. `Constant.Type` is one
byte of type plus one of padding, read as two.

A `.winmd` uses a small part of this. Win32 metadata carries no `Property`, `Event`,
`MethodImpl` or `GenericParam` at all; WinRT metadata carries all of them and no `ImplMap`.

## The coded indexes

A coded index packs a tag and a one-based row number into one value:

```
   value = (row + 1) << bits  |  tag
   row   = (value >> bits) - 1
   tag   = value & ((1 << bits) - 1)
```

A value of 0 means "nothing": tag 0, row 0, and row numbers are one-based so no real row is
0. The tag list is fixed by the standard, **including its holes**, and the number of bits
follows from the length of that list - not from the number of tables in it.

| Kind | Bits | Tags |
| --- | --- | --- |
| `TypeDefOrRef` | 2 | 0 TypeDef, 1 TypeRef, 2 TypeSpec |
| `HasConstant` | 2 | 0 Field, 1 Param, 2 Property |
| `HasCustomAttribute` | 5 | 0 MethodDef, 1 Field, 2 TypeRef, 3 TypeDef, 4 Param, 5 InterfaceImpl, 6 MemberRef, 7 Module, 8 DeclSecurity, 9 Property, 10 Event, 11 StandAloneSig, 12 ModuleRef, 13 TypeSpec, 14 Assembly, 15 AssemblyRef, 16 File, 17 ExportedType, 18 ManifestResource, 19 GenericParam, 20 GenericParamConstraint, 21 MethodSpec |
| `HasFieldMarshal` | 1 | 0 Field, 1 Param |
| `HasDeclSecurity` | 2 | 0 TypeDef, 1 MethodDef, 2 Assembly |
| `MemberRefParent` | 3 | 0 TypeDef, 1 TypeRef, 2 ModuleRef, 3 MethodDef, 4 TypeSpec |
| `HasSemantics` | 1 | 0 Event, 1 Property |
| `MethodDefOrRef` | 1 | 0 MethodDef, 1 MemberRef |
| `MemberForwarded` | 1 | 0 Field, 1 MethodDef |
| `Implementation` | 2 | 0 File, 1 AssemblyRef, 2 ExportedType |
| `CustomAttributeType` | 3 | 0 *unused*, 1 *unused*, **2 MethodDef**, 3 MemberRef, 4 *unused* |
| `ResolutionScope` | 2 | 0 Module, 1 ModuleRef, 2 AssemblyRef, 3 TypeRef |
| `TypeOrMethodDef` | 1 | 0 TypeDef, 1 MethodDef |

`CustomAttributeType` is the one to be careful with: two usable tags out of five, so three
bits, and `MethodDef` is tag **2**. A reader that sized the tag from the number of tables
would use one bit and misread every custom attribute in the file.

**One exception to the sizing rule.** `HasCustomAttribute` names twenty-two tables, but the
width of the column is computed from twenty-one of them: `DeclSecurity` is left out.
Microsoft's own reader does this, and matching it matters, because including a large
`DeclSecurity` would widen every attribute column and put every row after it at the wrong
offset.

Worked decode, an `Extends` column holding 801:

```
   801 = 0b11 0010 0001
                     ^^   tag = 01 = TypeRef
         \--------/       801 >> 2 = 200, minus one -> TypeRef[199]
```

## Heaps

### `#Strings`

One run of NUL terminated UTF-8, beginning with an empty string so that offset 0 can mean
"no name". A column holds the byte offset of the first character; read to the next NUL.

```
   00 44 33 44 31 32 5f 52 45 53 4f 55 52 43 45 5f ...
   ^  ^
   |  offset 1: "D3D12_RESOURCE_..."
   offset 0: ""
```

Nothing says how long a string is, and nothing stops a producer from overlapping them: a
name that is the suffix of another may be stored as an offset into the middle of it. Do not
assume the offsets partition the heap.

### `#GUID`

A plain array of 16 byte values, addressed by a **one-based index**: index 1 is at offset 0,
index 2 at offset 16. Index 0 means "none". This is the only heap addressed by index rather
than by byte offset, and getting it wrong is a common first bug.

### `#Blob`

A blob is a compressed length followed by that many bytes. Offset 0 is a zero-length blob.

**Compressed unsigned integers** are how the length and nearly every number inside a
signature are spelled. The top bits of the first byte say how wide the value is:

| First byte | Bytes | Value |
| --- | --- | --- |
| `0xxxxxxx` | 1 | the low 7 bits |
| `10xxxxxx` | 2 | the low 6 bits, then 8 more - up to 0x3fff |
| `110xxxxx` | 4 | the low 5 bits, then 24 more - up to 0x1fffffff |

Anything else is malformed. The standard also defines a *signed* compressed integer, which
rotates the sign bit to the bottom; it appears only in array shapes, and a reader that does
not decode `ELEMENT_TYPE_ARRAY` never needs it.

### `#US`

Where the operands of `ldstr` would live. A file with no code has none, and a `.winmd` has
no code.

## Signatures

Signatures are the part of metadata that is not a table: a small recursive grammar, written
into `#Blob`, readable only front to back. Every signature but a `TypeSpec` starts with a
one byte calling convention. Its **low four bits** - mask `0x0f` - say which kind of
signature this is:

| Low nibble | Kind | Then |
| --- | --- | --- |
| 0x00 | DEFAULT | param count, return type, that many params |
| 0x01-0x04 | C, STDCALL, THISCALL, FASTCALL | the same; these appear in FNPTR types |
| 0x05 | VARARG | the same, with a SENTINEL before the variable part |
| 0x06 | FIELD | one type, and nothing else |
| 0x07 | LOCALSIG | a count, then that many types |
| 0x08 | PROPERTY | a count, the property's type, then the index parameters |

and the **high bits** are flags or-ed on top:

| Flag | Meaning |
| --- | --- |
| 0x10 | GENERIC: a compressed generic parameter count comes before the parameter count |
| 0x20 | HASTHIS: the method takes an instance |
| 0x40 | EXPLICITTHIS: `this` is spelled out as the first parameter |

so a WinRT instance property is `0x28`, and a generic method is `0x10` or-ed into `0x00`.
A `TypeSpec` blob has no convention byte at all: it is a bare type. `MethodSpec.Instantiation`
is a signature of its own kind, listing the type arguments of one generic call; this reader
does not decode it, and ECMA-335 II.23.2.15 has the layout.

### Types

A type is a one byte `ELEMENT_TYPE_*` tag and whatever that tag needs:

| Tag | Name | Followed by |
| --- | --- | --- |
| 0x01 | VOID | - |
| 0x02 | BOOLEAN | - |
| 0x03 | CHAR | - |
| 0x04-0x0b | I1 U1 I2 U2 I4 U4 I8 U8 | - |
| 0x0c, 0x0d | R4, R8 | - |
| 0x0e | STRING | - |
| 0x0f | PTR | a type |
| 0x10 | BYREF | a type |
| 0x11 | VALUETYPE | a compressed `TypeDefOrRef` coded index |
| 0x12 | CLASS | a compressed `TypeDefOrRef` coded index |
| 0x13 | VAR | a compressed number: the type's own generic parameter |
| 0x14 | ARRAY | a type, then a shape: rank, sizes, lower bounds |
| 0x15 | GENERICINST | CLASS or VALUETYPE, a coded index, an argument count, then the arguments |
| 0x16 | TYPEDBYREF | - |
| 0x18, 0x19 | I, U | native int, native unsigned int |
| 0x1b | FNPTR | a method signature |
| 0x1c | OBJECT | - |
| 0x1d | SZARRAY | a type - a vector, which is what nearly every array in metadata is |
| 0x1e | MVAR | a compressed number: the method's own generic parameter |
| 0x1f, 0x20 | CMOD_REQD, CMOD_OPT | a coded index, then the type being modified |
| 0x41 | SENTINEL | marks the start of varargs |
| 0x45 | PINNED | a type |

The custom modifiers are prefixes: a parameter may be `CMOD_OPT <index> CMOD_OPT <index>
I4`, and a reader has to loop over them before it reaches the type. `const` in Win32
metadata arrives this way.

### One signature, byte by byte

`MessageBoxW`'s `MethodDef.Signature` column points at a blob beginning:

```
   00 04 11 9a d9 11 25 11 05 11 ...
   |  |  |  \---/
   |  |  |    compressed: 0x9ad9 & 0x3fff = 0x1ad9 = 6873
   |  |  |    as TypeDefOrRef: 6873 >> 2 = 1718 -> TypeRef[1717]
   |  |  ELEMENT_TYPE_VALUETYPE - the return type
   |  four parameters follow the return type
   the calling convention: DEFAULT, no HASTHIS
```

and continues with one type per parameter in the same shape.

**The names are not here.** A signature has types and no names; the names are `Param` rows,
reached from `MethodDef.ParamList`, and matched to the signature by `Param.Sequence`
counting from one, where **zero is the return value**. Sequence numbers may be sparse - a
parameter with nothing to say about it may have no `Param` row at all.

## Constants

A `Constant` row points at whatever holds the value - a `Field`, a `Param` or a `Property` -
and holds the type and the bytes:

| `Constant.Type` | Value in the blob |
| --- | --- |
| 0x02 | BOOLEAN, one byte |
| 0x03 | CHAR, two bytes of UTF-16 |
| 0x04-0x0b | I1 U1 I2 U2 I4 U4 I8 U8, little-endian |
| 0x0c, 0x0d | R4, R8 |
| 0x0e | STRING: the blob is UTF-16, and its length is the blob's |
| 0x12 | CLASS: a null reference, and the blob is four zero bytes |

The blob's own length says how many bytes to read, so a string constant needs no terminator.
This is how an enum's members carry their values, and how a Win32 `#define` survives into
metadata.

## Custom attribute values

`CustomAttribute.Value` is a blob whose shape depends on the constructor the row's `Type`
column points at, so it cannot be decoded alone: read the constructor's signature first, and
the fixed arguments are its parameters, in order.

```
   01 00                     prolog, always 0x0001
   <fixed args>              one per constructor parameter, no tags, no lengths
   <count : uint16>          how many named arguments follow
   <named args>              each: FIELD (0x53) or PROPERTY (0x54),
                             a type, a SerString name, then the value
```

A value is written flat: an `int32` is four bytes, a string is a **SerString** - a compressed
length then UTF-8, with a length of `0xff` meaning null - and an enum is its underlying
integer. A `System.Type` argument is a SerString holding the type's name. The count of named
arguments is a plain `uint16`, not compressed.

Nothing in the blob says how long it is or where the fixed arguments end; the constructor's
signature is the only thing that does.

## Lists, and the arrows that only point one way

`TypeDef.FieldList` holds the row where that type's fields begin. There is no count and no
terminator: the run ends where the **next row's** list begins, and the last row's run ends at
the end of the table.

```
   TypeDef                        Field
   +--------------------+         +----------+
   |  FieldList = 3     |-------->| Field[2] |  \
   +--------------------+         | Field[3] |   |  TypeDef[n] owns rows 2 to 4
   |  FieldList = 6     |---+     | Field[4] |  /
   +--------------------+   +---->| Field[5] |  \  TypeDef[n+1] owns 5 and 6
   |  FieldList = 8     |---+     | Field[6] |  /
   +--------------------+   +---->| Field[7] |     and TypeDef[n+2] starts here
                                  +----------+

   the column is one-based, so FieldList = 3 means Field[2],
   and a run ends one row before the next row's FieldList
```

The list columns are `TypeDef.FieldList`, `TypeDef.MethodList`, `MethodDef.ParamList`,
`PropertyMap.PropertyList` and `EventMap.EventList`.

Two consequences a parser has to live with. The target rows cannot be reordered without
rewriting every row that points into them. And there is no column pointing back: asking a
`Field` which type owns it means **searching** `TypeDef` for the row whose run contains it,
which is a binary search over a column that happens to be ascending. The same is true of
`Property` and `Event` through their maps.

## Sorted tables

The `Sorted` bitmap says which tables are ordered by the column that points at their owner.
That is what makes the metadata searchable rather than merely readable: an attribute lookup
is a binary search and a walk, not a scan.

| Table | Sorted by |
| --- | --- |
| CustomAttribute | Parent |
| Constant | Parent |
| FieldMarshal | Parent |
| DeclSecurity | Parent |
| ClassLayout | Parent |
| FieldLayout | Field |
| MethodSemantics | Association |
| MethodImpl | Class |
| ImplMap | MemberForwarded |
| FieldRVA | Field |
| NestedClass | NestedClass |
| GenericParam | Owner, then Number |
| GenericParamConstraint | Owner |
| InterfaceImpl | Class |

`TypeDef`, `MethodDef`, `Field`, `Param`, `Property` and `Event` are **not** sorted and do
not claim to be: their order is declaration order, and it is the order the list columns
depend on.

One caveat both this reader and Microsoft's carry: **`PropertyMap` and `EventMap` are
marked sorted by some producers and are not**, so a binary search over them silently misses
rows. Search them linearly.

## A worked read

Finding `MessageBoxW`, its signature and its DLL touches most of the format. In Win32
metadata the free functions of a namespace are the static methods of a type called `Apis`.

```
1. TypeDef      scan for TypeNamespace = "Windows.Win32.UI.WindowsAndMessaging"
                and TypeName = "Apis"            -> both are #Strings offsets
2. TypeDef      MethodList              -> the run of MethodDef rows for that type
3. MethodDef    Name                    -> #Strings, compared against "MessageBoxW"
4. MethodDef    Signature               -> #Blob, decoded as above: return type, 4 params
5. MethodDef    ParamList               -> the run of Param rows, for the names
6. Param        Sequence                -> matched to the signature, 0 is the return value
7. ImplMap      binary search MemberForwarded for the coded index of that MethodDef
8. ImplMap      ImportName              -> #Strings, "MessageBoxW"
9. ImplMap      ImportScope             -> ModuleRef -> Name -> "USER32.dll"
```

Step 7 is a search because nothing points from a `MethodDef` to its `ImplMap`; the arrow
runs the other way, and `ImplMap` is sorted so that the search is cheap.

## Pitfalls

A checklist of the things that are easy to get wrong, most of them silent:

- **`#GUID` is indexed from one**, and by index, not by byte offset.
- **Row numbers are one-based**, in both plain and coded indexes, so 0 means "nothing".
- **The tag width of a coded index counts reserved tags.** `CustomAttributeType` needs
  three bits for two tables.
- **`HasCustomAttribute` is sized without `DeclSecurity`**, or every row after the first
  attribute column lands at the wrong offset.
- **The version string and the stream names are padded** to four byte boundaries.
- **PE32 and PE32+ put the data directories in different places**; read the magic first.
- **A list column has no end** other than the next row's list, and the last row runs to the
  end of the table.
- **`PropertyMap` and `EventMap` may claim to be sorted and not be.**
- **A custom attribute blob cannot be decoded without its constructor's signature.**
- **Nothing bounds a `#Strings` entry** but its NUL, and entries may overlap.
- **Column widths are per file.** Nothing about a row's shape can be hard-coded.

## Where this lives in the code

| The format | This repository |
| --- | --- |
| the PE and CLI headers, the streams | `database.__init__` |
| row counts, column widths, row sizes, table offsets | `database`'s layout pass |
| the tables and their columns | `TableNumber` and the thirty-eight row classes |
| the coded indexes | the `coded_index_*` classes |
| compressed integers and blobs | `byte_view` |
| signatures | `MethodDefSig`, `FieldSig`, `TypeSig` and the rest |
| constants | `_constant_value` |
| attribute values | `CustomAttributeSig`, `FixedArgSig`, `NamedArgSig` |

`examples/dump.py` prints all of it as C#-like source and `examples/dumpwin32.py` as C-like
declarations, which between them exercise every part of the format described here.
