# Python winmd parser

A winmd parser written in Python and based on the ECMA-335 standard.  Its interface
follows [winmd](https://github.com/microsoft/winmd), the C++ reader from Microsoft that
this was written from.

```python
from winmd.reader import cache, get_category

db = cache(["vendor/Microsoft.Windows.SDK.Contracts/ref/netstandard2.0/Windows.Foundation.FoundationContract.winmd"])
type = db.find_required("Windows.Foundation", "IAsyncAction")

print(type.TypeNamespace(), type.TypeName(), get_category(type).name)
for method in type.MethodList():
    print(method.Name(), [p.Type().Type() for p in method.Signature().Params()])
```

Every accessor is a method call, named as in C++ - `type.TypeName()`, not `type.name` - so
what is known about the C++ reader carries over, and the tests hold this parser to it over
the real metadata. That is where this starts rather than where it stops: the C++ interface
is kept where it makes sense, and departed from where Python asks for something else. The
differences so far are listed below.

The C++ is needed to test this, not to use it: `pip install winmd` gets a pure Python
package.

## Installing

```bash
pip install winmd
```

Python 3.11 or newer, any platform. The metadata files are read, not shipped - see below.

## Getting the metadata

This reads `.winmd` files; it does not carry any. Where they come from:

| What | Where |
| --- | --- |
| WinRT, the running system's own | `C:\Windows\System32\WinMetadata\*.winmd` on any Windows 10 or 11 machine - nothing to install, and it matches that machine |
| WinRT, a particular SDK | the [`Microsoft.Windows.SDK.Contracts`](https://www.nuget.org/packages/Microsoft.Windows.SDK.Contracts) NuGet package, in `ref/netstandard2.0/` |
| Win32 | the [`Microsoft.Windows.SDK.Win32Metadata`](https://www.nuget.org/packages/Microsoft.Windows.SDK.Win32Metadata) NuGet package (published as a prerelease), at its root |
| WinAppSDK, WinUI, ... | each ships its own `.winmd` in its NuGet package |

What the tests read is installed under `vendor/` with `nuget.exe`, along with the C++
reader they are checked against:

```powershell
scripts/fetch-vendor.ps1
```

```
vendor/Microsoft.Windows.SDK.Contracts/ref/netstandard2.0/*.winmd   the WinRT contracts
vendor/Microsoft.Windows.SDK.Win32Metadata/Windows.Win32.winmd      the Win32 metadata
vendor/Microsoft.Windows.WinMD/winmd_reader.h                       the C++ reader
```

`WINMD_VENDOR` points the tests at another directory of the same shape; without one they
skip and say so.

## Reading it

Everything starts from a `cache`, which indexes the types of the files it is given by
namespace and name; that is what resolves a reference in one file to the definition in
another. Keep it alive as long as anything taken out of it is used.

```python
import glob
from winmd.reader import cache

winrt = cache(glob.glob(r"C:\Windows\System32\WinMetadata\*.winmd"))
win32 = cache(["vendor/Microsoft.Windows.SDK.Win32Metadata/Windows.Win32.winmd"])

print("Windows.Win32.UI.WindowsAndMessaging" in win32.namespaces())   # True
```

**A namespace and its types.** `namespaces()` maps a name to the types in it, both as a
whole and split by kind.

```python
members = win32.namespaces()["Windows.Win32.UI.WindowsAndMessaging"]
print("MSG" in members.types)                                    # True
print(any(type.TypeName() == "MSG" for type in members.structs)) # True
```

**A type.** `find_required` raises when there is none; `find` returns a row that is false
in a boolean context.

```python
from winmd.reader import category, get_category

type = win32.find_required("Windows.Win32.UI.WindowsAndMessaging", "MSG")
print(get_category(type) == category.struct_type)                     # True
print([field.Name() for field in type.FieldList()])
# ['hwnd', 'message', 'wParam', 'lParam', 'time', 'pt']
```

**A function, with its signature.** In Win32 metadata the functions and constants of a
namespace are the members of a static class named `Apis`. The parameter *types* come from
the signature and the *names* from the `Param` rows, matched by `Sequence()` counting from
1, where 0 is the return value.

```python
from winmd.reader import ElementType, get_type_namespace_and_name

def type_name(sig):
    value = sig.Type()
    name = value.name if isinstance(value, ElementType) else \
        ".".join(get_type_namespace_and_name(value))
    return name + "[]" * sig.is_szarray() + "*" * sig.ptr_count()

apis = win32.find_required("Windows.Win32.UI.WindowsAndMessaging", "Apis")
method = next(m for m in apis.MethodList() if m.Name() == "MessageBoxW")

signature = method.Signature()
names = {p.Sequence(): p for p in method.ParamList()}
for index, param in enumerate(signature.Params(), start=1):
    print(type_name(param.Type()), names[index].Name(), names[index].Flags().In())
# Windows.Win32.Foundation.HWND hWnd True
# Windows.Win32.Foundation.PWSTR lpText True
# ...
```

**Constants and enum members.** A constant is a `Field` whose `Flags().Literal()` is set;
an enum is the same thing wrapped in an `EnumDefinition`.

```python
foundation = win32.find_required("Windows.Win32.Foundation", "Apis")
print(next(f for f in foundation.FieldList() if f.Name() == "MAX_PATH").Constant().Value())
# 260

style = win32.find_required("Windows.Win32.UI.WindowsAndMessaging", "MESSAGEBOX_STYLE")
definition = style.get_enum_definition()
print(definition.m_underlying_type.name)                              # U4
print(definition.get_enumerator("MB_ICONWARNING").Constant().Value()) # 48
```

**An attribute, such as the IID of an interface.** `Value()` decodes the arguments, and
needs the file defining the attribute in the same cache.

```python
from winmd.reader import get_attribute

stream = win32.find_required("Windows.Win32.System.Com", "IStream")
attribute = get_attribute(stream, "Windows.Win32.Foundation.Metadata", "GuidAttribute")

args = attribute.Value()                     # name it: FixedArgs() borrows from it
parts = [arg.value.value for arg in args.FixedArgs()]
print("{:08x}-{:04x}-{:04x}-{}-{}".format(
    parts[0], parts[1], parts[2], bytes(parts[3:5]).hex(), bytes(parts[5:]).hex()))
# 0000000c-0000-0000-c000-000000000046
```

**The DLL and entry point of a P/Invoke.** Nothing points from a `MethodDef` to its
`ImplMap`, so walk that table once and index it by the method each row names. A row is
hashable and knows which file it came from, so keying by the row keeps two databases in the
same cache apart, which keying by its number would not.

```python
from winmd.reader import MemberForwarded

imports = {}
for database in win32.databases():
    for row in database.ImplMap:
        member = row.MemberForwarded()
        if member.type() is MemberForwarded.MethodDef:
            imports[member.MethodDef()] = (row.ImportScope().Name(), row.ImportName())

print(imports[method])                       # ('USER32.dll', 'MessageBoxW')
```

`ImportScope()` hands back the `ModuleRef` row rather than an index into it, so there is no
second table to walk. Where a column has no accessor, `row.get_value(column)` reads it raw.

**WinRT: what a class implements**, and following a type in a signature back to its
definition.

```python
from winmd.reader import find_required

uri = winrt.find_required("Windows.Foundation", "Uri")
for impl in uri.InterfaceImpl():
    print(".".join(get_type_namespace_and_name(impl.Interface())))
# Windows.Foundation.IUriRuntimeClass
# Windows.Foundation.IUriRuntimeClassWithAbsoluteCanonicalUri
# Windows.Foundation.IStringable

interface = winrt.find_required("Windows.Foundation", "IStringable")
returns = next(iter(interface.MethodList())).Signature().ReturnType().Type().Type()
print(returns.name if isinstance(returns, ElementType) else find_required(returns).TypeName())
# String
```

`examples/dump.py` is the same ideas at full length: it walks every namespace of any
metadata and prints it in a C# like syntax.

## Things that will bite

- **Every accessor is a method call**, named as in C++: `type.TypeName()`, not
  `type.name`. Nothing is a property.
- **In Win32 metadata the functions and constants live in a class named `Apis`**, one per
  namespace, beside the types. Looking for `MessageBoxW` among the types finds nothing.
- **A row can be invalid.** `find` and the accessors that may point at nothing return one
  instead of raising; test with `bool(row)` before using it. Using an invalid row raises
  `RuntimeError`.
- **Each table is a class of its own** - `TypeDef`, `MethodDef`, ... - holding that
  table's accessors and no others, as the C++ structs do. `AttributeError` is what asking
  a `TypeDef` for a `Signature()` gets you.
- **A range is not a list.** `MethodList()` and friends return a `RowRange`: it has
  `len()`, `[]`, slicing and iteration, and `.first` / `.second`, but it is not a `list`.
- **`Signature()` and `Value()` parse a blob every time they are called.** Reading
  `method.Signature()` twice does the work twice; name it if you use it more than once.
  (In the C++ reader this is worse than slow: what they return points into the object,
  which a temporary does not outlive.)
- **Decoding an attribute needs the attribute's own definition in the cache**, since the
  argument types come from its constructor. `ValueError` otherwise.
- **The `None` enumerator is `None_`** (`GenericParamVariance.None_`), Python having taken
  the name.
- **Some enums are `IntFlag`** - `CallingConvention`, `AssemblyFlags`,
  `GenericParamSpecialConstraint` - because the metadata holds combinations that have no
  enumerator. Mask, do not compare.
- **`Constant.ValueString()` is a `str`** decoded from UTF-16, while every other string is
  UTF-8; the typed accessors raise unless the constant is of that type, so prefer
  `Value()`.
- **`Param.Sequence()` starts at 1**, and sequence 0 is the return value, so a `Param` row
  and a `ParamSig` are only aligned through it.
- **A `TypeSpec` cannot be resolved** with `find()`; it is a signature, not a type. Check
  `index.type()` first.
- **Compare `index.type()` with `is`.** It returns a tag, and two kinds give the same tag
  to different tables: `HasCustomAttribute.MethodDef` and `TypeDefOrRef.TypeDef` are both
  tag 0, so `==` says they are equal. The C++ will not compile that comparison; here only
  `is` tells them apart.

## What is implemented

The whole of `winmd::reader`:

- the PE and CLI headers, the metadata root and the `#Strings`, `#Blob` and `#GUID` heaps
- all 38 tables, with the accessors each row has, and the 13 coded index kinds
- member lists (`FieldList`, `MethodList`, `ParamList`, `PropertyList`, `EventList`,
  `InterfaceImpl`, `GenericParam`, `MethodImplList`) and the back references that have no
  column of their own (`Parent`, `Constant`, `CustomAttribute`, `EnclosingType`,
  `MethodSemantic`)
- the flag structs: `TypeAttributes`, `MethodAttributes`, `FieldAttributes`,
  `ParamAttributes`, `PropertyAttributes`, `EventAttributes`, `MethodImplAttributes`,
  `MethodSemanticsAttributes`, `GenericParamAttributes`, `AssemblyAttributes`,
  `PInvokeAttributes`
- the signature parsers: `TypeSig`, `ParamSig`, `RetTypeSig`, `MethodDefSig`, `FieldSig`,
  `PropertySig`, `TypeSpecSig`, `CustomModSig`, `GenericTypeInstSig`, `GenericTypeIndex`,
  `GenericMethodTypeIndex`
- constants, and the custom attribute decoder: `CustomAttributeSig`, `FixedArgSig`,
  `NamedArgSig`, `ElemSig` (`ElemSig.SystemType`, `ElemSig.EnumValue`), `EnumDefinition`
- `cache` (`find`, `find_required`, `namespaces`, `namespace_members`, `nested_types`,
  `add_database`, `remove_type`) and `filter`
- the free functions: `get_type_namespace_and_name`,
  `get_base_class_namespace_and_name`, `extends_type`, `is_nested`, `get_category`,
  `get_attribute`, `find`, `find_required`, `is_const`, `enum_mask`,
  `uncompress_unsigned`

## Differences from the C++ interface

- **Ranges (`std::pair<Row, Row>`)** become range objects with `len()`, `[]`, slicing and
  iteration, keeping `.first`, `.second`, `.size()` and `.empty()`. The free functions the
  C++ needs over a pair - `begin`, `end`, `size`, `empty`, `distance` - are not here:
  `len(r)`, `not r` and `for row in r` say all of it.
- **Rows are iterators too**: `row + 1`, `row - 1`, `row_a - row_b`, the comparisons,
  `bool(row)` and `hash(row)`.
- **`coded_index<TypeDefOrRef>` is a class per kind**, named `coded_index_TypeDefOrRef`,
  so `isinstance` tells the kinds apart and each kind carries only the accessors it can
  answer to. Each states its own return type for `index.type()`, so that is the kind's
  enum and not any of the thirteen. There is no `coded_index[TypeDefOrRef]`: a kind is a
  value here rather than a type parameter, and the class is named, not subscripted.
- **`CodedIndexT` is the thirteen kinds**, a union the things keyed by a kind are
  typed on. The C++ constrains nothing: `coded_index<T>` takes any `T`, and one with no
  `coded_index_bits` specialisation quietly gets a tag width of 0.
- **`ImplMap` has accessors**, which the C++ leaves to `get_value` along with
  `DeclSecurity`, `FieldLayout` and `FieldRVA`. Those four tables never appear in WinRT
  metadata, which is what that reader was written for; `ImplMap` appears in Win32
  metadata, which is what this one is often pointed at, so it is named here.
- **The `Attributes` structs are read only**, unlike the C++ ones which can also set a bit.
- **The `None` enumerator** is a Python keyword and becomes `None_`.
- **`get_row<Row>()` takes the row class as an argument** - `index.get_row(TypeDef)`
  where the C++ writes `get_row<TypeDef>()` - and each kind carries a method named after
  the row type (`index.TypeDef()`, `index.MemberRef()`) that calls it. Asking for a table
  the index does not point at raises rather than tripping an assert.
- **`get_row()` with no argument is an addition**, and the one thing here the C++ has no
  form of: a template argument has to be known where it is written, so there is no way to
  ask it for "whatever table the tag names". It hands back a `Row`, which is as much as
  can be said before the tag is read - name the row class to get that class back.
- **Calling an accessor on a row that is not one** raises `RuntimeError` rather than
  reading whatever bytes are there. Test rows with `bool(row)`.
- **A signature is parsed from a blob alone** - `MethodDefSig(blob)` - because a blob knows
  which database it came from; the C++ has to be handed the table as well.
- **Enums are `enum.IntEnum`**, and the ones that hold bit combinations
  (`CallingConvention`, `AssemblyFlags`, `GenericParamSpecialConstraint`) are
  `enum.IntFlag`.
- **Lifetime**: rows, indexes and signatures point into a memory mapped file owned by a
  `database` or `cache`. Python keeps the owner alive through the references, so this only
  matters if you call `close()` yourself.

## Where the reading works differently

The interface is the C++ one; three things behind it are not, because a comparison or a
slice costs what a function call costs here and the C++ can afford to do them one at a
time. The answers are the same either way - `tests/test_reference.py` holds them to it
over every type in the metadata.

- **A column is taken out once, not searched in place.** The C++ binary searches the
  table itself, decoding a row per comparison (`impl/winmd_reader/column.h`). This takes
  the column out as a list of integers the first time something looks at it, and
  searches that. `PropertyMap` and `EventMap` come out of the compiler unsorted, so the
  C++ scans them linearly; this notices once and groups them into a dict, which is why
  those two give a `RowList` rather than a `RowRange`.
- **The heaps are copied, and a string is decoded.** `get_string` returns a
  `std::string_view` into the mapped file over there, with no copy and no decoding. A
  `str` cannot be that, so `#Strings`, `#Blob` and `#GUID` are copied out of the mapping
  when the file is opened - slicing `bytes` beats going through a `memoryview` - and
  every `Name()` decodes UTF-8.
- **Three things are memoised that the C++ looks up each time**: the column above, the
  namespace and name of an attribute's constructor, and the namespace and name behind a
  `TypeDefOrRef`. A file applies tens of thousands of attributes of a few hundred kinds
  and names the same base class over and over, so the answers are worth keeping.

## Behaviour inherited from the C++ reader

- `TypeDef.is_enum()` and `extends_type()` read the base class, so calling them on a type
  without one raises, as in C++. Check `if type.Extends():` first.
- `CustomAttribute.Value()` resolves enum arguments through the `cache`, and raises when
  the file defining the attribute is not in it.
- `get_type_namespace_and_name()` raises for a `TypeSpec`, which is a signature rather
  than a name.

## Examples

`examples/` holds programs written on top of the reader. Each documents itself, so read
the module docstring, or pass `--help` where there are arguments to pass.

```
dump.py        dumps any metadata in a C# like syntax; the only one that is not Windows only
dumpwin32.py   dumps Win32 API signatures in a C like syntax
ctypes_gen.py  generates a ctypes module from the Win32 metadata
windows.py     the Windows API, Win32 and WinRT alike, resolved on attribute access
browser.py     a window that searches the Win32 metadata, drawn with windows.py
```

## Tests

```powershell
scripts/fetch-vendor.ps1
```

```bash
python -m unittest discover -s tests -v
```

Three suites, and the second is the important one.

- `test_winmd.py` - the interface itself: the shapes, the errors, the corners that are
  ours rather than the metadata's.
- `test_reference.py` - builds `tests/reference.cpp` against the C++ reader and compares,
  line for line, how the two describe **every type** in the metadata: flags, category,
  base class, interfaces, generic parameters, fields with their signatures and constants,
  methods with their full signatures and parameter directions, properties, events, and
  every custom attribute with its arguments decoded, over the Win32 metadata and the
  SDK contracts under `vendor/`.
- `test_examples.py` - runs the programs under `examples/`, which nothing else builds.
  `dump.py`, `dumpwin32.py` and the generating half of `ctypes_gen.py` read metadata
  and run anywhere; `windows.py` and `browser.py` call the Windows API, and are skipped on
  a machine that cannot.

That second suite is why this can be trusted: the C++ reader is the reference, and it
still gets the last word. It needs a C++ compiler - g++, clang++ or MSVC, found in PATH
or through vswhere - and fails rather than skips without one, since a suite that quietly
does not run is worse than no suite. Everything it reads is committed, so it says the
same thing on any machine.

## Files

```
src/winmd/reader/        the reader, one module per header it answers to:
    enum.py                the enums, and the tags of each coded index
    flags.py               one class per column of flags
    view.py                the cursor a blob is read with
    table.py               what a row, a coded index and a table are made of
    helpers.py             the free functions
    signature.py           the signature blobs and the attribute decoder
    schema.py              the rows, and the ranges over them
    index.py               a column that may point at one of several tables
    database.py            one file
    cache.py               a set of files, indexed by namespace
    __init__.py            what winmd.reader offers, from all of the above
scripts/fetch-vendor.ps1 installs the metadata and the C++ reader under vendor/
scripts/bench.py         times the reader, and two revisions of it against each other
tests/test_winmd.py      the interface
tests/reference.cpp      the same descriptions, from the C++ reader
tests/describe.py        what both of them describe, in the same words
tests/test_reference.py  builds the one, runs the other, compares
tests/test_examples.py   runs the programs under examples/
examples/                programs written on the reader, each documented in itself
docs/winmd-format.md     what is in a .winmd file, from the first byte down
docs/winmd-reader.md     notes on the C++ reader this was written from
```

