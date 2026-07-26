"""WinRT, resolved from the metadata when an attribute is looked up.

    import winrt

    winrt.init()

    uri = winrt.Windows.Foundation.Uri("https://example.com/a/b?x=1")
    print(uri.Domain, uri.Path, uri.Query)
    print(uri.ToString())                       # IStringable, reached by QueryInterface

    calendar = winrt.Windows.Globalization.Calendar()
    print(calendar.Year, calendar.Month, calendar.Day)

    print(winrt.Windows.Foundation.Uri.EscapeComponent("a b"))   # a static member

    for tag in winrt.Windows.Globalization.ApplicationLanguages.Languages:
        print(tag)                              # IVectorView<String> as a sequence

    watcher = winrt.Windows.Devices.Enumeration.DeviceInformation.CreateWatcher()
    watcher.add_Added(lambda sender, device: print(device.Name))   # a Python delegate
    watcher.Start()

This is the WinRT counterpart of win32.py: namespaces, runtime classes,
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
    * parameterized interfaces: the IID of IVector<Uri> and friends is computed
      from the type signature, and the collection interfaces get the Python
      protocols (len(), [], in, iteration)
    * delegates: a Python callable passed where a delegate is expected becomes a
      COM object with a vtable of its own, which is what events (add_X/remove_X)
      and completion handlers (put_Completed) need
    * IAsyncOperation<T>.get() waits for a result by polling IAsyncInfo, or
      put_Completed hands it to a callback
    * arrays in all three forms: a sequence goes in (PassArray), a list is
      filled in place (FillArray) and an allocated one comes back and is freed
      (ReceiveArray)

What it does not cover: multidimensional arrays, and the delegates it builds are
agile but not marshalable, which is enough for the thread pool apartments
callbacks arrive on.

The metadata is C:\\Windows\\System32\\WinMetadata\\*.winmd, the metadata of the
running system; call configure(*files) to read others.
"""

import ctypes
import glob
import keyword
import os
import re
import sys
import time
import traceback
import uuid
from ctypes import (  # noqa: F401  (re-exported for convenience)
    POINTER,
    Structure,
    WINFUNCTYPE,
    byref,
    c_void_p,
    cast,
)
from enum import IntEnum, IntFlag

from winmd.reader import (
    ElementType,
    GenericTypeIndex,
    GenericTypeInstSig,
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

# The namespace of RFC 4122 name based IIDs of parameterized interfaces.
PINTERFACE_NAMESPACE = uuid.UUID("11f47ad5-7b73-42c0-abae-878b1e16adee")

# ctypes type and type signature of the basic types.
BASIC_TYPES = {
    ElementType.Boolean: (ctypes.c_bool, "b1"),
    ElementType.Char: (ctypes.c_uint16, "c2"),
    ElementType.I1: (ctypes.c_int8, "i1"),
    ElementType.U1: (ctypes.c_uint8, "u1"),
    ElementType.I2: (ctypes.c_int16, "i2"),
    ElementType.U2: (ctypes.c_uint16, "u2"),
    ElementType.I4: (ctypes.c_int32, "i4"),
    ElementType.U4: (ctypes.c_uint32, "u4"),
    ElementType.I8: (ctypes.c_int64, "i8"),
    ElementType.U8: (ctypes.c_uint64, "u8"),
    ElementType.R4: (ctypes.c_float, "f4"),
    ElementType.R8: (ctypes.c_double, "f8"),
    ElementType.I: (ctypes.c_ssize_t, "i8"),
    ElementType.U: (ctypes.c_size_t, "u8"),
}

COLLECTIONS = "Windows.Foundation.Collections"


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
            text = str(value).strip("{}").replace("-", "")
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

    def __repr__(self):
        return str(self)

    def __eq__(self, other):
        # A ctypes structure does not compare by value on its own, and
        # QueryInterface has to match the IID it is asked for.
        return isinstance(other, GUID) and bytes(self) == bytes(other)

    def __hash__(self):
        return hash(bytes(self))


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

_CoTaskMemFree = _combase.CoTaskMemFree
_CoTaskMemFree.restype, _CoTaskMemFree.argtypes = None, [c_void_p]


_initialized = False


def init(multithreaded=True):
    """RoInitialize; call it before anything else."""
    global _initialized
    _check(_RoInitialize(1 if multithreaded else 0))
    _initialized = True


def uninit():
    """RoUninitialize.

    Objects that outlive this are not released: their apartment is gone, so
    calling Release on them would take the process down.
    """
    global _initialized
    _initialized = False
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


def _vtable_entry(pointer, slot):
    return cast(pointer, POINTER(POINTER(c_void_p)))[0][slot]


class _Object:
    """A WinRT object: an interface pointer plus its vtable dispatch."""

    _iid_ = None
    _typedef_ = None
    _interfaces_ = ()

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
            raise TypeError(f"{interface.__name__} has no IID")
        result = c_void_p()
        hr = _QueryInterface(_vtable_entry(self._ptr, 0))(
            self._ptr, byref(interface._iid_), byref(result)
        )
        return interface._wrap(result) if hr >= 0 else None

    def __getattr__(self, name):
        for interface in type(self)._interfaces_:
            if hasattr(interface, name):
                other = self._as(interface)
                if other is not None:
                    return getattr(other, name)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    def __bool__(self):
        return bool(self._ptr)

    def __repr__(self):
        return f"<{type(self).__name__} at {self._ptr.value and hex(self._ptr.value)}>"

    def __del__(self):
        pointer = getattr(self, "_ptr", None)
        if pointer:
            if _initialized:
                _Release(_vtable_entry(pointer, 2))(pointer)
            self._ptr = c_void_p()


class IInspectable(_Object):
    """Every WinRT object is one; it can be asked what it really is."""

    _iid_ = GUID("{af86e2e0-b12d-4c6a-9c5a-d7aa65101e90}")

    def GetRuntimeClassName(self):
        out = HSTRING()
        prototype = WINFUNCTYPE(HRESULT, c_void_p, POINTER(HSTRING))
        _check(prototype(_vtable_entry(self._ptr, 4))(self._ptr, byref(out)))
        try:
            return _read_hstring(out)
        finally:
            _WindowsDeleteString(out)

    def _resolve_class(self):
        """The object as its runtime class, or None when that is not a class."""
        resolved = self.__dict__.get("_resolved")
        if resolved is None:
            name = self.GetRuntimeClassName()
            python = _find_type(name) if name and "`" not in name else None
            if isinstance(python, type) and issubclass(python, _Object) and python._iid_:
                resolved = self._as(python)
            self.__dict__["_resolved"] = resolved
        return resolved

    def __getattr__(self, name):
        if not name.startswith("_"):
            resolved = self._resolve_class()
            if resolved is not None:
                return getattr(resolved, name)
        return super().__getattr__(name)


class IActivationFactory(_Object):
    """Not in the metadata: the ABI interface every activation factory has."""

    _iid_ = GUID("{00000035-0000-0000-C000-000000000046}")

    def ActivateInstance(self):
        result = c_void_p()
        prototype = WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))
        _check(prototype(_vtable_entry(self._ptr, IINSPECTABLE_SLOTS))(self._ptr, byref(result)))
        return result


