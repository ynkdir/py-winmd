// Describes metadata with the C++ reader, in the text tests/describe.py writes.
//
//     reference <winmd file> [more files ...]
//
// This is the reference the Python reader is tested against: the two describe
// the same types and the descriptions have to match, line for line. Built and
// run by tests/test_reference.py, which passes the same files to both.
//
// The library is Microsoft.Windows.WinMD, header only; fetch-metadata.py
// --headers puts it where the test looks for it.

#include "winmd_reader.h"

#include <algorithm>
#include <cinttypes>
#include <cstdarg>
#include <cstdio>
#include <string>
#include <string_view>
#include <vector>

using namespace winmd::reader;

namespace
{
    // The usual visitor helper; the library does not export one.
    template <typename... T> struct overloaded : T... { using T::operator()...; };
    template <typename... T> overloaded(T...) -> overloaded<T...>;

    std::string out;

    void line(std::string const& text)
    {
        out += text;
        out += '\n';
    }

    std::string format(char const* fmt, ...)
    {
        char buffer[512];
        va_list args;
        va_start(args, fmt);
        vsnprintf(buffer, sizeof(buffer), fmt, args);
        va_end(args);
        return buffer;
    }

    std::string text(std::string_view value)
    {
        return std::string{ value };
    }

    // --- values, spelled the way describe.py spells them ------------------
    std::string boolean(bool value)
    {
        return value ? "True" : "False";
    }

    std::string quoted(std::string_view value)
    {
        std::string result = "\"";
        for (unsigned char c : value)
        {
            switch (c)
            {
            case '\\': result += "\\\\"; break;
            case '"': result += "\\\""; break;
            case '\n': result += "\\n"; break;
            case '\r': result += "\\r"; break;
            case '\t': result += "\\t"; break;
            default:
                if (c < 0x20 || c >= 0x7f)
                {
                    result += format("\\x%02x", c);
                }
                else
                {
                    result += static_cast<char>(c);
                }
            }
        }
        return result + "\"";
    }

    std::string quoted(std::u16string_view value)
    {
        std::string result = "\"";
        for (char16_t c : value)
        {
            if (c == u'\\') result += "\\\\";
            else if (c == u'"') result += "\\\"";
            else if (c == u'\n') result += "\\n";
            else if (c == u'\r') result += "\\r";
            else if (c == u'\t') result += "\\t";
            else if (c < 0x20 || c >= 0x7f) result += format("\\u%04x", (unsigned)c);
            else result += static_cast<char>(c);
        }
        return result + "\"";
    }

    template <typename T>
    std::string number(T value)
    {
        if constexpr (std::is_same_v<T, bool>)
        {
            return boolean(value);
        }
        else if constexpr (std::is_same_v<T, char16_t>)
        {
            return format("char(0x%04x)", (unsigned)value);
        }
        else if constexpr (std::is_floating_point_v<T>)
        {
            return format("%.6g", (double)value);
        }
        else if constexpr (std::is_signed_v<T>)
        {
            return format("%" PRId64, (int64_t)value);
        }
        else
        {
            return format("%" PRIu64, (uint64_t)value);
        }
    }

    std::string constant_value(Constant const& constant)
    {
        return std::visit([](auto&& value) -> std::string
        {
            using T = std::decay_t<decltype(value)>;
            if constexpr (std::is_same_v<T, std::u16string_view>)
            {
                return quoted(value);
            }
            else if constexpr (std::is_same_v<T, std::nullptr_t>)
            {
                return "None";
            }
            else
            {
                return number(value);
            }
        }, constant.Value());
    }

    // --- names -------------------------------------------------------------
    std::string reference_name(coded_index<TypeDefOrRef> const& index)
    {
        if (!index || index.type() == TypeDefOrRef::TypeSpec)
        {
            return "<TypeSpec>";
        }
        auto const [ns, name] = get_type_namespace_and_name(index);
        return text(ns) + "." + text(name);
    }

