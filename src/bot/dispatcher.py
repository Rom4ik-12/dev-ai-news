from __future__ import annotations
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message

from ..utils.config import load_env
from ..utils.logger import get
from ..ai.client import AI
from .handlers import qa, admin, menu, welcome, topics_cmd
from .publisher import Publisher

log = get(__name__)


class IncomingLogger(BaseMiddleware):
    """Логирует каждое входящее сообщение в группе бота — диагностика privacy/conflict."""
    def __init__(self, group_id: int):
        self.group_id = group_id

    async def __call__(self, handler, event: Message, data):
        if event.chat and event.chat.id == self.group_id:
            log.info("incoming msg id=%s thread=%s reply_to=%s from=%s text=%r",
                     event.message_id, event.message_thread_id,
                     event.reply_to_message.message_id if event.reply_to_message else None,
                     event.from_user.id if event.from_user else None,
                     (event.text or event.caption or '')[:60])
        return await handler(event, data)


def build(ai: AI) -> tuple[Bot, Dispatcher, Publisher]:
    env = load_env()
    bot = Bot(env.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.outer_middleware(IncomingLogger(env.group_id))
    dp.include_router(welcome.setup())
    dp.include_router(topics_cmd.setup())
    dp.include_router(menu.setup())
    dp.include_router(admin.setup())
    dp.include_router(qa.setup(ai))
    publisher = Publisher(bot)
    return bot, dp, publisher
