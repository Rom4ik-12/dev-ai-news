"""Inline-меню для админов: роли, права, статистика, источники, настройки."""
from __future__ import annotations
import yaml
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from ...utils.config import load_env, load_sources, CONFIG_DIR
from ...utils.logger import get
from ...storage import db

log = get(__name__)
router = Router(name="menu")

ROLES = ["user", "trusted", "moderator", "admin"]  # owner — только из .env
PERM_LABELS = {
    "qa.bypass_ratelimit": "Без лимита Q&A",
    "mute.use":            "Мут пользователей",
    "ban.use":             "Бан пользователей",
    "delete.use":          "Удаление сообщений",
    "stats.view":          "Просмотр статистики",
    "roles.assign":        "Назначение ролей",
    "sources.manage":      "Управление источниками",
    "settings.edit":       "Правка настроек",
    "admin_menu":          "Доступ к /admin",
}


def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=cb) for t, cb in row]
        for row in rows
    ])


def _main_menu() -> InlineKeyboardMarkup:
    return _kb([
        [("👥 Роли", "m:roles"),       ("🔐 Права", "m:perms")],
        [("📊 Статистика", "m:stats"), ("📡 Источники", "m:sources")],
        [("⚙️ Настройки", "m:settings"), ("❌ Закрыть", "m:close")],
    ])


def setup() -> Router:
    env = load_env()

    def _allowed(uid: int) -> bool:
        return db.has_permission(uid, "admin_menu", env.owner_id)

    @router.message(Command("admin"))
    async def cmd_admin(msg: Message):
        if not msg.from_user or not _allowed(msg.from_user.id): return
        await msg.reply("⚙️ <b>Админ-панель</b>\nВыберите раздел:", reply_markup=_main_menu())

    @router.callback_query(F.data.startswith("m:"))
    async def on_menu(cq: CallbackQuery):
        if not cq.from_user or not _allowed(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True); return
        action = cq.data.split(":", 1)[1]

        if action == "close":
            try: await cq.message.delete()
            except Exception: pass
            await cq.answer(); return

        if action == "back":
            await cq.message.edit_text("⚙️ <b>Админ-панель</b>\nВыберите раздел:", reply_markup=_main_menu())
            await cq.answer(); return

        if action == "roles":
            kb = _kb([[(r, f"role:{r}")] for r in ROLES] + [[("⬅️ Назад", "m:back")]])
            await cq.message.edit_text(
                "👥 <b>Роли</b>\nЧтобы выдать роль — ответьте на сообщение пользователя командой "
                "<code>/role &lt;роль&gt;</code> или <code>/role @user &lt;роль&gt;</code>.\n\n"
                "Здесь — список ролей и количество пользователей в каждой:",
                reply_markup=kb,
            )
            await cq.answer(); return

        if action == "perms":
            kb = _kb([[(r, f"perm:{r}")] for r in ROLES] + [[("⬅️ Назад", "m:back")]])
            await cq.message.edit_text(
                "🔐 <b>Права ролей</b>\nВыберите роль для настройки прав:",
                reply_markup=kb,
            )
            await cq.answer(); return

        if action == "stats":
            s = db.stats(24)
            txt = (f"📊 <b>За 24ч</b>\n"
                   f"Опубликовано: <b>{s['published']}</b>\n"
                   f"Q&A: <b>{s['qa']}</b> от <b>{s['active_users']}</b>\n"
                   f"Mute: {s['muted']} · Ban: {s['banned']}")
            if s["per_topic"]:
                txt += "\n\n<b>По темам:</b>\n" + "\n".join(f"• {f or '—'}: {n}" for f, n in s["per_topic"][:6])
            if s["usage"]:
                txt += "\n\n<b>Токены:</b>\n" + "\n".join(
                    f"• {u['model']}/{u['op']}: in={u['pt']} out={u['ct']}" for u in s["usage"][:6])
            kb = _kb([[("🔄", "m:stats"), ("⬅️ Назад", "m:back")]])
            await cq.message.edit_text(txt, reply_markup=kb)
            await cq.answer(); return

        if action == "sources":
            srcs = load_sources()
            by_prio: dict[str, int] = {}
            for s in srcs: by_prio[s.get("priority", "C")] = by_prio.get(s.get("priority", "C"), 0) + 1
            txt = (f"📡 <b>Источники</b>: {len(srcs)}\n" +
                   "\n".join(f"• Приоритет {p}: {n}" for p, n in sorted(by_prio.items())) +
                   "\n\nРедактируется в <code>config/sources.yaml</code>.")
            await cq.message.edit_text(txt, reply_markup=_kb([[("⬅️ Назад", "m:back")]]))
            await cq.answer(); return

        if action == "settings":
            text = (CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8")
            snippet = text if len(text) <= 3500 else text[:3500] + "\n…"
            await cq.message.edit_text(
                f"⚙️ <b>settings.yaml</b>\n<pre>{snippet}</pre>",
                reply_markup=_kb([[("⬅️ Назад", "m:back")]]),
            )
            await cq.answer(); return

        await cq.answer()

    @router.callback_query(F.data.startswith("role:"))
    async def on_role_info(cq: CallbackQuery):
        if not _allowed(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True); return
        role = cq.data.split(":", 1)[1]
        with db.connect() as c:
            n = c.execute("SELECT COUNT(*) n FROM users WHERE role=?", (role,)).fetchone()["n"]
            users = c.execute(
                "SELECT user_id, username FROM users WHERE role=? ORDER BY created_at DESC LIMIT 15",
                (role,)).fetchall()
        lines = [f"👥 Роль: <b>{role}</b> ({n})"]
        for u in users:
            uname = f"@{u['username']}" if u["username"] else f"id{u['user_id']}"
            lines.append(f"  • {uname}")
        await cq.message.edit_text("\n".join(lines),
                                   reply_markup=_kb([[("⬅️ Роли", "m:roles")]]))
        await cq.answer()

    @router.callback_query(F.data.startswith("perm:"))
    async def on_perm_role(cq: CallbackQuery):
        if not _allowed(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True); return
        parts = cq.data.split(":")
        # perm:<role>           — показать
        # perm:<role>:<perm>    — переключить
        role = parts[1]
        if len(parts) == 3:
            perm = parts[2]
            current = db.role_perms(role).get(perm, False)
            db.set_role_perm(role, perm, not current)
            db.audit(cq.from_user.id, "perm_toggle", {"role": role, "perm": perm, "to": not current})
        perms = db.role_perms(role)
        rows = []
        for p in db.ALL_PERMS:
            mark = "✅" if perms.get(p) else "❌"
            label = PERM_LABELS.get(p, p)
            rows.append([(f"{mark} {label}", f"perm:{role}:{p}")])
        rows.append([("⬅️ К ролям", "m:perms")])
        await cq.message.edit_text(f"🔐 Права роли <b>{role}</b>:", reply_markup=_kb(rows))
        await cq.answer()

    return router
