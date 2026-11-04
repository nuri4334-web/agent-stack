"""S2-05: authorization and sources through the gateway (API contract 8, 11; docs/data-model.md "Authorization chain").

"The AI was not called" is checked with the fake provider's counter and sent_to_ai.
Most tests call handle_question directly: signing in is slow (scrypt) and adds nothing here.
"""
import logging
import re
from dataclasses import replace

import pytest

from app import ai, gateway, settings
from app.accounts.rules import SignedInPerson
from app.data_selection import selection as selection_module
from app.data_selection.selection import select_messages
from app.database.schema import connect
from tests.auth_clients import FIXTURE_ACCOUNTS, channels_sent_to_ai

ASK = "/api/ask"
DEV, GENEL, YONETIM = "C0C83M051QD", "C0C8ATRM073", "C0CB44VUCF2"
ALI_SLACK = FIXTURE_ACCOUNTS["ali"].slack_user_id
QUESTION_NO_CHANNEL = "geçen hafta neler oldu?"
SOURCE_ID = re.compile(r"[CG][A-Z0-9_]+:[0-9]{10}\.[0-9]{6}")


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


def _person(username):
    account = FIXTURE_ACCOUNTS[username]
    person_id = _query("SELECT id FROM people WHERE username = ?", (username,))[0][0]
    return SignedInPerson(
        id=person_id, username=username, display_name=account.name, role=account.role,
        slack_user_id=account.slack_user_id,
    )


def _ask(username, question):
    return gateway.handle_question(question, _person(username))


def _steps():
    """The gateway events, oldest first: step, decision, reason, channel id, message count."""
    return _query(
        "SELECT step, decision, reason_code, channel_id, message_count FROM audit_events "
        "WHERE step NOT IN ('login', 'logout') ORDER BY id"
    )


def _assert_refused(answer, sent, reason, channel=None):
    assert answer.status == "no_access"
    assert answer.answer == gateway.NO_ACCESS_ANSWER
    assert answer.sources == []
    assert ai.fake_call_count() == 0
    assert sent == []
    assert _query("SELECT count(*) FROM ai_calls") == [(0,)]
    assert _steps() == [
        ("identity", "passed", None, None, 0),
        ("authorization", "stopped", reason, channel, 0),
    ]


def _add_message(channel_id, number, text):
    _write(
        "INSERT INTO messages (channel_id, ts, author_id, sent_at, clean_text) VALUES (?, ?, ?, ?, ?)",
        (channel_id, f"{1799000000 + number}.000100", ALI_SLACK, "2027-01-01T10:00:00+00:00", text),
    )


def _add_ik(status="allowed", member=None):
    """The fake #ik (C_IK, blocked by the test settings) with a message and, if wanted, a member."""
    _write("INSERT INTO channels (slack_id, name, is_private, status) VALUES ('C_IK', 'ik', 1, ?)", (status,))
    _add_message("C_IK", 1, "TEST - ik message")
    if member:
        _write(
            "INSERT INTO channel_memberships (channel_id, slack_user_id, updated_at) "
            "VALUES ('C_IK', ?, '2026-10-24T00:00:00+00:00')",
            (member,),
        )


# --- The "done" list of the task


def test_ali_yonetim_no_access_ai_not_called_event_stopped(fixture_accounts, sent_to_ai):
    _assert_refused(_ask("ali", "#yonetim'de neler konuşuldu?"), sent_to_ai, "NOT_CHANNEL_MEMBER", YONETIM)


def test_ayse_yonetim_gets_answer_and_yonetim_sources(fixture_accounts, sent_to_ai):
    answer = _ask("ayse", "#yonetim'de neler konuşuldu?")
    assert answer.status == "ok"
    assert answer.answer == ai.FAKE_FIXED_ANSWER
    assert [s.channel for s in answer.sources] == ["yonetim"] * 6
    assert channels_sent_to_ai(sent_to_ai) == [{"yonetim"}]
    assert [row[:3] for row in _steps()][1] == ("authorization", "passed", None)
    assert [row[3] for row in _steps()] == [None] + [YONETIM] * 6


