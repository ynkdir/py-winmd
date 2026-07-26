"""WinRT, resolved from the metadata when an attribute is looked up.

    import winrt

    winrt.init()

    uri = winrt.Windows.Foundation.Uri("https://example.com/a/b?x=1")
    print(uri.Domain, uri.Path, uri.Query)
    print(uri.ToString())                       # IStringable, reached by QueryInterface

    calendar = winrt.Windows.Globalization.Calendar()
    print(calendar.Year, calendar.Month, calendar.Day)

    print(winrt.Windows.Foundation.Uri.EscapeComponent("a b"))   # a static member

This is the WinRT counterpart of win32api.py: namespaces, runtime classes,
interfaces, structs and enums are built out of the metadata on demand and
dispatched through ctypes. What it covers:

    * activation - IActivationFactory.ActivateInstance, the factory interfaces
      of ActivatableAttribute, and the static interfaces of StaticAttribute
    * calls through the vtable, with the six IInspectable slots in front of the
      methods an interface declares itself
    * the [out, retval] convention: the HRESULT is checked and the trailing out
      parameter is what a call returns
    * HSTRING in and out, properties (get_X/put_X), and QueryInterface to the
      non-default interfaces of a runtime class

What it does not cover: parameterized interfaces (IVector<T>, IAsyncOperation<T>
- their IID has to be computed by hashing the type signature), implementing
delegates in Python, and therefore events and awaiting async operations.

The metadata is C:\\Windows\\System32\\WinMetadata\\*.winmd, the metadata of the
running system; call configure(*files) to read others.
"""

import ctypes
import glob
import keyword
import os
import re
import sys
from ctypes import (  # noqa: F401  (re-exported for convenience)
    POINTER,
    Structure,
    Union,
    WINFUNCTYPE,
    byref,
    c_void_p,
    cast,
    pointer,
    sizeof,
)
from enum import IntEnum, IntFlag

from winmd.reader import (
    ElementType,
    TypeDefOrRef,
    TypeLayout,
    cache,
    category,
    coded_index_TypeDefOrRef,
    find,
    get_attribute,
    get_category,
)

METADATA_ATTRIBUTES = "Windows.Foundation.Metadata"

HRESULT = ctypes.c_int32

# The WinRT ABI: everything an interface declares sits after IInspectable.
IINSPECTABLE_SLOTS = 6

PRIMITIVES = {
    ElementType.Void: None,
    ElementType.Boolean: ctypes.c_bool,
    ElementType.Char: ctypes.c_uint16,
    ElementType.I1: ctypes.c_int8,
    ElementType.U1: ctypes.c_uint8,
    ElementType.I2: ctypes.c_int16,
    ElementType.U2: ctypes.c_uint16,
    ElementType.I4: ctypes.c_int32,
    ElementType.U4: ctypes.c_uint32,
    ElementType.I8: ctypes.c_int64,
    ElementType.U8: ctypes.c_uint64,
    ElementType.R4: ctypes.c_float,
    ElementType.R8: ctypes.c_double,
    ElementType.I: ctypes.c_ssize_t,
    ElementType.U: ctypes.c_size_t,
    ElementType.Object: c_void_p,   # IInspectable*
}


class GUID(Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]

    def __init__(self, value=None):
        super().__init__()
        if value:
            text = value.strip("{}").replace("-", "")
            self.Data1 = int(text[0:8], 16)
            self.Data2 = int(text[8:12], 16)
            self.Data3 = int(text[12:16], 16)
            for index in range(8):
                self.Data4[index] = int(text[16 + index * 2 : 18 + index * 2], 16)

    def __str__(self):
        data4 = bytes(self.Data4)
        return "{{{:08x}-{:04x}-{:04x}-{}-{}}}".format(
            self.Data1, self.Data2, self.Data3, data4[:2].hex(), data4[2:].hex()
        )


class HSTRING(c_void_p):
    """A WinRT string handle."""


