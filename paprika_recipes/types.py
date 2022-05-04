from __future__ import annotations

from abc import ABCMeta, abstractmethod, abstractproperty
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Iterator

from typing_extensions import TypedDict

if TYPE_CHECKING:
    from .recipe import BaseRecipe


UNKNOWN = Any  # Used for documenting unknown API responses


@dataclass
class RemoteRecipeIdentifier:
    hash: str
    uid: str


class RecipeManager(metaclass=ABCMeta):
    def __iter__(self) -> Iterator[BaseRecipe]:
        yield from self.recipes

    @abstractproperty
    def recipes(self) -> Iterable[BaseRecipe]:
        ...

    @abstractmethod
    def count(self) -> int:
        ...


class ConfigDict(TypedDict, total=False):
    default_account: str
