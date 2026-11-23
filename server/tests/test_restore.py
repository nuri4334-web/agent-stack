"""S3-12: placeholders through the gateway: the AI sees EMAIL_1 / PERSON_1, the asking person gets the real values in
the answer and the sources (decision B1); [REDACTED] is never restored.

Values never appear in test output: a bool is computed first and asserted with a message that names only the kind.
"""
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app import ai, gateway, settings
from app.data_selection.rules import author_name
from app.data_selection.selection import select_messages
from app.database.schema import connect
from app.filters import injection
from app.filters.api import Vault
from app.filters.normalize import normalize
from app.filters.personal import find_personal
from app.main import app
from tests import attack_samples as s
from tests.auth_clients import BASE_URL, LOGIN_PATH, TEST_PASSWORD

DEV = s.DEV_CHANNEL_ID
GENEL = "C0C8ATRM073"
SERVER_ERROR = {"error": {"code": "SERVER_ERROR", "message": "An unexpected server error occurred."}}
DEV_PERSONS = 37  # 25 authors of the messages sent (S4-02: 2 are removed) + 12 names in the #dev texts of the seed


@pytest.fixture(autouse=True)
def _reset_counter():
    ai.reset_fake_counter()


@pytest.fixture
def vaults(monkeypatch):
    """Every Vault the gateway creates, with the number of mask and restore calls."""
    created = []

    class SpyVault(Vault):
        def __init__(self):
            super().__init__()
            self.mask_calls = 0
            self.restore_calls = 0
            created.append(self)

        def mask(self, text, people):
            self.mask_calls += 1
            return super().mask(text, people)

        def restore(self, answer):
            self.restore_calls += 1
            return super().restore(answer)

    monkeypatch.setattr(gateway, "Vault", SpyVault)
    return created


@pytest.fixture
def echo_placeholders(monkeypatch, sent_to_ai):
    """The AI answers with every placeholder it saw (never with the data itself)."""
    inner = ai.ask

    def echo(instruction, data):
        response = inner(instruction=instruction, data=data)
        response.answer = "Placeholders: " + " ".join(sorted(set(s.PLACEHOLDER.findall(data))))
        return response

    monkeypatch.setattr(ai, "ask", echo)
    return sent_to_ai


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


def _selected(question, channel_ids):
    """The messages the data selection gives for a question (before the gateway masks anything)."""
    connection = connect(settings.DATABASE_PATH)
    try:
        return select_messages(connection, question, readable_channel_ids=channel_ids).messages
    finally:
        connection.close()


def _events(request_id):
    rows = _query(
        "SELECT step, decision, reason_code, masked_count, masked_kinds FROM audit_events "
        "WHERE request_id = ? ORDER BY id",
        (request_id,),
    )
    return [
        {"step": step, "decision": decision, "reason_code": reason, "masked_count": count, "masked_kinds": json.loads(k)}
        for step, decision, reason, count, k in rows
    ]


def _row(request_id, step):
    return next(e for e in _events(request_id) if e["step"] == step)


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


# --- The AI sees placeholders, the person sees the values


def test_ali_dev_ai_sees_person_placeholders_answer_shows_names(client_as, echo_placeholders):
    authors = _dev_author_names()
    assert authors
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    body = r.json()
    data = echo_placeholders[0]
    leaked = any(name in data for name in authors)
    has_placeholder = "PERSON_" in data
    assert not leaked, "an author name reached the AI"
    assert has_placeholder, "no PERSON_n in what the AI saw"
    answer = body["answer"]
    names_back = all(name in answer for name in authors)
    assert names_back, "an author name was not restored in the answer"
    assert "PERSON_" not in answer
    expected = [m for m in _selected("#dev'i özetle", [DEV]) if not injection.detect(m.text).suspicious]
    assert len(expected) == 25  # S4-02: the 2 suspicious messages are not sent
    assert [m["author"] for m in body["sources"]] == [m.author for m in expected]
    same_texts = [m["text"] for m in body["sources"]] == [normalize(m.text) for m in expected]
    assert same_texts, "a source text is not the stored message text"
    assert body["security"]["masked"] == 7


def test_old_raw_secret_stays_redacted_in_sources(client_as, sent_to_ai):
    """Correction 4: sources are the restored masked messages, never the stored raw text: [REDACTED] stays."""
    _write(
        "INSERT INTO messages (channel_id, ts, author_id, sent_at, clean_text) VALUES (?, ?, ?, ?, ?)",
        (DEV, "1800000000.000100", "U0CA5HH3M1V", "2027-01-15T08:00:00+00:00",
         f"eski not: {s.AWS_KEY} ve {s.GITHUB_TOKEN}"),
    )
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    source = next(m for m in r.json()["sources"] if m["id"] == f"{DEV}:1800000000.000100")
    raw_back = s.AWS_KEY in source["text"] or s.GITHUB_TOKEN in source["text"]
    assert not raw_back, "the stored raw secret is in the source"
    assert source["text"] == "eski not: [REDACTED] ve [REDACTED]"
    real, display = _query("SELECT real_name, display_name FROM slack_users WHERE slack_id = 'U0CA5HH3M1V'")[0]
    assert source["author"] == author_name(real, display, "U0CA5HH3M1V")


