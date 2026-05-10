from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


@dataclass
class Env:
    bot_token: str
    group_id: int
    mod_topic_id: int | None
    owner_id: int
    pollinations_key: str
    ai_main_model: str
    ai_embed_model: str
    ai_embed_dims: int
    fetch_interval_min: int
    qa_rate_per_hour: int
    similarity_threshold: float
    git_auto_update: bool
    git_check_interval_min: int
    git_branch: str


def _int(v: str | None, default: int = 0) -> int:
    try: return int(v) if v else default
    except ValueError: return default


def load_env() -> Env:
    load_dotenv(ROOT / ".env")
    return Env(
        bot_token=os.getenv("BOT_TOKEN", ""),
        group_id=_int(os.getenv("GROUP_ID")),
        mod_topic_id=_int(os.getenv("MOD_TOPIC_ID")) or None,
        owner_id=_int(os.getenv("OWNER_ID")),
        pollinations_key=os.getenv("POLLINATIONS_API_KEY", ""),
        ai_main_model=os.getenv("AI_MAIN_MODEL", "gemini-fast"),
        ai_embed_model=os.getenv("AI_EMBED_MODEL", "openai-3-small"),
        ai_embed_dims=_int(os.getenv("AI_EMBED_DIMS"), 512),
        fetch_interval_min=_int(os.getenv("FETCH_INTERVAL_MIN"), 15),
        qa_rate_per_hour=_int(os.getenv("QA_RATE_PER_HOUR"), 10),
        similarity_threshold=float(os.getenv("SIMILARITY_THRESHOLD", "0.82")),
        git_auto_update=os.getenv("GIT_AUTO_UPDATE", "true").lower() == "true",
        git_check_interval_min=_int(os.getenv("GIT_CHECK_INTERVAL_MIN"), 10),
        git_branch=os.getenv("GIT_BRANCH", "main"),
    )


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8")) or {}


def load_settings() -> dict:
    return load_yaml("settings.yaml")


def load_sources() -> list[dict]:
    return load_yaml("sources.yaml").get("sources", [])


def load_topics() -> dict:
    return load_yaml("topics.yaml")


def load_channels() -> list[dict]:
    return load_yaml("channels.yaml").get("channels", [])
