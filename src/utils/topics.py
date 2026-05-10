from __future__ import annotations
from .config import load_topics as _raw


def cfg() -> dict:
    r = _raw()
    return {"fallback": r.get("fallback"), "topics": r.get("topics", {})}


def autopublish_topics() -> dict[str, dict]:
    return {n: t for n, t in cfg()["topics"].items() if not t.get("no_autopublish")}


def fallback() -> str | None:
    return cfg().get("fallback")


def thread_id_for(name: str | None) -> int | None:
    if not name: return None
    t = cfg()["topics"].get(name)
    return t.get("thread_id") if t else None


def names_for_classifier() -> list[tuple[str, str]]:
    """[(name, description), ...] только для тем, куда можно автопостить."""
    return [(n, t.get("description") or "") for n, t in autopublish_topics().items()]
