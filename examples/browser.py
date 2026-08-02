"""A window that browses the Win32 metadata, drawn with the API it browses.

    python examples/browser.py
    python examples/browser.py --metadata other/Windows.Win32.winmd

Type a substring in the box at the top. The list underneath fills with the
names of Win32 that contain it, and picking one shows what windows.py made of
that name: the fields of a struct with the size ctypes gives it, the members
of an enum, the signature of a function or a callback, or the value of a
constant.

The window is made of the same names. RegisterClassExW, CreateWindowExW, the
message loop and the two controls are all resolved out of the metadata being
browsed, on first attribute access, like everything else windows.py hands back -
so the program draws itself with the thing it is showing you.
"""

import argparse
import ctypes
import glob
import os
import sys
from enum import IntEnum, IntFlag

import windows

# Where the Win32 metadata is when nothing names it: what scripts/fetch-vendor.ps1
# installs, in the repository this example lives in.
REPOSITORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_METADATA = os.path.join(
    "vendor", "Microsoft.Windows.SDK.Win32Metadata", "*.winmd"
)

CLASS_NAME = "WinmdBrowserWindow"
ID_SEARCH, ID_LIST, ID_DETAIL = 100, 101, 102
MARGIN, ROW, LIST_WIDTH = 8, 24, 320

# A list box is not the place to put two hundred thousand names, and nobody
# reads past the first screen of a substring search anyway.
LIMIT = 500

# The C spelling of the ctypes primitives, so a field reads as the header does.
SPELLING = {
    "c_bool": "bool",
    "c_char": "char",
    "c_wchar": "wchar",
    "c_wchar_p": "wchar *",
    "c_char_p": "char *",
    "c_int8": "int8",
    "c_uint8": "uint8",
    "c_short": "int16",
    "c_ushort": "uint16",
    "c_byte": "int8",
    "c_ubyte": "uint8",
    "c_int16": "int16",
    "c_uint16": "uint16",
    "c_int32": "int32",
    "c_uint32": "uint32",
    "c_int64": "int64",
    "c_uint64": "uint64",
    "c_long": "int32",
    "c_ulong": "uint32",
    "c_longlong": "int64",
    "c_ulonglong": "uint64",
    "c_float": "float",
    "c_double": "double",
    "c_ssize_t": "intptr",
    "c_size_t": "uintptr",
    "c_void_p": "void *",
}


def spelling(ctype):
    """How a ctypes type is written here."""
    if ctype is None:
        return "void"
    name = getattr(ctype, "__name__", str(ctype))
    if name.startswith("LP_"):
        return spelling(getattr(ctype, "_type_", None)) + " *"
    if issubclass(type(ctype), type) and issubclass(ctype, ctypes.Array):
        return f"{spelling(ctype._type_)}[{ctype._length_}]"
    return SPELLING.get(name, name)


def describe_record(value):
    """A struct or a union: what it holds, and what ctypes laid it out as."""
    kind = "union" if issubclass(value, ctypes.Union) else "struct"
    lines = [f"{kind}, {ctypes.sizeof(value)} bytes"]
    for name, field in ((f[0], f[1]) for f in value._fields_):
        lines.append(f"    {spelling(field)} {name}")
    return lines


def describe_enum(value):
    """An enum, with its members in the order the metadata gives them."""
    kind = "flags" if issubclass(value, IntFlag) else "enum"
    lines = [f"{kind}, {len(value.__members__)} members"]
    for member in value:
        lines.append(f"    {member.name} = {member.value}")
    return lines


def describe_callable(value):
    """A function or a callback, as its prototype.

    A callback is the ctypes type itself, which keeps its prototype under
    _argtypes_; a function is an instance of one, and keeps it under argtypes.
    """
    argtypes = getattr(value, "_argtypes_", None)
    restype = getattr(value, "_restype_", None)
    if argtypes is None:
        argtypes, restype = value.argtypes, value.restype
    arguments = ", ".join(spelling(argtype) for argtype in argtypes) or "void"
    return [f"{spelling(restype)} ({arguments})"]


def describe_interface(value):
    """A COM interface: what it derives from, its IID and its methods."""
    inherited = [cls.__name__ for cls in value.__mro__[1:] if hasattr(cls, "_iid_")]
    lines = [f"interface{' : ' + inherited[0] if inherited else ''}"]
    lines.append(f"    {value._iid_}")
    for cls in reversed([cls for cls in value.__mro__ if hasattr(cls, "_iid_")]):
        for name, method in cls.__dict__.items():
            if callable(method) and not name.startswith("_"):
                lines.append(f"    {cls.__name__}.{name}()")
    return lines


