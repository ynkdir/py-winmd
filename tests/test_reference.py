"""Checks the reader against the C++ one it was written from.

    python tests/test_reference.py

Builds tests/reference.cpp against the Microsoft.Windows.WinMD headers, runs it
over the same .winmd files as the Python reader, and compares the two
descriptions line for line: flags, category, base class, interfaces, generic
parameters, fields with their signatures and constants, methods with their full
signatures and parameter directions, properties, events, and every custom
attribute with its arguments decoded.

Skipped, with a reason, when the headers, a C++ compiler or the metadata are
not there:

    scripts/fetch-vendor.ps1                  # installs both, under vendor/
"""

import glob
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import describe                                    # noqa: E402
from describe import HEADERS, SDK, WIN32           # noqa: E402

BUILD = os.path.join(ROOT, "build", "reference")


def find_compiler():
    """A C++17 compiler, and how to invoke it. MSVC needs its environment."""
    for name in ("g++", "clang++"):
        found = shutil.which(name)
        if found:
            return name, [found, "-std=c++17", "-O1", "-w"]
    if shutil.which("cl"):
        return "cl", ["cl", "/std:c++17", "/EHsc", "/nologo", "/W0"]
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", ""),
                           "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if os.path.exists(vswhere):
        done = subprocess.run(
            [vswhere, "-latest", "-products", "*", "-property", "installationPath"],
            capture_output=True, text=True)
        path = done.stdout.strip()
        vcvars = os.path.join(path, "VC", "Auxiliary", "Build", "vcvars64.bat")
        if path and os.path.exists(vcvars):
            return "cl", [vcvars]                  # marker: run through cmd
    return None, None


def build_reference():
    """Compiles tests/reference.cpp, and says where the binary is."""
    os.makedirs(BUILD, exist_ok=True)
    name, command = find_compiler()
    if not name:
        raise unittest.SkipTest("no C++ compiler found (g++, clang++ or MSVC)")

    source = os.path.join(HERE, "reference.cpp")
    if name == "cl":
        binary = os.path.join(BUILD, "reference.exe")
        # The trailing backslash of /Fo has to be doubled: one before the closing
        # quote escapes the quote itself, and the path comes out mangled.
        compile = (f'cl /std:c++17 /EHsc /nologo /W0 /I"{HEADERS}" "{source}" '
                   f'/Fe:"{binary}" /Fo:"{BUILD}\\\\"')
        if len(command) == 1:
            # MSVC needs its environment, and quoting a call to vcvars64.bat
            # through cmd /c is more trouble than writing the two lines down.
            script = os.path.join(BUILD, "build.bat")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write(f'@echo off\ncall "{command[0]}" >nul\n{compile}\n')
            done = subprocess.run(["cmd", "/c", script], capture_output=True, text=True)
        else:
            done = subprocess.run(["cmd", "/c", compile], capture_output=True, text=True)
    else:
        binary = os.path.join(BUILD, "reference")
        done = subprocess.run(command + [f"-I{HEADERS}", source, "-o", binary],
                              capture_output=True, text=True)
    if done.returncode:
        raise AssertionError(f"building the reference failed:\n{done.stdout}\n{done.stderr}")
    return binary


def reference_output(binary, paths):
    done = subprocess.run([binary, *paths], capture_output=True)
    if done.returncode:
        raise AssertionError(f"the reference failed: {done.stderr.decode(errors='replace')}")
    return done.stdout.decode("utf-8").splitlines()


class TestAgainstTheCppReader(unittest.TestCase):
    """The Python reader must describe metadata exactly as the C++ one does."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(os.path.join(HEADERS, "winmd_reader.h")):
            raise unittest.SkipTest(
                f"no C++ reader in {HEADERS}; run scripts/fetch-vendor.ps1")
        cls.binary = build_reference()
        import winmd.reader
        cls.reader = winmd.reader

    def compare(self, paths):
        for path in paths:
            if not os.path.exists(path):
                self.skipTest(f"{path} is missing; run fetch-metadata.py")
        expected = reference_output(self.binary, paths)
        actual = describe.describe_all(paths, self.reader)

        if expected != actual:
            for index, (left, right) in enumerate(zip(expected, actual)):
                if left != right:
                    context = "\n".join(
                        f"    {line}" for line in expected[max(0, index - 6):index])
                    self.fail(f"line {index} differs\n{context}\n"
                              f"  c++   : {left}\n  python: {right}")
            self.fail(f"the descriptions are {len(actual)} lines against "
                      f"{len(expected)} from the reference")
        self.assertGreater(len(actual), 1000)

    def test_win32(self):
        self.compare([os.path.join(WIN32, "Windows.Win32.winmd")])

    def test_winrt_contracts(self):
        self.compare(sorted(glob.glob(os.path.join(SDK, "Windows.Foundation.*.winmd"))))

    def test_winrt_system(self):
        paths = sorted(glob.glob(r"C:\Windows\System32\WinMetadata\*.winmd"))
        if not paths:
            self.skipTest("no WinMetadata on this machine")
        self.compare(paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)

