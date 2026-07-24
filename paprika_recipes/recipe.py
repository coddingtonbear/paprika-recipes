from __future__ import annotations

import datetime
import gzip
import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field, fields
from typing import IO, Any, TypeVar

from .types import UNKNOWN

T = TypeVar("T", bound="BaseRecipe")


@dataclass
class BaseRecipe:
    categories: list[str] = field(default_factory=list)
    cook_time: str = ""
    created: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )
    description: str = ""
    difficulty: str = ""
    directions: str = ""
    hash: str = field(
        default_factory=lambda: hashlib.sha256(
            str(uuid.uuid4()).encode("utf-8")
        ).hexdigest()
    )
    image_url: str = ""
    ingredients: str = ""
    name: str = ""
    notes: str = ""
    nutritional_info: str = ""
    photo: str = ""
    photo_hash: str = ""
    photo_large: UNKNOWN = None
    prep_time: str = ""
    rating: int = 0
    servings: str = ""
    source: str = ""
    source_url: str = ""
    total_time: str = ""
    uid: str = field(default_factory=lambda: str(uuid.uuid4()).upper())

    @classmethod
    def get_all_fields(cls):
        return fields(cls)

    @classmethod
    def from_file(cls: type[T], data: IO[bytes]) -> T:
        return cls.from_dict(json.loads(gzip.open(data).read()))

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        # Recipes may hold fields from a different context than this
        # class (e.g. a remote recipe's `in_trash` appearing in a file
        # fed to `create-archive`); ignore fields we don't know about.
        known_fields = {field.name for field in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known_fields})

    def as_paprikarecipe(self) -> bytes:
        return gzip.compress(self.as_json().encode("utf-8"))

    def as_json(self):
        return json.dumps(self.as_dict())

    def as_dict(self):
        return asdict(self)

    def calculate_hash(self) -> str:
        fields = self.as_dict()
        fields.pop("hash", None)

        return hashlib.sha256(
            json.dumps(fields, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def update_hash(self):
        self.hash = self.calculate_hash()

    @property
    def safe_name(self):
        return self.name.replace("/", "%2F")

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"<{self}>"
