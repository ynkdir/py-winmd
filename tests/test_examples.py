"""Runs the programs under examples/, to see that they still run.

    python tests/test_examples.py

They are the worked examples the README points at, and nothing else builds
them, so a change to the reader that breaks one shows up here and nowhere
else. What is checked is that each does its job and says something it should
say, not what it says word for word: the metadata under vendor/ can be
refreshed and these should survive it.

dump.py, dumpwin32.py and ctypes_gen.py read metadata and print, so they run
anywhere. win32.py and winrt.py call the Windows API, and are skipped on a
machine that cannot.
"""

import contextlib
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "examples"))

from describe import SDK, WIN32  # noqa: E402

FOUNDATION = os.path.join(SDK, "Windows.Foundation.FoundationContract.winmd")
WIN32_MD = os.path.join(WIN32, "Windows.Win32.winmd")
ON_WINDOWS = sys.platform == "win32"


def run(module, *argv):
    """main(argv) with its output captured, as the command line would have it."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        module.main(list(argv))
    return out.getvalue()


class TestDump(unittest.TestCase):
    """Any metadata, in a C# like syntax."""

    def test_one_type(self):
        import dump

        printed = run(dump, "--type", "Windows.Foundation.IAsyncAction", FOUNDATION)
        self.assertIn("interface Windows.Foundation.IAsyncAction", printed)
        self.assertIn("Windows.Foundation.IAsyncInfo", printed)  # what it extends
        self.assertIn("void GetResults()", printed)

    def test_a_namespace(self):
        import dump

        printed = run(dump, "--namespace", "Windows.Foundation", FOUNDATION)
        self.assertIn("Windows.Foundation.AsyncStatus", printed)
        self.assertGreater(len(printed.splitlines()), 50)

    def test_a_summary(self):
        import dump

        printed = run(dump, "--summary", FOUNDATION)
        self.assertIn("Windows.Foundation", printed)


class TestDumpWin32(unittest.TestCase):
    """Win32 signatures, in a C like syntax."""

    def test_a_function(self):
        import dumpwin32

        printed = run(dumpwin32, "--search", "MessageBoxW")
        self.assertIn("MessageBoxW", printed)
        self.assertIn("USER32.dll", printed)  # from the ImplMap table
        self.assertIn("HWND hWnd", printed)  # a parameter, by name

    def test_a_struct(self):
        import dumpwin32

        printed = run(dumpwin32, "--search", "^MSG$", "--kind", "struct")
        self.assertIn("struct MSG {", printed)
        self.assertIn("HWND hwnd;", printed)

    def test_an_interface(self):
        import dumpwin32

        printed = run(dumpwin32, "--search", "^IStream$", "--kind", "interface")
        self.assertIn("interface IStream", printed)
        # the IID, from the GuidAttribute
        self.assertIn("0000000c-0000-0000-c000-000000000046", printed)

    def test_the_namespaces(self):
        import dumpwin32

        printed = run(dumpwin32, "--list")
        self.assertIn("Windows.Win32.UI.WindowsAndMessaging", printed)


class TestCtypesGen(unittest.TestCase):
    """A ctypes module generated from the Win32 metadata."""

    def generate(self, *argv):
        import ctypes_gen

        path = os.path.join(ROOT, "build", "generated.py")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        run(ctypes_gen, *argv, "-o", path)
        with open(path, encoding="utf-8") as file:
            return path, file.read()

    def test_a_function(self):
        path, source = self.generate("--function", "MessageBoxW")
        self.assertIn("MessageBoxW", source)
        self.assertIn("WinDLL", source)
        compile(source, path, "exec")  # it is at least Python

    def test_a_struct_and_its_union(self):
        _, source = self.generate("--type", "INPUT")
        # INPUT has an anonymous union, which is where ExplicitLayout is read
        self.assertIn("(Union)", source)
        self.assertIn("_anonymous_", source)
        self.assertIn("class INPUT(Structure)", source)

    @unittest.skipUnless(ON_WINDOWS, "the generated module loads Windows DLLs")
    def test_the_generated_module_imports(self):
        path, _ = self.generate("--function", "MessageBoxW")
        sys.path.insert(0, os.path.dirname(path))
        try:
            sys.modules.pop("generated", None)
            import generated  # type: ignore

            self.assertTrue(callable(generated.MessageBoxW))
        finally:
            sys.path.remove(os.path.dirname(path))


@unittest.skipUnless(ON_WINDOWS, "win32.py calls the Win32 API")
class TestWin32(unittest.TestCase):
    """The Win32 API, resolved from the metadata on attribute access."""

    @classmethod
    def setUpClass(cls):
        import win32

        win32.configure(WIN32_MD)
        cls.win32 = win32

    def test_a_constant(self):
        self.assertEqual(self.win32.MB_ICONINFORMATION, 0x40)

    def test_a_function(self):
        self.assertTrue(callable(self.win32.MessageBoxW))

    def test_the_namespace_path(self):
        namespaced = (
            self.win32.Windows.Win32.UI.WindowsAndMessaging.MessageBoxW  # type: ignore
        )
        self.assertIs(namespaced, self.win32.MessageBoxW)

    def test_a_struct(self):
        point = self.win32.POINT(1, 2)  # type: ignore
        self.assertEqual((point.x, point.y), (1, 2))


@unittest.skipUnless(ON_WINDOWS, "winrt.py activates WinRT classes")
class TestWinRT(unittest.TestCase):
    """WinRT: activation, HSTRING, generics."""

    @classmethod
    def setUpClass(cls):
        import winrt

        winrt.init()
        cls.winrt = winrt

    @classmethod
    def tearDownClass(cls):
        cls.winrt.uninit()

    def test_a_class_and_its_properties(self):
        uri = self.winrt.Windows.Foundation.Uri(  # type: ignore
            "https://example.com/a?b=c"
        )
        self.assertEqual(uri.Domain, "example.com")
        self.assertEqual(uri.Query, "?b=c")
        self.assertEqual(uri.ToString(), "https://example.com/a?b=c")

    def test_a_generic_interface(self):
        strings = self.winrt.Windows.Foundation.Collections.StringMap()  # type: ignore
        strings.Insert("one", "1")
        self.assertEqual(strings.Lookup("one"), "1")
        self.assertEqual(strings.Size, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
