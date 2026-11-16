"""S3-14: the masked text table. The exact data text sent to the AI is written to masked_texts before the AI call;
never a value or a Vault mapping. If it cannot be written the request stops (500) and the AI is not called.

Values never appear in test output: a bool is computed first and asserted with a message that names only the kind.
"""
import logging
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import ai, gateway, settings
from app.data_selection.rules import author_name
from app.database.masked_texts import MaskedTextWriteError, write_masked_text
from app.database.schema import connect, create_tables
from app.main import app
from tests import attack_samples as s
from tests.auth_clients import BASE_URL, LOGIN_PATH, TEST_PASSWORD, TEST_PERSON

DEV = s.DEV_CHANNEL_ID
FIXED_NOW = datetime(2026, 11, 16, 9, 30, tzinfo=timezone.utc)
SERVER_ERROR = {"error": {"code": "SERVER_ERROR", "message": "An unexpected server error occurred."}}
VALUE_QUESTION = f"#dev'i özetle, anahtar: {s.SLACK_TOKEN} iletişim: {s.EMAIL} {s.PHONE_INTL}"
VALUES = (s.SLACK_TOKEN, s.EMAIL, s.PHONE_INTL)


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


def _rows():
    """(request_id, created_at, masked_text) of every row, oldest first."""
    return _query("SELECT request_id, created_at, masked_text FROM masked_texts ORDER BY id")


def _row_count():
    return _query("SELECT count(*) FROM masked_texts")[0][0]


def _steps(request_id):
    return _query(
        "SELECT step, decision, reason_code FROM audit_events WHERE request_id = ? ORDER BY id", (request_id,),
    )


def _latest_request_id():
    return _query("SELECT request_id FROM audit_events WHERE step = 'identity' ORDER BY id DESC LIMIT 1")[0][0]


def _client_without_raise(username="ali"):
    c = TestClient(app, base_url=BASE_URL, raise_server_exceptions=False)
    assert c.post(LOGIN_PATH, json={"username": username, "password": TEST_PASSWORD}).status_code == 200
    return c


def _dev_author_names():
    rows = _query(
        "SELECT DISTINCT u.real_name, u.display_name, u.slack_id FROM messages m "
        "JOIN slack_users u ON u.slack_id = m.author_id WHERE m.channel_id = ? AND u.is_bot = 0",
        (DEV,),
    )
    return sorted({author_name(real, display, slack_id) for real, display, slack_id in rows})


# --- The writer


def test_write_masked_text_inserts_one_row_and_does_not_commit():
    connection = connect(":memory:")
    try:
        create_tables(connection)
        write_masked_text(connection, created_at="2026-11-16T09:30:00+00:00", request_id="ab12", masked_text="x")
        assert connection.in_transaction
        assert connection.execute("SELECT request_id, created_at, masked_text FROM masked_texts").fetchall() == [
            ("ab12", "2026-11-16T09:30:00+00:00", "x"),
        ]
    finally:
        connection.close()


# --- One row per question, the same text the AI saw


def test_full_question_writes_one_row_equal_to_what_ai_saw(fixture_accounts, sent_to_ai):
    answer = gateway.handle_question("#dev'i özetle", TEST_PERSON, now=lambda: FIXED_NOW)
    assert answer.status == "ok"
    assert len(sent_to_ai) == 1
    rows = _rows()
    assert len(rows) == 1
    request_id, created_at, masked_text = rows[0]
    assert request_id == answer.request_id
    assert created_at == "2026-11-16T09:30:00+00:00"
    same = masked_text == sent_to_ai[0]
    assert same, "the stored text is not exactly the text sent to the AI"


