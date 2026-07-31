"""What each reader costs before it has read anything: the import."""

import subprocess
import sys
import time


def measure(code, repeat=5):
    best = float("inf")
    for _ in range(repeat):
        start = time.perf_counter()
        subprocess.run([sys.executable, "-c", code], check=True)
        best = min(best, (time.perf_counter() - start) * 1000)
    return best


bare = measure("pass")
bindings = measure("import winmd.reader")
pure = measure("import sys; sys.path.insert(0, 'research'); import purewinmd")

print(f"bare interpreter            {bare:6.1f} ms")
print(f"import winmd.reader         {bindings - bare:6.1f} ms on top")
print(f"import purewinmd            {pure - bare:6.1f} ms on top")
