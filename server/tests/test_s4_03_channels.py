"""S4-03 acceptance tests: the channels a person can ask about, GET /api/channels (API contract v5, section 9a).

Written by the test chat (A) before the code, from the task card only (Sprint 4 guide, Nuri, S4-03 and section 2).
The implementer does not change this file.

K1  No session -> 401 UNAUTHENTICATED (also a made-up, an expired session and an inactive account).
K2  Ali -> ["dev", "genel"]; Ayşe -> ["dev", "genel", "yonetim"] (sorted by name).
K3  An admin without a linked Slack account -> empty list (the role gives no channel).
K4  The blocked #ik and excluded channels are never listed, even if the person's Slack account is a member.
K5  The answer has no channel id and no other field: only "name".
K6  The AI is not called; no audit event is written.

The card's tip: the list comes from the same rule as the question ("a second rule would make the screen lie").
So the list is also checked against the gateway itself: every listed channel can really be asked about, and every
channel that is not listed gets no_access when asked by name.
Decisions (test chat, 23 Nov):
- A name with two rows in the channels table (e.g. a stale old row) is refused at question time, so it is not listed.
- A name made only of digits (#2026) is not read as a channel name in a question, so it is not listed.
- The list does not need the hidden instruction detector: it works the same with detector_unavailable.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import ai, gateway, main, settings
from app.accounts import store
from app.accounts.rules import SignedInPerson, new_session_token
from app.database.schema import connect
from app.main import app
from tests.auth_clients import FIXTURE_ACCOUNTS, TEST_PASSWORD, set_session_cookie

CHANNELS = "/api/channels"
LOGIN = "/api/auth/login"
DEV, GENEL, YONETIM = "C0C83M051QD", "C0C8ATRM073", "C0CB44VUCF2"
ALI_SLACK = FIXTURE_ACCOUNTS["ali"].slack_user_id
UNAUTHENTICATED = {"error": {"code": "UNAUTHENTICATED", "message": "Please sign in."}}
EXPECTED = {
    "ali": ["dev", "genel"],
    "ayse": ["dev", "genel", "yonetim"],
    "admin": [],
    "unlinked": [],
    "admin_linked": ["dev", "genel"],
}


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


def _add_channel(slack_id, name, status, member=ALI_SLACK):
    _write("INSERT INTO channels (slack_id, name, is_private, status) VALUES (?, ?, 0, ?)", (slack_id, name, status))
    if member:
        _add_member(slack_id, member)


def _add_member(channel_id, slack_user_id):
    _write(
        "INSERT INTO channel_memberships (channel_id, slack_user_id, updated_at) "
        "VALUES (?, ?, '2026-11-23T00:00:00+00:00')",
        (channel_id, slack_user_id),
    )


def _names(client):
    r = client.get(CHANNELS)
    assert r.status_code == 200
    return [channel["name"] for channel in r.json()["channels"]]


def _person(username):
    account = FIXTURE_ACCOUNTS[username]
    person_id = _query("SELECT id FROM people WHERE username = ?", (username,))[0][0]
    return SignedInPerson(
        id=person_id, username=username, display_name=account.name, role=account.role,
        slack_user_id=account.slack_user_id,
    )


def _gateway_events():
    return _query("SELECT count(*) FROM audit_events WHERE step NOT IN ('login', 'logout')")[0][0]


@pytest.fixture
def clock(monkeypatch):
    """The server clock of the endpoints, moved by hand: clock.now = ..."""
    class Clock:
        now = datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(main, "_utc_now", lambda: Clock.now)
    return Clock


# --- K1: no session


def test_no_cookie_401(anonymous_client):
    r = anonymous_client().get(CHANNELS)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED


@pytest.mark.parametrize("token", ["TEST-made-up-token", None])
def test_made_up_or_unknown_token_401(fixture_accounts, anonymous_client, token):
    c = anonymous_client()
    set_session_cookie(c, token or new_session_token())
    r = c.get(CHANNELS)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED


def test_expired_session_401(fixture_accounts, anonymous_client, clock):
    c = anonymous_client()
    assert c.post(LOGIN, json={"username": "ali", "password": TEST_PASSWORD}).status_code == 200
    assert c.get(CHANNELS).status_code == 200
    clock.now += timedelta(hours=8)
    r = c.get(CHANNELS)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED


def test_inactive_account_401(client_as):
    c = client_as("ali")
    assert c.get(CHANNELS).status_code == 200
    connection = connect(settings.DATABASE_PATH)
    try:
        store.deactivate(connection, _person("ali").id)
    finally:
        connection.close()
    r = c.get(CHANNELS)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED


def test_inactive_flag_set_by_hand_401(client_as):
    c = client_as("ali")
    _write("UPDATE people SET is_active = 0 WHERE username = 'ali'")
    assert c.get(CHANNELS).status_code == 401


def test_401_writes_no_audit_event(anonymous_client):
    anonymous_client().get(CHANNELS)
    assert _query("SELECT count(*) FROM audit_events") == [(0,)]


# --- K2, K3: who gets which list


@pytest.mark.parametrize("username", list(EXPECTED))
def test_list_of_every_test_account(client_as, username):
    r = client_as(username).get(CHANNELS)
    assert r.status_code == 200
    assert r.json() == {"channels": [{"name": name} for name in EXPECTED[username]]}


def test_sorted_by_name_not_by_id_or_insert_order(client_as, monkeypatch):
    # Inserted last, with an id that sorts after the others: must still come first.
    monkeypatch.setattr(settings, "ALLOWED_CHANNELS", [*settings.ALLOWED_CHANNELS, "C0ZZARGE001"])
    _add_channel("C0ZZARGE001", "arge", "allowed")
    assert _names(client_as("ali")) == ["arge", "dev", "genel"]


def test_admin_role_gives_no_channel(client_as):
    # Same Slack account, the role changed by hand: the list stays the same.
    as_admin = _names(client_as("admin_linked"))
    _write("UPDATE people SET role = 'user' WHERE username = 'admin_linked'")
    assert _names(client_as("admin_linked")) == as_admin == ["dev", "genel"]


def test_admin_without_slack_gets_empty_list_even_with_yonetim_members(client_as):
    assert _query("SELECT count(*) FROM channel_memberships WHERE channel_id = ?", (YONETIM,))[0][0] > 0
    assert client_as("admin").get(CHANNELS).json() == {"channels": []}


def test_linked_without_memberships_empty_list(client_as):
    _write("DELETE FROM channel_memberships WHERE slack_user_id = ?", (ALI_SLACK,))
    assert client_as("ali").get(CHANNELS).json() == {"channels": []}


def test_no_slack_data_empty_list(client_as):
    for table in ("channel_memberships", "messages", "channels"):
        _write(f"DELETE FROM {table}")
    assert client_as("ali").get(CHANNELS).json() == {"channels": []}


def test_membership_change_counts_from_the_next_request(client_as):
    c = client_as("ali")
    assert _names(c) == ["dev", "genel"]
    _add_member(YONETIM, ALI_SLACK)
    assert _names(c) == ["dev", "genel", "yonetim"]
    _write("DELETE FROM channel_memberships WHERE channel_id = ? AND slack_user_id = ?", (DEV, ALI_SLACK))
    assert _names(c) == ["genel", "yonetim"]


def test_query_parameter_changes_nothing(client_as):
    c = client_as("ali")
    for path in (f"{CHANNELS}?all=1", f"{CHANNELS}?user=ayse", f"{CHANNELS}?channel=yonetim"):
        assert _names(c) == ["dev", "genel"]
        r = c.get(path)
        assert r.status_code == 200
        assert [ch["name"] for ch in r.json()["channels"]] == ["dev", "genel"]


# --- K4: blocked and excluded channels


def test_ik_with_a_stale_allowed_row_and_a_membership_is_not_listed(client_as):
    # C_IK is in BLOCKED_CHANNELS of the test settings; the table row says "allowed" (a stale row).
    _add_channel("C_IK", "ik", "allowed")
    assert _names(client_as("ali")) == ["dev", "genel"]


def test_ik_blocked_even_if_also_in_the_allow_list(client_as, monkeypatch):
    # The blocked list always wins.
    monkeypatch.setattr(settings, "ALLOWED_CHANNELS", [*settings.ALLOWED_CHANNELS, "C_IK"])
    _add_channel("C_IK", "ik", "allowed")
    assert "ik" not in _names(client_as("ali"))


@pytest.mark.parametrize("status", ["excluded", "blocked"])
def test_not_allowed_status_with_a_membership_is_not_listed(client_as, monkeypatch, status):
    # Even in the allow list of the settings: the table status must be allowed too.
    monkeypatch.setattr(settings, "ALLOWED_CHANNELS", [*settings.ALLOWED_CHANNELS, "C0OLD000001"])
    _add_channel("C0OLD000001", "old", status)
    assert _names(client_as("ali")) == ["dev", "genel"]


def test_allowed_row_not_in_the_allow_list_is_not_listed(client_as):
    # The table says allowed, the settings at request time do not (e.g. .env changed after the last sync).
    _add_channel("C0NEW000001", "aaa-yeni", "allowed")
    assert _names(client_as("ali")) == ["dev", "genel"]


def test_blocked_at_request_time_is_not_listed(client_as, monkeypatch):
    monkeypatch.setattr(settings, "BLOCKED_CHANNELS", [*settings.BLOCKED_CHANNELS, DEV])
    assert _names(client_as("ali")) == ["genel"]


def test_removed_from_allow_list_is_not_listed(client_as, monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_CHANNELS", [GENEL, YONETIM])
    assert _query("SELECT status FROM channels WHERE slack_id = ?", (DEV,)) == [("allowed",)]
    assert _names(client_as("ali")) == ["genel"]
    assert _names(client_as("ayse")) == ["genel", "yonetim"]


def test_settings_change_counts_from_the_next_request(client_as, monkeypatch):
    c = client_as("ali")
    assert _names(c) == ["dev", "genel"]
    monkeypatch.setattr(settings, "BLOCKED_CHANNELS", [*settings.BLOCKED_CHANNELS, GENEL])
    assert _names(c) == ["dev"]


def test_name_with_two_rows_is_not_listed(client_as):
    # A stale old row with the same name: a question about #dev is refused, so #dev must not be offered.
    _add_channel("C0DEVOLD001", "dev", "excluded", member=None)
    assert _names(client_as("ali")) == ["genel"]


def test_name_made_only_of_digits_is_not_listed(client_as, monkeypatch):
    # "#2026" in a question is not a channel name (it reads as a question about all channels).
    monkeypatch.setattr(settings, "ALLOWED_CHANNELS", [*settings.ALLOWED_CHANNELS, "C0DIGITS001"])
    _add_channel("C0DIGITS001", "2026", "allowed")
    assert _names(client_as("ali")) == ["dev", "genel"]


# --- The list and the question agree (same rule, no second rule)


# (#2026 is left out here: it is not a channel name in a question, so asking it is not refused; own test above.)
SETUPS = ["seed", "ik_stale", "excluded_member", "blocked_now", "removed_from_allow", "two_rows"]


def _setup(case, monkeypatch):
    if case == "ik_stale":
        _add_channel("C_IK", "ik", "allowed")
    elif case == "excluded_member":
        monkeypatch.setattr(settings, "ALLOWED_CHANNELS", [*settings.ALLOWED_CHANNELS, "C0OLD000001"])
        _add_channel("C0OLD000001", "old", "excluded")
    elif case == "blocked_now":
        monkeypatch.setattr(settings, "BLOCKED_CHANNELS", [*settings.BLOCKED_CHANNELS, DEV])
    elif case == "removed_from_allow":
        monkeypatch.setattr(settings, "ALLOWED_CHANNELS", [GENEL, YONETIM])
    elif case == "two_rows":
        _add_channel("C0DEVOLD001", "dev", "excluded", member=None)


@pytest.mark.parametrize("case", SETUPS)
@pytest.mark.parametrize("username", ["ali", "ayse", "admin_linked", "admin"])
def test_listed_exactly_when_the_question_is_allowed(client_as, monkeypatch, sent_to_ai, case, username):
    _setup(case, monkeypatch)
    listed = _names(client_as(username))
    person = _person(username)
    every_name = sorted({name for (name,) in _query("SELECT name FROM channels")} | {"ik", "yok"})
    for name in every_name:
        answer = gateway.handle_question(f"#{name}'i özetle", person)
        if name in listed:
            assert answer.status != "no_access", f"listed but refused: #{name}"
        else:
            assert answer.status == "no_access", f"not listed but asked: #{name}"


# --- K5: only names


@pytest.mark.parametrize("username", ["ayse", "admin_linked"])
def test_only_the_name_field_and_no_channel_id(client_as, username):
    r = client_as(username).get(CHANNELS)
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert set(body) == {"channels"}
    for channel in body["channels"]:
        assert set(channel) == {"name"}
        assert isinstance(channel["name"], str)
        assert not channel["name"].startswith("#")
    for slack_id in (DEV, GENEL, YONETIM, ALI_SLACK, FIXTURE_ACCOUNTS[username].slack_user_id):
        assert slack_id not in r.text


def test_no_names_of_unlisted_channels_in_the_body(client_as, monkeypatch):
    _add_channel("C_IK", "ik", "allowed")
    monkeypatch.setattr(settings, "ALLOWED_CHANNELS", [*settings.ALLOWED_CHANNELS, "C0OLD000001"])
    _add_channel("C0OLD000001", "gizli-eski", "excluded")
    r = client_as("ali").get(CHANNELS)
    assert r.json() == {"channels": [{"name": "dev"}, {"name": "genel"}]}
    for hidden in ('"ik"', "yonetim", "gizli-eski", "C_IK", "C0OLD000001"):
        assert hidden not in r.text


# --- K6: no AI, no event, no detector


@pytest.mark.parametrize("username", ["ali", "ayse", "admin", "unlinked"])
def test_ai_not_called_and_no_gateway_event(client_as, sent_to_ai, username):
    c = client_as(username)
    events_before = _query("SELECT count(*) FROM audit_events")[0][0]
    for _ in range(3):
        assert c.get(CHANNELS).status_code == 200
    assert sent_to_ai == []
    assert ai.fake_call_count() == 0
    assert _query("SELECT count(*) FROM ai_calls") == [(0,)]
    assert _query("SELECT count(*) FROM audit_events")[0][0] == events_before
    assert _gateway_events() == 0


def test_no_masked_or_suspicious_rows(client_as):
    client_as("ayse").get(CHANNELS)
    assert _query("SELECT count(*) FROM masked_texts") == [(0,)]
    assert _query("SELECT count(*) FROM suspicious_messages") == [(0,)]


def test_works_without_the_detector(client_as, detector_unavailable, sent_to_ai):
    r = client_as("ali").get(CHANNELS)
    assert r.status_code == 200
    assert r.json() == {"channels": [{"name": "dev"}, {"name": "genel"}]}
    assert sent_to_ai == []


# --- Method and person


def test_route_is_get_only(client_as):
    c = client_as("ali")
    assert c.post(CHANNELS, json={}).status_code == 405


def test_the_list_follows_the_signed_in_person_not_another(client_as):
    ali, ayse = client_as("ali"), client_as("ayse")
    assert _names(ali) == ["dev", "genel"]
    assert _names(ayse) == ["dev", "genel", "yonetim"]
    assert _names(ali) == ["dev", "genel"]