class WinRTError(OSError):
    def __init__(self, hr):
        self.hresult = hr & 0xFFFFFFFF
        super().__init__(f"0x{self.hresult:08X}: {ctypes.FormatError(hr).strip()}")


def _check(hr):
    if hr < 0:
        raise WinRTError(hr)
    return hr


# --- combase ----------------------------------------------------------------
_combase = ctypes.WinDLL("combase.dll")

_RoInitialize = _combase.RoInitialize
_RoInitialize.restype, _RoInitialize.argtypes = HRESULT, [ctypes.c_int32]

_RoUninitialize = _combase.RoUninitialize
_RoUninitialize.restype, _RoUninitialize.argtypes = None, []

_RoGetActivationFactory = _combase.RoGetActivationFactory
_RoGetActivationFactory.restype = HRESULT
_RoGetActivationFactory.argtypes = [HSTRING, POINTER(GUID), POINTER(c_void_p)]

_WindowsCreateString = _combase.WindowsCreateString
_WindowsCreateString.restype = HRESULT
_WindowsCreateString.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, POINTER(HSTRING)]

_WindowsDeleteString = _combase.WindowsDeleteString
_WindowsDeleteString.restype, _WindowsDeleteString.argtypes = HRESULT, [HSTRING]

_WindowsGetStringRawBuffer = _combase.WindowsGetStringRawBuffer
_WindowsGetStringRawBuffer.restype = ctypes.c_void_p
_WindowsGetStringRawBuffer.argtypes = [HSTRING, POINTER(ctypes.c_uint32)]


def init(multithreaded=True):
    """RoInitialize; call it before anything else."""
    _check(_RoInitialize(1 if multithreaded else 0))


def uninit():
    """RoUninitialize. Every WinRT object has to be gone before this."""
    _factories.clear()
    _RoUninitialize()


def _create_hstring(value):
    if value is None:
        return HSTRING()
    handle = HSTRING()
    _check(_WindowsCreateString(value, len(value), byref(handle)))
    return handle


def _read_hstring(handle):
    if not handle:
        return ""
    length = ctypes.c_uint32()
    buffer = _WindowsGetStringRawBuffer(handle, byref(length))
    return ctypes.wstring_at(buffer, length.value) if buffer else ""


# --- IUnknown plumbing ------------------------------------------------------
_QueryInterface = WINFUNCTYPE(HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))
_Release = WINFUNCTYPE(ctypes.c_uint32, c_void_p)


def _vtable_entry(ptr, slot):
    return cast(ptr, POINTER(POINTER(c_void_p)))[0][slot]


class _Object:
    """A WinRT object: an interface pointer plus its vtable dispatch."""

    _iid_ = None
    _typedef_ = None

    def __init__(self, pointer=None):
        self._ptr = c_void_p(pointer.value if isinstance(pointer, c_void_p) else pointer)

    @classmethod
    def _wrap(cls, pointer):
        """Takes ownership of an interface pointer that is already AddRef'd."""
        instance = cls.__new__(cls)
        instance._ptr = c_void_p(pointer.value if isinstance(pointer, c_void_p) else pointer)
        return instance

    def _as(self, interface):
        """QueryInterface; returns None when the object does not support it."""
        if interface._iid_ is None:
            raise TypeError(f"{interface.__name__} has no IID in the metadata")
        result = c_void_p()
        hr = _QueryInterface(_vtable_entry(self._ptr, 0))(
            self._ptr, byref(interface._iid_), byref(result)
        )
        return interface._wrap(result) if hr >= 0 else None

    def __bool__(self):
        return bool(self._ptr)

    def __repr__(self):
        return f"<{type(self).__name__} at {self._ptr.value and hex(self._ptr.value)}>"

    def __del__(self):
        pointer = getattr(self, "_ptr", None)
        if pointer:
            _Release(_vtable_entry(pointer, 2))(pointer)
            self._ptr = c_void_p()


