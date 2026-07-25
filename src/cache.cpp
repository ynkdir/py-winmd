// cache.h / filter.h
#include "bind.h"

#include <string>

namespace
{
    using namespace_map = std::map<std::string_view, cache::namespace_members>;
    using type_map = std::map<std::string_view, TypeDef>;

    // A read only mapping view; the keys are std::string_view instances that point
    // into the metadata, so the map itself must never be modified from Python.
    template <typename Map>
    nb::class_<Map> bind_ro_map(nb::module_& m, char const* name)
    {
        nb::class_<Map> c(m, name);
        nb::object scope = c;

        c.def("__len__", [](Map const& self) { return self.size(); })
            .def("__contains__", [](Map const& self, std::string_view key)
                { return self.find(key) != self.end(); }, nb::arg("key"))
            .def("__getitem__", [](Map const& self, std::string_view key) ->
                typename Map::mapped_type const&
                {
                    auto const entry = self.find(key);
                    if (entry == self.end())
                    {
                        throw nb::key_error(std::string{ key }.c_str());
                    }
                    return entry->second;
                }, nb::arg("key"), nb::rv_policy::reference_internal)
            .def("get", [](nb::object self, std::string_view key, nb::object fallback)
                {
                    auto const& map = nb::cast<Map const&>(self);
                    auto const entry = map.find(key);
                    if (entry == map.end())
                    {
                        return fallback;
                    }
                    return nb::cast(&entry->second, nb::rv_policy::reference_internal, self);
                }, nb::arg("key"), nb::arg("default") = nb::none())
            .def("__iter__", [scope](Map const& self)
                {
                    return nb::make_key_iterator(scope, "key_iterator", self.begin(), self.end());
                }, KA)
            .def("keys", [](Map const& self)
                {
                    nb::list keys;
                    for (auto const& entry : self)
                    {
                        keys.append(nb::cast(entry.first));
                    }
                    return keys;
                })
            .def("values", [](nb::object self)
                {
                    nb::list values;
                    for (auto const& entry : nb::cast<Map const&>(self))
                    {
                        values.append(nb::cast(&entry.second, nb::rv_policy::reference_internal,
                            self));
                    }
                    return values;
                })
            .def("items", [](nb::object self)
                {
                    nb::list items;
                    for (auto const& entry : nb::cast<Map const&>(self))
                    {
                        items.append(nb::make_tuple(nb::cast(entry.first),
                            nb::cast(&entry.second, nb::rv_policy::reference_internal, self)));
                    }
                    return items;
                })
            .def("__repr__", [name](Map const& self)
                {
                    return "<winmd.reader." + std::string{ name } + " size=" +
                        std::to_string(self.size()) + ">";
                });

        return c;
    }

    using type_filter = std::function<bool(TypeDef const&)>;
}

void bind_cache(nb::module_& m)
{
    bind_ro_map<type_map>(m, "type_map");
    bind_ro_map<namespace_map>(m, "namespace_map");

    nb::class_<cache> cache_class(m, "cache");

    nb::class_<cache::namespace_members>(cache_class, "namespace_members")
        .def(nb::init<>())
        .def_ro("types", &cache::namespace_members::types)
        .def_ro("interfaces", &cache::namespace_members::interfaces)
        .def_ro("classes", &cache::namespace_members::classes)
        .def_ro("enums", &cache::namespace_members::enums)
        .def_ro("structs", &cache::namespace_members::structs)
        .def_ro("delegates", &cache::namespace_members::delegates)
        .def_ro("attributes", &cache::namespace_members::attributes)
        .def_ro("contracts", &cache::namespace_members::contracts)
        .def("__repr__", [](cache::namespace_members const& self)
            {
                return "<winmd.reader.cache.namespace_members types=" +
                    std::to_string(self.types.size()) + ">";
            });

    nb::class_<cache::default_type_filter>(cache_class, "default_type_filter")
        .def(nb::init<>())
        .def("__call__", &cache::default_type_filter::operator(), nb::arg("type"));

    cache_class
        .def(nb::init<>())
        .def("__init__", [](cache* self, std::vector<std::string> const& files, type_filter filter)
            {
                if (filter)
                {
                    new (self) cache(files, filter);
                }
                else
                {
                    new (self) cache(files);
                }
            }, nb::arg("files"), nb::arg("filter").none() = nb::none())
        .def("__init__", [](cache* self, std::string const& file, type_filter filter)
            {
                std::vector<std::string> const files{ file };
                if (filter)
                {
                    new (self) cache(files, filter);
                }
                else
                {
                    new (self) cache(files);
                }
            }, nb::arg("file"), nb::arg("filter").none() = nb::none())
        .def("find", [](cache const& self, std::string_view type_namespace,
            std::string_view type_name) { return self.find(type_namespace, type_name); },
            nb::arg("type_namespace"), nb::arg("type_name"), KA)
        .def("find", [](cache const& self, std::string_view type_string)
            { return self.find(type_string); }, nb::arg("type_string"), KA)
        .def("find_required", [](cache const& self, std::string_view type_namespace,
            std::string_view type_name) { return self.find_required(type_namespace, type_name); },
            nb::arg("type_namespace"), nb::arg("type_name"), KA)
        .def("find_required", [](cache const& self, std::string_view type_string)
            { return self.find_required(type_string); }, nb::arg("type_string"), KA)
        .def("databases", &cache::databases, nb::rv_policy::reference_internal)
        .def("namespaces", &cache::namespaces, nb::rv_policy::reference_internal)
        .def("remove_type", [](cache& self, std::string_view ns, std::string_view name)
            { self.remove_type(ns, name); }, nb::arg("ns"), nb::arg("name"))
        .def("add_database", [](cache& self, std::string const& file, type_filter filter)
            {
                if (filter)
                {
                    self.add_database(std::string_view{ file }, filter);
                }
                else
                {
                    self.add_database(std::string_view{ file });
                }
            }, nb::arg("file"), nb::arg("filter").none() = nb::none())
        .def("nested_types", [](cache const& self, TypeDef const& enclosing_type)
            { return self.nested_types(enclosing_type); }, nb::arg("enclosing_type"))
        .def("__repr__", [](cache const& self)
            {
                return "<winmd.reader.cache databases=" + std::to_string(self.databases().size()) +
                    " namespaces=" + std::to_string(self.namespaces().size()) + ">";
            });

    nb::class_<filter>(m, "filter")
        .def(nb::init<>())
        .def("__init__", [](filter* self, std::vector<std::string> const& includes,
            std::vector<std::string> const& excludes) { new (self) filter(includes, excludes); },
            nb::arg("includes"), nb::arg("excludes"))
        .def("includes", [](filter const& self, TypeDef const& type) { return self.includes(type); },
            nb::arg("type"))
        .def("includes", [](filter const& self, std::vector<TypeDef> const& types)
            { return self.includes(types); }, nb::arg("types"))
        .def("includes", [](filter const& self, cache::namespace_members const& members)
            { return self.includes(members); }, nb::arg("members"))
        .def("includes", [](filter const& self, std::string_view type)
            { return self.includes(type); }, nb::arg("type"))
        .def("empty", &filter::empty)
        .def("__call__", [](filter const& self, TypeDef const& type) { return self.includes(type); },
            nb::arg("type"));
}
