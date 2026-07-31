# A pure Python reader, measured against the bindings

What it would cost to read `.winmd` in Python alone, instead of binding the C++
reader. Everything here was measured on this machine against the real metadata,
not a synthetic file: `Windows.Win32.winmd` (23.2 MB, 37,311 types) and the
WinRT metadata of the running system (20 files, 6.6 MB). Python 3.14, MSVC
build of the extension.

```
research/purewinmd.py   the reader: PE -> CLI -> metadata root, heaps, the 38
                        table schemas, coded indexes, rows and a namespace index
research/agree.py       checks it against the bindings, row by row
research/bench.py       the same tasks through both
research/optimize.py    where the time goes and what moves it
research/columns.py     column oriented decoding, with and without numpy
research/caching.py     saving the parse instead of doing it again
research/startup.py     what each reader costs before it reads anything
```

`agree.py` passes on all three files it is pointed at: identical row counts, and
identical values for every column of every `TypeDef` (37,311 rows), and for
`MethodDef`, `Field` and `Param` sampled across the table. The two readers agree.

## 1. How long each takes

```
Windows.Win32.winmd  (23.2 MB, 37311 types)
task                  pure python               bindings   ratio
open             2.9 ms                    0.1 ms          55.7x
typedefs        25.5 ms                   13.8 ms           1.9x
index           23.3 ms                   18.8 ms           1.2x
members         35.3 ms                  112.9 ms           0.3x

Windows.UI.Xaml.winmd  (1.7 MB, 3323 types)
open             0.2 ms                    0.0 ms           5.5x
typedefs         1.6 ms                    0.7 ms           2.5x
index            1.4 ms                    0.9 ms           1.5x
members          5.0 ms                   12.2 ms           0.4x

the 20 files of System32\WinMetadata, indexed together (6.6 MB)
index            7.9 ms                    5.3 ms           1.5x
```

- `open` - map the file and lay the tables out; nothing read
- `typedefs` - the namespace and name of every type, as Python strings
- `index` - `{namespace: {name: type}}`, what a `cache` is for
- `members` - walk every type's fields and methods, and every method's parameters

**The 15-30x of the earlier synthetic measurement does not appear.** That
comparison was a C++ program against a Python one; this one is Python against
Python, and the bindings have to build a Python object for every row and every
string they hand over. Once both sides pay that, the gap is 1.2x to 2.5x - and
where the work is arithmetic over columns rather than objects, pure Python wins:
`members` computes each member list from two integers (`my first child` until
`the next row's first child`), while the bindings create a row object per method
and per parameter.

The absolute numbers are what matter for a projection: **23 ms to index the
entire Win32 metadata, 8 ms for all of WinRT.** Neither is a startup problem.

`open` is 55x but 3 ms: it is the one place the pure reader copies, taking the
6.4 MB `#Strings` heap out of the mapping (see below).

Import, on a bare 37 ms interpreter: `winmd.reader` 9.6 ms, `purewinmd` 5.4 ms.

## 2. What it costs to write and keep

`purewinmd.py` is 303 lines of code for: the PE and CLI headers, the metadata
root and its streams, the heap index sizes, the 38 table schemas, the 13 coded
indexes and their sizing rule, row and table decoding, and a namespace index.
That is the whole of what the C++ `database` does - `pe.h`, `database.h`,
`table.h`, `column.h` and a slice of `cache.h`.

It is also the easy half. What a projection needs beyond it:

| Still to write | The C++ it mirrors |
| --- | --- |
| signature blobs: `TypeSig`, `MethodDefSig`, `ParamSig`, generics | `signature.h`, 590 lines |
| custom attribute decoding, `ElemSig` and friends | `custom_attribute.h`, 385 lines |
| the flag structs, one accessor per bit | `flags.h`, 660 lines |
| `get_category`, `EnumDefinition`, `get_attribute` | `key.h`, 213 lines |
| resolving references across files, nested types, filters | `cache.h`, `helpers.h`, `type_helpers.h` |

Signatures are where the fiddly parts live: compressed unsigned integers,
`ELEMENT_TYPE` prefixes that nest, `modopt`/`modreq`, generic instantiations.
Call it another 800 to 1,200 lines of Python, and the bugs will be in there
rather than in the table layout.

Two traps found while writing this, both of which cost real time:

