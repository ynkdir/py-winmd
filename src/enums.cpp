// enum.h and flags.h
#include "bind.h"

namespace
{
    // The Attributes structs expose the same name as getter and setter; Python
    // dispatches on the argument count.
#define FLAG_GET(cls, name) .def(#name, nb::overload_cast<>(&cls::name, nb::const_))
#define FLAG_BOOL(cls, name)                                                                       \
    FLAG_GET(cls, name)                                                                            \
    .def(#name, nb::overload_cast<bool>(&cls::name), nb::arg("arg"))
#define FLAG_ENUM(cls, name, type)                                                                 \
    FLAG_GET(cls, name)                                                                            \
    .def(#name, nb::overload_cast<type>(&cls::name), nb::arg("arg"))

    template <typename T>
    void add_flags_common(nb::class_<T>& c, char const* name)
    {
        using value_type = decltype(T::value);

        c.def(nb::init<>())
            .def("__init__", [](T* self, value_type value) { new (self) T{ { value } }; },
                nb::arg("value"))
            .def_rw("value", &T::value)
            .def("__int__", [](T const& self) { return self.value; })
            .def("__index__", [](T const& self) { return self.value; })
            .def("__eq__", [](T const& self, T const& other) { return self.value == other.value; },
                nb::is_operator())
            .def("__ne__", [](T const& self, T const& other) { return self.value != other.value; },
                nb::is_operator())
            .def("__hash__", [](T const& self) { return std::hash<value_type>{}(self.value); })
            .def("__repr__", [name](T const& self)
                {
                    return "<winmd.reader." + std::string{ name } + " " + to_hex(self.value) + ">";
                });
    }
}

void bind_enums(nb::module_& m)
{
    nb::enum_<TypeDefOrRef>(m, "TypeDefOrRef", nb::is_arithmetic())
        .value("TypeDef", TypeDefOrRef::TypeDef)
        .value("TypeRef", TypeDefOrRef::TypeRef)
        .value("TypeSpec", TypeDefOrRef::TypeSpec);

    nb::enum_<HasConstant>(m, "HasConstant", nb::is_arithmetic())
        .value("Field", HasConstant::Field)
        .value("Param", HasConstant::Param)
        .value("Property", HasConstant::Property);

    nb::enum_<HasCustomAttribute>(m, "HasCustomAttribute", nb::is_arithmetic())
        .value("MethodDef", HasCustomAttribute::MethodDef)
        .value("Field", HasCustomAttribute::Field)
        .value("TypeRef", HasCustomAttribute::TypeRef)
        .value("TypeDef", HasCustomAttribute::TypeDef)
        .value("Param", HasCustomAttribute::Param)
        .value("InterfaceImpl", HasCustomAttribute::InterfaceImpl)
        .value("MemberRef", HasCustomAttribute::MemberRef)
        .value("Module", HasCustomAttribute::Module)
        .value("Permission", HasCustomAttribute::Permission)
        .value("Property", HasCustomAttribute::Property)
        .value("Event", HasCustomAttribute::Event)
        .value("StandAloneSig", HasCustomAttribute::StandAloneSig)
        .value("ModuleRef", HasCustomAttribute::ModuleRef)
        .value("TypeSpec", HasCustomAttribute::TypeSpec)
        .value("Assembly", HasCustomAttribute::Assembly)
        .value("AssemblyRef", HasCustomAttribute::AssemblyRef)
        .value("File", HasCustomAttribute::File)
        .value("ExportedType", HasCustomAttribute::ExportedType)
        .value("ManifestResource", HasCustomAttribute::ManifestResource)
        .value("GenericParam", HasCustomAttribute::GenericParam)
        .value("GenericParamConstraint", HasCustomAttribute::GenericParamConstraint)
        .value("MethodSpec", HasCustomAttribute::MethodSpec);

    nb::enum_<HasFieldMarshal>(m, "HasFieldMarshal", nb::is_arithmetic())
        .value("Field", HasFieldMarshal::Field)
        .value("Param", HasFieldMarshal::Param);

    nb::enum_<HasDeclSecurity>(m, "HasDeclSecurity", nb::is_arithmetic())
        .value("TypeDef", HasDeclSecurity::TypeDef)
        .value("MethodDef", HasDeclSecurity::MethodDef)
        .value("Assembly", HasDeclSecurity::Assembly);

    nb::enum_<MemberRefParent>(m, "MemberRefParent", nb::is_arithmetic())
        .value("TypeDef", MemberRefParent::TypeDef)
        .value("TypeRef", MemberRefParent::TypeRef)
        .value("ModuleRef", MemberRefParent::ModuleRef)
        .value("MethodDef", MemberRefParent::MethodDef)
        .value("TypeSpec", MemberRefParent::TypeSpec);

    nb::enum_<HasSemantics>(m, "HasSemantics", nb::is_arithmetic())
        .value("Event", HasSemantics::Event)
        .value("Property", HasSemantics::Property);

    nb::enum_<MethodDefOrRef>(m, "MethodDefOrRef", nb::is_arithmetic())
        .value("MethodDef", MethodDefOrRef::MethodDef)
        .value("MemberRef", MethodDefOrRef::MemberRef);

    nb::enum_<MemberForwarded>(m, "MemberForwarded", nb::is_arithmetic())
        .value("Field", MemberForwarded::Field)
        .value("MethodDef", MemberForwarded::MethodDef);

    nb::enum_<Implementation>(m, "Implementation", nb::is_arithmetic())
        .value("File", Implementation::File)
        .value("AssemblyRef", Implementation::AssemblyRef)
        .value("ExportedType", Implementation::ExportedType);

    nb::enum_<CustomAttributeType>(m, "CustomAttributeType", nb::is_arithmetic())
        .value("MethodDef", CustomAttributeType::MethodDef)
        .value("MemberRef", CustomAttributeType::MemberRef);

    nb::enum_<ResolutionScope>(m, "ResolutionScope", nb::is_arithmetic())
        .value("Module", ResolutionScope::Module)
        .value("ModuleRef", ResolutionScope::ModuleRef)
        .value("AssemblyRef", ResolutionScope::AssemblyRef)
        .value("TypeRef", ResolutionScope::TypeRef);

    nb::enum_<TypeOrMethodDef>(m, "TypeOrMethodDef", nb::is_arithmetic())
        .value("TypeDef", TypeOrMethodDef::TypeDef)
        .value("MethodDef", TypeOrMethodDef::MethodDef);

    nb::enum_<MemberAccess>(m, "MemberAccess", nb::is_arithmetic())
        .value("CompilerControlled", MemberAccess::CompilerControlled)
        .value("Private", MemberAccess::Private)
        .value("FamAndAssem", MemberAccess::FamAndAssem)
        .value("Assembly", MemberAccess::Assembly)
        .value("Family", MemberAccess::Family)
        .value("FamOrAssem", MemberAccess::FamOrAssem)
        .value("Public", MemberAccess::Public);

    nb::enum_<TypeVisibility>(m, "TypeVisibility", nb::is_arithmetic())
        .value("NotPublic", TypeVisibility::NotPublic)
        .value("Public", TypeVisibility::Public)
        .value("NestedPublic", TypeVisibility::NestedPublic)
        .value("NestedPrivate", TypeVisibility::NestedPrivate)
        .value("NestedFamily", TypeVisibility::NestedFamily)
        .value("NestedAssembly", TypeVisibility::NestedAssembly)
        .value("NestedFamANDAssem", TypeVisibility::NestedFamANDAssem)
        .value("NestedFamORAssem", TypeVisibility::NestedFamORAssem);

    nb::enum_<TypeLayout>(m, "TypeLayout", nb::is_arithmetic())
        .value("AutoLayout", TypeLayout::AutoLayout)
        .value("SequentialLayout", TypeLayout::SequentialLayout)
        .value("ExplicitLayout", TypeLayout::ExplicitLayout);

    nb::enum_<TypeSemantics>(m, "TypeSemantics", nb::is_arithmetic())
        .value("Class", TypeSemantics::Class)
        .value("Interface", TypeSemantics::Interface);

    nb::enum_<StringFormat>(m, "StringFormat", nb::is_arithmetic())
        .value("AnsiClass", StringFormat::AnsiClass)
        .value("UnicodeClass", StringFormat::UnicodeClass)
        .value("AutoClass", StringFormat::AutoClass)
        .value("CustomFormatClass", StringFormat::CustomFormatClass)
        .value("CustomFormatMask", StringFormat::CustomFormatMask);

    nb::enum_<CodeType>(m, "CodeType", nb::is_arithmetic())
        .value("IL", CodeType::IL)
        .value("Native", CodeType::Native)
        .value("OPTIL", CodeType::OPTIL)
        .value("Runtime", CodeType::Runtime);

    nb::enum_<Managed>(m, "Managed", nb::is_arithmetic())
        .value("Unmanaged", Managed::Unmanaged)
        .value("Managed", Managed::Managed);

    nb::enum_<VtableLayout>(m, "VtableLayout", nb::is_arithmetic())
        .value("ReuseSlot", VtableLayout::ReuseSlot)
        .value("NewSlot", VtableLayout::NewSlot);

    nb::enum_<GenericParamVariance>(m, "GenericParamVariance", nb::is_arithmetic())
        .value("None_", GenericParamVariance::None)
        .value("Covariant", GenericParamVariance::Covariant)
        .value("Contravariant", GenericParamVariance::Contravariant);

    nb::enum_<GenericParamSpecialConstraint>(m, "GenericParamSpecialConstraint",
        nb::is_arithmetic(), nb::is_flag())
        .value("ReferenceTypeConstraint", GenericParamSpecialConstraint::ReferenceTypeConstraint)
        .value("NotNullableValueTypeConstraint",
            GenericParamSpecialConstraint::NotNullableValueTypeConstraint)
        .value("DefaultConstructorConstraint",
            GenericParamSpecialConstraint::DefaultConstructorConstraint);

    nb::enum_<ConstantType>(m, "ConstantType", nb::is_arithmetic())
        .value("Boolean", ConstantType::Boolean)
        .value("Char", ConstantType::Char)
        .value("Int8", ConstantType::Int8)
        .value("UInt8", ConstantType::UInt8)
        .value("Int16", ConstantType::Int16)
        .value("UInt16", ConstantType::UInt16)
        .value("Int32", ConstantType::Int32)
        .value("UInt32", ConstantType::UInt32)
        .value("Int64", ConstantType::Int64)
        .value("UInt64", ConstantType::UInt64)
        .value("Float32", ConstantType::Float32)
        .value("Float64", ConstantType::Float64)
        .value("String", ConstantType::String)
        .value("Class", ConstantType::Class);

    nb::enum_<ElementType>(m, "ElementType", nb::is_arithmetic())
        .value("End", ElementType::End)
        .value("Void", ElementType::Void)
        .value("Boolean", ElementType::Boolean)
        .value("Char", ElementType::Char)
        .value("I1", ElementType::I1)
        .value("U1", ElementType::U1)
        .value("I2", ElementType::I2)
        .value("U2", ElementType::U2)
        .value("I4", ElementType::I4)
        .value("U4", ElementType::U4)
        .value("I8", ElementType::I8)
        .value("U8", ElementType::U8)
        .value("R4", ElementType::R4)
        .value("R8", ElementType::R8)
        .value("String", ElementType::String)
        .value("Ptr", ElementType::Ptr)
        .value("ByRef", ElementType::ByRef)
        .value("ValueType", ElementType::ValueType)
        .value("Class", ElementType::Class)
        .value("Var", ElementType::Var)
        .value("Array", ElementType::Array)
        .value("GenericInst", ElementType::GenericInst)
        .value("TypedByRef", ElementType::TypedByRef)
        .value("I", ElementType::I)
        .value("U", ElementType::U)
        .value("FnPtr", ElementType::FnPtr)
        .value("Object", ElementType::Object)
        .value("SZArray", ElementType::SZArray)
        .value("MVar", ElementType::MVar)
        .value("CModReqd", ElementType::CModReqd)
        .value("CModOpt", ElementType::CModOpt)
        .value("Internal", ElementType::Internal)
        .value("Modifier", ElementType::Modifier)
        .value("Sentinel", ElementType::Sentinel)
        .value("Pinned", ElementType::Pinned)
        .value("Type", ElementType::Type)
        .value("TaggedObject", ElementType::TaggedObject)
        .value("Field", ElementType::Field)
        .value("Property", ElementType::Property)
        .value("Enum", ElementType::Enum);

    nb::enum_<CallingConvention>(m, "CallingConvention", nb::is_arithmetic(), nb::is_flag())
        .value("Default", CallingConvention::Default)
        .value("VarArg", CallingConvention::VarArg)
        .value("Field", CallingConvention::Field)
        .value("LocalSig", CallingConvention::LocalSig)
        .value("Property", CallingConvention::Property)
        .value("GenericInst", CallingConvention::GenericInst)
        .value("Mask", CallingConvention::Mask)
        .value("HasThis", CallingConvention::HasThis)
        .value("ExplicitThis", CallingConvention::ExplicitThis)
        .value("Generic", CallingConvention::Generic);

    nb::enum_<AssemblyHashAlgorithm>(m, "AssemblyHashAlgorithm", nb::is_arithmetic())
        .value("None_", AssemblyHashAlgorithm::None)
        .value("Reserved_MD5", AssemblyHashAlgorithm::Reserved_MD5)
        .value("SHA1", AssemblyHashAlgorithm::SHA1);

    nb::enum_<AssemblyFlags>(m, "AssemblyFlags", nb::is_arithmetic(), nb::is_flag())
        .value("PublicKey", AssemblyFlags::PublicKey)
        .value("Retargetable", AssemblyFlags::Retargetable)
        .value("WindowsRuntime", AssemblyFlags::WindowsRuntime)
        .value("DisableJITcompileOptimizer", AssemblyFlags::DisableJITcompileOptimizer)
        .value("EnableJITcompileTracking", AssemblyFlags::EnableJITcompileTracking);

    // type_helpers.h
    nb::enum_<category>(m, "category", nb::is_arithmetic())
        .value("interface_type", category::interface_type)
        .value("class_type", category::class_type)
        .value("enum_type", category::enum_type)
        .value("struct_type", category::struct_type)
        .value("delegate_type", category::delegate_type);

    m.def("enum_mask", [](ElementType value, ElementType mask) { return enum_mask(value, mask); },
        nb::arg("value"), nb::arg("mask"));
    m.def("enum_mask",
        [](CallingConvention value, CallingConvention mask) { return enum_mask(value, mask); },
        nb::arg("value"), nb::arg("mask"));
    m.def("enum_mask", [](AssemblyFlags value, AssemblyFlags mask) { return enum_mask(value, mask); },
        nb::arg("value"), nb::arg("mask"));
    m.def("enum_mask", [](StringFormat value, StringFormat mask) { return enum_mask(value, mask); },
        nb::arg("value"), nb::arg("mask"));
    m.def("enum_mask",
        [](GenericParamSpecialConstraint value, GenericParamSpecialConstraint mask)
        { return enum_mask(value, mask); }, nb::arg("value"), nb::arg("mask"));
}

void bind_flags(nb::module_& m)
{
    {
        nb::class_<AssemblyAttributes> c(m, "AssemblyAttributes");
        add_flags_common(c, "AssemblyAttributes");
        c FLAG_BOOL(AssemblyAttributes, WindowsRuntime);
    }
    {
        nb::class_<EventAttributes> c(m, "EventAttributes");
        add_flags_common(c, "EventAttributes");
        c FLAG_BOOL(EventAttributes, SpecialName)
            FLAG_BOOL(EventAttributes, RTSpecialName);
    }
    {
        nb::class_<FieldAttributes> c(m, "FieldAttributes");
        add_flags_common(c, "FieldAttributes");
        c FLAG_ENUM(FieldAttributes, Access, MemberAccess)
            FLAG_GET(FieldAttributes, Static)
            FLAG_GET(FieldAttributes, InitOnly)
            FLAG_GET(FieldAttributes, Literal)
            FLAG_GET(FieldAttributes, NotSerialized)
            FLAG_GET(FieldAttributes, SpecialName)
            FLAG_GET(FieldAttributes, PInvokeImpl)
            FLAG_GET(FieldAttributes, RTSpecialName)
            FLAG_GET(FieldAttributes, HasFieldMarshal)
            FLAG_GET(FieldAttributes, HasDefault)
            FLAG_GET(FieldAttributes, HasFieldRVA);
    }
    {
        nb::class_<GenericParamAttributes> c(m, "GenericParamAttributes");
        add_flags_common(c, "GenericParamAttributes");
        c FLAG_ENUM(GenericParamAttributes, Variance, GenericParamVariance)
            FLAG_ENUM(GenericParamAttributes, SpecialConstraint, GenericParamSpecialConstraint);
    }
    {
        nb::class_<MethodAttributes> c(m, "MethodAttributes");
        add_flags_common(c, "MethodAttributes");
        c FLAG_ENUM(MethodAttributes, Access, MemberAccess)
            FLAG_BOOL(MethodAttributes, Static)
            FLAG_BOOL(MethodAttributes, Final)
            FLAG_BOOL(MethodAttributes, Virtual)
            FLAG_BOOL(MethodAttributes, HideBySig)
            FLAG_ENUM(MethodAttributes, Layout, VtableLayout)
            FLAG_BOOL(MethodAttributes, Strict)
            FLAG_BOOL(MethodAttributes, Abstract)
            FLAG_BOOL(MethodAttributes, SpecialName)
            FLAG_BOOL(MethodAttributes, PInvokeImpl)
            FLAG_BOOL(MethodAttributes, UnmanagedExport)
            FLAG_BOOL(MethodAttributes, RTSpecialName)
            FLAG_BOOL(MethodAttributes, HasSecurity)
            FLAG_BOOL(MethodAttributes, RequireSecObject);
    }
    {
        nb::class_<MethodImplAttributes> c(m, "MethodImplAttributes");
        add_flags_common(c, "MethodImplAttributes");
        c FLAG_ENUM(MethodImplAttributes, CodeType, CodeType)
            FLAG_ENUM(MethodImplAttributes, Managed, Managed)
            FLAG_BOOL(MethodImplAttributes, ForwardRef)
            FLAG_BOOL(MethodImplAttributes, PreserveSig)
            FLAG_BOOL(MethodImplAttributes, InternalCall)
            FLAG_BOOL(MethodImplAttributes, Synchronized)
            FLAG_BOOL(MethodImplAttributes, NoInlining)
            FLAG_BOOL(MethodImplAttributes, NoOptimization);
    }
    {
        nb::class_<MethodSemanticsAttributes> c(m, "MethodSemanticsAttributes");
        add_flags_common(c, "MethodSemanticsAttributes");
        c FLAG_BOOL(MethodSemanticsAttributes, Setter)
            FLAG_BOOL(MethodSemanticsAttributes, Getter)
            FLAG_BOOL(MethodSemanticsAttributes, Other)
            FLAG_BOOL(MethodSemanticsAttributes, AddOn)
            FLAG_BOOL(MethodSemanticsAttributes, RemoveOn)
            FLAG_BOOL(MethodSemanticsAttributes, Fire);
    }
    {
        nb::class_<ParamAttributes> c(m, "ParamAttributes");
        add_flags_common(c, "ParamAttributes");
        c FLAG_BOOL(ParamAttributes, In)
            FLAG_BOOL(ParamAttributes, Out)
            FLAG_BOOL(ParamAttributes, Optional)
            FLAG_BOOL(ParamAttributes, HasDefault)
            FLAG_BOOL(ParamAttributes, HasFieldMarshal);
    }
    {
        nb::class_<PropertyAttributes> c(m, "PropertyAttributes");
        add_flags_common(c, "PropertyAttributes");
        c FLAG_BOOL(PropertyAttributes, SpecialName)
            FLAG_BOOL(PropertyAttributes, RTSpecialName)
            FLAG_BOOL(PropertyAttributes, HasDefault);
    }
    {
        nb::class_<TypeAttributes> c(m, "TypeAttributes");
        add_flags_common(c, "TypeAttributes");
        c FLAG_ENUM(TypeAttributes, Visibility, TypeVisibility)
            FLAG_ENUM(TypeAttributes, Layout, TypeLayout)
            FLAG_ENUM(TypeAttributes, Semantics, TypeSemantics)
            FLAG_BOOL(TypeAttributes, Abstract)
            FLAG_BOOL(TypeAttributes, Sealed)
            FLAG_BOOL(TypeAttributes, SpecialName)
            FLAG_BOOL(TypeAttributes, Import)
            FLAG_BOOL(TypeAttributes, Serializable)
            FLAG_BOOL(TypeAttributes, WindowsRuntime)
            FLAG_ENUM(TypeAttributes, StringFormat, StringFormat)
            FLAG_BOOL(TypeAttributes, BeforeFieldInit)
            FLAG_BOOL(TypeAttributes, RTSpecialName)
            FLAG_BOOL(TypeAttributes, HasSecurity)
            FLAG_BOOL(TypeAttributes, IsTypeForwarder);
    }

    // column.h
    nb::class_<AssemblyVersion>(m, "AssemblyVersion")
        .def(nb::init<>())
        .def("__init__", [](AssemblyVersion* self, uint16_t major, uint16_t minor, uint16_t build,
            uint16_t revision) { new (self) AssemblyVersion{ major, minor, build, revision }; },
            nb::arg("MajorVersion"), nb::arg("MinorVersion"), nb::arg("BuildNumber"),
            nb::arg("RevisionNumber"))
        .def_rw("MajorVersion", &AssemblyVersion::MajorVersion)
        .def_rw("MinorVersion", &AssemblyVersion::MinorVersion)
        .def_rw("BuildNumber", &AssemblyVersion::BuildNumber)
        .def_rw("RevisionNumber", &AssemblyVersion::RevisionNumber)
        .def("__repr__", [](AssemblyVersion const& self)
            {
                return "<winmd.reader.AssemblyVersion " + std::to_string(self.MajorVersion) + "." +
                    std::to_string(self.MinorVersion) + "." + std::to_string(self.BuildNumber) +
                    "." + std::to_string(self.RevisionNumber) + ">";
            });
}
