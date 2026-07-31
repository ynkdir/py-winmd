# winmd for Python

A reader for Windows Metadata (`.winmd`) - the ECMA-335 tables behind WinRT and the Win32
API - in nothing but the standard library. No compiler, no wheels per platform, no
dependencies.

```python
import winmd
from winmd.reader import cache, get_category

db = cache(["metadata/Microsoft.Windows.SDK.Contract/Windows.Foundation.FoundationContract.winmd"])
type = db.find_required("Windows.Foundation", "IAsyncAction")

print(type.TypeNamespace(), type.TypeName(), get_category(type))
for method in type.MethodList():
    print(method.Name(), [p.Type().Type() for p in method.Signature().Params()])
```

The interface follows [Microsoft.Windows.WinMD](https://github.com/microsoft/winmd), the
C++ reader this was written from: every accessor is a method call, named as in C++ -
`type.TypeName()`, not `type.name`. That C++ reader is also the reference the tests use.
Nothing else does: `pip install winmd` gets a pure Python package.

## Installing

```bash
pip install winmd
```

Python 3.9 or newer, any platform. The metadata files are read, not shipped - see below.
## Getting the metadata

This reads `.winmd` files; it does not carry any. Where they come from:

| What | Where |
| --- | --- |
| WinRT, the running system's own | `C:\Windows\System32\WinMetadata\*.winmd` on any Windows 10 or 11 machine - nothing to install, and it matches that machine |
| WinRT, a particular SDK | the [`Microsoft.Windows.SDK.Contracts`](https://www.nuget.org/packages/Microsoft.Windows.SDK.Contracts) NuGet package, in `ref/netstandard2.0/` |
| Win32 | the [`Microsoft.Windows.SDK.Win32Metadata`](https://www.nuget.org/packages/Microsoft.Windows.SDK.Win32Metadata) NuGet package (published as a prerelease), at its root |
| WinAppSDK, WinUI, ... | each ships its own `.winmd` in its NuGet package |

`fetch-metadata.py` downloads the two NuGet ones into `metadata/`. A NuGet package is a
zip, so it needs nothing but the standard library and works wherever Python does: it reads
the newest version from the flat container index, downloads the package to a temporary file
and takes the `.winmd` files out of it. Directories that are already populated are skipped,
so pass `--force` to refresh them, and `--directory` to put them somewhere else.

```bash
python fetch-metadata.py
```

```
metadata/Microsoft.Windows.SDK.Contract/*.winmd          95 files, the WinRT contracts
metadata/Microsoft.Windows.SDK.Win32Metadata/Windows.Win32.winmd
```

Any URL of the same shape works if you want a specific version rather than the newest:

```
https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.win32metadata/<version>/microsoft.windows.sdk.win32metadata.<version>.nupkg
```

The tests look the metadata up through the `WINMD_METADATA` environment variable and skip
when it is not there.

```bash
WINMD_METADATA=$PWD/metadata python tests/test_winmd.py
```

## Reading it

Everything starts from a `cache`, which indexes the types of the files it is given by
namespace and name; that is what resolves a reference in one file to the definition in
another. Keep it alive as long as anything taken out of it is used.

```python
import glob
from winmd.reader import cache

winrt = cache(glob.glob(r"C:\Windows\System32\WinMetadata\*.winmd"))
win32 = cache(["metadata/Microsoft.Windows.SDK.Win32Metadata/Windows.Win32.winmd"])

print(len(win32.namespaces()), "namespaces")           # 325
```

**A namespace and its types.** `namespaces()` maps a name to the types in it, both as a
whole and split by kind.

```python
members = win32.namespaces()["Windows.Win32.UI.WindowsAndMessaging"]
print(len(members.types), len(members.structs), len(members.enums))   # 199 109 75
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
`ImplMap`, so walk that table once and index it. `get_value(column)` reads a column that
has no named accessor.

```python
imports = {}
for database in win32.databases():
    modules = [database.get_string(row.get_value(0)) for row in database.ModuleRef]
    for row in database.ImplMap:
        member = row.get_value(1)                    # MemberForwarded
        if member & 1:                               # 1 == MethodDef
            imports[(member >> 1) - 1] = (
                modules[row.get_value(3) - 1], database.get_string(row.get_value(2)))

print(imports[method.index()])                       # ('USER32.dll', 'MessageBoxW')
```

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
- **A range is not a list.** `MethodList()` and friends return a `Row_range`: it has
  `len()`, `[]` and iteration, and `.first` / `.second`, but it is not a `list`.
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
  `get_attribute`, `find`, `find_required`, `is_const`, `enum_mask`, `begin`, `end`,
  `size`, `empty`, `distance`, `uncompress_unsigned`

## Differences from the C++ interface

- **Ranges (`std::pair<Row, Row>`)** become range objects with `len()`, `[]` and
  iteration, keeping `.first` and `.second`. `begin(r)`, `end(r)`, `size(r)`, `empty(r)`
  and `distance(r)` work as before.
- **Rows are iterators too**: `row + 1`, `row - 1`, `row_a - row_b`, the comparisons,
  `bool(row)` and `hash(row)`.
- **The `Attributes` structs are read only**, unlike the C++ ones which can also set a bit.
- **The `None` enumerator** is a Python keyword and becomes `None_`.
- **`get_row<Row>()` is a method named after the row type** (`index.TypeDef()`,
  `index.MemberRef()`), and asking for the wrong one raises rather than tripping an assert.
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
win32.py       the Win32 API, resolved from the metadata on attribute access
winrt.py       WinRT, the same way: activation, HSTRING, generics, events, arrays
```

## Tests

```bash
python fetch-metadata.py --headers
python -m unittest discover -s tests -v
```

Two suites, and the second is the important one.

- `test_winmd.py` - 45 tests over the interface itself: the shapes, the errors, the
  corners that are ours rather than the metadata's.
- `test_reference.py` - builds `tests/reference.cpp` against the C++ reader and compares,
  line for line, how the two describe **every type** in the metadata: flags, category,
  base class, interfaces, generic parameters, fields with their signatures and constants,
  methods with their full signatures and parameter directions, properties, events, and
  every custom attribute with its arguments decoded. 34,902 types of Win32 metadata,
  12,683 of the SDK contracts, 14,701 of the system WinRT metadata.

That second suite is why this can be trusted: the C++ reader is the reference, and it
still gets the last word. It needs a C++ compiler (g++, clang++ or MSVC, found in PATH or
through vswhere) and the headers `fetch-metadata.py --headers` downloads; without them it
skips and says so.

## Files

```
src/winmd/reader.py      the reader
src/winmd/__init__.py    re-exports it
fetch-metadata.py        downloads the .winmd files, and the C++ reader for the tests
tests/test_winmd.py      the interface
tests/reference.cpp      the same descriptions, from the C++ reader
tests/describe.py        what both of them describe, in the same words
tests/test_reference.py  builds the one, runs the other, compares
examples/                programs written on the reader, each documented in itself
docs/winmd-reader.md     notes on the C++ reader this was written from
```