def test_ali_question_without_channel_gets_no_yonetim(fixture_accounts, sent_to_ai):
    answer = _ask("ali", QUESTION_NO_CHANNEL)
    assert answer.status == "ok"
    assert {s.channel for s in answer.sources} == {"dev", "genel"}
    assert len(answer.sources) == 33
    assert channels_sent_to_ai(sent_to_ai) == [{"dev", "genel"}]
    for (text,) in _query("SELECT clean_text FROM messages WHERE channel_id = ?", (YONETIM,)):
        assert text not in sent_to_ai[0]


def test_ayse_question_without_channel_gets_all_three(fixture_accounts, sent_to_ai):
    answer = _ask("ayse", QUESTION_NO_CHANNEL)
    assert {s.channel for s in answer.sources} == {"dev", "genel", "yonetim"}
    assert len(answer.sources) == 39


@pytest.mark.parametrize("username", ["unlinked", "admin"])
@pytest.mark.parametrize("question, channel", [("#dev'i özetle", DEV), (QUESTION_NO_CHANNEL, None)])
def test_no_slack_account_sees_no_channel_data(fixture_accounts, sent_to_ai, username, question, channel):
    _assert_refused(_ask(username, question), sent_to_ai, "NO_SLACK_ACCOUNT", channel)


def test_admin_role_does_not_open_yonetim(fixture_accounts, sent_to_ai):
    _assert_refused(_ask("admin_linked", "#yonetim'de neler konuşuldu?"), sent_to_ai, "NOT_CHANNEL_MEMBER", YONETIM)


def test_admin_linked_reads_only_own_channels(fixture_accounts, sent_to_ai):
    answer = _ask("admin_linked", "#dev'i özetle")
    assert answer.status == "ok"
    assert len(answer.sources) == 27


@pytest.mark.parametrize("username", ["ali", "ayse", "admin_linked"])
def test_ik_is_refused_for_everyone(fixture_accounts, sent_to_ai, username):
    _assert_refused(_ask(username, "#ik'i özetle"), sent_to_ai, "CHANNEL_NOT_ALLOWED")


def test_ik_is_never_read_even_with_a_stale_allowed_row_and_a_membership(fixture_accounts, sent_to_ai):
    _add_ik(member=ALI_SLACK)
    _assert_refused(_ask("ali", "#ik'i özetle"), sent_to_ai, "CHANNEL_NOT_ALLOWED", "C_IK")
    answer = _ask("ali", QUESTION_NO_CHANNEL)
    assert {s.channel for s in answer.sources} == {"dev", "genel"}
    assert "TEST - ik message" not in sent_to_ai[0]


# --- The answer over HTTP


def test_every_refusal_has_the_same_body(client_as, sent_to_ai):
    ali, unlinked = client_as("ali"), client_as("unlinked")
    answers = [
        ali.post(ASK, json={"question": "#yonetim'de neler var?"}),
        ali.post(ASK, json={"question": "#ik'i özetle"}),
        ali.post(ASK, json={"question": "#yok-boyle-bir-kanal"}),
        unlinked.post(ASK, json={"question": "#dev'i özetle"}),
    ]
    assert {r.status_code for r in answers} == {200}
    for r in answers:
        body = r.json()
        assert body.pop("request_id")
        assert body == {
            "status": "no_access", "answer": "You don't have access to this information.", "sources": [],
            "security": {"blocked": 0, "masked": 0, "suspicious": 0},
        }
    assert sent_to_ai == []


def test_sources_over_http_have_the_contract_fields(client_as, sent_to_ai):
    sources = client_as("ali").post(ASK, json={"question": "#dev'i özetle"}).json()["sources"]
    assert len(sources) == 27
    for source in sources:
        assert set(source) == {"id", "channel", "author", "time", "text"}
        assert source["time"].endswith("+00:00")


