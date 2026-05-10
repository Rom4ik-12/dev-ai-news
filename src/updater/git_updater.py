from __future__ import annotations
import asyncio, os, sys, subprocess
from pathlib import Path
from ..utils.config import load_env, ROOT
from ..utils.logger import get

log = get(__name__)


def _run(*args: str) -> tuple[int, str]:
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stdout + r.stderr).strip()


def current_head() -> str:
    code, out = _run("git", "rev-parse", "HEAD")
    return out if code == 0 else ""


def _has_git() -> bool:
    return (ROOT / ".git").exists()


async def watch_and_restart() -> None:
    """Каждые N минут git fetch + сравниваем HEAD с origin/branch.
    Если новые коммиты — git pull --ff-only и os.execv для рестарта."""
    env = load_env()
    if not env.git_auto_update:
        log.info("git auto-update disabled"); return
    if not _has_git():
        log.warning("not a git repo, auto-update disabled"); return
    branch = env.git_branch
    interval = max(60, env.git_check_interval_min * 60)
    log.info("git auto-update: branch=%s every %ds", branch, interval)
    while True:
        await asyncio.sleep(interval)
        try:
            code, _ = _run("git", "fetch", "--quiet", "origin", branch)
            if code != 0: continue
            local = current_head()
            code, remote = _run("git", "rev-parse", f"origin/{branch}")
            if code != 0 or not remote or remote == local:
                continue
            log.info("update detected: %s -> %s, pulling", local[:8], remote[:8])
            # До pull смотрим, какие файлы поменяются (нужно знать про requirements.txt)
            code, diff = _run("git", "diff", "--name-only", local, remote)
            changed = set(diff.splitlines()) if code == 0 else set()
            code, out = _run("git", "pull", "--ff-only", "origin", branch)
            if code != 0:
                log.error("git pull failed: %s", out); continue
            if "requirements.txt" in changed:
                log.info("requirements.txt changed — installing")
                code, out = _run(sys.executable, "-m", "pip", "install", "-q",
                                 "-r", "requirements.txt")
                if code != 0:
                    log.error("pip install failed, restart anyway:\n%s", out)
                else:
                    log.info("pip install OK")
            log.info("restarting via os.execv")
            os.execv(sys.executable, [sys.executable, "-m", "src.main"])
        except Exception as e:
            log.exception("updater error: %s", e)