def test_ayse_genel_phones(client_as, sent_to_ai):
    texts = [normalize(m.text) for m in _selected("#genel'i özetle", [GENEL])]
    phones = [t[sp.start:sp.end] for t in texts for sp in find_personal(t) if sp.kind == "phone"]
    assert len(phones) == 2
    r = s.ask(client_as("ayse"), "#genel'i özetle")
    assert r.status_code == 200
    body = r.json()
    leaked = any(p in data for p in phones for data in sent_to_ai)
    has_placeholder = any("PHONE_" in data for data in sent_to_ai)
    in_sources = all(any(p in m["text"] for m in body["sources"]) for p in phones)
    assert not leaked, "phone reached the AI"
    assert has_placeholder, "no PHONE_n in what the AI saw"
    assert in_sources, "phone was not restored in the sources"
    assert body["security"]["masked"] == 2
    row = _row(body["request_id"], "sanitization")
    assert (row["masked_kinds"], row["masked_count"]) == ({"person": 7, "phone": 2}, 9)


def test_redacted_stays_in_answer_and_sources(client_as, sent_to_ai, monkeypatch):
    monkeypatch.setattr(ai, "FAKE_FIXED_ANSWER", "The key was [REDACTED], PERSON_1 said.")
    r = s.ask(client_as("ali"), "#dev'i özetle")
    body = r.json()
    assert body["answer"].startswith("The key was [REDACTED], ")
    assert "PERSON_1" not in body["answer"]
    assert any(s.REDACTED in m["text"] for m in body["sources"])


def test_invented_placeholder_in_answer_stays(client_as, sent_to_ai, monkeypatch):
    monkeypatch.setattr(ai, "FAKE_FIXED_ANSWER", "EMAIL_9 and PERSON_99 and CARD_3")
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.json()["answer"] == "EMAIL_9 and PERSON_99 and CARD_3"


def test_literal_placeholder_never_becomes_real_value(client_as, sent_to_ai, monkeypatch):
    monkeypatch.setattr(ai, "FAKE_FIXED_ANSWER", "EMAIL_1 / EMAIL_2")
    r = s.ask(client_as("ali"), f"#dev'i özetle, EMAIL_1 nedir? iletişim: {s.EMAIL}")
    assert r.status_code == 200
    question = s.question_part(sent_to_ai[0])
    assert question == "#dev'i özetle, EMAIL_1 nedir? iletişim: EMAIL_2"
    answer = r.json()["answer"]
    expected = answer == f"EMAIL_1 / {s.EMAIL}"
    assert expected, "the written EMAIL_1 changed or the real email was not restored"


def test_literal_placeholder_in_an_author_name_is_never_restored(client_as, sent_to_ai, monkeypatch):
    """Correction 3: a Slack user shown as "EMAIL_1" writes in #dev after the question gave out EMAIL_1:
    EMAIL_1 becomes ambiguous and is never restored, in the answer or in the sources."""
    _write("INSERT INTO slack_users (slack_id, display_name, real_name, is_bot) VALUES ('U_LITERAL', 'EMAIL_1', NULL, 0)")
    _write(
        "INSERT INTO messages (channel_id, ts, author_id, sent_at, clean_text) VALUES (?, ?, 'U_LITERAL', ?, ?)",
        (DEV, "1800000000.000200", "2027-01-15T08:00:00+00:00", "TEST - merhaba"),
    )
    monkeypatch.setattr(ai, "FAKE_FIXED_ANSWER", "Contact: EMAIL_1")
    r = s.ask(client_as("ali"), f"#dev'i özetle, iletişim: {s.EMAIL}")
    assert r.status_code == 200
    body = r.json()
    question = s.question_part(sent_to_ai[0])
    assert question == "#dev'i özetle, iletişim: EMAIL_1"  # given out before the author was seen
    leaked = s.EMAIL in r.text
    assert not leaked, "the email came back for an ambiguous EMAIL_1"
    assert body["answer"] == "Contact: EMAIL_1"
    source = next(m for m in body["sources"] if m["id"] == f"{DEV}:1800000000.000200")
    assert (source["author"], source["text"]) == ("EMAIL_1", "TEST - merhaba")


def test_link_removed_then_placeholder_restored(client_as, sent_to_ai, monkeypatch, vaults):
    monkeypatch.setattr(ai, "FAKE_FIXED_ANSWER", "See https://PERSON_1.example.com/x and PERSON_1.")
    r = s.ask(client_as("ali"), "#dev'i özetle")
    body = r.json()
    name = vaults[0].restore("PERSON_1")
    assert name != "PERSON_1"
    restored = body["answer"] == f"See link removed and {name}."
    assert restored, "the link was not removed or PERSON_1 was not restored"
    assert body["security"]["blocked"] == 1