def test_ai_error_answer_has_no_sources(client_as, monkeypatch):
    def raise_error(instruction, data):
        raise ai.AIError(code="TIMEOUT", message="TEST - timeout")

    monkeypatch.setattr(ai, "ask", raise_error)
    r = client_as("ali").post(ASK, json={"question": "#dev'i özetle"})
    assert r.status_code == 504
    assert "sources" not in r.json()


# --- Several channels and the limit


@pytest.mark.parametrize("question", ["#dev ve #yonetim", "#yonetim ve #dev"])
def test_one_refused_channel_refuses_all(fixture_accounts, sent_to_ai, question):
    _assert_refused(_ask("ali", question), sent_to_ai, "NOT_CHANNEL_MEMBER")


def test_two_readable_channels_are_read(fixture_accounts, sent_to_ai):
    answer = _ask("ali", "#dev ve #genel")
    assert {s.channel for s in answer.sources} == {"dev", "genel"}


def test_same_name_two_rows_is_refused(fixture_accounts, sent_to_ai):
    _write("INSERT INTO channels (slack_id, name, is_private, status) VALUES ('C0DEVOLD001', 'dev', 0, 'allowed')")
    _assert_refused(_ask("ali", "#dev'i özetle"), sent_to_ai, "CHANNEL_NOT_ALLOWED")


def test_question_without_channel_reads_at_most_50_of_own_channels(fixture_accounts, sent_to_ai):
    for number in range(1, 61):
        _add_message(DEV, number, f"TEST - dev {number}")
    # Newer than all of them, but not a channel of Ali: must not push his messages out or reach the AI.
    for number in range(100, 110):
        _add_message(YONETIM, number, f"TEST - yonetim {number}")
    answer = _ask("ali", QUESTION_NO_CHANNEL)
    assert [s.text for s in answer.sources] == [f"TEST - dev {number}" for number in range(11, 61)]
    assert "TEST - yonetim" not in sent_to_ai[0]


# --- Sources


def _line(source):
    return f"[#{source.channel} | {source.author} | {source.time}]: {source.text}"


def test_sources_are_the_messages_sent_to_the_ai_in_the_same_order(fixture_accounts, sent_to_ai):
    answer = _ask("ali", QUESTION_NO_CHANNEL)
    data = sent_to_ai[0]
    assert data.endswith("\n".join(_line(s) for s in answer.sources))
    assert _query("SELECT messages_sent FROM ai_calls") == [(len(answer.sources),)]


def test_source_ids_are_unique_and_match_the_messages(fixture_accounts, sent_to_ai):
    answer = _ask("ayse", QUESTION_NO_CHANNEL)
    ids = [s.id for s in answer.sources]
    assert len(set(ids)) == 39
    assert all(SOURCE_ID.fullmatch(i) for i in ids)
    assert set(ids) == {f"{c}:{ts}" for c, ts in _query("SELECT channel_id, ts FROM messages")}


def test_source_id_keeps_ts_as_text(fixture_accounts, sent_to_ai):
    _add_message(DEV, 1, "TEST - zeros at the end")
    answer = _ask("ali", "#dev'i özetle")
    assert answer.sources[-1].id == f"{DEV}:1799000001.000100"


def test_source_id_is_not_sent_to_the_ai(fixture_accounts, sent_to_ai):
    answer = _ask("ali", "#dev'i özetle")
    for source in answer.sources:
        assert source.id not in sent_to_ai[0]


def test_source_time_is_utc(fixture_accounts, sent_to_ai):
    answer = _ask("ayse", QUESTION_NO_CHANNEL)
    assert len(answer.sources) == 39
    assert all(s.time.endswith("+00:00") for s in answer.sources)


