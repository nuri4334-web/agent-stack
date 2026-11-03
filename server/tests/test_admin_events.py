"""S2-04: the admin event list, GET /api/admin/events (API contract 9)."""
from datetime import datetime

import pytest

from app import ai, settings
from app.accounts import store
from app.audit.log import write_event
from app.database.schema import connect
from app.main import app
from tests.auth_clients import LOGIN_PATH, TEST_PASSWORD, set_session_cookie

EVENTS = "/api/admin/events"
ASK = "/api/ask"
LOGOUT = "/api/auth/logout"
TIME = "2026-11-04T09:00:00+00:00"
FIELDS = {
    "created_at", "request_id", "person", "channel", "step", "decision", "reason_code",
    "message_count", "blocked_count", "masked_count", "suspicious_count", "duration_ms",
}
UNAUTHENTICATED = {"error": {"code": "UNAUTHENTICATED", "message": "Please sign in."}}
FORBIDDEN = {"error": {"code": "FORBIDDEN", "message": "You don't have permission for this page."}}
INVALID_REQUEST = {"error": {"code": "INVALID_REQUEST", "message": "Invalid request format. See the API contract."}}
BAD_LIMITS = ["limit=0", "limit=101", "limit=-1", "limit=1.5", "limit=abc", "limit=", "limit=5.0", "limit=%2B5", "limit=5&limit=6"]


def _person_id(username):
    connection = connect(settings.DATABASE_PATH)
    try:
        return connection.execute("SELECT id FROM people WHERE username = ?", (username,)).fetchone()[0]
    finally:
        connection.close()


def _add_events(count, **fields):
    """Writes events straight to the table: no question and no login needed. Their request ids are 1, 2, 3 ... in hex."""
    connection = connect(settings.DATABASE_PATH)
    try:
        with connection:
            for number in range(1, count + 1):
                write_event(
                    connection, created_at=TIME, request_id=f"{number:x}", duration_ms=1.5,
                    **({"step": "identity", "decision": "passed"} | fields),
                )
    finally:
        connection.close()


def _set_inactive(username):
    connection = connect(settings.DATABASE_PATH)
    try:
        with connection:
            connection.execute("UPDATE people SET is_active = 0 WHERE username = ?", (username,))
    finally:
        connection.close()


def _gateway_events(body):
    return [e for e in body["events"] if e["step"] not in ("login", "logout")]


# --- Who can read it


def test_admin_gets_200_with_events(client_as):
    r = client_as("admin").get(EVENTS)
    assert r.status_code == 200
    assert [(e["step"], e["decision"], e["person"]) for e in r.json()["events"]] == [("login", "passed", "admin")]


def test_user_gets_403_forbidden(client_as):
    r = client_as("ali").get(EVENTS)
    assert r.status_code == 403
    assert r.json() == FORBIDDEN


def test_without_session_401(anonymous_client):
    r = anonymous_client().get(EVENTS)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED


def test_made_up_cookie_401(anonymous_client):
    c = anonymous_client()
    set_session_cookie(c, "0" * 43)
    assert c.get(EVENTS).status_code == 401


def test_after_logout_401(client_as):
    c = client_as("admin")
    assert c.post(LOGOUT).status_code == 204
    assert c.get(EVENTS).status_code == 401


def test_inactive_admin_with_session_401(client_as):
    c = client_as("admin")
    assert c.get(EVENTS).status_code == 200
    _set_inactive("admin")
    r = c.get(EVENTS)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED


def test_admin_deactivated_during_session_401(client_as):
    c = client_as("admin")
    connection = connect(settings.DATABASE_PATH)
    try:
        store.deactivate(connection, _person_id("admin"))
    finally:
        connection.close()
    assert c.get(EVENTS).status_code == 401


def test_role_is_checked_on_every_request(client_as):
    c = client_as("admin")
    assert c.get(EVENTS).status_code == 200
    connection = connect(settings.DATABASE_PATH)
    try:
        with connection:
            connection.execute("UPDATE people SET role = 'user' WHERE username = 'admin'")
    finally:
        connection.close()
    assert c.get(EVENTS).status_code == 403


# --- limit


def test_invalid_limit_422(client_as):
    c = client_as("admin")
    for query in BAD_LIMITS:
        r = c.get(f"{EVENTS}?{query}")
        assert r.status_code == 422, query
        assert r.json() == INVALID_REQUEST


