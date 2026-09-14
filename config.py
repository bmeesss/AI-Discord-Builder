"""Central application configuration.

Configuration is read from environment variables (or a local ``.env`` file).
Secrets are never supplied as code defaults.  Local AI is opt-in: selecting a
cloud provider never imports, starts, installs, or downloads Ollama.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

load_dotenv()


VALID_AI_PROVIDERS = frozenset({"groq", "openai", "ollama"})


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
AI_PROVIDER = os.getenv("AI_PROVIDER", "groq").strip().lower()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or None

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
WEB_PORT = _env_int("WEB_PORT", 8080, minimum=1)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()

# --- Database / persistence ---
# "postgres" is the recommended default for self-hosting; "supabase" remains
# supported as an optional cloud backend.  When DATABASE_BACKEND is not set
# the storage factory falls back to "supabase" only for existing deployments
# that have Supabase keys (and no DATABASE_URL) configured.
DATABASE_BACKEND = os.getenv("DATABASE_BACKEND", "").strip().lower()
DATABASE_URL = os.getenv("DATABASE_URL") or None
DB_POOL_MIN_SIZE = _env_int("DB_POOL_MIN_SIZE", 1, minimum=1)
DB_POOL_MAX_SIZE = _env_int("DB_POOL_MAX_SIZE", 10, minimum=1)
DB_MIGRATE_ON_STARTUP = _env_bool("DB_MIGRATE_ON_STARTUP", True)
SUPABASE_URL = os.getenv("SUPABASE_URL") or None
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or None

VALID_DATABASE_BACKENDS = frozenset({"postgres", "supabase"})

# Database containers (Compose) read these; they are not bot settings.
POSTGRES_USER = os.getenv("POSTGRES_USER", "discord_builder")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD") or None
POSTGRES_DB = os.getenv("POSTGRES_DB", "discord_builder")

# --- Logging ---
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "logs/actions.log")


def validate_config(
    environ: dict[str, str] | None = None,
    require_discord: bool = True,
    require_database: bool = True,
) -> None:
    """Validate configuration without revealing secret values.

    ``environ`` is injectable for tests.  ``require_discord=False`` and
    ``require_database=False`` are used by the setup CLI, which must be able
    to inspect/test local AI before bot token or database settings exist.
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

    if provider == "groq" and not configured("GROQ_API_KEY", GROQ_API_KEY):
        missing.append("GROQ_API_KEY")
    elif provider == "openai" and not configured("OPENAI_API_KEY", OPENAI_API_KEY):
        missing.append("OPENAI_API_KEY")
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

    if require_database:
        backend = (
            configured("DATABASE_BACKEND", DATABASE_BACKEND) or ""
        ).strip().lower()
        database_url = configured("DATABASE_URL", DATABASE_URL)
        supabase_url = configured("SUPABASE_URL", SUPABASE_URL)
        supabase_key = configured("SUPABASE_KEY", SUPABASE_KEY)

        if backend and backend not in VALID_DATABASE_BACKENDS:
            supported = ", ".join(sorted(VALID_DATABASE_BACKENDS))
            raise RuntimeError(
                f"Unknown DATABASE_BACKEND={backend!r}. "
                f"Supported backends: {supported}."
            )

        if not backend:
            # Same auto-detection as the storage factory: existing
            # Supabase-only deployments keep working without new settings.
            backend = (
                "supabase"
                if supabase_url and supabase_key and not database_url
                else "postgres"
            )

        if backend == "postgres":
            if not database_url:
                missing.append("DATABASE_URL")
            else:
                parsed_dsn = urlparse(database_url.strip())
                has_host = bool(parsed_dsn.hostname) or "host" in parse_qs(
                    parsed_dsn.query
                )
                if parsed_dsn.scheme not in {"postgresql", "postgres"} or not has_host:
                    raise RuntimeError(
                        "DATABASE_URL must be a valid "
                        "postgresql://user:password@host:5432/database URL."
                    )
        else:
            if not supabase_url:
                missing.append("SUPABASE_URL")
            if not supabase_key:
                missing.append("SUPABASE_KEY")

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill in the requested values."
        )
