import json

import pytest

from app.slack_connector.sync import sync_slack
from app.slack_connector.seed import (
    SEED_PATH, SeedError, export_seed, write_seed_file, read_seed, load_seed,
)
from app.database.schema import connect
from tests.fake_slack import ALLOWED, NOW, message, sample_slack

SLACK_TABLES = ["channels", "slack_users", "channel_memberships", "messages"]
D21_LIKE = (
    "SLACK_BOT_TOKEN=xoxb-0000-EXAMPLE-1111 GITHUB=ghp_EXAMPLE1234 "
    "GEMINI=AIzaEXAMPLE_abc-12 AWS=AKIAEXAMPLE0000"
)


@pytest.fixture
def db():
    connection = connect(":memory:")
    yield connection
    connection.close()


def _filled(db, slack=None):
    sync_slack(db, slack or sample_slack(), ALLOWED, days=30, now=lambda: NOW, run_id="a1b2c3d4")
    return db


def _empty_db():
    return connect(":memory:")


def _counts(db):
    return {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in SLACK_TABLES}


def _content(db):
    return (
        set(db.execute("SELECT channel_id, ts, author_id, sent_at, clean_text FROM messages")),
        set(db.execute("SELECT channel_id, slack_user_id FROM channel_memberships")),
        set(db.execute("SELECT slack_id, display_name, real_name, is_bot FROM slack_users")),
        set(db.execute("SELECT slack_id, name, is_private, status FROM channels")),
    )


def test_seed_export_then_load_into_empty_db_same_counts(db, tmp_path):
    _filled(db)
    path = tmp_path / "seed.json"
    write_seed_file(export_seed(db), path)
    new = _empty_db()
    counts = load_seed(new, read_seed(path), ALLOWED, lambda: NOW)
    assert counts == {"channels": 3, "allowed_channels": 3, "users": 4, "memberships": 9, "messages": 6}
    expected = _content(db)
    loaded = _content(new)
    assert loaded[0] == expected[0]
    assert loaded[1] == expected[1]
    assert loaded[2] == expected[2]
    assert loaded[3] == {c for c in expected[3] if c[3] == "allowed"}
    assert new.execute("SELECT DISTINCT typeof(ts) FROM messages").fetchall() == [("text",)]
    new.close()


def test_seed_has_no_audit_log_or_excluded_channel(db, tmp_path):
    _filled(db)
    path = tmp_path / "seed.json"
    write_seed_file(export_seed(db), path)
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert set(data) == {"format", "version", "channels", "slack_users", "channel_memberships", "messages"}
    for forbidden in ["audit_events", "ai_calls", "request_id", "C_IK", "C_SALES", "maaş", "teklif"]:
        assert forbidden not in text
    assert b"\r\n" not in path.read_bytes()


def test_load_into_filled_db_is_rejected(db, tmp_path):
    _filled(db)
    data = export_seed(db)
    before = _counts(db)
    with pytest.raises(SeedError):
        load_seed(db, data, ALLOWED, lambda: NOW)
    assert _counts(db) == before


def test_seed_with_token_pattern_is_not_written(db, tmp_path):
    slack = sample_slack()
    slack.messages["C_DEV"].append(message("U_ALI", "key: xoxb-1234-abcd-real", 1, 900))
    _filled(db, slack)
    data = export_seed(db)
    path = tmp_path / "seed.json"
    with pytest.raises(SeedError) as error:
        write_seed_file(data, path)
    assert "slack_token" in str(error.value)
    assert "xoxb-1234" not in str(error.value)
    assert not path.exists()

    # A hand-written file is also rejected when read (even if hidden with an escape sequence).
    for ensure_ascii in [False, True]:
        path.write_text(json.dumps(data, ensure_ascii=ensure_ascii).replace("xoxb", "\\u0078oxb"),
                        encoding="utf-8")
        with pytest.raises(SeedError) as error:
            read_seed(path)
        assert "slack_token" in str(error.value)


def test_fake_keys_with_example_stay_in_seed(db, tmp_path):
    slack = sample_slack()
    slack.messages["C_DEV"].append(message("U_ALI", D21_LIKE, 1, 900))
    _filled(db, slack)
    path = tmp_path / "seed.json"
    write_seed_file(export_seed(db), path)
    new = _empty_db()
    load_seed(new, read_seed(path), ALLOWED, lambda: NOW)
    assert new.execute(
        "SELECT clean_text FROM messages WHERE channel_id = 'C_DEV' AND clean_text LIKE 'SLACK_BOT%'"
    ).fetchone() == (D21_LIKE,)
    new.close()


def test_rejected_if_used_token_appears_in_message(db, tmp_path):
    # It passes the pattern rule because it contains EXAMPLE; only the "used token" rule catches it.
    token = "xoxb-EXAMPLE-9999-USED"
    slack = sample_slack()
    slack.messages["C_DEV"].append(message("U_ALI", f"pasted by mistake {token}", 1, 900))
    _filled(db, slack)
    path = tmp_path / "seed.json"
    with pytest.raises(SeedError) as error:
        write_seed_file(export_seed(db), path, token=token)
    assert token not in str(error.value)
    assert not path.exists()
    write_seed_file(export_seed(db), path, token="")
    with pytest.raises(SeedError):
        read_seed(path, token)


def test_loader_allow_list_is_applied(db, tmp_path):
    _filled(db)
    new = _empty_db()
    counts = load_seed(new, export_seed(db), ["genel", "yonetim"], lambda: NOW)
    assert counts["allowed_channels"] == 2
    assert new.execute("SELECT status FROM channels WHERE slack_id = 'C_DEV'").fetchone() == ("excluded",)
    assert new.execute("SELECT count(*) FROM messages WHERE channel_id = 'C_DEV'").fetchone() == (0,)
    assert new.execute("SELECT count(*) FROM channel_memberships WHERE channel_id = 'C_DEV'").fetchone() == (0,)
    new.close()


def test_repo_seed_file_is_valid():
    if not SEED_PATH.exists():
        pytest.skip("demo-data/slack-seed.json does not exist yet (added after a real sync).")
    # read_seed rejects a file with a token pattern other than EXAMPLE.
    data = read_seed(SEED_PATH)
    names = [c["name"] for c in data["channels"]]
    assert "ik" not in [n.lower() for n in names]
    new = _empty_db()
    counts = load_seed(new, data, names, lambda: NOW)
    assert counts["messages"] == len(data["messages"])
    assert counts["memberships"] == len(data["channel_memberships"])
    new.close()
