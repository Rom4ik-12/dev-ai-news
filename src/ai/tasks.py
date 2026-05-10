"""Высокоуровневые AI-операции пайплайна."""
from __future__ import annotations
from .client import AI
from . import prompts


async def triage_score(ai: AI, title: str, desc: str, preview_chars: int = 600) -> int:
    text = f"Заголовок: {title}\nОписание: {desc[:preview_chars]}"
    out = await ai.chat(prompts.TRIAGE, text, op="triage", max_tokens=5, temperature=0.0)
    digits = "".join(ch for ch in out if ch.isdigit())
    if not digits: return 0
    try: return max(0, min(10, int(digits[:2])))
    except ValueError: return 0


async def summarize(ai: AI, title: str, body: str, max_tokens: int = 350) -> str:
    text = f"Заголовок: {title}\n\nТекст:\n{body[:6000]}"
    return await ai.chat(prompts.SUMMARIZE, text, op="summarize", max_tokens=max_tokens, temperature=0.4)


async def is_addition(ai: AI, new_title: str, new_summary: str,
                      old_title: str, old_summary: str) -> bool:
    text = (f"УЖЕ ОПУБЛИКОВАНО:\nЗаголовок: {old_title}\nКратко: {old_summary}\n\n"
            f"НОВОЕ:\nЗаголовок: {new_title}\nКратко: {new_summary}")
    out = await ai.chat(prompts.ADDITION_JUDGE, text, op="judge", max_tokens=3, temperature=0.0)
    return out.strip().upper().startswith("ДА")


async def classify_topic(ai: AI, title: str, summary: str,
                         topics: list[tuple[str, str]], fallback: str | None) -> str:
    if not topics: return fallback or ""
    listing = "\n".join(f"- {n}: {d}" for n, d in topics)
    text = f"Темы:\n{listing}\n\nНовость:\nЗаголовок: {title}\nКратко: {summary[:800]}"
    out = await ai.chat(prompts.CLASSIFY, text, op="classify", max_tokens=10, temperature=0.0)
    out = out.strip().strip('"\'`').splitlines()[0].strip()
    valid = {n for n, _ in topics}
    if out in valid: return out
    # терпимо к мусору: ищем имя темы как подстроку в ответе
    for n in valid:
        if n.lower() in out.lower(): return n
    return fallback or topics[0][0]


async def answer_question(ai: AI, post_summary: str, post_title: str,
                          question: str, max_tokens: int = 300) -> str:
    ctx = f"ПОСТ:\nЗаголовок: {post_title}\n\n{post_summary}\n\nВОПРОС: {question}"
    return await ai.chat(prompts.QA, ctx, op="qa", max_tokens=max_tokens, temperature=0.4)