def test_row_is_committed_before_the_ai_call(fixture_accounts, monkeypatch):
    seen_at_call = []
    real = ai.ask

    def spy(instruction, data):
        rows = _query("SELECT masked_text FROM masked_texts")  # a separate connection: sees only committed rows
        seen_at_call.append(len(rows) == 1 and rows[0][0] == data)
        return real(instruction=instruction, data=data)

    monkeypatch.setattr(ai, "ask", spy)
    gateway.handle_question("#dev'i özetle", TEST_PERSON)
    assert seen_at_call == [True]


def test_secret_and_personal_question_stores_no_value(client_as, sent_to_ai):
    r = s.ask(client_as("ali"), VALUE_QUESTION)
    assert r.status_code == 200
    rows = _rows()
    assert len(rows) == 1 and len(sent_to_ai) == 1
    masked_text = rows[0][2]
    same = masked_text == sent_to_ai[0]
    assert same, "the stored text is not exactly the text sent to the AI"
    in_row = any(value in masked_text for value in VALUES)
    raw_shapes = s.raw_shapes_in(masked_text)
    assert not in_row, "a secret or personal value is in the masked text row"
    assert raw_shapes == [], "a raw secret shape is in the masked text row"
    question = s.question_part(masked_text)
    marks = (s.REDACTED in question, "EMAIL_1" in question, "PHONE_1" in question)
    assert marks == (True, True, True), "the question must carry [REDACTED], EMAIL_1 and PHONE_1"
    connection = connect(settings.DATABASE_PATH)
    try:
        stored = any(value in cell for cell in s.db_text_cells(connection) for value in VALUES)
    finally:
        connection.close()
    assert not stored, "a secret or personal value is stored somewhere in the database"


def test_names_are_stored_as_placeholders(client_as, sent_to_ai):
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    masked_text = _rows()[0][2]
    names = _dev_author_names()
    assert names
    name_in_row = any(name in masked_text for name in names)
    has_placeholder = "PERSON_" in masked_text
    assert not name_in_row, "a real author name is in the masked text row"
    assert has_placeholder, "the masked text row has no PERSON placeholder"


def test_table_has_no_vault_mapping(client_as, sent_to_ai):
    r = s.ask(client_as("ali"), f"#dev'i özetle, iletişim: {s.EMAIL}")
    assert r.status_code == 200
    columns = {row[1] for row in _query("PRAGMA table_info(masked_texts)")}
    assert columns == {"id", "request_id", "created_at", "masked_text"}
    stored = any(s.EMAIL in str(cell) for row in _query("SELECT * FROM masked_texts") for cell in row)
    assert not stored, "the e-mail value is in the masked text table"


def test_each_request_has_its_own_row(client_as, sent_to_ai):
    ali = client_as("ali")
    ids = [s.ask(ali, "#dev'i özetle").json()["request_id"] for _ in range(2)]
    assert [row[0] for row in _rows()] == ids
    assert ids[0] != ids[1]
    connection = connect(settings.DATABASE_PATH)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            with connection:
                write_masked_text(connection, created_at="t", request_id=ids[0], masked_text="again")
    finally:
        connection.close()


def test_ai_error_keeps_the_row(client_as, monkeypatch):
    def raise_error(instruction, data):
        raise ai.AIError(code="TIMEOUT", message="TEST - provider error")

    monkeypatch.setattr(ai, "ask", raise_error)
    r = client_as("ali").post(s.ASK, json={"question": "#dev'i özetle"})
    assert r.status_code == 504
    assert _row_count() == 1
    assert _query("SELECT count(*) FROM ai_calls") == [(1,)]


def test_masked_text_only_in_its_table(client_as, sent_to_ai, caplog):
    marker = "TEST-MARKER-masked-3a14"
    with caplog.at_level(logging.DEBUG):
        r = s.ask(client_as("ali"), f"#dev'i özetle {marker}")
        listed = client_as("admin").get(s.EVENTS)
    assert r.status_code == 200 and listed.status_code == 200
    assert marker in _rows()[0][2]
    other = " ".join(str(v) for row in _query("SELECT * FROM audit_events") + _query("SELECT * FROM ai_calls")
                     for v in row)
    for place in (other, listed.text, caplog.text):
        assert marker not in place


