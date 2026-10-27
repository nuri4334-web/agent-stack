"""S1-05: end-to-end flow, AI call record and the first red authorization test."""
import logging
import re
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import settings, gateway, ai
from app.main import app
from app.database.schema import connect

client = TestClient(app)

ALI = "U0CA5HH3M1V"
FIXED_NOW = datetime(2026, 10, 25, 9, 30, tzinfo=timezone.utc)
LINE_START = re.compile(r"^\[#([\w-]+) \| ", re.MULTILINE)


@pytest.fixture
def sent(monkeypatch):
    """Captures the data texts sent to the AI; calls the real fake provider (the counter works)."""
    captured = []
    real = ai.ask

    def spy(instruction, data):
        captured.append(data)
        return real(instruction=instruction, data=data)

    monkeypatch.setattr(ai, "ask", spy)
    ai.reset_fake_counter()
    return captured


def _query(sql, params=()):
    connection = connect(settings.DATABASE_PATH)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _channel_texts(name):
    return [t for (t,) in _query(
        "SELECT m.clean_text FROM messages m JOIN channels c ON c.slack_id = m.channel_id WHERE c.name = ?", (name,),
    )]


def _call_rows():
    return _query(
        "SELECT created_at, request_id, model, result, messages_sent, duration_ms, input_tokens, output_tokens "
        "FROM ai_calls ORDER BY id"
    )


def _ask(question, user="ali"):
    return client.post("/api/ask", json={"question": question, "user": user})


def _add_excluded_channel():
    connection = connect(settings.DATABASE_PATH)
    try:
        with connection:
            connection.execute(
                "INSERT INTO channels (slack_id, name, is_private, status) VALUES ('C0OLD000001', 'old', 0, 'excluded')"
            )
            connection.execute(
                "INSERT INTO messages (channel_id, ts, author_id, sent_at, clean_text) VALUES "
                "('C0OLD000001', '1792665999.000001', ?, '2026-10-22T10:46:39+00:00', 'TEST - excluded message')",
                (ALI,),
            )
    finally:
        connection.close()


def test_summarize_dev_ai_called_once_and_only_dev(sent):
    r = _ask("#dev'i özetle")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["answer"] == ai.FAKE_FIXED_ANSWER
    assert body["sources"] == []
    assert ai.fake_call_count() == 1
    assert len(sent) == 1
    channels = LINE_START.findall(sent[0])
    assert set(channels) == {"dev"}
    assert len(channels) == 27
    for text in _channel_texts("yonetim") + _channel_texts("genel"):
        assert text not in sent[0]


def test_no_channel_name_only_allowed_channels(sent):
    _add_excluded_channel()
    r = _ask("geçen hafta neler oldu?")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    channels = LINE_START.findall(sent[0])
    assert set(channels) == {"dev", "genel", "yonetim"}
    assert len(channels) == 39
    assert "TEST - excluded message" not in sent[0]


def test_pr_number_does_not_get_no_access_goes_to_all_allowed_channels(sent):
    r = _ask("PR #17 ne durumda?")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert ai.fake_call_count() == 1
    assert set(LINE_START.findall(sent[0])) == {"dev", "genel", "yonetim"}


@pytest.mark.parametrize("question", ["#ik'i özetle", "#bugs neler var", "#dev ve #ik"])
def test_not_allowed_channel_no_access_ai_not_called(sent, question):
    r = _ask(question)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "no_access"
    assert body["answer"] == gateway.NO_ACCESS_ANSWER
    assert body["sources"] == []
    assert ai.fake_call_count() == 0
    assert sent == []
    assert _call_rows() == []


def test_blocked_id_no_access_even_if_table_says_allowed(sent):
    # Stale data: the table says "allowed" for #ik (e.g. written before the id was blocked).
    connection = connect(settings.DATABASE_PATH)
    try:
        with connection:
            connection.execute(
                "INSERT INTO channels (slack_id, name, is_private, status) VALUES ('C_IK', 'ik', 1, 'allowed')"
            )
            connection.execute(
                "INSERT INTO messages (channel_id, ts, author_id, sent_at, clean_text) VALUES "
                "('C_IK', '1792665999.000002', ?, '2026-10-22T10:46:39+00:00', 'TEST - ik message')",
                (ALI,),
            )
    finally:
        connection.close()
    assert settings.BLOCKED_CHANNELS == ["C_IK"]
    r = _ask("#ik'i özetle")
    assert r.status_code == 200
    assert r.json()["status"] == "no_access"
    assert ai.fake_call_count() == 0
    assert sent == []
    assert _call_rows() == []
    r = _ask("geçen hafta neler oldu?")
    assert r.json()["status"] == "ok"
    assert set(LINE_START.findall(sent[0])) == {"dev", "genel", "yonetim"}
    assert "TEST - ik message" not in sent[0]


def test_old_name_settings_logged_once(sent, monkeypatch, caplog):
    monkeypatch.setattr(settings, "ALLOWED_CHANNELS", ["genel", "dev", "yonetim"])
    with caplog.at_level(logging.WARNING, logger="agentstack"):
        first = _ask("#dev'i özetle")
        second = _ask("geçen hafta neler oldu?")
    assert first.json()["status"] == "no_access"
    assert second.json()["answer"] == gateway.NO_MESSAGES_ANSWER
    assert ai.fake_call_count() == 0
    assert sent == []
    warnings = [r.getMessage() for r in caplog.records if "now takes channel IDs" in r.getMessage()]
    assert warnings == [
        "Channel settings: ALLOWED_CHANNELS now takes channel IDs (e.g. C0123ABCDEF); "
        "these values are ignored: genel, dev, yonetim"
    ]