def namespace_of(name):
    """The namespace a name came from, for the names that came from one.

    windows.py defines a few itself - GUID and the interface base among them -
    and those are in dir() like the rest, with no namespace to point at.
    """
    try:
        return windows.namespace_of(name)
    except AttributeError:
        return "(windows.py itself)"


def describe(name):
    """What windows.py made of one name, as the lines of the pane on the right."""
    try:
        value = getattr(windows, name)
    except Exception as error:  # a name the metadata has but ctypes cannot build
        return "\r\n".join([name, "", f"{type(error).__name__}: {error}"])

    lines = [name, namespace_of(name), ""]
    if isinstance(value, type) and issubclass(value, (ctypes.Structure, ctypes.Union)):
        lines += describe_record(value)
    elif isinstance(value, type) and issubclass(value, (IntEnum, IntFlag)):
        lines += describe_enum(value)
    elif isinstance(value, (IntEnum, IntFlag)):
        lines += [f"{type(value).__name__}.{value.name} = {value.value}"]
    elif isinstance(value, type) and hasattr(value, "_iid_"):
        lines += describe_interface(value)
    elif hasattr(value, "argtypes") or hasattr(value, "_argtypes_"):
        lines += describe_callable(value)
    elif isinstance(value, type):
        lines += [f"{type(value).__name__}"]
    else:
        lines += [f"{type(value).__name__} = {value!r}"]
    return "\r\n".join(lines)


class Browser:
    """The window, its three controls and the names they are showing."""

    def __init__(self):
        self.names = []
        self.shown = []
        self.window = None
        self.search = None
        self.list = None
        self.detail = None
        self.font = None

    # --- the controls ---------------------------------------------------
    def child(self, cls, style, identifier):
        """One child control, of one of the classes the system registers."""
        return windows.CreateWindowExW(
            0,
            cls,
            None,
            windows.WS_CHILD | windows.WS_VISIBLE | style,
            0,
            0,
            0,
            0,
            self.window,
            ctypes.c_void_p(identifier),
            None,
            None,
        )

    def create(self, window):
        """WM_CREATE: the three controls, and the font the shell uses."""
        self.window = window
        self.search = self.child(
            "EDIT", windows.WS_BORDER | windows.ES_AUTOHSCROLL, ID_SEARCH
        )
        self.list = self.child(
            "LISTBOX",
            windows.WS_BORDER | windows.WS_VSCROLL | windows.LBS_NOTIFY,
            ID_LIST,
        )
        self.detail = self.child(
            "EDIT",
            windows.WS_BORDER
            | windows.WS_VSCROLL
            | windows.ES_MULTILINE
            | windows.ES_READONLY,
            ID_DETAIL,
        )

        metrics = windows.NONCLIENTMETRICSW()
        metrics.cbSize = ctypes.sizeof(metrics)
        windows.SystemParametersInfoW(
            windows.SPI_GETNONCLIENTMETRICS,
            ctypes.sizeof(metrics),
            ctypes.byref(metrics),
            0,
        )
        self.font = windows.CreateFontIndirectW(ctypes.byref(metrics.lfMessageFont))
        for control in (self.search, self.list, self.detail):
            windows.SendMessageW(control, windows.WM_SETFONT, self.font, 1)

        self.fill("")

    def layout(self):
        """WM_SIZE: the search box across the top, the list beside the pane."""
        rect = windows.RECT()
        windows.GetClientRect(self.window, ctypes.byref(rect))
        width, height = rect.right - MARGIN, rect.bottom - MARGIN
        windows.MoveWindow(self.search, MARGIN, MARGIN, width - MARGIN, ROW, True)
        top = MARGIN + ROW + MARGIN
        windows.MoveWindow(self.list, MARGIN, top, LIST_WIDTH, height - top, True)
        left = MARGIN + LIST_WIDTH + MARGIN
        windows.MoveWindow(self.detail, left, top, width - left, height - top, True)

    # --- the names ------------------------------------------------------
    def fill(self, wanted):
        """The names holding `wanted`, up to what a list box is good for."""
        wanted = wanted.lower()
        self.shown = [name for name in self.names if wanted in name.lower()][:LIMIT]
        windows.SendMessageW(self.list, windows.LB_RESETCONTENT, 0, 0)
        for name in self.shown:
            text = ctypes.create_unicode_buffer(name)
            windows.SendMessageW(
                self.list, windows.LB_ADDSTRING, 0, ctypes.addressof(text)
            )
        found = len([name for name in self.names if wanted in name.lower()])
        self.say(
            f"{found} names match" + (f", showing {LIMIT}" if found > LIMIT else "")
        )

    def selected(self):
        """WM_COMMAND from the list: describe whichever name was picked."""
        index = windows.SendMessageW(self.list, windows.LB_GETCURSEL, 0, 0)
        if 0 <= index < len(self.shown):
            self.say(describe(self.shown[index]))

    def typed(self):
        """WM_COMMAND from the search box: refill the list."""
        text = ctypes.create_unicode_buffer(256)
        windows.GetWindowTextW(self.search, text, len(text))
        self.fill(text.value)

    def say(self, text):
        windows.SetWindowTextW(self.detail, text)


