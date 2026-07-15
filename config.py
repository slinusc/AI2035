"""Central configuration, loaded from environment variables.

All deploy-time settings live here so the rest of the app never reads os.environ
directly. On Heroku every value below is set as a config var.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load a local .env when present (no-op on Heroku, where vars are already set).
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def _get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _get_bool(name: str, default: bool = False) -> bool:
    value = _get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


# --- Provider selection -----------------------------------------------------

LLM_PROVIDER = (_get("LLM_PROVIDER", "openai") or "openai").lower()

OPENAI_API_KEY = _get("OPENAI_API_KEY")
# GPT-5.6 Luna is the intended default. Set the exact API model id here at deploy.
OPENAI_MODEL = _get("OPENAI_MODEL", "gpt-5.6-luna")

ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _get("ANTHROPIC_MODEL", "claude-opus-4-8")
ANTHROPIC_THINKING = _get_bool("ANTHROPIC_THINKING", False)

# Max output tokens for a single response. Anthropic needs this explicitly.
MAX_TOKENS = int(_get("MAX_TOKENS", "8192") or "8192")


# --- System prompt (components 1 + 4: Goal + Work assignment) ---------------

def _load_system_prompt() -> str:
    inline = _get("SYSTEM_PROMPT")
    if inline:
        return inline
    path = _get("SYSTEM_PROMPT_PATH", "prompts/system_prompt.md")
    prompt_path = (BASE_DIR / path).resolve()
    try:
        return prompt_path.read_text(encoding="utf-8")
    except OSError:
        return (
            "Du bist ein Assistent, der beim Modellieren positiver "
            "KI-Zukunftsszenarien bis 2035 hilft."
        )


SYSTEM_PROMPT = _load_system_prompt()


# --- Auth (required by Chainlit's persistent data layer) --------------------

APP_USERNAME = _get("APP_USERNAME", "admin")
APP_PASSWORD = _get("APP_PASSWORD")


# --- Database (Heroku Postgres) ---------------------------------------------

def _normalize_database_url(raw: str | None) -> str | None:
    """Make a Heroku DATABASE_URL usable by SQLAlchemy's async asyncpg driver.

    Heroku hands out ``postgres://…`` URLs. SQLAlchemy's async engine needs the
    ``postgresql+asyncpg://…`` scheme, and asyncpg does not understand the
    ``sslmode`` query parameter that Heroku appends, so we strip it. SSL itself
    is enabled via connect_args in app.py.
    """
    if not raw:
        return None

    url = raw
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    # Drop query params (e.g. ?sslmode=require) that asyncpg rejects.
    if "?" in url:
        url = url.split("?", 1)[0]

    return url


DATABASE_URL = _normalize_database_url(_get("DATABASE_URL"))


def _default_ssl_require() -> bool:
    """Heroku Postgres requires SSL; local dev databases usually don't."""
    if not DATABASE_URL:
        return False
    return not any(host in DATABASE_URL for host in ("localhost", "127.0.0.1"))


# Explicit override via DB_SSL, else inferred from the host.
_db_ssl_override = _get("DB_SSL")
DATABASE_SSL = (
    _get_bool("DB_SSL", False)
    if _db_ssl_override is not None
    else _default_ssl_require()
)


def validate() -> None:
    """Fail fast with a clear message if the selected provider is misconfigured."""
    if LLM_PROVIDER not in {"openai", "anthropic"}:
        raise RuntimeError(
            f"LLM_PROVIDER must be 'openai' or 'anthropic', got '{LLM_PROVIDER}'"
        )
    if LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
        raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set")
    if LLM_PROVIDER == "anthropic" and not ANTHROPIC_API_KEY:
        raise RuntimeError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
