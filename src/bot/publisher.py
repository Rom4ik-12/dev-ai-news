from __future__ import annotations
import asyncio, aiohttp
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import BufferedInputFile

from ..utils.config import load_env, load_settings, load_sources
from ..utils import topics as topics_router
from ..utils.logger import get
from ..storage import db
from ..sources.telegram_channel import ChannelPost

log = get(__name__)


def _src_name(source_id: str) -> str:
    for s in load_sources():
        if s["id"] == source_id: return s["name"]
    return source_id


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format(post, parent, settings) -> str:
    pub = settings["publish"]
    head = ""
    if parent:
        head = f"<b>{_esc(pub['addition_prefix'])}</b> «{_esc(parent['title'])}»\n\n"
    title = _esc(post["title"].strip())
    body = _esc((post["summary"] or "").strip())
    url = post["url"]
    src_name = _esc(_src_name(post["source_id"]))
    # Заголовок-гиперссылка + сноска со ссылкой на источник внизу
    return (f"{head}<b><a href=\"{url}\">{title}</a></b>\n\n"
            f"{body}\n\n"
            f"<i>Источник: <a href=\"{url}\">{src_name}</a></i>")


MIN_INTERVAL_SEC = 3.5  # > 1 msg/3s рекомендованного TG для групп


class Publisher:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.env = load_env()
        self.settings = load_settings()
        self._lock = asyncio.Lock()
        self._last_sent_at = 0.0

    async def _throttle(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            wait = MIN_INTERVAL_SEC - (now - self._last_sent_at)
            if wait > 0: await asyncio.sleep(wait)
            self._last_sent_at = asyncio.get_event_loop().time()

    async def _safe_send(self, send_fn):
        """Throttle + ловим TelegramRetryAfter с автоматическим retry (один раз)."""
        await self._throttle()
        try:
            return await send_fn()
        except TelegramRetryAfter as e:
            log.warning("flood control, sleeping %ss", e.retry_after)
            await asyncio.sleep(e.retry_after + 1)
            await self._throttle()
            return await send_fn()

    async def publish(self, post, parent=None) -> None:
        text = _format(post, parent, self.settings)
        # post["focus"] здесь = выбранное классификатором имя темы
        topic_id = topics_router.thread_id_for(post["focus"])
        try:
            msg = await self._safe_send(lambda: self.bot.send_message(
                chat_id=self.env.group_id,
                text=text,
                parse_mode=ParseMode.HTML,
                message_thread_id=topic_id,
                disable_web_page_preview=False,
                reply_to_message_id=parent["tg_message_id"] if parent and parent["tg_chat_id"] == self.env.group_id else None,
            ))
        except TelegramBadRequest as e:
            log.error("send_message failed: %s", e)
            db.update_post(post["id"], status="rejected")
            return
        db.update_post(post["id"],
                       status="published",
                       published_at=db.now(),
                       tg_chat_id=msg.chat.id,
                       tg_message_id=msg.message_id,
                       tg_thread_id=topic_id)
        db.audit(None, "publish", {"post_id": post["id"], "addition_of": parent["id"] if parent else None})

    async def publish_channel(self, item: ChannelPost, target_topic: str, footer: str) -> None:
        """Перепост из публичного TG-канала с подписью-футером."""
        topic_id = topics_router.thread_id_for(target_topic)
        text = (item.text or "").strip()
        # Telegram caption лимит = 1024 символа; режем оставив место под футер
        max_caption = 1024
        suffix = f"\n\n— <i>{footer}</i>"
        if len(text) + len(suffix) > max_caption:
            text = text[: max_caption - len(suffix) - 1] + "…"
        caption = f"{text}{suffix}"
        try:
            if item.image_url:
                # тащим файл сами — у CDN нестабильно с прямой передачей URL Telegram'у
                async with aiohttp.ClientSession() as s:
                    async with s.get(item.image_url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                        data = await r.read() if r.status == 200 else None
                if data:
                    photo = BufferedInputFile(data, filename="card.jpg")
                    msg = await self._safe_send(lambda: self.bot.send_photo(
                        self.env.group_id, photo, caption=caption,
                        parse_mode=ParseMode.HTML, message_thread_id=topic_id))
                else:
                    msg = await self._safe_send(lambda: self.bot.send_message(
                        self.env.group_id, caption, parse_mode=ParseMode.HTML,
                        message_thread_id=topic_id))
            else:
                msg = await self._safe_send(lambda: self.bot.send_message(
                    self.env.group_id, caption, parse_mode=ParseMode.HTML,
                    message_thread_id=topic_id))
        except TelegramBadRequest as e:
            log.error("publish_channel failed: %s", e); return
        db.channel_post_save(item.post_id, item.channel, msg.chat.id, msg.message_id)
        db.audit(None, "publish_channel", {"post": item.post_id, "topic": target_topic})
