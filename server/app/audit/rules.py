"""Audit rules (S2-04): pure functions; use no database, network or clock."""
import re

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
