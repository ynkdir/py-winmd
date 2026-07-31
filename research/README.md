# A pure Python reader, measured against the bindings

> This is the measurement that decided it. The pure Python reader is now the
> library, in `python/winmd/reader.py`, and the nanobind bindings it is compared
> with here were removed; the C++ reader remains as what the tests check
> against, through `tests/reference.cpp`. The scripts that needed the bindings
> went with them - `optimize.py` and `columns.py`, which only need the reader,
> are still here and still run.

What it costs to read `.winmd` in Python alone, instead of binding the C++
reader. Measured on this machine against the real metadata, not a synthetic
file: `Windows.Win32.winmd` (23.2 MB, 37,311 types), the Windows SDK contracts,
and the WinRT metadata of the running system (20 files, 6.6 MB). Python 3.14,
MSVC build of the extension.

```
research/purewinmd.py   the reader
research/agree.py       describes every type with both readers and compares
research/bench.py       the same tasks through both
research/optimize.py    where the time goes and what moves it
research/columns.py     column oriented decoding, with and without numpy
research/caching.py     saving the parse instead of doing it again
research/startup.py     what each reader costs before it reads anything
```

## What is implemented

All of it, in 1,547 lines of code:

- PE to CLI header to metadata root, the `#Strings`, `#Blob` and `#GUID` heaps
- the 38 tables, their schemas, the heap index widths and the coded index
  sizing rules, with rows that carry the same accessors as the C++ ones
- the 13 coded indexes, with the tag order the standard gives them
- member lists (`FieldList`, `MethodList`, `ParamList`, `PropertyList`,
  `EventList`, `InterfaceImpl`, `GenericParam`, `MethodImplList`) and the back
  references that have no column (`Parent`, `Constant`, `CustomAttribute`,
  `EnclosingType`, `MethodSemantic`)
- the flag structs: `TypeAttributes`, `MethodAttributes`, `FieldAttributes`,
  `ParamAttributes`, `PropertyAttributes`, `EventAttributes`,
  `MethodImplAttributes`, `MethodSemanticsAttributes`, `GenericParamAttributes`,
  `PInvokeAttributes`
- signatures: `MethodDefSig`, `FieldSig`, `PropertySig`, `TypeSpecSig`,
  `TypeSig`, `ParamSig`, `RetTypeSig`, `CustomModSig`, `GenericTypeInstSig`,
  and the two generic parameter indexes
- constants, and the custom attribute decoder: `CustomAttributeSig`,
  `FixedArgSig`, `NamedArgSig`, `ElemSig` with `SystemType` and `EnumValue`,
  `EnumDefinition`
- `cache` with `find`, `find_required`, `namespaces`, `namespace_members`,
  `nested_types`, `add_database` and a `filter`
- the free functions: `get_type_namespace_and_name`,
  `get_base_class_namespace_and_name`, `extends_type`, `is_nested`,
  `get_category`, `get_attribute`, `find`, `find_required`, `is_const`,
  `enum_mask`

## Do the two agree?

`agree.py` asks both readers to describe every type in a file as text - flags,
category, base class, interfaces, generic parameters, every field with its
signature and constant, every method with its full signature and its parameter
names and directions, properties, events, and every custom attribute with its
arguments decoded - and compares the descriptions line by line.

```
Windows.Win32.winmd                    34,902 types described identically
Windows.Foundation.UniversalApiContract 12,584 types described identically
System32\WinMetadata (20 files)        14,701 types described identically
```

62,187 types, no differences.

## How long each takes

```
Windows.Win32.winmd  (23.2 MB, 37311 types)
task                  pure python               bindings   ratio
open             6.2 ms                    0.1 ms          88.5x
typedefs        28.2 ms                   13.8 ms           2.0x
index          224.9 ms                   20.1 ms          11.2x
members         38.0 ms                  112.2 ms           0.3x
signatures    1192.2 ms                  293.1 ms           4.1x
attributes     892.9 ms                  176.9 ms           5.0x

Windows.UI.Xaml.winmd  (1.7 MB, 3323 types)
open             0.4 ms                    0.0 ms           9.2x
typedefs         1.6 ms                    0.7 ms           2.3x
index           15.7 ms                    0.9 ms          16.6x
members          5.1 ms                   12.2 ms           0.4x
signatures     140.5 ms                   32.0 ms           4.4x
attributes     209.6 ms                   36.9 ms           5.7x

the 20 files of System32\WinMetadata, as one cache (6.6 MB)
index           72.7 ms                    5.4 ms          13.4x
```

- `open` - map the file and lay the tables out; nothing read
- `typedefs` - the namespace and name of every type, from the raw table
- `index` - `cache(path)`: index by namespace, skipping nested types, and sort
  every type into interfaces, classes, enums, structs, delegates - which means
  `get_category` and therefore an attribute lookup, per type
- `members` - walk every type's fields and methods and every method's parameters
- `signatures` - parse every method signature and name every type in it
- `attributes` - decode every custom attribute of every type