# --- No row when nothing goes to the AI


@pytest.mark.parametrize("account, channel", [("ali", "yonetim"), ("unlinked", "dev")], ids=["not_member", "unlinked"])
def test_no_access_writes_no_row(client_as, sent_to_ai, account, channel):
    r = s.ask(client_as(account), f"#{channel}'i özetle, anahtar: {s.SLACK_TOKEN}")
    assert r.json()["status"] == "no_access"
    assert sent_to_ai == []
    assert _row_count() == 0


def test_unauthenticated_writes_no_row(anonymous_client, sent_to_ai):
    assert anonymous_client().post(s.ASK, json={"question": "#dev'i özetle"}).status_code == 401
    assert gateway.handle_question("#dev'i özetle", None).status == "no_access"
    assert sent_to_ai == []
    assert _row_count() == 0


def test_no_messages_writes_no_row(client_as, sent_to_ai):
    _write("DELETE FROM messages WHERE channel_id = ?", (DEV,))
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.json()["answer"] == gateway.NO_MESSAGES_ANSWER
    assert sent_to_ai == []
    assert _row_count() == 0


# --- Order and errors: the safe side


def test_sanitization_error_writes_no_row(fixture_accounts, sent_to_ai, monkeypatch):
    def broken(text):
        raise RuntimeError("TEST - filter failed")

    monkeypatch.setattr(gateway, "mask_secrets", broken)
    r = _client_without_raise().post(s.ASK, json={"question": "#dev'i özetle"})
    assert r.status_code == 500
    assert sent_to_ai == [] and ai.fake_call_count() == 0
    assert _row_count() == 0


def test_ask_ai_without_sanitization_writes_no_row(fixture_accounts, sent_to_ai, monkeypatch):
    """The question_for_ai check (RuntimeError) runs before the write: the unmasked question is never stored."""
    monkeypatch.setattr(gateway, "STEPS", [(n, f) for n, f in gateway.STEPS if n != "sanitization"])
    r = _client_without_raise().post(s.ASK, json={"question": "#dev'i özetle"})
    assert r.status_code == 500
    assert sent_to_ai == [] and ai.fake_call_count() == 0
    assert _row_count() == 0


def test_write_failure_stops_request_and_ai_is_not_called(fixture_accounts, sent_to_ai, monkeypatch, caplog):
    marker = "TEST-MARKER-write-3a14"

    def broken(connection, *, created_at, request_id, masked_text):
        # The error text carries a part of the masked question: it must never reach the answer or the log.
        raise sqlite3.OperationalError("TEST - " + s.question_part(masked_text))

    monkeypatch.setattr(gateway, "write_masked_text", broken)
    c = _client_without_raise()
    with caplog.at_level(logging.DEBUG):
        r = c.post(s.ASK, json={"question": f"#dev'i özetle {marker}"})
    assert r.status_code == 500
    assert r.json() == SERVER_ERROR
    assert sent_to_ai == [] and ai.fake_call_count() == 0
    assert _query("SELECT count(*) FROM ai_calls") == [(0,)]
    assert _row_count() == 0
    request_id = _latest_request_id()
    assert _steps(request_id) == [
        ("identity", "passed", None), ("authorization", "passed", None), ("data_selection", "passed", None),
        ("sanitization", "passed", None), ("ask_ai", "stopped", None),
    ]
    assert f"Failed to write masked text (request {request_id}): OperationalError" in caplog.text
    in_response = marker in r.text or "TEST - " in r.text
    in_log = marker in caplog.text or "TEST - " in caplog.text or "özetle" in caplog.text
    assert not in_response, "the error text or the question is in the response"
    assert not in_log, "the error text or the question is in the log"


def test_write_error_carries_no_text():
    error = MaskedTextWriteError()
    assert str(error) == "" and error.args == ()
