"""S3-02b: secret attack tests, written before the filter code exists (blind: the rule code was never read).

The attacker's view: only docs/api-contract.md v4, the Sprint 3 filter interface (with its Clarifications 1-3)
and the fixtures in tests/conftest.py, tests/fake_slack.py and tests/auth_clients.py.

- xfail(strict=True, raises=AssertionError) where the protection is still missing; one mark per group, removed in
  the PR of the task that is merged LAST among the tasks named in its reason.
- A test that already passes today stays a normal test (regression guard; e.g. innocent look-alikes).
- No value is ever shown in test output: a bool is computed first and asserted with a message naming only the kind;
  parametrize ids are kind names only.
- Fields that do not exist yet (security.alarm, event masked_kinds / alarm) are read with .get(), so a test fails
  today with AssertionError and never with KeyError.
"""
from datetime import datetime, timezone

import pytest

from app import ai
from app.database.schema import connect
from app.filters.api import mask_secrets
from app.filters.types import FilterResult
from app.slack_connector import seed
from app.slack_connector.sync import sync_slack
from tests import attack_samples as s
from tests.fake_slack import ALLOWED_IDS, BLOCKED_IDS, NOW, message, sample_slack, ts

PENDING_S3_05 = pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="S3-05 sync/seed filter + S3-09 secret rules",
)
PENDING_S3_08 = pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="S3-08 sanitization step + S3-09 secret rules",
)
PENDING_S3_03 = pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="S3-03 answer check (PR #25) + S3-09 secret rules (PR #24)",
)

SECRET_KINDS = list(s.SECRET_SAMPLES)


@pytest.fixture(autouse=True)
def _reset_counter():
    ai.reset_fake_counter()


# === Group 1: the filter API, secrets (S3-09) =======================================================================

@pytest.mark.parametrize("kind", SECRET_KINDS)
def test_mask_secrets_hides_each_secret_kind(kind):
    """Each of the 10 secret kinds, in its typical form: masked, counted once under its kind, alarm (decision B2)."""
    sample = s.SECRET_SAMPLES[kind]
    result = mask_secrets(f"deploy notu: {sample.text} (lütfen kullanma)")
    leaked = sample.leaked_in(result.text)
    has_mask = s.REDACTED in result.text
    assert not leaked, f"{kind} left in the text"
    assert has_mask, f"no [REDACTED] for {kind}"
    assert dict(result.counts) == {kind: 1}, f"wrong counts for {kind}"
    assert result.alarm is True, f"no alarm for {kind}"


def test_key_split_by_invisible_character():
    """A zero-width space inside the token must not hide it from the rules (normalize runs first)."""
    split = s.SLACK_TOKEN[:2] + "\u200b" + s.SLACK_TOKEN[2:]
    result = mask_secrets(f"token: {split}")
    leaked = s.SLACK_TOKEN in result.text or split in result.text
    assert not leaked, "slack_token left in the text"
    assert dict(result.counts) == {"slack_token": 1}, "wrong counts"
    assert result.alarm is True, "no alarm"


def test_key_in_the_middle_of_a_sentence():
    """A token inside a sentence: masked, the words around it stay."""
    result = mask_secrets(f"deploy yine düştü, {s.GITHUB_TOKEN} ile denedim ama olmadı")
    leaked = s.GITHUB_TOKEN in result.text
    kept = result.text.startswith("deploy yine düştü, ") and result.text.endswith(" ile denedim ama olmadı")
    assert not leaked, "github_token left in the text"
    assert kept, "the words around the token changed"
    assert result.alarm is True, "no alarm"


def test_key_inside_code_block():
    """A token inside a ``` code block is masked too."""
    result = mask_secrets(f"şunu çalıştır:\n```\nexport GITHUB_TOKEN={s.GITHUB_TOKEN}\n```")
    leaked = s.GITHUB_TOKEN in result.text
    assert not leaked, "github_token left in the code block"
    assert result.alarm is True, "no alarm"


