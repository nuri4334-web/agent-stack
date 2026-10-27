"""Pure functions that turn Slack data into table rows (S1-04): use no network, database or clock."""
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from ..database.rules import channel_status

# Slack message id: exactly "10 digits . 6 digits" (same as the CHECK in the messages table).
_TS_PATTERN = re.compile(r"[0-9]{10}\.[0-9]{6}")

# Slack error codes and subtype names: lower case letters, digits and "_".
_CODE_PATTERN = re.compile(r"[a-z0-9_]{1,40}")


def is_valid_ts(ts: object) -> bool:
    """Is ts a string in exactly the "10 digits . 6 digits" format."""
    return isinstance(ts, str) and _TS_PATTERN.fullmatch(ts) is not None


def ts_to_iso(ts: str) -> str:
    """ISO 8601 UTC time from the seconds part of ts. ts is not converted to a decimal number."""
    seconds = int(ts.split(".", 1)[0])
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def oldest_ts(now: datetime, days: int) -> str:
    """conversations.history "oldest" value: `days` days before now, in "1729500000.000000" format."""
    seconds = int((now - timedelta(days=days)).timestamp())
    return f"{seconds}.000000"


def sanitize_error_code(code: object) -> str:
    """The code as is if it is only a-z, 0-9 and "_" (at most 40 characters), otherwise "unknown_error"."""
    if isinstance(code, str) and _CODE_PATTERN.fullmatch(code):
        return code
    return "unknown_error"


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and len(value.strip()) > 0


def skip_reason(message: object) -> str | None:
    """None if the message will be written; the reason (subtype name or fixed code) if skipped. Never returns message text.

    Only people's plain messages are taken: every message with a subtype is skipped.
    """
    if not isinstance(message, dict) or message.get("type") != "message":
        return "not_a_message"
    if "subtype" in message:
        subtype = message["subtype"]
        if isinstance(subtype, str) and _CODE_PATTERN.fullmatch(subtype):
            return subtype
        return "unknown_subtype"
    if not is_valid_ts(message.get("ts")):
        return "invalid_ts"
    if not _non_empty_text(message.get("user")):
        return "no_author"
    if not _non_empty_text(message.get("text")):
        return "empty_text"
    return None


def should_keep_message(message: object) -> bool:
    """Will the message be written to the database (yes if there is no skip reason)."""
    return skip_reason(message) is None


def channel_row(channel: object, allowed_channels: Iterable[str], blocked_channels: Iterable[str]) -> dict:
    """Turns a conversations.list record into a channels row; status is computed from the channel id every time."""
    if not isinstance(channel, dict):
        raise ValueError("Channel record is invalid.")
    slack_id, name = channel.get("id"), channel.get("name")
    if not _non_empty_text(slack_id) or not _non_empty_text(name):
        raise ValueError("Channel record has no id or name.")
    return {
        "slack_id": slack_id,
        "name": name,
        "is_private": 1 if channel.get("is_private") is True else 0,
        "status": channel_status(slack_id, allowed_channels, blocked_channels),
    }


def user_row(user: object) -> dict:
    """Turns a users.list record into a slack_users row; an empty name becomes None."""
    if not isinstance(user, dict) or not _non_empty_text(user.get("id")):
        raise ValueError("User record has no id.")
    slack_id = user["id"]
    profile = user.get("profile")
    if not isinstance(profile, dict):
        profile = {}
    display = profile.get("display_name")
    real = profile.get("real_name") or user.get("real_name")
    return {
        "slack_id": slack_id,
        "display_name": display if _non_empty_text(display) else None,
        "real_name": real if _non_empty_text(real) else None,
        # Slackbot's is_bot field comes as false; it is still a bot.
        "is_bot": 1 if user.get("is_bot") is True or slack_id == "USLACKBOT" else 0,
    }
