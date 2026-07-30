#include "bind.h"

NB_MODULE(_winmd, m)
{
    m.doc() = "Python bindings for the Microsoft.Windows.WinMD C++ metadata reader.";

    auto reader = m.def_submodule("reader", R"(Reads Windows Metadata (.winmd), the ECMA-335 tables behind WinRT and Win32.

    from winmd.reader import cache, get_category

    db = cache([r"C:\Windows\System32\WinMetadata\Windows.Foundation.winmd"])
    type = db.find_required("Windows.Foundation", "Uri")

    print(type.TypeNamespace(), type.TypeName(), get_category(type))
    for method in type.MethodList():
        print(method.Name(), [p.Type().Type() for p in method.Signature().Params()])

The interface is the C++ one, so every accessor is a method call, named as in
C++: type.TypeName(), not type.name. Start from a cache, which indexes the
types of the files it is given by namespace, and keep it alive as long as
anything taken out of it is used.

Where the .winmd files come from:

    WinRT   C:\Windows\System32\WinMetadata\*.winmd, on any Windows 10 or 11
            machine, or the Microsoft.Windows.SDK.Contracts NuGet package
    Win32   the Microsoft.Windows.SDK.Win32Metadata NuGet package (prerelease)

In Win32 metadata the functions and constants of a namespace are the members of
a static class named Apis; the types sit beside it. Nothing is found without
that.

See help() on cache, database, TypeDef, MethodDef and get_attribute, and the
project README for the whole of it.)");

    // std::invalid_argument (impl::throw_invalid) already maps to ValueError.
    // The row classes are declared first and defined last: by then every type a
    // row accessor can return is registered, so the generated signatures use the
    // Python names instead of the raw C++ ones.
    bind_enums(reader);
    bind_flags(reader);
    bind_view(reader);
    bind_rows_declare(reader);
    bind_tables(reader);
    bind_indexes(reader);
    bind_signatures(reader);
    bind_cache(reader);
    bind_rows(reader);
    bind_helpers(reader);
}