class IActivationFactory(_Object):
    """Not in the metadata: the ABI interface every activation factory has."""

    _iid_ = GUID("{00000035-0000-0000-C000-000000000046}")

    def ActivateInstance(self):
        result = c_void_p()
        prototype = WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))
        _check(prototype(_vtable_entry(self._ptr, IINSPECTABLE_SLOTS))(self._ptr, byref(result)))
        return result


# --- metadata ---------------------------------------------------------------
_files = None
_cache = None
_types = {}
_enum_ctype = {}
_factories = {}
_namespaces = None


def configure(*files):
    """Uses these .winmd files instead of the metadata of the running system."""
    global _files, _cache, _namespaces
    _files, _cache, _namespaces = list(files), None, None
    _types.clear()
    _enum_ctype.clear()
    _factories.clear()


def _metadata_files():
    """The metadata of the running system, or *.winmd next to this module."""
    if _files:
        return _files
    system = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "WinMetadata")
    files = sorted(glob.glob(os.path.join(system, "*.winmd")))
    if not files:
        here = os.path.dirname(os.path.abspath(__file__))
        files = sorted(glob.glob(os.path.join(here, "*.winmd")))
    if not files:
        raise RuntimeError(f"no .winmd files in {system}; call configure() to use other files")
    return files


def metadata():
    global _cache
    if _cache is None:
        _cache = cache(_metadata_files())
    return _cache


def _namespace_names():
    global _namespaces
    if _namespaces is None:
        _namespaces = set(metadata().namespaces().keys())
    return _namespaces


# --- names ------------------------------------------------------------------
def _identifier(name):
    name = re.sub(r"\W", "_", name)
    if keyword.iskeyword(name) or not name or name[0].isdigit():
        name = "_" + name
    return name


def _attribute_args(attribute):
    try:
        signature = attribute.Value()
    except ValueError:
        return [], {}

    def unwrap(value):
        while hasattr(value, "value"):
            value = value.value
        return value

    return (
        [unwrap(argument) for argument in signature.FixedArgs()],
        {argument.name: unwrap(argument.value) for argument in signature.NamedArgs()},
    )


def _iid_of(typedef):
    attribute = get_attribute(typedef, METADATA_ATTRIBUTES, "GuidAttribute")
    if not attribute:
        return None
    args, _ = _attribute_args(attribute)
    if len(args) != 11:
        return None
    return GUID(
        "{{{:08x}-{:04x}-{:04x}-{}-{}}}".format(
            args[0],
            args[1],
            args[2],
            "".join(f"{b:02x}" for b in args[3:5]),
            "".join(f"{b:02x}" for b in args[5:]),
        )
    )


# --- the ABI of a signature -------------------------------------------------
def _abi_type(sig):
    """The ctypes type a metadata type is passed as."""
    element = sig.Type()
    result = _abi_element(element)
    for _ in range(sig.ptr_count()):
        result = c_void_p
    if sig.is_szarray() or sig.is_array():
        raise NotImplementedError("array parameters are not supported")
    return result


def _abi_element(element):
    if isinstance(element, ElementType):
        if element == ElementType.String:
            return HSTRING
        return PRIMITIVES.get(element, c_void_p)
    if isinstance(element, coded_index_TypeDefOrRef):
        if element.type() == TypeDefOrRef.TypeSpec:
            return c_void_p  # a parameterized interface: an opaque pointer
        typedef = find(element)
        if not typedef:
            return c_void_p
        resolved = _resolve(typedef)
        if isinstance(resolved, type) and issubclass(resolved, _Object):
            return c_void_p
        return _enum_ctype.get(resolved, resolved)
    return c_void_p