# --- Counting and when the Vault runs


def test_names_counted_in_event_not_on_screen(client_as, sent_to_ai):
    r = s.ask(client_as("ali"), "#dev'i özetle")
    body = r.json()
    assert body["security"]["masked"] == 7
    assert _row(body["request_id"], "sanitization")["masked_kinds"]["person"] == DEV_PERSONS


def test_one_vault_per_request_used_for_masking_and_restoring(client_as, sent_to_ai, vaults):
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    assert len(vaults) == 1
    assert vaults[0].mask_calls == 1 + 2 * 27  # the question, then the text and the author of every message
    assert vaults[0].restore_calls == 1 + 2 * 25  # the answer, then the text and the author of every source (S4-02: 25)


@pytest.mark.parametrize("account, channel", [("ali", "yonetim"), ("unlinked", "dev")], ids=["not_member", "unlinked"])
def test_no_access_never_uses_the_vault(client_as, sent_to_ai, vaults, account, channel):
    r = s.ask(client_as(account), f"#{channel}'i özetle, iletişim: {s.EMAIL}")
    assert r.json()["status"] == "no_access"
    assert sum(v.mask_calls + v.restore_calls for v in vaults) == 0


def test_no_messages_never_uses_the_vault(client_as, sent_to_ai, vaults):
    _write("DELETE FROM messages WHERE channel_id = ?", (DEV,))
    r = s.ask(client_as("ali"), f"#dev'i özetle, iletişim: {s.EMAIL}")
    assert r.json()["answer"] == gateway.NO_MESSAGES_ANSWER
    assert sum(v.mask_calls + v.restore_calls for v in vaults) == 0


# --- Errors and what is kept


def test_restore_error_stops_safely(fixture_accounts, sent_to_ai, monkeypatch, caplog):
    """Decision N-1 and correction 1: a restore error is 500, never a masked answer; no value reaches the answer
    or the log, even when the error text itself carries one."""
    class BrokenVault(Vault):
        def restore(self, answer):
            raise RuntimeError(f"TEST - restore failed on {s.EMAIL}")

    monkeypatch.setattr(gateway, "Vault", BrokenVault)
    c = _client_without_raise()
    with caplog.at_level(logging.DEBUG):
        r = c.post(s.ASK, json={"question": f"#dev'i özetle, iletişim: {s.EMAIL}"})
    assert r.status_code == 500
    assert r.json() == SERVER_ERROR
    in_response = s.EMAIL in r.text or "EMAIL_" in r.text
    in_log = s.EMAIL in caplog.text or "TEST - restore failed" in caplog.text
    assert not in_response, "a value or placeholder is in the response"
    assert not in_log, "the error text or the value is in the log"
    assert "RuntimeError" in caplog.text
    request_id = _query("SELECT request_id FROM audit_events WHERE step = 'identity' ORDER BY id DESC LIMIT 1")[0][0]
    events = _events(request_id)
    assert [(e["step"], e["decision"], e["reason_code"]) for e in events][-2:] == [
        ("response_check", "passed", None), ("presentation", "stopped", None),
    ]


def test_vault_values_never_stored_or_logged(client_as, sent_to_ai, caplog):
    question = f"#dev'i özetle, iletişim: {s.EMAIL} {s.PHONE_INTL}"
    with caplog.at_level(logging.DEBUG):
        r = s.ask(client_as("ali"), question)
    assert r.status_code == 200
    events_text = client_as("admin").get(s.EVENTS).text
    connection = connect(settings.DATABASE_PATH)
    try:
        cells = s.db_text_cells(connection)
    finally:
        connection.close()
    stored = any(s.EMAIL in cell or s.PHONE_INTL in cell for cell in cells)
    in_events = s.EMAIL in events_text or s.PHONE_INTL in events_text
    in_log = s.EMAIL in caplog.text or s.PHONE_INTL in caplog.text
    assert not stored, "a personal value is stored in the database"
    assert not in_events, "a personal value is in the event list"
    assert not in_log, "a personal value is in the log"
    assert _row(r.json()["request_id"], "sanitization")["masked_kinds"]["email"] == 1


def test_context_repr_has_no_values(fixture_accounts, sent_to_ai, monkeypatch):
    seen = []
    real = gateway.presentation

    def spy(c):
        seen.append(repr(c))
        real(c)
        seen.append(repr(c))

    monkeypatch.setattr(gateway, "STEPS", [(n, spy if n == "presentation" else f) for n, f in gateway.STEPS])
    from tests.auth_clients import TEST_PERSON
    gateway.handle_question(f"#dev'i özetle, iletişim: {s.EMAIL}", TEST_PERSON)
    assert len(seen) == 2
    for text in seen:
        leaked = s.EMAIL in text or "iletişim" in text or "EMAIL_" in text or "Deniz" in text
        assert not leaked, "a value, the question or a placeholder is in the context repr"
