"""Where the time goes in the pure Python reader, and what moves it.

    python research/optimize.py metadata/.../Windows.Win32.winmd

Answers, on real metadata rather than a synthetic file, what the decoding
strategy is worth: a row at a time, a table at a time, or a column at a time,
and what the string heap costs however it is held.
"""

import array
import gc
import mmap
import os
import statistics
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from winmd.reader import TYPE_DEF, Database

NAME, NAMESPACE = 1, 2              # TypeDef columns


def timed(function, repeat=5):
    times = []
    for _ in range(repeat):
        gc.collect()
        start = time.perf_counter()
        result = function()
        times.append((time.perf_counter() - start) * 1000)
        del result
    return min(times)


def report(title, rows):
    width = max(len(name) for name, _ in rows)
    best = min(time for _, time in rows)
    print(f"\n{title}")
    for name, value in rows:
        print(f"  {name:{width}}  {value:8.1f} ms   {value / best:5.2f}x")


def main(path):
    db = Database(path)
    count = db.rows(TYPE_DEF)
    start = db._start[TYPE_DEF]
    size = db._row_size[TYPE_DEF]
    fmt = db._format[TYPE_DEF]
    tables = db._tables
    print(f"{os.path.basename(path)}: {count} TypeDef rows of {size} bytes, {fmt}")

    # --- decoding a table ---------------------------------------------------
    def per_row():
        return [struct.unpack_from(fmt, tables, start + index * size)
                for index in range(count)]

    def per_row_compiled():
        unpack = struct.Struct(fmt).unpack_from
        return [unpack(tables, start + index * size) for index in range(count)]

    def whole_table():
        return list(struct.iter_unpack(fmt, tables[start:start + size * count]))

    def whole_table_no_list():
        # what a program that only wants two columns would do
        return [(row[NAMESPACE], row[NAME])
                for row in struct.iter_unpack(fmt, tables[start:start + size * count])]

    def columns_with_array():
        # one array per column, sliced out of the table with a stride
        raw = bytes(tables[start:start + size * count])
        out = []
        for offset, width in db._columns[TYPE_DEF]:
            values = array.array({2: "H", 4: "I", 8: "Q"}[width])
            values.frombytes(b"".join(
                raw[index * size + offset:index * size + offset + width]
                for index in range(count)))
            out.append(values)
        return out

    report("decoding the TypeDef table", [
        ("unpack_from, a row at a time", timed(per_row)),
        ("Struct().unpack_from, a row at a time", timed(per_row_compiled)),
        ("iter_unpack, the whole table", timed(whole_table)),
        ("iter_unpack, keeping two columns", timed(whole_table_no_list)),
        ("array per column, strided", timed(columns_with_array)),
    ])

    # --- the string heap ----------------------------------------------------
    with open(path, "rb") as handle:
        data = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
    view = memoryview(data)
    heap_start, heap_size = db._strings_range
    print(f"\n#Strings is {heap_size / 1024 / 1024:.1f} MB")

    rows = db.table(TYPE_DEF)
    indexes = [row[NAME] for row in rows] + [row[NAMESPACE] for row in rows]
    unique = len(set(indexes))
    print(f"{len(indexes)} name lookups, {unique} of them distinct")

    heap_bytes = bytes(view[heap_start:heap_start + heap_size])
    heap_view = view[heap_start:heap_start + heap_size]

    def from_bytes():
        out = []
        for index in indexes:
            end = heap_bytes.index(b"\0", index)
            out.append(heap_bytes[index:end].decode("utf-8"))
        return out

    def from_memoryview():
        # mmap has find(); a memoryview has neither index() nor find(), so a
        # reader that stays on the mapping has to go through the mmap itself.
        mapping = data
        out = []
        for index in indexes:
            end = mapping.find(b"\0", heap_start + index)
            out.append(str(mapping[heap_start + index:end], "utf-8"))
        return out

    def cached():
        cache = {}
        out = []
        for index in indexes:
            value = cache.get(index)
            if value is None:
                end = heap_bytes.index(b"\0", index)
                value = cache[index] = heap_bytes[index:end].decode("utf-8")
            out.append(value)
        return out

    # Decoding the heap in one go and indexing into it by offset looks like the
    # obvious win, and is wrong: the heap shares suffixes, so an index can point
    # into the middle of a string rather than at its start.
    table = {}
    position = 0
    for piece in heap_bytes.split(b"\0"):
        table[position] = piece.decode("utf-8")
        position += len(piece) + 1
    inside = [index for index in set(indexes) if index not in table]
    print(f"{len(inside)} of the {unique} distinct offsets point inside another "
          f"string (suffix sharing), so splitting the heap up front does not work")
    if inside:
        example = inside[0]
        end = heap_bytes.index(b"\0", example)
        start = heap_bytes.rindex(b"\0", 0, example) + 1
        print(f"    offset {example} is {heap_bytes[example:end].decode()!r}, "
              f"the tail of {heap_bytes[start:end].decode()!r}")

    def split_once():
        return [table[index] for index in indexes if index in table]

    report("reading the names of every type", [
        ("bytes heap, decode each time", timed(from_bytes)),
        ("memoryview of the mapping", timed(from_memoryview)),
        ("bytes heap, cached by offset", timed(cached)),
        ("split the heap once (wrong, see above)", timed(split_once)),
    ])

    # --- and the two together, which is the shape of a real startup ---------
    namespace_indexes = [row[NAMESPACE] for row in rows]
    print(f"\n{len(namespace_indexes)} namespace lookups, "
          f"{len(set(namespace_indexes))} of them distinct")

    def index_cached():
        cache = {}
        out = {}
        for row in rows:
            if not row[0]:
                continue
            names = []
            for index in (row[NAMESPACE], row[NAME]):
                value = cache.get(index)
                if value is None:
                    end = heap_bytes.index(b"\0", index)
                    value = cache[index] = heap_bytes[index:end].decode("utf-8")
                names.append(value)
            out.setdefault(names[0], {})[names[1]] = row
        return out

    def index_plain():
        out = {}
        for row in rows:
            if not row[0]:
                continue
            index = row[NAMESPACE]
            namespace = heap_bytes[index:heap_bytes.index(b"\0", index)].decode("utf-8")
            index = row[NAME]
            name = heap_bytes[index:heap_bytes.index(b"\0", index)].decode("utf-8")
            out.setdefault(namespace, {})[name] = row
        return out

    def index_namespace_cached_only():
        cache = {}
        out = {}
        for row in rows:
            if not row[0]:
                continue
            index = row[NAMESPACE]
            namespace = cache.get(index)
            if namespace is None:
                end = heap_bytes.index(b"\0", index)
                namespace = cache[index] = heap_bytes[index:end].decode("utf-8")
            index = row[NAME]
            name = heap_bytes[index:heap_bytes.index(b"\0", index)].decode("utf-8")
            out.setdefault(namespace, {})[name] = row
        return out

    report("building {namespace: {name: row}} from the decoded table", [
        ("no string cache", timed(index_plain)),
        ("cache every string", timed(index_cached)),
        ("cache namespaces only", timed(index_namespace_cached_only)),
    ])

    del heap_view
    view.release()
    data.close()
    db.close()


if __name__ == "__main__":
    main(sys.argv[1])