def _converters(sig):
    """(python -> abi, abi -> python) for one metadata type."""
    element = sig.Type()

    if isinstance(element, ElementType) and element == ElementType.String:
        return (lambda value: (_create_hstring(value), True), _read_hstring)

    if isinstance(element, coded_index_TypeDefOrRef):
        if element.type() == TypeDefOrRef.TypeSpec:
            return (_pass_object, lambda value: value)
        typedef = find(element)
        if typedef:
            resolved = _resolve(typedef)
            if isinstance(resolved, type) and issubclass(resolved, _Object):
                return (_pass_object, resolved._wrap)
            if isinstance(resolved, type) and issubclass(resolved, IntEnum):
                return (
                    lambda value: (int(value), False),
                    lambda out: resolved(_plain_value(out)),
                )

    return (lambda value: (value, False), _plain_value)


def _pass_object(value):
    if value is None:
        return (c_void_p(), False)
    if isinstance(value, _Object):
        return (value._ptr, False)
    return (value, False)


def _plain_value(value):
    return value.value if hasattr(value, "value") else value


# --- methods ----------------------------------------------------------------
def _make_method(method, slot):
    signature = method.Signature()
    parameters = list(signature.Params())
    in_converters = [_converters(p.Type())[0] for p in parameters]
    argument_types = [_abi_type(p.Type()) for p in parameters]

    returns = signature.ReturnType()
    if returns:
        return_type = _abi_type(returns.Type())
        out_converter = _converters(returns.Type())[1]
        prototype = WINFUNCTYPE(HRESULT, c_void_p, *argument_types, POINTER(return_type))
    else:
        return_type = out_converter = None
        prototype = WINFUNCTYPE(HRESULT, c_void_p, *argument_types)

    name = method.Name()

    def call(self, *arguments):
        if len(arguments) != len(in_converters):
            raise TypeError(f"{name}() takes {len(in_converters)} arguments")
        if not self._ptr:
            raise ValueError(f"{type(self).__name__}.{name} on a null interface")

        strings, values = [], []
        for argument, convert in zip(arguments, in_converters):
            value, is_string = convert(argument)
            values.append(value)
            if is_string:
                strings.append(value)
        try:
            function = prototype(_vtable_entry(self._ptr, slot))
            if return_type is None:
                _check(function(self._ptr, *values))
                return None
            out = return_type()
            _check(function(self._ptr, *values, byref(out)))
            return out_converter(out)
        finally:
            for handle in strings:
                _WindowsDeleteString(handle)

    call.__name__ = name
    call.__qualname__ = name
    return call


def _method_name(method, taken):
    attribute = get_attribute(method, METADATA_ATTRIBUTES, "OverloadAttribute")
    if attribute:
        args, _ = _attribute_args(attribute)
        if args:
            return _identifier(args[0])
    name = _identifier(method.Name())
    if name in taken:
        name = f"{name}{len(list(method.Signature().Params()))}"
    return name


def _add_members(cls, typedef):
    """The methods and properties an interface declares, in vtable order."""
    methods = {}
    slot = IINSPECTABLE_SLOTS
    for method in typedef.MethodList():
        try:
            function = _make_method(method, slot)
        except NotImplementedError:
            function = None
        slot += 1
        if function is None:
            continue
        methods[method.Name()] = function
        setattr(cls, _method_name(method, vars(cls)), function)

    for property_row in typedef.PropertyList():
        getter = setter = None
        for semantic in property_row.MethodSemantic():
            name = semantic.Method().Name()
            if semantic.Semantic().Getter():
                getter = methods.get(name)
            elif semantic.Semantic().Setter():
                setter = methods.get(name)
        if getter or setter:
            setattr(cls, _identifier(property_row.Name()), property(getter, setter))


# --- types ------------------------------------------------------------------
def _resolve(typedef):
    known = _types.get(typedef)
    if known is not None:
        return known

    kind = get_category(typedef)
    name = _identifier(typedef.TypeName().split("`")[0])

    if kind == category.enum_type:
        return _build_enum(typedef, name)
    if kind == category.struct_type:
        return _build_struct(typedef, name)
    if kind == category.interface_type:
        return _build_interface(typedef, name)
    if kind == category.class_type:
        return _build_class(typedef, name)
    # A delegate: usable as an opaque pointer only.
    _types[typedef] = c_void_p
    return c_void_p