def test_ai_not_called_if_no_messages(sent, monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(settings, "DATABASE_PATH", tmp_path / "empty.db")
    with caplog.at_level(logging.WARNING, logger="agentstack"):
        r = _ask("#dev'i özetle")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["answer"] == gateway.NO_MESSAGES_ANSWER
    assert ai.fake_call_count() == 0
    assert _call_rows() == []
    assert "No Slack data" in caplog.text
    assert "#dev" not in caplog.text


def test_call_record_correct_and_has_no_text(sent):
    question = "#dev'i özetle"
    answer = gateway.handle_question(question, "ali", now=lambda: FIXED_NOW)
    rows = _call_rows()
    assert len(rows) == 1
    created_at, request_id, model, result, count, duration_ms, input_tokens, output_tokens = rows[0]
    assert created_at == FIXED_NOW.isoformat()
    assert request_id == answer.request_id
    assert (model, result, count) == ("fake-v1", "ok", 27)
    assert duration_ms >= 0
    assert input_tokens > 0 and output_tokens > 0
    text_columns = " ".join(str(d) for d in rows[0])
    assert question not in text_columns
    assert ai.FAKE_FIXED_ANSWER not in text_columns
    for text in _channel_texts("dev"):
        assert text not in text_columns


@pytest.mark.parametrize("code, http, result", [
    ("TIMEOUT", 504, "timeout"),
    ("PROVIDER_ERROR", 502, "provider_error"),
    ("QUOTA_EXCEEDED", 502, "provider_error"),
])
def test_provider_error_record_and_502_504(monkeypatch, code, http, result):
    def raise_error(instruction, data):
        raise ai.AIError(code=code, message="TEST - provider error")

    monkeypatch.setattr(ai, "ask", raise_error)
    r = _ask("#dev'i özetle")
    assert r.status_code == http
    assert r.json()["error"]["code"] == ("TIMEOUT" if code == "TIMEOUT" else "PROVIDER_ERROR")
    rows = _call_rows()
    assert len(rows) == 1
    _, _, model, written_result, count, _, input_tokens, output_tokens = rows[0]
    assert (model, written_result, count, input_tokens, output_tokens) == ("unknown", result, 27, None, None)


def test_model_name_from_setting_on_gemini_error(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-test-model")

    def raise_error(instruction, data):
        raise ai.AIError(code="TIMEOUT", message="TEST")

    monkeypatch.setattr(ai, "ask", raise_error)
    assert _ask("#dev'i özetle").status_code == 504
    assert _call_rows()[0][2] == "gemini-test-model"


def test_answer_and_error_not_broken_if_record_cannot_be_written(sent, monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("TEST - write failed")

    monkeypatch.setattr(gateway, "write_ai_call", broken)
    with caplog.at_level(logging.ERROR, logger="agentstack"):
        r = _ask("#dev'i özetle")
    assert r.status_code == 200
    assert r.json()["answer"] == ai.FAKE_FIXED_ANSWER
    assert "Failed to write AI call record" in caplog.text

    def raise_error(instruction, data):
        raise ai.AIError(code="TIMEOUT", message="TEST")

    monkeypatch.setattr(ai, "ask", raise_error)
    r = _ask("#dev'i özetle")
    assert r.status_code == 504
    assert r.json()["error"]["code"] == "TIMEOUT"


@pytest.mark.parametrize("with_error", [False, True])
def test_connection_opened_and_closed_on_every_request(monkeypatch, with_error):
    opened = []

    def track(path):
        opened.append((path, connect(path)))
        return opened[-1][1]

    monkeypatch.setattr(gateway, "connect", track)
    if with_error:
        def raise_error(instruction, data):
            raise ai.AIError(code="PROVIDER_ERROR", message="TEST")
        monkeypatch.setattr(ai, "ask", raise_error)
    r = _ask("#dev'i özetle")
    assert r.status_code == (502 if with_error else 200)
    assert len(opened) == 1
    path, connection = opened[0]
    assert path == settings.DATABASE_PATH
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_tests_do_not_touch_real_database(tmp_path_factory):
    real = settings.ROOT / "server" / "agentstack.db"
    assert settings.DATABASE_PATH != real
    assert settings.DATABASE_PATH.is_relative_to(tmp_path_factory.getbasetemp())

    def state():
        return (real.stat().st_size, real.stat().st_mtime_ns) if real.exists() else None

    before = state()
    assert _ask("#dev'i özetle").status_code == 200
    assert state() == before


def test_red_test_preconditions():
    assert _query("SELECT status FROM channels WHERE name = 'yonetim'") == [("allowed",)]
    assert _channel_texts("yonetim")
    assert _query(
        "SELECT 1 FROM channel_memberships m JOIN channels c ON c.slack_id = m.channel_id "
        "WHERE c.name = 'yonetim' AND m.slack_user_id = ?", (ALI,),
    ) == []


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Stage 2: no authorization layer")
def test_ali_yonetim_question_ai_not_called(sent):
    r = _ask("#yonetim'de neler konuşuldu?", user="ali")
    assert r.status_code == 200
    body = r.json()
    assert ai.fake_call_count() == 0
    assert sent == []
    for text in _channel_texts("yonetim"):
        assert text not in body["answer"]
        assert all(text not in s["text"] for s in body["sources"])
    assert body["status"] == "no_access"
