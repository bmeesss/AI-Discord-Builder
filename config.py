"""Central application configuration.

Configuration is read from environment variables (or a local ``.env`` file).
Secrets are never supplied as code defaults.  Local AI is opt-in: selecting a
cloud provider never imports, starts, installs, or downloads Ollama.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from urllib.parse import urlparse

from dotenv import load_dotenv

from ai.providers.registry import CLOUD_PRESETS, SUPPORTED_PROVIDERS

load_dotenv()


VALID_AI_PROVIDERS = SUPPORTED_PROVIDERS


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(
        f"Environment variable {name} must be a boolean "
        "(true/false, yes/no, 1/0)."
    )


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer.") from exc
    if parsed < minimum:
        raise RuntimeError(
            f"Environment variable {name} must be >= {minimum}."
        )
    return parsed


# --- Discord ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# --- AI providers ---
# Provider names, API-key env vars and default models come from
# ai.providers.registry (single source of truth).  Only the selected
# provider's key is required; all cloud providers use the same OpenAI-
# compatible request shape.
AI_PROVIDER = os.getenv("AI_PROVIDER", "groq").strip().lower()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", CLOUD_PRESETS["groq"].default_model)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", CLOUD_PRESETS["openai"].default_model)
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", CLOUD_PRESETS["gemini"].default_model)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", CLOUD_PRESETS["mistral"].default_model)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL", CLOUD_PRESETS["openrouter"].default_model
)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", CLOUD_PRESETS["deepseek"].default_model)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", CLOUD_PRESETS["anthropic"].default_model)

XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_MODEL = os.getenv("XAI_MODEL", CLOUD_PRESETS["xai"].default_model)

TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
TOGETHER_MODEL = os.getenv("TOGETHER_MODEL", CLOUD_PRESETS["together"].default_model)

PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
PERPLEXITY_MODEL = os.getenv("PERPLEXITY_MODEL", CLOUD_PRESETS["perplexity"].default_model)

# Ollama has no API key.  ``LOCAL_AI_MODEL`` is accepted as a friendly alias;
# OLLAMA_MODEL remains the canonical provider setting.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
OLLAMA_MODEL = (
    os.getenv("OLLAMA_MODEL")
    or os.getenv("LOCAL_AI_MODEL")
    or "qwen3:4b"
).strip()
LOCAL_AI_MODEL = os.getenv("LOCAL_AI_MODEL", OLLAMA_MODEL).strip()
LOCAL_AI_AUTO_SETUP = _env_bool("LOCAL_AI_AUTO_SETUP", False)
LOCAL_AI_AUTO_SELECT_MODEL = _env_bool("LOCAL_AI_AUTO_SELECT_MODEL", True)
AI_REQUEST_TIMEOUT_SECONDS = _env_int("AI_REQUEST_TIMEOUT_SECONDS", 60, minimum=1)

# --- Bot gedrag ---
# Alleen leden met Administrator permissie mogen /ask gebruiken om server te bouwen.
REQUIRE_ADMIN = _env_bool("REQUIRE_ADMIN", True)

# Max aantal acties dat de AI in 1 plan mag voorstellen (veiligheidslimiet).
MAX_ACTIONS_PER_PLAN = _env_int("MAX_ACTIONS_PER_PLAN", 40, minimum=1)

# Max aantal keren dat de AI een ongeldig plan mag herstellen.
MAX_AI_RETRIES = _env_int("MAX_AI_RETRIES", 2, minimum=0)

# Hoe lang (seconden) een bevestigingsknop actief blijft voordat die verloopt.
CONFIRMATION_TIMEOUT = _env_int("CONFIRMATION_TIMEOUT", 120, minimum=1)

# --- Local setup/deployment ---
APP_ENV = os.getenv("APP_ENV", "production").strip().lower()
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
# WEB_PORT wins when set.  Otherwise the platform port is used: Render sets
# PORT (default 10000) for every web service and routes public traffic to it,
# so the health endpoints must bind there.  Local runs default to 8080.
WEB_PORT = _env_int("WEB_PORT", _env_int("PORT", 8080, minimum=1), minimum=1)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()

# --- Local JSON storage (no database) ---
# Persistence (rollback history, conversations, memories, analysis) lives in
# local JSON files inside DATA_DIR — no PostgreSQL, Supabase, SQLite or any
# other external service is involved.
DATA_DIR = os.getenv("DATA_DIR", "data").strip() or "data"

# --- Logging ---
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "logs/actions.log")


def validate_config(
    environ: dict[str, str] | None = None,
    require_discord: bool = True,
) -> None:
    """Validate configuration without revealing secret values.

    ``environ`` is injectable for tests.  ``require_discord=False`` is used by
    the setup CLI, which must be able to inspect/test local AI before a bot
    token exists.  There is deliberately no database configuration to
    validate: the bot stores everything in local JSON files.
    """

    values: Callable[[str], str | None]
    if environ is None:
        values = os.getenv
    else:
        values = environ.get

    def configured(name: str, module_default: str | None = None) -> str | None:
        if environ is not None:
            return values(name)
        return values(name) or module_default

    provider = configured("AI_PROVIDER", AI_PROVIDER) or AI_PROVIDER
    provider = provider.strip().lower()
    missing: list[str] = []

    if require_discord and not configured("DISCORD_TOKEN", DISCORD_TOKEN):
        missing.append("DISCORD_TOKEN")

    if provider not in VALID_AI_PROVIDERS:
        supported = ", ".join(sorted(VALID_AI_PROVIDERS))
        raise RuntimeError(
            f"Unknown AI_PROVIDER={provider!r}. Supported providers: {supported}."
        )

    api_key_defaults = {
        "groq": ("GROQ_API_KEY", GROQ_API_KEY),
        "openai": ("OPENAI_API_KEY", OPENAI_API_KEY),
        "gemini": ("GEMINI_API_KEY", GEMINI_API_KEY),
        "mistral": ("MISTRAL_API_KEY", MISTRAL_API_KEY),
        "openrouter": ("OPENROUTER_API_KEY", OPENROUTER_API_KEY),
        "deepseek": ("DEEPSEEK_API_KEY", DEEPSEEK_API_KEY),
        "anthropic": ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
        "xai": ("XAI_API_KEY", XAI_API_KEY),
        "together": ("TOGETHER_API_KEY", TOGETHER_API_KEY),
        "perplexity": ("PERPLEXITY_API_KEY", PERPLEXITY_API_KEY),
    }
    # Sanity: every registered cloud provider must have a key mapping (and
    # vice versa), so a new registry entry cannot silently skip validation.
    if set(api_key_defaults) != set(CLOUD_PRESETS):
        raise RuntimeError(
            "Provider API-key validation is out of sync with ai.providers.registry."
        )

    if provider in api_key_defaults:
        key_name, key_default = api_key_defaults[provider]
        if not configured(key_name, key_default):
            missing.append(key_name)
    elif provider == "ollama":
        model = (
            configured("OLLAMA_MODEL", OLLAMA_MODEL)
            or configured("LOCAL_AI_MODEL", LOCAL_AI_MODEL)
            or OLLAMA_MODEL
        )
        if not model.strip():
            missing.append("OLLAMA_MODEL")

        base_url = configured("OLLAMA_BASE_URL", OLLAMA_BASE_URL) or ""
        parsed_url = urlparse(base_url.strip())
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise RuntimeError(
                "OLLAMA_BASE_URL must be an absolute http:// or https:// URL."
            )

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill in the requested values."
        )
