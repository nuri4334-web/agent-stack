"""S3-05: Slack sync and seed load mask secrets before writing, and keep the per-kind counts (never a value).

The secret rules (S3-09) may not exist yet, so mask_secrets is replaced by a fake here: these tests prove the
wiring (what is written, what is counted, what happens when the filter fails), not the rules.
"""
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from app.database.schema import connect, create_tables
from app.filters import api
from app.filters.types import FilterResult
from app.slack_connector import sanitize, seed
from app.slack_connector.sync import print_summary, sync_slack
from tests.fake_slack import ALLOWED_IDS, BLOCKED_IDS, NOW, message, sample_slack, ts

SECRET = "TEST-SECRET-EXAMPLE-305"
LOAD_TIME = datetime(2026, 10, 24, tzinfo=timezone.utc)


def _fake_mask(text: str) -> FilterResult:
    """Masks SECRET like the real filter would; counts it as a slack_token."""
    found = text.count(SECRET)
    if not found:
        return FilterResult(text)
    return FilterResult(text.replace(SECRET, api.REDACTED), {"slack_token": found}, True)


def _failing_mask(text: str) -> FilterResult:
    if SECRET in text:
        raise RuntimeError(f"TEST - rule failed on {text}")
    return FilterResult(text)


def _wrong_counts_mask(text: str) -> FilterResult:
    if SECRET in text:
        return FilterResult(text.replace(SECRET, api.REDACTED), {"email": 1})
    return FilterResult(text)


@pytest.fixture
def db():
    connection = connect(":memory:")
    yield connection
    connection.close()


def _cells(connection) -> list[str]:
    """Every text cell of every table."""
    cells = []
    for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
        for row in connection.execute(f'SELECT * FROM "{table}"'):
            cells.extend(cell for cell in row if isinstance(cell, str))
    return cells


def _stored(connection) -> bool:
    return any(SECRET in cell for cell in _cells(connection))


def _sync_with_secret(db):
    slack = sample_slack()
    slack.messages["C_DEV"].append(message("U_ALI", f"deploy key {SECRET} and again {SECRET}", 1, 700))
    return sync_slack(db, slack, ALLOWED_IDS, blocked_channels=BLOCKED_IDS, days=30, now=lambda: NOW,
                      run_id="5305a1b2")


def _seed_data(text: str) -> dict:
    return {
        "format": seed.FORMAT, "version": seed.VERSION,
        "channels": [{"slack_id": "C_DEV", "name": "dev", "is_private": 0}],
        "slack_users": [{"slack_id": "U_ALI", "display_name": "Ali", "real_name": "Ali Demo", "is_bot": 0}],
        "channel_memberships": [{"channel_id": "C_DEV", "slack_user_id": "U_ALI"}],
        "messages": [{
            "channel_id": "C_DEV", "ts": "1792665328.994119", "author_id": "U_ALI",
            "sent_at": "2026-10-22T11:05:00+00:00", "clean_text": text,
        }],
    }


# --- sanitize


def test_sanitize_returns_the_mask_secrets_result(monkeypatch):
    expected = FilterResult("masked", {"aws_key": 1}, True)
    monkeypatch.setattr(api, "mask_secrets", lambda text: expected)
    assert sanitize.sanitize("anything") is expected


def test_counts_json_is_sorted_and_has_no_values():
    assert sanitize.counts_json(FilterResult("x", {"slack_token": 2, "aws_key": 1})) == '{"aws_key":1,"slack_token":2}'
    assert sanitize.counts_json(FilterResult("x")) == "{}"


@pytest.mark.parametrize("counts", [
    {"email": 1},
    {"person": 1},
    {"slack_token": 0},
    {"slack_token": "1"},
    {"slack_token": True},
], ids=["personal_kind", "name_kind", "zero", "text_count", "bool_count"])
def test_counts_json_rejects_unknown_kind_or_bad_count(counts):
    with pytest.raises(ValueError):
        sanitize.counts_json(FilterResult("x", counts))


# --- Slack sync


def test_sync_writes_masked_text_and_counts(db, monkeypatch):
    monkeypatch.setattr(api, "mask_secrets", _fake_mask)
    _sync_with_secret(db)
    row = db.execute(
        "SELECT clean_text, secret_counts FROM messages WHERE channel_id = 'C_DEV' AND ts = ?", (ts(1, 700),)
    ).fetchone()
    stored = _stored(db)
    assert not stored, "the secret is stored in the database"
    assert row == ("deploy key [REDACTED] and again [REDACTED]", '{"slack_token":2}')
    others = {r[0] for r in db.execute("SELECT secret_counts FROM messages WHERE ts != ?", (ts(1, 700),))}
    assert others == {"{}"}


