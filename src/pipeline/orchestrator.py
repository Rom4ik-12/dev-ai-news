from __future__ import annotations
import aiohttp, asyncio
import numpy as np

from ..utils.config import load_env, load_settings, load_sources
from ..utils import topics as topics_router
from ..utils.logger import get
from ..storage import db
from ..sources import rss
from ..ai.client import AI
from ..ai import tasks as ai_tasks

log = get(__name__)
PRIORITY_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}


def _enabled_sources(min_priority: str) -> list[dict]:
    threshold = PRIORITY_RANK.get(min_priority, 2)
    return [s for s in load_sources() if PRIORITY_RANK.get((s.get("priority") or "C"), 2) >= threshold]


def _cosine_max(v: np.ndarray, others: list[tuple[int, np.ndarray]]) -> tuple[float, int | None]:
    if not others: return 0.0, None
    M = np.stack([o for _, o in others])
    sims = M @ v
    i = int(sims.argmax())
    return float(sims[i]), others[i][0]


class Pipeline:
    """Orchestrates: fetch → triage → embed → dedup → addition → summarize → publish."""

    def __init__(self, ai: AI, publisher):
        self.env = load_env()
        self.settings = load_settings()
        self.ai = ai
        self.publisher = publisher  # callable: async (post_row, parent_post_row|None)

    async def run_once(self) -> None:
        cfg = self.settings["pipeline"]
        triage_cfg = self.settings["triage"]
        sum_cfg = self.settings["summarize"]
        add_cfg = self.settings["addition"]

        sources = _enabled_sources(cfg.get("min_priority", "B"))
        log.info("Fetching from %d sources", len(sources))
        items = await rss.fetch_all(sources)
        # Отбрасываем уже виденное и слишком старое
        max_age = cfg.get("max_age_hours", 24) * 3600
        now = db.now()
        fresh = [
            it for it in items
            if (it.published_ts is None or now - it.published_ts < max_age)
            and not db.post_exists(it.source_id, it.guid)
        ]
        log.info("Fresh items: %d / %d", len(fresh), len(items))
        if not fresh: return

        # Триаж по дешёвой модели на title+desc
        scores = await asyncio.gather(*(
            ai_tasks.triage_score(self.ai, it.title, it.description, triage_cfg["preview_chars"])
            for it in fresh
        ))
        passed = [(it, s) for it, s in zip(fresh, scores) if s >= triage_cfg["min_score"]]
        passed.sort(key=lambda x: -x[1])
        passed = passed[: cfg.get("max_posts_per_cycle", 20)]
        log.info("Triage passed: %d", len(passed))
        if not passed: return

        # Запоминаем в БД (status=pending, без summary), скачиваем полные тексты, делаем эмбеддинги
        async with aiohttp.ClientSession() as session:
            full_texts = await asyncio.gather(*(
                rss.fetch_full_article(session, it.url) for it, _ in passed
            ))

        post_ids: list[int] = []
        for (it, score), full in zip(passed, full_texts):
            pid = db.insert_post(it.source_id, it.guid, it.url, it.title,
                                 full or it.description, it.focus)
            db.update_post(pid, score=score)
            post_ids.append(pid)

        # Эмбеддинги по title + первые ~500 символов описания/тела
        embed_inputs = [
            f"{it.title}\n{(full or it.description)[:1500]}"
            for (it, _), full in zip(passed, full_texts)
        ]
        vectors = await self.ai.embed_many(embed_inputs)
        for pid, v in zip(post_ids, vectors):
            db.save_embedding(pid, v)

        # Кандидаты для дополнения — недавние опубликованные эмбеддинги
        recent = db.all_recent_embeddings(add_cfg["window_hours"])
        published_map = {p["id"]: p for p in db.recent_published(add_cfg["window_hours"])}
        recent_published = [(pid, v) for pid, v in recent if pid in published_map]

        topic_choices = topics_router.names_for_classifier()
        fb = topics_router.fallback()

        # Резюме + классификация темы + публикация (последовательно — экономнее и надёжнее)
        for (it, score), full, pid, vec in zip(passed, full_texts, post_ids, vectors):
            summary = await ai_tasks.summarize(self.ai, it.title, full or it.description,
                                               max_tokens=sum_cfg["max_tokens"])
            topic_name = await ai_tasks.classify_topic(self.ai, it.title, summary, topic_choices, fb)
            db.update_post(pid, summary=summary, focus=topic_name)

            parent = None
            sim, near_id = _cosine_max(vec, [(p, v) for p, v in recent_published if p != pid])
            if sim >= add_cfg["similarity_threshold"] and near_id:
                near = published_map[near_id]
                if await ai_tasks.is_addition(self.ai, it.title, summary,
                                              near["title"], near["summary"] or ""):
                    parent = near
                    db.update_post(pid, parent_post_id=near_id)

            try:
                await self.publisher(db.get_post(pid), parent)
            except Exception as e:
                log.exception("publish failed for post %s: %s", pid, e)
                db.update_post(pid, status="rejected")
                continue
