"""Python bindings for the Microsoft.Windows.WinMD C++ metadata parsing library.

The C++ interface is mirrored as directly as the Python object model allows::

    import winmd
    from winmd.reader import cache, TypeVisibility

    db = winmd.cache("metadata/Windows.Foundation.FoundationContract.winmd")
    type = db.find_required("Windows.Foundation", "IAsyncAction")

    for method in type.MethodList():
        print(method.Name(), method.Signature().ReturnType())

Everything lives in ``winmd.reader`` (mirroring ``winmd::reader``) and is
re-exported from ``winmd`` itself for convenience.
"""

import sys as _sys

from ._winmd import reader

# Makes `import winmd.reader` and `from winmd.reader import X` work even though
# `reader` is a pybind11 submodule rather than a file on disk.
_sys.modules[__name__ + ".reader"] = reader

_names = [_name for _name in dir(reader) if not _name.startswith("_")]

for _name in _names:
    globals()[_name] = getattr(reader, _name)

__all__ = ["reader", *_names]


def __dir__():
    return sorted(__all__)
