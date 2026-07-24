import json
import logging
import os
from abc import ABCMeta, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


class NotFound(Exception):
    pass


class Cache(metaclass=ABCMeta):
    @abstractmethod
    def is_cached(self, uid: str, hash: str) -> bool: ...

    @abstractmethod
    def store_in_cache(self, uid: str, hash: str, recipe: dict): ...

    @abstractmethod
    def read_from_cache(self, uid: str, hash: str) -> dict: ...

    @abstractmethod
    def save(self): ...


class NullCache(Cache):
    def is_cached(self, uid: str, hash: str) -> bool:
        return False

    def store_in_cache(self, uid: str, hash: str, recipe: dict):
        pass

    def read_from_cache(self, uid: str, hash: str) -> dict:
        raise NotImplementedError()

    def save(self):
        pass


class DirectoryCache(Cache):
    def __init__(self, path: str):
        self._root_path = Path(path)
        self._index = self._load_index()

    def is_cached(self, uid: str, hash: str) -> bool:
        return self.index.get(uid) == hash

    def store_in_cache(self, uid: str, hash: str, recipe: dict):
        self.index[uid] = hash

        try:
            with open(self._root_path / f"{uid}.json", "w") as outf:
                json.dump(recipe, outf)
        except Exception as e:
            logger.exception("Error encountered while writing to cache: %s", e)

    def read_from_cache(self, uid: str, hash: str) -> dict:
        if not self.is_cached(uid, hash):
            raise NotFound()

        try:
            with open(self._root_path / f"{uid}.json") as outf:
                return json.load(outf)
        except Exception as e:
            logger.exception("Error encountered while loading from cache: %s", e)
            return {}

    @property
    def index(self) -> dict[str, str]:
        return self._index

    def _load_index(self) -> dict[str, str]:
        index_path = self._root_path / "index.json"

        if not os.path.isfile(index_path):
            return {}

        try:
            with open(index_path) as inf:
                return json.load(inf)
        except Exception as e:
            logger.exception("Error encountered while loading cache index: %s", e)
            return {}

    def save(self):
        try:
            with open(self._root_path / "index.json", "w") as outf:
                json.dump(self.index, outf)
        except Exception as e:
            logger.exception("Error encountered while saving cache: %s", e)


class WriteOnlyDirectoryCache(DirectoryCache):
    def is_cached(self, uid: str, hash: str) -> bool:
        return False

    def read_from_cache(self, uid: str, hash: str) -> dict:
        raise NotImplementedError()