def _build_enum(typedef, name):
    flags = bool(get_attribute(typedef, METADATA_ATTRIBUTES, "FlagsAttribute"))
    members = {
        _identifier(field.Name()): field.Constant().Value()
        for field in typedef.FieldList()
        if field.Flags().Literal()
    }
    base = IntFlag if flags else IntEnum
    result = base(name, members) if members else base(name, {"_none": 0})
    _enum_ctype[result] = PRIMITIVES.get(
        typedef.get_enum_definition().m_underlying_type, ctypes.c_int32
    )
    _types[typedef] = result
    return result


def _build_struct(typedef, name):
    result = type(name, (Structure,), {})
    _types[typedef] = result
    result._fields_ = [
        (_identifier(field.Name()), _abi_type(field.Signature().Type()))
        for field in typedef.FieldList()
    ]
    return result


def _build_interface(typedef, name):
    result = type(name, (_Object,), {"_iid_": _iid_of(typedef), "_typedef_": typedef})
    _types[typedef] = result
    _add_members(result, typedef)
    return result


def _interfaces_of(typedef):
    """(default interface, the other ones) of a runtime class."""
    default, others = None, []
    for impl in typedef.InterfaceImpl():
        if impl.Interface().type() == TypeDefOrRef.TypeSpec:
            continue  # a parameterized interface, IVector<T> and friends
        interface = find(impl.Interface())
        if not interface:
            continue
        if get_attribute(impl, METADATA_ATTRIBUTES, "DefaultAttribute"):
            default = interface
        else:
            others.append(interface)
    return default, others


def _build_class(typedef, name):
    default, others = _interfaces_of(typedef)
    base = _resolve(default) if default else _Object
    class_name = f"{typedef.TypeNamespace()}.{typedef.TypeName()}"

    result = type(name, (base,), {"_class_name_": class_name, "_typedef_": typedef})
    _types[typedef] = result
    result._interfaces_ = [_resolve(interface) for interface in others]

    activations, statics = [], []
    for attribute in typedef.CustomAttribute():
        _, attribute_name = attribute.TypeNamespaceAndName()
        if attribute_name not in ("ActivatableAttribute", "StaticAttribute"):
            continue
        args, _ = _attribute_args(attribute)
        interface = None
        if args and isinstance(args[0], str) is False and hasattr(args[0], "name"):
            interface = args[0].name
        elif args and isinstance(args[0], str) and "." in args[0]:
            interface = args[0]
        if attribute_name == "ActivatableAttribute":
            activations.append(interface)  # None: IActivationFactory.ActivateInstance
        else:
            statics.append(interface)

    result._activations_ = activations
    result._statics_ = statics
    result.__init__ = _make_constructor(result)
    _add_statics(result)
    return result


def _find_type(full_name):
    typedef = metadata().find(full_name)
    return _resolve(typedef) if typedef else None


def _factory(class_name, interface):
    """The activation factory of a class, as `interface`."""
    key = (class_name, interface.__name__)
    factory = _factories.get(key)
    if factory is None:
        handle = _create_hstring(class_name)
        try:
            result = c_void_p()
            _check(_RoGetActivationFactory(handle, byref(interface._iid_), byref(result)))
        finally:
            _WindowsDeleteString(handle)
        factory = _factories[key] = interface._wrap(result)
    return factory