# --- delegates implemented in Python ----------------------------------------
_ADD_REF = WINFUNCTYPE(ctypes.c_uint32, c_void_p)
_QUERY_INTERFACE_IMPL = WINFUNCTYPE(HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))
_REFCOUNT_IMPL = WINFUNCTYPE(ctypes.c_uint32, c_void_p)

IID_IUNKNOWN = GUID("{00000000-0000-0000-C000-000000000046}")
IID_IAGILE_OBJECT = GUID("{94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90}")

E_NOINTERFACE = -2147467262   # 0x80004002
E_FAIL = -2147467259          # 0x80004005


def _add_ref(pointer):
    if pointer:
        _ADD_REF(_vtable_entry(pointer, 1))(pointer)


class _Delegate:
    """A COM object with the four slots of a WinRT delegate, backed by Python.

    The vtable is [QueryInterface, AddRef, Release, Invoke]; a delegate is the
    one WinRT interface kind that is not IInspectable derived. `_live` keeps the
    object from being collected while native code holds a reference to it.
    """

    _live = {}

    def __init__(self, iid, invoke_prototype, invoke):
        self._iid = iid
        self._count = 1
        self._callbacks = (
            _QUERY_INTERFACE_IMPL(self._query_interface),
            _REFCOUNT_IMPL(self._increment),
            _REFCOUNT_IMPL(self._decrement),
            invoke_prototype(invoke),
        )
        self._vtable = (c_void_p * 4)(
            *(cast(callback, c_void_p) for callback in self._callbacks)
        )
        self._this = (c_void_p * 1)(cast(self._vtable, c_void_p))
        self.pointer = c_void_p(ctypes.addressof(self._this))
        _Delegate._live[self.pointer.value] = self

    def _query_interface(self, this, iid, result):
        wanted = iid[0]
        if wanted in (IID_IUNKNOWN, IID_IAGILE_OBJECT, self._iid):
            result[0] = self.pointer.value
            self._increment(this)
            return 0
        result[0] = None
        return E_NOINTERFACE

    def _increment(self, this):
        self._count += 1
        return self._count

    def _decrement(self, this):
        self._count -= 1
        count = self._count
        if count <= 0:
            _Delegate._live.pop(self.pointer.value, None)
        return max(count, 0)

    def release(self):
        """Drops the reference that creating the delegate took."""
        self._decrement(None)


