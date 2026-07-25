// schema.h / column.h / custom_attribute.h - the 38 metadata table row types
#include "bind.h"

#include <vector>

namespace
{
    // Row specific accessors. `c` is the class being registered, `name` its name.
    template <typename R>
    void bind_row_extras(nb::class_<R>&, char const*)
    {
    }

    // Accessors returning a value that does not point back into the database.
#define M(fn) c.def(#fn, [name](R const& self) { require_valid(self, name); return self.fn(); })
    // Accessors returning rows, indexes, signatures or blobs: those must keep the
    // database (and therefore the memory mapped file) alive.
#define MK(fn)                                                                                     \
    c.def(#fn, [name](R const& self) { require_valid(self, name); return self.fn(); }, KA)
    // Accessors returning a std::pair<Row, Row> range.
#define MR(fn)                                                                                     \
    c.def(                                                                                         \
        #fn, [name](R const& self) { require_valid(self, name); return make_range(self.fn()); }, KA)

    template <>
    void bind_row_extras<TypeRef>(nb::class_<TypeRef>& c, char const* name)
    {
        using R = TypeRef;
        MK(ResolutionScope);
        M(TypeName);
        M(TypeNamespace);
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<CustomAttribute>(nb::class_<CustomAttribute>& c, char const* name)
    {
        using R = CustomAttribute;
        MK(Parent);
        MK(Type);
        MK(Value);
        M(TypeNamespaceAndName);
    }

    template <>
    void bind_row_extras<TypeDef>(nb::class_<TypeDef>& c, char const* name)
    {
        using R = TypeDef;
        M(Flags);
        M(TypeName);
        M(TypeNamespace);
        MK(Extends);
        MR(FieldList);
        MR(MethodList);
        MR(CustomAttribute);
        MR(InterfaceImpl);
        MR(GenericParam);
        MR(PropertyList);
        MR(EventList);
        MR(MethodImplList);
        MK(EnclosingType);
        M(is_enum);
        MK(get_enum_definition);
    }

    template <>
    void bind_row_extras<MethodDef>(nb::class_<MethodDef>& c, char const* name)
    {
        using R = MethodDef;
        M(RVA);
        M(ImplFlags);
        M(Flags);
        M(Name);
        MK(Signature);
        MR(ParamList);
        MR(CustomAttribute);
        MK(Parent);
        MR(GenericParam);
        M(SpecialName);
    }

    template <>
    void bind_row_extras<MemberRef>(nb::class_<MemberRef>& c, char const* name)
    {
        using R = MemberRef;
        MK(Class);
        M(Name);
        MK(MethodSignature);
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<Module>(nb::class_<Module>& c, char const* name)
    {
        using R = Module;
        M(Name);
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<Field>(nb::class_<Field>& c, char const* name)
    {
        using R = Field;
        M(Flags);
        M(Name);
        MK(Signature);
        MR(CustomAttribute);
        MK(Constant);
        MK(Parent);
        MK(FieldMarshal);
    }

    template <>
    void bind_row_extras<Param>(nb::class_<Param>& c, char const* name)
    {
        using R = Param;
        M(Flags);
        M(Sequence);
        M(Name);
        MR(CustomAttribute);
        MK(Constant);
        MK(FieldMarshal);
    }

    template <>
    void bind_row_extras<InterfaceImpl>(nb::class_<InterfaceImpl>& c, char const* name)
    {
        using R = InterfaceImpl;
        MK(Class);
        MK(Interface);
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<Constant>(nb::class_<Constant>& c, char const* name)
    {
        using R = Constant;
        M(Type);
        MK(Parent);
        M(ValueBoolean);
        M(ValueChar);
        M(ValueInt8);
        M(ValueUInt8);
        M(ValueInt16);
        M(ValueUInt16);
        M(ValueInt32);
        M(ValueUInt32);
        M(ValueInt64);
        M(ValueUInt64);
        M(ValueFloat32);
        M(ValueFloat64);
        c.def("ValueString", [name](Constant const& self)
            {
                require_valid(self, name);
                return self.ValueString();
            });
        c.def("ValueClass", [name](Constant const& self)
            {
                require_valid(self, name);
                self.ValueClass();
                return nb::none();
            });
        M(Value);
    }

    template <>
    void bind_row_extras<FieldMarshal>(nb::class_<FieldMarshal>& c, char const* name)
    {
        using R = FieldMarshal;
        MK(Parent);
    }

    template <>
    void bind_row_extras<TypeSpec>(nb::class_<TypeSpec>& c, char const* name)
    {
        using R = TypeSpec;
        MK(Signature);
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<ClassLayout>(nb::class_<ClassLayout>& c, char const* name)
    {
        using R = ClassLayout;
        M(PackingSize);
        M(ClassSize);
        MK(Parent);
    }

    template <>
    void bind_row_extras<StandAloneSig>(nb::class_<StandAloneSig>& c, char const* name)
    {
        using R = StandAloneSig;
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<EventMap>(nb::class_<EventMap>& c, char const* name)
    {
        using R = EventMap;
        MK(Parent);
        MR(EventList);
    }

    template <>
    void bind_row_extras<Event>(nb::class_<Event>& c, char const* name)
    {
        using R = Event;
        M(EventFlags);
        M(Name);
        MK(EventType);
        MR(MethodSemantic);
        MK(Parent);
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<PropertyMap>(nb::class_<PropertyMap>& c, char const* name)
    {
        using R = PropertyMap;
        MK(Parent);
        MR(PropertyList);
    }

    template <>
    void bind_row_extras<Property>(nb::class_<Property>& c, char const* name)
    {
        using R = Property;
        M(Flags);
        M(Name);
        MK(Type);
        MR(MethodSemantic);
        MK(Parent);
        MK(Constant);
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<MethodSemantics>(nb::class_<MethodSemantics>& c, char const* name)
    {
        using R = MethodSemantics;
        M(Semantic);
        MK(Method);
        MK(Association);
    }

    template <>
    void bind_row_extras<MethodImpl>(nb::class_<MethodImpl>& c, char const* name)
    {
        using R = MethodImpl;
        MK(Class);
        MK(MethodBody);
        MK(MethodDeclaration);
    }

    template <>
    void bind_row_extras<ModuleRef>(nb::class_<ModuleRef>& c, char const* name)
    {
        using R = ModuleRef;
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<Assembly>(nb::class_<Assembly>& c, char const* name)
    {
        using R = Assembly;
        M(HashAlgId);
        M(Version);
        M(Flags);
        MK(PublicKey);
        M(Name);
        M(Culture);
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<AssemblyProcessor>(nb::class_<AssemblyProcessor>& c, char const* name)
    {
        using R = AssemblyProcessor;
        M(Processor);
    }

    template <>
    void bind_row_extras<AssemblyOS>(nb::class_<AssemblyOS>& c, char const* name)
    {
        using R = AssemblyOS;
        M(OSPlatformId);
        M(OSMajorVersion);
        M(OSMinorVersion);
    }

    template <>
    void bind_row_extras<AssemblyRef>(nb::class_<AssemblyRef>& c, char const* name)
    {
        using R = AssemblyRef;
        M(Version);
        M(Flags);
        MK(PublicKeyOrToken);
        M(Name);
        M(Culture);
        M(HashValue);
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<AssemblyRefProcessor>(nb::class_<AssemblyRefProcessor>& c, char const* name)
    {
        using R = AssemblyRefProcessor;
        M(Processor);
        MK(AssemblyRef);
    }

    template <>
    void bind_row_extras<AssemblyRefOS>(nb::class_<AssemblyRefOS>& c, char const* name)
    {
        using R = AssemblyRefOS;
        M(OSPlatformId);
        M(OSMajorVersion);
        M(OSMinorVersion);
        MK(AssemblyRef);
    }

    template <>
    void bind_row_extras<File>(nb::class_<File>& c, char const* name)
    {
        using R = File;
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<ExportedType>(nb::class_<ExportedType>& c, char const* name)
    {
        using R = ExportedType;
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<ManifestResource>(nb::class_<ManifestResource>& c, char const* name)
    {
        using R = ManifestResource;
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<NestedClass>(nb::class_<NestedClass>& c, char const* name)
    {
        using R = NestedClass;
        MK(NestedType);
        MK(EnclosingType);
    }

    template <>
    void bind_row_extras<GenericParam>(nb::class_<GenericParam>& c, char const* name)
    {
        using R = GenericParam;
        M(Number);
        M(Flags);
        MK(Owner);
        M(Name);
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<MethodSpec>(nb::class_<MethodSpec>& c, char const* name)
    {
        using R = MethodSpec;
        MR(CustomAttribute);
    }

    template <>
    void bind_row_extras<GenericParamConstraint>(nb::class_<GenericParamConstraint>& c,
        char const* name)
    {
        using R = GenericParamConstraint;
        MR(CustomAttribute);
    }

#undef M
#undef MK
#undef MR

    // The classes are registered up front (bind_rows_declare) and filled in later
    // (bind_rows) so that every type referenced by a row accessor - ranges,
    // coded_index, signatures, database - is already known to nanobind and shows
    // up under its Python name in the generated signatures.
    std::vector<nb::object> g_row_classes;

    // row_base<Row>: rows are values (a table pointer plus a row index) and at the
    // same time random access iterators, exactly as in C++.
    template <typename R>
    void bind_row(nb::class_<R>& c, char const* name)
    {
        c.def(nb::init<>())
            .def("index", &R::index)
            .def("get_value", [name](R const& self, uint32_t column)
                {
                    require_valid(self, name);
                    return self.template get_value<uint64_t>(column);
                }, nb::arg("column"))
            .def("get_database", [name](R const& self) -> database const&
                {
                    require_valid(self, name);
                    return self.get_database();
                }, nb::rv_policy::reference_internal)
            .def("get_cache", [name](R const& self) -> cache const&
                {
                    require_valid(self, name);
                    auto const* value = &self.get_cache();
                    if (value == nullptr)
                    {
                        throw std::runtime_error("the database was opened without a cache");
                    }
                    return *value;
                }, nb::rv_policy::reference_internal)
            .def("__bool__", [](R const& self) { return static_cast<bool>(self); })
            .def("__eq__", [](R const& self, R const& other) { return self == other; },
                nb::is_operator())
            .def("__ne__", [](R const& self, R const& other) { return self != other; },
                nb::is_operator())
            .def("__lt__", [](R const& self, R const& other) { return self < other; },
                nb::is_operator())
            .def("__le__", [](R const& self, R const& other) { return self <= other; },
                nb::is_operator())
            .def("__gt__", [](R const& self, R const& other) { return self > other; },
                nb::is_operator())
            .def("__ge__", [](R const& self, R const& other) { return self >= other; },
                nb::is_operator())
            .def("__hash__", [](R const& self)
                {
                    if (!self)
                    {
                        return size_t{ 0 };
                    }
                    auto const db = reinterpret_cast<uintptr_t>(&self.get_database());
                    return std::hash<uintptr_t>{}(db) ^ (std::hash<uint32_t>{}(self.index()) << 1);
                })
            .def("__add__", [](R const& self, int32_t offset) { return self + offset; },
                nb::arg("offset"), KA)
            .def("__sub__", [](R const& self, int32_t offset) { return self - offset; },
                nb::arg("offset"), KA)
            .def("__sub__", [](R const& self, R const& other) { return self - other; },
                nb::arg("other"))
            .def("__repr__", [name](R const& self)
                {
                    if (!self)
                    {
                        return "<winmd.reader." + std::string{ name } + " (empty)>";
                    }
                    return "<winmd.reader." + std::string{ name } + " index=" +
                        std::to_string(self.index()) + ">";
                });

        bind_row_extras<R>(c, name);
    }
}

void bind_rows_declare(nb::module_& m)
{
#define DECLARE_ROW(row) g_row_classes.push_back(nb::class_<row>(m, #row));
    WINMD_ROWS(DECLARE_ROW)
#undef DECLARE_ROW
}

void bind_rows(nb::module_&)
{
    size_t index = 0;
#define BIND_ROW(row)                                                                              \
    {                                                                                              \
        auto c = nb::borrow<nb::class_<row>>(g_row_classes[index++]);                  \
        bind_row<row>(c, #row);                                                                    \
    }
    WINMD_ROWS(BIND_ROW)
#undef BIND_ROW
    g_row_classes.clear();
}
