from __future__ import annotations
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from ..utils.config import load_env
from ..ai.client import AI
from .handlers import qa, admin, menu, welcome, topics_cmd
from .publisher import Publisher


def build(ai: AI) -> tuple[Bot, Dispatcher, Publisher]:
    env = load_env()
    bot = Bot(env.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(welcome.setup())
    dp.include_router(topics_cmd.setup())
    dp.include_router(menu.setup())
    dp.include_router(admin.setup())
    dp.include_router(qa.setup(ai))
    publisher = Publisher(bot)
    return bot, dp, publisher
