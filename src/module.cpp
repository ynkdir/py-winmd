#include "bind.h"

NB_MODULE(_winmd, m)
{
    m.doc() = "Python bindings for the Microsoft.Windows.WinMD C++ metadata reader.";

    auto reader = m.def_submodule("reader", "winmd::reader");

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
