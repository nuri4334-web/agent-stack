"""S3-08: the sanitization step (gateway step 4): question and messages masked before the AI, counters, event kinds.

Values never appear in test output: a bool is computed first and asserted with a message that names only the kind
(same rule as the S3-02b attack tests). The values come from tests/attack_samples.py (made up, contain EXAMPLE).
"""
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app import ai, gateway, settings
from app.data_selection.rules import split_suspicious
from app.data_selection.selection import people_names
from app.database.schema import connect, create_tables
from app.filters.types import FilterResult
from app.main import app
from tests import attack_samples as s
from tests.auth_clients import BASE_URL, LOGIN_PATH, TEST_PASSWORD

DEV = s.DEV_CHANNEL_ID
SERVER_ERROR = {"error": {"code": "SERVER_ERROR", "message": "An unexpected server error occurred."}}
# The secrets masked at sync in the .env message of #dev in the demo seed (secret_counts; 7 in total).
DEV_KINDS = {"aws_key": 2, "db_password": 1, "env_secret": 1, "github_token": 1, "google_key": 1, "slack_token": 1}
DEV_MASKED = sum(DEV_KINDS.values())
DEV_MESSAGES = 27
KEY_QUESTION_START = "#dev'i özetle, bu anahtar çalışmıyor: "
KEY_QUESTION = KEY_QUESTION_START + s.SLACK_TOKEN


@pytest.fixture(autouse=True)
def _reset_counter():
    ai.reset_fake_counter()


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


def _events(request_id):
    """The gateway events of one request, oldest first, with the S3-08 fields."""
    rows = _query(
        "SELECT step, decision, reason_code, message_count, masked_count, masked_kinds, alarm, suspicious_count "
        "FROM audit_events WHERE request_id = ? ORDER BY id",
        (request_id,),
    )
    return [
        {
            "step": step, "decision": decision, "reason_code": reason, "message_count": messages,
            "masked_count": masked, "masked_kinds": json.loads(kinds), "alarm": bool(alarm), "suspicious_count": suspicious,
        }
        for step, decision, reason, messages, masked, kinds, alarm, suspicious in rows
    ]


def _row(request_id, step):
    rows = [e for e in _events(request_id) if e["step"] == step]
    return rows[0] if rows else None


def _latest_request_id():
    return _query("SELECT request_id FROM audit_events WHERE step = 'identity' ORDER BY id DESC LIMIT 1")[0][0]


def _client_without_raise(username="ali"):
    """A signed-in client that shows a 500 answer as an answer, not as an exception in the test."""
    c = TestClient(app, base_url=BASE_URL, raise_server_exceptions=False)
    assert c.post(LOGIN_PATH, json={"username": username, "password": TEST_PASSWORD}).status_code == 200
    return c


def _insert_raw_dev_message():
    """A #dev message with a raw AWS key and GitHub token, written straight to the table (like a row written before
    S3-05; secret_counts stays '{}'). Newest ts, so "#dev'i özetle" selects it. Author: Ali's Slack account."""
    _write(
        "INSERT INTO messages (channel_id, ts, author_id, sent_at, clean_text) VALUES (?, ?, ?, ?, ?)",
        (DEV, "1800000000.000100", "U0CA5HH3M1V", "2027-01-15T08:00:00+00:00",
         f"eski not: {s.AWS_KEY} ve {s.GITHUB_TOKEN}"),
    )


# --- The question


def test_question_key_is_masked_sent_redacted_and_alarms(client_as, sent_to_ai):
    r = s.ask(client_as("ali"), KEY_QUESTION)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert len(sent_to_ai) == 1
    question = s.question_part(sent_to_ai[0])
    question_has_mask = question == KEY_QUESTION_START + s.REDACTED
    question_leaked = s.SLACK_TOKEN in question
    leaked_anywhere = any(s.SLACK_TOKEN in data for data in sent_to_ai)
    in_response = s.SLACK_TOKEN in r.text
    assert question_has_mask, "the question line sent to the AI must be the question with [REDACTED]"
    assert not question_leaked, "slack_token is in the question line sent to the AI"
    assert not leaked_anywhere, "slack_token is in some part of what the AI saw"
    assert not in_response, "slack_token is in the response"
    assert body["security"]["alarm"] is True
    assert body["security"]["masked"] == DEV_MASKED + 1
    row = _row(body["request_id"], "sanitization")
    assert row["masked_kinds"] == DEV_KINDS | {"slack_token": 2}
    assert (row["masked_count"], row["alarm"]) == (DEV_MASKED + 1, True)


def test_question_without_secret_is_sent_as_written(client_as, sent_to_ai):
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    assert [s.question_part(data) for data in sent_to_ai] == ["#dev'i özetle"]
    assert r.json()["security"]["alarm"] is False


