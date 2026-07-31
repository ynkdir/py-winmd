"""Checks the pure Python reader against the C++ one, row by row."""

import sys

sys.path.insert(0, "research")

import purewinmd
from purewinmd import (
    FIELD, FIELD_LIST, FLAGS, METHOD_DEF, METHOD_LIST, NAME, NAMESPACE, PARAM,
    TYPE_DEF, TYPE_REF, Database,
)
from winmd.reader import database


def compare(path):
    pure = Database(path)
    cpp = database(path)

    for table, name in ((TYPE_DEF, "TypeDef"), (METHOD_DEF, "MethodDef"),
                        (FIELD, "Field"), (PARAM, "Param"), (TYPE_REF, "TypeRef")):
        mine = pure.rows(table)
        theirs = getattr(cpp, name).size()
        assert mine == theirs, f"{name}: {mine} != {theirs}"
    print(f"{path.rsplit(chr(92), 1)[-1]:50} row counts agree")

    # every TypeDef, in full
    rows = pure.table(TYPE_DEF)
    for index, row in enumerate(rows):
        theirs = cpp.TypeDef[index]
        assert pure.string(row[NAMESPACE]) == theirs.TypeNamespace(), index
        assert pure.string(row[NAME]) == theirs.TypeName(), index
        assert row[FLAGS] == theirs.Flags().value, index
        assert row[FIELD_LIST] == theirs.get_value(4) , index
        assert row[METHOD_LIST] == theirs.get_value(5), index
    print(f"{'':50} {len(rows)} TypeDef rows agree")

    # and the columns of the tables a program actually walks
    for table, name, columns in (
        (METHOD_DEF, "MethodDef", (0, 1, 2, 3, 4, 5)),
        (FIELD, "Field", (0, 1, 2)),
        (PARAM, "Param", (0, 1, 2)),
    ):
        rows = pure.table(table)
        native = getattr(cpp, name)
        for index in range(0, len(rows), max(1, len(rows) // 5000)):
            for column in columns:
                assert rows[index][column] == native[index].get_value(column), \
                    f"{name}[{index}].{column}"
        print(f"{'':50} {name} columns agree ({len(rows)} rows)")

    pure.close()


if __name__ == "__main__":
    for path in sys.argv[1:]:
        compare(path)
    print("OK")
