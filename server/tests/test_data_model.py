import sqlite3

import pytest

from app import gateway
from app.database.schema import SCHEMA_VERSION, connect, create_tables

TABLES = {
    "people", "linked_accounts", "slack_users", "channels",
    "channel_memberships", "messages", "audit_events", "ai_calls",
}
TIME = "2026-10-22T14:05:00+03:00"
TS = "1729500000.000100"


@pytest.fixture
def db():
    connection = connect(":memory:")
    create_tables(connection)
    yield connection
    connection.close()


def _columns(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _insert(db, table, row):
    columns = ", ".join(row)
    placeholders = ", ".join("?" * len(row))
    return db.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(row.values()))


def _add_channel(db, slack_id="C1", name="dev", is_private=0, **fields):
    _insert(db, "channels", {"slack_id": slack_id, "name": name, "is_private": is_private} | fields)


def _add_user(db, slack_id="U1"):
    _insert(db, "slack_users", {"slack_id": slack_id, "display_name": "Deniz"})


def _add_message(db, channel_id="C1", ts=TS, author_id="U1"):
    _insert(db, "messages", {
        "channel_id": channel_id, "ts": ts, "author_id": author_id,
        "sent_at": TIME, "clean_text": "you take the login page",
    })


def _add_person(db, name="Ali", **fields):
    return _insert(db, "people", {"display_name": name} | fields).lastrowid


def _link_account(db, person_id, source_account_id, source="slack", link_method="admin"):
    _insert(db, "linked_accounts", {
        "person_id": person_id, "source": source, "source_account_id": source_account_id,
        "link_method": link_method, "linked_at": TIME,
    })


def _add_event(db, **fields):
    row = {
        "created_at": TIME, "request_id": "3f9c2a1b7d4e", "step": "authorization",
        "decision": "passed", "duration_ms": 1.5,
    } | fields
    return _insert(db, "audit_events", row).lastrowid


def _add_ai_call(db, **fields):
    row = {
        "created_at": TIME, "request_id": "3f9c2a1b7d4e", "model": "gemini-2.0-flash",
        "result": "ok", "messages_sent": 12, "duration_ms": 850.25,
        "input_tokens": 1200, "output_tokens": 300,
    } | fields
    _insert(db, "ai_calls", row)


def test_tables_created_when_empty(db):
    names = {s[0] for s in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )}
    assert names == TABLES
    for table in TABLES:
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 3


def test_creating_twice_causes_no_problem(db):
    _add_channel(db)
    db.commit()
    create_tables(db)
    assert db.execute("SELECT count(*) FROM channels").fetchone()[0] == 1
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_newer_version_database_is_rejected():
    connection = connect(":memory:")
    connection.execute("PRAGMA user_version = 4")
    with pytest.raises(RuntimeError):
        create_tables(connection)
    connection.close()


@pytest.mark.parametrize("old_version", [1, 2])
def test_older_schema_version_is_rejected(old_version):
    connection = connect(":memory:")
    connection.execute(f"PRAGMA user_version = {old_version}")
    with pytest.raises(RuntimeError, match="older than the code"):
        create_tables(connection)
    assert connection.execute(
        "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA user_version").fetchone()[0] == old_version
    connection.close()


def test_foreign_keys_on(db):
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    _add_user(db)
    with pytest.raises(sqlite3.IntegrityError):
        _add_message(db, channel_id="C_MISSING")


def test_messages_have_no_raw_text_column(db):
    columns = _columns(db, "messages")
    assert columns == {"id", "channel_id", "ts", "author_id", "sent_at", "clean_text", "is_suspicious"}
    assert not any("ham" in s or "raw" in s for s in columns)


def test_audit_events_have_no_text_column(db):
    assert _columns(db, "audit_events") == {
        "id", "created_at", "request_id", "person_id", "step", "decision", "reason_code", "channel_id",
        "message_count", "channel_count", "user_count", "membership_count",
        "blocked_count", "masked_count", "suspicious_count", "duration_ms",
    }


def test_event_reason_rejects_free_text(db):
    _add_event(db, decision="stopped", reason_code="NOT_CHANNEL_MEMBER")
    for reason in ["Ali: password 1234", "not_channel_member", "", "A" * 41]:
        with pytest.raises(sqlite3.IntegrityError):
            _add_event(db, decision="stopped", reason_code=reason)


def test_event_steps_same_as_gateway(db):
    for name in [name for name, _ in gateway.STEPS] + ["slack_sync"]:
        _add_event(db, step=name)
    with pytest.raises(sqlite3.IntegrityError):
        _add_event(db, step="other_step")


def test_event_decision_limited(db):
    for decision in ["passed", "stopped", "ok", "error"]:
        _add_event(db, decision=decision)
    with pytest.raises(sqlite3.IntegrityError):
        _add_event(db, decision="success")


def test_slack_sync_summary_can_be_written(db):
    row_id = _add_event(
        db, step="slack_sync", decision="ok", request_id="a1b2c3d4e5f6",
        channel_count=3, user_count=5, membership_count=9, message_count=42,
    )
    row = db.execute(
        "SELECT person_id, channel_count, user_count, membership_count, message_count "
        "FROM audit_events WHERE id = ?", (row_id,)
    ).fetchone()
    assert row == (None, 3, 5, 9, 42)
    with pytest.raises(sqlite3.IntegrityError):
        _add_event(db, step="slack_sync", decision="ok", channel_count=-1)