# --- The messages


def test_old_raw_secret_in_message_is_masked_without_alarm(client_as, sent_to_ai):
    _insert_raw_dev_message()
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    body = r.json()
    raw = sorted({name for data in sent_to_ai for name in s.raw_shapes_in(data)})
    in_sources = any(s.AWS_KEY in m["text"] or s.GITHUB_TOKEN in m["text"] for m in body["sources"])
    question_has_mask = any(s.REDACTED in s.question_part(data) for data in sent_to_ai)
    assert not raw, f"raw secret shapes reached the AI: {raw}"
    assert not in_sources, "a raw secret is in sources"
    assert not question_has_mask, "the question had no secret"
    assert body["security"]["alarm"] is False
    assert body["security"]["masked"] == DEV_MASKED + 2
    row = _row(body["request_id"], "sanitization")
    assert row["masked_kinds"] == DEV_KINDS | {"aws_key": 3, "github_token": 2}
    assert row["alarm"] is False


def test_secrets_masked_at_sync_count_once(client_as, sent_to_ai):
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    body = r.json()
    redacted_in_messages = sum(data.count(s.REDACTED) for data in sent_to_ai)
    assert redacted_in_messages >= 1, "the .env message of #dev must go to the AI with [REDACTED]"
    assert body["security"]["masked"] == DEV_MASKED  # not counted again at question time
    row = _row(body["request_id"], "sanitization")
    assert (row["masked_kinds"], row["masked_count"], row["alarm"]) == (DEV_KINDS, DEV_MASKED, False)


def test_other_channel_without_secrets_counts_zero(client_as, sent_to_ai):
    r = s.ask(client_as("ali"), "#genel'i özetle")
    assert r.status_code == 200
    body = r.json()
    assert body["security"] == {"blocked": 0, "masked": 0, "suspicious": 0, "alarm": False}
    row = _row(body["request_id"], "sanitization")
    assert (row["masked_kinds"], row["masked_count"]) == ({}, 0)


# --- The event rows


def test_masked_kinds_sum_equals_masked_count_on_every_row(client_as, sent_to_ai, monkeypatch):
    monkeypatch.setattr(ai, "FAKE_FIXED_ANSWER", f"Use this: {s.GITHUB_TOKEN}")
    r = s.ask(client_as("ali"), KEY_QUESTION)
    assert r.status_code == 200
    events = client_as("admin").get(s.EVENTS).json()["events"]
    rows = [e for e in events if e["request_id"] == r.json()["request_id"]]
    assert len(rows) == 7
    for row in rows:
        assert sum(row["masked_kinds"].values()) == row["masked_count"], row["step"]
        assert row["alarm"] is (row["step"] == "sanitization"), row["step"]
    for row in events:
        if row["step"] in ("login", "logout"):
            assert (row["masked_kinds"], row["alarm"], row["masked_count"]) == ({}, False, 0)


def test_response_check_row_has_the_kinds_of_the_answer(client_as, sent_to_ai, monkeypatch):
    monkeypatch.setattr(ai, "FAKE_FIXED_ANSWER", f"Use this key: {s.SLACK_TOKEN}")
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    body = r.json()
    leaked = s.SLACK_TOKEN in body["answer"]
    assert not leaked, "slack_token reached the user"
    assert body["security"]["masked"] == DEV_MASKED  # the answer's second scan never counts on the screen (N2)
    assert body["security"]["alarm"] is False  # a secret in the answer is not an alarm
    row = _row(body["request_id"], "response_check")
    assert (row["masked_kinds"], row["masked_count"], row["alarm"]) == ({"slack_token": 1}, 1, False)


