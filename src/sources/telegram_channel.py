"""Скрейпер публичного preview Telegram-канала через t.me/s/{channel}.
Без userbot/Bot API — обычный HTTP+HTML."""
from __future__ import annotations
import re, aiohttp
from dataclasses import dataclass
from bs4 import BeautifulSoup
from .rss import HEADERS, TIMEOUT
from ..utils.logger import get

log = get(__name__)


@dataclass
class ChannelPost:
    channel: str
    post_id: str          # "NewAITracker/1234"
    url: str              # https://t.me/NewAITracker/1234
    text: str
    image_url: str | None
    ts: int | None


_BG_RE = re.compile(r"background-image:\s*url\(['\"]?([^'\")]+)")


async def fetch_channel(channel: str, limit: int = 20) -> list[ChannelPost]:
    url = f"https://t.me/s/{channel}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=HEADERS, timeout=TIMEOUT) as r:
                if r.status != 200:
                    log.warning("t.me/s/%s -> HTTP %s", channel, r.status); return []
                html = await r.text()
    except Exception as e:
        log.warning("channel %s fetch error: %s", channel, e); return []
    soup = BeautifulSoup(html, "lxml")
    out: list[ChannelPost] = []
    for node in soup.select(".tgme_widget_message"):
        post_id = node.get("data-post") or ""
        if not post_id: continue
        text_el = node.select_one(".tgme_widget_message_text")
        text = text_el.get_text("\n", strip=True) if text_el else ""
        # картинка
        img_url = None
        photo = node.select_one(".tgme_widget_message_photo_wrap")
        if photo and photo.get("style"):
            m = _BG_RE.search(photo["style"])
            if m: img_url = m.group(1)
        # время
        ts = None
        t = node.select_one("time[datetime]")
        if t and t.get("datetime"):
            try:
                from datetime import datetime
                ts = int(datetime.fromisoformat(t["datetime"].replace("Z", "+00:00")).timestamp())
            except Exception: pass
        out.append(ChannelPost(
            channel=channel,
            post_id=post_id,
            url=f"https://t.me/{post_id}",
            text=text,
            image_url=img_url,
            ts=ts,
        ))
    # t.me/s отдаёт от старых к новым — оставляем последние N
    return out[-limit:]
