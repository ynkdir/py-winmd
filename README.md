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

Requirements: Windows, Visual Studio (C++ workload), Python 3.9+.
The build uses [Meson and meson-python](https://nanobind.readthedocs.io/en/latest/meson.html).

### All in one

```powershell
.\bootstrap.ps1
.\.venv\Scripts\Activate.ps1
python tests\test_winmd.py
```

`bootstrap.ps1` creates `.venv`, installs the build dependencies (meson-python, meson,
ninja, nanobind), fetches the Meson wraps and performs an editable install with the MSVC
toolchain. Pass `-Wheel` to build a redistributable wheel into `dist/` instead.

### By hand

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install meson-python meson ninja nanobind

# nanobind and robin-map go into subprojects/ (only the .wrap files are checked in)
meson wrap install robin-map
meson wrap install nanobind

# from a VS Developer PowerShell, or after running vcvars64.bat
pip install --no-build-isolation -e .
```

The editable install rebuilds with ninja on import, so **activate `.venv` to use the
module as well** (meson and ninja have to be on PATH). Set `MESONPY_EDITABLE_SKIP` to the
build directory (`build/cp314`) to suppress the rebuild. If you see
`vswhere.exe is not recognized`, add `%ProgramFiles(x86)%\Microsoft Visual Studio\Installer`
to PATH or work from a VS Developer PowerShell; it does not affect the build.

nanobind is statically linked as a Meson subproject (WrapDB), so the pip `nanobind`
package is only used to generate the type stubs. The stubs (`python/winmd/**/*.pyi`) are
checked in; regenerate them after changing the bindings.

```bash
python -m nanobind.stubgen -m winmd._winmd -r -O python/winmd -M python/winmd/py.typed
```

## Getting the NuGet content

Neither the C++ headers that are wrapped nor the `.winmd` files are part of this
repository. Both come from NuGet.

```powershell
.\fetch-packages.ps1                  # both
.\fetch-packages.ps1 -Kind library    # only the headers needed to build
.\fetch-packages.ps1 -Kind metadata   # only the .winmd files used by the tests
```

| Target directory | NuGet package | Used for |
| --- | --- | --- |
| `winmd\` | `Microsoft.Windows.WinMD` | building (the wrapped C++ headers) |
| `metadata\Microsoft.Windows.SDK.Contract` | `Microsoft.Windows.SDK.Contracts` | tests (WinRT contracts) |
| `metadata\Microsoft.Windows.SDK.Win32Metadata` | `Microsoft.Windows.SDK.Win32Metadata` (prerelease) | tests (Win32 API) |

`nuget.exe` is taken from PATH and downloaded to `.tools\nuget.exe` when it is missing.
Directories that are already populated are skipped, so pass `-Force` to refresh them.
`bootstrap.ps1` runs `-Kind library` before building. The tests look the metadata up
through the `WINMD_METADATA` environment variable and skip when it is not there.

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

### `examples/dump.py` - dump any metadata in a C# like syntax

```bash
# list the namespaces
python examples/dump.py "metadata/Microsoft.Windows.SDK.Contract/*.winmd"

# a single type
python examples/dump.py --type Windows.Foundation.Uri "metadata/**/*.winmd"

# a whole namespace
python examples/dump.py --namespace Windows.Win32.UI.WindowsAndMessaging "metadata/**/*.winmd"
```

### `examples/dumpwin32.py` - dump Win32 API signatures in a C like syntax

Prints functions (with their DLL and entry point), structs and unions, enums, constants,
callbacks and COM interfaces.

```bash
python examples/dumpwin32.py --list                              # list the namespaces
python examples/dumpwin32.py --namespace UI.WindowsAndMessaging  # a whole namespace
python examples/dumpwin32.py --search "^CreateWindowEx"          # search every namespace
python examples/dumpwin32.py --search "^MSG$" --kind struct      # restrict the kind
```

```c
HWND CreateWindowExW([in] WINDOW_EX_STYLE dwExStyle, [in, opt] PWSTR lpClassName, ...); // USER32.dll

struct INPUT {
    union _Anonymous_e__Union {
        MOUSEINPUT mi;
        KEYBDINPUT ki;
        HARDWAREINPUT hi;
    };
    INPUT_TYPE type;
    _Anonymous_e__Union Anonymous;
};

interface IStream : ISequentialStream { // {0000000c-0000-0000-c000-000000000046}
    HRESULT Seek([in] long dlibMove, [in] STREAM_SEEK dwOrigin, [out, opt] ulong* plibNewPosition);
    ...
};

const uint WM_CREATE = 1;
typedef LRESULT (*WNDPROC)(HWND param0, uint param1, WPARAM param2, LPARAM param3);
```

The DLL and entry point are read straight out of the `ImplMap` and `ModuleRef` tables with
`row.get_value(column)` and `database.get_string()`, because the C++ side has no accessors
for those two tables either.

### `examples/ctypes_gen.py` - generate a module usable with ctypes

Collects everything the selected functions, types and constants need (structs, unions,
typedefs, enums, callbacks) recursively and writes a module that can be imported and
called as it is.

```bash
# just the functions you need; the types they use come along
python examples/ctypes_gen.py --function GetCursorPos --function EnumWindows -o w32.py

# a whole namespace
python examples/ctypes_gen.py --namespace Windows.Win32.UI.WindowsAndMessaging -o user32.py
```

```python
import ctypes, w32

point = w32.POINT()
w32.GetCursorPos(ctypes.byref(point))
print(point.x, point.y)

@w32.WNDENUMPROC
def collect(hwnd, lparam):
    return True

w32.EnumWindows(collect, 0)
print(w32.MB_ICONINFORMATION, w32.SM_CXSCREEN)      # enums are IntEnum/IntFlag
```

COM interfaces are generated as classes that dispatch through the vtable.

```bash
python examples/ctypes_gen.py --function SHCreateMemStream --type IStream -o com.py
```

```python
import ctypes, com

stream = com.SHCreateMemStream(None, 0)             # returns an IStream
written = ctypes.c_uint32()
stream.Write(b"hello", 5, ctypes.byref(written))    # vtable slot 3
stream.Seek(0, com.STREAM_SEEK.STREAM_SEEK_SET, None)

unknown = com.IUnknown()
stream.QueryInterface(ctypes.byref(com.IUnknown._iid_), ctypes.byref(unknown))
unknown.Release()
stream.Release()                                    # inherited from IUnknown
```

What the generator emits:

| Item | Generated as |
| --- | --- |
| structs and unions | `Structure` / `Union`. The classes are declared before their `_fields_` are assigned (the metadata has cycles); by-value dependencies are sorted topologically and the `PackingSize` of `ClassLayout` becomes `_pack_` |
| anonymous unions | registered in `_anonymous_`, so their members are reachable directly |
| enums | `IntEnum` / `IntFlag` (following `[Flags]`) plus a module constant per member; `argtypes` uses the underlying ctypes type |
| functions | `WinDLL` / `CDLL` and `use_last_error` follow the `MappingFlags` of `ImplMap`; `restype` and `argtypes` are set at import time |
| callbacks | `WINFUNCTYPE` / `CFUNCTYPE` |
| fixed size arrays | `type * N` from the `CountConst` of `NativeArrayInfoAttribute` |
| GUID constants | instances of the `GUID` structure that ships with the generated module |
| COM interfaces | classes deriving from `c_void_p` whose methods go through their vtable slot; the interface hierarchy (`IStream` -> `ISequentialStream` -> `IUnknown`) and the IID (`_iid_`) are preserved |
| `PWSTR` / `PSTR` | replaced with `c_wchar_p` / `c_char_p`, which ctypes handles better |

The DLLs are loaded when the generated module is imported. A whole namespace generated
with `--namespace` can name DLLs that are not installed (`dxcompiler.dll`, for instance)
or functions that the installed version does not export, and then the import fails.
Generating the functions you actually need with `--function` avoids that.

### `examples/win32.py` - the whole API resolved on attribute access

The same ctypes objects as above, but built when a name is looked up instead of being
generated in advance. Nothing has to be selected up front.

```python
import win32

win32.MessageBoxW(None, "hello", "winmd", win32.MB_OK | win32.MB_ICONINFORMATION)
win32.MessageBoxA(None, b"hello", b"winmd", win32.MB_OK)   # the A variants take bytes

point = win32.POINT()
win32.GetCursorPos(win32.byref(point))
print(point.x, point.y)

info = win32.SYSTEM_INFO()
win32.GetSystemInfo(win32.byref(info))
print(info.dwNumberOfProcessors)

stream = win32.SHCreateMemStream(None, 0)                  # COM works too
written = win32.byref(ctypes.c_uint32())
stream.Write(b"hello", 5, written)
stream.Release()
```

The metadata is `Windows.Win32.winmd` from the directory the module lives in. To use it,
drop `win32.py` and that file somewhere on the import path (site-packages, for
instance). To run it straight from this repository, or to read other metadata, name the
files instead:

```python
import win32

win32.configure("metadata/Microsoft.Windows.SDK.Win32Metadata/Windows.Win32.winmd")
```

That first access loads the metadata and indexes every name (functions, types, constants
and enum members) in about 0.3 s. A name is turned into a ctypes object once and stored in
the module, so later uses are plain attribute lookups. `dir(win32)` lists what is available
(240,107 names with both metadata packages of this repository) and
`win32.namespace_of("MessageBoxA")` tells you where a name came from. The Win32 namespaces
are indexed first, so they win the 231 names - all of them enum members like `All` or
`Aborted` - that the WinRT contracts define as well.

A DLL is loaded the first time one of its functions is used, so a function whose DLL is
not installed raises then and there instead of at import time. Unknown names raise
`AttributeError`.

### `examples/winrt.py` - WinRT resolved on attribute access

The same idea for WinRT, which needs rather more than a vtable call: activation factories,
HSTRING, and the `[out, retval]` calling convention.

```python
import winrt

winrt.init()                                              # RoInitialize

uri = winrt.Windows.Foundation.Uri("https://example.com/a/b?x=1")
print(uri.Domain, uri.Path, uri.Query)                    # get_X as properties
print(uri.ToString())                                     # IStringable, through QueryInterface
print(winrt.Windows.Foundation.Uri.EscapeComponent("a b"))  # a static member

calendar = winrt.Windows.Globalization.Calendar()         # ActivateInstance
print(calendar.Year, calendar.Month, repr(calendar.DayOfWeek))

document = winrt.Windows.Data.Json.JsonObject.Parse('{"name": "winmd"}')
print(document.GetNamedString("name"), document.Stringify())

# parameterized interfaces: the collections behave like Python containers
for tag in winrt.Windows.Globalization.ApplicationLanguages.Languages:  # IVectorView<String>
    print(tag)

array = winrt.Windows.Data.Json.JsonArray.Parse("[1, 2, 3]")            # IVector<IJsonValue>
print(len(array), array[0].GetNumber(), [value.Stringify() for value in array])

properties = winrt.Windows.Foundation.Collections.PropertySet()         # IMap<String, Object>
properties["name"] = winrt.Windows.Data.Json.JsonValue.CreateStringValue("winmd")
print(len(properties), list(properties.keys()), "name" in properties)

# an asynchronous operation can be waited for, or handed a callback
DeviceInformation = winrt.Windows.Devices.Enumeration.DeviceInformation
devices = DeviceInformation.FindAllAsync().get()
print(len(devices), devices[0].Name)

# a Python callable becomes a delegate, which is what events need
watcher = DeviceInformation.CreateWatcher()
token = watcher.add_Added(lambda sender, device: print(device.Name))
watcher.add_EnumerationCompleted(lambda sender, argument: print("done"))
watcher.Start()
...
watcher.remove_Added(token)

IVector = winrt.Windows.Foundation.Collections.IVector   # closing a generic by hand
print(IVector[str]._iid_)                                # {98b9acc1-4b56-532e-ac73-03d5291cca90}
```

| Item | How it is built |
| --- | --- |
| metadata | `C:\Windows\System32\WinMetadata\*.winmd`, the metadata of the running system; `configure(*files)` overrides it |
| namespaces | `winrt.Windows.Foundation` walks the namespaces of the cache (WinRT names collide too often for one flat namespace) |
| vtable | an interface starts at slot 6: the metadata lists none of the IInspectable members, they are implicit |
| calls | the ABI is `HRESULT method(this, args..., out retval)`; the wrapper allocates the out slot, raises `WinRTError` on failure and returns the value |
| strings | `WindowsCreateString` / `WindowsGetStringRawBuffer` around every `String` parameter and result |
| runtime classes | a subclass of the `[default]` interface; `ActivatableAttribute` gives the factory interfaces (or `IActivationFactory.ActivateInstance` when it names none) and `StaticAttribute` the static ones |
| other interfaces | `QueryInterface` on attribute miss, so `uri.ToString()` finds `IStringable`; an interface can require others (`IPropertySet` requires `IMap<String, Object>`) and those are followed too |
| enums, structs | `IntEnum` / `IntFlag` and `Structure`, as in the ctypes generator |
| out parameters | a method with several out parameters returns a tuple, `found, index = vector.IndexOf(x)` |
| parameterized interfaces | the IID of `IVector<Uri>` is the RFC 4122 name based UUID of its type signature - `pinterface({913337e9-…};rc(Windows.Foundation.Uri;{9e365e57-…}))` - which is what makes `QueryInterface` for a closed generic possible; `IVector[Uri]` closes one by hand |
| collections | `IIterable`, `IIterator`, `IVector`, `IVectorView`, `IMap`, `IMapView` and `IKeyValuePair` get `len()`, `[]`, `in`, iteration, `keys()` / `values()` / `items()` and `append` |
| async | `IAsyncOperation<T>.get()` waits by polling `IAsyncInfo.Status` and then calls `GetResults`, or `put_Completed` takes a callback |
| delegates | a Python callable passed where a delegate is expected becomes a COM object of its own: a four slot vtable (`QueryInterface`, `AddRef`, `Release`, `Invoke`) built with `WINFUNCTYPE`, answering for `IUnknown`, `IAgileObject` and its own IID, reference counted so that it stays alive exactly as long as the runtime holds it |
| events | `add_X` / `remove_X` with the `EventRegistrationToken` they return; the arguments of a callback are converted back into Python, and interface pointers are given a reference of their own |
| arrays | an array is two ABI parameters, a length and the data, in three flavours: a sequence goes in (`ReplaceAll([...])`), a list is filled in place, its length being the capacity (`items = [None] * 8; count = view.GetMany(0, items)`) or an allocated one comes back and is freed with `CoTaskMemFree` (`crypto.CopyToByteArray(buffer)`) |
| `Object` | an `IInspectable` result asks `GetRuntimeClassName` what it is and casts itself to that class, so `PropertyValue.CreateInspectable(uri).Domain` works; `_as(interface)` covers what that cannot resolve, such as a boxed value |

Not covered: multidimensional arrays, and a delegate is agile but not marshalable - enough
for the thread pool apartments callbacks arrive on.

One subtlety worth writing down: the signature of a runtime class is
`rc(<name>;<signature of its default interface>)`, and when that default interface is itself
parameterized the `pinterface(...)` form has to go in, not its IID.
`DeviceInformationCollection` is such a class (`IVectorView<DeviceInformation>`), and getting
it wrong means the IID computed for `AsyncOperationCompletedHandler<DeviceInformationCollection>`
is wrong, the runtime's `QueryInterface` on the handler fails, and the callback silently never
arrives.

Every one of the 14,694 types in the system metadata resolves in about two seconds: 4,545
runtime classes, 8,052 interfaces, 39,665 methods, 16,977 properties, and the 4,642 closed
parameterized interfaces they mention (918 `TypedEventHandler<T, U>`, 666 `IIterable<T>`,
627 `IAsyncOperation<T>`, 576 `IVectorView<T>`, ...). Not one method of a non-generic
interface fails to build (33,589 of them).

## Tests

```bash
python tests/test_winmd.py
```

45 tests read the real winmd files under `metadata/` (Windows SDK Contract and
Win32Metadata); run `fetch-packages.ps1` first.

## Files

```
meson.build          Meson build definition (meson-python backend)
subprojects/*.wrap   where nanobind and robin-map come from (WrapDB)
bootstrap.ps1        sets up .venv and builds
fetch-packages.ps1   downloads the C++ headers and the .winmd files from NuGet
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
examples/dump.py        dumps any metadata in a C# like syntax
examples/dumpwin32.py   dumps Win32 API signatures in a C like syntax
examples/ctypes_gen.py  generates a ctypes module from the Win32 metadata
examples/win32.py       the Win32 API resolved on attribute access
examples/winrt.py       WinRT resolved on attribute access
```
