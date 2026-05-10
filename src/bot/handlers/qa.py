from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import ChatType

from ...utils.config import load_env, load_settings
from ...utils.logger import get
from ...storage import db
from ...ai.client import AI
from ...ai import tasks as ai_tasks

log = get(__name__)
router = Router(name="qa")


def setup(ai: AI) -> Router:
    env = load_env()
    settings = load_settings()
    qa_cfg = settings["qa"]

    @router.message(F.reply_to_message, F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}))
    async def on_reply(msg: Message):
        if msg.chat.id != env.group_id:
            return
        replied = msg.reply_to_message
        if not replied or not replied.from_user or not replied.from_user.is_bot:
            return
        post = db.get_post_by_message(msg.chat.id, replied.message_id)
        if not post or not post["summary"]:
            log.info("reply on bot msg %s — но в БД нет поста с summary, пропускаю",
                     replied.message_id)
            return  # не наш пост или ещё без summary
        log.info("QA: user=%s post=%s qlen=%s",
                 msg.from_user.id if msg.from_user else None,
                 post["id"], len((msg.text or msg.caption or '')))
        user = msg.from_user
        if not user: return
        db.upsert_user(user.id, user.username)
        if db.is_silenced(user.id):
            return
        if not db.has_permission(user.id, "qa.bypass_ratelimit", env.owner_id) \
                and db.qa_count_last_hour(user.id) >= qa_cfg["rate_per_hour"]:
            await msg.reply("Слишком много вопросов за последний час. Попробуйте позже.")
            return
        question = (msg.text or msg.caption or "").strip()
        if len(question) < 3 or len(question) > 1000:
            return
        try:
            answer = await ai_tasks.answer_question(
                ai, post["summary"], post["title"], question,
                max_tokens=qa_cfg["max_tokens"],
            )
        except Exception as e:
            log.exception("QA failed: %s", e)
            await msg.reply("Не удалось ответить, попробуйте позже.")
            return
        sent = await msg.reply(answer)
        db.log_qa(user.id, post["id"], question, answer)
        log.info("QA user=%s post=%s -> msg=%s", user.id, post["id"], sent.message_id)

    return router