def test_failed_channel_record_can_be_written(db):
    _add_channel(db)
    _add_event(db, step="slack_sync", decision="error", reason_code="CHANNEL_FETCH_FAILED", channel_id="C1")
    with pytest.raises(sqlite3.IntegrityError):
        _add_event(db, step="slack_sync", decision="error", reason_code="CHANNEL_FETCH_FAILED",
                   channel_id="C_MISSING")


def test_ai_call_has_no_text_column(db):
    assert _columns(db, "ai_calls") == {
        "id", "created_at", "request_id", "model", "result", "messages_sent",
        "duration_ms", "input_tokens", "output_tokens",
    }
    _add_ai_call(db)
    with pytest.raises(sqlite3.IntegrityError):
        _add_ai_call(db, model="gemini 2.0 flash")
    with pytest.raises(sqlite3.IntegrityError):
        _add_ai_call(db, input_tokens=-1)


def test_ai_result_limited(db):
    _add_ai_call(db, result="provider_error", input_tokens=None, output_tokens=None)
    _add_ai_call(db, result="timeout", input_tokens=None, output_tokens=None)
    for result in ["PROVIDER_ERROR", "failed", ""]:
        with pytest.raises(sqlite3.IntegrityError):
            _add_ai_call(db, result=result)


def test_new_channel_default_excluded(db):
    _add_channel(db, "C1", "dev", is_private=0)
    _add_channel(db, "C2", "yonetim", is_private=1)
    statuses = [s[0] for s in db.execute("SELECT status FROM channels")]
    assert statuses == ["excluded", "excluded"]


def test_channel_status_only_allowed_excluded_or_blocked(db):
    for status in ["public", "private", "exclude", "BLOCKED", ""]:
        with pytest.raises(sqlite3.IntegrityError):
            _add_channel(db, "C1", "dev", status=status)


def test_blocked_status_accepted(db):
    _add_channel(db, "C1", "dev", status="blocked")
    _add_channel(db, "C2", "genel")
    statuses = [s[0] for s in db.execute("SELECT status FROM channels ORDER BY slack_id")]
    assert statuses == ["blocked", "excluded"]


def test_channel_name_has_no_rule_in_table(db):
    # MIG-B: the table does not look at the name; the blocked list (by id, in .env) is applied in sync, seed load
    # and at question time (see test_blocked_id_no_access_even_if_table_says_allowed).
    _add_channel(db, "C9", "ik", is_private=1, status="allowed")
    assert db.execute("SELECT status FROM channels WHERE slack_id = 'C9'").fetchone() == ("allowed",)


def test_channel_and_ts_cannot_be_written_twice(db):
    _add_channel(db, "C1", "dev")
    _add_channel(db, "C2", "genel")
    _add_user(db)
    _add_message(db, "C1")
    with pytest.raises(sqlite3.IntegrityError):
        _add_message(db, "C1")
    _add_message(db, "C2")


def test_ts_stored_as_text(db):
    _add_channel(db)
    _add_user(db)
    _add_message(db)
    assert db.execute("SELECT ts, typeof(ts) FROM messages").fetchone() == (TS, "text")


def test_ts_cannot_be_written_as_decimal_number(db):
    _add_channel(db)
    _add_user(db)
    for ts in [1729500000.0001, 1729500000, "1729500000.0001"]:
        with pytest.raises(sqlite3.IntegrityError):
            _add_message(db, ts=ts)


def test_is_suspicious_default_empty(db):
    _add_channel(db)
    _add_user(db)
    _add_message(db)
    assert db.execute("SELECT is_suspicious FROM messages").fetchone()[0] is None


def test_role_default_user(db):
    person_id = _add_person(db)
    assert db.execute("SELECT role FROM people WHERE id = ?", (person_id,)).fetchone()[0] == "user"
    _add_person(db, "Nuri", role="admin")
    with pytest.raises(sqlite3.IntegrityError):
        _add_person(db, "Musa", role="superadmin")


def test_same_slack_account_cannot_link_to_two_people(db):
    ali = _add_person(db, "Ali")
    deniz = _add_person(db, "Deniz")
    _link_account(db, ali, "U123")
    with pytest.raises(sqlite3.IntegrityError):
        _link_account(db, deniz, "U123")
    _link_account(db, deniz, "U123", source="github")


def test_person_cannot_link_two_accounts_in_same_source(db):
    ali = _add_person(db)
    _link_account(db, ali, "U1")
    with pytest.raises(sqlite3.IntegrityError):
        _link_account(db, ali, "U2")


def test_source_and_link_method_limited(db):
    ali = _add_person(db)
    with pytest.raises(sqlite3.IntegrityError):
        _link_account(db, ali, "U1", source="gitlab")
    with pytest.raises(sqlite3.IntegrityError):
        _link_account(db, ali, "U1", link_method="automatic")


def test_membership_cannot_be_written_with_unknown_user(db):
    _add_channel(db)
    with pytest.raises(sqlite3.IntegrityError):
        _insert(db, "channel_memberships", {
            "channel_id": "C1", "slack_user_id": "U_MISSING", "updated_at": TIME,
        })
