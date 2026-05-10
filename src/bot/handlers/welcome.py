from __future__ import annotations
import asyncio
from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest
from html import escape

from ...utils.config import load_env, load_settings
from ...utils.logger import get

log = get(__name__)
router = Router(name="welcome")


def setup() -> Router:
    env = load_env()
    cfg = load_settings().get("welcome", {})

    @router.message(F.new_chat_members)
    async def on_join(msg: Message, bot: Bot):
        if not cfg.get("enabled", True): return
        if msg.chat.id != env.group_id: return
        delay = int(cfg.get("delete_after_sec", 30))
        template = cfg.get("text") or "Привет, {name}!"
        for u in msg.new_chat_members or []:
            if u.is_bot: continue
            name = f'<a href="tg://user?id={u.id}">{escape(u.full_name or "друг")}</a>'
            try:
                sent = await bot.send_message(
                    chat_id=msg.chat.id,
                    text=template.format(name=name),
                    parse_mode="HTML",
                    message_thread_id=msg.message_thread_id,
                    disable_notification=True,
                )
            except TelegramBadRequest as e:
                log.warning("welcome send fail: %s", e); continue
            asyncio.create_task(_delete_later(bot, sent.chat.id, sent.message_id, delay))
        # сервисное сообщение о входе тоже стираем
        asyncio.create_task(_delete_later(bot, msg.chat.id, msg.message_id, delay))

    return router


async def _delete_later(bot: Bot, chat_id: int, message_id: int, delay: int) -> None:
    try:
        await asyncio.sleep(max(1, delay))
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        log.debug("auto-delete fail %s/%s: %s", chat_id, message_id, e)
