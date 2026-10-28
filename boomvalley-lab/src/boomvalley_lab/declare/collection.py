"""The one named-collection rule.

Analysis views (frozen R31) and assignment mechanisms (R35) are collections of
named things whose declaration order means nothing. The shared rule is small on
purpose; what a view or a mechanism *is* stays in its own section.

    names        non-empty strings, unique within the collection
    reserved     a collection may reserve names (e.g. the default view's name)
    order        canonical order is by name; declaration order is not meaning
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from boomvalley_lab.core.errors import DeclarationError


class Named(Protocol):
    @property
    def name(self) -> str: ...


T = TypeVar("T", bound=Named)


@dataclass(frozen=True)
class NamedCollection(Generic[T]):
    """An immutable, name-ordered collection. Build with `of`."""

    items: tuple[T, ...]

    @classmethod
    def of(
        cls, items: Iterable[T], *, what: str = "item", reserved: Iterable[str] = ()
    ) -> NamedCollection[T]:
        items = tuple(items)
        reserved = set(reserved)
        names = []
        for item in items:
            name = item.name
            if not isinstance(name, str) or not name.strip():
                raise DeclarationError(f"a {what} must have a non-empty name: {name!r}")
            if name in reserved:
                raise DeclarationError(f"{name!r} is reserved and cannot name a {what}")
            names.append(name)
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise DeclarationError(f"{what} names must be unique; repeated: {repeated}")
        return cls(tuple(sorted(items, key=lambda item: item.name)))

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.items)

    def get(self, name: str) -> T:
        for item in self.items:
            if item.name == name:
                return item
        raise DeclarationError(f"no declared item named {name!r}; declared: {list(self.names)}")

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)
