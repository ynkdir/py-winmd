"""Column oriented decoding, with and without numpy.

    python research/columns.py metadata/.../Windows.Win32.winmd

A table is a fixed stride of bytes, so pulling one column out of it is what
numpy is good at. The question is whether that helps a reader whose output is
Python objects in the end.
"""

import gc
import os
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"))

from winmd.reader import TYPE_DEF, Database

NAMESPACE = 2                       # the TypeDef column

try:
    import numpy
except ImportError:
    numpy = None


def timed(function, repeat=7):
    times = []
    for _ in range(repeat):
        gc.collect()
        start = time.perf_counter()
        result = function()
        times.append((time.perf_counter() - start) * 1000)
        del result
    return min(times)


def main(path):
    db = Database(path)
    count = db.rows(TYPE_DEF)
    size = db._row_size[TYPE_DEF]
    start = db._start[TYPE_DEF]
    fmt = db._format[TYPE_DEF]
    offset, width = db._columns[TYPE_DEF][NAMESPACE]
    raw = bytes(db._tables[start:start + size * count])
    print(f"{os.path.basename(path)}: {count} rows x {size} bytes, "
          f"column {NAMESPACE} at +{offset} ({width} bytes)")

    def rows_then_column():
        return [row[NAMESPACE] for row in struct.iter_unpack(fmt, raw)]

    def strided_struct():
        # one unpack per row, but only of the column
        column = struct.Struct("<I")
        return [column.unpack_from(raw, index * size + offset)[0]
                for index in range(count)]

    results = [
        ("iter_unpack the rows, keep one column", timed(rows_then_column)),
        ("unpack just the column, a row at a time", timed(strided_struct)),
    ]

    if numpy is not None:
        def numpy_column():
            table = numpy.frombuffer(raw, dtype=numpy.uint8).reshape(count, size)
            return table[:, offset:offset + width].copy().view(numpy.uint32).ravel()

        def numpy_column_to_list():
            return numpy_column().tolist()

        results.append(("numpy strided view", timed(numpy_column)))
        results.append(("numpy strided view, then .tolist()", timed(numpy_column_to_list)))

        assert numpy_column().tolist() == rows_then_column()
    else:
        print("(numpy is not installed; run this in an environment that has it)")

    best = min(value for _, value in results)
    width_ = max(len(name) for name, _ in results)
    print()
    for name, value in results:
        print(f"  {name:{width_}}  {value:8.2f} ms   {value / best:5.2f}x")

    db.close()


if __name__ == "__main__":
    main(sys.argv[1])


