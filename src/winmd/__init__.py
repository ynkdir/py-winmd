"""A reader for Windows Metadata (.winmd), the ECMA-335 tables behind WinRT
and Win32, in nothing but the standard library.

    import winmd
    from winmd.reader import cache, get_category

    db = cache([r"C:\\Windows\\System32\\WinMetadata\\Windows.Foundation.winmd"])
    type = db.find_required("Windows.Foundation", "Uri")

    print(type.TypeNamespace(), type.TypeName(), get_category(type))
    for method in type.MethodList():
        print(method.Name(), [p.Type().Type() for p in method.Signature().Params()])

The interface follows Microsoft.Windows.WinMD, the C++ reader this was written
against and is tested against: every accessor is a method call, named as in C++
- `type.TypeName()`, not `type.name`. Everything lives in `winmd.reader` and is
re-exported from `winmd` itself.

Where the .winmd files come from:

    WinRT   C:\\Windows\\System32\\WinMetadata\\*.winmd, on any Windows 10 or 11
            machine, or the Microsoft.Windows.SDK.Contracts NuGet package
    Win32   the Microsoft.Windows.SDK.Win32Metadata NuGet package (prerelease)

In Win32 metadata the functions and constants of a namespace are the members of
a static class named Apis; the types sit beside it. Nothing is found without
that.
"""

from . import reader as reader

_names = [_name for _name in dir(reader) if not _name.startswith("_")]

for _name in _names:
    globals()[_name] = getattr(reader, _name)

__all__ = ["reader", *_names]


def __dir__():
    return sorted(__all__)
