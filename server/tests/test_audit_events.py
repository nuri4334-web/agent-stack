"""S2-04: the audit events of the gateway steps (API contract 8, 11; docs/data-model.md 7)."""
import logging
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import ai, gateway, settings
from app.audit.event_limit import IP_LIMIT, UnauthenticatedEventLimiter
from app.database.schema import connect
from app.main import app
from tests.auth_clients import BASE_URL, LOGIN_PATH, TEST_PASSWORD, TEST_PERSON

ASK = "/api/ask"
ME = "/api/auth/me"
EVENTS = "/api/admin/events"
STEP_NAMES = [name for name, _ in gateway.STEPS]
DEV = "C0C83M051QD"
FIXED_NOW = datetime(2026, 11, 4, 9, 30, tzinfo=timezone.utc)
UNAUTHENTICATED = {"error": {"code": "UNAUTHENTICATED", "message": "Please sign in."}}
SERVER_ERROR = {"error": {"code": "SERVER_ERROR", "message": "An unexpected server error occurred."}}


def _query(sql, params=()):
    connection = connect(settings.DATABASE_PATH)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _write(sql, params=()):
    connection = connect(settings.DATABASE_PATH)
    try:
        with connection:
            connection.execute(sql, params)
    finally:
        connection.close()


def _steps():
    """The gateway events, oldest first: step, decision, reason, channel id, message count."""
    return _query(
        "SELECT step, decision, reason_code, channel_id, message_count FROM audit_events "
        "WHERE step NOT IN ('login', 'logout') ORDER BY id"
    )


def _insert_ik(status):
    _write("INSERT INTO channels (slack_id, name, is_private, status) VALUES ('C_IK', 'ik', 1, ?)", (status,))


def _raise_ai_error(code):
    def raise_error(instruction, data):
        raise ai.AIError(code=code, message="TEST - provider error")
    return raise_error


def _break_event_of(monkeypatch, step):
    """write_event of the gateway fails for one step, with a text that must never reach the log."""
    real = gateway.write_event

    def broken(connection, **fields):
        if fields["step"] == step:
            raise sqlite3.OperationalError("TEST - write failed")
        real(connection, **fields)

    monkeypatch.setattr(gateway, "write_event", broken)


def _client_without_raise(username="ali"):
    """A signed-in client that shows a 500 answer as an answer, not as an exception in the test."""
    c = TestClient(app, base_url=BASE_URL, raise_server_exceptions=False)
    assert c.post(LOGIN_PATH, json={"username": username, "password": TEST_PASSWORD}).status_code == 200
    return c


# --- Complete requests


def test_full_request_writes_seven_events_in_step_order(fixture_accounts, sent_to_ai):
    gateway.handle_question("#dev'i özetle", TEST_PERSON)
    assert _steps() == [
        ("identity", "passed", None, None, 0),
        ("authorization", "passed", None, DEV, 0),
        ("data_selection", "passed", None, DEV, 27),
        ("sanitization", "passed", None, DEV, 0),
        ("ask_ai", "passed", None, DEV, 27),
        ("response_check", "passed", None, DEV, 0),
        ("presentation", "passed", None, DEV, 0),
    ]
    assert [row[0] for row in _steps()] == STEP_NAMES


def test_events_have_request_id_of_the_answer_and_person_of_the_session(client_as, sent_to_ai):
    answer = client_as("ayse").post(ASK, json={"question": "#dev'i özetle"}).json()
    ayse_id = _query("SELECT id FROM people WHERE username = 'ayse'")[0][0]
    rows = _query("SELECT request_id, person_id FROM audit_events WHERE step NOT IN ('login', 'logout')")
    assert rows == [(answer["request_id"], ayse_id)] * 7


def test_event_time_is_the_given_time_in_utc_and_counts_stay_zero(fixture_accounts, sent_to_ai):
    gateway.handle_question("#dev'i özetle", TEST_PERSON, now=lambda: FIXED_NOW)
    rows = _query(
        "SELECT created_at, duration_ms, channel_count, user_count, membership_count, blocked_count, "
        "masked_count, suspicious_count FROM audit_events"
    )
    assert len(rows) == 7
    for created_at, duration_ms, *counts in rows:
        assert created_at == "2026-11-04T09:30:00+00:00"
        assert duration_ms >= 0
        assert counts == [0] * 6


