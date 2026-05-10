from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class FetchedItem:
    source_id: str
    source_name: str
    url: str
    guid: str
    title: str
    description: str = ""
    full_text: str | None = None
    focus: str | None = None
    lang: str = "RU"
    published_ts: int | None = None
    extra: dict = field(default_factory=dict)