def _delegate_invoke(typedef, arguments):
    """The prototype and the parameter types of a delegate's Invoke."""
    invoke = next((m for m in typedef.MethodList() if m.Name() == "Invoke"), None)
    if invoke is None:
        raise NotImplementedError("a delegate without Invoke")
    signature = invoke.Signature()
    parameters = [_type_of_sig(p.Type(), arguments) for p in signature.Params()]
    returns = signature.ReturnType()
    return_type = _type_of_sig(returns.Type(), arguments) if returns else None
    abi = [parameter.abi for parameter in parameters]
    if return_type is not None:
        abi.append(POINTER(return_type.abi))
    return WINFUNCTYPE(HRESULT, c_void_p, *abi), parameters, return_type


def _incoming(parameter, value):
    """Converts an argument the delegate is called with; pointers are borrowed."""
    if isinstance(parameter.python, type) and issubclass(parameter.python, _Object):
        _add_ref(c_void_p(value) if not isinstance(value, c_void_p) else value)
    return parameter.from_abi(value)


def _delegate_type(typedef, signature, iid, arguments=()):
    """A _Type that turns a Python callable into a WinRT delegate."""
    def to_abi(value):
        if value is None:
            return (c_void_p(), None)
        if isinstance(value, _Object):
            return (value._ptr, None)
        if isinstance(value, _Delegate):
            return (value.pointer, None)
        if not callable(value):
            raise TypeError(f"{value!r} is not callable")

        prototype, parameters, return_type = _delegate_invoke(typedef, arguments)

        def invoke(this, *abi_values):
            try:
                values = [
                    _incoming(parameter, abi_value)
                    for parameter, abi_value in zip(parameters, abi_values)
                ]
                result = value(*values)
                if return_type is not None and abi_values[-1]:
                    abi_values[-1][0] = return_type.to_abi(result)[0]
                return 0
            except Exception:  # a Python error must not escape into native code
                traceback.print_exc()
                return E_FAIL

        delegate = _Delegate(iid, prototype, invoke)
        # Native code takes its own reference; ours goes away after the call.
        return (delegate.pointer, delegate.release)

    return _Type(signature, c_void_p, to_abi, python=None)


# --- metadata ---------------------------------------------------------------
_files = None
_cache = None
_namespaces = None
_types = {}         # TypeDef -> Python type (non generic)
_generics = {}      # (TypeDef, signature of the arguments) -> closed Python type
_type_cache = {}    # TypeDef -> _Type
_enum_ctype = {}
_factories = {}


def configure(*files):
    """Uses these .winmd files instead of the metadata of the running system."""
    global _files, _cache, _namespaces
    _files, _cache, _namespaces = list(files), None, None
    for mapping in (_types, _generics, _type_cache, _enum_ctype, _factories):
        mapping.clear()


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


# --- names and attributes ---------------------------------------------------
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


def _full_name(typedef):
    return f"{typedef.TypeNamespace()}.{typedef.TypeName()}"


# --- types ------------------------------------------------------------------
class _Type:
    """How one metadata type crosses the ABI, and how it is signed."""

    __slots__ = ("signature", "abi", "to_abi", "from_abi", "python")

    def __init__(self, signature, abi, to_abi=None, from_abi=None, python=None):
        self.signature = signature
        self.abi = abi
        self.to_abi = to_abi or _pass_value
        self.from_abi = from_abi or _plain_value
        self.python = python

    def __repr__(self):
        return f"<_Type {self.signature}>"


def _pass_value(value):
    return (value, None)


def _plain_value(value):
    return value.value if hasattr(value, "value") else value


def _pass_object(value):
    if value is None:
        return (c_void_p(), None)
    if isinstance(value, _Object):
        return (value._ptr, None)
    return (value, None)


_VOID = _Type("", None)
def _string_to_abi(value):
    handle = _create_hstring(value)
    return (handle, lambda: _WindowsDeleteString(handle))


_STRING = _Type("string", HSTRING, _string_to_abi, _read_hstring, str)
_GUID_TYPE = _Type("g16", GUID, python=GUID)
_INSPECTABLE = _Type(
    "cinterface(IInspectable)",
    c_void_p,
    _pass_object,
    lambda value: IInspectable._wrap(value),
    IInspectable,
)


def _type_of(element, arguments=()):
    """The _Type of a metadata type; `arguments` closes the generic parameters."""
    if isinstance(element, ElementType):
        if element == ElementType.String:
            return _STRING
        if element == ElementType.Object:
            return _INSPECTABLE
        if element == ElementType.Void:
            return _VOID
        abi, signature = BASIC_TYPES.get(element, (c_void_p, "cinterface(IInspectable)"))
        return _Type(signature, abi)

    if isinstance(element, GenericTypeIndex):
        if element.index >= len(arguments):
            raise NotImplementedError("an open generic parameter")
        return arguments[element.index]

    if isinstance(element, GenericTypeInstSig):
        return _type_of_generic(element, arguments)

    if isinstance(element, coded_index_TypeDefOrRef):
        if element.type() == TypeDefOrRef.TypeSpec:
            return _type_of_generic(element.TypeSpec().Signature().GenericTypeInst(), arguments)
        namespace, name = _reference_name(element)
        if (namespace, name) == ("System", "Guid"):
            return _GUID_TYPE
        typedef = find(element)
        if not typedef:
            raise NotImplementedError(f"{namespace}.{name} is not in the metadata")
        return _type_of_typedef(typedef)

    raise NotImplementedError(f"the type {element!r}")