@pytest.mark.parametrize("mask", [_failing_mask, _wrong_counts_mask], ids=["filter_error", "wrong_counts"])
def test_sync_filter_error_writes_nothing_of_the_channel(db, monkeypatch, mask):
    monkeypatch.setattr(api, "mask_secrets", mask)
    summary = _sync_with_secret(db)
    dev = next(r for r in summary.channels if r.name == "dev")
    assert (dev.status, dev.reason_code) == ("error", "CHANNEL_FILTER_FAILED")
    assert dev.error_detail in ("filter: RuntimeError", "filter: ValueError")
    assert db.execute("SELECT count(*) FROM messages WHERE channel_id = 'C_DEV'").fetchone() == (0,)
    assert db.execute("SELECT count(*) FROM messages WHERE channel_id = 'C_GENEL'").fetchone()[0] > 0
    assert db.execute(
        "SELECT decision, reason_code, channel_id FROM audit_events WHERE decision = 'error'"
    ).fetchall() == [("error", "CHANNEL_FILTER_FAILED", "C_DEV")]
    lines = []
    print_summary(summary, lines.append)
    shown = SECRET in "\n".join(lines)
    stored = _stored(db)
    assert not shown, "the secret is shown in the summary"
    assert not stored, "the secret is stored in the database"


# --- seed load


def test_seed_load_masks_and_counts(db, monkeypatch):
    monkeypatch.setattr(api, "mask_secrets", _fake_mask)
    seed.load_seed(db, _seed_data(f"JWT_SECRET={SECRET}"), ["C_DEV"], lambda: LOAD_TIME, blocked_channels=[])
    stored = _stored(db)
    assert not stored, "the secret is stored in the database"
    assert db.execute("SELECT clean_text, secret_counts FROM messages").fetchall() == [
        ("JWT_SECRET=[REDACTED]", '{"slack_token":1}'),
    ]


@pytest.mark.parametrize("mask", [_failing_mask, _wrong_counts_mask], ids=["filter_error", "wrong_counts"])
def test_seed_load_filter_error_loads_nothing(db, monkeypatch, mask):
    monkeypatch.setattr(api, "mask_secrets", mask)
    with pytest.raises(seed.SeedError) as error:
        seed.load_seed(db, _seed_data(f"key {SECRET}"), ["C_DEV"], lambda: LOAD_TIME, blocked_channels=[])
    shown = SECRET in str(error.value)
    assert not shown, "the secret is in the error message"
    assert "The secret filter failed" in str(error.value)
    for table in seed.SLACK_TABLES:
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,), table


def test_seed_command_filter_error_exit_1(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "mask_secrets", _failing_mask)
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(_seed_data(f"key {SECRET}")), encoding="utf-8")
    lines = []
    code = seed.run_command(
        ["load", "--file", str(seed_path)], database_path=tmp_path / "test.db", allowed_channels=["C_DEV"],
        blocked_channels=[], now=lambda: LOAD_TIME, write=lines.append,
    )
    shown = SECRET in "\n".join(lines)
    assert code == 1
    assert not shown, "the secret is in the output"
    assert lines == ["ERROR: The secret filter failed (RuntimeError); nothing was loaded."]


# --- schema


def _add_dev_message(connection, **extra):
    connection.execute("INSERT INTO channels (slack_id, name, is_private) VALUES ('C_DEV', 'dev', 0)")
    connection.execute("INSERT INTO slack_users (slack_id) VALUES ('U_ALI')")
    columns = {"channel_id": "C_DEV", "ts": "1792665328.994119", "author_id": "U_ALI",
               "sent_at": "2026-10-22T11:05:00+00:00", "clean_text": "TEST - message"} | extra
    connection.execute(
        f"INSERT INTO messages ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
        tuple(columns.values()),
    )


def test_secret_counts_defaults_to_empty_object(db):
    create_tables(db)
    _add_dev_message(db)
    assert db.execute("SELECT secret_counts FROM messages").fetchone() == ("{}",)


@pytest.mark.parametrize("value", ["x", "[]", "1"], ids=["not_json", "array", "number"])
def test_secret_counts_rejects_invalid_json(db, value):
    create_tables(db)
    with pytest.raises(sqlite3.IntegrityError):
        _add_dev_message(db, secret_counts=value)
