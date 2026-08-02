# The shape of a `.winmd` file

What is actually in one of these files, from the first byte to a decoded signature.
[ECMA-335](https://ecma-international.org/publications-and-standards/standards/ecma-335/)
partition II is the standard this follows; this is the walk through it that reading
`Windows.Win32.winmd` and `Windows.Foundation.FoundationContract.winmd` with a hex editor
and this reader turned up. `docs/winmd-reader.md` is the companion piece about the C++
reader's interface; this one is about the bytes underneath both readers.

Written with [Claude](https://claude.com/claude-code).

## A PE file with nothing to run

A `.winmd` is a Windows executable that cannot be executed. It has the DOS stub, the PE
signature, an optional header and a section table, and then a section whose entire content
is metadata: no code, no imports, no entry point. The CLR would happily load it as an
assembly, and nothing would happen.

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
|    |  metadata root  <-- everything below is in | |
|    |                     here                   | |
|    +--------------------------------------------+ |
+--------------------------------------------------+
|  .reloc   a few bytes, because the format wants   |
|           a relocation section                    |
+--------------------------------------------------+
```

That is why a `.winmd` can be read on Linux and macOS as happily as on Windows: nothing in
it is loaded or called, it is parsed.

## From byte zero to the metadata

Four hops, each one an offset in the thing before it.

```
byte 0x3c            a 4 byte offset          -> the PE signature
PE + 0x18            the optional header      -> its 16 data directories
data directory #14   an RVA and a size        -> the CLI header
CLI header + 0x08    an RVA and a size        -> the metadata root
```

The addresses in the last two are **RVAs**, not file offsets: an RVA is an address in the
image once it is loaded, and turning one into a file offset means finding the section that
contains it and applying that section's difference between its virtual address and its
position in the file. A reader that maps the file has to do this by hand, because nothing
mapped it the way the loader would.

The CLI header is what makes the file managed. It carries the runtime version, some flags,
and the pointer to the metadata; the rest of its fields - entry point, resources, strong
name signature - are empty in a `.winmd`.

## The metadata root and its streams

```
+---------------------------------------------------------+
| "BSJB"    signature                                      |
| major, minor, reserved                                   |
| length + version string   e.g. "v4.0.30319"              |
| flags, stream count                                      |
+---------------------------------------------------------+
| offset, size, "#~"        \                              |
| offset, size, "#Strings"   |  one header per stream,     |
| offset, size, "#US"        |  each offset relative to    |
| offset, size, "#GUID"      |  the "BSJB" above           |
| offset, size, "#Blob"     /                              |
+---------------------------------------------------------+
| the streams themselves, in whatever order                |
+---------------------------------------------------------+
```

Each stream is a flat region with a name, and the name says how to read it:

| Stream | What is in it |
| --- | --- |
| `#~` | the tables. This is the metadata; everything else is storage the tables point into |
| `#Strings` | names: UTF-8, NUL terminated, referred to by byte offset |
| `#Blob` | length-prefixed byte strings: signatures, and the arguments of custom attributes |
| `#GUID` | 16 byte values, referred to by a **one-based index** rather than an offset |
| `#US` | user strings, the operands of `ldstr`. A `.winmd` has no code, so this is empty |

The stream names are NUL terminated and padded so the next header starts on a four byte
boundary, which is worth knowing if you are stepping through by hand.

## `#~`: the tables

```
+---------------------------------------------------------+
| reserved (0)                                     4 bytes |
| major, minor version                             2 bytes |
| HeapSizes                                        1 byte  |  <- how wide heap offsets are
| reserved (1)                                     1 byte  |
| Valid                                            8 bytes |  <- which tables are here
| Sorted                                           8 bytes |  <- which of them are ordered
+---------------------------------------------------------+
| row count of the first present table             4 bytes |
| row count of the next one                        4 bytes |
| ... one per bit set in Valid                             |
+---------------------------------------------------------+
| the rows of the first table, back to back                |
| the rows of the next table, back to back                 |
| ...                                                      |
+---------------------------------------------------------+
```

Three things to notice.

**`Valid` is a bitmap over the table numbers.** The standard defines a table for each of a
fixed set of numbers - `Module` is 0, `TypeRef` is 1, `TypeDef` is 2, and so on. A file
carries only the tables it needs, and only those have a bit set, a row count, and rows. The
tables appear in ascending order of their number, with nothing in between.

**`HeapSizes` is three bits.** Bit 0 says `#Strings` offsets are four bytes rather than
two, bit 1 says the same for `#GUID`, bit 2 for `#Blob`. A file whose string heap fits in
65,536 bytes can spell every name offset in two.

**There is no table of contents.** The rows begin immediately after the last row count,
and the only way to find the second table is to know how big a row of the first one is and
multiply. Which brings us to the part that makes metadata awkward.

## A row is not a fixed size

The standard gives every table a fixed list of columns, but not fixed widths. Three rules
decide how wide a column is, and all three depend on the file being read:

1. **A heap offset** is 2 or 4 bytes, from the `HeapSizes` bits above.
2. **An index into a table** is 2 bytes if that table has fewer than 65,536 rows, and 4
   otherwise.
3. **A coded index** - a column that can point into any of several tables - is 2 bytes if
   every one of those tables is small enough to fit alongside the tag bits, and 4
   otherwise.

So the same table is a different size in every file. `TypeDef` has six columns everywhere,
but:

```
Windows.Win32.winmd                          24 bytes per row   <IIIIII
Windows.Foundation.FoundationContract.winmd  14 bytes per row   <IHHHHH
```

The Win32 metadata is large enough that every one of those columns needs four bytes; a
single WinRT contract needs four only for the flags, which are four by definition.

This is the whole difficulty of reading metadata, and the reason a reader cannot be a set
of `struct` declarations. It has to:

```
read the row counts of every present table
    -> work out how wide each column of each table is
        -> add them up to get the size of a row
            -> add those up to find where each table starts
                -> only now can it read row N of table T
```

In this repository that walk is [`database`'s layout
pass](../src/winmd/reader.py), which lists the columns of all
thirty-eight tables the way the C++ reader's `database.h` does, and turns each into an
offset, a width, and a `struct` format string for the row.

## Pointing at things

### A simple index

A column that always points at one table holds a **one-based row number**, so that zero
can mean "nothing". `Field.Parent` is not stored at all - see lists, below - but
`ImplMap.ImportScope` is a plain index into `ModuleRef`, and reading it means subtracting
one.

### A coded index

A column that can point at one of several tables packs the two together: the low bits are
a **tag** saying which table, the rest is the one-based row number.

```
   value = 801
   binary  0b11 0010 0001
                       ^^  tag, 2 bits wide for a TypeDefOrRef
           \--------/      row + 1

   tag 01  -> TypeRef          (00 is TypeDef, 10 is TypeSpec)
   801 >> 2 = 200 -> TypeRef[199]
```

The tag is as wide as it needs to be for the list of tables that kind can name, and the
list is fixed by the standard - including the holes:

| Kind | Tag bits | The tables its tag can name |
| --- | --- | --- |
| `TypeDefOrRef` | 2 | TypeDef, TypeRef, TypeSpec |
| `HasConstant` | 2 | Field, Param, Property |
| `HasFieldMarshal` | 1 | Field, Param |
| `MemberRefParent` | 3 | TypeDef, TypeRef, ModuleRef, MethodDef, TypeSpec |
| `CustomAttributeType` | 3 | *(unused)*, *(unused)*, MethodDef, MemberRef, *(unused)* |
| `HasCustomAttribute` | 5 | twenty-two of them, from MethodDef to MethodSpec |

`CustomAttributeType` is the one worth staring at. It names two tables but its tags run
from 0 to 4, three of which the standard reserves and never assigns, so the tag needs three
bits and `MethodDef` is tag 2 rather than tag 0. A reader that counted the tables instead
of reading the standard would size this column at one bit and decode every custom attribute
wrongly.

That width is also what decides whether the column is two or four bytes: with five bits of
tag, a `HasCustomAttribute` column has eleven bits left for the row number in a two byte
column, so as soon as any one of the tables it can name reaches 2,048 rows, every such
column in the file becomes four.

## Lists, which have no end

`TypeDef` has a `FieldList` column and a `MethodList` column, and each holds the row where
that type's fields begin. There is no count and no end marker. The end is **where the next
row's list begins**:

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

Two consequences. The rows of `Field` cannot be reordered without rewriting every
`TypeDef`, and asking a `Field` which type owns it means searching `TypeDef` for the row
whose run contains it - the arrow only points one way. The last row of `TypeDef` runs to
the end of `Field`.

`TypeDef.MethodList`, `MethodDef.ParamList`, `PropertyMap.PropertyList` and
`EventMap.EventList` all work exactly this way.

## The heaps

### `#Strings`

One long run of NUL terminated UTF-8, starting with an empty string so that offset 0 means
"no name". A column holds the byte offset of the first character; reading it means scanning
to the next NUL.

```
   00 44 33 44 31 32 5f 52 45 53 4f 55 52 43 45 5f 53 54 41 54 45 ...
   ^  ^
   |  offset 1: "D3D12_RESOURCE_STATE_..."
   offset 0: ""
```

Nothing says how long the string is, and nothing prevents two names from sharing a
suffix - a compiler is free to store `Length` at the offset of the last five bytes of
`ByteLength`.

### `#Blob`, and compressed integers

A blob is a length, then that many bytes. The length is a **compressed unsigned integer**,
and so is nearly every number inside a signature. The first byte says how wide it is:

```
   0xxxxxxx                                 1 byte,  values up to 0x7f
   10xxxxxx yyyyyyyy                        2 bytes, values up to 0x3fff
   110xxxxx yyyyyyyy zzzzzzzz wwwwwwww      4 bytes, values up to 0x1fffffff
```

so small numbers - which is most of them - cost one byte. The decoding is
[`uncompress_unsigned`](../src/winmd/reader.py) and it is worth reading; it
is six lines and the whole `#Blob` stream is built on it.

### A signature, byte by byte

`MessageBoxW`'s signature column points at a blob that starts:

```
   00 04 11 9a d9 11 25 11 05 11 ...
   |  |  |  \---/
   |  |  |    the compressed value 0x9ad9 -> 0x1ad9 -> 6873
   |  |  |    as a TypeDefOrRef: 6873 >> 2 = 1718, tag 1 -> TypeRef[1717]
   |  |  ELEMENT_TYPE_VALUETYPE
   |  four parameters
   the calling convention: DEFAULT
```

and continues with one type per parameter in the same shape. Every type in metadata is
written this way: a one byte `ELEMENT_TYPE_*` tag, followed by whatever that tag needs -
nothing at all for `I4` or `STRING`, a compressed coded index for `CLASS` and `VALUETYPE`,
a nested type for `SZARRAY` and `PTR`, a type and its arguments for `GENERICINST`.

Signatures are the one part of metadata that is not a table: they are a small recursive
grammar, they can only be read front to back, and they are why a reader needs a cursor over
bytes rather than a row offset.

### `#GUID` and `#US`

`#GUID` is an array of sixteen byte values indexed from one; a `.winmd` normally holds just
the module's MVID. `#US` is where `ldstr` operands would live, and a file with no code has
none.

## Sorted, and what it buys

The `Sorted` bitmap says which tables are ordered by the column that points at their owner.
This is what makes the metadata searchable rather than merely readable:

- **`CustomAttribute`** is sorted by its `Parent` coded index, so every attribute on a type
  is one binary search followed by a walk.
- **`Constant`**, **`FieldMarshal`**, **`ImplMap`**, **`NestedClass`**,
  **`InterfaceImpl`**, **`ClassLayout`**, **`FieldLayout`** and the rest of the
  parent-keyed tables are the same.
- **`TypeDef`**, **`MethodDef`**, **`Field`** and the other definition tables are *not*
  sorted, and never claim to be: their order is the order things were declared, and it is
  the order the list columns above depend on.

One caveat that this reader and the C++ one both carry: `PropertyMap` and `EventMap` are
marked sorted by some producers and are not in fact sorted, so both readers search them
linearly. `README.md` lists it under "Things that will bite".

## Putting it together

Finding `MessageBoxW` and its DLL touches most of the above:

```
#Strings  "Apis"          -> the TypeDef row for the namespace's static class
TypeDef   MethodList      -> a run of MethodDef rows
MethodDef Name            -> #Strings, matched against "MessageBoxW"
MethodDef Signature       -> #Blob, decoded as above into a return type and parameters
MethodDef ParamList       -> a run of Param rows, for the names the signature does not have
ImplMap   MemberForwarded -> a coded index back at that MethodDef, found by binary search
ImplMap   ImportName      -> #Strings, "MessageBoxW"
ImplMap   ImportScope     -> ModuleRef -> #Strings, "USER32.dll"
```

The type of a parameter comes from the signature and its name from a `Param` row, and the
two are matched by `Param.Sequence()` counting from one, where zero is the return value.
Nothing points from a `MethodDef` to its `ImplMap`; the arrow runs the other way, which is
why the last three lines are a search rather than a lookup.

## Where this lives in the code

| The format | This repository |
| --- | --- |
| the PE and CLI headers | `database.__init__` |
| the streams | `database`, which copies each heap out once |
| row counts, column widths, row sizes | `database`'s layout pass |
| the tables and their columns | `TableNumber` and the row classes |
| coded indexes | the `coded_index_*` classes |
| compressed integers, blobs, signatures | `byte_view` and the `*Sig` classes |

`examples/dump.py` prints all of it as C#-like source, and `examples/dumpwin32.py` as
C-like declarations.