- **The string heap shares suffixes.** 2,554 of the 35,520 distinct name
  offsets in `Windows.Win32.winmd` point *inside* another string - offset
  2,228,292 is `TIMEVAL`, the tail of `LDAP_TIMEVAL`. Splitting the heap on
  `\0` up front and indexing the pieces, which looks like the obvious
  optimisation, silently misses those. Read from the offset to the next `\0`.
- **A table's rows can only be found by summing the sizes of every table before
  it**, and those sizes depend on the row counts of tables that the coded index
  rules refer to. Get one coded index size wrong and everything after it decodes
  to plausible rubbish rather than failing. `agree.py` exists for that reason.

## 3. What actually makes it faster

Decoding the `TypeDef` table (37,311 rows of 24 bytes):

```
unpack_from, a row at a time                5.7 ms    2.30x
Struct().unpack_from, a row at a time       4.6 ms    1.87x
iter_unpack, the whole table                3.2 ms    1.30x
iter_unpack, keeping two columns            2.5 ms    1.00x
array per column, strided                  22.6 ms    9.14x
```

`struct.iter_unpack` over the whole table is the win, as the earlier
investigation found - 1.8x over a row at a time. Building the strided slices for
`array.array` by hand in Python costs far more than it saves; that idea only
works if something else does the striding.

Something else can: numpy views the table as `(rows, row_size)` bytes and takes
a column with no Python loop at all.

```
iter_unpack the rows, keep one column        1.82 ms   17.41x
unpack just the column, a row at a time      2.09 ms   19.99x
numpy strided view                           0.10 ms    1.00x
numpy strided view, then .tolist()           0.31 ms    2.92x
```

17x on that column - but on the whole `index` task it would save perhaps 2 ms in
23 ms, because the strings dominate, and it buys a hard dependency on numpy for
a library whose output is Python objects. Not worth it here.

The strings, which are the real cost (74,622 lookups, 35,520 distinct):

```
bytes heap, decode each time                 9.5 ms    1.00x
bytes heap, cached by offset                11.2 ms    1.18x
memoryview of the mapping                   12.0 ms    1.26x
```

Two things to note. Copying the heap into `bytes` once beats reading through the
mapping - `mmap` has `find`, a memoryview has neither `index` nor `find`, so
staying on the mapping means going through the `mmap` object and slicing it.
And **caching decoded strings by offset makes it slower**: type and member names
are nearly all distinct, so the dict lookup usually misses and costs more than
decoding eight bytes again.

Where a column repeats, caching wins as expected - 326 distinct namespaces over
37,311 rows:

```
building {namespace: {name: row}}
no string cache            14.7 ms    1.27x
cache every string         18.2 ms    1.58x
cache namespaces only      11.5 ms    1.00x
```

So `Database.string()` does not cache, and `namespaces()` caches namespaces
only. That one change took the `index` task from 30.7 ms to 23.3 ms.

## 4. Parse once and keep it?

Building a fuller index - namespace, name and the method range of every type,
plus all 70,707 method names - then writing it out and reading it back:

```
building it from the file          86.6 ms
writing it as pickle               12.3 ms   (2.2 MB)
writing it as marshal               5.5 ms   (2.3 MB)
reading the pickle back            10.8 ms    8.01x faster than parsing
reading the marshal back           10.4 ms    8.37x faster than parsing

the bindings' cache([path])        19.8 ms
```

For the pure Python reader a cache is worth 8x, and lands at about 10 ms, which
is the same order as the bindings' own `cache()`. For the bindings there is
nothing to gain: reloading a pickle costs about half of what parsing costs them
in the first place, and the pickle then has to be invalidated when the metadata
changes.

Both are dominated by allocating Python objects, which is why the two converge
at around 10 ms whichever route the bytes take. `marshal` writes twice as fast
as `pickle` and reads the same; it is also version-locked and only handles
builtin types, which the index happens to be made of.

## What this says

Neither implementation is a startup problem at these sizes. The choice is not
about speed:

- **The bindings** give the whole of `winmd::reader` - signatures, custom
  attributes, categories, the cache semantics - for the cost of building a C++
  extension, and the abi3 wheel means one binary per platform.
- **Pure Python** is 303 lines for the tables, needs no toolchain and no wheel
  at all, and is faster for anything that stays in integers. The remaining 800
  to 1,200 lines are the fiddly ones, and they would have to be kept correct
  against metadata that keeps changing.

A middle road worth considering: the tables in Python, and nothing else. A
projection that reads names, flags and member lists - which is most of what
generating bindings needs - is served by exactly what is in `purewinmd.py`
today. Signatures are the part that earns its keep in C++.
