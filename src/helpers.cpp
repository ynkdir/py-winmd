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
    m.def("get_type_namespace_and_name", &namespace_and_name, nb::arg("type"));
    m.def("get_base_class_namespace_and_name", [](TypeDef const& type)
        {
            require_valid(type, "TypeDef");
            return namespace_and_name(type.Extends());
        }, nb::arg("type"));
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
        }, nb::arg("type"));

#define BIND_GET_ATTRIBUTE(row)                                                                    \
    m.def("get_attribute", [](row const& value, std::string_view type_namespace,                   \
        std::string_view type_name)                                                                \
        {                                                                                          \
            require_valid(value, #row);                                                            \
            return get_attribute(value, type_namespace, type_name);                                \
        }, nb::arg("row"), nb::arg("type_namespace"), nb::arg("type_name"), KA);
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
        }, nb::arg("type"), KA);
    m.def("find", [](coded_index<TypeDefOrRef> const& type)
        {
            require_valid(type, "coded_index_TypeDefOrRef");
            if (type.type() == TypeDefOrRef::TypeSpec)
            {
                throw std::invalid_argument("a TypeSpec cannot be resolved to a TypeDef");
            }
            require_cache(type.get_database());
            return find(type);
        }, nb::arg("type"), KA);
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
        }, nb::arg("type"), KA);
    m.def("is_const", [](ParamSig const& param) { return is_const(param); }, nb::arg("param"));
}
