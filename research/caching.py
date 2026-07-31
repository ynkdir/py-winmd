"""Is it worth saving the parse instead of doing it again?

    python research/caching.py metadata/.../Windows.Win32.winmd

Builds the index a program needs at startup, writes it out with pickle and with
marshal, and reads it back - against simply parsing the file again.
"""

import gc
import marshal
import os
import pickle
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import purewinmd
from purewinmd import METHOD_DEF, TYPE_DEF, Database

# TypeDef columns, read straight from the table
FLAGS, NAME, NAMESPACE, EXTENDS, FIELD_LIST, METHOD_LIST = range(6)
from winmd.reader import cache


def timed(function, repeat=5):
    times = []
    for _ in range(repeat):
        gc.collect()
        start = time.perf_counter()
        result = function()
        times.append((time.perf_counter() - start) * 1000)
    return min(times), result


def build_index(path):
    """{namespace: {name: row}} plus every method name, which is the shape a
    projection wants: enough to answer "what is called X" without the file."""
    db = Database(path)
    types = db.table(TYPE_DEF)
    methods = db.table(METHOD_DEF)
    string = db.string

    index = {}
    method_names = []
    for row_index, row in enumerate(types):
        if not row[0]:
            continue
        following = types[row_index + 1] if row_index + 1 < len(types) else None
        first = row[METHOD_LIST] - 1
        last = (following[METHOD_LIST] - 1) if following else len(methods)
        index.setdefault(string(row[NAMESPACE]), {})[string(row[NAME])] = (
            row_index, first, last)
        method_names.extend(string(methods[i][3]) for i in range(first, last))
    db.close()
    return index, method_names


def main(path):
    print(f"{os.path.basename(path)}  ({os.path.getsize(path) / 1024 / 1024:.1f} MB)")

    parse, (index, method_names) = timed(lambda: build_index(path))
    namespaces = len(index)
    types = sum(len(members) for members in index.values())
    print(f"index: {namespaces} namespaces, {types} types, {len(method_names)} method names")
    print(f"\nbuilding it from the file      {parse:8.1f} ms")

    payload = (index, method_names)
    directory = tempfile.mkdtemp()
    pickle_path = os.path.join(directory, "index.pickle")
    marshal_path = os.path.join(directory, "index.marshal")

    write_pickle, _ = timed(lambda: open(pickle_path, "wb").write(
        pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)))
    write_marshal, _ = timed(lambda: open(marshal_path, "wb").write(
        marshal.dumps(payload)))

    read_pickle, _ = timed(lambda: pickle.loads(open(pickle_path, "rb").read()))
    read_marshal, _ = timed(lambda: marshal.loads(open(marshal_path, "rb").read()))

    print(f"writing it as pickle           {write_pickle:8.1f} ms   "
          f"({os.path.getsize(pickle_path) / 1024 / 1024:.1f} MB)")
    print(f"writing it as marshal          {write_marshal:8.1f} ms   "
          f"({os.path.getsize(marshal_path) / 1024 / 1024:.1f} MB)")
    print(f"reading the pickle back        {read_pickle:8.1f} ms   "
          f"{parse / read_pickle:5.2f}x faster than parsing")
    print(f"reading the marshal back       {read_marshal:8.1f} ms   "
          f"{parse / read_marshal:5.2f}x faster than parsing")

    # the bindings, for scale: a cache is the same thing in C++
    build_cache, _ = timed(lambda: cache([path]))
    print(f"\nthe bindings' cache([path])    {build_cache:8.1f} ms")

    os.remove(pickle_path)
    os.remove(marshal_path)
    os.rmdir(directory)


if __name__ == "__main__":
    main(sys.argv[1])

