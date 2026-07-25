// table.h / database.h - table_base, table<T>, std::pair<Row, Row> ranges, database
#include "bind.h"

#include <string>

namespace
{
    template <typename Row>
    void bind_range(nb::module_& m, char const* name, std::string const& iterator_name)
    {
        using Range = row_range<Row>;

        nb::class_<Range> c(m, name);
        nb::object scope = c; // the iterator type is registered as a nested class

        c.def(nb::init<>())
            .def("__init__", [](Range* self, Row const& first, Row const& second)
                { new (self) Range{ first, second }; }, nb::arg("first"), nb::arg("second"),
                nb::keep_alive<1, 2>(), nb::keep_alive<1, 3>())
            .def_ro("first", &Range::first)
            .def_ro("second", &Range::second)
            .def("size", &Range::size)
            .def("empty", &Range::empty)
            .def("__len__", &Range::size)
            .def("__bool__", [](Range const& self) { return !self.empty(); })
            .def("__iter__", [scope, iterator_name](Range const& self)
                {
                    return nb::make_iterator<nb::rv_policy::copy, Row, Row, Row>(scope,
                        iterator_name.c_str(), self.first, self.second, KA);
                }, KA)
            .def("__getitem__", [](Range const& self, int64_t index)
                {
                    auto const size = static_cast<int64_t>(self.size());
                    if (index < 0)
                    {
                        index += size;
                    }
                    if (index < 0 || index >= size)
                    {
                        throw nb::index_error("range index out of range");
                    }
                    return self.first + static_cast<int32_t>(index);
                }, nb::arg("index"), KA)
            .def("__repr__", [name](Range const& self)
                {
                    return "<winmd.reader." + std::string{ name } + " size=" +
                        std::to_string(self.size()) + ">";
                });

        // view.h / helpers.h free functions, overloaded for every range type.
        m.def("begin", [](Range const& self) { return self.first; }, nb::arg("values"), KA);
        m.def("end", [](Range const& self) { return self.second; }, nb::arg("values"), KA);
        m.def("distance", [](Range const& self) { return self.second - self.first; },
            nb::arg("values"));
        m.def("size", [](Range const& self) { return self.size(); }, nb::arg("range"));
        m.def("empty", [](Range const& self) { return self.empty(); }, nb::arg("range"));
    }

    template <typename Row>
    void bind_table(nb::module_& m, char const* name, std::string const& iterator_name)
    {
        using Table = table<Row>;

        nb::class_<Table, table_base> c(m, name);
        nb::object scope = c;

        c.def("begin", &Table::begin, KA)
            .def("end", &Table::end, KA)
            .def("__getitem__", [](Table const& self, int64_t row)
                {
                    auto const size = static_cast<int64_t>(self.size());
                    if (row < 0)
                    {
                        row += size;
                    }
                    if (row < 0 || row >= size)
                    {
                        throw nb::index_error("table row index out of range");
                    }
                    return self[static_cast<uint32_t>(row)];
                }, nb::arg("row"), KA)
            .def("__len__", &Table::size)
            .def("__iter__", [scope, iterator_name](Table const& self)
                {
                    return nb::make_iterator<nb::rv_policy::copy, Row, Row, Row>(scope,
                        iterator_name.c_str(), self.begin(), self.end(), KA);
                }, KA)
            .def("__repr__", [name](Table const& self)
                {
                    return "<winmd.reader." + std::string{ name } + " size=" +
                        std::to_string(self.size()) + ">";
                });
    }
}

void bind_tables(nb::module_& m)
{
#define BIND_RANGE(row) bind_range<row>(m, #row "_range", #row "_range_iterator");
    WINMD_ROWS(BIND_RANGE)
#undef BIND_RANGE

    nb::class_<table_base>(m, "table_base")
        .def("get_database", &table_base::get_database, nb::rv_policy::reference_internal)
        .def("size", &table_base::size)
        .def("row_size", &table_base::row_size)
        .def("column_size", &table_base::column_size, nb::arg("column"))
        .def("get_value", [](table_base const& self, uint32_t row, uint32_t column)
            {
                if (column >= 6 || self.column_size(column) == 0)
                {
                    throw nb::index_error("invalid column index");
                }
                if (row >= self.size())
                {
                    throw nb::index_error("invalid row index");
                }
                return self.get_value<uint64_t>(row, column);
            }, nb::arg("row"), nb::arg("column"));

#define BIND_TABLE(row) bind_table<row>(m, #row "_table", #row "_table_iterator");
    WINMD_ROWS(BIND_TABLE)
#undef BIND_TABLE

    nb::class_<database> db(m, "database");

    db
        // bytes converts to std::string as well, so the buffer overload comes first.
        .def("__init__", [](database* self, nb::bytes const& buffer, cache const* c)
            {
                auto const first = static_cast<uint8_t const*>(buffer.data());
                std::vector<uint8_t> copy{ first, first + buffer.size() };
                new (self) database(std::move(copy), c);
            }, nb::arg("buffer"), nb::arg("cache").none() = nullptr, nb::keep_alive<1, 3>())
        .def("__init__", [](database* self, std::string const& path, cache const* c)
            { new (self) database(std::string_view{ path }, c); },
            nb::arg("path"), nb::arg("cache").none() = nullptr, nb::keep_alive<1, 3>())
        .def_static("is_database", [](std::string const& path)
            { return database::is_database(std::string_view{ path }); }, nb::arg("path"))
        .def("path", &database::path)
        .def("get_cache", [](database const& self) -> cache const&
            {
                auto const* value = &self.get_cache();
                if (value == nullptr)
                {
                    throw std::runtime_error("the database was opened without a cache");
                }
                return *value;
            }, nb::rv_policy::reference_internal)
        .def("get_string", [](database const& self, uint32_t index)
            { return std::string{ self.get_string(index) }; }, nb::arg("index"))
        .def("get_blob", &database::get_blob, nb::arg("index"), KA)
#define BIND_DATABASE_TABLE(row) .def_ro(#row, &database::row)
        WINMD_ROWS(BIND_DATABASE_TABLE)
#undef BIND_DATABASE_TABLE
        .def("__repr__", [](database const& self)
            { return "<winmd.reader.database '" + self.path() + "'>"; });

    // cache::databases()
    nb::class_<std::list<database>> databases(m, "database_list");
    nb::object databases_scope = databases;

    databases
        .def("__len__", [](std::list<database> const& self) { return self.size(); })
        .def("__iter__", [databases_scope](std::list<database> const& self)
            {
                return nb::make_iterator<nb::rv_policy::reference_internal>(databases_scope,
                    "iterator", self.begin(), self.end(), KA);
            }, KA)
        .def("__getitem__", [](std::list<database> const& self, int64_t index) -> database const&
            {
                auto const size = static_cast<int64_t>(self.size());
                if (index < 0)
                {
                    index += size;
                }
                if (index < 0 || index >= size)
                {
                    throw nb::index_error("database index out of range");
                }
                auto iterator = self.begin();
                std::advance(iterator, index);
                return *iterator;
            }, nb::arg("index"), nb::rv_policy::reference_internal)
        .def("__repr__", [](std::list<database> const& self)
            { return "<winmd.reader.database_list size=" + std::to_string(self.size()) + ">"; });
}
