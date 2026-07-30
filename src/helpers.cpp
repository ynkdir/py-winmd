// type_helpers.h / helpers.h / key.h (get_attribute, get_category)
#include "bind.h"

namespace
{
    void require_cache(database const& db)
    {
        if (&db.get_cache() == nullptr)
        {
            throw std::runtime_error("the database was opened without a cache");
        }
    }

    std::pair<std::string_view, std::string_view> namespace_and_name(
        coded_index<TypeDefOrRef> const& type)
    {
        require_valid(type, "coded_index_TypeDefOrRef");
        if (type.type() == TypeDefOrRef::TypeSpec)
        {
            throw std::invalid_argument("a TypeSpec has no namespace and name");
        }
        return get_type_namespace_and_name(type);
    }
}

void bind_helpers(nb::module_& m)
{
    // type_helpers.h
    m.def("get_type_namespace_and_name", &namespace_and_name, nb::arg("type"),
        "(namespace, name) of what a coded_index_TypeDefOrRef points at, whichever "
        "table that is. The way to name the type in a signature or a base class.");
    m.def("get_base_class_namespace_and_name", [](TypeDef const& type)
        {
            require_valid(type, "TypeDef");
            return namespace_and_name(type.Extends());
        }, nb::arg("type"),
        "(namespace, name) of what the type extends, ('', '') when it extends nothing.");
    m.def("extends_type", [](TypeDef const& type, std::string_view type_namespace,
        std::string_view type_name)
        {
            require_valid(type, "TypeDef");
            return extends_type(type, type_namespace, type_name);
        }, nb::arg("type"), nb::arg("typeNamespace"), nb::arg("typeName"));
    m.def("is_nested", [](TypeDef const& type)
        {
            require_valid(type, "TypeDef");
            return is_nested(type);
        }, nb::arg("type"));
    m.def("is_nested", [](TypeRef const& type)
        {
            require_valid(type, "TypeRef");
            return is_nested(type);
        }, nb::arg("type"));

    // key.h
    m.def("get_category", [](TypeDef const& type)
        {
            require_valid(type, "TypeDef");
            return get_category(type);
        }, nb::arg("type"),
        "What kind of type it is: category.interface_type, class_type, enum_type, "
        "struct_type or delegate_type. Reads the flags and the base class, and "
        "counts a type carrying a GuidAttribute as an interface, which is how "
        "WinRT and Win32 metadata mark COM interfaces.");

#define BIND_GET_ATTRIBUTE(row)                                                                    \
    m.def("get_attribute", [](row const& value, std::string_view type_namespace,                   \
        std::string_view type_name)                                                                \
        {                                                                                          \
            require_valid(value, #row);                                                            \
            return get_attribute(value, type_namespace, type_name);                                \
        }, nb::arg("row"), nb::arg("type_namespace"), nb::arg("type_name"), KA,                     \
        "The attribute of that name applied to the row, or an invalid "                            \
        "CustomAttribute when there is none - test it with bool(). Its arguments "                 \
        "come from Value(), which needs the file defining the attribute in the "                   \
        "cache: get_attribute(type, \"Windows.Win32.Foundation.Metadata\", "                       \
        "\"GuidAttribute\").");
    WINMD_ATTRIBUTABLE_ROWS(BIND_GET_ATTRIBUTE)
#undef BIND_GET_ATTRIBUTE

    m.def("get_attribute", [](coded_index<TypeDefOrRef> const& value,
        std::string_view type_namespace, std::string_view type_name)
        {
            require_valid(value, "coded_index_TypeDefOrRef");
            return get_attribute(value, type_namespace, type_name);
        }, nb::arg("row"), nb::arg("type_namespace"), nb::arg("type_name"), KA);

    // helpers.h
    m.def("find", [](TypeRef const& type)
        {
            require_valid(type, "TypeRef");
            require_cache(type.get_database());
            return find(type);
        }, nb::arg("type"), KA,
        "The TypeDef a reference points at, looked up in the cache; an invalid "
        "TypeDef when the file defining it is not in there.");
    m.def("find", [](coded_index<TypeDefOrRef> const& type)
        {
            require_valid(type, "coded_index_TypeDefOrRef");
            if (type.type() == TypeDefOrRef::TypeSpec)
            {
                throw std::invalid_argument("a TypeSpec cannot be resolved to a TypeDef");
            }
            require_cache(type.get_database());
            return find(type);
        }, nb::arg("type"), KA,
        "The TypeDef a TypeDefOrRef column points at, whichever table it names - "
        "what to call on TypeDef.Extends(), an interface, or the type in a "
        "signature. A TypeSpec cannot be resolved and raises.");
    m.def("find_required", [](TypeRef const& type)
        {
            require_valid(type, "TypeRef");
            require_cache(type.get_database());
            return find_required(type);
        }, nb::arg("type"), KA);
    m.def("find_required", [](coded_index<TypeDefOrRef> const& type)
        {
            require_valid(type, "coded_index_TypeDefOrRef");
            if (type.type() == TypeDefOrRef::TypeSpec)
            {
                throw std::invalid_argument("a TypeSpec cannot be resolved to a TypeDef");
            }
            require_cache(type.get_database());
            return find_required(type);
        }, nb::arg("type"), KA, "find(), but raises ValueError when it resolves to nothing.");
    m.def("is_const", [](ParamSig const& param) { return is_const(param); }, nb::arg("param"),
        "Whether the parameter carries the const modifier Win32 metadata uses.");
}
