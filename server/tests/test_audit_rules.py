"""S2-04: pure rules of the audit log: gateway event fields, list limit, event limit, the channel of an event."""
import re
from datetime import datetime, timedelta, timezone

import pytest

from app import settings
from app.audit import event_limit
from app.audit.event_limit import IP_LIMIT, UnauthenticatedEventLimiter
from app.audit.rules import GATEWAY_REASON_CODES, gateway_event, parse_event_limit
from app.data_selection.rules import find_target_channels, named_channel_id

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)
CHANNELS = [
    ("C_DEV", "dev", "allowed"),
    ("C_GENEL", "genel", "allowed"),
    ("C_BUGS", "bugs", "excluded"),
    ("C_IK", "ik", "blocked"),
    ("C_OLD1", "old", "allowed"),
    ("C_OLD2", "Old", "allowed"),
]


def _event(step="ask_ai", **changes):
    fields = {
        "stopped": False, "reason_code": None, "message_count": 3, "person_id": 7, "channel_id": "C_DEV",
        "request_id": "abc123", "created_at": NOW.isoformat(), "duration_ms": 1.5,
    }
    return gateway_event(step, **(fields | changes))


# --- gateway_event


def test_gateway_event_passed_has_no_reason():
    assert _event() == {
        "created_at": NOW.isoformat(), "request_id": "abc123", "step": "ask_ai", "decision": "passed",
        "duration_ms": 1.5, "reason_code": None, "channel_id": "C_DEV", "person_id": 7, "message_count": 3,
    }


def test_gateway_event_passed_with_reason_rejected():
    with pytest.raises(ValueError):
        _event(reason_code="TIMEOUT")


def test_gateway_event_stopped_keeps_reason():
    event = _event(stopped=True, reason_code="TIMEOUT")
    assert (event["decision"], event["reason_code"]) == ("stopped", "TIMEOUT")


def test_gateway_event_stopped_may_have_no_reason():
    event = _event(stopped=True)
    assert (event["decision"], event["reason_code"]) == ("stopped", None)


@pytest.mark.parametrize("code", ["SERVER_ERROR", "INVALID_CREDENTIALS", "free text"])
def test_gateway_event_unknown_reason_rejected(code):
    with pytest.raises(ValueError):
        _event(stopped=True, reason_code=code)


def test_gateway_event_negative_count_rejected():
    with pytest.raises(ValueError):
        _event(message_count=-1)


@pytest.mark.parametrize("step, expected", [
    ("identity", 0), ("authorization", 0), ("data_selection", 3), ("sanitization", 0),
    ("ask_ai", 3), ("response_check", 0), ("presentation", 0),
])
def test_gateway_event_message_count_only_for_selection_and_ai(step, expected):
    assert _event(step)["message_count"] == expected


def test_gateway_reason_codes_match_contract():
    contract = (settings.ROOT / "docs" / "api-contract.md").read_text(encoding="utf-8")
    section = contract.split("## 11. Reason codes")[1].split("## Version notes")[0]
    rows = [line for line in section.splitlines() if line.startswith("| `")]
    gateway_rows = [row for row in rows if row.split("|")[2].strip() != "login"]
    assert {code for row in gateway_rows for code in re.findall(r"`([A-Z_]+)`", row.split("|")[1])} == GATEWAY_REASON_CODES


# --- parse_event_limit


def test_parse_event_limit_default_50():
    assert parse_event_limit([]) == 50


@pytest.mark.parametrize("value, expected", [("1", 1), ("50", 50), ("100", 100)])
def test_parse_event_limit_accepts_whole_numbers(value, expected):
    assert parse_event_limit([value]) == expected


@pytest.mark.parametrize("values", [
    ["0"], ["101"], ["-1"], ["1.5"], ["abc"], [""], ["5.0"], ["+5"], [" 5"], ["5 "], ["1_0"], ["٥"], ["1e2"],
    ["9" * 5000], ["5", "6"],
])
def test_parse_event_limit_rejects(values):
    with pytest.raises(ValueError):
        parse_event_limit(values)


# --- UnauthenticatedEventLimiter


def test_event_limiter_allows_at_most_30_per_ip():
    limiter = UnauthenticatedEventLimiter()
    assert IP_LIMIT == 30
    assert [limiter.allow("ip", NOW).allowed for _ in range(31)] == [True] * 30 + [False]


def test_event_limiter_other_ip_is_separate():
    limiter = UnauthenticatedEventLimiter()
    for _ in range(31):
        limiter.allow("ip", NOW)
    assert limiter.allow("other", NOW).allowed


def test_event_limiter_counts_skipped():
    limiter = UnauthenticatedEventLimiter()
    for _ in range(30):
        assert limiter.allow("ip", NOW).skipped == 0
    assert [limiter.allow("ip", NOW).skipped for _ in range(3)] == [1, 2, 3]


def test_event_limiter_window_frees_and_forgets_skipped():
    limiter = UnauthenticatedEventLimiter()
    for _ in range(31):
        limiter.allow("ip", NOW)
    assert not limiter.allow("ip", NOW + timedelta(minutes=14, seconds=59)).allowed
    later = NOW + timedelta(minutes=15)
    assert limiter.allow("ip", later).allowed
    for _ in range(29):
        limiter.allow("ip", later)
    assert limiter.allow("ip", later).skipped == 1


def test_event_limiter_keeps_no_skipped_count_of_old_ips():
    limiter = UnauthenticatedEventLimiter()
    for _ in range(31):
        limiter.allow("old", NOW)
    limiter.allow("new", NOW + timedelta(minutes=15))
    assert limiter._skipped == {}
    assert set(limiter._by_ip) == {"new"}


def test_event_limiter_reset():
    limiter = UnauthenticatedEventLimiter()
    for _ in range(31):
        limiter.allow("ip", NOW)
    limiter.reset()
    assert limiter.allow("ip", NOW) == event_limit.EventPermit(allowed=True, skipped=0)


# --- named_channel_id


@pytest.mark.parametrize("question, expected", [
    ("#dev'i özetle", "C_DEV"),
    ("#DEV özet", "C_DEV"),
    ("#dev ve yine #dev", "C_DEV"),
    ("#bugs neler var", "C_BUGS"),
    ("#ik'i özetle", "C_IK"),
    ("#dev ve #genel", None),
    ("#dev ve #ik", None),
    ("geçen hafta neler oldu?", None),
    ("PR #17 ne durumda?", None),
    ("#yok neler var", None),
    ("#old neler var", None),
])
def test_named_channel_id(question, expected):
    assert named_channel_id(question, CHANNELS) == expected


def test_named_channel_id_empty_table():
    assert named_channel_id("#dev", []) is None


@pytest.mark.parametrize("question", ["#dev'i özetle", "#DEV özet", "#genel neler var", "#dev ve yine #dev"])
def test_named_channel_id_same_as_the_only_target_of_an_allowed_channel(question):
    result, targets = find_target_channels(question, CHANNELS)
    assert result == "ok"
    assert [named_channel_id(question, CHANNELS)] == targets
