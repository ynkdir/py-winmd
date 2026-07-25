// signature.h / custom_attribute.h / key.h (EnumDefinition)
#include "bind.h"

namespace
{
    template <typename T>
    std::vector<T> to_vector(std::pair<typename std::vector<T>::const_iterator,
        typename std::vector<T>::const_iterator> const& range)
    {
        return std::vector<T>{ range.first, range.second };
    }
}

void bind_signatures(nb::module_& m)
{
    nb::class_<GenericTypeIndex>(m, "GenericTypeIndex")
        .def("__init__", [](GenericTypeIndex* self, uint32_t index)
            { new (self) GenericTypeIndex{ index }; }, nb::arg("index"))
        .def_rw("index", &GenericTypeIndex::index)
        .def("__repr__", [](GenericTypeIndex const& self)
            { return "<winmd.reader.GenericTypeIndex " + std::to_string(self.index) + ">"; });

    nb::class_<GenericMethodTypeIndex>(m, "GenericMethodTypeIndex")
        .def("__init__", [](GenericMethodTypeIndex* self, uint32_t index)
            { new (self) GenericMethodTypeIndex{ index }; }, nb::arg("index"))
        .def_rw("index", &GenericMethodTypeIndex::index)
        .def("__repr__", [](GenericMethodTypeIndex const& self)
            { return "<winmd.reader.GenericMethodTypeIndex " + std::to_string(self.index) + ">"; });

    nb::class_<CustomModSig>(m, "CustomModSig")
        .def("__init__", [](CustomModSig* self, table_base const& table, byte_view& data)
            { new (self) CustomModSig{ &table, data }; }, nb::arg("table"), nb::arg("data"),
            nb::keep_alive<1, 2>())
        .def("CustomMod", &CustomModSig::CustomMod)
        .def("Type", &CustomModSig::Type, KA);

    nb::class_<GenericTypeInstSig>(m, "GenericTypeInstSig")
        .def("__init__", [](GenericTypeInstSig* self, table_base const& table, byte_view& data)
            { new (self) GenericTypeInstSig{ &table, data }; }, nb::arg("table"), nb::arg("data"),
            nb::keep_alive<1, 2>())
        .def("__init__", [](GenericTypeInstSig* self, coded_index<TypeDefOrRef> const& type,
            std::vector<TypeSig> args)
            { new (self) GenericTypeInstSig{ type, std::move(args) }; }, nb::arg("type"),
            nb::arg("args"), nb::keep_alive<1, 2>())
        .def("ClassOrValueType", &GenericTypeInstSig::ClassOrValueType)
        .def("GenericType", &GenericTypeInstSig::GenericType, KA)
        .def("GenericArgCount", &GenericTypeInstSig::GenericArgCount)
        .def("GenericArgs", [](GenericTypeInstSig const& self)
            { return to_vector<TypeSig>(self.GenericArgs()); });

    nb::class_<TypeSig>(m, "TypeSig")
        .def("__init__", [](TypeSig* self, table_base const& table, byte_view& data)
            { new (self) TypeSig{ &table, data }; }, nb::arg("table"), nb::arg("data"),
            nb::keep_alive<1, 2>())
        .def("Type", [](nb::handle self)
            { return cast_keep_alive(nb::cast<TypeSig const&>(self).Type(), self); },
            nb::sig("def Type(self) -> ElementType | coded_index_TypeDefOrRef | GenericTypeIndex "
                "| GenericTypeInstSig | GenericMethodTypeIndex"))
        .def("element_type", &TypeSig::element_type)
        .def("is_szarray", &TypeSig::is_szarray)
        .def("is_array", &TypeSig::is_array)
        .def("array_rank", &TypeSig::array_rank)
        .def("array_sizes", &TypeSig::array_sizes)
        .def("ptr_count", &TypeSig::ptr_count);

    nb::class_<ParamSig>(m, "ParamSig")
        .def("__init__", [](ParamSig* self, table_base const& table, byte_view& data)
            { new (self) ParamSig{ &table, data }; }, nb::arg("table"), nb::arg("data"),
            nb::keep_alive<1, 2>())
        .def("CustomMod", [](ParamSig const& self)
            { return to_vector<CustomModSig>(self.CustomMod()); })
        .def("ByRef", &ParamSig::ByRef)
        .def("Type", &ParamSig::Type, KA);

    nb::class_<RetTypeSig>(m, "RetTypeSig")
        .def("__init__", [](RetTypeSig* self, table_base const& table, byte_view& data)
            { new (self) RetTypeSig{ &table, data }; }, nb::arg("table"), nb::arg("data"),
            nb::keep_alive<1, 2>())
        .def("CustomMod", [](RetTypeSig const& self)
            { return to_vector<CustomModSig>(self.CustomMod()); })
        .def("ByRef", &RetTypeSig::ByRef)
        .def("Type", [](RetTypeSig const& self) -> TypeSig const&
            {
                if (!self)
                {
                    throw std::runtime_error("the return type is void");
                }
                return self.Type();
            }, KA)
        .def("__bool__", [](RetTypeSig const& self) { return static_cast<bool>(self); });

    nb::class_<MethodDefSig>(m, "MethodDefSig")
        .def("__init__", [](MethodDefSig* self, table_base const& table, byte_view& data)
            { new (self) MethodDefSig{ &table, data }; }, nb::arg("table"), nb::arg("data"),
            nb::keep_alive<1, 2>())
        .def("CallConvention", &MethodDefSig::CallConvention)
        .def("GenericParamCount", &MethodDefSig::GenericParamCount)
        .def("ReturnType", &MethodDefSig::ReturnType, KA)
        .def("Params",
            [](MethodDefSig const& self) { return to_vector<ParamSig>(self.Params()); });

    nb::class_<FieldSig>(m, "FieldSig")
        .def("__init__", [](FieldSig* self, table_base const& table, byte_view& data)
            { new (self) FieldSig{ &table, data }; }, nb::arg("table"), nb::arg("data"),
            nb::keep_alive<1, 2>())
        .def("CustomMod", [](FieldSig const& self)
            { return to_vector<CustomModSig>(self.CustomMod()); })
        .def("Type", &FieldSig::Type, KA);

    nb::class_<PropertySig>(m, "PropertySig")
        .def("__init__", [](PropertySig* self, table_base const& table, byte_view& data)
            { new (self) PropertySig{ &table, data }; }, nb::arg("table"), nb::arg("data"),
            nb::keep_alive<1, 2>())
        .def("Type", &PropertySig::Type, KA)
        .def("CallConvention", &PropertySig::CallConvention);

    nb::class_<TypeSpecSig>(m, "TypeSpecSig")
        .def("__init__", [](TypeSpecSig* self, table_base const& table, byte_view& data)
            { new (self) TypeSpecSig{ &table, data }; }, nb::arg("table"), nb::arg("data"),
            nb::keep_alive<1, 2>())
        .def("GenericTypeInst", &TypeSpecSig::GenericTypeInst, KA);

    // signature.h free functions; all of them advance the cursor.
    m.def("parse_cmods", [](table_base const& table, byte_view& data)
        { return parse_cmods(&table, data); }, nb::arg("table"), nb::arg("data"));
    m.def("parse_szarray", [](table_base const& table, byte_view& data)
        { return parse_szarray(&table, data); }, nb::arg("table"), nb::arg("data"));
    m.def("parse_array", [](table_base const& table, byte_view& data)
        { return parse_array(&table, data); }, nb::arg("table"), nb::arg("data"));
    m.def("parse_array_sizes", [](table_base const& table, byte_view& data)
        { return parse_array_sizes(&table, data); }, nb::arg("table"), nb::arg("data"));
    m.def("parse_ptr", [](table_base const& table, byte_view& data)
        { return parse_ptr(&table, data); }, nb::arg("table"), nb::arg("data"));
    m.def("is_by_ref", [](byte_view& data) { return is_by_ref(data); }, nb::arg("data"));

    // key.h
    nb::class_<EnumDefinition>(m, "EnumDefinition")
        .def("__init__", [](EnumDefinition* self, TypeDef const& type)
            {
                require_valid(type, "TypeDef");
                if (!type.is_enum())
                {
                    throw std::invalid_argument("the type is not an enum");
                }
                new (self) EnumDefinition{ type };
            }, nb::arg("type"), nb::keep_alive<1, 2>())
        .def_ro("m_typedef", &EnumDefinition::m_typedef)
        .def_ro("m_underlying_type", &EnumDefinition::m_underlying_type)
        .def("get_enumerator", [](EnumDefinition const& self, std::string const& name)
            {
                auto const fields = self.m_typedef.FieldList();
                auto const field = self.get_enumerator(name);
                if (field == fields.second)
                {
                    throw nb::key_error(name.c_str());
                }
                return field;
            }, nb::arg("name"), KA)
        .def("__repr__", [](EnumDefinition const& self)
            {
                return "<winmd.reader.EnumDefinition " + std::string{ self.m_typedef.TypeNamespace() } +
                    "." + std::string{ self.m_typedef.TypeName() } + ">";
            });

    // custom_attribute.h
    auto elem_sig = nb::class_<ElemSig>(m, "ElemSig");

    // Not constructible from Python: SystemType::name is a std::string_view that
    // must point into the blob it was parsed from.
    nb::class_<ElemSig::SystemType>(elem_sig, "SystemType")
        .def_prop_ro("name",
            [](ElemSig::SystemType const& self) { return std::string{ self.name }; })
        .def("__repr__", [](ElemSig::SystemType const& self)
            { return "<winmd.reader.ElemSig.SystemType '" + std::string{ self.name } + "'>"; });

    nb::class_<ElemSig::EnumValue>(elem_sig, "EnumValue")
        .def_ro("type", &ElemSig::EnumValue::type)
        .def_ro("value", &ElemSig::EnumValue::value)
        .def("equals_enumerator", [](ElemSig::EnumValue const& self, std::string const& name)
            { return self.equals_enumerator(name); }, nb::arg("name"))
        .def("__repr__", [](ElemSig::EnumValue const& self)
            {
                return "<winmd.reader.ElemSig.EnumValue " +
                    std::string{ self.type.m_typedef.TypeName() } + ">";
            });

    elem_sig
        .def("__init__", [](ElemSig* self, database const& db, ParamSig const& param,
            byte_view& data) { new (self) ElemSig{ db, param, data }; }, nb::arg("db"),
            nb::arg("param"), nb::arg("data"), nb::keep_alive<1, 2>())
        .def("__init__", [](ElemSig* self, ElemSig::SystemType const& type)
            { new (self) ElemSig{ type }; }, nb::arg("type"))
        .def("__init__", [](ElemSig* self, EnumDefinition const& enum_def, byte_view& data)
            { new (self) ElemSig{ enum_def, data }; }, nb::arg("enum_def"), nb::arg("data"),
            nb::keep_alive<1, 2>())
        .def("__init__", [](ElemSig* self, ElementType type, byte_view& data)
            { new (self) ElemSig{ type, data }; }, nb::arg("type"), nb::arg("data"))
        .def_ro("value", &ElemSig::value)
        .def_static("read_element", &ElemSig::read_element, nb::arg("db"), nb::arg("param"),
            nb::arg("data"))
        .def_static("read_primitive", &ElemSig::read_primitive, nb::arg("type"), nb::arg("data"))
        .def_static("read_enum", &ElemSig::read_enum, nb::arg("type"), nb::arg("data"));

    nb::class_<FixedArgSig>(m, "FixedArgSig")
        .def("__init__", [](FixedArgSig* self, database const& db, ParamSig const& ctor_param,
            byte_view& data) { new (self) FixedArgSig{ db, ctor_param, data }; }, nb::arg("db"),
            nb::arg("ctor_param"), nb::arg("data"), nb::keep_alive<1, 2>())
        .def("__init__", [](FixedArgSig* self, ElemSig::SystemType const& type)
            { new (self) FixedArgSig{ type }; }, nb::arg("type"))
        .def("__init__", [](FixedArgSig* self, EnumDefinition const& enum_def, byte_view& data)
            { new (self) FixedArgSig{ enum_def, data }; }, nb::arg("enum_def"), nb::arg("data"),
            nb::keep_alive<1, 2>())
        .def("__init__", [](FixedArgSig* self, ElementType type, bool is_array, byte_view& data)
            { new (self) FixedArgSig{ type, is_array, data }; }, nb::arg("type"),
            nb::arg("is_array"), nb::arg("data"))
        .def_ro("value", &FixedArgSig::value);

    nb::class_<NamedArgSig>(m, "NamedArgSig")
        .def("__init__", [](NamedArgSig* self, database const& db, byte_view& data)
            { new (self) NamedArgSig{ db, data }; }, nb::arg("db"), nb::arg("data"),
            nb::keep_alive<1, 2>())
        .def_prop_ro("name",
            [](NamedArgSig const& self) { return std::string{ self.name }; })
        .def_ro("value", &NamedArgSig::value)
        .def("__repr__", [](NamedArgSig const& self)
            { return "<winmd.reader.NamedArgSig '" + std::string{ self.name } + "'>"; });

    nb::class_<CustomAttributeSig>(m, "CustomAttributeSig")
        .def("__init__", [](CustomAttributeSig* self, table_base const& table, byte_view& data,
            MethodDefSig const& ctor) { new (self) CustomAttributeSig{ &table, data, ctor }; },
            nb::arg("table"), nb::arg("data"), nb::arg("ctor"), nb::keep_alive<1, 2>())
        .def("FixedArgs", &CustomAttributeSig::FixedArgs)
        .def("NamedArgs", &CustomAttributeSig::NamedArgs);
}
