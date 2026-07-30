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

    nb::class_<cache> cache_class(m, "cache", R"(A set of .winmd files, with their types indexed by namespace and name.

    db = cache(["Windows.Win32.winmd"])            # or one path, or many
    type = db.find_required("Windows.Win32.Foundation", "HANDLE")

This is what resolves a reference in one file to the definition in another, so
almost everything starts here. Rows, strings and signatures all point into the
memory mapped files it owns - keep the cache alive as long as they are used.

Nested types and the <Module> pseudo type are left out of the index; find them
through nested_types() and databases() respectively. A filter passed as the
second argument decides which types are indexed at all.)");

    nb::class_<cache::namespace_members>(cache_class, "namespace_members",
        "The types of one namespace: `types` has all of them by name, the other "
        "members are the same types by kind. Win32 metadata keeps the functions "
        "and constants of the namespace in types[\"Apis\"].")
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
            nb::arg("type_namespace"), nb::arg("type_name"), KA,
            "The type, or an invalid TypeDef when there is none - test it with bool().")
        .def("find", [](cache const& self, std::string_view type_string)
            { return self.find(type_string); }, nb::arg("type_string"), KA,
            "find() by a dotted name: find(\"Windows.Foundation.Uri\").")
        .def("find_required", [](cache const& self, std::string_view type_namespace,
            std::string_view type_name) { return self.find_required(type_namespace, type_name); },
            nb::arg("type_namespace"), nb::arg("type_name"), KA,
            "find(), but raises ValueError instead of returning an invalid TypeDef.")
        .def("find_required", [](cache const& self, std::string_view type_string)
            { return self.find_required(type_string); }, nb::arg("type_string"), KA,
            "find_required() by a dotted name.")
        .def("databases", &cache::databases, nb::rv_policy::reference_internal,
            "The database objects, one per file, for reaching a table directly.")
        .def("namespaces", &cache::namespaces, nb::rv_policy::reference_internal,
            "{namespace name: namespace_members}, read only, sorted by name.")
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
            }, nb::arg("file"), nb::arg("filter").none() = nb::none(),
            "Indexes another file. Existing rows stay valid.")
        .def("nested_types", [](cache const& self, TypeDef const& enclosing_type)
            { return self.nested_types(enclosing_type); }, nb::arg("enclosing_type"),
            "The types nested inside this one; they are not in the namespace index.")
        .def("__repr__", [](cache const& self)
            {
                return "<winmd.reader.cache databases=" + std::to_string(self.databases().size()) +
                    " namespaces=" + std::to_string(self.namespaces().size()) + ">";
            });

    nb::class_<filter>(m, "filter",
        "A set of include and exclude prefixes, longest first, for carving a "
        "subset out of the metadata: filter([\"Windows.Foundation\"], "
        "[\"Windows.Foundation.Metadata\"]). With no rules everything is "
        "included. Callable, so it can be passed to cache() as the filter.")
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
