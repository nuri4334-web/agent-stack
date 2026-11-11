"""S3-02b: personal data and name attack tests, written before the filter code exists (blind).

Decision B1: personal data (email, phone, tckn, iban, card) and Slack people names go to the AI as placeholders
(EMAIL_1 ... PERSON_1) and are restored for the asking person; [REDACTED] is never restored.
Decision N3: names are not counted in security.masked, only in the event rows (masked_kinds has person).
People names = real_name and display_name of the non-bot Slack users (technical decision, 10 Nov).

Same rules as test_secret_attacks.py: one strict xfail mark per group, no value in any test output (bools first,
messages name only the kind), fields that do not exist yet are read with .get().
"""
import pytest

from app import ai
from app.database.schema import connect
from tests import attack_samples as s

PENDING_S3_12 = pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="S3-12 Vault + S3-07 personal/name rules + S3-08 sanitization step",
)

PERSONAL_CASES = list(s.PERSONAL_SAMPLES)
NAME_FIELDS = ["real_name", "display_name"]
NO_PLACEHOLDER_ANSWER = "The fake provider saw no placeholder."


@pytest.fixture(autouse=True)
def _reset_counter():
    ai.reset_fake_counter()


@pytest.fixture
def echo_placeholders(monkeypatch, sent_to_ai):
    """Wraps ai.ask (on top of sent_to_ai, so the data is still captured and the real fake provider still counts the
    call): the answer is every placeholder seen in the data sent to the AI, so the presentation step has something
    to restore. If the data has no placeholder, the answer is a fixed text with no value in it: the wrapper never
    echoes the incoming data, otherwise a restore test could pass today by mistake (XPASS)."""
    inner = ai.ask

    def echo(instruction, data):
        response = inner(instruction=instruction, data=data)
        found = sorted(set(s.PLACEHOLDER.findall(data)))
        response.answer = "Placeholders: " + " ".join(found) if found else NO_PLACEHOLDER_ANSWER
        return response

    monkeypatch.setattr(ai, "ask", echo)
    return sent_to_ai


def _dev_member_name(path, field: str) -> str:
    """A name of a non-bot #dev member from the test's database (the seed); never written to output."""
    connection = connect(path)
    try:
        rows = connection.execute(
            "SELECT u.real_name, u.display_name FROM slack_users u "
            "JOIN channel_memberships m ON m.slack_user_id = u.slack_id "
            "WHERE m.channel_id = ? AND u.is_bot = 0 ORDER BY u.slack_id",
            (s.DEV_CHANNEL_ID,),
        ).fetchall()
    finally:
        connection.close()
    index = 0 if field == "real_name" else 1
    names = [row[index].strip() for row in rows if row[index] and len(row[index].strip()) >= 3]
    if not names:
        pytest.skip(f"no #dev member with a {field} in the seed")
    return names[0]


def _personal_question(value: str) -> str:
    return f"#dev'i özetle, iletişim: {value}"


def _name_question(name: str) -> str:
    return f"#dev'i özetle, {name} ne dedi?"


# === Group 4: personal data and names (S3-07 + S3-08 + S3-12) =======================================================

@PENDING_S3_12
@pytest.mark.parametrize("case", PERSONAL_CASES)
def test_personal_data_in_question_is_placeholder(client_as, sent_to_ai, case):
    """Personal data in Ali's question: the AI never sees the value, it sees the placeholder."""
    value, prefix = s.PERSONAL_SAMPLES[case]
    r = s.ask(client_as("ali"), _personal_question(value))
    assert r.status_code == 200
    assert ai.fake_call_count() == 1
    leaked = any(value in data for data in sent_to_ai)
    has_placeholder = any(f"{prefix}_" in p for data in sent_to_ai for p in s.PLACEHOLDER.findall(data))
    assert not leaked, f"{case} reached the AI"
    assert has_placeholder, f"no {prefix}_n placeholder for {case}"


@PENDING_S3_12
@pytest.mark.parametrize("field", NAME_FIELDS)
def test_person_name_in_question_is_placeholder(client_as, sent_to_ai, _temporary_database, field):
    """A Slack person's name in the question: the question part sent to the AI has PERSON_n, not the name."""
    name = _dev_member_name(_temporary_database, field)
    r = s.ask(client_as("ali"), _name_question(name))
    assert r.status_code == 200
    questions = [s.question_part(data) for data in sent_to_ai]
    assert questions, "the AI was not called"
    leaked = any(name.casefold() in q.casefold() for q in questions)
    has_placeholder = any(p.startswith("PERSON_") for q in questions for p in s.PLACEHOLDER.findall(q))
    assert not leaked, f"person ({field}) reached the AI"
    assert has_placeholder, f"no PERSON_n placeholder for the {field}"


