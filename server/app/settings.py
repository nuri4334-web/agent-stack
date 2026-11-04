"""Settings: values are read from the .env file. No secret lives in the code."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load the .env file at the repo root (server/app/settings.py -> two folders up)
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _parse_list(value: str) -> list[str]:
    return [p.strip() for p in value.split(",") if p.strip()]


def _text_or_default(value: str | None, default: str) -> str:
    """The stripped value; a missing, empty or spaces-only value gives the default."""
    return (value or "").strip() or default


def parse_bool_setting(name: str, value: str) -> bool:
    """'true' or 'false' (spaces and case ignored). Anything else, also empty, stops the program: ValueError."""
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"{name} must be true or false.")


# Slack bot token (xoxb-...). Only the sync command uses it; it is never written to any output.
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")

# Slack channel IDs (C...) the assistant reads. A channel that is not on the list is not read (default: none).
ALLOWED_CHANNELS = _parse_list(os.getenv("ALLOWED_CHANNELS", ""))

# Slack channel IDs that are never read (e.g. HR, finance). Always wins over ALLOWED_CHANNELS.
BLOCKED_CHANNELS = _parse_list(os.getenv("BLOCKED_CHANNELS", ""))

# Address(es) where the frontend runs; the browser may send requests to the server only from here.
FRONTEND_ORIGINS = _parse_list(os.getenv("FRONTEND_ORIGINS", "http://localhost:5173"))

# Secure attribute of the session cookie. false ONLY for local development over http://localhost.
SESSION_COOKIE_SECURE = parse_bool_setting("SESSION_COOKIE_SECURE", os.getenv("SESSION_COOKIE_SECURE", "true"))

# AI provider: 'gemini' or 'fake' (default: 'fake')
AI_PROVIDER = os.getenv("AI_PROVIDER", "fake").strip().lower()

# Secret Gemini API key (never written to logs, error messages or the screen)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Gemini model name (empty -> default is used) and timeout (seconds)
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_MODEL = _text_or_default(os.getenv("GEMINI_MODEL"), DEFAULT_GEMINI_MODEL)
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))
# SQLite database file. A relative path is resolved from the repo root (empty -> default is used).
DATABASE_PATH = ROOT / (os.getenv("DATABASE_PATH") or "server/agentstack.db")