def test_question_without_channel_name_has_no_channel(fixture_accounts, sent_to_ai):
    gateway.handle_question("geçen hafta neler oldu?", TEST_PERSON)
    rows = _steps()
    assert len(rows) == 7
    assert {row[3] for row in rows} == {None}
    assert [row[4] for row in rows] == [0, 0, 33, 0, 33, 0, 0]


def test_two_named_channels_have_no_channel(fixture_accounts, sent_to_ai):
    gateway.handle_question("#dev ve #genel", TEST_PERSON)
    assert {row[3] for row in _steps()} == {None}


# --- Stopped in authorization or data selection


@pytest.mark.parametrize("question", ["#ik'i özetle", "#bugs neler var", "#dev ve #ik"])
def test_channel_not_allowed_stops_in_authorization(fixture_accounts, sent_to_ai, question):
    answer = gateway.handle_question(question, TEST_PERSON)
    assert answer.status == "no_access"
    assert _steps() == [
        ("identity", "passed", None, None, 0),
        ("authorization", "stopped", "CHANNEL_NOT_ALLOWED", None, 0),
    ]
    assert sent_to_ai == []


@pytest.mark.parametrize("status", ["blocked", "excluded"])
def test_channel_row_of_a_refused_channel_is_written(fixture_accounts, sent_to_ai, status):
    _insert_ik(status)
    gateway.handle_question("#ik'i özetle", TEST_PERSON)
    assert _steps()[-1] == ("authorization", "stopped", "CHANNEL_NOT_ALLOWED", "C_IK", 0)


def test_no_messages_writes_three_events(fixture_accounts, sent_to_ai):
    _write("DELETE FROM messages WHERE channel_id = ?", (DEV,))
    answer = gateway.handle_question("#dev'i özetle", TEST_PERSON)
    assert (answer.status, answer.answer) == ("ok", gateway.NO_MESSAGES_ANSWER)
    assert _steps() == [
        ("identity", "passed", None, None, 0),
        ("authorization", "passed", None, DEV, 0),
        ("data_selection", "stopped", "NO_MESSAGES", DEV, 0),
    ]
    assert sent_to_ai == []


def test_no_slack_data_writes_three_events(fixture_accounts, sent_to_ai):
    for table in ("channel_memberships", "messages", "channels"):
        _write(f"DELETE FROM {table}")
    answer = gateway.handle_question("#dev'i özetle", TEST_PERSON)
    assert answer.answer == gateway.NO_MESSAGES_ANSWER
    assert _steps() == [
        ("identity", "passed", None, None, 0),
        ("authorization", "passed", None, None, 0),
        ("data_selection", "stopped", "NO_SLACK_DATA", None, 0),
    ]
    assert sent_to_ai == []


# --- AI errors and unexpected errors


@pytest.mark.parametrize("code, http, reason", [
    ("TIMEOUT", 504, "TIMEOUT"),
    ("PROVIDER_ERROR", 502, "PROVIDER_ERROR"),
    ("QUOTA_EXCEEDED", 502, "PROVIDER_ERROR"),
    ("BILLING", 502, "PROVIDER_ERROR"),
])
def test_ai_error_writes_five_events_and_keeps_502_504(client_as, monkeypatch, code, http, reason):
    monkeypatch.setattr(ai, "ask", _raise_ai_error(code))
    r = client_as("ali").post(ASK, json={"question": "#dev'i özetle"})
    assert r.status_code == http
    assert r.json()["error"]["code"] == reason
    assert _steps() == [
        ("identity", "passed", None, None, 0),
        ("authorization", "passed", None, DEV, 0),
        ("data_selection", "passed", None, DEV, 27),
        ("sanitization", "passed", None, DEV, 0),
        ("ask_ai", "stopped", reason, DEV, 27),
    ]
    assert len(_query("SELECT id FROM ai_calls")) == 1


