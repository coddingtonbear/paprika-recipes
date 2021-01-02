from __future__ import annotations


from dataclasses import dataclass, field, fields, asdict


@dataclass
class Category:
    name: str
    uid: str
    parent_uid: str = ""
    order_flag: int = 0

    def as_json(self):
        return json.dumps(self.as_dict())

    def as_dict(self):
        return asdict(self)

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"<{self}>"
