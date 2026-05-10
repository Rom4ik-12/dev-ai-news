from __future__ import annotations
import asyncio
import numpy as np
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..utils.config import load_env, load_settings
from ..utils.logger import get
from ..storage import db

log = get(__name__)
BASE_URL = "https://gen.pollinations.ai/v1"


class AI:
    def __init__(self):
        env = load_env()
        self.env = env
        self.settings = load_settings()
        self.client = AsyncOpenAI(base_url=BASE_URL, api_key=env.pollinations_key)
        self.main_model = env.ai_main_model
        self.embed_model = env.ai_embed_model
        self.embed_dims = env.ai_embed_dims

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10),
           retry=retry_if_exception_type(Exception))
    async def chat(self, system: str, user: str, *, op: str,
                   max_tokens: int = 400, temperature: float = 0.3,
                   model: str | None = None) -> str:
        m = model or self.main_model
        resp = await self.client.chat.completions.create(
            model=m,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = (resp.choices[0].message.content or "").strip()
        u = getattr(resp, "usage", None)
        pt = getattr(u, "prompt_tokens", 0) or 0
        ct = getattr(u, "completion_tokens", 0) or 0
        db.log_usage(m, op, pt, ct)
        return text

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10),
           retry=retry_if_exception_type(Exception))
    async def embed(self, text: str) -> np.ndarray:
        resp = await self.client.embeddings.create(
            model=self.embed_model,
            input=text[:8000],
            dimensions=self.embed_dims,
        )
        u = getattr(resp, "usage", None)
        pt = getattr(u, "prompt_tokens", 0) or 0
        db.log_usage(self.embed_model, "embed", pt, 0)
        v = np.array(resp.data[0].embedding, dtype=np.float32)
        n = np.linalg.norm(v)
        return v / n if n > 0 else v

    async def embed_many(self, texts: list[str]) -> list[np.ndarray]:
        # параллелизм скромный, чтобы не упереться в rate-limit
        sem = asyncio.Semaphore(4)
        async def one(t):
            async with sem:
                return await self.embed(t)
        return await asyncio.gather(*(one(t) for t in texts))