def test_unexpected_step_error_writes_stopped_event_without_reason(client_as, monkeypatch):
    def broken(c):
        raise RuntimeError("TEST - unexpected")

    monkeypatch.setattr(gateway, "STEPS", [("identity", gateway.identity), ("sanitization", broken)])
    c = _client_without_raise()
    r = c.post(ASK, json={"question": "#dev'i özetle"})
    assert r.status_code == 500
    assert r.json() == SERVER_ERROR
    assert _steps() == [
        ("identity", "passed", None, None, 0),
        ("sanitization", "stopped", None, None, 0),
    ]


# --- Without a person or a session


def test_identity_without_person_writes_unauthenticated_event():
    gateway.handle_question("#dev'i özetle", None)
    assert _query("SELECT step, decision, reason_code, person_id, channel_id FROM audit_events") == [
        ("identity", "stopped", "UNAUTHENTICATED", None, None),
    ]


def test_ask_without_session_writes_one_identity_event(anonymous_client, sent_to_ai):
    r = anonymous_client().post(ASK, json={"question": "#dev'i özetle"})
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED
    rows = _query(
        "SELECT step, decision, reason_code, person_id, channel_id, message_count, request_id, duration_ms "
        "FROM audit_events"
    )
    assert len(rows) == 1
    assert rows[0][:6] == ("identity", "stopped", "UNAUTHENTICATED", None, None, 0)
    assert rows[0][6] and rows[0][7] >= 0
    assert sent_to_ai == []
    assert ai.fake_call_count() == 0


def test_ask_without_session_events_are_limited_per_ip(anonymous_client, sent_to_ai, caplog):
    c = anonymous_client()
    marker = "TEST-MARKER-limit-5d21"
    with caplog.at_level(logging.DEBUG, logger="agentstack"):
        answers = [c.post(ASK, json={"question": marker}) for _ in range(IP_LIMIT + 2)]
    assert {r.status_code for r in answers} == {401}
    assert all(r.json() == UNAUTHENTICATED for r in answers)
    assert _query("SELECT count(*) FROM audit_events") == [(30,)]
    assert "Unauthenticated ask events skipped (limit reached): 1" in caplog.text
    assert marker not in caplog.text
    assert "testclient" not in caplog.text


def test_skipped_events_are_logged_first_and_every_100th(caplog):
    limiter = UnauthenticatedEventLimiter()
    for _ in range(IP_LIMIT):
        limiter.allow("ip", FIXED_NOW)
    with caplog.at_level(logging.WARNING, logger="agentstack"):
        for _ in range(200):
            gateway.record_unauthenticated_ask("ip", FIXED_NOW, 0.1, limiter)
    assert [r.getMessage().split(": ")[1] for r in caplog.records] == ["1", "100", "200"]


@pytest.mark.parametrize("path", [ME, EVENTS])
def test_me_and_admin_endpoint_without_session_write_no_event(anonymous_client, path):
    assert anonymous_client().get(path).status_code == 401
    assert _query("SELECT count(*) FROM audit_events") == [(0,)]


def test_refused_body_with_session_writes_no_event(client_as):
    assert client_as("ali").post(ASK, json={"question": ""}).status_code == 422
    assert _steps() == []


# --- An event cannot be written


def test_event_write_failure_stops_request_and_ai_is_not_called(client_as, sent_to_ai, monkeypatch, caplog):
    _break_event_of(monkeypatch, "data_selection")
    c = _client_without_raise()
    with caplog.at_level(logging.ERROR, logger="agentstack"):
        r = c.post(ASK, json={"question": "#dev'i özetle"})
    assert r.status_code == 500
    assert r.json() == SERVER_ERROR
    assert sent_to_ai == []
    assert ai.fake_call_count() == 0
    assert _query("SELECT count(*) FROM ai_calls") == [(0,)]
    assert [row[0] for row in _steps()] == ["identity", "authorization"]
    request_id = _query("SELECT request_id FROM audit_events WHERE step = 'identity'")[0][0]
    assert f"Failed to write audit event (step data_selection, request {request_id}): OperationalError" in caplog.text
    assert "TEST - write failed" not in caplog.text
    assert "özetle" not in caplog.text