def _make_constructor(cls):
    def __init__(self, *arguments):
        for interface_name in cls._activations_:
            if interface_name is None:
                if arguments:
                    continue
                factory = _factory(cls._class_name_, IActivationFactory)
                self._ptr = factory.ActivateInstance()
                return
            interface = _find_type(interface_name)
            if interface is None:
                continue
            factory = _factory(cls._class_name_, interface)
            for method in interface._typedef_.MethodList():
                if len(list(method.Signature().Params())) != len(arguments):
                    continue
                created = getattr(factory, _identifier(method.Name()))(*arguments)
                self._ptr = created._ptr
                created._ptr = c_void_p()  # ownership moves to self
                return
        if not cls._activations_:
            raise TypeError(f"{cls._class_name_} is not activatable")
        raise TypeError(f"no activation of {cls._class_name_} takes {len(arguments)} arguments")

    return __init__


def _add_statics(cls):
    """Static members live on their own interface, reached through the factory."""
    for interface_name in cls._statics_:
        if interface_name is None:
            continue
        interface = _find_type(interface_name)
        if interface is None:
            continue
        for method in interface._typedef_.MethodList():
            name = _identifier(method.Name())
            if name in vars(cls):
                continue
            setattr(cls, name, _make_static(cls, interface, name))
        for property_row in interface._typedef_.PropertyList():
            name = _identifier(property_row.Name())
            if name not in vars(cls):
                setattr(cls, name, _make_static_property(cls, interface, property_row))


def _make_static(cls, interface, name):
    def call(*arguments):
        return getattr(_factory(cls._class_name_, interface), name)(*arguments)

    call.__name__ = name
    return staticmethod(call)


def _make_static_property(cls, interface, property_row):
    name = _identifier(property_row.Name())

    class _StaticProperty:
        def __get__(self, instance, owner=None):
            return getattr(_factory(cls._class_name_, interface), name)

        def __set__(self, instance, value):
            setattr(_factory(cls._class_name_, interface), name, value)

    return _StaticProperty()


# --- QueryInterface fallback ------------------------------------------------
def _object_getattr(self, name):
    for interface in getattr(type(self), "_interfaces_", ()):
        if hasattr(interface, name):
            other = self._as(interface)
            if other is not None:
                return getattr(other, name)
    raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")


_Object.__getattr__ = _object_getattr


# --- namespaces -------------------------------------------------------------
class Namespace:
    """A metadata namespace; attributes are its types and sub-namespaces."""

    def __init__(self, name):
        self._name = name

    def __repr__(self):
        return f"<winrt namespace {self._name}>"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        typedef = metadata().find(self._name, name)
        if typedef:
            value = _resolve(typedef)
        else:
            child = f"{self._name}.{name}"
            if child in _namespace_names() or any(
                other.startswith(child + ".") for other in _namespace_names()
            ):
                value = Namespace(child)
            else:
                raise AttributeError(f"{self._name} has no member {name!r}")
        setattr(self, name, value)
        return value

    def __dir__(self):
        members = metadata().namespaces().get(self._name)
        names = list(members.types.keys()) if members is not None else []
        prefix = self._name + "."
        for other in _namespace_names():
            if other.startswith(prefix):
                names.append(other[len(prefix) :].split(".")[0])
        return sorted(set(names))


def __getattr__(name):
    """The top level namespaces (Windows, ...)."""
    if name.startswith("_"):
        raise AttributeError(name)
    if name in _namespace_names() or any(
        other.startswith(name + ".") for other in _namespace_names()
    ):
        value = Namespace(name)
        globals()[name] = value
        return value
    raise AttributeError(f"no WinRT namespace named {name!r}")


_PUBLIC = ("init", "uninit", "configure", "metadata", "Namespace", "GUID", "HSTRING",
           "WinRTError", "IActivationFactory")


def __dir__():
    return sorted(set(_PUBLIC) | {name.split(".")[0] for name in _namespace_names()})


if __name__ == "__main__":
    init()
    print(f"{len(_metadata_files())} .winmd files, {len(_namespace_names())} namespaces")
    for name in sys.argv[1:]:
        value = sys.modules[__name__]
        for part in name.split("."):
            value = getattr(value, part)
        print(f"{name}: {value!r}")