@pytest.mark.parametrize("account, channel", [("ali", "yonetim"), ("unlinked", "dev")], ids=["not_member", "unlinked"])
def test_no_access_masks_nothing_and_never_alarms(client_as, sent_to_ai, account, channel):
    r = s.ask(client_as(account), f"#{channel}'i özetle, anahtar: {s.SLACK_TOKEN}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "no_access"
    assert body["security"] == {"blocked": 0, "masked": 0, "suspicious": 0, "alarm": False}
    assert sent_to_ai == []
    events = _events(body["request_id"])
    assert [e["step"] for e in events] == ["identity", "authorization"]
    assert all((e["masked_kinds"], e["alarm"]) == ({}, False) for e in events)


def test_no_messages_masks_nothing_and_never_alarms(client_as, sent_to_ai):
    _write("DELETE FROM messages WHERE channel_id = ?", (DEV,))
    r = s.ask(client_as("ali"), f"#dev'i özetle, anahtar: {s.SLACK_TOKEN}")
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == gateway.NO_MESSAGES_ANSWER
    assert body["security"] == {"blocked": 0, "masked": 0, "suspicious": 0, "alarm": False}
    assert sent_to_ai == []
    events = _events(body["request_id"])
    assert [e["step"] for e in events] == ["identity", "authorization", "data_selection"]
    assert all((e["masked_kinds"], e["alarm"]) == ({}, False) for e in events)


# --- No value is kept


def test_event_list_and_database_have_no_question_value(client_as, sent_to_ai):
    r = s.ask(client_as("ali"), KEY_QUESTION)
    assert r.status_code == 200
    events_text = client_as("admin").get(s.EVENTS).text
    connection = connect(settings.DATABASE_PATH)
    try:
        stored = any(s.SLACK_TOKEN in cell for cell in s.db_text_cells(connection))
    finally:
        connection.close()
    in_events = s.SLACK_TOKEN in events_text
    assert not in_events, "slack_token is in the event list"
    assert not stored, "slack_token is stored in the database"
    question = s.question_part(sent_to_ai[0])
    question_has_mask = question == KEY_QUESTION_START + s.REDACTED
    assert question_has_mask, "the question line sent to the AI must be the question with [REDACTED]"


def test_response_has_no_secret_counts(client_as, sent_to_ai):
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    assert "secret_counts" not in r.text
    sources = r.json()["sources"]
    assert len(sources) == DEV_MESSAGES
    for source in sources:
        assert set(source) == {"id", "channel", "author", "time", "text"}


# --- The Vault (body in S3-12): counted and used without another gateway change


class _CountingVault:
    """A stand-in for the Vault of S3-12: every mask call returns one e-mail and two names (counts only)."""

    instances: list["_CountingVault"] = []

    def __init__(self):
        self.calls: list[tuple[str, ...]] = []
        _CountingVault.instances.append(self)

    def mask(self, text, people):
        self.calls.append(tuple(people))
        return FilterResult(text=text, counts={"email": 1, "person": 2})

    def restore(self, answer):
        return answer


def test_vault_counts_reach_events_but_names_not_the_screen(client_as, sent_to_ai, monkeypatch):
    monkeypatch.setattr(_CountingVault, "instances", [])
    monkeypatch.setattr(gateway, "Vault", _CountingVault)
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    body = r.json()
    assert len(_CountingVault.instances) == 1, "one Vault per request"
    vault = _CountingVault.instances[0]
    calls = 1 + 2 * DEV_MESSAGES  # the question, then the text and the author of every message
    assert len(vault.calls) == calls
    connection = connect(settings.DATABASE_PATH)
    try:
        people = people_names(connection)
    finally:
        connection.close()
    assert people
    assert set(vault.calls) == {people}
    assert body["security"]["masked"] == DEV_MASKED + calls  # e-mails count, names do not (N3)
    row = _row(body["request_id"], "sanitization")
    assert row["masked_kinds"] == DEV_KINDS | {"email": calls, "person": 2 * calls}
    assert row["masked_count"] == DEV_MASKED + 3 * calls


def test_vault_text_is_what_the_ai_sees(client_as, sent_to_ai, monkeypatch):
    class ReplacingVault(_CountingVault):
        def mask(self, text, people):
            super().mask(text, people)
            return FilterResult(text=text.replace("özetle", "PERSON_1"), counts={"person": 1})

    monkeypatch.setattr(_CountingVault, "instances", [])
    monkeypatch.setattr(gateway, "Vault", ReplacingVault)
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    assert [s.question_part(data) for data in sent_to_ai] == ["#dev'i PERSON_1"]
    assert r.json()["security"]["masked"] == DEV_MASKED


# --- Errors stop on the safe side


def test_filter_error_stops_safely(fixture_accounts, sent_to_ai, monkeypatch, caplog):
    def broken(text):
        raise RuntimeError(f"TEST - filter failed on {text}")

    monkeypatch.setattr(gateway, "mask_secrets", broken)
    c = _client_without_raise()
    with caplog.at_level(logging.DEBUG):
        r = c.post(s.ASK, json={"question": KEY_QUESTION})
    assert r.status_code == 500
    assert r.json() == SERVER_ERROR
    assert sent_to_ai == [] and ai.fake_call_count() == 0
    events = _events(_latest_request_id())
    assert [(e["step"], e["decision"], e["reason_code"]) for e in events] == [
        ("identity", "passed", None), ("authorization", "passed", None), ("data_selection", "passed", None),
        ("sanitization", "stopped", None),
    ]
    assert (events[-1]["masked_kinds"], events[-1]["alarm"], events[-1]["masked_count"]) == ({}, False, 0)
    in_log = s.SLACK_TOKEN in caplog.text or "TEST - filter failed" in caplog.text
    assert not in_log, "the error text or the value is in the log"
    assert "RuntimeError" in caplog.text


def test_ask_ai_refuses_without_sanitization(fixture_accounts, sent_to_ai, monkeypatch, caplog):
    steps = [(name, step) for name, step in gateway.STEPS if name != "sanitization"]
    monkeypatch.setattr(gateway, "STEPS", steps)
    c = _client_without_raise()
    with caplog.at_level(logging.DEBUG):
        r = c.post(s.ASK, json={"question": KEY_QUESTION})
    assert r.status_code == 500
    assert r.json() == SERVER_ERROR
    assert sent_to_ai == [] and ai.fake_call_count() == 0
    events = _events(_latest_request_id())
    assert [(e["step"], e["decision"]) for e in events][-1] == ("ask_ai", "stopped")
    in_log = s.SLACK_TOKEN in caplog.text or "özetle" in caplog.text
    assert not in_log, "the question or the value is in the log"
    assert "RuntimeError" in caplog.text


@pytest.mark.parametrize("bad", [
    '{"email":1}', '{"slack_token":0}', '{"slack_token":"1"}', '{"slack_token":1.5}', '{"slack_token":true}',
], ids=["personal_kind", "zero", "text", "fraction", "bool"])
def test_bad_secret_counts_row_stops_the_question(fixture_accounts, sent_to_ai, caplog, bad):
    """Decision N-1: a wrong secret_counts value is an error (500), never counted as 0."""
    _write("UPDATE messages SET secret_counts = ? WHERE channel_id = ? AND secret_counts != '{}'", (bad, DEV))
    assert _query("SELECT count(*) FROM messages WHERE secret_counts = ?", (bad,)) == [(1,)]
    c = _client_without_raise()
    with caplog.at_level(logging.DEBUG):
        r = c.post(s.ASK, json={"question": "#dev'i özetle"})
    assert r.status_code == 500
    assert r.json() == SERVER_ERROR
    assert sent_to_ai == [] and ai.fake_call_count() == 0
    events = _events(_latest_request_id())
    assert [(e["step"], e["decision"], e["reason_code"]) for e in events] == [
        ("identity", "passed", None), ("authorization", "passed", None), ("data_selection", "stopped", None),
    ]
    in_log = bad in caplog.text or "secret_counts" in caplog.text or "slack_token" in caplog.text
    assert not in_log, "the stored value is in the log"
    assert "ValueError" in caplog.text


# --- Suspicious messages (the detector is connected in Stage 4)


def test_suspicious_is_zero_today(client_as, sent_to_ai):
    assert gateway.SUSPICIOUS_CHECK is None
    r = s.ask(client_as("ali"), "#dev'i özetle")
    body = r.json()
    assert body["security"]["suspicious"] == 0
    assert len(body["sources"]) == DEV_MESSAGES
    assert _row(body["request_id"], "sanitization")["suspicious_count"] == 0


def test_removed_message_is_not_sent_and_not_counted(client_as, sent_to_ai, monkeypatch):
    """The Stage 4 place: a removed message is not sent, not in sources, and its counts do not count."""
    monkeypatch.setattr(gateway, "SUSPICIOUS_CHECK", lambda text: s.REDACTED in text)
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    body = r.json()
    redacted_sent = any(s.REDACTED in data for data in sent_to_ai)
    assert not redacted_sent, "the removed message was sent to the AI"
    assert len(body["sources"]) == DEV_MESSAGES - 1
    assert body["security"] == {"blocked": 0, "masked": 0, "suspicious": 1, "alarm": False}
    row = _row(body["request_id"], "sanitization")
    assert (row["suspicious_count"], row["masked_kinds"], row["masked_count"]) == (1, {}, 0)
    assert _row(body["request_id"], "ask_ai")["message_count"] == DEV_MESSAGES - 1


def test_split_suspicious():
    items = ["a", "bad 1", "b", "bad 2"]
    assert split_suspicious(items, str, None) == (items, 0)
    assert split_suspicious(items, str, lambda text: text.startswith("bad")) == (["a", "b"], 2)
    assert split_suspicious([], str, lambda text: True) == ([], 0)


# --- People names for the Vault


def test_people_names_are_non_bot_real_and_display_names():
    connection = connect(":memory:")
    try:
        create_tables(connection)
        connection.executemany(
            "INSERT INTO slack_users (slack_id, real_name, display_name, is_bot) VALUES (?, ?, ?, ?)",
            [
                ("U1", " Deniz Aydın ", "deniz", 0),
                ("U2", "Ayşe Demir", "  ", 0),
                ("U3", None, "Ali", 0),
                ("U4", "Ali", None, 0),
                ("B1", "Deploy Bot", "deploybot", 1),
            ],
        )
        assert people_names(connection) == ("Ali", "Ayşe Demir", "Deniz Aydın", "deniz")
    finally:
        connection.close()