    char const* element_type_name(ElementType type)
    {
        switch (type)
        {
        case ElementType::End: return "End";
        case ElementType::Void: return "Void";
        case ElementType::Boolean: return "Boolean";
        case ElementType::Char: return "Char";
        case ElementType::I1: return "I1";
        case ElementType::U1: return "U1";
        case ElementType::I2: return "I2";
        case ElementType::U2: return "U2";
        case ElementType::I4: return "I4";
        case ElementType::U4: return "U4";
        case ElementType::I8: return "I8";
        case ElementType::U8: return "U8";
        case ElementType::R4: return "R4";
        case ElementType::R8: return "R8";
        case ElementType::String: return "String";
        case ElementType::Ptr: return "Ptr";
        case ElementType::ByRef: return "ByRef";
        case ElementType::ValueType: return "ValueType";
        case ElementType::Class: return "Class";
        case ElementType::Var: return "Var";
        case ElementType::Array: return "Array";
        case ElementType::GenericInst: return "GenericInst";
        case ElementType::TypedByRef: return "TypedByRef";
        case ElementType::I: return "I";
        case ElementType::U: return "U";
        case ElementType::FnPtr: return "FnPtr";
        case ElementType::Object: return "Object";
        case ElementType::SZArray: return "SZArray";
        case ElementType::MVar: return "MVar";
        case ElementType::CModReqd: return "CModReqd";
        case ElementType::CModOpt: return "CModOpt";
        case ElementType::Internal: return "Internal";
        case ElementType::Modifier: return "Modifier";
        case ElementType::Sentinel: return "Sentinel";
        case ElementType::Pinned: return "Pinned";
        case ElementType::Type: return "Type";
        case ElementType::TaggedObject: return "TaggedObject";
        case ElementType::Field: return "Field";
        case ElementType::Property: return "Property";
        case ElementType::Enum: return "Enum";
        default: return "?";
        }
    }

    std::string type_name(TypeSig const& sig)
    {
        std::string name = std::visit(overloaded{
            [](ElementType type) { return std::string{ element_type_name(type) }; },
            [](coded_index<TypeDefOrRef> const& index) { return reference_name(index); },
            [](GenericTypeIndex index) { return format("!%u", index.index); },
            [](GenericMethodTypeIndex index) { return format("!!%u", index.index); },
            [](GenericTypeInstSig const& inst) -> std::string
            {
                std::string result = reference_name(inst.GenericType()) + "<";
                bool first = true;
                for (auto&& argument : inst.GenericArgs())
                {
                    if (!first) result += ", ";
                    first = false;
                    result += type_name(argument);
                }
                return result + ">";
            },
        }, sig.Type());

        if (sig.is_szarray())
        {
            name += "[]";
        }
        for (int i = 0; i < sig.ptr_count(); ++i)
        {
            name += "*";
        }
        return name;
    }

    // --- custom attributes -------------------------------------------------
    std::string element(ElemSig const& elem)
    {
        return std::visit(overloaded{
            [](ElemSig::SystemType const& type) { return "typeof(" + text(type.name) + ")"; },
            [](ElemSig::EnumValue const& value)
            {
                auto const inner = std::visit([](auto&& v) { return number(v); }, value.value);
                return "enum(" + text(value.type.m_typedef.TypeName()) + ", " + inner + ")";
            },
            [](std::string_view value) { return quoted(value); },
            [](auto&& value) { return number(value); },
        }, elem.value);
    }

    std::string argument(FixedArgSig const& arg)
    {
        return std::visit(overloaded{
            [](ElemSig const& elem) { return element(elem); },
            [](std::vector<ElemSig> const& elems)
            {
                std::string result = "[";
                bool first = true;
                for (auto&& elem : elems)
                {
                    if (!first) result += ", ";
                    first = false;
                    result += element(elem);
                }
                return result + "]";
            },
        }, arg.value);
    }

    template <typename Row>
    void attributes(Row const& row, char const* indent)
    {
        for (auto&& attribute : row.CustomAttribute())
        {
            auto const [ns, name] = attribute.TypeNamespaceAndName();
            std::string arguments;
            try
            {
                auto const signature = attribute.Value();
                bool first = true;
                for (auto&& fixed : signature.FixedArgs())
                {
                    if (!first) arguments += ", ";
                    first = false;
                    arguments += argument(fixed);
                }
                for (auto&& named : signature.NamedArgs())
                {
                    if (!first) arguments += ", ";
                    first = false;
                    arguments += text(named.name) + "=" + argument(named.value);
                }
            }
            catch (...)
            {
                arguments = "<error>";
            }
            line(std::string{ indent } + "attribute " + text(ns) + "." + text(name) +
                 "(" + arguments + ")");
        }
    }

    // --- the description ---------------------------------------------------
    char const* category_name(category value)
    {
        switch (value)
        {
        case category::interface_type: return "interface_type";
        case category::class_type: return "class_type";
        case category::enum_type: return "enum_type";
        case category::struct_type: return "struct_type";
        case category::delegate_type: return "delegate_type";
        default: return "?";
        }
    }