def _type_of_sig(sig, arguments=()):
    """The _Type of a TypeSig (a parameter, a return value or a field)."""
    if sig.is_szarray() or sig.is_array():
        raise NotImplementedError("array types")
    return _type_of(sig.Type(), arguments)


def _reference_name(index):
    if index.type() == TypeDefOrRef.TypeDef:
        row = index.TypeDef()
    else:
        row = index.TypeRef()
    return row.TypeNamespace(), row.TypeName()


def _type_of_typedef(typedef):
    known = _type_cache.get(typedef)
    if known is not None:
        return known

    kind = get_category(typedef)
    name = _full_name(typedef)

    if kind == category.enum_type:
        python = _resolve(typedef)
        abi = _enum_ctype[python]
        underlying = "u4" if abi is ctypes.c_uint32 else "i4"
        result = _Type(
            f"enum({name};{underlying})",
            abi,
            lambda value: (int(value), None),
            lambda out: python(_plain_value(out)),
            python,
        )
    elif kind == category.struct_type:
        python = _resolve(typedef)
        fields = ";".join(
            _type_of_sig(field.Signature().Type()).signature for field in typedef.FieldList()
        )
        result = _Type(f"struct({name};{fields})", python, python=python)
    elif kind == category.interface_type:
        python = _resolve(typedef)
        result = _Type(f"{python._iid_}", c_void_p, _pass_object, python._wrap, python)
    elif kind == category.class_type:
        python = _resolve(typedef)
        default = getattr(python, "_default_signature_", None)
        result = _Type(f"rc({name};{default})", c_void_p, _pass_object, python._wrap, python)
    else:  # a delegate
        iid = _iid_of(typedef)
        result = _delegate_type(typedef, f"delegate({iid})", iid)

    _type_cache[typedef] = result
    return result


def _type_of_generic(instance, arguments=()):
    """A closed parameterized interface, IVector<Uri> and the like."""
    typedef = find(instance.GenericType())
    if not typedef:
        raise NotImplementedError("a parameterized type that is not in the metadata")
    closed = tuple(_type_of(argument.Type(), arguments) for argument in instance.GenericArgs())
    python = _closed_generic(typedef, closed)
    if isinstance(python, _Type):
        return python  # a parameterized delegate
    return _Type(python._signature_, c_void_p, _pass_object, python._wrap, python)


def _closed_generic(typedef, arguments):
    """Builds IVector<Uri> and friends: the IID comes from the signature."""
    key = (typedef, tuple(argument.signature for argument in arguments))
    known = _generics.get(key)
    if known is not None:
        return known

    signature = "pinterface({};{})".format(
        _iid_of(typedef), ";".join(argument.signature for argument in arguments)
    )
    iid = GUID(uuid.uuid5(PINTERFACE_NAMESPACE, signature))

    if get_category(typedef) == category.delegate_type:
        # TypedEventHandler<TSender, TResult> and friends: the same IID rule, but
        # what comes out is a factory for Python implemented delegates.
        result = _delegate_type(typedef, signature, iid, arguments)
        _generics[key] = result
        return result
    name = "{}_{}".format(
        _identifier(typedef.TypeName().split("`")[0]),
        "_".join(_argument_name(argument) for argument in arguments),
    )
    result = type(
        name,
        (_Object,),
        {
            "_iid_": iid,
            "_typedef_": typedef,
            "_signature_": signature,
            "_arguments_": arguments,
        },
    )
    _generics[key] = result
    _add_members(result, typedef, arguments)
    _add_protocol(result, typedef)
    # IMap<K, V> requires IIterable<IKeyValuePair<K, V>>: that is where First() is.
    _, required = _interfaces_of(typedef, arguments)
    result._interfaces_ = tuple(required)
    _forward_protocol(result, required)
    return result


def _argument_name(argument):
    if argument.python is not None:
        return getattr(argument.python, "__name__", str(argument.python))
    return re.sub(r"\W", "", argument.signature)[:8]


# --- methods ----------------------------------------------------------------
def _element_value(abi_type, value):
    """What an element of a ctypes array has to be assigned."""
    return value.value if isinstance(value, ctypes._SimpleCData) else value


def _fill_buffer(element, values):
    """A ctypes array holding `values`, plus what has to be freed afterwards."""
    buffer = (element.abi * len(values))()
    cleanups = []
    for index, value in enumerate(values):
        converted, cleanup = element.to_abi(value)
        buffer[index] = _element_value(element.abi, converted)
        if cleanup is not None:
            cleanups.append(cleanup)
    return buffer, cleanups


