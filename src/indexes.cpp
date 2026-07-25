// table.h / index.h / key.h - coded_index<T>
#include "bind.h"

namespace
{
    // index_base<T>::get_row<Row>(), but the type tag is verified instead of
    // asserted, so a mismatch raises instead of reading a bogus row.
    template <typename Index, typename Row>
    Row get_row(coded_index<Index> const& self, char const* name)
    {
        require_valid(self, name);
        if (self.type() != index_tag_v<Index, Row>)
        {
            throw std::runtime_error(std::string{ "coded_index does not hold the requested row type" });
        }
        return self.template get_row<Row>();
    }

    template <typename Index>
    void bind_index_extras(nb::class_<coded_index<Index>>&, char const*)
    {
    }

    // Adds an accessor named after the target row type, e.g. index.TypeDef().
#define ROW(target)                                                                                \
    c.def(#target, [name](coded_index<I> const& self) { return get_row<I, target>(self, name); }, KA)

    template <>
    void bind_index_extras<TypeDefOrRef>(nb::class_<coded_index<TypeDefOrRef>>& c, char const* name)
    {
        using I = TypeDefOrRef;
        ROW(TypeDef);
        ROW(TypeRef);
        ROW(TypeSpec);
        c.def("CustomAttribute", [name](coded_index<I> const& self)
            {
                require_valid(self, name);
                return make_range(self.CustomAttribute());
            }, KA);
    }

    template <>
    void bind_index_extras<HasConstant>(nb::class_<coded_index<HasConstant>>& c, char const* name)
    {
        using I = HasConstant;
        ROW(Field);
        ROW(Param);
        ROW(Property);
    }

    template <>
    void bind_index_extras<HasCustomAttribute>(nb::class_<coded_index<HasCustomAttribute>>& c,
        char const* name)
    {
        using I = HasCustomAttribute;
        ROW(MethodDef);
        ROW(Field);
        ROW(TypeRef);
        ROW(TypeDef);
        ROW(Param);
        ROW(InterfaceImpl);
        ROW(MemberRef);
        ROW(Module);
        ROW(Property);
        ROW(Event);
        ROW(StandAloneSig);
        ROW(ModuleRef);
        ROW(TypeSpec);
        ROW(Assembly);
        ROW(AssemblyRef);
        ROW(File);
        ROW(ExportedType);
        ROW(ManifestResource);
        ROW(GenericParam);
        ROW(GenericParamConstraint);
        ROW(MethodSpec);
    }

    template <>
    void bind_index_extras<HasFieldMarshal>(nb::class_<coded_index<HasFieldMarshal>>& c,
        char const* name)
    {
        using I = HasFieldMarshal;
        ROW(Field);
        ROW(Param);
    }

    template <>
    void bind_index_extras<HasDeclSecurity>(nb::class_<coded_index<HasDeclSecurity>>& c,
        char const* name)
    {
        using I = HasDeclSecurity;
        ROW(TypeDef);
        ROW(MethodDef);
        ROW(Assembly);
    }

    template <>
    void bind_index_extras<MemberRefParent>(nb::class_<coded_index<MemberRefParent>>& c,
        char const* name)
    {
        using I = MemberRefParent;
        ROW(TypeDef);
        ROW(TypeRef);
        ROW(ModuleRef);
        ROW(MethodDef);
        ROW(TypeSpec);
    }

    template <>
    void bind_index_extras<HasSemantics>(nb::class_<coded_index<HasSemantics>>& c, char const* name)
    {
        using I = HasSemantics;
        ROW(Event);
        ROW(Property);
    }

    template <>
    void bind_index_extras<MethodDefOrRef>(nb::class_<coded_index<MethodDefOrRef>>& c,
        char const* name)
    {
        using I = MethodDefOrRef;
        ROW(MethodDef);
        ROW(MemberRef);
    }

    template <>
    void bind_index_extras<MemberForwarded>(nb::class_<coded_index<MemberForwarded>>& c,
        char const* name)
    {
        using I = MemberForwarded;
        ROW(Field);
        ROW(MethodDef);
    }

    template <>
    void bind_index_extras<Implementation>(nb::class_<coded_index<Implementation>>& c,
        char const* name)
    {
        using I = Implementation;
        ROW(File);
        ROW(AssemblyRef);
        ROW(ExportedType);
    }

    template <>
    void bind_index_extras<CustomAttributeType>(nb::class_<coded_index<CustomAttributeType>>& c,
        char const* name)
    {
        using I = CustomAttributeType;
        ROW(MethodDef);
        ROW(MemberRef);
    }

    template <>
    void bind_index_extras<ResolutionScope>(nb::class_<coded_index<ResolutionScope>>& c,
        char const* name)
    {
        using I = ResolutionScope;
        ROW(Module);
        ROW(ModuleRef);
        ROW(AssemblyRef);
        ROW(TypeRef);
    }

    template <>
    void bind_index_extras<TypeOrMethodDef>(nb::class_<coded_index<TypeOrMethodDef>>& c,
        char const* name)
    {
        using I = TypeOrMethodDef;
        ROW(TypeDef);
        ROW(MethodDef);
    }

#undef ROW

    template <typename Index>
    void bind_index(nb::module_& m, char const* name)
    {
        using I = coded_index<Index>;

        nb::class_<I> c(m, name);

        c.def(nb::init<>())
            .def("type", [name](I const& self) { require_valid(self, name); return self.type(); })
            .def("index", [name](I const& self) { require_valid(self, name); return self.index(); })
            .def("get_database", [name](I const& self) -> database const&
                {
                    require_valid(self, name);
                    return self.get_database();
                }, nb::rv_policy::reference_internal)
            .def("__bool__", [](I const& self) { return static_cast<bool>(self); })
            .def("__eq__", [](I const& self, I const& other) { return self == other; },
                nb::is_operator())
            .def("__ne__", [](I const& self, I const& other) { return self != other; },
                nb::is_operator())
            .def("__lt__", [](I const& self, I const& other) { return self < other; },
                nb::is_operator())
            .def("__hash__", [](I const& self)
                {
                    if (!self)
                    {
                        return size_t{ 0 };
                    }
                    auto const db = reinterpret_cast<uintptr_t>(&self.get_database());
                    return std::hash<uintptr_t>{}(db) ^
                        (std::hash<uint32_t>{}(self.index()) << 1) ^
                        (std::hash<uint32_t>{}(static_cast<uint32_t>(self.type())) << 2);
                })
            .def("__repr__", [name](I const& self)
                {
                    if (!self)
                    {
                        return "<winmd.reader." + std::string{ name } + " (empty)>";
                    }
                    return "<winmd.reader." + std::string{ name } + " type=" +
                        std::to_string(static_cast<uint32_t>(self.type())) + " index=" +
                        std::to_string(self.index()) + ">";
                });

        bind_index_extras<Index>(c, name);
    }
}

void bind_indexes(nb::module_& m)
{
#define BIND_INDEX(index) bind_index<index>(m, "coded_index_" #index);
    WINMD_INDEXES(BIND_INDEX)
#undef BIND_INDEX
}
