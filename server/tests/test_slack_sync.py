from datetime import datetime

import pytest

from app.slack_connector import sanitize
from app.slack_connector.sync import run_command, print_summary, sync_slack
from app.database.schema import connect
from tests.fake_slack import ALLOWED, NOW, message, sample_slack, ts

CHANNEL_ENDPOINTS = {"conversations.members", "conversations.history"}


@pytest.fixture
def db():
    # sync_slack creates the tables itself (create_tables is the first thing).
    connection = connect(":memory:")
    yield connection
    connection.close()


def _sync(db, slack, allowed=ALLOWED, run_id="a1b2c3d4", **options):
    return sync_slack(db, slack, allowed, days=30, now=lambda: NOW, run_id=run_id, **options)


def _count(db, sql, *params):
    return db.execute(sql, params).fetchone()[0]


def _message_count(db, channel_id=None):
    if channel_id is None:
        return _count(db, "SELECT count(*) FROM messages")
    return _count(db, "SELECT count(*) FROM messages WHERE channel_id = ?", channel_id)


def _summary_row(db):
    return db.execute(
        "SELECT request_id, person_id, decision, reason_code, channel_count, user_count, "
        "membership_count, message_count FROM audit_events WHERE step = 'slack_sync' AND decision = 'ok' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()


def _error_rows(db):
    return db.execute(
        "SELECT reason_code, channel_id FROM audit_events WHERE decision = 'error' ORDER BY id"
    ).fetchall()


def test_no_member_or_message_request_for_excluded_channel(db):
    slack = sample_slack()
    _sync(db, slack)
    assert slack.channel_calls("C_SALES") == []
    assert _message_count(db, "C_SALES") == 0
    assert _count(db, "SELECT count(*) FROM channel_memberships WHERE channel_id = 'C_SALES'") == 0
    assert _count(db, "SELECT status FROM channels WHERE slack_id = 'C_SALES'") == "excluded"


def test_ik_not_fetched_even_if_in_allowlist(db):
    slack = sample_slack()
    _sync(db, slack, allowed=ALLOWED + ["ik", "#IK"])
    assert slack.channel_calls("C_IK") == []
    assert _message_count(db, "C_IK") == 0
    assert _count(db, "SELECT count(*) FROM channel_memberships WHERE channel_id = 'C_IK'") == 0
    assert _count(db, "SELECT status FROM channels WHERE slack_id = 'C_IK'") == "excluded"


def test_private_yonetim_messages_are_fetched(db):
    _sync(db, sample_slack())
    assert _count(db, "SELECT is_private FROM channels WHERE slack_id = 'C_YON'") == 1
    assert _count(db, "SELECT status FROM channels WHERE slack_id = 'C_YON'") == "allowed"
    assert _message_count(db, "C_YON") == 1


def test_running_twice_does_not_change_message_count(db):
    slack = sample_slack()
    first = _sync(db, slack)
    second = _sync(db, slack, run_id="e5f6")
    assert first.message_count == 6
    assert second.message_count == 0
    assert _message_count(db) == 6
    assert _summary_row(db)[7] == 0


def test_pagination_reads_all_pages(db):
    slack = sample_slack(page_size=1)
    summary = _sync(db, slack)
    assert summary.message_count == 6
    assert summary.membership_count == 9
    assert _count(db, "SELECT count(*) FROM channels") == 5
    assert _count(db, "SELECT count(*) FROM slack_users") == 4
    history = [p.get("cursor") for endpoint, p in slack.calls
               if endpoint == "conversations.history" and p["channel"] == "C_DEV"]
    assert history == [None, "1", "2"]


def test_other_channels_continue_when_one_fails(db):
    slack = sample_slack()
    slack.errors[("conversations.history", "C_DEV")] = "not_in_channel"
    summary = _sync(db, slack)
    assert _message_count(db, "C_DEV") == 0
    assert _message_count(db, "C_GENEL") == 2
    assert _message_count(db, "C_YON") == 1
    assert _error_rows(db) == [("CHANNEL_FETCH_FAILED", "C_DEV")]
    assert _summary_row(db)[3] == "SOME_CHANNELS_FAILED"
    assert summary.channel_count == 2
    dev = next(c for c in summary.channels if c.name == "dev")
    assert dev.error_detail == "Slack: not_in_channel"


def test_bot_not_in_channel_no_request_and_error_record(db):
    slack = sample_slack()
    slack.channels[1]["is_member"] = False
    _sync(db, slack)
    assert slack.channel_calls("C_DEV") == []
    assert _error_rows(db) == [("BOT_NOT_IN_CHANNEL", "C_DEV")]


def test_summary_row_written_with_correct_counts(db):
    _sync(db, sample_slack())
    assert _summary_row(db) == ("a1b2c3d4", None, "ok", None, 3, 4, 9, 6)
    assert _count(db, "SELECT count(*) FROM audit_events") == 1


def test_unknown_author_added_to_slack_users_first(db):
    slack = sample_slack()
    slack.messages["C_DEV"].append(message("U_STRANGER", "hello", 1, 900))
    _sync(db, slack)
    row = db.execute(
        "SELECT display_name, real_name, is_bot FROM slack_users WHERE slack_id = 'U_STRANGER'"
    ).fetchone()
    assert row == (None, None, 0)
    assert _count(db, "SELECT count(*) FROM messages WHERE author_id = 'U_STRANGER'") == 1


def test_ts_stays_text(db):
    _sync(db, sample_slack())
    expected = ts(5, 100)
    assert expected.endswith(".000100")
    assert db.execute(
        "SELECT ts, typeof(ts) FROM messages WHERE channel_id = 'C_GENEL' ORDER BY ts LIMIT 1"
    ).fetchone() == (expected, "text")


def test_member_who_left_is_deleted_on_next_sync(db):
    slack = sample_slack()
    _sync(db, slack)
    slack.members["C_DEV"].remove("U_DENIZ")
    later = "2026-10-24T12:00:00+00:00"
    sync_slack(db, slack, ALLOWED, days=30, now=lambda: datetime.fromisoformat(later), run_id="e5f6")
    members = db.execute(
        "SELECT slack_user_id, updated_at FROM channel_memberships WHERE channel_id = 'C_DEV' "
        "ORDER BY slack_user_id"
    ).fetchall()
    assert members == [("U_ALI", later), ("U_BOT", later)]


def test_messages_with_subtype_are_skipped(db):
    slack = sample_slack()
    slack.messages["C_GENEL"] += [
        message(None, "bot wrote", 3, 400, subtype="bot_message", bot_id="B1"),
        message("U_ALI", "thread reply", 3, 500, subtype="thread_broadcast"),
        message("U_ALI", "   ", 3, 600),
        message(None, "no author", 3, 700),
    ]
    summary = _sync(db, slack)
    genel = next(c for c in summary.channels if c.name == "genel")
    assert genel.new_messages == 2
    assert genel.fetched_messages == 7
    assert dict(genel.skipped) == {
        "channel_join": 1, "bot_message": 1, "thread_broadcast": 1, "empty_text": 1, "no_author": 1,
    }
    assert _message_count(db, "C_GENEL") == 2
    lines = []
    print_summary(summary, lines.append)
    genel_line = next(s for s in lines if s.startswith("#genel"))
    assert "5 skipped: bot_message 1, channel_join 1, empty_text 1, no_author 1, thread_broadcast 1" in genel_line
    output = "\n".join(lines)
    for text in ["bot wrote", "thread reply", "kanala katıldı", "günaydın"]:
        assert text not in output


def test_sanitize_called_before_writing(db, monkeypatch):
    monkeypatch.setattr(sanitize, "sanitize", lambda text: "[CLEAN]")
    _sync(db, sample_slack())
    assert {s[0] for s in db.execute("SELECT clean_text FROM messages")} == {"[CLEAN]"}


def test_data_of_channel_removed_from_allowlist_is_deleted(db):
    slack = sample_slack()
    _sync(db, slack)
    _sync(db, slack, allowed=["genel", "yonetim"], run_id="e5f6")
    assert _count(db, "SELECT status FROM channels WHERE slack_id = 'C_DEV'") == "excluded"
    assert _message_count(db, "C_DEV") == 0
    assert _count(db, "SELECT count(*) FROM channel_memberships WHERE channel_id = 'C_DEV'") == 0
    assert _message_count(db, "C_GENEL") == 2
    # Audit events are not deleted; the channel row stays.
    assert _count(db, "SELECT count(*) FROM audit_events") == 2


def test_channel_missing_in_slack_becomes_excluded(db):
    slack = sample_slack()
    _sync(db, slack)
    slack.channels = [c for c in slack.channels if c["id"] != "C_DEV"]
    summary = _sync(db, slack, run_id="e5f6")
    assert _count(db, "SELECT status FROM channels WHERE slack_id = 'C_DEV'") == "excluded"
    assert _message_count(db, "C_DEV") == 0
    assert slack.channel_calls("C_DEV") == ["conversations.members", "conversations.history"]
    dev = next(c for c in summary.channels if c.name == "dev")
    assert (dev.status, dev.deleted_messages) == ("excluded", 3)


def test_from_scratch_refetches_messages(db):
    slack = sample_slack()
    _sync(db, slack)
    slack.messages["C_DEV"].pop()
    _sync(db, slack, run_id="e5f6")
    assert _message_count(db, "C_DEV") == 3
    summary = _sync(db, slack, run_id="f7a8", from_scratch=True)
    assert _message_count(db, "C_DEV") == 2
    assert summary.message_count == 5
    assert _count(db, "SELECT count(*) FROM audit_events") == 3


def test_nothing_written_if_channel_list_fails(db):
    slack = sample_slack()
    slack.errors[("conversations.list", None)] = "invalid_auth"
    summary = _sync(db, slack)
    assert summary.failed_to_start == "CHANNEL_LIST_FAILED"
    assert _error_rows(db) == [("CHANNEL_LIST_FAILED", None)]
    assert _count(db, "SELECT count(*) FROM audit_events") == 1
    for table in ["channels", "slack_users", "channel_memberships", "messages"]:
        assert _count(db, f"SELECT count(*) FROM {table}") == 0
    assert not any(endpoint in CHANNEL_ENDPOINTS for endpoint, _ in slack.calls)


def test_oldest_param_from_days(db):
    slack = sample_slack()
    _sync(db, slack)
    expected = f"{int(NOW.timestamp()) - 30 * 86400}.000000"
    oldest = {p["oldest"] for endpoint, p in slack.calls if endpoint == "conversations.history"}
    assert oldest == {expected}


def test_does_not_start_without_token(tmp_path):
    path = tmp_path / "test.db"
    created = []
    lines = []

    def run(argv, token):
        return run_command(
            argv, token=token, client_factory=lambda t: created.append(t) or sample_slack(),
            database_path=path, allowed_channels=ALLOWED, now=lambda: NOW, write=lines.append,
        )

    assert run([], "") == 2
    assert run(["--days", "0"], "xoxb-EXAMPLE") == 2
    assert run(["--days", "366"], "xoxb-EXAMPLE") == 2
    assert created == []
    assert not path.exists()
    assert "SLACK_BOT_TOKEN" in lines[0]
