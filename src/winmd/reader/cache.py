"""A set of files indexed by namespace, as cache.h and filter.h have them.

What resolves a TypeRef in one file to the TypeDef in another, since metadata
names types across files rather than pointing at them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from .database import database
from .enum import TableNumber, category
from .helpers import extends_type, get_attribute, get_category, is_nested
from .schema import TypeDef
from .table import Row


# --- the cache ------------------------------------------------------------
class namespace_members:
    __slots__ = (
        "types",
        "interfaces",
        "classes",
        "enums",
        "structs",
        "delegates",
        "attributes",
        "contracts",
    )

    def __init__(self) -> None:
        self.types: dict[str, TypeDef] = {}
        self.interfaces: list[TypeDef] = []
        self.classes: list[TypeDef] = []
        self.enums: list[TypeDef] = []
        self.structs: list[TypeDef] = []
        self.delegates: list[TypeDef] = []
        self.attributes: list[TypeDef] = []
        self.contracts: list[TypeDef] = []

    def __repr__(self) -> str:
        return f"<namespace_members types={len(self.types)}>"


class filter:
    """Include and exclude prefixes, longest first."""

    def __init__(
        self, includes: Sequence[str] = (), excludes: Sequence[str] = ()
    ) -> None:
        self._rules: list[tuple[str, bool]] = [(prefix, True) for prefix in includes]
        self._rules += [(prefix, False) for prefix in excludes]
        self._rules.sort(key=lambda rule: (len(rule[0]), not rule[1]), reverse=True)

    def includes(
        self,
        value: TypeDef
        | namespace_members
        | str
        | Iterable[TypeDef | namespace_members | str],
    ) -> bool:
        if isinstance(value, Row):
            return self._match(value.TypeNamespace(), value.TypeName())
        if isinstance(value, namespace_members):
            return any(
                self._match(row.TypeNamespace(), row.TypeName())
                for row in value.types.values()
            )
        if isinstance(value, str):
            namespace, _, name = value.rpartition(".")
            return self._match(namespace, name)
        return any(self.includes(row) for row in value)

    def _match(self, namespace: str, name: str) -> bool:
        if not self._rules:
            return True
        full = f"{namespace}.{name}"
        for prefix, included in self._rules:
            if full == prefix or full.startswith(prefix + "."):
                return included
        return False

    def empty(self) -> bool:
        return not self._rules

    def __call__(self, type: TypeDef) -> bool:
        return self.includes(type)


class cache:
    """A set of .winmd files, with their types indexed by namespace and name."""

    def __init__(
        self,
        files: Sequence[str] | str = (),
        filter: Callable[[TypeDef], bool] | None = None,
    ) -> None:
        if isinstance(files, str):
            files = [files]
        self._databases: list[database] = []
        self._namespaces: dict[str, namespace_members] = {}
        self._nested: dict[TypeDef, list[TypeDef]] = {}
        for file in files:
            self.add_database(file, filter)

    def add_database(
        self, file: str, filter: Callable[[TypeDef], bool] | None = None
    ) -> None:
        db = database(file, self)
        self._databases.append(db)

        heap = db._strings
        namespaces: dict[int, str] = {}
        for index, row in enumerate(db.table(TableNumber.TypeDef)):
            if not row[0]:  # the <Module> row
                continue
            type = TypeDef(db, index)
            if is_nested(type) or (filter is not None and not filter(type)):
                continue
            at = row[2]
            namespace = namespaces.get(at)
            if namespace is None:
                namespace = namespaces[at] = heap[at : heap.index(b"\0", at)].decode(
                    "utf-8"
                )
            at = row[1]
            name = heap[at : heap.index(b"\0", at)].decode("utf-8")
            members = self._namespaces.get(namespace)
            if members is None:
                members = self._namespaces[namespace] = namespace_members()
            if name not in members.types:
                members.types[name] = type
                self._add_to_members(type, members)

        for row in db.NestedClass:
            self._nested.setdefault(row.EnclosingType(), []).append(row.NestedType())

    def _add_to_members(self, type: TypeDef, members: namespace_members) -> None:
        kind = get_category(type)
        if kind == category.interface_type:
            members.interfaces.append(type)
        elif kind == category.class_type:
            if extends_type(type, "System", "Attribute"):
                members.attributes.append(type)
            else:
                members.classes.append(type)
        elif kind == category.enum_type:
            members.enums.append(type)
        elif kind == category.struct_type:
            if get_attribute(
                type, "Windows.Foundation.Metadata", "ApiContractAttribute"
            ):
                members.contracts.append(type)
            else:
                members.structs.append(type)
        elif kind == category.delegate_type:
            members.delegates.append(type)

    def find(self, namespace: str, name: str | None = None) -> TypeDef | None:
        if name is None:
            namespace, _, name = namespace.rpartition(".")
            if not namespace:
                raise ValueError("a type name needs a namespace")
        members = self._namespaces.get(namespace)
        return members.types.get(name) if members else None

    def find_required(self, namespace: str, name: str | None = None) -> TypeDef:
        type = self.find(namespace, name)
        if not type:
            raise ValueError(f"the type {namespace}.{name} could not be found")
        return type

    def namespaces(self) -> dict[str, namespace_members]:
        return self._namespaces

    def databases(self) -> list[database]:
        return self._databases

    def nested_types(self, enclosing: TypeDef) -> list[TypeDef]:
        return self._nested.get(enclosing, [])

    def remove_type(self, namespace: str, name: str) -> None:
        members = self._namespaces.get(namespace)
        if not members:
            return
        for collection in (
            members.interfaces,
            members.classes,
            members.enums,
            members.structs,
            members.delegates,
        ):
            for index, type in enumerate(collection):
                if type.TypeName() == name:
                    del collection[index]
                    break

    def close(self) -> None:
        for db in self._databases:
            db.close()

    def __repr__(self) -> str:
        return (
            f"<cache databases={len(self._databases)} "
            f"namespaces={len(self._namespaces)}>"
        )
