"""What a short script costs: import, index, a few calls, exit.

    python research/startup_win32.py

Runs the same little program four ways - each reader, and each of the two ways
win32.py can be asked for a name - as a separate process, so what is measured is
what the user waits for.
"""

import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
METADATA = os.path.join(ROOT, "metadata", "Microsoft.Windows.SDK.Win32Metadata",
                        "Windows.Win32.winmd")

FLAT = """
{setup}
win32.configure(r"{metadata}")

print(win32.GetSystemMetrics(win32.SM_CXSCREEN),
      win32.GetSystemMetrics(win32.SM_CYSCREEN))
point = win32.POINT()
win32.GetCursorPos(win32.byref(point))
print(point.x, point.y)
print(win32.GetTickCount64())
"""

NAMESPACED = """
{setup}
win32.configure(r"{metadata}")

api = win32.Windows.Win32.UI.WindowsAndMessaging
kernel = win32.Windows.Win32.System.SystemInformation
foundation = win32.Windows.Win32.Foundation

print(api.GetSystemMetrics(api.SYSTEM_METRICS_INDEX.SM_CXSCREEN),
      api.GetSystemMetrics(api.SYSTEM_METRICS_INDEX.SM_CYSCREEN))
point = foundation.POINT()
print(kernel.GetTickCount64())
"""

# The module's __getattr__ builds the flat index of every name before it looks
# at the namespaces, so reaching for a namespace does not avoid it. Going
# through _namespace() does, which is what this third style measures - and what
# win32.py could do by checking the namespace roots first.
DIRECT = """
{setup}
win32.configure(r"{metadata}")

api = win32._namespace("Windows.Win32.UI.WindowsAndMessaging")
kernel = win32._namespace("Windows.Win32.System.SystemInformation")
foundation = win32._namespace("Windows.Win32.Foundation")

print(api.GetSystemMetrics(api.SYSTEM_METRICS_INDEX.SM_CXSCREEN),
      api.GetSystemMetrics(api.SYSTEM_METRICS_INDEX.SM_CYSCREEN))
point = foundation.POINT()
print(kernel.GetTickCount64())
"""

BINDINGS = f"import sys; sys.path.insert(0, r'{os.path.join(ROOT, 'examples')}'); import win32"
PURE = f"import sys; sys.path.insert(0, r'{HERE}'); import win32pure as win32"


def measure(python, code, repeat=5):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(code)
        path = handle.name
    try:
        best = float("inf")
        for _ in range(repeat):
            start = time.perf_counter()
            done = subprocess.run([python, path], capture_output=True, text=True)
            if done.returncode:
                raise SystemExit(done.stderr[-2000:])
            best = min(best, (time.perf_counter() - start) * 1000)
        return best
    finally:
        os.remove(path)


def main():
    python = sys.argv[1] if len(sys.argv) > 1 else sys.executable
    bare = measure(python, "pass")
    print(f"python {python}")
    print(f"bare interpreter                              {bare:8.1f} ms\n")

    rows = []
    for style, template in (("flat (win32.GetSystemMetrics)", FLAT),
                            ("namespaced (win32.Windows.Win32...)", NAMESPACED),
                            ("namespaced, no flat index", DIRECT)):
        for reader, setup in (("bindings", BINDINGS), ("pure python", PURE)):
            code = template.format(setup=setup, metadata=METADATA)
            rows.append((f"{style:36} {reader:12}", measure(python, code)))

    width = max(len(name) for name, _ in rows)
    best = min(value for _, value in rows)
    for name, value in rows:
        print(f"{name:{width}}  {value:8.1f} ms   {value - bare:8.1f} ms of work "
              f"  {value / best:5.2f}x")


if __name__ == "__main__":
    main()