def test_check_order_session_then_role_then_limit(client_as, anonymous_client):
    assert anonymous_client().get(f"{EVENTS}?limit=abc").status_code == 401
    assert client_as("ali").get(f"{EVENTS}?limit=abc").status_code == 403
    assert client_as("admin").get(f"{EVENTS}?limit=abc").status_code == 422


def test_default_50_and_at_most_100(client_as):
    c = client_as("admin")
    _add_events(120)
    assert len(c.get(EVENTS).json()["events"]) == 50
    assert len(c.get(f"{EVENTS}?limit=100").json()["events"]) == 100
    assert len(c.get(f"{EVENTS}?limit=1").json()["events"]) == 1
    assert c.get(f"{EVENTS}?limit=101").status_code == 422


def test_newest_first_also_with_the_same_time(client_as):
    c = client_as("admin")
    _add_events(3)
    assert [e["request_id"] for e in c.get(f"{EVENTS}?limit=3").json()["events"]] == ["3", "2", "1"]


# --- Fields


def test_exactly_the_twelve_contract_fields(client_as):
    c = client_as("admin")
    _add_events(1)
    events = c.get(EVENTS).json()["events"]
    assert len(events) == 2
    for event in events:
        assert set(event) == FIELDS


def test_all_fields_of_a_stopped_event(client_as):
    c = client_as("admin")
    _add_events(
        1, step="data_selection", decision="stopped", reason_code="CHANNEL_NOT_ALLOWED", channel_id="C0C83M051QD",
        person_id=_person_id("ali"), message_count=4, blocked_count=1, masked_count=2, suspicious_count=3,
    )
    assert c.get(f"{EVENTS}?limit=1").json()["events"] == [{
        "created_at": TIME, "request_id": "1", "person": "ali", "channel": "dev", "step": "data_selection",
        "decision": "stopped", "reason_code": "CHANNEL_NOT_ALLOWED", "message_count": 4, "blocked_count": 1,
        "masked_count": 2, "suspicious_count": 3, "duration_ms": 1.5,
    }]


def test_person_and_channel_names_of_a_question(client_as):
    ali, admin = client_as("ali"), client_as("admin")
    answer = ali.post(ASK, json={"question": "#dev'i özetle"}).json()
    events = _gateway_events(admin.get(EVENTS).json())
    assert len(events) == 7
    assert {e["request_id"] for e in events} == {answer["request_id"]}
    assert {e["person"] for e in events} == {"ali"}
    assert [e["channel"] for e in reversed(events)] == [None, None, "dev", "dev", "dev", "dev", "dev"]
    assert [e["step"] for e in events][0] == "presentation"


def test_created_at_is_utc(client_as):
    created_at = client_as("admin").get(EVENTS).json()["events"][0]["created_at"]
    assert created_at.endswith("+00:00")
    assert datetime.fromisoformat(created_at).utcoffset().total_seconds() == 0


def test_slack_sync_login_and_logout_events_are_listed(client_as):
    ali = client_as("ali")
    ali.post(LOGOUT)
    admin = client_as("admin")
    _add_events(1, step="slack_sync", decision="ok", message_count=12, channel_count=3)
    events = admin.get(EVENTS).json()["events"]
    assert [(e["step"], e["decision"], e["person"], e["channel"]) for e in events] == [
        ("slack_sync", "ok", None, None),
        ("login", "passed", "admin", None),
        ("logout", "passed", "ali", None),
        ("login", "passed", "ali", None),
    ]
    assert events[0]["message_count"] == 12


def test_failed_login_of_unknown_name_has_no_person(client_as, anonymous_client):
    typed = "TEST-nobody-name"
    anonymous_client().post(LOGIN_PATH, json={"username": typed, "password": TEST_PASSWORD})
    r = client_as("admin").get(EVENTS)
    assert r.json()["events"][-1]["person"] is None
    assert r.json()["events"][-1]["reason_code"] == "INVALID_CREDENTIALS"
    assert typed not in r.text


def test_endpoint_writes_no_event_and_never_calls_ai(client_as, sent_to_ai):
    c = client_as("admin")
    first = c.get(EVENTS).json()
    assert c.get(EVENTS).json() == first
    assert ai.fake_call_count() == 0
    assert sent_to_ai == []


def test_openapi_lists_the_answers():
    operation = app.openapi()["paths"][EVENTS]["get"]
    assert {"200", "401", "403", "422", "500"} <= set(operation["responses"])
