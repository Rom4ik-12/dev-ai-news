from __future__ import annotations
import asyncio, signal
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
    cleaned = db.cleanup_orphans()
    if cleaned: log.info("cleanup: marked %d orphan posts as rejected", cleaned)
    ai = AI()
    bot, dp, publisher = build_bot(ai)
    pipe = Pipeline(ai, lambda post, parent=None: publisher.publish(post, parent))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try: loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError: pass  # Windows

    async def _wait_stop():
        await stop_event.wait()
        log.info("stop signal received, shutting down gracefully")

    log.info("starting bot, pipeline, updater")
    tasks = [
        asyncio.create_task(dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())),
        asyncio.create_task(_pipeline_loop(pipe, env.fetch_interval_min)),
        asyncio.create_task(_channels_loop(publisher, env.fetch_interval_min)),
        asyncio.create_task(watch_and_restart()),
        asyncio.create_task(_wait_stop()),
    ]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in pending: t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