    char const* visibility_name(TypeVisibility value)
    {
        switch (value)
        {
        case TypeVisibility::NotPublic: return "NotPublic";
        case TypeVisibility::Public: return "Public";
        case TypeVisibility::NestedPublic: return "NestedPublic";
        case TypeVisibility::NestedPrivate: return "NestedPrivate";
        case TypeVisibility::NestedFamily: return "NestedFamily";
        case TypeVisibility::NestedAssembly: return "NestedAssembly";
        case TypeVisibility::NestedFamANDAssem: return "NestedFamANDAssem";
        case TypeVisibility::NestedFamORAssem: return "NestedFamORAssem";
        default: return "?";
        }
    }

    char const* layout_name(TypeLayout value)
    {
        switch (value)
        {
        case TypeLayout::AutoLayout: return "AutoLayout";
        case TypeLayout::SequentialLayout: return "SequentialLayout";
        case TypeLayout::ExplicitLayout: return "ExplicitLayout";
        default: return "?";
        }
    }

    void describe(TypeDef const& type)
    {
        line("type " + text(type.TypeNamespace()) + "." + text(type.TypeName()));

        auto const flags = type.Flags();
        line(format("  flags 0x%x %s visibility=%s layout=%s semantics=%s "
                    "abstract=%s sealed=%s special=%s",
                    flags.value, category_name(get_category(type)),
                    visibility_name(flags.Visibility()), layout_name(flags.Layout()),
                    flags.Semantics() == TypeSemantics::Interface ? "Interface" : "Class",
                    boolean(flags.Abstract()).c_str(), boolean(flags.Sealed()).c_str(),
                    boolean(flags.SpecialName()).c_str()));

        std::string base;
        if (type.Extends())
        {
            auto const [ns, name] = get_base_class_namespace_and_name(type);
            base = text(ns) + "." + text(name);
        }
        line("  extends " + base);
        line("  nested " + boolean(is_nested(type)));

        for (auto&& impl : type.InterfaceImpl())
        {
            line("  implements " + reference_name(impl.Interface()));
        }
        for (auto&& parameter : type.GenericParam())
        {
            line(format("  generic %u ", parameter.Number()) + text(parameter.Name()));
        }
        attributes(type, "  ");

        for (auto&& field : type.FieldList())
        {
            std::string value;
            if (field.Flags().Literal())
            {
                value = " = " + constant_value(field.Constant());
            }
            line("  field " + text(field.Name()) + " : " +
                 type_name(field.Signature().Type()) + value);
            attributes(field, "    ");
        }

        for (auto&& method : type.MethodList())
        {
            auto const signature = method.Signature();
            std::string returns = signature.ReturnType()
                ? type_name(signature.ReturnType().Type()) : "void";

            std::vector<Param> rows;
            for (auto&& row : method.ParamList())
            {
                rows.push_back(row);
            }

            std::string parameters;
            uint32_t index = 1;
            for (auto&& param : signature.Params())
            {
                if (index > 1) parameters += ", ";
                parameters += type_name(param.Type());
                if (param.ByRef()) parameters += "&";
                parameters += " ";

                Param const* found = nullptr;
                for (auto&& row : rows)
                {
                    if (row.Sequence() == index) { found = &row; break; }
                }
                if (found)
                {
                    parameters += text(found->Name()) +
                        "[in=" + boolean(found->Flags().In()) +
                        " out=" + boolean(found->Flags().Out()) + "]";
                }
                else
                {
                    parameters += "?";
                }
                ++index;
            }

            line("  method " + returns + " " + text(method.Name()) + "(" + parameters +
                 ") " + format("conv=0x%x generic=%u flags=0x%x",
                               (unsigned)signature.CallConvention(),
                               signature.GenericParamCount(), method.Flags().value));
            attributes(method, "    ");
        }

        for (auto&& property : type.PropertyList())
        {
            line("  property " + text(property.Name()) + " : " +
                 type_name(property.Type().Type()));
        }
        for (auto&& event : type.EventList())
        {
            line("  event " + text(event.Name()) + " : " +
                 reference_name(event.EventType()));
        }
    }
}

int main(int argc, char** argv)
{
    if (argc < 2)
    {
        fprintf(stderr, "usage: reference <winmd file> [more files ...]\n");
        return 2;
    }

    std::vector<std::string> files;
    for (int index = 1; index < argc; ++index)
    {
        files.emplace_back(argv[index]);
    }

    cache const db{ files };

    std::vector<std::pair<std::string_view, std::string_view>> types;
    for (auto&& [namespace_name, members] : db.namespaces())
    {
        for (auto&& [name, type] : members.types)
        {
            types.emplace_back(namespace_name, name);
        }
    }
    std::sort(types.begin(), types.end());

    out.reserve(1 << 24);
    for (auto&& [namespace_name, name] : types)
    {
        describe(db.find_required(namespace_name, name));
    }

    fwrite(out.data(), 1, out.size(), stdout);
    return 0;
}

