"""
config.py
Centrale configuratie, geladen uit environment variables (.env lokaal, of
Render environment variables in productie).
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Discord ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# --- AI Provider ---
# "groq" of "openai"
AI_PROVIDER = os.getenv("AI_PROVIDER", "groq").lower()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# --- Bot gedrag ---
# Alleen leden met Administrator permissie mogen /ask gebruiken om server te bouwen
REQUIRE_ADMIN = os.getenv("REQUIRE_ADMIN", "true").lower() == "true"

# Max aantal acties dat de AI in 1 plan mag voorstellen (veiligheidslimiet)
MAX_ACTIONS_PER_PLAN = int(os.getenv("MAX_ACTIONS_PER_PLAN", "40"))

# Hoe lang (seconden) een bevestigingsknop actief blijft voordat die verloopt
CONFIRMATION_TIMEOUT = int(os.getenv("CONFIRMATION_TIMEOUT", "120"))

# --- Logging ---
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "logs/actions.log")


def validate_config():
    """Controleert of verplichte config aanwezig is. Wordt aangeroepen bij opstarten."""
    missing = []
    if not DISCORD_TOKEN:
        missing.append("DISCORD_TOKEN")

    if AI_PROVIDER == "groq" and not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")
    elif AI_PROVIDER == "openai" and not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")

    if missing:
        raise RuntimeError(
            f"Ontbrekende environment variables: {', '.join(missing)}. "
            f"Zet deze in je .env bestand (lokaal) of in Render's environment settings."
        )