def test_env_block_with_several_lines():
    """A pasted .env block: both secret values masked, harmless setting lines unchanged."""
    text = (
        "DEBUG=true\n"
        f"AWS_ACCESS_KEY_ID={s.AWS_KEY}\n"
        f"AWS_SECRET_ACCESS_KEY={s.AWS_SECRET_VALUE}\n"
        "PASSWORD_MIN_LENGTH=8"
    )
    result = mask_secrets(text)
    leaked_key = s.AWS_KEY in result.text
    leaked_secret = s.AWS_SECRET_VALUE in result.text
    lines = result.text.splitlines()
    harmless_kept = "DEBUG=true" in lines and "PASSWORD_MIN_LENGTH=8" in lines
    assert not leaked_key, "aws_key left in the .env block"
    assert not leaked_secret, "the secret access key left in the .env block"
    assert result.masked >= 2, "at least 2 values must be counted"
    assert harmless_kept, "a harmless setting line changed"
    assert result.alarm is True, "no alarm"


def test_database_url_password_counted_once():
    """Interface Clarification 1: the password in DATABASE_URL is one value, counted once as db_password."""
    result = mask_secrets(s.SECRET_SAMPLES["db_password"].text)
    leaked = s.DB_PASSWORD in result.text
    user_and_host_kept = "app:" in result.text and "@db.internal:5432/app" in result.text
    assert not leaked, "db_password left in the text"
    assert dict(result.counts) == {"db_password": 1}, "the password must be counted once, as db_password"
    assert user_and_host_kept, "user or host changed"


def test_masking_twice_does_not_count_again():
    """Interface Clarification 2: mask_secrets does not count an existing [REDACTED] again."""
    first = mask_secrets(f"token: {s.SLACK_TOKEN}")
    second = mask_secrets(first.text)
    unchanged = second.text == first.text
    assert dict(first.counts) == {"slack_token": 1}, "the first pass must count the token"
    assert dict(second.counts) == {}, "the second pass counted [REDACTED] again"
    assert unchanged, "the second pass changed the text"


def test_existing_redacted_mark_is_not_counted():
    """Interface Clarification 2: a text that only has [REDACTED] is left as it is, nothing counted, no alarm."""
    text = "deploy token: [REDACTED]"
    assert mask_secrets(text) == FilterResult(text, {}, False)


# === Group 2: Slack sync and seed (S3-05) ===========================================================================

@PENDING_S3_05
def test_seed_secrets_are_masked_in_database(_temporary_database):
    """After the seed load of conftest: no raw secret shape in any table, and #dev has a [REDACTED] (the .env
    message of the demo seed). The seed file is never read by the test, only the loaded database."""
    connection = connect(_temporary_database)
    try:
        raw = sorted({name for cell in s.db_text_cells(connection) for name in s.raw_shapes_in(cell)})
        dev_texts = [row[0] for row in connection.execute(
            "SELECT m.clean_text FROM messages m JOIN channels c ON c.slack_id = m.channel_id WHERE c.name = 'dev'"
        )]
    finally:
        connection.close()
    assert not raw, f"raw secret shapes stored in the database: {raw}"
    redacted = any(s.REDACTED in t for t in dev_texts)
    assert redacted, "no [REDACTED] in #dev"


@pytest.fixture
def memory_db():
    connection = connect(":memory:")
    yield connection
    connection.close()


@PENDING_S3_05
@pytest.mark.parametrize("kind", SECRET_KINDS)
def test_synced_secret_is_masked_before_storing(memory_db, kind):
    """A Slack message with a secret is synced: the value is in no table, the message is stored with [REDACTED]."""
    sample = s.SECRET_SAMPLES[kind]
    slack = sample_slack()
    slack.messages["C_DEV"].append(message("U_ALI", f"yeni ayar: {sample.text}", 1, 400))
    sync_slack(memory_db, slack, ALLOWED_IDS, blocked_channels=BLOCKED_IDS, days=30, now=lambda: NOW,
               run_id="5302b0c1")
    stored = any(sample.leaked_in(cell) for cell in s.db_text_cells(memory_db))
    row = memory_db.execute(
        "SELECT clean_text FROM messages WHERE channel_id = 'C_DEV' AND ts = ?", (ts(1, 400),)
    ).fetchone()
    assert not stored, f"{kind} stored in the database"
    assert row is not None, "the message was not stored"
    has_mask = s.REDACTED in row[0]
    assert has_mask, f"no [REDACTED] for {kind}"


