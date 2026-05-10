"""Перепост постов из публичных Telegram-каналов (минуя AI-пайплайн)."""
from __future__ import annotations
import asyncio
from ..utils.config import load_channels
from ..utils.logger import get
from ..storage import db
from ..sources.telegram_channel import fetch_channel

log = get(__name__)


async def run_once(publisher) -> None:
    """publisher.publish_channel(item, target_topic, footer)"""
    chans = load_channels()
    if not chans: return
    seed_mode = db.total_published() == 0
    for c in chans:
        try:
            posts = await fetch_channel(c["channel"], c.get("fetch_limit", 20))
        except Exception as e:
            log.warning("channel %s fetch fail: %s", c["channel"], e); continue
        new = [p for p in posts if not db.channel_post_seen(p.post_id)]
        if c.get("require_image", False):
            new = [p for p in new if p.image_url]
        log.info("channel %s: %d new (of %d)%s",
                 c["channel"], len(new), len(posts), " [seed]" if seed_mode else "")
        if seed_mode:
            for p in new:
                db.channel_post_save(p.post_id, p.channel, 0, 0)  # mark seen, no real send
            continue
        for p in new:
            try:
                await publisher.publish_channel(p, c["target_topic"], c.get("footer", ""))
                await asyncio.sleep(2)  # бережём rate-limit
            except Exception as e:
                log.exception("channel publish %s failed: %s", p.post_id, e)