The earlier, table-only measurement said 1.2x to 2.5x. With the whole interface
implemented the honest range is **4x to 13x**, and where it is worst is where
the C++ does most per call: the cache, which resolves an attribute per type, and
the signature and attribute decoders, which parse a blob into small objects.

`members` remains faster in Python, and for the same reason as before: it is
arithmetic over two integers per row, where the bindings allocate a row object
per method and per parameter.

The absolute numbers still matter more than the ratios. Indexing the whole Win32
metadata takes 225 ms and all of WinRT 73 ms; parsing every signature in Win32
takes 1.2 s. A projection that indexes at startup and parses the signatures it
actually needs is fine. One that parses every signature of every type on every
run is not.

Import, on a bare 37 ms interpreter: `winmd.reader` 9.6 ms, `purewinmd` 5.4 ms.

## What made it faster

Two memos, both of the same shape: a column whose values repeat.

| | |
| --- | --- |
| the name of the attribute a `CustomAttribute` row applies, by its constructor | 350 ms -> 259 ms |
| `get_type_namespace_and_name` by coded index value | 259 ms -> 225 ms |

A file applies tens of thousands of attributes with a few hundred distinct
constructors, and names `System.ValueType` as a base class thousands of times.
Decoded strings, by contrast, are *not* worth caching - see below.

Table decoding, on the `TypeDef` table of Win32 (37,311 rows of 24 bytes):

```
unpack_from, a row at a time                5.7 ms    2.30x
Struct().unpack_from, a row at a time       4.6 ms    1.87x
iter_unpack, the whole table                3.2 ms    1.30x
iter_unpack, keeping two columns            2.5 ms    1.00x
array per column, strided                  22.6 ms    9.14x
```

`struct.iter_unpack` over the whole table is the win. Building strided slices
for `array.array` in Python costs far more than it saves.

numpy can do the striding without a Python loop:

```
iter_unpack the rows, keep one column        1.82 ms   17.41x
numpy strided view                           0.10 ms    1.00x
numpy strided view, then .tolist()           0.31 ms    2.92x
```

17x on that column - but perhaps 2 ms out of 225 ms on the `index` task, for a
hard dependency on numpy in a library whose output is Python objects.

The strings, which are the real cost of the light tasks (74,622 lookups, 35,520
distinct):

```
bytes heap, decode each time                 9.5 ms    1.00x
bytes heap, cached by offset                11.2 ms    1.18x
memoryview of the mapping                   12.0 ms    1.26x
```

Copying the heap into `bytes` once beats reading through the mapping, and
**caching decoded strings by offset makes it slower** - names are nearly all
distinct, so the lookup usually misses and costs more than decoding eight bytes
again. Where a column does repeat, caching wins as expected: 326 distinct
namespaces over 37,311 rows takes the namespace index from 14.7 ms to 11.5 ms.

## The short script

The case a projection is actually used for: import, call a few APIs, exit.
`research/port_win32.py` ports `examples/win32.py` onto the pure reader - the
two offer the same names, so it is two substitutions - and
`research/startup_win32.py` runs the same little program as a separate process
each way. Times are the whole process, on an interpreter that starts in 44 ms.

```
                                                    process    of that, work
flat        win32.GetSystemMetrics()  bindings       348 ms         304 ms
                                      pure python    879 ms         835 ms
namespaced  win32.Windows.Win32...    bindings       353 ms         309 ms
                                      pure python    891 ms         847 ms
namespaced, without the flat index    bindings       122 ms          79 ms
                                      pure python    409 ms         365 ms
```

Two things fall out of this.

**The bindings win a short script**, 348 ms against 879 ms, and the gap is the
one the benchmarks predict: this is index building, where the pure reader is
about 11x, softened here by the interpreter start and the ctypes work that both
pay.

**The bigger lever is not the reader.** `win32.py` resolves a name by building a
flat index of every name in the metadata - 217,948 of them - and its
`__getattr__` does that before it looks at the namespaces, so reaching for
`win32.Windows.Win32...` does not avoid it. Going straight to a namespace, which
only indexes that one namespace, takes the bindings from 348 ms to 122 ms and
the pure reader from 879 ms to 409 ms. Checking the namespace roots before
building the flat index would give that to `win32.py` for three lines.

With that done, the pure reader on a short script (409 ms) is close to the
bindings as they are used today (348 ms). Its floor is the cache: `_namespace_tree()`
asks for every namespace, which in the pure reader means categorising every
type, 225 ms of the 365. A cache that skipped the per-kind lists - which
`win32.py` never reads - would take most of that back.

## Parse once and keep it?

Building an index of namespace, name and method range for every type, plus all
70,707 method names, then writing it out and reading it back:

