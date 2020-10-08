from __future__ import annotations

from dataclasses import dataclass, field, fields, asdict
import datetime
import gzip
import hashlib
import json
from typing import Any, Dict, IO, List, Type, TypeVar
import uuid

from .types import UNKNOWN


T = TypeVar("T", bound="BaseRecipe")


@dataclass
class BaseRecipe:
    categories: List[str] = field(default_factory=list)
    cook_time: str = ""
    created: str = field(default_factory=lambda: str(datetime.datetime.utcnow())[0:19])
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
    def from_file(cls: Type[T], data: IO[bytes]) -> T:
        return cls.from_dict(json.loads(gzip.open(data).read()))

    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        return cls(**data)

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

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"<{self}>"