def _read_buffer(element, data, count, owned):
    """The Python list of `count` elements; `owned` also frees them."""
    items = [element.from_abi(data[index]) for index in range(count)]
    if owned and element is _STRING:
        for index in range(count):
            _WindowsDeleteString(data[index])
    return items


def _array_kind(parameter, row):
    """PassArray, FillArray or ReceiveArray, as the ABI spells them."""
    if row is not None and row.Flags().In():
        return "pass"
    return "receive" if parameter.ByRef() else "fill"


def _make_method(method, slot, arguments=()):
    """A callable for one vtable slot.

    The WinRT ABI is `HRESULT method(this, in..., out..., out retval)`, and an
    array takes two of those parameters: a length and the data. The HRESULT is
    checked; the return value and the out parameters come back as the result, as
    a tuple when there is more than one. A FillArray is different: it is given a
    list whose length is the capacity, and that list is what the call writes to.
    """
    signature = method.Signature()
    rows = {row.Sequence(): row for row in method.ParamList()}

    plan, argument_types = [], []
    for index, parameter in enumerate(signature.Params(), start=1):
        row = rows.get(index)
        parameter_sig = parameter.Type()
        if parameter_sig.is_array():
            raise NotImplementedError("multidimensional arrays")
        if parameter_sig.is_szarray():
            element = _type_of(parameter_sig.Type(), arguments)
            kind = _array_kind(parameter, row)
            plan.append((kind, element, len(argument_types)))
            if kind == "receive":
                argument_types.extend(
                    [POINTER(ctypes.c_uint32), POINTER(POINTER(element.abi))]
                )
            else:  # pass and fill share the (length, data) shape
                argument_types.extend([ctypes.c_uint32, POINTER(element.abi)])
            continue
        parameter_type = _type_of(parameter_sig.Type(), arguments)
        is_out = parameter.ByRef() or (row is not None and row.Flags().Out() and not
                                       row.Flags().In())
        plan.append(("out" if is_out else "in", parameter_type, len(argument_types)))
        argument_types.append(POINTER(parameter_type.abi) if is_out else parameter_type.abi)

    returns = signature.ReturnType()
    return_type = return_element = None
    if returns:
        if returns.Type().is_szarray():
            return_element = _type_of(returns.Type().Type(), arguments)
            argument_types.extend(
                [POINTER(ctypes.c_uint32), POINTER(POINTER(return_element.abi))]
            )
        else:
            return_type = _type_of_sig(returns.Type(), arguments)
            argument_types.append(POINTER(return_type.abi))

    prototype = WINFUNCTYPE(HRESULT, c_void_p, *argument_types)
    wanted = sum(1 for kind, _, _ in plan if kind in ("in", "pass", "fill"))
    name = method.Name()

    def call(self, *values):
        if len(values) != wanted:
            raise TypeError(f"{name}() takes {wanted} arguments")
        if not self._ptr:
            raise ValueError(f"{type(self).__name__}.{name} on a null interface")

        abi_values = [None] * len(argument_types)
        cleanups, results_of, fills = [], [], []
        given = iter(values)

        for kind, element, position in plan:
            if kind == "in":
                converted, cleanup = element.to_abi(next(given))
                abi_values[position] = converted
                if cleanup is not None:
                    cleanups.append(cleanup)
            elif kind == "out":
                out = element.abi()
                abi_values[position] = byref(out)
                results_of.append(lambda out=out, element=element: element.from_abi(out))
            elif kind == "pass":
                items = list(next(given))
                buffer, buffer_cleanups = _fill_buffer(element, items)
                abi_values[position] = len(items)
                abi_values[position + 1] = buffer
                cleanups.extend(buffer_cleanups)
            elif kind == "fill":
                target = next(given)
                try:
                    capacity = len(target)
                except TypeError:
                    raise TypeError(
                        f"{name}() writes into the list it is given, so it takes"
                        f" one, not {type(target).__name__}"
                    ) from None
                buffer = (element.abi * capacity)()
                abi_values[position] = capacity
                abi_values[position + 1] = buffer
                fills.append((target, buffer, element, capacity))
            else:  # receive: the callee allocates
                length = ctypes.c_uint32()
                data = POINTER(element.abi)()
                abi_values[position] = byref(length)
                abi_values[position + 1] = byref(data)
                results_of.append(
                    lambda length=length, data=data, element=element:
                    _receive_array(element, data, length.value)
                )

        if return_element is not None:
            length = ctypes.c_uint32()
            data = POINTER(return_element.abi)()
            abi_values[-2], abi_values[-1] = byref(length), byref(data)
            results_of.insert(
                0,
                lambda: _receive_array(return_element, data, length.value),
            )
        elif return_type is not None:
            out = return_type.abi()
            abi_values[-1] = byref(out)
            results_of.insert(0, lambda: return_type.from_abi(out))

        try:
            _check(prototype(_vtable_entry(self._ptr, slot))(self._ptr, *abi_values))
            for target, buffer, element, capacity in fills:
                target[:] = _read_buffer(element, buffer, capacity, True)
            results = [produce() for produce in results_of]
            if not results:
                return None
            return results[0] if len(results) == 1 else tuple(results)
        finally:
            for cleanup in cleanups:
                cleanup()

    call.__name__ = name
    call.__qualname__ = name
    return call


