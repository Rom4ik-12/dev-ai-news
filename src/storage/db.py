from __future__ import annotations
import sqlite3, json, time
from pathlib import Path
from contextlib import contextmanager
import numpy as np

from ..utils.config import DATA_DIR

DB_PATH = DATA_DIR / "bot.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    guid TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    full_text TEXT,
    focus TEXT,
    topic_id INTEGER,
    tg_chat_id INTEGER,
    tg_message_id INTEGER,
    tg_thread_id INTEGER,
    parent_post_id INTEGER REFERENCES posts(id),
    fetched_at INTEGER NOT NULL,
    published_at INTEGER,
    score INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|published|rejected|moderation
    UNIQUE(source_id, guid)
);
CREATE INDEX IF NOT EXISTS idx_posts_published ON posts(published_at);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);

CREATE TABLE IF NOT EXISTS embeddings (
    post_id INTEGER PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    vector BLOB NOT NULL,
    dims INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    role TEXT NOT NULL DEFAULT 'user',  -- owner|admin|moderator|trusted|user
    muted_until INTEGER DEFAULT 0,
    banned INTEGER DEFAULT 0,
    qa_count INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS qa_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    post_id INTEGER REFERENCES posts(id),
    question TEXT,
    answer TEXT,
    ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qa_user_ts ON qa_log(user_id, ts);

CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    model TEXT NOT NULL,
    op TEXT NOT NULL,        -- triage|summarize|qa|judge|embed
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    cost REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON ai_usage(ts);

CREATE TABLE IF NOT EXISTS channel_posts (
    post_id TEXT PRIMARY KEY,        -- "NewAITracker/123"
    channel TEXT NOT NULL,
    tg_chat_id INTEGER,
    tg_message_id INTEGER,
    published_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_bindings (
    name TEXT PRIMARY KEY,
    thread_id INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS role_perms (
    role TEXT NOT NULL,
    perm TEXT NOT NULL,
    allowed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (role, perm)
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    actor INTEGER,
    action TEXT NOT NULL,
    payload TEXT
);
"""


def init() -> None:
    with connect() as con:
        con.executescript(SCHEMA)


@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def now() -> int:
    return int(time.time())


# ---------- posts ----------

def post_exists(source_id: str, guid: str) -> bool:
    with connect() as c:
        return c.execute(
            "SELECT 1 FROM posts WHERE source_id=? AND guid=? LIMIT 1",
            (source_id, guid),
        ).fetchone() is not None


def insert_post(source_id: str, guid: str, url: str, title: str,
                full_text: str | None, focus: str | None) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO posts(source_id,guid,url,title,full_text,focus,fetched_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (source_id, guid, url, title, full_text, focus, now()),
        )
        return cur.lastrowid


def update_post_by_guid(source_id: str, guid: str, **fields) -> None:
    if not fields: return
    cols = ", ".join(f"{k}=?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE posts SET {cols} WHERE source_id=? AND guid=?",
                  (*fields.values(), source_id, guid))


def update_post(post_id: int, **fields) -> None:
    if not fields: return
    cols = ", ".join(f"{k}=?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE posts SET {cols} WHERE id=?", (*fields.values(), post_id))


def get_post(post_id: int) -> sqlite3.Row | None:
    with connect() as c:
        return c.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()


def get_post_by_message(chat_id: int, message_id: int) -> sqlite3.Row | None:
    with connect() as c:
        return c.execute(
            "SELECT * FROM posts WHERE tg_chat_id=? AND tg_message_id=?",
            (chat_id, message_id),
        ).fetchone()


def cleanup_orphans() -> int:
    """Посты со status='pending' и непустым summary — это прерванный цикл публикации.
    Помечаем как 'rejected', чтобы не загромождать БД и не путать дедуп."""
    with connect() as c:
        cur = c.execute(
            "UPDATE posts SET status='rejected' WHERE status='pending' AND summary IS NOT NULL"
        )
        return cur.rowcount


def total_published() -> int:
    with connect() as c:
        return int(c.execute("SELECT COUNT(*) n FROM posts WHERE status='published'").fetchone()["n"])


def recent_published(window_hours: int) -> list[sqlite3.Row]:
    cutoff = now() - window_hours * 3600
    with connect() as c:
        return c.execute(
            "SELECT * FROM posts WHERE status='published' AND published_at >= ?",
            (cutoff,),
        ).fetchall()


# ---------- embeddings ----------

def save_embedding(post_id: int, vector: np.ndarray) -> None:
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO embeddings(post_id,vector,dims) VALUES(?,?,?)",
            (post_id, vector.astype(np.float32).tobytes(), int(vector.shape[0])),
        )


def get_embedding(post_id: int) -> np.ndarray | None:
    with connect() as c:
        r = c.execute("SELECT vector,dims FROM embeddings WHERE post_id=?", (post_id,)).fetchone()
    if not r: return None
    return np.frombuffer(r["vector"], dtype=np.float32).copy()


def all_recent_embeddings(window_hours: int) -> list[tuple[int, np.ndarray]]:
    cutoff = now() - window_hours * 3600
    with connect() as c:
        rows = c.execute(
            "SELECT e.post_id, e.vector FROM embeddings e "
            "JOIN posts p ON p.id=e.post_id "
            "WHERE p.fetched_at >= ?",
            (cutoff,),
        ).fetchall()
    return [(r["post_id"], np.frombuffer(r["vector"], dtype=np.float32).copy()) for r in rows]


# ---------- users / roles ----------

ROLE_RANK = {"user": 0, "trusted": 1, "moderator": 2, "admin": 3, "owner": 4}


def upsert_user(user_id: int, username: str | None) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO users(user_id,username,created_at) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
            (user_id, username, now()),
        )


def get_user(user_id: int) -> sqlite3.Row | None:
    with connect() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def set_role(user_id: int, role: str) -> None:
    with connect() as c:
        c.execute("UPDATE users SET role=? WHERE user_id=?", (role, user_id))


def has_role(user_id: int, min_role: str, owner_id: int) -> bool:
    if user_id == owner_id: return True
    u = get_user(user_id)
    if not u: return False
    return ROLE_RANK.get(u["role"], 0) >= ROLE_RANK.get(min_role, 99)


def mute(user_id: int, until_ts: int) -> None:
    with connect() as c:
        c.execute("UPDATE users SET muted_until=? WHERE user_id=?", (until_ts, user_id))


def ban(user_id: int, value: bool = True) -> None:
    with connect() as c:
        c.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if value else 0, user_id))


def is_silenced(user_id: int) -> bool:
    u = get_user(user_id)
    if not u: return False
    return bool(u["banned"]) or (u["muted_until"] or 0) > now()


def qa_count_last_hour(user_id: int) -> int:
    cutoff = now() - 3600
    with connect() as c:
        r = c.execute(
            "SELECT COUNT(*) AS n FROM qa_log WHERE user_id=? AND ts>=?",
            (user_id, cutoff),
        ).fetchone()
    return int(r["n"])


def log_qa(user_id: int, post_id: int | None, q: str, a: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO qa_log(user_id,post_id,question,answer,ts) VALUES(?,?,?,?,?)",
            (user_id, post_id, q, a, now()),
        )


# ---------- usage / audit ----------

def log_usage(model: str, op: str, pt: int, ct: int, cost: float = 0.0) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO ai_usage(ts,model,op,prompt_tokens,completion_tokens,cost) "
            "VALUES(?,?,?,?,?,?)",
            (now(), model, op, pt, ct, cost),
        )


def audit(actor: int | None, action: str, payload: dict | None = None) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO audit(ts,actor,action,payload) VALUES(?,?,?,?)",
            (now(), actor, action, json.dumps(payload, ensure_ascii=False) if payload else None),
        )


# ---------- stats ----------

# ---------- channel posts ----------

def channel_post_seen(post_id: str) -> bool:
    with connect() as c:
        return c.execute("SELECT 1 FROM channel_posts WHERE post_id=?", (post_id,)).fetchone() is not None


def channel_post_save(post_id: str, channel: str, chat_id: int, message_id: int) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO channel_posts(post_id,channel,tg_chat_id,tg_message_id,published_at) VALUES(?,?,?,?,?)",
                  (post_id, channel, chat_id, message_id, now()))


# ---------- topic bindings ----------

def topic_bindings() -> dict[str, int]:
    with connect() as c:
        return {r["name"]: r["thread_id"] for r in c.execute("SELECT name, thread_id FROM topic_bindings")}


def bind_topic(name: str, thread_id: int) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO topic_bindings(name, thread_id) VALUES(?, ?)", (name, thread_id))


def unbind_topic(name: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM topic_bindings WHERE name=?", (name,))


# ---------- permissions ----------

DEFAULT_PERMS: dict[str, set[str]] = {
    "user":      set(),
    "trusted":   {"qa.bypass_ratelimit"},
    "moderator": {"qa.bypass_ratelimit", "mute.use", "delete.use", "stats.view"},
    "admin":     {"qa.bypass_ratelimit", "mute.use", "delete.use", "stats.view",
                  "ban.use", "roles.assign", "sources.manage", "settings.edit", "admin_menu"},
    "owner":     set(),  # owner всегда всё
}
ALL_PERMS = sorted({"qa.bypass_ratelimit", "mute.use", "ban.use", "delete.use",
                    "stats.view", "roles.assign", "sources.manage", "settings.edit", "admin_menu"})


def seed_perms() -> None:
    with connect() as c:
        for role, perms in DEFAULT_PERMS.items():
            for p in ALL_PERMS:
                c.execute("INSERT OR IGNORE INTO role_perms(role,perm,allowed) VALUES(?,?,?)",
                          (role, p, 1 if p in perms else 0))


def role_perms(role: str) -> dict[str, bool]:
    with connect() as c:
        rows = c.execute("SELECT perm,allowed FROM role_perms WHERE role=?", (role,)).fetchall()
    return {r["perm"]: bool(r["allowed"]) for r in rows}


def set_role_perm(role: str, perm: str, allowed: bool) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO role_perms(role,perm,allowed) VALUES(?,?,?)",
                  (role, perm, 1 if allowed else 0))


def has_permission(user_id: int, perm: str, owner_id: int) -> bool:
    if user_id == owner_id: return True
    u = get_user(user_id)
    role = u["role"] if u else "user"
    with connect() as c:
        r = c.execute("SELECT allowed FROM role_perms WHERE role=? AND perm=?", (role, perm)).fetchone()
    return bool(r["allowed"]) if r else False


def stats(window_hours: int = 24) -> dict:
    cutoff = now() - window_hours * 3600
    with connect() as c:
        published = c.execute(
            "SELECT COUNT(*) n FROM posts WHERE status='published' AND published_at>=?",
            (cutoff,),
        ).fetchone()["n"]
        per_source = c.execute(
            "SELECT source_id, COUNT(*) n FROM posts "
            "WHERE status='published' AND published_at>=? GROUP BY source_id ORDER BY n DESC",
            (cutoff,),
        ).fetchall()
        per_topic = c.execute(
            "SELECT focus, COUNT(*) n FROM posts "
            "WHERE status='published' AND published_at>=? GROUP BY focus ORDER BY n DESC",
            (cutoff,),
        ).fetchall()
        qa = c.execute("SELECT COUNT(*) n FROM qa_log WHERE ts>=?", (cutoff,)).fetchone()["n"]
        active_users = c.execute(
            "SELECT COUNT(DISTINCT user_id) n FROM qa_log WHERE ts>=?", (cutoff,),
        ).fetchone()["n"]
        usage = c.execute(
            "SELECT model, op, SUM(prompt_tokens) pt, SUM(completion_tokens) ct, SUM(cost) cost "
            "FROM ai_usage WHERE ts>=? GROUP BY model, op",
            (cutoff,),
        ).fetchall()
        muted = c.execute("SELECT COUNT(*) n FROM users WHERE muted_until>?", (now(),)).fetchone()["n"]
        banned = c.execute("SELECT COUNT(*) n FROM users WHERE banned=1").fetchone()["n"]
        top_discussed = c.execute(
            "SELECT p.id, p.title, COUNT(q.id) n FROM posts p "
            "JOIN qa_log q ON q.post_id=p.id WHERE q.ts>=? "
            "GROUP BY p.id ORDER BY n DESC LIMIT 5",
            (cutoff,),
        ).fetchall()
    return dict(
        window_hours=window_hours,
        published=published,
        per_source=[(r["source_id"], r["n"]) for r in per_source],
        per_topic=[(r["focus"], r["n"]) for r in per_topic],
        qa=qa,
        active_users=active_users,
        usage=[dict(r) for r in usage],
        muted=muted, banned=banned,
        top_discussed=[(r["id"], r["title"], r["n"]) for r in top_discussed],
    )
