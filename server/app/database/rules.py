"""Channel rule (S1-03): pure function; uses no database, network or clock."""
from collections.abc import Iterable
from typing import Literal

# Exactly the same as the status values in the table.
ALLOWED = "allowed"
EXCLUDED = "excluded"

# Channels that are never read, even if written on the allow list by mistake.
BLOCKED_CHANNELS = frozenset({"ik"})


def normalize_channel_name(name: str) -> str:
    """Strips spaces and the leading '#', converts to lower case (" #Dev " -> "dev")."""
    return name.strip().lstrip("#").strip().lower()


def channel_status(channel_name: str, allowed_channels: Iterable[str]) -> Literal["allowed", "excluded"]:
    """"allowed" if the channel is on the allow list, otherwise "excluded". A blocked or empty name is always "excluded"."""
    name = normalize_channel_name(channel_name)
    if not name or name in BLOCKED_CHANNELS:
        return EXCLUDED
    allowed = {normalize_channel_name(c) for c in allowed_channels}
    return ALLOWED if name in allowed else EXCLUDED
