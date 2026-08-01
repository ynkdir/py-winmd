"""Times the reader, and compares two revisions of it.

    python scripts/bench.py                     # this working tree
    python scripts/bench.py --against HEAD      # this tree against a revision
    python scripts/bench.py --against pure-python~10

A number on its own says little: the same code measured 235 ms, 450 ms and
242 ms over one afternoon on one machine, as it warmed up and cooled down. So
--against measures both within a minute of each other and prints the pair,
which is the only comparison this has ever got a trustworthy answer from.

The other revision is checked out with `git worktree add` into a temporary
directory, so nothing here is touched, and its own src/ is what gets measured.
The metadata read is always this tree's, so both sides read the same bytes.
"""

import argparse
import os
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.environ.get("WINMD_VENDOR") or os.path.join(ROOT, "vendor")
WIN32 = os.path.join(VENDOR, "Microsoft.Windows.SDK.Win32Metadata", "Windows.Win32.winmd")
SDK = os.path.join(VENDOR, "Microsoft.Windows.SDK.Contracts", "ref", "netstandard2.0")


def measure(what, rounds=5):
    """The median of a few runs, which is steadier than the mean here."""
    times = []
    for _ in range(rounds):
        start = time.perf_counter()
        what()
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def benchmarks(reader):
    """What to time, and how to run each: name -> callable."""
    import glob

    contracts = sorted(path for path in glob.glob(os.path.join(SDK, "*"))
                       if path.lower().endswith(".winmd"))

    def open_one():
        reader.database(WIN32).close()

    def build_cache():
        reader.cache([WIN32]).close()

    def walk_everything():
        db = reader.cache([WIN32])
        for members in db.namespaces().values():
            for type in members.types.values():
                for field in type.FieldList():
                    field.Signature().Type().Type()
                for method in type.MethodList():
                    method.Signature().Params()
        db.close()

    def read_attributes():
        db = reader.cache(contracts)
        for members in db.namespaces().values():
            for type in members.types.values():
                for attribute in type.CustomAttribute():
                    attribute.TypeNamespaceAndName()
        db.close()

    return {
        "open Windows.Win32.winmd": open_one,
        "cache it": build_cache,
        "walk every signature in it": walk_everything,
        "name every attribute of the contracts": read_attributes,
    }


def run(source):
    """Times each benchmark against the reader under `source`."""
    sys.path.insert(0, source)
    for name in [name for name in sys.modules if name.startswith("winmd")]:
        del sys.modules[name]
    try:
        import winmd.reader as reader

        return {name: measure(what) for name, what in benchmarks(reader).items()}
    finally:
        sys.path.remove(source)


def worktree(revision):
    """`revision` checked out somewhere temporary, and cleaned up after."""
    directory = tempfile.mkdtemp(prefix="winmd-bench-")
    subprocess.run(["git", "worktree", "add", "--detach", directory, revision],
                   cwd=ROOT, check=True, capture_output=True)
    return directory


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--against", metavar="REVISION",
                        help="a git revision to measure beside this working tree")
    args = parser.parse_args(argv)

    if not os.path.exists(WIN32):
        parser.error(f"no metadata under {VENDOR}; scripts/fetch-vendor.ps1 installs it")

    here = run(os.path.join(ROOT, "src"))
    if args.against is None:
        for name, seconds in here.items():
            print(f"{seconds * 1000:8.0f} ms  {name}")
        return

    directory = worktree(args.against)
    try:
        there = run(os.path.join(directory, "src"))
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", directory],
                       cwd=ROOT, check=False, capture_output=True)

    print(f"{'this tree':>12}  {args.against:>12}")
    for name, seconds in here.items():
        was = there[name]
        print(f"{seconds * 1000:9.0f} ms {was * 1000:9.0f} ms  "
              f"{seconds / was:5.2f}x  {name}")


if __name__ == "__main__":
    main()
