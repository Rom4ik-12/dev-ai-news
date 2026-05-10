from __future__ import annotations
import asyncio, time, calendar
import aiohttp, feedparser
from bs4 import BeautifulSoup

from .base import FetchedItem
from ..utils.logger import get

log = get(__name__)
HEADERS = {"User-Agent": "dev.ai.news bot/1.0 (+https://github.com/)"}
TIMEOUT = aiohttp.ClientTimeout(total=20)


def _strip_html(s: str | None) -> str:
    if not s: return ""
    return BeautifulSoup(s, "lxml").get_text(" ", strip=True)


def _ts(entry) -> int | None:
    for k in ("published_parsed", "updated_parsed"):
        v = getattr(entry, k, None) or entry.get(k) if isinstance(entry, dict) else getattr(entry, k, None)
        if v:
            try: return calendar.timegm(v)
            except Exception: pass
    return None


async def fetch_feed(session: aiohttp.ClientSession, src: dict, max_items: int = 30) -> list[FetchedItem]:
    url = src.get("rss") or src.get("url")
    if not url: return []
    try:
        async with session.get(url, headers=HEADERS, timeout=TIMEOUT) as r:
            if r.status != 200:
                log.warning("RSS %s -> HTTP %s", src["id"], r.status)
                return []
            raw = await r.read()
    except Exception as e:
        log.warning("RSS %s fetch error: %s", src["id"], e)
        return []
    feed = feedparser.parse(raw)
    items = []
    for e in feed.entries[:max_items]:
        link = e.get("link") or ""
        guid = e.get("id") or e.get("guid") or link
        if not guid: continue
        items.append(FetchedItem(
            source_id=src["id"],
            source_name=src["name"],
            url=link,
            guid=guid,
            title=(e.get("title") or "").strip(),
            description=_strip_html(e.get("summary") or e.get("description") or ""),
            focus=src.get("focus"),
            lang=src.get("lang", "RU"),
            published_ts=_ts(e),
        ))
    return items


async def fetch_full_article(session: aiohttp.ClientSession, url: str, limit_chars: int = 8000) -> str | None:
    try:
        async with session.get(url, headers=HEADERS, timeout=TIMEOUT) as r:
            if r.status != 200: return None
            html = await r.text(errors="ignore")
    except Exception as e:
        log.debug("Article fetch fail %s: %s", url, e)
        return None
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        t.decompose()
    # Эвристика: <article> > main > body
    node = soup.find("article") or soup.find("main") or soup.body
    text = node.get_text(" ", strip=True) if node else soup.get_text(" ", strip=True)
    return text[:limit_chars]


async def fetch_all(sources: list[dict]) -> list[FetchedItem]:
    async with aiohttp.ClientSession() as s:
        results = await asyncio.gather(*(fetch_feed(s, src) for src in sources),
                                       return_exceptions=True)
    out: list[FetchedItem] = []
    for r in results:
        if isinstance(r, Exception):
            log.warning("source error: %s", r)
            continue
        out.extend(r)
    return out
