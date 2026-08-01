# `winmd::reader` - the C++ metadata parser

Notes on the library this project was ported from: [Microsoft.Windows.WinMD](https://github.com/microsoft/winmd),
a header-only C++17 reader for Windows Metadata. It ships as the NuGet package
`Microsoft.Windows.WinMD` and has no documentation of its own beyond the headers, so this
is what reading them turned up. Version 1.0.260529.3 is
what it describes; every snippet here was compiled with `g++ -std=c++17 -Wall` and run
against `Windows.Win32.winmd` and `Windows.Foundation.FoundationContract.winmd`.

Written with [Claude](https://claude.com/claude-code) from the headers of that version.

Everything lives in `namespace winmd::reader`, and one include pulls the whole thing in:

```cpp
#include "winmd_reader.h"
```

There is nothing to build or link. `impl/base.h` includes `<windows.h>` on Windows and
`<sys/mman.h>` elsewhere, which is the only platform dependent part: the file is mapped,
never copied. C++17 is required - the interface is built on `std::string_view`,
`std::variant` and structured bindings.

A `.winmd` file is a PE image whose only real content is the ECMA-335 metadata that a
.NET assembly carries, so this is an ECMA-335 reader with WinRT conveniences on top.
[ECMA-335](https://ecma-international.org/publications-and-standards/standards/ecma-335/)
partition II is the reference for what the tables mean; this library is a faithful, almost
transparent view of them.

## The 30-second tour

```cpp
#include "winmd_reader.h"
#include <cstdio>

using namespace winmd::reader;

int main()
{
    cache db{ std::vector<std::string>{ "Windows.Win32.winmd" } };

    TypeDef type = db.find_required("Windows.Win32.UI.WindowsAndMessaging", "MSG");

    printf("%.*s.%.*s is a %s\n",
        (int)type.TypeNamespace().size(), type.TypeNamespace().data(),
        (int)type.TypeName().size(), type.TypeName().data(),
        get_category(type) == category::struct_type ? "struct" : "something else");

    for (auto&& field : type.FieldList())
    {
        printf("  %.*s\n", (int)field.Name().size(), field.Name().data());
    }
}
```

`std::string_view` is what the library returns everywhere, and it points straight into the
mapped file - hence the `%.*s`. Nothing is copied and nothing is allocated per string.

## The model

```
file  ->  database  ->  table<Row>  ->  Row  ->  columns
                   \                        \
                    38 tables                coded_index, signature blobs, strings
```

- **`database`** is one `.winmd` file: 38 tables plus the string, blob, guid and userstring
  heaps.
- **`cache`** owns a set of databases and indexes their types by namespace and name. This
  is what resolves a `TypeRef` in one file to the `TypeDef` in another, so nearly every
  program wants one.
- **rows** (`TypeDef`, `MethodDef`, `Field`, ...) are two words: a pointer to the table and
  a row index. They are values - copy them freely - and they are also random access
  iterators over their own table.

### `database`

```cpp
static bool database::is_database(std::string_view path);      // cheap PE + metadata check

explicit database(std::string_view path, cache const* = nullptr);
explicit database(std::vector<uint8_t>&& buffer, cache const* = nullptr);
```

A database is neither copyable nor movable, which is why `cache` keeps them in a
`std::list`. Every table is a public member, named after the table:

```cpp
database db{ "Windows.Win32.winmd" };

printf("%u types, %u methods\n", db.TypeDef.size(), db.MethodDef.size());

for (auto&& type : db.TypeDef) { /* ... */ }     // tables are ranges
TypeDef first = db.TypeDef[0];                   // and are indexable
```

Also useful: `db.path()`, `db.get_cache()`, `db.get_string(index)`, `db.get_blob(index)`,
and `db.get_table<TypeDef>()` when the table is a template parameter.

Reading a database directly is fine when the file is self-contained. As soon as a type
refers to something in another file - and `Windows.Win32.winmd` refers to `System.Guid`,
every WinRT class refers to its interfaces - a `cache` is what resolves it.

### `cache`

```cpp
cache();                                                  // empty, fill with add_database
explicit cache(std::string const& file);
explicit cache(C const& files);                           // any container of paths
explicit cache(C const& files, TypeFilter filter);        // filter is bool(TypeDef const&)

void add_database(std::string_view file);
void add_database(std::string_view file, TypeFilter filter);
```

Building one walks every `TypeDef` in every file and files it under its namespace. Types
whose `Flags().value` is 0 (the `<Module>` pseudo-type) and nested types are skipped, and
so is anything the filter rejects.

```cpp
cache c{ files };

TypeDef t = c.find("Windows.Foundation", "IAsyncAction");   // {} when not found
TypeDef u = c.find("Windows.Foundation.IAsyncAction");      // same, dotted
TypeDef v = c.find_required("Windows.Foundation", "Uri");   // throws instead of returning {}

for (auto&& [name, members] : c.namespaces())
{
    printf("%.*s: %zu types\n", (int)name.size(), name.data(), members.types.size());
}
```

`namespaces()` is a `std::map<std::string_view, namespace_members>`, and
`namespace_members` is the same set of types sliced by kind:

```cpp
struct namespace_members
{
    std::map<std::string_view, TypeDef> types;   // everything, by name
    std::vector<TypeDef> interfaces;
    std::vector<TypeDef> classes;
    std::vector<TypeDef> enums;
    std::vector<TypeDef> structs;
    std::vector<TypeDef> delegates;
    std::vector<TypeDef> attributes;   // classes deriving from System.Attribute
    std::vector<TypeDef> contracts;    // structs with ApiContractAttribute
};
```

The rest of the surface: `databases()`, `nested_types(TypeDef)` (the types nested inside
one, from the `NestedClass` table) and `remove_type(ns, name)`, which drops a type from the
per-kind vectors - a projection's way of saying "I handle this one myself".

**The cache must outlive everything taken out of it.** Rows point at tables, tables point
at the mapped file, and the string views point into it. `add_database` is documented not to
invalidate existing rows, but it can invalidate references into `namespaces()`.

### `filter`

`filter` turns a list of include and exclude prefixes into a predicate, longest prefix
first, which is what code generators use to carve out a subset of the metadata:

```cpp
filter f{ std::vector<std::string>{ "Windows.Foundation" },      // includes
          std::vector<std::string>{ "Windows.Foundation.Metadata" } };  // excludes

f.includes(type);                       // TypeDef, or "Namespace.Name"
f.includes(members);                    // any type in a namespace survives
f.bind_each<...>(...);                  // helpers for walking what is left
```

With no rules at all everything is included.

## Rows

Every row derives from `row_base<Row>` and gets:

| | |
| --- | --- |
| `explicit operator bool()` | false for a default constructed (invalid) row |
| `index()` | the zero based row index |
| `get_database()`, `get_cache()` | where it came from |
| `coded_index<T>()` | this row as a coded index of kind `T` |
| `++`, `--`, `+`, `-`, `[]`, `==`, `<` | it is a random access iterator over its table |

The iterator part is what makes ranges work: a range of rows is a
`std::pair<Row, Row>` of begin and end, and `TypeDef::MethodList()` and friends return one.

```cpp
auto methods = type.MethodList();
for (auto&& method : methods) { /* ... */ }

size(methods);     // std::size_t          - winmd::reader::size
empty(methods);    // bool
begin(methods); end(methods);
```

A row range is safe to iterate straight out of the accessor, because a row is a value that
carries its own table pointer. **A range over parsed data is not** - see the lifetime note
below, it is the one way to get this wrong.

**Calling an accessor on an invalid row is undefined behaviour**, not an exception: the
assert that catches it is compiled out in release builds. Anything that can fail to find a
row returns a default constructed one, so test with `if (type)` before using it.

### Coded indexes

Some columns can point at more than one table; ECMA-335 encodes the table in the low bits.
`coded_index<T>` is that column, `T` being one of `TypeDefOrRef`, `HasConstant`,
`HasCustomAttribute`, `HasFieldMarshal`, `HasDeclSecurity`, `MemberRefParent`,
`HasSemantics`, `MethodDefOrRef`, `MemberForwarded`, `Implementation`,
`CustomAttributeType`, `ResolutionScope` or `TypeOrMethodDef`.

```cpp
coded_index<TypeDefOrRef> extends = type.Extends();

if (extends.type() == TypeDefOrRef::TypeRef)
{
    TypeRef base = extends.TypeRef();       // get_row<TypeRef>() by another name
}
```

`type()` is the tag, `index()` the row, and `get_row<Row>()` (or the named accessor)
returns the row. **Asking for the wrong row type asserts** - check `type()` first. An
unset column gives a coded index that is false in a boolean context.

Two free functions do the common thing, which is "give me the definition, wherever it is":

```cpp
TypeDef base = find(extends);            // {} when it cannot be resolved
TypeDef base = find_required(extends);   // throws instead
```

They follow a `TypeRef` through the cache to the `TypeDef` in whichever file defines it.

## The tables

All 38 are there. The ones a reader actually touches:

| Table | What it holds | Notable accessors |
| --- | --- | --- |
| `TypeDef` | a type | `TypeName`, `TypeNamespace`, `Flags`, `Extends`, `FieldList`, `MethodList`, `PropertyList`, `EventList`, `InterfaceImpl`, `GenericParam`, `MethodImplList`, `EnclosingType`, `CustomAttribute` |
| `MethodDef` | a method | `Name`, `Flags`, `ImplFlags`, `Signature`, `ParamList`, `Parent`, `RVA`, `GenericParam` |
| `Field` | a field | `Name`, `Flags`, `Signature`, `Constant`, `Parent`, `FieldMarshal` |
| `Param` | a parameter | `Name`, `Flags`, `Sequence`, `Constant` |
| `Property`, `Event` | a property or event | `Name`, `Flags`, `Type`, `MethodSemantic`, `Parent` |
| `MethodSemantics` | which method is a getter, setter, adder... | `Semantic`, `Method`, `Association` |
| `InterfaceImpl` | "this type implements that interface" | `Class`, `Interface` |
| `CustomAttribute` | an attribute application | `Parent`, `Type`, `Value`, `TypeNamespaceAndName` |
| `Constant` | a literal value | `Type`, `Parent`, `Value`, `ValueInt32`, `ValueString`, ... |
| `TypeRef` | a reference to a type elsewhere | `TypeName`, `TypeNamespace`, `ResolutionScope` |
| `TypeSpec` | an instantiated generic | `Signature` |
| `NestedClass` | nesting | `NestedType`, `EnclosingType` |
| `GenericParam`, `GenericParamConstraint` | type parameters | `Name`, `Number`, `Flags`, `Owner`, `Constraint` |
| `ImplMap`, `ModuleRef` | P/Invoke: which DLL and entry point | `MappingFlags`, `MemberForwarded`, `ImportName`, `ImportScope` |
| `ClassLayout`, `FieldLayout` | explicit layout | `PackingSize`, `ClassSize`, `Parent` |
| `Assembly`, `AssemblyRef`, `Module`, `ModuleRef` | identity | `Name`, `Version`, `Flags` |

The rest (`DeclSecurity`, `FieldRVA`, `File`, `ExportedType`, `ManifestResource`,
`StandAloneSig`, `MethodSpec`, `MethodImpl`, `EventMap`, `PropertyMap`, `AssemblyOS`,
`AssemblyProcessor`, `AssemblyRefOS`, `AssemblyRefProcessor`, `FieldMarshal`) are bound too
and follow the same shape.

Where ECMA-335 stores a range as "my first child until the next row's first child", the
accessor hands back the range directly: `TypeDef::MethodList()`, `FieldList()`,
`ParamList()`, `PropertyList()`, `EventList()`. Where it stores a back pointer, the
accessor searches for it: `MethodDef::Parent()`, `Field::Parent()`.

### Flags

Attribute columns come back as small structs with one named accessor per bit, each of
which both reads and writes:

```cpp
TypeAttributes flags = type.Flags();

flags.Semantics() == TypeSemantics::Interface;
flags.Visibility() == TypeVisibility::Public;
flags.Layout() == TypeLayout::SequentialLayout;
flags.value;                                     // the raw uint32_t

MethodAttributes m = method.Flags();
m.SpecialName(); m.Static(); m.Abstract();

FieldAttributes f = field.Flags();
f.Literal(); f.Static();                         // an enum member is both

ParamAttributes p = param.Flags();
p.In(); p.Out(); p.Optional();
```

The structs are `AssemblyAttributes`, `EventAttributes`, `FieldAttributes`,
`GenericParamAttributes`, `MethodAttributes`, `MethodImplAttributes`,
`MethodSemanticsAttributes`, `ParamAttributes`, `PropertyAttributes` and `TypeAttributes`.

## Signatures

Signatures are compressed blobs, and the library parses them into a small tree. The entry
points are `MethodDef::Signature()` (a `MethodDefSig`), `Field::Signature()` (a `FieldSig`),
`Property::Type()` (a `PropertySig`) and `TypeSpec::Signature()` (a `TypeSpecSig`).

```cpp
MethodDefSig sig = method.Signature();   // by value, and it owns what Params() returns

sig.CallConvention();      // CallingConvention, a bit field - use enum_mask
sig.GenericParamCount();
sig.ReturnType();          // RetTypeSig, false in a boolean context for void
sig.Params();              // std::pair of ParamSig iterators
```

`ParamSig` and `RetTypeSig` each carry `Type()` (a `TypeSig`) and `ByRef()`.

### `TypeSig`

The interesting one. `TypeSig::Type()` is a variant of five alternatives:

```cpp
using value_type = std::variant<
    ElementType,                 // a primitive: I4, String, Boolean, Object, ...
    coded_index<TypeDefOrRef>,   // a named type - resolve with find()
    GenericTypeIndex,            // !0, !1 - the type's own parameter
    GenericTypeInstSig,          // IVector<Uri> and the like
    GenericMethodTypeIndex>;     // !!0 - a method's parameter
```

and around it sit the modifiers:

```cpp
sig.element_type();     // the leading ElementType byte
sig.is_szarray();       // T[]
sig.is_array();         // multidimensional, with array_rank() / array_sizes()
sig.ptr_count();        // levels of pointer indirection
```

So printing a type is a `std::visit`:

```cpp
void print(TypeSig const& sig, cache const& c)
{
    std::visit(overloaded{
        [](ElementType t) { printf("<primitive %d>", (int)t); },
        [&](coded_index<TypeDefOrRef> const& index)
        {
            auto [ns, name] = get_type_namespace_and_name(index);
            printf("%.*s.%.*s", (int)ns.size(), ns.data(), (int)name.size(), name.data());
        },
        [](GenericTypeIndex i) { printf("!%u", i.index); },
        [&](GenericTypeInstSig const& inst)
        {
            auto [ns, name] = get_type_namespace_and_name(inst.GenericType());
            printf("%.*s.%.*s<", (int)ns.size(), ns.data(), (int)name.size(), name.data());
            for (auto&& arg : inst.GenericArgs()) { print(arg, c); }
            printf(">");
        },
        [](GenericMethodTypeIndex i) { printf("!!%u", i.index); },
    }, sig.Type());

    if (sig.is_szarray()) { printf("[]"); }
    for (int i = 0; i < sig.ptr_count(); ++i) { printf("*"); }
}
```

`GenericTypeInstSig` has `GenericType()` (a `coded_index<TypeDefOrRef>`), `GenericArgs()`
(a pair of `TypeSig` iterators) and `GenericArgCount()`.

`CustomModSig` shows up as `CustomMod()` on the signature types: `modopt`/`modreq`, whose
`Type()` is a `coded_index<TypeDefOrRef>`. Win32 metadata uses it for `const`, which
`is_const(ParamSig const&)` checks for you.

## Constants

`Constant` is the literal behind a field, parameter or property:

```cpp
Constant c = field.Constant();

c.Type();          // ConstantType
c.Value();         // std::variant of every constant type
c.ValueInt32();    // or reach for the one you expect
c.ValueString();   // std::u16string_view - metadata strings are UTF-16 here
```

`Constant::Value()` returning a variant is the safe way; the typed accessors assert if the
type does not match.

## Custom attributes

Every row that can carry attributes has a `CustomAttribute()` range, and one free function
finds a particular attribute:

```cpp
CustomAttribute attribute = get_attribute(type, "Windows.Foundation.Metadata", "GuidAttribute");
if (attribute) { /* ... */ }
```

`CustomAttribute::TypeNamespaceAndName()` gives the attribute's own type, and `Value()`
decodes the argument blob:

```cpp
CustomAttributeSig args = attribute.Value();   // name it: the args below borrow from it

for (auto&& arg : args.FixedArgs())    // positional
{
    ElemSig const& elem = std::get<ElemSig>(arg.value);
    std::visit(..., elem.value);
}

for (auto&& arg : args.NamedArgs())    // named
{
    printf("%.*s = ...\n", (int)arg.name.size(), arg.name.data());
}
```

`ElemSig::value` is a variant of `bool`, `char16_t`, the integer types, `float`, `double`,
`std::string_view`, `ElemSig::SystemType` (a `typeof(...)` argument, carrying `name`) and
`ElemSig::EnumValue`. An `EnumValue` knows the `EnumDefinition` it came from and can be
compared against an enumerator by name:

```cpp
elem.equals_enumerator("Public");
```

Decoding an attribute needs the argument types, which means the attribute's constructor,
which means resolving the attribute class - so this only works with a `cache` that has the
defining file in it. Arguments of a type the cache does not know throw.

### `EnumDefinition`

```cpp
EnumDefinition def = type.get_enum_definition();   // assert()s that type.is_enum()

def.m_underlying_type;              // ElementType::I4 and friends
def.get_enumerator("Aborted");      // the Field row
```

The underlying type is the one field of an enum that is neither literal nor static.

## Helpers worth knowing

| | |
| --- | --- |
| `find(TypeRef)`, `find_required(TypeRef)` | resolve a reference through the cache |
| `find(coded_index<TypeDefOrRef>)`, `find_required(...)` | the same for a column that may be either |
| `get_type_namespace_and_name(coded_index<TypeDefOrRef>)` | the pair, whichever table it points at |
| `get_base_class_namespace_and_name(TypeDef)` | what it extends, `{}` for none |
| `extends_type(TypeDef, ns, name)` | direct base check |
| `is_nested(TypeDef)`, `is_nested(TypeRef)` | visibility based |
| `get_category(TypeDef)` | `interface_type`, `class_type`, `enum_type`, `struct_type`, `delegate_type` |
| `is_const(ParamSig)` | the `const` modopt Win32 metadata uses |
| `enum_mask(value, mask)` | for the bit field enums such as `CallingConvention` |
| `size`, `empty`, `begin`, `end`, `distance` | over a `std::pair` range |
| `uncompress_unsigned`, `uncompress_enum` | the ECMA-335 blob primitives, if you parse yourself |

`get_category` is heuristic in the way WinRT metadata demands: a type is an interface if
its flags say so *or* it carries a `GuidAttribute`; a struct with `ApiContractAttribute` is
a contract; a class deriving from `System.Attribute` is an attribute.

## Recipes

### Every method of a type, with its signature

```cpp
for (auto&& method : type.MethodList())
{
    auto sig = method.Signature();
    printf("%.*s(", (int)method.Name().size(), method.Name().data());

    auto params = method.ParamList();
    for (auto&& param : sig.Params())
    {
        // The Param rows and the signature params line up, except that a Param row
        // with Sequence() == 0 describes the return value.
    }
    printf(")\n");
}
```

The two lists are parallel but not identical: `MethodDef::ParamList()` gives the `Param`
rows (names and flags), `MethodDefSig::Params()` gives the types. Match them by
`Param::Sequence()`, starting at 1, and treat sequence 0 as the return value.

### The DLL and entry point behind a P/Invoke

`ImplMap` has no accessor from `MethodDef`, so walk it once and index it:

```cpp
std::map<uint32_t, std::pair<std::string_view, std::string_view>> imports;

for (auto&& row : db.ImplMap)
{
    auto member = row.get_value<uint32_t>(1);      // MemberForwarded coded index
    if (member & 1)                                // 1 == MethodDef
    {
        auto scope = row.get_value<uint32_t>(3);
        imports[(member >> 1) - 1] = {
            db.get_string(db.ModuleRef[scope - 1].get_value<uint32_t>(0)),
            db.get_string(row.get_value<uint32_t>(2)) };
    }
}
```

`row.get_value<T>(column)` is the escape hatch for columns without a named accessor.

### A GUID from `GuidAttribute`

```cpp
auto attribute = get_attribute(type, "Windows.Foundation.Metadata", "GuidAttribute");

CustomAttributeSig args = attribute.Value();   // named: FixedArgs() borrows from it
std::vector<int64_t> parts;

for (auto&& arg : args.FixedArgs())
{
    std::visit([&](auto&& v)
    {
        if constexpr (std::is_arithmetic_v<std::decay_t<decltype(v)>>)
        {
            parts.push_back((int64_t)v);
        }
    }, std::get<ElemSig>(arg.value).value);
}
// parts is {Data1, Data2, Data3, b0..b7} - eleven values
```

## Things that will bite

- **A range is two iterators, and parsed data is owned by the object it came from.**
  `Signature()`, `Value()`, `Params()`, `FixedArgs()`, `GenericArgs()` and friends hand back
  a `std::pair` of iterators into a `std::vector` inside the signature object. Iterating one
  straight out of a call that returns by value walks freed memory - the temporary dies at
  the end of the full expression, and the range-for keeps only the pair:

  ```cpp
  for (auto&& p : method.Signature().Params()) { ... }     // use after free
  for (auto&& a : attribute.Value().FixedArgs()) { ... }   // use after free

  MethodDefSig sig = method.Signature();                   // right: name it first
  for (auto&& p : sig.Params()) { ... }
  ```

  It usually does not crash; it quietly reads rubbish, and `std::visit` then reports a
  valueless variant. Row ranges (`MethodList()`, `FieldList()`, ...) are exempt: a row is a
  value with a table pointer inside it, and owns nothing.
- **Lifetime.** Every `std::string_view`, every row and every signature borrows from the
  mapped file. Outliving the `cache` (or `database`) is a use after free. Copy into a
  `std::string` if you need to keep it.
- **Invalid rows are undefined behaviour**, not exceptions. `find` returning `{}` is normal;
  using it is not.
- **Coded index accessors assert** on a tag mismatch. Check `type()`.
- **Not thread safe for writing.** Reading a built `cache` from several threads is fine;
  `add_database` while others read is not.
- **`database` is neither copyable nor movable.** Hold it by reference, or let a `cache`
  own it.
- **Undeclared enum values happen.** `CallingConvention`, `AssemblyFlags` and
  `GenericParamSpecialConstraint` are bit fields, and Win32 metadata carries combinations
  no enumerator names. Mask, do not compare.
- **`ValueString()` is UTF-16** (`std::u16string_view`) while every other string is UTF-8
  `std::string_view`.
