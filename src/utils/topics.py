from __future__ import annotations
from .config import load_topics as _raw
from ..storage import db


def cfg() -> dict:
    r = _raw()
    return {"fallback": r.get("fallback"), "topics": r.get("topics", {})}


def autopublish_topics() -> dict[str, dict]:
    return {n: t for n, t in cfg()["topics"].items() if not t.get("no_autopublish")}


def fallback() -> str | None:
    return cfg().get("fallback")


def thread_id_for(name: str | None) -> int | None:
    """DB binding имеет приоритет над thread_id из yaml."""
    if not name: return None
    bindings = db.topic_bindings()
    if name in bindings: return bindings[name]
    t = cfg()["topics"].get(name)
    return t.get("thread_id") if t else None


def all_names() -> list[str]:
    return list(cfg()["topics"].keys())


def names_for_classifier() -> list[tuple[str, str]]:
    """[(name, description), ...] только для тем, куда можно автопостить."""
    return [(n, t.get("description") or "") for n, t in autopublish_topics().items()]