@PENDING_S3_05
def test_seed_load_masks_secrets(memory_db):
    """A seed with secrets in clean_text (e.g. an old export) is loaded: the values are in no table."""
    data = {
        "format": seed.FORMAT,
        "version": seed.VERSION,
        "channels": [{"slack_id": "C_DEV", "name": "dev", "is_private": 0}],
        "slack_users": [{"slack_id": "U_ALI", "display_name": "Ali", "real_name": "Ali Demo", "is_bot": 0}],
        "channel_memberships": [{"channel_id": "C_DEV", "slack_user_id": "U_ALI"}],
        "messages": [{
            "channel_id": "C_DEV", "ts": "1792665328.994119", "author_id": "U_ALI",
            "sent_at": "2026-10-22T11:05:00+00:00",
            "clean_text": f"bot: {s.SLACK_TOKEN} aws: {s.AWS_KEY}",
        }],
    }
    seed.load_seed(memory_db, data, ["C_DEV"], lambda: datetime(2026, 10, 24, tzinfo=timezone.utc),
                   blocked_channels=[])
    cells = s.db_text_cells(memory_db)
    stored = any(s.SLACK_TOKEN in c or s.AWS_KEY in c for c in cells)
    assert not stored, "a secret from the seed is stored in the database"


# === Group 3: the gateway, question and messages (S3-08) ============================================================

KEY_QUESTION = f"#dev'i özetle, bu anahtar çalışmıyor: {s.SLACK_TOKEN}"


@PENDING_S3_08
def test_key_pasted_in_question_is_not_sent(client_as, sent_to_ai):
    """Ali pastes a Slack token into his question: not stopped (B2), the AI gets [REDACTED], alarm is true."""
    r = s.ask(client_as("ali"), KEY_QUESTION)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert ai.fake_call_count() == 1
    leaked = any(s.SLACK_TOKEN in data for data in sent_to_ai)
    has_mask = any(s.REDACTED in data for data in sent_to_ai)
    in_response = s.SLACK_TOKEN in r.text
    assert not leaked, "slack_token reached the AI"
    assert has_mask, "no [REDACTED] in what the AI saw"
    assert not in_response, "slack_token is in the response"
    assert body["security"].get("alarm") is True, "security.alarm must be true"
    assert body["security"]["masked"] >= 1, "security.masked must be at least 1"


def _insert_raw_dev_message(path) -> None:
    """Writes a #dev message with a raw AWS key and GitHub token straight into the test's temporary database, skipping
    sync (like a row written before S3-05). Newest ts, so "#dev'i özetle" selects it. Author: Ali's Slack account of
    the seed. The text is built here, so no value is a function argument (a crash traceback shows arguments)."""
    text = f"eski not: {s.AWS_KEY} ve {s.GITHUB_TOKEN}"
    connection = connect(path)
    try:
        with connection:
            connection.execute(
                "INSERT INTO messages (channel_id, ts, author_id, sent_at, clean_text) VALUES (?, ?, ?, ?, ?)",
                (s.DEV_CHANNEL_ID, "1800000000.000100", "U0CA5HH3M1V", "2027-01-15T08:00:00+00:00", text),
            )
    finally:
        connection.close()


@PENDING_S3_08
def test_raw_secret_in_stored_message_is_not_sent(client_as, sent_to_ai, _temporary_database):
    """A raw secret already in the database is masked again at question time (interface table, place B)."""
    _insert_raw_dev_message(_temporary_database)
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    body = r.json()
    raw = sorted({name for data in sent_to_ai for name in s.raw_shapes_in(data)})
    in_sources = any(s.AWS_KEY in m["text"] or s.GITHUB_TOKEN in m["text"] for m in body["sources"])
    assert not raw, f"raw secret shapes reached the AI: {raw}"
    assert not in_sources, "a raw secret is in sources"
    # The secret was not in the question, so no alarm (API contract 8, security.alarm).
    assert body["security"].get("alarm", False) is False, "alarm must be false when the question has no secret"


@PENDING_S3_08
def test_sanitization_event_counts_kind_without_value(client_as, sent_to_ai):
    """The sanitization event of a question with a token: alarm, the kind and its count, never the value."""
    r = s.ask(client_as("ali"), KEY_QUESTION)
    assert r.status_code == 200
    row, events_text = s.event_row(client_as("admin"), r.json()["request_id"], "sanitization")
    assert row is not None, "no sanitization event"
    kinds = row.get("masked_kinds") or {}
    leaked = s.SLACK_TOKEN in events_text
    assert row.get("alarm") is True, "the sanitization event must have alarm true"
    assert kinds.get("slack_token", 0) >= 1, "masked_kinds must count slack_token"
    assert sum(kinds.values()) == row["masked_count"], "masked_kinds must add up to masked_count"
    assert not leaked, "slack_token is in the event list"