def _receive_array(element, data, count):
    """Reads an array the callee allocated, and frees it."""
    if not data:
        return []
    items = _read_buffer(element, data, count, True)
    _CoTaskMemFree(cast(data, c_void_p))
    return items


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


def _add_members(cls, typedef, arguments=()):
    """The methods and properties an interface declares, in vtable order."""
    methods = {}
    slot = IINSPECTABLE_SLOTS
    for method in typedef.MethodList():
        try:
            function = _make_method(method, slot, arguments)
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
            member = semantic.Method().Name()
            if semantic.Semantic().Getter():
                getter = methods.get(member)
            elif semantic.Semantic().Setter():
                setter = methods.get(member)
        if getter or setter:
            setattr(cls, _identifier(property_row.Name()), property(getter, setter))


# --- the Python protocols of the collection interfaces -----------------------
def _add_protocol(cls, typedef):
    protocol = _PROTOCOLS.get(_full_name(typedef))
    if protocol is not None:
        protocol(cls)


def _protocol_iterable(cls):
    def __iter__(self):
        iterator = self.First()
        while iterator.HasCurrent:
            yield iterator.Current
            iterator.MoveNext()

    cls.__iter__ = __iter__


def _protocol_iterator(cls):
    def __iter__(self):
        while self.HasCurrent:
            yield self.Current
            self.MoveNext()

    cls.__iter__ = __iter__


def _protocol_vector_view(cls):
    def __len__(self):
        return self.Size

    def __getitem__(self, index):
        size = self.Size
        if index < 0:
            index += size
        if not 0 <= index < size:
            raise IndexError(f"index out of range: {index}")
        return self.GetAt(index)

    def __iter__(self):
        for index in range(self.Size):
            yield self.GetAt(index)

    def __contains__(self, value):
        found, _ = self.IndexOf(value)
        return found

    cls.__len__, cls.__getitem__, cls.__iter__, cls.__contains__ = (
        __len__,
        __getitem__,
        __iter__,
        __contains__,
    )


def _protocol_vector(cls):
    _protocol_vector_view(cls)

    def __setitem__(self, index, value):
        if index < 0:
            index += self.Size
        self.SetAt(index, value)

    def append(self, value):
        self.Append(value)

    def __delitem__(self, index):
        if index < 0:
            index += self.Size
        self.RemoveAt(index)

    cls.__setitem__, cls.append, cls.__delitem__ = __setitem__, append, __delitem__


def _protocol_map_view(cls):
    def __len__(self):
        return self.Size

    def __getitem__(self, key):
        if not self.HasKey(key):
            raise KeyError(key)
        return self.Lookup(key)

    def __contains__(self, key):
        return self.HasKey(key)

    def __iter__(self):
        for pair in self.First():
            yield pair.Key

    def items(self):
        return [(pair.Key, pair.Value) for pair in self.First()]

    def keys(self):
        return [key for key in self]

    def values(self):
        return [value for _, value in self.items()]

    cls.__len__, cls.__getitem__, cls.__contains__, cls.__iter__ = (
        __len__,
        __getitem__,
        __contains__,
        __iter__,
    )
    cls.items, cls.keys, cls.values = items, keys, values


def _protocol_map(cls):
    _protocol_map_view(cls)

    def __setitem__(self, key, value):
        self.Insert(key, value)

    def __delitem__(self, key):
        if not self.HasKey(key):
            raise KeyError(key)
        self.Remove(key)

    cls.__setitem__, cls.__delitem__ = __setitem__, __delitem__


def _protocol_key_value_pair(cls):
    def __iter__(self):
        # so that `for key, value in mapping.items()` works
        return iter((self.Key, self.Value))

    def __repr__(self):
        return f"({self.Key!r}, {self.Value!r})"

    cls.__iter__, cls.__repr__ = __iter__, __repr__


def _async_get(self, timeout=30.0, interval=0.005):
    """Waits for an asynchronous operation and returns its result."""
    info = self._as(_find_type("Windows.Foundation.IAsyncInfo"))
    if info is None:
        raise TypeError("not an asynchronous operation")
    deadline = time.monotonic() + timeout
    while int(info.Status) == 0:  # AsyncStatus.Started
        if time.monotonic() > deadline:
            raise TimeoutError(f"the operation did not finish within {timeout}s")
        time.sleep(interval)
    status = int(info.Status)
    if status == 2:  # Canceled
        raise RuntimeError("the operation was canceled")
    if status == 3:  # Error
        raise WinRTError(info.ErrorCode)
    return self.GetResults() if hasattr(self, "GetResults") else None


