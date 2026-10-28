"""Channel rule (S1-03, MIG-B): pure functions; use no database, network or clock.

A channel is decided by its Slack channel id only; its name never allows it (a name can be changed in Slack).
"""
import re
from collections.abc import Iterable
from typing import Literal

# Exactly the same as the status values in the table.
ALLOWED = "allowed"
EXCLUDED = "excluded"
BLOCKED = "blocked"

# Slack channel id: "C..." (public and new private) or "G..." (old private), upper case letters and digits.
# Slack channel names are always lower case, so no name matches. "_" is only for the fake ids in tests (C_DEV).
CHANNEL_ID_PATTERN = re.compile(r"[CG][A-Z0-9_]+")


def normalize_channel_name(name: str) -> str:
    """Strips spaces and the leading '#', converts to lower case (" #Dev " -> "dev"). Only for "#name" in a question."""
    return name.strip().lstrip("#").strip().lower()


def is_channel_id(value: object) -> bool:
    """Is value a Slack channel id (no spaces, no case conversion)."""
    return isinstance(value, str) and CHANNEL_ID_PATTERN.fullmatch(value) is not None


def channel_ids(values: Iterable[str]) -> frozenset[str]:
    """The valid channel ids in the list (spaces around a value are removed); other values are dropped."""
    return frozenset(v.strip() for v in values if is_channel_id(v.strip()))


def invalid_channel_values(values: Iterable[str]) -> list[str]:
    """The non-empty values in the list that are not channel ids, in order (e.g. old names "genel", "dev")."""
    result = []
    for v in values:
        value = v.strip()
        if value and not is_channel_id(value) and value not in result:
            result.append(value)
    return result


def channel_status(
    channel_id: str, allowed_channels: Iterable[str], blocked_channels: Iterable[str]
) -> Literal["allowed", "excluded", "blocked"]:
    """"blocked" if the id is on the blocked list (always wins); "allowed" if it is on the allow list; otherwise "excluded"."""
    channel_id = channel_id.strip() if isinstance(channel_id, str) else ""
    if channel_id in channel_ids(blocked_channels):
        return BLOCKED
    if is_channel_id(channel_id) and channel_id in channel_ids(allowed_channels):
        return ALLOWED
    return EXCLUDED


def blocked_list_error(blocked_channels: Iterable[str]) -> str | None:
    """Error text if the blocked list has a value that is not a channel id; the sync and seed commands stop then."""
    invalid = invalid_channel_values(blocked_channels)
    if invalid:
        return f"BLOCKED_CHANNELS takes channel IDs; invalid values: {', '.join(invalid)}"
    return None


def channel_list_warnings(allowed_channels: Iterable[str], blocked_channels: Iterable[str]) -> list[str]:
    """Warnings about the two lists. They contain only setting values (channel ids or names), never secrets."""
    allowed, blocked = list(allowed_channels), list(blocked_channels)
    warnings = []
    invalid = invalid_channel_values(allowed)
    if invalid:
        warnings.append(
            "ALLOWED_CHANNELS now takes channel IDs (e.g. C0123ABCDEF); "
            f"these values are ignored: {', '.join(invalid)}"
        )
    error = blocked_list_error(blocked)
    if error:
        warnings.append(error)
    if not channel_ids(allowed):
        warnings.append("ALLOWED_CHANNELS is empty; no channel will be read.")
    both = sorted(channel_ids(allowed) & channel_ids(blocked))
    if both:
        warnings.append(f"These channel IDs are on both lists; BLOCKED_CHANNELS wins: {', '.join(both)}")
    return warnings
