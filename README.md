# winmd for Python

A Python extension module that wraps the [Microsoft.Windows.WinMD](https://github.com/microsoft/winmd)
C++ header library (in `winmd/`) with [nanobind](https://github.com/wjakob/nanobind).
The interface of `winmd::reader` is mirrored as directly as the Python object model allows.

```python
import winmd
from winmd.reader import cache, get_category, category

db = cache("metadata/Microsoft.Windows.SDK.Contract/Windows.Foundation.FoundationContract.winmd")
type = db.find_required("Windows.Foundation", "IAsyncAction")

print(type.TypeNamespace(), type.TypeName(), get_category(type))
for method in type.MethodList():
    print(method.Name(), [p.Type().Type() for p in method.Signature().Params()])
```

## Building

Requirements: Python 3.12+ with its development headers (they come with the interpreter on
Windows; `python3-dev` on Debian and Ubuntu), a C++17 compiler and a PEP 517 build
frontend. Nothing else has to be prepared - a clean checkout builds as it is.

```bash
python -m build
```

That is all: `dist/` gets an sdist and a wheel. Any other frontend does the same thing,
since the work is done by
[Meson and meson-python](https://nanobind.readthedocs.io/en/latest/meson.html), which the
frontend installs into an isolated environment by itself.

Three things are worth knowing about how it manages without a setup script.

- **The sources it wraps are Meson subprojects.** `subprojects/*.wrap` names the
  Microsoft.Windows.WinMD NuGet package (the C++ library this binds), nanobind and
  robin-map; the build downloads and verifies each one. Only the `.wrap` files are checked
  in, so the build needs network access the first time.
- **The toolchain is the one Meson finds**, and nothing here pins it. On Windows that
  usually means MSVC without any preparation: when no compiler is on PATH, Meson locates
  the Visual Studio installation with `vswhere.exe`, runs `vcvars64.bat` and takes the
  environment from it, so neither a Developer PowerShell nor `vcvars64.bat` beforehand is
  needed. (The `'vswhere.exe' is not recognized` line that scrolls past comes from
  `vcvars64.bat` itself and is harmless.) To force that even when another compiler is on
  PATH, pass `--vsenv` on to Meson - `-Csetup-args=--vsenv` with most frontends.
- **The extension targets the stable ABI**, which is what nanobind calls Python's limited
  API and is why 3.12 is the floor. One binary serves every version from the one it was
  built with on: a wheel built with 3.12 is tagged `cp312-abi3` and installs on 3.13, 3.14
  and later just as well, so build with the oldest Python you mean to support. Where the
  limited API cannot be used - a free-threaded interpreter, say - turn it off with
  `-Csetup-args=-Dpython.allow_limited_api=false` and the wheel is tagged for that one
  version, as extensions usually are.

The C++ library guards its Windows specific parts with `_WIN32` and reads the metadata with
`mmap` elsewhere, so the module is not Windows only: it builds and passes its tests with
MSVC on Windows (one `cp313-abi3` wheel on 3.13, 3.14 and 3.15) and with gcc 15 on Ubuntu.
The examples are Windows only, since they call the Windows API.

### Working on the bindings

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install meson-python meson ninja nanobind
pip install --no-build-isolation -e .
```

An editable install rebuilds with ninja on import, so **activate `.venv` to use the module
as well** - meson and ninja have to be on PATH, and an import from a bare environment
fails in the rebuild instead. Set `MESONPY_EDITABLE_SKIP` to the build directory
(`build/cp314`) to turn the rebuild off; note that it disables the import hook altogether,
so the package is then not importable from the source tree at all.

nanobind is statically linked as a subproject, so the pip `nanobind` package is only used
to generate the type stubs. The stubs (`python/winmd/**/*.pyi`) are checked in; regenerate
them after changing the bindings.

```bash
python -m nanobind.stubgen -m winmd._winmd -r -O python/winmd -M python/winmd/py.typed
```

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
- **`Value()` and `Signature()` return objects that own what they hand out.** Keep the
  signature or the attribute value in a variable while iterating `Params()` or
  `FixedArgs()`.
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

## Module layout

| C++ | Python |
| --- | --- |
| `winmd::reader` | `winmd.reader` (also re-exported from `winmd`) |
| `winmd::reader::TypeDef` | `winmd.reader.TypeDef` |
| `table<TypeDef>` | `winmd.reader.TypeDef_table` |
| `std::pair<TypeDef, TypeDef>` (a range) | `winmd.reader.TypeDef_range` |
| `coded_index<TypeDefOrRef>` | `winmd.reader.coded_index_TypeDefOrRef` |
| `cache::namespace_members` | `winmd.reader.cache.namespace_members` |
| `std::list<database>` (`cache::databases()`) | `winmd.reader.database_list` |
| `std::map<std::string_view, namespace_members>` | `winmd.reader.namespace_map` (read only) |
| `std::map<std::string_view, TypeDef>` | `winmd.reader.type_map` (read only) |

Method and argument names are the C++ ones (`TypeNamespace()`, `MethodList()`,
`find_required()`, `get_enum_definition()`, ...). Nothing is turned into a property, so
accessors are called just like in C++: `type.TypeName()`.

### Type mapping

| C++ | Python |
| --- | --- |
| `std::string_view` / `std::string` | `str` (copied) |
| `std::u16string_view` (`Constant::ValueString`) | `str` (through a caster of our own) |
| `char16_t` (`Constant::ValueChar`) | a one character `str` (through a caster of our own) |
| `std::vector<T>` | `list[T]` (copied) |
| `std::pair<A, B>` | `tuple` |
| `std::optional<T>` / `std::nullptr_t` | `T` or `None` |
| `std::variant<...>` (`TypeSig::Type()`, `Constant::Value()`, `ElemSig::value`) | the corresponding Python object |
| `enum class` | `enum.IntEnum` (`enum.IntFlag` for the ones holding bit combinations) |
| `byte_view` | `winmd.reader.byte_view` (`len()`, `bytes()`, `[]`) |

### What is bound

- all 38 metadata table row types and their accessors (`schema.h` / `column.h`)
- the 13 `coded_index<T>` kinds, `table<T>`, `table_base` and `database` (every table is
  exposed as a member)
- the signature parsers: `TypeSig`, `ParamSig`, `RetTypeSig`, `MethodDefSig`, `FieldSig`,
  `PropertySig`, `TypeSpecSig`, `CustomModSig`, `GenericTypeInstSig`, `GenericTypeIndex`,
  `GenericMethodTypeIndex`
- the custom attribute decoder: `CustomAttributeSig`, `FixedArgSig`, `NamedArgSig`,
  `ElemSig` (`ElemSig.SystemType`, `ElemSig.EnumValue`), `EnumDefinition`
- `cache` (constructor with a type filter, `add_database`, `find`, `find_required`,
  `namespaces`, `databases`, `nested_types`, `remove_type`) and `filter`
- the 10 flag structs (`TypeAttributes` and friends) and `AssemblyVersion`
- the free functions: `get_type_namespace_and_name`, `get_base_class_namespace_and_name`,
  `extends_type`, `is_nested`, `find`, `find_required`, `is_const`, `get_attribute`,
  `get_category`, `enum_mask`, `begin`, `end`, `size`, `empty`, `distance`,
  `uncompress_unsigned`, `read_*`, `parse_*`

## Differences from the C++ interface

- **Ranges (`std::pair<Row, Row>`)** become `Row_range` objects. They keep `.first` and
  `.second` and add `len()`, `[]` and iteration. `begin(r)`, `end(r)`, `size(r)`,
  `empty(r)` and `distance(r)` work as before.
- **Rows are iterators too**, so `row + 1`, `row - 1`, `row_a - row_b`, the comparison
  operators, `bool(row)` and `hash(row)` are available.
- **The getter and setter of the `Attributes` structs share a name** and are selected by
  the argument count: `flags.Static()` reads, `flags.Static(True)` writes.
- **The `None` enumerator** is a Python keyword and becomes `None_`
  (`GenericParamVariance.None_`, `AssemblyHashAlgorithm.None_`).
- **Template arguments are part of the name** (`coded_index_TypeDefOrRef`, `Field_table`).
- **`get_row<Row>()` is spelled as a method named after the row type**
  (`index.TypeDef()`, `index.MemberRef()`, ...). The same accessors are added to the
  coded indexes the C++ side does not define them for (`HasCustomAttribute` and others).
  A type tag mismatch raises instead of tripping the C++ assert.
- **Calling an accessor on an invalid row** (a default constructed `TypeDef()`, say) is
  undefined behaviour in C++ and raises `RuntimeError` here. Test rows with `bool(row)`.
- **Enums are real Python enums** (that is how nanobind models them), so returning a value
  that is not a declared enumerator raises `ValueError`. `CallingConvention`,
  `AssemblyFlags` and `GenericParamSpecialConstraint` hold bit combinations and are
  `enum.IntFlag`, which accepts composites such as `Property | HasThis`.
- **`byte_view` does not implement the buffer protocol** (nanobind has no `def_buffer`).
  Use `bytes(view)` or `view.as_bytes()` for a copy.
- **Lifetime**: rows, indexes, signatures and `byte_view` point into the memory mapped
  file owned by a `database` / `cache`. nanobind's `keep_alive` keeps the owner alive for
  as long as anything derived from it lives, so dropping the `cache` from a local variable
  is safe. Values returned as a `list` (`Params()`, `FixedArgs()`, `nested_types()`, ...)
  and an enum returned by `TypeSig.Type()` carry no such link, so keep the `cache` around
  like you would in C++.
- **`namespaces()` and `types`** are read only mapping views (their keys are
  `string_view`s pointing into the metadata). They support `len`, `in`, `[]`, `get`,
  `keys()`, `values()`, `items()` and iteration.

## Behaviour inherited from the C++ library

- `TypeDef.is_enum()` and `extends_type()` read the base class (`Extends()`), so calling
  them on an interface without a base raises, exactly like the C++ code does. Check
  `if type.Extends():` first.
- `CustomAttribute.Value()` resolves enum arguments through the `cache`. Without
  `mscorlib` and friends loaded this raises `ValueError`, for instance
  `Type 'System.Runtime.InteropServices.CallingConvention' could not be found`
  (the C++ `throw_invalid`).
- `read_*`, `uncompress_unsigned` and `parse_*` advance the `byte_view` that is passed in
  (the C++ `byte_view&`).

## Examples

`examples/` holds programs written on top of the bindings. Each documents itself, so read
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
python tests/test_winmd.py
```

45 tests read the real winmd files under `metadata/` (Windows SDK Contract and
Win32Metadata); run `fetch-metadata.py` first, or point `WINMD_METADATA` at a directory
that has them - the files are ordinary data, so the tests pass off Windows as well.

## Files

```
meson.build          Meson build definition (meson-python backend)
subprojects/*.wrap   where the C++ library, nanobind and robin-map come from
fetch-metadata.py    downloads the .winmd files the tests read from NuGet
src/bind.h           shared definitions (table macros, range wrapper, keep_alive, casters)
src/module.cpp       module definition
src/enums.cpp        enum.h / flags.h / AssemblyVersion
src/view.cpp         view.h (byte_view, file_view) and the blob reading helpers
src/rows.cpp         the 38 row types of schema.h / column.h
src/indexes.cpp      the 13 coded_index<T> kinds
src/tables.cpp       table_base / table<T> / ranges / database
src/signatures.cpp   signature.h / custom_attribute.h / EnumDefinition
src/cache.cpp        cache.h / filter.h
src/helpers.cpp      type_helpers.h / helpers.h / get_attribute / get_category
python/winmd/        the Python package (thin wrapper over the extension plus stubs)
examples/            programs written on the bindings, each documented in itself
```
