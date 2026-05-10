from __future__ import annotations
import time
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ...utils.config import load_env
from ...utils.logger import get
from ...storage import db

log = get(__name__)
router = Router(name="admin")
ROLES = ("user", "trusted", "moderator", "admin")  # owner назначается только через .env


def _can(perm: str, env, user_id: int) -> bool:
    return db.has_permission(user_id, perm, env.owner_id)


def setup() -> Router:
    env = load_env()

    @router.message(Command("role"))
    async def cmd_role(msg: Message, command: CommandObject):
        if not msg.from_user or not _can("roles.assign", env, msg.from_user.id): return
        # /role @user moderator   или   /role moderator (reply)
        args = (command.args or "").split()
        target_id = None; role = None
        if msg.reply_to_message and msg.reply_to_message.from_user:
            target_id = msg.reply_to_message.from_user.id
            if args: role = args[0]
        elif len(args) >= 2:
            uname = args[0].lstrip("@")
            with db.connect() as c:
                r = c.execute("SELECT user_id FROM users WHERE username=?", (uname,)).fetchone()
            if r: target_id = r["user_id"]
            role = args[1]
        if not target_id or role not in ROLES:
            await msg.reply(f"Использование: ответом на сообщение `/role <{'/'.join(ROLES)}>` или `/role @user <role>`")
            return
        db.upsert_user(target_id, None)
        db.set_role(target_id, role)
        db.audit(msg.from_user.id, "set_role", {"target": target_id, "role": role})
        await msg.reply(f"Роль пользователя {target_id} → {role}")

    @router.message(Command("mute"))
    async def cmd_mute(msg: Message, command: CommandObject):
        if not msg.from_user or not _can("mute.use", env, msg.from_user.id): return
        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            await msg.reply("Ответьте на сообщение пользователя командой `/mute <минут>`"); return
        try: minutes = int((command.args or "60").split()[0])
        except ValueError: minutes = 60
        target = msg.reply_to_message.from_user
        db.upsert_user(target.id, target.username)
        db.mute(target.id, db.now() + minutes * 60)
        db.audit(msg.from_user.id, "mute", {"target": target.id, "minutes": minutes})
        await msg.reply(f"Mute {minutes} минут для {target.full_name}")

    @router.message(Command("unmute"))
    async def cmd_unmute(msg: Message):
        if not msg.from_user or not _can("mute.use", env, msg.from_user.id): return
        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            await msg.reply("Ответьте на сообщение командой `/unmute`"); return
        target = msg.reply_to_message.from_user
        db.upsert_user(target.id, target.username); db.mute(target.id, 0)
        db.audit(msg.from_user.id, "unmute", {"target": target.id})
        await msg.reply(f"Unmute {target.full_name}")

    @router.message(Command("ban"))
    async def cmd_ban(msg: Message):
        if not msg.from_user or not _can("ban.use", env, msg.from_user.id): return
        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            await msg.reply("Ответьте на сообщение пользователя командой `/ban`"); return
        target = msg.reply_to_message.from_user
        db.upsert_user(target.id, target.username); db.ban(target.id, True)
        db.audit(msg.from_user.id, "ban", {"target": target.id})
        await msg.reply(f"Бан для {target.full_name}")

    @router.message(Command("unban"))
    async def cmd_unban(msg: Message):
        if not msg.from_user or not _can("ban.use", env, msg.from_user.id): return
        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            await msg.reply("Ответьте на сообщение пользователя"); return
        target = msg.reply_to_message.from_user
        db.upsert_user(target.id, target.username); db.ban(target.id, False)
        db.audit(msg.from_user.id, "unban", {"target": target.id})
        await msg.reply(f"Unban {target.full_name}")

    @router.message(Command("delete"))
    async def cmd_delete(msg: Message, bot):
        if not msg.from_user or not _can("delete.use", env, msg.from_user.id): return
        if not msg.reply_to_message: return
        try:
            await bot.delete_message(msg.chat.id, msg.reply_to_message.message_id)
            await msg.delete()
        except Exception as e:
            await msg.reply(f"Не удалось удалить: {e}")

    @router.message(Command("stats"))
    async def cmd_stats(msg: Message, command: CommandObject):
        if not msg.from_user or not _can("stats.view", env, msg.from_user.id): return
        try: hours = int((command.args or "24").split()[0])
        except ValueError: hours = 24
        s = db.stats(hours)
        lines = [f"📊 <b>Статистика за {hours}ч</b>",
                 f"Опубликовано: <b>{s['published']}</b>",
                 f"Q&A: <b>{s['qa']}</b> от <b>{s['active_users']}</b> пользователей",
                 f"Mute сейчас: {s['muted']}, забанено: {s['banned']}"]
        if s["per_topic"]:
            lines.append("\n<b>По темам:</b>")
            for f, n in s["per_topic"][:8]:
                lines.append(f"  • {f or '—'}: {n}")
        if s["per_source"]:
            lines.append("\n<b>По источникам:</b>")
            for sid, n in s["per_source"][:8]:
                lines.append(f"  • {sid}: {n}")
        if s["top_discussed"]:
            lines.append("\n<b>Топ обсуждаемых:</b>")
            for pid, title, n in s["top_discussed"]:
                lines.append(f"  • #{pid} ({n} вопр.) — {title[:60]}")
        if s["usage"]:
            lines.append("\n<b>AI-расход (токены):</b>")
            for u in s["usage"]:
                lines.append(f"  • {u['model']}/{u['op']}: in={u['pt']} out={u['ct']}")
        await msg.reply("\n".join(lines), parse_mode="HTML")

    @router.message(Command("whoami"))
    async def cmd_whoami(msg: Message):
        if not msg.from_user: return
        u = db.get_user(msg.from_user.id)
        role = "owner" if msg.from_user.id == env.owner_id else (u["role"] if u else "user")
        await msg.reply(f"id: <code>{msg.from_user.id}</code>\nrole: <b>{role}</b>", parse_mode="HTML")

    return router
