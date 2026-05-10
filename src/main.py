from __future__ import annotations
import asyncio
from .utils import logger as L
from .utils.config import load_env
from .storage import db
from .ai.client import AI
from .bot.dispatcher import build as build_bot
from .pipeline.orchestrator import Pipeline
from .pipeline import channels as channels_pipe
from .updater.git_updater import watch_and_restart

L.setup("INFO")
log = L.get("main")


async def _pipeline_loop(pipe: Pipeline, interval_min: int) -> None:
    interval = max(60, interval_min * 60)
    await asyncio.sleep(10)
    while True:
        try: await pipe.run_once()
        except Exception as e: log.exception("pipeline cycle failed: %s", e)
        await asyncio.sleep(interval)


async def _channels_loop(publisher, interval_min: int) -> None:
    interval = max(60, interval_min * 60)
    await asyncio.sleep(20)
    while True:
        try: await channels_pipe.run_once(publisher)
        except Exception as e: log.exception("channels cycle failed: %s", e)
        await asyncio.sleep(interval)


async def main() -> None:
    env = load_env()
    if not env.bot_token or not env.group_id or not env.owner_id:
        raise SystemExit("Заполните BOT_TOKEN, GROUP_ID, OWNER_ID в .env")
    db.init(); db.seed_perms()
    ai = AI()
    bot, dp, publisher = build_bot(ai)
    pipe = Pipeline(ai, lambda post, parent=None: publisher.publish(post, parent))

    log.info("starting bot, pipeline, updater")
    await asyncio.gather(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        _pipeline_loop(pipe, env.fetch_interval_min),
        _channels_loop(publisher, env.fetch_interval_min),
        watch_and_restart(),
    )


if __name__ == "__main__":
    asyncio.run(main())