def test_no_messages_answer_has_no_sources(fixture_accounts, sent_to_ai):
    _write("DELETE FROM messages WHERE channel_id = ?", (DEV,))
    answer = _ask("ali", "#dev'i özetle")
    assert (answer.status, answer.answer, answer.sources) == ("ok", gateway.NO_MESSAGES_ANSWER, [])
    assert ai.fake_call_count() == 0


def test_step_stopping_before_ai_leaves_sources_empty(fixture_accounts, sent_to_ai, monkeypatch):
    def stop(c):
        c.status = "no_access"
        c.stopped = True

    steps = [(name, stop if name == "sanitization" else step) for name, step in gateway.STEPS]
    monkeypatch.setattr(gateway, "STEPS", steps)
    assert _ask("ali", "#dev'i özetle").sources == []
    assert sent_to_ai == []


def test_step_refusing_after_ai_leaves_sources_empty(fixture_accounts, sent_to_ai, monkeypatch):
    def stop(c):
        c.status = "no_access"
        c.stopped = True

    steps = [(name, stop if name == "response_check" else step) for name, step in gateway.STEPS]
    monkeypatch.setattr(gateway, "STEPS", steps)
    answer = _ask("ali", "#dev'i özetle")
    assert (answer.status, answer.sources) == ("no_access", [])


# --- Settings at question time


def test_blocked_at_question_time_is_not_read_with_a_membership(fixture_accounts, sent_to_ai, monkeypatch):
    monkeypatch.setattr(settings, "BLOCKED_CHANNELS", [DEV])
    _assert_refused(_ask("ali", "#dev'i özetle"), sent_to_ai, "CHANNEL_NOT_ALLOWED", DEV)
    answer = _ask("ali", QUESTION_NO_CHANNEL)
    assert {s.channel for s in answer.sources} == {"genel"}