def test_first_event_write_failure_runs_no_other_step(fixture_accounts, sent_to_ai, monkeypatch):
    _break_event_of(monkeypatch, "identity")
    with pytest.raises(gateway.AuditWriteError):
        gateway.handle_question("#dev'i özetle", TEST_PERSON)
    assert sent_to_ai == []
    assert _steps() == []


def test_ai_event_write_failure_is_not_hidden(client_as, sent_to_ai, monkeypatch):
    _break_event_of(monkeypatch, "ask_ai")
    r = _client_without_raise().post(ASK, json={"question": "#dev'i özetle"})
    assert r.status_code == 500
    assert r.json() == SERVER_ERROR
    assert ai.FAKE_FIXED_ANSWER not in r.text


def test_event_write_failure_on_ai_error_gives_500(client_as, monkeypatch):
    _break_event_of(monkeypatch, "ask_ai")
    monkeypatch.setattr(ai, "ask", _raise_ai_error("TIMEOUT"))
    r = _client_without_raise().post(ASK, json={"question": "#dev'i özetle"})
    assert r.status_code == 500
    assert r.json() == SERVER_ERROR


def test_event_write_failure_without_session_keeps_401(anonymous_client, monkeypatch, caplog):
    _break_event_of(monkeypatch, "identity")
    with caplog.at_level(logging.ERROR, logger="agentstack"):
        r = anonymous_client().post(ASK, json={"question": "#dev'i özetle"})
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED
    assert "Failed to write audit event (step identity, request " in caplog.text
    assert "TEST - write failed" not in caplog.text


def test_database_failure_without_session_keeps_401(anonymous_client, monkeypatch):
    def broken(path):
        raise sqlite3.OperationalError("TEST - cannot open")

    monkeypatch.setattr(gateway, "connect", broken)
    assert anonymous_client().post(ASK, json={"question": "#dev"}).status_code == 401


# --- No text


def test_no_question_or_message_text_anywhere(client_as, sent_to_ai, caplog):
    marker = "TEST-MARKER-question-8c41"
    question = f"#dev'i özetle {marker}"
    ali = client_as("ali")
    admin = client_as("admin")
    with caplog.at_level(logging.DEBUG):
        assert ali.post(ASK, json={"question": question}).status_code == 200
        listed = admin.get(EVENTS, params={"limit": 100})
    assert listed.status_code == 200
    assert len([e for e in listed.json()["events"] if e["step"] not in ("login", "logout")]) == 7
    texts = [t for (t,) in _query(
        "SELECT clean_text FROM messages WHERE channel_id = ?", (DEV,),
    )]
    assert len(texts) == 27
    assert marker in sent_to_ai[0]  # the marker really travelled through the gateway
    rows = _query("SELECT * FROM audit_events") + _query("SELECT * FROM ai_calls")
    stored = " ".join(str(value) for row in rows for value in row)
    for place in (stored, listed.text, caplog.text):
        assert marker not in place
        assert question not in place
        assert ai.FAKE_FIXED_ANSWER not in place
        for text in texts:
            assert text not in place


def test_one_connection_per_question(fixture_accounts, sent_to_ai, monkeypatch):
    opened = []

    def track(path):
        opened.append(path)
        return connect(path)

    monkeypatch.setattr(gateway, "connect", track)
    gateway.handle_question("#dev'i özetle", TEST_PERSON)
    assert len(opened) == 1
    assert len(_steps()) == 7


def test_unauthenticated_event_on_a_new_database_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_PATH", tmp_path / "new.db")
    gateway.record_unauthenticated_ask("ip", FIXED_NOW, 0.1)
    assert _query("SELECT created_at FROM audit_events") == [("2026-11-04T09:30:00+00:00",)]