def _protocol_async(cls):
    cls.get = _async_get


_PROTOCOLS = {
    f"{COLLECTIONS}.IIterable`1": _protocol_iterable,
    f"{COLLECTIONS}.IIterator`1": _protocol_iterator,
    f"{COLLECTIONS}.IVector`1": _protocol_vector,
    f"{COLLECTIONS}.IVectorView`1": _protocol_vector_view,
    f"{COLLECTIONS}.IMap`2": _protocol_map,
    f"{COLLECTIONS}.IMapView`2": _protocol_map_view,
    f"{COLLECTIONS}.IKeyValuePair`2": _protocol_key_value_pair,
    "Windows.Foundation.IAsyncOperation`1": _protocol_async,
    "Windows.Foundation.IAsyncOperationWithProgress`2": _protocol_async,
}

_PROTOCOL_MEMBERS = (
    "__len__",
    "__iter__",
    "__getitem__",
    "__setitem__",
    "__delitem__",
    "__contains__",
    "items",
    "keys",
    "values",
    "append",
    "get",
)


# --- interfaces, classes, enums, structs ------------------------------------
def _resolve(typedef):
    known = _types.get(typedef)
    if known is not None:
        return known

    if len(typedef.GenericParam()) and get_category(typedef) == category.interface_type:
        result = Parameterized(typedef)
        _types[typedef] = result
        return result

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
    _types[typedef] = c_void_p  # a delegate: an opaque pointer
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
    _enum_ctype[result] = BASIC_TYPES.get(
        typedef.get_enum_definition().m_underlying_type, (ctypes.c_int32, "i4")
    )[0]
    _types[typedef] = result
    return result


def _build_struct(typedef, name):
    result = type(name, (Structure,), {})
    _types[typedef] = result
    result._fields_ = [
        (_identifier(field.Name()), _type_of_sig(field.Signature().Type()).abi)
        for field in typedef.FieldList()
    ]
    return result


def _build_interface(typedef, name):
    result = type(name, (_Object,), {"_iid_": _iid_of(typedef), "_typedef_": typedef})
    _types[typedef] = result
    _add_members(result, typedef)
    _add_protocol(result, typedef)
    # The InterfaceImpl rows of an interface are the interfaces it requires.
    _, required = _interfaces_of(typedef)
    result._interfaces_ = tuple(required)
    _forward_protocol(result, required)
    return result


def _forward_protocol(cls, interfaces):
    """Lets len(), [] and iteration reach an interface behind QueryInterface."""
    for interface in interfaces:
        for member in _PROTOCOL_MEMBERS:
            if member not in vars(cls) and hasattr(interface, member):
                setattr(cls, member, _forward(interface, member))


def _interfaces_of(typedef, arguments=()):
    """(default interface, the other ones) of a class, or what an interface requires.

    `arguments` closes the generic parameters: IMap<K, V> requires
    IIterable<IKeyValuePair<K, V>>, which only makes sense once K and V are known.
    """
    default, others = None, []
    for impl in typedef.InterfaceImpl():
        index = impl.Interface()
        try:
            if index.type() == TypeDefOrRef.TypeSpec:
                interface = _type_of_generic(
                    index.TypeSpec().Signature().GenericTypeInst(), arguments
                ).python
            else:
                found = find(index)
                interface = _resolve(found) if found else None
        except NotImplementedError:
            interface = None
        if interface is None or not isinstance(interface, type):
            continue
        if get_attribute(impl, METADATA_ATTRIBUTES, "DefaultAttribute"):
            default = interface
        else:
            others.append(interface)
    return default, others


def _build_class(typedef, name):
    default, others = _interfaces_of(typedef)
    base = default if default is not None else _Object
    class_name = _full_name(typedef)

    result = type(name, (base,), {"_class_name_": class_name, "_typedef_": typedef})
    _types[typedef] = result

    # Transitively: an interface can require others, and those carry members too.
    interfaces = []
    for interface in ([default] if default else []) + others:
        for candidate in (interface,) + tuple(getattr(interface, "_interfaces_", ())):
            if candidate is not None and candidate is not base and candidate not in interfaces:
                interfaces.append(candidate)
    result._interfaces_ = tuple(interfaces)
    # rc(<name>;<signature of the default interface>): that signature is the IID
    # of a plain interface, but the pinterface form of a parameterized one -
    # DeviceInformationCollection has IVectorView<DeviceInformation> as default.
    result._default_signature_ = (
        getattr(default, "_signature_", None)
        or (str(default._iid_) if default is not None and default._iid_ else "unknown")
    )

    # A collection interface only gives Python its protocol when the methods are
    # on the class itself; the ones behind QueryInterface need forwarding.
    _forward_protocol(result, interfaces)

    activations, statics = [], []
    for attribute in typedef.CustomAttribute():
        _, attribute_name = attribute.TypeNamespaceAndName()
        if attribute_name not in ("ActivatableAttribute", "StaticAttribute"):
            continue
        args, _ = _attribute_args(attribute)
        interface_name = None
        if args and hasattr(args[0], "name"):
            interface_name = args[0].name
        elif args and isinstance(args[0], str) and "." in args[0]:
            interface_name = args[0]
        (activations if attribute_name == "ActivatableAttribute" else statics).append(
            interface_name
        )

    result._activations_ = activations
    result._statics_ = statics
    result.__init__ = _make_constructor(result)
    _add_statics(result)
    return result


