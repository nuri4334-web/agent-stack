"""S4-03 (implementer's own tests): GET /api/channels (API contract 9a) and the rule behind it."""
import pytest

from app import settings
from app.data_selection.rules import decide_access, listable_channel_names
from app.data_selection.selection import member_channel_ids, question_time_channels
from app.database.schema import connect
from tests.auth_clients import FIXTURE_ACCOUNTS, set_session_cookie

PATH = "/api/channels"
DEV, GENEL, YONETIM = "C0C83M051QD", "C0C8ATRM073", "C0CB44VUCF2"


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


def _names(client):
    r = client.get(PATH)
    assert r.status_code == 200
    return [c["name"] for c in r.json()["channels"]]


def _add_channel(slack_id, name, status="allowed", members=()):
    _write("INSERT INTO channels (slack_id, name, is_private, status) VALUES (?, ?, 0, ?)", (slack_id, name, status))
    for user in members:
        _write(
            "INSERT INTO channel_memberships (channel_id, slack_user_id, updated_at) VALUES (?, ?, ?)",
            (slack_id, user, "2026-10-24T00:00:00+00:00"),
        )


def _allow(monkeypatch, *ids):
    monkeypatch.setattr(settings, "ALLOWED_CHANNELS", list(settings.ALLOWED_CHANNELS) + list(ids))


ALI = FIXTURE_ACCOUNTS["ali"].slack_user_id


# --- K1: no session
def test_no_session_is_401(anonymous_client):
    r = anonymous_client().get(PATH)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_made_up_token_is_401(anonymous_client):
    client = anonymous_client()
    set_session_cookie(client, "a" * 43)
    assert client.get(PATH).status_code == 401


def test_expired_session_is_401(client_as):
    client = client_as("ali")
    assert client.get(PATH).status_code == 200
    _write("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
    assert client.get(PATH).status_code == 401


def test_inactive_account_is_401(client_as):
    client = client_as("ali")
    _write("UPDATE people SET is_active = 0 WHERE username = 'ali'")
    r = client.get(PATH)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


# --- K2, K3
def test_ali_and_ayse(client_as):
    assert _names(client_as("ali")) == ["dev", "genel"]
    assert _names(client_as("ayse")) == ["dev", "genel", "yonetim"]


@pytest.mark.parametrize("name", ["admin", "unlinked"])
def test_no_slack_account_gets_an_empty_list(client_as, name):
    r = client_as(name).get(PATH)
    assert r.status_code == 200
    assert r.json() == {"channels": []}


def test_admin_role_gives_no_channel(client_as):
    # admin_linked is an admin and not a member of #yonetim
    assert "yonetim" not in _names(client_as("admin_linked"))


# --- K4: blocked and excluded channels are never listed, even for a member
def test_blocked_and_excluded_never_listed(client_as, monkeypatch):
    _add_channel("C_IK", "ik", status="blocked", members=[ALI])
    _allow(monkeypatch, "C_IK")  # even if the settings wrongly allowed it, the table status blocks it
    _add_channel("CEXCL", "gizli", status="excluded", members=[ALI])
    assert _names(client_as("ali")) == ["dev", "genel"]


def test_channel_blocked_in_settings_is_not_listed(client_as, monkeypatch):
    monkeypatch.setattr(settings, "BLOCKED_CHANNELS", [DEV])
    assert _names(client_as("ali")) == ["genel"]


# --- K5: only "name"
def test_response_has_only_names(client_as):
    body = client_as("ali").get(PATH).json()
    assert list(body) == ["channels"]
    assert all(list(item) == ["name"] for item in body["channels"])
    assert DEV not in client_as("ali").get(PATH).text


# --- technical decisions (a), (b), and the read-back guard
def test_duplicate_rows_with_one_name_are_not_listed(client_as, monkeypatch):
    _add_channel("CDUP1", "dev", members=[ALI])
    _allow(monkeypatch, "CDUP1")
    assert _names(client_as("ali")) == ["genel"]


def test_duplicate_after_normalization_is_not_listed(client_as, monkeypatch):
    _add_channel("CDUP2", "Genel", members=[ALI])
    _allow(monkeypatch, "CDUP2")
    assert _names(client_as("ali")) == ["dev"]


def test_all_digit_name_is_not_listed(client_as, monkeypatch):
    _add_channel("C2026", "2026", members=[ALI])
    _allow(monkeypatch, "C2026")
    assert _names(client_as("ali")) == ["dev", "genel"]


@pytest.mark.parametrize("name", ["foo bar", "dev.x", "dev'x"])
def test_name_that_is_read_back_differently_is_not_listed(client_as, monkeypatch, name):
    _add_channel("CODD1", name, members=[ALI])
    _allow(monkeypatch, "CODD1")
    assert _names(client_as("ali")) == ["dev", "genel"]


def test_name_is_the_normalized_name(client_as, monkeypatch):
    _add_channel("CUP1", "Proje-1", members=[ALI])
    _allow(monkeypatch, "CUP1")
    assert _names(client_as("ali")) == ["dev", "genel", "proje-1"]


# --- same decision as at question time
def test_every_listed_name_passes_and_every_other_is_refused():
    connection = connect(settings.DATABASE_PATH)
    try:
        channels = question_time_channels(connection)
        for account in ("ali", "ayse", "admin_linked"):
            members = member_channel_ids(connection, FIXTURE_ACCOUNTS[account].slack_user_id)
            listed = listable_channel_names(channels, members)
            for _, name, _ in channels:
                n = name.lower()
                passes = not decide_access(f"#{n}", channels, members, slack_linked=True).reason_code
                assert (n in listed) == passes
    finally:
        connection.close()


# --- every request reads the database
def test_membership_and_setting_changes_count_at_once(client_as, monkeypatch):
    client = client_as("ali")
    assert _names(client) == ["dev", "genel"]
    _write("DELETE FROM channel_memberships WHERE channel_id = ? AND slack_user_id = ?", (GENEL, ALI))
    assert _names(client) == ["dev"]
    monkeypatch.setattr(settings, "ALLOWED_CHANNELS", [GENEL])
    assert _names(client) == []


# --- K6: no AI, no audit row
def test_no_ai_call_and_no_audit_rows(client_as, anonymous_client, sent_to_ai):
    client = client_as("ali")  # sign-in first: it is not the endpoint's business
    anonymous = anonymous_client()
    before = _query("SELECT COUNT(*) FROM audit_events")[0][0]
    assert client.get(PATH).status_code == 200
    assert anonymous.get(PATH).status_code == 401
    assert _query("SELECT COUNT(*) FROM audit_events")[0][0] == before
    assert sent_to_ai == []


def test_list_works_when_the_detector_is_unavailable(client_as, detector_unavailable):
    assert _names(client_as("ali")) == ["dev", "genel"]


def test_no_cache_header_is_added(client_as):
    assert "cache-control" not in client_as("ali").get(PATH).headers