@PENDING_S3_12
def test_message_authors_are_placeholders(client_as, sent_to_ai, _temporary_database):
    """Decision B1 covers every Slack person name, the author in the message header too: "#dev'i özetle" sends no
    real_name of any #dev author to the AI, anywhere in the data."""
    connection = connect(_temporary_database)
    try:
        authors = [row[0].strip() for row in connection.execute(
            "SELECT DISTINCT u.real_name FROM messages m JOIN slack_users u ON u.slack_id = m.author_id "
            "WHERE m.channel_id = ? AND u.is_bot = 0 AND u.real_name IS NOT NULL",
            (s.DEV_CHANNEL_ID,),
        ) if row[0] and len(row[0].strip()) >= 3]
    finally:
        connection.close()
    assert authors, "the seed has no #dev author with a real_name"
    r = s.ask(client_as("ali"), "#dev'i özetle")
    assert r.status_code == 200
    assert sent_to_ai, "the AI was not called"
    leaked = any(name in data for name in authors for data in sent_to_ai)
    has_placeholder = any(p.startswith("PERSON_") for data in sent_to_ai for p in s.PLACEHOLDER.findall(data))
    assert not leaked, "an author name reached the AI"
    assert has_placeholder, "no PERSON_n placeholder in the data"


@PENDING_S3_12
@pytest.mark.parametrize("case", PERSONAL_CASES)
def test_personal_data_is_restored_for_the_asker(client_as, echo_placeholders, case):
    """The AI answers with the placeholder: Ali gets the real value back (B1)."""
    value, _ = s.PERSONAL_SAMPLES[case]
    r = s.ask(client_as("ali"), _personal_question(value))
    assert r.status_code == 200
    restored = value in r.json()["answer"]
    assert restored, f"{case} was not restored"


@PENDING_S3_12
@pytest.mark.parametrize("field", NAME_FIELDS)
def test_person_name_is_restored_for_the_asker(client_as, echo_placeholders, _temporary_database, field):
    """The AI answers with PERSON_n: Ali gets the real name back (B1)."""
    name = _dev_member_name(_temporary_database, field)
    r = s.ask(client_as("ali"), _name_question(name))
    assert r.status_code == 200
    restored = name.casefold() in r.json()["answer"].casefold()
    assert restored, f"person ({field}) was not restored"


@PENDING_S3_12
def test_personal_data_counts_in_masked(client_as, sent_to_ai):
    """One e-mail in the question adds exactly 1 to security.masked (API contract 8, from S3-12)."""
    ali = client_as("ali")
    before = s.ask(ali, "#dev'i özetle")
    after = s.ask(ali, _personal_question(s.EMAIL))
    assert before.status_code == after.status_code == 200
    diff = after.json()["security"]["masked"] - before.json()["security"]["masked"]
    assert diff == 1, "an e-mail in the question must add 1 to security.masked"


@PENDING_S3_12
def test_names_not_counted_in_masked_but_in_event(client_as, sent_to_ai, _temporary_database):
    """Decision N3: a name in the question does not change security.masked, but the sanitization event counts it
    under person."""
    name = _dev_member_name(_temporary_database, "real_name")
    ali = client_as("ali")
    before = s.ask(ali, "#dev'i özetle")
    after = s.ask(ali, _name_question(name))
    assert before.status_code == after.status_code == 200
    assert after.json()["security"]["masked"] == before.json()["security"]["masked"], "names must not count"
    row_before, _ = s.event_row(client_as("admin"), before.json()["request_id"], "sanitization")
    row_after, _ = s.event_row(client_as("admin"), after.json()["request_id"], "sanitization")
    assert row_before is not None and row_after is not None, "no sanitization event"
    person_before = (row_before.get("masked_kinds") or {}).get("person", 0)
    person_after = (row_after.get("masked_kinds") or {}).get("person", 0)
    assert person_after >= person_before + 1, "the sanitization event must count the name under person"


def test_redacted_is_never_restored(client_as, sent_to_ai, monkeypatch):
    """[REDACTED] stays in the answer and the pasted key never comes back (B1); passes today, must stay so."""
    monkeypatch.setattr(ai, "FAKE_FIXED_ANSWER", "The key was [REDACTED].")
    r = s.ask(client_as("ali"), f"#dev'i özetle, anahtar: {s.SLACK_TOKEN}")
    assert r.status_code == 200
    answer = r.json()["answer"]
    has_mask = s.REDACTED in answer
    leaked = s.SLACK_TOKEN in answer
    assert has_mask, "[REDACTED] must stay in the answer"
    assert not leaked, "slack_token reached the user"
