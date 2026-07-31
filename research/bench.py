"""Times the pure Python reader against the nanobind bindings, same tasks.

    python research/bench.py metadata/Microsoft.Windows.SDK.Win32Metadata/Windows.Win32.winmd

Each task is what a program actually does, not a microbenchmark:

    open        open the file and lay the tables out; nothing read yet
    typedefs    the namespace and name of every type
    index       {namespace: {name: type}}, which is what a cache is for
    members     walk every type's fields and methods, and every method's params
"""

import argparse
import gc
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

import purewinmd
from purewinmd import (
    FIELD_LIST, FLAGS, METHOD_DEF, METHOD_LIST, NAME, NAMESPACE, PARAM, TYPE_DEF,
)
from winmd.reader import cache, database


def timed(function, repeat):
    """The best and the median of `repeat` runs, in milliseconds."""
    times = []
    for _ in range(repeat):
        gc.collect()
        start = time.perf_counter()
        result = function()
        times.append((time.perf_counter() - start) * 1000)
        del result
    return min(times), statistics.median(times)


# --- pure Python ----------------------------------------------------------
def pure_open(path):
    db = purewinmd.Database(path)
    db.close()


def pure_typedefs(path):
    db = purewinmd.Database(path)
    string = db.string
    names = [(string(row[NAMESPACE]), string(row[NAME])) for row in db.table(TYPE_DEF)]
    db.close()
    return names


def pure_index(path):
    db = purewinmd.Database(path)
    index = db.namespaces()
    db.close()
    return index


def pure_members(path):
    """A member list is 'my first child until the next row's first child'."""
    db = purewinmd.Database(path)
    types = db.table(TYPE_DEF)
    methods = db.table(METHOD_DEF)
    field_count = db.rows(4)
    param_count = db.rows(PARAM)

    fields = 0
    parameters = 0
    for index, row in enumerate(types):
        following = types[index + 1] if index + 1 < len(types) else None
        fields += (following[FIELD_LIST] if following else field_count + 1) - row[FIELD_LIST]
        first = row[METHOD_LIST] - 1
        last = (following[METHOD_LIST] - 1) if following else len(methods)
        for method_index in range(first, last):
            after = methods[method_index + 1] if method_index + 1 < len(methods) else None
            parameters += (after[5] if after else param_count + 1) - methods[method_index][5]
    db.close()
    return fields, parameters


# --- the bindings ---------------------------------------------------------
def cpp_open(path):
    database(path)


def cpp_typedefs(path):
    db = database(path)
    return [(row.TypeNamespace(), row.TypeName()) for row in db.TypeDef]


def cpp_index(path):
    return cache([path])


def cpp_members(path):
    db = database(path)
    fields = 0
    parameters = 0
    for type in db.TypeDef:
        fields += len(type.FieldList())
        for method in type.MethodList():
            parameters += len(method.ParamList())
    return fields, parameters


TASKS = (
    ("open", pure_open, cpp_open),
    ("typedefs", pure_typedefs, cpp_typedefs),
    ("index", pure_index, cpp_index),
    ("members", pure_members, cpp_members),
)


def pure_index_all(paths):
    """The WinRT case: one index over a directory full of files."""
    index = {}
    for path in paths:
        db = purewinmd.Database(path)
        for namespace, members in db.namespaces().items():
            index.setdefault(namespace, {}).update(members)
        db.close()
    return index


def cpp_index_all(paths):
    return cache(list(paths))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--together", action="store_true",
                        help="index every file into one cache, as WinRT needs")
    arguments = parser.parse_args()

    if arguments.together:
        files = arguments.files
        size = sum(os.path.getsize(path) for path in files) / 1024 / 1024
        print(f"\n{len(files)} files, {size:.1f} MB, indexed together")
        pure_best, pure_median = timed(lambda: pure_index_all(files), arguments.repeat)
        cpp_best, cpp_median = timed(lambda: cpp_index_all(files), arguments.repeat)
        print(f"{'task':10} {'pure python':>22} {'bindings':>22} {'ratio':>7}")
        print(f"{'index':10} {pure_best:9.1f} ms ({pure_median:7.1f}) "
              f"{cpp_best:9.1f} ms ({cpp_median:7.1f}) {pure_best / cpp_best:6.1f}x")
        return

    for path in arguments.files:
        size = os.path.getsize(path) / 1024 / 1024
        db = purewinmd.Database(path)
        rows = db.rows(TYPE_DEF)
        db.close()
        print(f"\n{os.path.basename(path)}  ({size:.1f} MB, {rows} types)")
        print(f"{'task':10} {'pure python':>22} {'bindings':>22} {'ratio':>7}")

        for name, pure, cpp in TASKS:
            pure_best, pure_median = timed(lambda: pure(path), arguments.repeat)
            cpp_best, cpp_median = timed(lambda: cpp(path), arguments.repeat)
            print(f"{name:10} {pure_best:9.1f} ms ({pure_median:7.1f}) "
                  f"{cpp_best:9.1f} ms ({cpp_median:7.1f}) {pure_best / cpp_best:6.1f}x")


if __name__ == "__main__":
    main()
