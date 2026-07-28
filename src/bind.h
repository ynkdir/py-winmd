// Common infrastructure for the winmd Python bindings (nanobind).
//
// The bindings mirror the C++ interface of winmd::reader as closely as the
// Python object model allows:
//
//   * winmd::reader::X                  -> winmd.reader.X
//   * table<Row>                        -> winmd.reader.Row_table
//   * coded_index<Index>                -> winmd.reader.coded_index_Index
//   * std::pair<Row, Row> (a range)     -> winmd.reader.Row_range (iterable)
//   * std::variant<...>                 -> the corresponding Python object
//   * std::string_view                  -> str (copied)
//   * getter/setter overloads (Flags)   -> same name, argument count selects
//
#pragma once

#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <nanobind/nanobind.h>
#include <nanobind/make_iterator.h>
#include <nanobind/operators.h>

// Only the casters that are included exist, which is how the containers that
// are exposed by reference (std::list<database>, the std::map members of the
// cache) stay opaque: nanobind/stl/list.h and map.h are deliberately not used.
// Teaches nb::class_ that std::list<database> is not really copy constructible
// (database is not), which std::is_copy_constructible alone cannot tell.
#include <nanobind/stl/detail/traits.h>

#include <nanobind/stl/function.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/string_view.h>
#include <nanobind/stl/variant.h>
#include <nanobind/stl/vector.h>

#include "winmd_reader.h"  // the Microsoft.Windows.WinMD headers, a subproject

#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>

namespace nb = nanobind;
using namespace winmd;
using namespace winmd::reader;

NAMESPACE_BEGIN(NB_NAMESPACE)
NAMESPACE_BEGIN(detail)

/// UTF-16 code unit (Constant::ValueChar, ElemSig) -> a one character str.
template <> struct type_caster<char16_t>
{
    NB_TYPE_CASTER(char16_t, const_name("str"))

    bool from_python(handle src, uint8_t, cleanup_list*) noexcept
    {
        if (!PyUnicode_Check(src.ptr()) || PyUnicode_GetLength(src.ptr()) != 1)
        {
            return false;
        }
        auto const ch = PyUnicode_ReadChar(src.ptr(), 0);
        if (ch == static_cast<Py_UCS4>(-1) || ch > 0xffff)
        {
            PyErr_Clear();
            return false;
        }
        value = static_cast<char16_t>(ch);
        return true;
    }

    static handle from_cpp(char16_t value, rv_policy, cleanup_list*) noexcept
    {
        int byte_order = -1; // little endian, no byte order mark
        return PyUnicode_DecodeUTF16(reinterpret_cast<char const*>(&value), 2, "surrogatepass",
            &byte_order);
    }
};

/// UTF-16 string constant (Constant::ValueString) -> str.
template <> struct type_caster<std::u16string_view>
{
    NB_TYPE_CASTER(std::u16string_view, const_name("str"))

    bool from_python(handle, uint8_t, cleanup_list*) noexcept
    {
        return false; // a view would have to point at Python owned memory
    }

    static handle from_cpp(std::u16string_view value, rv_policy, cleanup_list*) noexcept
    {
        int byte_order = -1;
        return PyUnicode_DecodeUTF16(reinterpret_cast<char const*>(value.data()),
            static_cast<Py_ssize_t>(value.size() * 2), "surrogatepass", &byte_order);
    }
};

NAMESPACE_END(detail)
NAMESPACE_END(NB_NAMESPACE)

// Every row, table, coded_index, byte_view and signature ultimately points into
// memory owned by a database (and databases are owned by a cache), so anything
// derived from a Python object must keep that object alive.
#define KA nb::keep_alive<0, 1>()

// The 38 metadata tables, in the order of ECMA-335 II.22.
#define WINMD_ROWS(X)                                                                              \
    X(Module)                                                                                      \
    X(TypeRef)                                                                                     \
    X(TypeDef)                                                                                     \
    X(Field)                                                                                       \
    X(MethodDef)                                                                                   \
    X(Param)                                                                                       \
    X(InterfaceImpl)                                                                               \
    X(MemberRef)                                                                                   \
    X(Constant)                                                                                    \
    X(CustomAttribute)                                                                             \
    X(FieldMarshal)                                                                                \
    X(DeclSecurity)                                                                                \
    X(ClassLayout)                                                                                 \
    X(FieldLayout)                                                                                 \
    X(StandAloneSig)                                                                               \
    X(EventMap)                                                                                    \
    X(Event)                                                                                       \
    X(PropertyMap)                                                                                 \
    X(Property)                                                                                    \
    X(MethodSemantics)                                                                             \
    X(MethodImpl)                                                                                  \
    X(ModuleRef)                                                                                   \
    X(TypeSpec)                                                                                    \
    X(ImplMap)                                                                                     \
    X(FieldRVA)                                                                                    \
    X(Assembly)                                                                                    \
    X(AssemblyProcessor)                                                                           \
    X(AssemblyOS)                                                                                  \
    X(AssemblyRef)                                                                                 \
    X(AssemblyRefProcessor)                                                                        \
    X(AssemblyRefOS)                                                                               \
    X(File)                                                                                        \
    X(ExportedType)                                                                                \
    X(ManifestResource)                                                                             \
    X(NestedClass)                                                                                 \
    X(GenericParam)                                                                                \
    X(MethodSpec)                                                                                  \
    X(GenericParamConstraint)

