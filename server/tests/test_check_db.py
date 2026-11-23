"""S3-05: the raw secret check command (python -m app.database.check_db).

The secret rules (S3-09) may not exist yet, so find_secrets is replaced by a fake where a finding is needed.
The command runs only on the temporary database of conftest or on files in tmp_path, never on server/agentstack.db.
"""
import sqlite3

import pytest

from app import settings
from app.database import check_db
from app.database.schema import connect
from app.filters import secrets
from app.filters.types import Span
from tests import attack_samples as s

SECRET = "TEST-SECRET-EXAMPLE-305"


def _run(argv=None, database_path=None):
    lines = []
    code = check_db.run_command(
        argv or [], database_path=database_path or settings.DATABASE_PATH, write=lines.append,
    )
    return code, lines


def _add_message(path, text, seq):
    connection = connect(path)
    try:
        with connection:
            cursor = connection.execute(
                "INSERT INTO messages (channel_id, ts, author_id, sent_at, clean_text) "
                "VALUES ('C0C83M051QD', ?, 'U0CA5HH3M1V', '2026-10-24T09:00:00+00:00', ?)",
                (f"1800000000.{seq:06d}", text),
            )
        return cursor.lastrowid
    finally:
        connection.close()


def _fake_find_secrets(text):
    """A slack_token finding wherever SECRET is."""
    spans, start = [], text.find(SECRET)
    while start >= 0:
        spans.append(Span(start, start + len(SECRET), "slack_token", "certain"))
        start = text.find(SECRET, start + 1)
    return spans


def test_check_db_clean_database_exit_0(_temporary_database):
    """The seeded temporary database (the same path as 'seed load') has no raw secret.

    When PR #24 is merged, this test proves that the real seed (D21 included) is clean after masking.
    """
    connection = connect(_temporary_database)
    try:
        count = connection.execute("SELECT count(*) FROM messages").fetchone()[0]
    finally:
        connection.close()
    code, lines = _run()
    assert code == 0
    assert lines == [f"Checked {count} messages, 0 masked texts and 0 suspicious messages.", "0 raw secrets."]


def test_check_db_reports_id_and_kind_never_value(_temporary_database, monkeypatch):
    monkeypatch.setattr(secrets, "find_secrets", _fake_find_secrets)
    first = _add_message(_temporary_database, f"key {SECRET} and {SECRET}", 1)
    second = _add_message(_temporary_database, f"other {SECRET}", 2)
    code, lines = _run(["--db", str(_temporary_database)])
    shown = any(SECRET in line or "key " in line or "other " in line for line in lines)
    assert code == 1
    assert not shown, "message text is in the output"
    assert lines[1:] == [
        f"message {first}: slack_token", f"message {first}: slack_token", f"message {second}: slack_token",
        "3 raw secrets in 2 messages.",
    ]


def test_check_db_runs_rules_on_normalized_text(_temporary_database, monkeypatch):
    seen = []
    monkeypatch.setattr(secrets, "find_secrets", lambda text: seen.append(text) or [])
    _add_message(_temporary_database, "xo​xb split", 1)
    assert _run()[0] == 0
    assert "xoxb split" in seen
    assert not any("​" in text for text in seen)


def test_check_db_rule_error_exit_2(_temporary_database, monkeypatch):
    """Closed on error: a failing rule never looks like a clean database, and no text is shown."""
    def broken(text):
        raise RuntimeError(f"TEST - rule failed on {text}")

    monkeypatch.setattr(secrets, "find_secrets", broken)
    _add_message(_temporary_database, f"key {SECRET}", 1)
    code, lines = _run()
    shown = any(SECRET in line for line in lines)
    assert code == 2
    assert not shown, "message text is in the output"
    assert lines == ["The secret check failed (RuntimeError)."]
    assert "0 raw secrets." not in lines


def test_check_db_missing_file_exit_2_and_not_created(tmp_path):
    path = tmp_path / "missing.db"
    code, lines = _run(["--db", str(path)])
    assert code == 2
    assert lines[0].startswith("ERROR: database file not found")
    assert not path.exists()


@pytest.mark.parametrize("version", [0, 4])
def test_check_db_wrong_schema_exit_2(tmp_path, version):
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {version}")
    connection.close()
    code, lines = _run(["--db", str(path)])
    assert code == 2
    assert "seed load" in lines[0]


def test_check_db_is_read_only(_temporary_database):
    before = _temporary_database.read_bytes()
    assert _run()[0] == 0
    assert _temporary_database.read_bytes() == before


def test_check_db_wrong_usage_exit_2():
    assert _run(["--unknown"])[0] == 2


# --- S3-14: masked_texts is scanned too


def _add_masked_text(path, text, request_id):
    connection = connect(path)
    try:
        with connection:
            cursor = connection.execute(
                "INSERT INTO masked_texts (created_at, request_id, masked_text) "
                "VALUES ('2026-11-16T09:00:00+00:00', ?, ?)",
                (request_id, text),
            )
        return cursor.lastrowid
    finally:
        connection.close()


def test_check_db_scans_masked_texts(_temporary_database, monkeypatch):
    monkeypatch.setattr(secrets, "find_secrets", _fake_find_secrets)
    row_id = _add_masked_text(_temporary_database, f"User question: key {SECRET}", "a1b2c3")
    code, lines = _run()
    shown = any(SECRET in line or "User question" in line for line in lines)
    assert code == 1
    assert not shown, "masked text is in the output"
    assert lines[0].endswith(" messages, 1 masked text and 0 suspicious messages.")
    assert lines[1:] == [f"masked text {row_id}: slack_token", "1 raw secret in 1 masked text."]


def test_check_db_names_both_places_when_both_have_findings(_temporary_database, monkeypatch):
    monkeypatch.setattr(secrets, "find_secrets", _fake_find_secrets)
    message_id = _add_message(_temporary_database, f"key {SECRET}", 1)
    row_id = _add_masked_text(_temporary_database, f"User question: {SECRET}", "a1b2c3")
    code, lines = _run()
    assert code == 1
    assert lines[1:] == [
        f"message {message_id}: slack_token", f"masked text {row_id}: slack_token",
        "2 raw secrets in 1 message and 1 masked text.",
    ]


def test_check_db_clean_after_secret_question(client_as):
    """A real question with a key and personal data: the masked text written by the gateway has no raw secret."""
    r = s.ask(client_as("ali"), f"#dev'i özetle, anahtar: {s.SLACK_TOKEN} e-posta: {s.EMAIL}")
    assert r.status_code == 200
    code, lines = _run()
    assert code == 0
    assert lines[0].endswith(" messages, 1 masked text and 2 suspicious messages.")  # S4-02: D23, D24 removed
    assert lines[-1] == "0 raw secrets."


def test_check_db_rule_error_on_masked_text_exit_2(_temporary_database, monkeypatch):
    def broken_on_masked(text):
        if text.startswith("User question"):
            raise RuntimeError(f"TEST - rule failed on {text}")
        return []

    monkeypatch.setattr(secrets, "find_secrets", broken_on_masked)
    _add_masked_text(_temporary_database, f"User question: {SECRET}", "a1b2c3")
    code, lines = _run()
    shown = any(SECRET in line for line in lines)
    assert code == 2
    assert not shown, "masked text is in the output"
    assert lines == ["The secret check failed (RuntimeError)."]
