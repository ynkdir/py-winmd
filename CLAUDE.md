# Python winmd parser

A Python port of the C++ winmd parser.

## Principles

- Keep compatibility with the C++ implementation wherever it can be kept.
- Depart from it where the port to Python would otherwise be forced.
- Prefer code that is standard, static and declarative.

## Rules

- **Read the C++ before naming anything.** It is in the tree, under
  `vendor/Microsoft.Windows.WinMD/impl/winmd_reader/`: `enum.h` for the enums
  and the values they hold, `flags.h` for the flags columns, `schema.h` for the
  38 tables and the accessors each row has, `table.h` and `signature.h` for the
  rest. A name, an accessor and an enumerator's value match it unless Python
  cannot say the same thing. What is left over is listed under "Differences from
  the C++ interface" in README.md, and that list is meant to stay short.
- **tests/test_reference.py decides.** It builds the C++ reader and compares it
  against this one over every type in the metadata. Where the two disagree, this
  one is wrong.
- **Write it down rather than build it at run time.** No `setattr` onto a class,
  no names injected into `globals()`. A table, a coded index kind and a flags
  column are each a class, written out.
- **One name for one thing.** No alias beside the name it aliases, and nothing
  re-exported under a second spelling. `__all__` is what the module offers.
- **Never add `*.winmd` to `.gitignore`.** `vendor/` is committed, the metadata
  and the C++ headers alike, and that pattern also matches the directory
  `Microsoft.Windows.WinMD` where the file system ignores case.

## Checks

    python -m unittest discover -s tests   # reference suite wants a C++ compiler
    pyrefly check                          # keep at 0; every function is annotated

Python 3.11 or newer.