// The coded index kinds of ECMA-335 II.24.2.6.
#define WINMD_INDEXES(X)                                                                           \
    X(TypeDefOrRef)                                                                                \
    X(HasConstant)                                                                                 \
    X(HasCustomAttribute)                                                                          \
    X(HasFieldMarshal)                                                                              \
    X(HasDeclSecurity)                                                                             \
    X(MemberRefParent)                                                                             \
    X(HasSemantics)                                                                                \
    X(MethodDefOrRef)                                                                              \
    X(MemberForwarded)                                                                              \
    X(Implementation)                                                                              \
    X(CustomAttributeType)                                                                         \
    X(ResolutionScope)                                                                             \
    X(TypeOrMethodDef)

// Row types that have a CustomAttribute() accessor (used for get_attribute).
#define WINMD_ATTRIBUTABLE_ROWS(X)                                                                 \
    X(Module)                                                                                      \
    X(TypeRef)                                                                                     \
    X(TypeDef)                                                                                     \
    X(Field)                                                                                       \
    X(MethodDef)                                                                                   \
    X(Param)                                                                                       \
    X(InterfaceImpl)                                                                               \
    X(MemberRef)                                                                                   \
    X(Property)                                                                                    \
    X(Event)                                                                                       \
    X(StandAloneSig)                                                                               \
    X(ModuleRef)                                                                                   \
    X(TypeSpec)                                                                                    \
    X(Assembly)                                                                                    \
    X(AssemblyRef)                                                                                 \
    X(File)                                                                                        \
    X(ExportedType)                                                                                \
    X(ManifestResource)                                                                            \
    X(GenericParam)                                                                                \
    X(MethodSpec)                                                                                  \
    X(GenericParamConstraint)

// A row (or coded_index) may be "empty" - the C++ code default constructs those
// to signal "not found" and dereferencing one is undefined behaviour. Python
// callers get an exception instead of an access violation.
template <typename T>
inline T const& require_valid(T const& value, char const* what)
{
    if (!value)
    {
        throw std::runtime_error(std::string{ "invalid " } + what +
            " (default constructed or not found)");
    }
    return value;
}

// std::pair<Row, Row> ranges become a lazily iterated sequence object.
template <typename Row>
struct row_range
{
    Row first{};
    Row second{};

    uint32_t size() const noexcept
    {
        return second.index() > first.index() ? second.index() - first.index() : 0;
    }

    bool empty() const noexcept
    {
        return size() == 0;
    }
};

template <typename Pair>
inline auto make_range(Pair const& pair)
{
    return row_range<typename Pair::first_type>{ pair.first, pair.second };
}

// Casts a value that may or may not be a bound type (std::variant results).
// nanobind enums are Python enum members, which are shared singletons, so a
// keep_alive would tie the database to the interpreter lifetime; only bound
// instances take part in the lifetime chain.
template <typename T>
inline nb::object cast_keep_alive(T&& value, nb::handle parent)
{
    nb::object result = nb::cast(std::forward<T>(value), nb::rv_policy::copy);
    if (nb::inst_check(result))
    {
        nb::detail::keep_alive(result.ptr(), parent.ptr());
    }
    return result;
}

template <typename T>
inline std::string to_hex(T value)
{
    std::ostringstream stream;
    stream << "0x" << std::hex << static_cast<uint64_t>(value);
    return stream.str();
}

// Registration entry points, one per translation unit.
void bind_enums(nb::module_& m);
void bind_flags(nb::module_& m);
void bind_view(nb::module_& m);
void bind_rows_declare(nb::module_& m);
void bind_rows(nb::module_& m);
void bind_indexes(nb::module_& m);
void bind_tables(nb::module_& m);
void bind_signatures(nb::module_& m);
void bind_cache(nb::module_& m);
void bind_helpers(nb::module_& m);
