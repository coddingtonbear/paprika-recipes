from __future__ import annotations

from dataclasses import dataclass, field, asdict
import gzip
import json
from typing import Any, Dict, IO, List, Optional

from .types import UNKNOWN


@dataclass
class Recipe:
    uid: str
    created: str
    hash: str
    name: str
    description: str
    ingredients: str
    directions: str
    notes: str
    nutritional_info: str
    prep_time: str
    cook_time: str
    total_time: str
    difficulty: str
    servings: str
    rating: int
    source: str
    source_url: str
    photo: str
    photo_large: UNKNOWN
    photo_hash: str
    image_url: str
    categories: List[UNKNOWN] = field(default_factory=list)
    photo_data: Optional[str] = None
    photos: List[UNKNOWN] = field(default_factory=list)

    @classmethod
    def from_file(cls, data: IO) -> Recipe:
        return cls.from_dict(json.loads(gzip.open(data).read()))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Recipe:
        return cls(**data)

    def as_dict(self):
        return asdict(self)

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"<{self}>"
