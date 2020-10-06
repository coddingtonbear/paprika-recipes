from __future__ import annotations

from dataclasses import dataclass, field, asdict
import datetime
import gzip
import hashlib
import json
from typing import Any, Dict, IO, List, Optional
import uuid

from .types import UNKNOWN


@dataclass
class Recipe:
    name: str = ""
    description: str = ""
    ingredients: str = ""
    directions: str = ""
    notes: str = ""
    nutritional_info: str = ""
    prep_time: str = ""
    cook_time: str = ""
    total_time: str = ""
    difficulty: str = ""
    servings: str = ""
    rating: int = 0
    source: str = ""
    source_url: str = ""
    photo: str = ""
    photo_large: UNKNOWN = None
    photo_hash: str = ""
    image_url: str = ""
    uid: str = str(uuid.uuid4()).upper()
    created: str = str(datetime.datetime.utcnow())[0:19]
    categories: List[UNKNOWN] = field(default_factory=list)
    photo_data: Optional[str] = None
    photos: List[UNKNOWN] = field(default_factory=list)
    hash: str = hashlib.sha256(str(uuid.uuid4()).encode("utf-8")).hexdigest()

    @classmethod
    def from_file(cls, data: IO[bytes]) -> Recipe:
        return cls.from_dict(json.loads(gzip.open(data).read()))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Recipe:
        return cls(**data)

    def as_paprikarecipe(self, outf: IO[bytes]):
        with gzip.open(outf, mode="wb") as recipe_file_gz:
            recipe_file_gz.write(json.dumps(self.as_dict()).encode("utf-8"))

    def as_dict(self):
        return asdict(self)

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"<{self}>"
