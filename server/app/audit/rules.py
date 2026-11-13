"""Audit rules (S2-04): pure functions; use no database, network or clock."""
import re
from collections import Counter
from collections.abc import Collection, Mapping

from ..filters.types import PERSONAL_KINDS, SECRET_KINDS

# The kinds counted on the screen (security.masked): secrets and personal data, never names (decision N3).
SCREEN_KINDS = frozenset(SECRET_KINDS + PERSONAL_KINDS)

# Reason codes of the gateway steps (API contract 11); the login codes are written by app/accounts/login.py.
GATEWAY_REASON_CODES = frozenset({
    "UNAUTHENTICATED", "NO_SLACK_ACCOUNT", "NOT_CHANNEL_MEMBER", "CHANNEL_NOT_ALLOWED",
    "NO_SLACK_DATA", "NO_MESSAGES", "PROVIDER_ERROR", "TIMEOUT",
})

# Only these steps handle messages; the count of every other step is 0.
MESSAGE_COUNT_STEPS = frozenset({"data_selection", "ask_ai"})

# The limit of the admin event list (API contract 9).
EVENT_LIST_DEFAULT = 50
EVENT_LIST_MAX = 100

_WHOLE_NUMBER = re.compile(r"[0-9]+", re.ASCII)


def gateway_event(
    step: str,
    *,
    stopped: bool,
    reason_code: str | None,
    message_count: int,
    person_id: int | None,
    channel_id: str | None,
    request_id: str,
    created_at: str,
    duration_ms: float,
) -> dict[str, object]:
    """The fields of one gateway step's event, for write_event. Only codes, counts and durations go in.

    A stopped step may have no reason code (an unexpected error: the contract has no code for it).
    """
    if reason_code is not None and not stopped:
        raise ValueError("A step that passed has no reason code.")
    if reason_code is not None and reason_code not in GATEWAY_REASON_CODES:
        raise ValueError("Unknown reason code.")
    if message_count < 0:
        raise ValueError("Message count cannot be negative.")
    return {
        "created_at": created_at,
        "request_id": request_id,
        "step": step,
        "decision": "stopped" if stopped else "passed",
        "duration_ms": duration_ms,
        "reason_code": reason_code,
        "channel_id": channel_id,
        "person_id": person_id,
        "message_count": message_count if step in MESSAGE_COUNT_STEPS else 0,
    }


def kind_counts(counts: Mapping[str, object], allowed: Collection[str]) -> dict[str, int]:
    """Checks per-kind counts (kind -> count) and returns them sorted by kind.

    Only kinds in `allowed` and whole counts of at least 1 (not bool) are accepted; anything else is a ValueError.
    The error never names a kind or a count, so it can be logged.
    """
    if not isinstance(counts, Mapping):
        raise ValueError("Counts must be an object of kinds.")
    for kind, count in counts.items():
        if kind not in allowed:
            raise ValueError("Unknown kind in counts.")
        if type(count) is not int or count < 1:
            raise ValueError("Counts must be whole numbers of at least 1.")
    return dict(sorted(counts.items()))


def add_counts(*counts: Mapping[str, int]) -> dict[str, int]:
    """The per-kind sum of several count mappings, sorted by kind, without kinds of count 0."""
    total: Counter[str] = Counter()
    for item in counts:
        total.update(item)
    return {kind: total[kind] for kind in sorted(total) if total[kind] > 0}


def screen_masked(kinds: Mapping[str, int]) -> int:
    """security.masked: the secrets and personal data of a per-kind count; names (person) never count (N3)."""
    return sum(count for kind, count in kinds.items() if kind in SCREEN_KINDS)


def parse_event_limit(values: list[str]) -> int:
    """The `limit` query values of the event list: none -> the default; one whole number from 1 to the maximum.

    Anything else is a ValueError: only digits count, so "5.0", "+5", " 5" and "1_0" are refused too.
    """
    if not values:
        return EVENT_LIST_DEFAULT
    if len(values) != 1 or not _WHOLE_NUMBER.fullmatch(values[0]):
        raise ValueError("Invalid limit.")
    limit = int(values[0])
    if not 1 <= limit <= EVENT_LIST_MAX:
        raise ValueError("Invalid limit.")
    return limit