def test_removed_from_allow_list_is_not_read(fixture_accounts, sent_to_ai, monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_CHANNELS", [GENEL, YONETIM])
    assert _query("SELECT status FROM channels WHERE slack_id = ?", (DEV,)) == [("allowed",)]
    _assert_refused(_ask("ali", "#dev'i özetle"), sent_to_ai, "CHANNEL_NOT_ALLOWED", DEV)
    answer = _ask("ali", QUESTION_NO_CHANNEL)
    assert {s.channel for s in answer.sources} == {"genel"}


def test_list_warning_logged_when_authorization_stops_first(fixture_accounts, monkeypatch, caplog):
    monkeypatch.setattr(settings, "ALLOWED_CHANNELS", ["dev"])
    with caplog.at_level(logging.WARNING, logger="agentstack"):
        assert _ask("ali", "#dev'i özetle").status == "no_access"
    assert "ALLOWED_CHANNELS now takes channel IDs" in caplog.text


# --- The role plays no part


@pytest.mark.parametrize("question", ["#dev'i özetle", "#yonetim'de neler var?", QUESTION_NO_CHANNEL, "#ik"])
def test_same_memberships_same_result_for_user_and_admin(fixture_accounts, sent_to_ai, question):
    person = _person("admin_linked")
    as_admin = gateway.handle_question(question, replace(person, role="admin"))
    as_user = gateway.handle_question(question, replace(person, role="user"))
    assert (as_admin.status, as_admin.answer, as_admin.sources) == (as_user.status, as_user.answer, as_user.sources)
    assert len(set(sent_to_ai)) <= 1


# --- Defense in depth


def _without_authorization():
    return [(name, step) for name, step in gateway.STEPS if name != "authorization"]


@pytest.mark.parametrize("question", ["#dev'i özetle", QUESTION_NO_CHANNEL])
def test_without_authorization_step_nothing_is_read(fixture_accounts, sent_to_ai, monkeypatch, caplog, question):
    monkeypatch.setattr(gateway, "STEPS", _without_authorization())
    with caplog.at_level(logging.ERROR, logger="agentstack"):
        answer = _ask("ayse", question)
    assert (answer.status, answer.answer, answer.sources) == ("no_access", gateway.NO_ACCESS_ANSWER, [])
    assert ai.fake_call_count() == 0
    assert sent_to_ai == []
    assert _steps()[-1] == ("data_selection", "stopped", None, None, 0)
    assert f"request {answer.request_id}" in caplog.text
    assert question not in caplog.text


def test_authorization_left_empty_reads_nothing(fixture_accounts, sent_to_ai, monkeypatch):
    steps = [(name, (lambda c: None) if name == "authorization" else step) for name, step in gateway.STEPS]
    monkeypatch.setattr(gateway, "STEPS", steps)
    assert _ask("ayse", "#dev'i özetle").status == "no_access"
    assert sent_to_ai == []


def test_no_person_at_authorization_is_refused(sent_to_ai, monkeypatch):
    monkeypatch.setattr(gateway, "STEPS", [s for s in gateway.STEPS if s[0] != "identity"])
    answer = gateway.handle_question("#dev'i özetle", None)
    assert answer.status == "no_access"
    assert sent_to_ai == []
    assert [row[:3] for row in _steps()] == [("authorization", "stopped", "NO_SLACK_ACCOUNT")]


@pytest.fixture
def seeded():
    connection = connect(settings.DATABASE_PATH)
    yield connection
    connection.close()


def test_select_messages_reads_only_readable_channels(seeded):
    selection = select_messages(seeded, QUESTION_NO_CHANNEL, readable_channel_ids=[GENEL])
    assert {m.channel for m in selection.messages} == {"genel"}


@pytest.mark.parametrize("question", ["#dev'i özetle", QUESTION_NO_CHANNEL])
def test_select_messages_with_empty_set_reads_nothing(seeded, question):
    assert select_messages(seeded, question, readable_channel_ids=[]).messages == []


def test_select_messages_has_no_default_set(seeded):
    with pytest.raises(TypeError):
        select_messages(seeded, QUESTION_NO_CHANNEL)


@pytest.fixture
def channels_of_every_kind(seeded):
    """An excluded channel and a channel with an allowed row; both have a message."""
    with seeded:
        seeded.execute("INSERT INTO channels (slack_id, name, is_private, status) VALUES ('C0OLD', 'old', 0, 'excluded')")
        seeded.execute("INSERT INTO channels (slack_id, name, is_private, status) VALUES ('C_IK', 'ik', 1, 'allowed')")
    _add_message("C0OLD", 1, "TEST - excluded message")
    _add_message("C_IK", 2, "TEST - ik message")


@pytest.mark.parametrize("wrong_id, question", [
    ("C0OLD", "#old"), ("C0OLD", QUESTION_NO_CHANNEL),
    ("C_IK", "#ik"), ("C_IK", QUESTION_NO_CHANNEL),
    ("C0NOTINTABLE", "#yok"), ("C0NOTINTABLE", QUESTION_NO_CHANNEL),
])
def test_wrong_authorization_decision_opens_no_channel(seeded, channels_of_every_kind, wrong_id, question):
    selection = select_messages(seeded, question, readable_channel_ids=[wrong_id])
    assert selection.messages == []


@pytest.mark.parametrize("wrong_id", ["C0OLD", "C_IK", "C0NOTINTABLE"])
def test_wrong_decision_and_wrong_target_open_no_channel(seeded, channels_of_every_kind, monkeypatch, wrong_id):
    # Authorization AND the target decision are wrong: the settings and the query still keep the channel closed.
    monkeypatch.setattr(selection_module, "find_target_channels", lambda question, c: ("ok", [wrong_id, GENEL]))
    selection = select_messages(seeded, "herhangi", readable_channel_ids=[wrong_id, GENEL])
    assert {m.channel for m in selection.messages} == {"genel"}


# --- Memberships are read on every question (stale access ends with the next sync)


def test_removed_membership_ends_access_on_the_next_question(fixture_accounts, sent_to_ai):
    person = _person("ayse")
    assert gateway.handle_question("#yonetim", person).status == "ok"
    _write(
        "DELETE FROM channel_memberships WHERE channel_id = ? AND slack_user_id = ?",
        (YONETIM, person.slack_user_id),
    )
    answer = gateway.handle_question("#yonetim", person)
    assert answer.status == "no_access"
    assert ai.fake_call_count() == 1


def test_added_membership_gives_access_on_the_next_question(fixture_accounts, sent_to_ai):
    person = _person("ali")
    assert gateway.handle_question("#yonetim", person).status == "no_access"
    _write(
        "INSERT INTO channel_memberships (channel_id, slack_user_id, updated_at) "
        "VALUES (?, ?, '2026-11-04T00:00:00+00:00')",
        (YONETIM, person.slack_user_id),
    )
    assert gateway.handle_question("#yonetim", person).status == "ok"


# --- Linked, but without memberships


def _linked_without_memberships():
    _write("DELETE FROM channel_memberships WHERE slack_user_id = ?", (ALI_SLACK,))
    return _person("ali")


def test_linked_without_memberships_named_channel(fixture_accounts, sent_to_ai):
    _linked_without_memberships()
    _assert_refused(_ask("ali", "#dev'i özetle"), sent_to_ai, "NOT_CHANNEL_MEMBER", DEV)


def test_linked_without_memberships_no_channel_name(fixture_accounts, sent_to_ai):
    answer = gateway.handle_question(QUESTION_NO_CHANNEL, _linked_without_memberships())
    assert (answer.status, answer.answer, answer.sources) == ("ok", gateway.NO_MESSAGES_ANSWER, [])
    assert ai.fake_call_count() == 0
    assert sent_to_ai == []
    assert _steps() == [
        ("identity", "passed", None, None, 0),
        ("authorization", "passed", None, None, 0),
        ("data_selection", "stopped", "NO_MESSAGES", None, 0),
    ]


def test_linked_account_that_slack_users_does_not_know_reads_nothing(fixture_accounts, sent_to_ai):
    person = replace(_person("ali"), slack_user_id="U0NOTINTABLE")
    _assert_refused(gateway.handle_question("#dev", person), sent_to_ai, "NOT_CHANNEL_MEMBER", DEV)


def _empty_slack_tables():
    for table in ("channel_memberships", "messages", "channels"):
        _write(f"DELETE FROM {table}")


@pytest.mark.parametrize("question", ["#dev'i özetle", QUESTION_NO_CHANNEL])
def test_no_slack_data_for_a_linked_person(fixture_accounts, sent_to_ai, question):
    _empty_slack_tables()
    answer = _ask("ali", question)
    assert (answer.status, answer.answer) == ("ok", gateway.NO_MESSAGES_ANSWER)
    assert _steps() == [
        ("identity", "passed", None, None, 0),
        ("authorization", "passed", None, None, 0),
        ("data_selection", "stopped", "NO_SLACK_DATA", None, 0),
    ]


def test_no_slack_data_for_a_person_without_slack(fixture_accounts, sent_to_ai):
    _empty_slack_tables()
    _assert_refused(_ask("unlinked", "#dev'i özetle"), sent_to_ai, "NO_SLACK_ACCOUNT")


# --- No text


def test_no_text_in_events_or_logs_on_refusal(fixture_accounts, sent_to_ai, caplog):
    marker = "TEST-MARKER-refused-3e7b"
    with caplog.at_level(logging.DEBUG):
        _ask("ali", f"#yonetim {marker}")
        _ask("unlinked", f"#dev {marker}")
    rows = _query("SELECT * FROM audit_events")
    assert len(rows) == 4
    stored = " ".join(str(value) for row in rows for value in row)
    assert marker not in stored
    assert marker not in caplog.text