def _forward(interface, member):
    """Calls a member of an interface the object has to be cast to first."""
    def forwarded(self, *arguments, **keywords):
        other = self._as(interface)
        if other is None:
            raise TypeError(f"{type(self).__name__} does not support {interface.__name__}")
        return getattr(other, member)(*arguments, **keywords)

    forwarded.__name__ = member
    return forwarded


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
            if not isinstance(interface, type):
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
        if not isinstance(interface, type):
            continue
        # Taken from the interface class, so that the overload renaming of
        # _add_members is what the static member is called too.
        for name, member in list(vars(interface).items()):
            if name.startswith("_") or name in vars(cls):
                continue
            if isinstance(member, property):
                setattr(cls, name, _StaticProperty(cls, interface, name))
            elif callable(member):
                setattr(cls, name, _make_static(cls, interface, name))


def _make_static(cls, interface, name):
    def call(*arguments):
        return getattr(_factory(cls._class_name_, interface), name)(*arguments)

    call.__name__ = name
    return staticmethod(call)


class _StaticProperty:
    def __init__(self, cls, interface, name):
        self._cls, self._interface, self._name = cls, interface, name

    def __get__(self, instance, owner=None):
        return getattr(_factory(self._cls._class_name_, self._interface), self._name)

    def __set__(self, instance, value):
        setattr(_factory(self._cls._class_name_, self._interface), self._name, value)


# --- generics ---------------------------------------------------------------
class Parameterized:
    """An open parameterized interface: IVector[Uri] closes it."""

    def __init__(self, typedef):
        self._typedef = typedef
        self.__name__ = typedef.TypeName()

    def __repr__(self):
        return f"<parameterized {_full_name(self._typedef)}>"

    def __getitem__(self, arguments):
        if not isinstance(arguments, tuple):
            arguments = (arguments,)
        return _closed_generic(self._typedef, tuple(_type_argument(a) for a in arguments))


_PYTHON_TYPES = {
    str: _STRING,
    bool: _Type("b1", ctypes.c_bool),
    int: _Type("i4", ctypes.c_int32),
    float: _Type("f8", ctypes.c_double),
    object: _INSPECTABLE,
}


def _type_argument(argument):
    """A type argument written in Python: a generated type, or str/int/bool/float."""
    if isinstance(argument, _Type):
        return argument
    if argument in _PYTHON_TYPES:
        return _PYTHON_TYPES[argument]
    typedef = getattr(argument, "_typedef_", None)
    if typedef is not None:
        if isinstance(argument, type) and getattr(argument, "_signature_", None):
            return _Type(argument._signature_, c_void_p, _pass_object, argument._wrap, argument)
        return _type_of_typedef(typedef)
    if isinstance(argument, IntEnum) or (
        isinstance(argument, type) and issubclass(argument, IntEnum)
    ):
        for typedef, value in _types.items():
            if value is argument:
                return _type_of_typedef(typedef)
    raise TypeError(f"{argument!r} cannot be a WinRT type argument")


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
        if not typedef:  # a parameterized type carries its arity: IVector`1
            for arity in (1, 2, 3):
                typedef = metadata().find(self._name, f"{name}`{arity}")
                if typedef:
                    break
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
        names = [name.split("`")[0] for name in members.types.keys()] if members else []
        prefix = self._name + "."
        for other in _namespace_names():
            if other.startswith(prefix):
                names.append(other[len(prefix) :].split(".")[0])
        return sorted(set(names))


_PUBLIC = (
    "init",
    "uninit",
    "configure",
    "metadata",
    "wait",
    "Namespace",
    "Parameterized",
    "GUID",
    "HSTRING",
    "WinRTError",
    "IActivationFactory",
)


def wait(operation, timeout=30.0):
    """Waits for an IAsyncOperation/IAsyncAction and returns its result."""
    return _async_get(operation, timeout)


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


def __dir__():
    return sorted(set(_PUBLIC) | {name.split(".")[0] for name in _namespace_names()})


if __name__ == "__main__":
    init()
    print(f"{len(_metadata_files())} .winmd files, {len(_namespace_names())} namespaces")
    for argument in sys.argv[1:]:
        value = sys.modules[__name__]
        for part in argument.split("."):
            value = getattr(value, part)
        print(f"{argument}: {value!r}")