def _dispatch(window, message, wparam, lparam):
    """The window procedure, over whichever Browser is current."""
    browser = _current
    if message == windows.WM_CREATE:
        browser.create(window)
    elif message == windows.WM_SIZE:
        browser.layout()
    elif message == windows.WM_COMMAND:
        control, notification = wparam & 0xFFFF, (wparam >> 16) & 0xFFFF
        if control == ID_SEARCH and notification == windows.EN_CHANGE:
            browser.typed()
        elif control == ID_LIST and notification == windows.LBN_SELCHANGE:
            browser.selected()
    elif message == windows.WM_DESTROY:
        windows.PostQuitMessage(0)
    else:
        return windows.DefWindowProcW(window, message, wparam, lparam)
    return 0


# The window class outlives the window, so a second run in the same process
# reuses the registration - and with it the procedure that registration holds.
# That callback must therefore outlive the run that made it, so there is one
# of it for the module, and it dispatches to whichever Browser is current.
_current = None
_proc = None


def window_proc():
    """The one WNDPROC this module ever makes."""
    global _proc
    if _proc is None:
        _proc = windows.WNDPROC(_dispatch)
    return _proc


def build(browser, title):
    """Registers the class and makes the window. Returns its handle."""
    instance = windows.GetModuleHandleW(None)
    arrow = ctypes.cast(ctypes.c_void_p(windows.IDC_ARROW), ctypes.c_wchar_p)

    cls = windows.WNDCLASSEXW()
    cls.cbSize = ctypes.sizeof(cls)
    cls.lpfnWndProc = window_proc()
    cls.hInstance = instance
    cls.hCursor = windows.LoadCursorW(None, arrow)
    cls.hbrBackground = ctypes.c_void_p(windows.COLOR_WINDOW + 1)
    cls.lpszClassName = CLASS_NAME
    if not windows.RegisterClassExW(ctypes.byref(cls)):
        # The class outlives one window, so a second run of main() in the same
        # process finds it already there, which is not a failure.
        if ctypes.get_last_error() != windows.ERROR_CLASS_ALREADY_EXISTS:
            raise OSError(f"RegisterClassExW failed: {ctypes.get_last_error()}")

    window = windows.CreateWindowExW(
        0,
        CLASS_NAME,
        title,
        windows.WS_OVERLAPPEDWINDOW,
        windows.CW_USEDEFAULT,
        windows.CW_USEDEFAULT,
        900,
        600,
        None,
        None,
        instance,
        None,
    )
    if not window:
        raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")
    return window


def pump(once=False):
    """The message loop, or one pass of it when `once`."""
    message = windows.MSG()
    if once:
        while windows.PeekMessageW(
            ctypes.byref(message), None, 0, 0, windows.PM_REMOVE
        ):
            windows.TranslateMessage(ctypes.byref(message))
            windows.DispatchMessageW(ctypes.byref(message))
        return
    while windows.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        windows.TranslateMessage(ctypes.byref(message))
        windows.DispatchMessageW(ctypes.byref(message))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--metadata",
        nargs="+",
        metavar="FILE",
        help=f"Win32 .winmd files (default: {DEFAULT_METADATA})",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="build the window, exercise it and close it, without showing it",
    )
    args = parser.parse_args(argv)

    files = args.metadata or glob.glob(os.path.join(REPOSITORY, DEFAULT_METADATA))
    if not files:
        parser.error(
            f"no .winmd file found - name one with --metadata, or put the Win32 "
            f"metadata in {DEFAULT_METADATA} (scripts/fetch-vendor.ps1 does)"
        )
    windows.configure(*files)

    global _current
    browser = _current = Browser()
    browser.names = sorted(name for name in dir(windows) if not name.startswith("_"))
    window = build(browser, f"winmd browser - {len(browser.names)} names")

    if args.selftest:
        browser.layout()
        browser.fill("MessageBox")
        pump(once=True)
        shown = windows.SendMessageW(browser.list, windows.LB_GETCOUNT, 0, 0)
        rect = windows.RECT()
        windows.GetClientRect(browser.list, ctypes.byref(rect))
        print(f"{len(browser.names)} names, {shown} shown for MessageBox")
        print(f"the list is {rect.right} x {rect.bottom}")
        print(describe("POINT"))
        windows.DestroyWindow(window)
        pump(once=True)
        return 0

    windows.ShowWindow(window, windows.SW_SHOWNORMAL)
    windows.UpdateWindow(window)
    pump()
    return 0


if __name__ == "__main__":
    sys.exit(main())
