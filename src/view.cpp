// view.h - byte_view / file_view, plus the blob reading helpers of signature.h
#include "bind.h"

#include <optional>

namespace
{
    template <typename T>
    void add_as(nb::class_<byte_view>& c, char const* name)
    {
        c.def(name, [](byte_view const& self, uint32_t offset) { return self.as<T>(offset); },
            nb::arg("offset") = 0);
    }

    template <typename T>
    void add_read(nb::module_& m, char const* name)
    {
        m.def(name, [](byte_view& cursor) { return read<T>(cursor); }, nb::arg("cursor"),
            "Reads a value from the cursor and advances it.");
    }
}

void bind_view(nb::module_& m)
{
    nb::class_<byte_view> c(m, "byte_view");

    c.def(nb::init<>())
        .def("__init__", [](byte_view* self, nb::bytes const& data)
            {
                // Keeps no ownership: the bytes object is kept alive by keep_alive.
                auto const first = static_cast<uint8_t const*>(data.data());
                new (self) byte_view{ first, first + data.size() };
            }, nb::arg("data"), nb::keep_alive<1, 2>())
        .def("size", &byte_view::size)
        .def("__len__", &byte_view::size)
        .def("__bool__", [](byte_view const& self) { return static_cast<bool>(self); })
        .def("seek", &byte_view::seek, nb::arg("offset"), KA)
        .def("sub", &byte_view::sub, nb::arg("offset"), nb::arg("size"), KA)
        .def("as_string",
            [](byte_view const& self, uint32_t offset) -> std::optional<std::string>
            {
                auto value = self.as_string(offset);
                if (value.data() == nullptr)
                {
                    return std::nullopt; // length 0xff: the null string
                }
                return std::string{ value };
            }, nb::arg("offset") = 0)
        .def("as_u16string_constant", &byte_view::as_u16string_constant)
        .def("as_bytes", [](byte_view const& self)
            { return nb::bytes(self.begin(), self.size()); })
        .def("__bytes__", [](byte_view const& self)
            { return nb::bytes(self.begin(), self.size()); })
        .def("__getitem__", [](byte_view const& self, int64_t index)
            {
                auto const size = static_cast<int64_t>(self.size());
                if (index < 0)
                {
                    index += size;
                }
                if (index < 0 || index >= size)
                {
                    throw nb::index_error("byte_view index out of range");
                }
                return self.as<uint8_t>(static_cast<uint32_t>(index));
            }, nb::arg("index"))
        .def("__repr__", [](byte_view const& self)
            { return "<winmd.reader.byte_view size=" + std::to_string(self.size()) + ">"; });

    // byte_view::as<T>
    add_as<bool>(c, "as_bool");
    add_as<char16_t>(c, "as_char");
    add_as<int8_t>(c, "as_int8");
    add_as<uint8_t>(c, "as_uint8");
    add_as<int16_t>(c, "as_int16");
    add_as<uint16_t>(c, "as_uint16");
    add_as<int32_t>(c, "as_int32");
    add_as<uint32_t>(c, "as_uint32");
    add_as<int64_t>(c, "as_int64");
    add_as<uint64_t>(c, "as_uint64");
    add_as<float>(c, "as_float32");
    add_as<double>(c, "as_float64");

    nb::class_<file_view, byte_view>(m, "file_view")
        .def("__init__", [](file_view* self, std::string const& path)
            { new (self) file_view{ std::string_view{ path } }; }, nb::arg("path"));

    // signature.h: read<T>(byte_view&) / uncompress_unsigned(byte_view&).
    // These advance the cursor that is passed in.
    add_read<bool>(m, "read_bool");
    add_read<char16_t>(m, "read_char");
    add_read<int8_t>(m, "read_int8");
    add_read<uint8_t>(m, "read_uint8");
    add_read<int16_t>(m, "read_int16");
    add_read<uint16_t>(m, "read_uint16");
    add_read<int32_t>(m, "read_int32");
    add_read<uint32_t>(m, "read_uint32");
    add_read<int64_t>(m, "read_int64");
    add_read<uint64_t>(m, "read_uint64");
    add_read<float>(m, "read_float32");
    add_read<double>(m, "read_float64");
    add_read<ElementType>(m, "read_element_type");
    add_read<CallingConvention>(m, "read_calling_convention");
    m.def("read_string",
        [](byte_view& cursor) { return std::string{ read<std::string_view>(cursor) }; },
        nb::arg("cursor"), "Reads a compressed-length UTF-8 string and advances the cursor.");

    m.def("uncompress_unsigned", [](byte_view& cursor) { return uncompress_unsigned(cursor); },
        nb::arg("cursor"), "Reads a compressed unsigned integer and advances the cursor.");
    m.def("uncompress_enum_element_type",
        [](byte_view& cursor) { return uncompress_enum<ElementType>(cursor); }, nb::arg("cursor"));
    m.def("uncompress_enum_calling_convention",
        [](byte_view& cursor) { return uncompress_enum<CallingConvention>(cursor); },
        nb::arg("cursor"));
}
