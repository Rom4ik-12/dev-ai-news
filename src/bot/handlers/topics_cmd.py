"""Команды для удобной привязки тем форума к именам из topics.yaml.

Использование:
  /bindtopic         — внутри темы; покажет inline-меню с именами тем, тап → биндим текущий thread
  /unbindtopic <имя> — снимает привязку
  /topics            — показывает текущие привязки (DB override + дефолты из yaml)
"""
from __future__ import annotations
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from ...utils.config import load_env
from ...utils import topics as topics_router
from ...utils.logger import get
from ...storage import db

log = get(__name__)
router = Router(name="topics_cmd")


def _can(env, uid: int) -> bool:
    return db.has_permission(uid, "settings.edit", env.owner_id)


def setup() -> Router:
    env = load_env()

    @router.message(Command("bindtopic"))
    async def cmd_bindtopic(msg: Message):
        if not msg.from_user or not _can(env, msg.from_user.id): return
        if msg.chat.id != env.group_id:
            await msg.reply("Эту команду нужно выполнять в группе бота."); return
        thread_id = msg.message_thread_id
        if thread_id is None:
            await msg.reply("Команду нужно отправить <b>внутри темы форума</b> — иначе бот не знает, какой thread_id привязывать.")
            return
        bindings = db.topic_bindings()
        rows = []
        for name in topics_router.all_names():
            mark = "✅" if bindings.get(name) == thread_id else ("🔁" if name in bindings else "")
            rows.append([InlineKeyboardButton(text=f"{mark} {name}", callback_data=f"bind:{thread_id}:{name}")])
        rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="bind:cancel")])
        await msg.reply(
            f"Привязать эту тему (<code>thread_id={thread_id}</code>) к рубрике:\n"
            f"<i>✅ — уже привязана сюда, 🔁 — привязана к другой теме (будет переопределено)</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

    @router.callback_query(F.data.startswith("bind:"))
    async def on_bind(cq: CallbackQuery):
        if not cq.from_user or not _can(env, cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True); return
        parts = cq.data.split(":", 2)
        if parts[1] == "cancel":
            try: await cq.message.delete()
            except Exception: pass
            await cq.answer(); return
        try:
            thread_id = int(parts[1]); name = parts[2]
        except (ValueError, IndexError):
            await cq.answer("Битый callback", show_alert=True); return
        if name not in topics_router.all_names():
            await cq.answer("Неизвестная тема", show_alert=True); return
        db.bind_topic(name, thread_id)
        db.audit(cq.from_user.id, "bind_topic", {"name": name, "thread_id": thread_id})
        await cq.message.edit_text(f"✅ Рубрика <b>{name}</b> привязана к thread_id <code>{thread_id}</code>.")
        await cq.answer("Готово")

    @router.message(Command("unbindtopic"))
    async def cmd_unbind(msg: Message, command: CommandObject):
        if not msg.from_user or not _can(env, msg.from_user.id): return
        name = (command.args or "").strip()
        if not name:
            await msg.reply("Использование: <code>/unbindtopic &lt;Имя&gt;</code>"); return
        if name not in topics_router.all_names():
            await msg.reply(f"Нет такой темы. Доступные: {', '.join(topics_router.all_names())}"); return
        db.unbind_topic(name)
        db.audit(msg.from_user.id, "unbind_topic", {"name": name})
        await msg.reply(f"🗑 Привязка для <b>{name}</b> снята (теперь читается из yaml).")

    @router.message(Command("topics"))
    async def cmd_topics(msg: Message):
        if not msg.from_user or not _can(env, msg.from_user.id): return
        bindings = db.topic_bindings()
        lines = ["📌 <b>Привязки тем</b>:"]
        for name in topics_router.all_names():
            tid = topics_router.thread_id_for(name)
            src = "DB" if name in bindings else ("yaml" if tid else "—")
            lines.append(f"  • <b>{name}</b>: <code>{tid if tid is not None else 'не задано'}</code> <i>({src})</i>")
        lines.append("\nЧтобы привязать — отправьте <code>/bindtopic</code> внутри нужной темы форума.")
        await msg.reply("\n".join(lines))

    return router