```
building it from the file          82.6 ms
writing it as pickle               13.8 ms   (2.4 MB)
writing it as marshal               5.3 ms   (2.5 MB)
reading the pickle back            11.9 ms    6.94x faster than parsing
reading the marshal back           10.0 ms    8.24x faster than parsing

the bindings' cache([path])        19.6 ms
```

Worth about 8x, landing at 10 ms - the same order as the bindings' own cache.
For the bindings there is nothing to gain. Note that this index is the cheap
kind; a cache of *decoded signatures* would be far larger and is where the pure
reader would actually want one.

## Two traps worth knowing

Both cost real time here, and both are invisible until something silently
returns nothing.

- **The string heap shares suffixes.** 2,554 of the 35,520 distinct name offsets
  in `Windows.Win32.winmd` point *inside* another string - offset 2,228,292 is
  `TIMEVAL`, the tail of `LDAP_TIMEVAL`. Splitting the heap on `\0` and indexing
  the pieces, the obvious optimisation, misses those.
- **`PropertyMap` and `EventMap` are not sorted.** ECMA-335 has them sorted by
  `Parent` and the C++ reader scans them linearly anyway, which is the tell:
  `Windows.Foundation.UniversalApiContract` has `... 7680, 7681, 7679 ...` in
  `PropertyMap.Parent`. A binary search finds nothing for those types and they
  simply come out with no properties. `purewinmd` checks each column for
  sortedness once and groups the unsorted ones into a dict.

The coded indexes have a third: the tag order is not the list of tables used to
size them. `HasCustomAttribute` has 22 tags - tag 8, `Permission`, has no table
in the C++ sizing list - and `CustomAttributeType` starts at 2. Get that wrong
and every attribute resolves to the wrong row.

## Maintenance

What each route asks someone to keep working, counted in lines that are ours:

```
bindings                                pure python
  src/*.cpp, bind.h        2,051          purewinmd.py         1,554
  meson.build                 61          agree.py (oracle)      255
  pyproject.toml              26
  subprojects/*.wrap          34
  .github/workflows           70
  stubs, generated         3,542
```

Similar sizes, very different shapes.

**The bindings do not contain the parser.** The 2,051 lines are a translation
layer; the reading is Microsoft's 5,799 lines of headers, which we consume and
do not maintain. When they publish a fix, taking it is three lines of a wrap
file - version, URL, hash - and a rebuild. In the pure reader, a fix to the
metadata reading is ours to write.

**The pure reader has no build.** No compiler, no wheels, no abi3, no CI matrix.
The other column of that table is where the bindings' real tax sits: a release
builds eight wheels on six runners, and getting there cost two bugs that only
appear in CI - Meson preferring a MinGW gcc that was on the runner's PATH, and
the default architecture list including win32, where there is no 32 bit
toolchain. Neither is hard, but both are the kind of thing that has to be
re-learned when it breaks in a year.

**The pure reader's bugs are silent.** Four of them were written here, and not
one produced an error:

| what | what it did |
| --- | --- |
| coded index tag order (`CustomAttributeType` starts at 2) | every attribute resolved to the wrong row |
| `HasCustomAttribute` missing its `Permission` tag | the same, for everything after tag 8 |
| binary search on `PropertyMap`, which is not sorted | types quietly had no properties |
| `GenericParam.Number()` reading the flags column | generic parameters numbered wrong |

A wrong number decoded from the right offset is still a number. Nothing in
Python's type system or in a unit test of "does it parse" catches this; what
caught all four was `agree.py`, which asks both readers to describe 62,187 types
and compares the text. That test takes 12 seconds for Win32 and is the reason
the pure reader can be trusted at all.

Which is the catch: **the oracle is the thing it would replace**. A pure reader
kept alongside the bindings is safe to change. One that replaces them needs
another oracle - golden files, or the C# tooling this was meant to retire - or
it goes back to being 1,554 lines of hand-written offsets with nothing checking
them.

**Reading it is easier; changing it is riskier.** Everything is one file, in
Python, with pdb and `dis` available and no build step between an idea and
running it - against a C++ layer where a mistake can be a segfault (releasing an
interface after `RoUninitialize` crashed the process during this work) and every
change is a rebuild and a stub regeneration. For anyone who knows Python and not
C++, the pure reader is the one they can actually fix.

## What this says

The bindings are 4x to 13x faster once the whole interface is in play, and that
is the fair comparison now that both sides implement the same thing.

- **Pure Python** is 1,547 lines with no toolchain, no wheel and no build step,
  and it is fast enough to index the whole Win32 metadata in a quarter of a
  second. It wins where the work is integer arithmetic over columns.
- **The bindings** are worth their build for the decoders. Signatures and custom
  attributes are 4x to 5x, and they are what a projection does most of.

If the choice is either/or, it turns on whether the metadata is parsed once per
session (either is fine) or repeatedly per invocation (the bindings, or a cached
parse). If it is not either/or, the split that the numbers suggest is the tables
in Python and the decoders in C++ - though a project that has the C++ reader
building at all may as well take all of it.