@pytest.mark.parametrize("account, channel", [("ali", "yonetim"), ("unlinked", "dev")], ids=["not_member", "unlinked"])
def test_no_access_answer_never_alarms(client_as, sent_to_ai, account, channel):
    """Decision N1: a no_access answer never has alarm true, even with a secret in the question."""
    r = s.ask(client_as(account), f"#{channel}'i özetle, anahtar: {s.SLACK_TOKEN}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "no_access"
    assert body["security"].get("alarm", False) is False
    assert ai.fake_call_count() == 0
    calls = len(sent_to_ai)
    assert calls == 0, "the AI was called"
    _, events_text = s.event_row(client_as("admin"), body["request_id"], "authorization")
    leaked = s.SLACK_TOKEN in events_text
    assert not leaked, "slack_token is in the event list"


def test_no_messages_answer_never_alarms(client_as, sent_to_ai, _temporary_database):
    """Decision N1: the "No messages were found" answer never has alarm true (only the test's database is changed)."""
    connection = connect(_temporary_database)
    try:
        with connection:
            connection.execute("DELETE FROM messages WHERE channel_id = ?", (s.DEV_CHANNEL_ID,))
    finally:
        connection.close()
    r = s.ask(client_as("ali"), f"#dev'i özetle, anahtar: {s.SLACK_TOKEN}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    no_messages_answer = body["answer"] == "No messages were found for this question."
    assert no_messages_answer, "not the no-messages answer"
    assert body["security"].get("alarm", False) is False
    assert ai.fake_call_count() == 0
    calls = len(sent_to_ai)
    assert calls == 0, "the AI was called"


# === Group 5: second scan of the answer (S3-03 + S3-09) =============================================================

@PENDING_S3_03
def test_secret_in_answer_is_masked_not_counted_on_screen(client_as, sent_to_ai, monkeypatch):
    """The AI answers with a token: the user gets [REDACTED]; security.masked does not change (N2); the
    response_check event counts it."""
    ali = client_as("ali")
    baseline = s.ask(ali, "#dev'i özetle")
    assert baseline.status_code == 200
    masked_before = baseline.json()["security"]["masked"]

    monkeypatch.setattr(ai, "FAKE_FIXED_ANSWER", f"Use this key: {s.SLACK_TOKEN}")
    r = s.ask(ali, "#dev'i özetle")
    assert r.status_code == 200
    body = r.json()
    leaked = s.SLACK_TOKEN in body["answer"]
    has_mask = s.REDACTED in body["answer"]
    assert not leaked, "slack_token reached the user"
    assert has_mask, "no [REDACTED] in the answer"
    assert body["security"]["masked"] == masked_before, "the answer's second scan must not count in security.masked"
    row, events_text = s.event_row(client_as("admin"), body["request_id"], "response_check")
    assert row is not None, "no response_check event"
    kinds = row.get("masked_kinds") or {}
    in_events = s.SLACK_TOKEN in events_text
    assert row["masked_count"] >= 1, "response_check masked_count must be at least 1"
    assert kinds.get("slack_token", 0) >= 1, "response_check masked_kinds must count slack_token"
    assert not in_events, "slack_token is in the event list"


# === Group 6: innocent look-alikes (normal tests; a rule that breaks one gives a false alarm) =======================

INNOCENT = {
    "commit_sha": "deploy commit 3f9c2a1b7d4e5f60718293a4b5c6d7e8f9012345 merged",
    "uuid": "request 123e4567-e89b-12d3-a456-426614174000 done",
    "sha256": "checksum e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "order_number": "sipariş SIP-2026-000123 hazır",
    "datetime": "toplantı 2026-11-10T09:12:03+00:00",
    "setting_line": "PASSWORD_MIN_LENGTH=8",
    "channel_name": "#dev kanalında konuşalım",
}


@pytest.mark.parametrize("case", list(INNOCENT))
def test_innocent_lookalikes_are_untouched(case):
    text = INNOCENT[case]
    assert mask_secrets(text) == FilterResult(text, {}, False)


@pytest.mark.parametrize("case", ["tckn", "iban", "card"])
def test_sample_values_are_valid(case):
    """The made-up personal data has a correct checksum, so the attack tests stay meaningful."""
    check = {"tckn": (s.tckn_is_valid, s.TCKN), "iban": (s.iban_is_valid, s.IBAN), "card": (s.luhn_is_valid, s.CARD)}
    is_valid, value = check[case]
    assert is_valid(value), f"the {case} sample has a wrong checksum"
