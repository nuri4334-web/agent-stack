"""S2-11: authorization attack tests, written before the authorization code exists.

The attacker's view: these tests use only docs/api-contract.md v3 and the fixtures in
tests/conftest.py and tests/auth_clients.py, never the implementation.

- xfail(strict=True, raises=AssertionError) only where the protection is still missing;
  a test that already passes today stays a normal test (regression guard).
- "The AI was not called" is checked with the fake provider's counter and sent_to_ai,
  never with `sources` (empty until S2-05).
"""
import pytest

from app.ai import fake_call_count, reset_fake_counter
from tests.auth_clients import (
    LOGIN_PATH,
    TEST_PASSWORD,
    channels_sent_to_ai,
    session_cookie,
    set_session_cookie,
)

ASK = "/api/ask"
LOGOUT = "/api/auth/logout"
EVENTS = "/api/admin/events"

STAGE2 = "Stage 2: identity and authorization not implemented yet"


def ask(client, question, **extra):
    return client.post(ASK, json={"question": question, **extra})


@pytest.fixture(autouse=True)
def _reset_counter():
    reset_fake_counter()


# --- Channel membership -----------------------------------------------------------------

@pytest.mark.xfail(strict=True, raises=AssertionError, reason=STAGE2)
def test_ali_asks_private_channel_he_is_not_in(client_as, sent_to_ai):
    """Ali asks about #yonetim, which he is not a member of: no_access and the AI is never called."""
    r = ask(client_as("ali"), "#yonetim'de neler konuşuldu?")
    assert r.status_code == 200
    assert r.json()["status"] == "no_access"
    assert r.json()["sources"] == []
    assert fake_call_count() == 0
    assert sent_to_ai == []


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=STAGE2)
def test_ali_general_question_does_not_leak_yonetim(client_as, sent_to_ai):
    """Ali asks without naming a channel: only his own channels reach the AI, never #yonetim."""
    r = ask(client_as("ali"), "geçen hafta neler oldu?")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert fake_call_count() == 1
    assert channels_sent_to_ai(sent_to_ai) == [{"dev", "genel"}]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=STAGE2)
def test_admin_role_gives_no_channel_access(client_as, sent_to_ai):
    """An admin linked to a Slack account outside #yonetim asks about it: the role gives no channel access."""
    r = ask(client_as("admin_linked"), "#yonetim'de neler konuşuldu?")
    assert r.status_code == 200
    assert r.json()["status"] == "no_access"
    assert fake_call_count() == 0
    assert sent_to_ai == []


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=STAGE2)
def test_unlinked_user_sees_no_channel_data(client_as, sent_to_ai):
    """A user without a linked Slack account asks about #dev: no_access and no channel data reaches the AI."""
    r = ask(client_as("unlinked"), "#dev'i özetle")
    assert r.status_code == 200
    assert r.json()["status"] == "no_access"
    assert fake_call_count() == 0
    assert sent_to_ai == []


def test_blocklisted_channel_is_always_refused(client_as, sent_to_ai):
    """Ayşe, who may read #yonetim, asks about blocklisted #ik: refused already today, must stay refused."""
    r = ask(client_as("ayse"), "#ik'i özetle")
    assert r.status_code == 200
    assert r.json()["status"] == "no_access"
    assert fake_call_count() == 0
    assert sent_to_ai == []


# --- Identity ---------------------------------------------------------------------------

def test_user_field_cannot_impersonate_ayse(client_as, sent_to_ai):
    """Ali adds the old "user": "ayse" field to act as Ayşe: 422 and the AI is never called."""
    r = ask(client_as("ali"), "#yonetim'de neler konuşuldu?", user="ayse")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_REQUEST"
    assert fake_call_count() == 0
    assert sent_to_ai == []


def test_request_without_session_is_rejected(anonymous_client, sent_to_ai):
    """A request with no session asks about #dev: 401 UNAUTHENTICATED and the AI is never called."""
    r = ask(anonymous_client(), "#dev'i özetle")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    assert fake_call_count() == 0
    assert sent_to_ai == []


def test_forged_session_cookie_is_rejected(anonymous_client, sent_to_ai):
    """An attacker sends a made-up session cookie: 401 and the AI is never called."""
    client = anonymous_client()
    set_session_cookie(client, "forged-EXAMPLE-" + "0" * 43)
    r = ask(client, "#dev'i özetle")
    assert r.status_code == 401
    assert fake_call_count() == 0
    assert sent_to_ai == []


def test_logged_out_cookie_cannot_be_replayed(client_as, sent_to_ai):
    """Ali logs out and replays his old session cookie: 401, the server deleted the session."""
    client = client_as("ali")
    old_token = session_cookie(client)
    assert old_token, "client_as('ali') should hold a session cookie"
    assert client.post(LOGOUT).status_code == 204
    set_session_cookie(client, old_token)
    r = ask(client, "#dev'i özetle")
    assert r.status_code == 401
    assert fake_call_count() == 0
    assert sent_to_ai == []


# --- Admin-only endpoint ----------------------------------------------------------------

def test_non_admin_cannot_read_event_list(client_as):
    """Ali, who is not an admin, asks for the security event list: 403 FORBIDDEN."""
    r = client_as("ali").get(EVENTS)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


# --- Brute force ------------------------------------------------------------------------

def test_wrong_passwords_lock_the_username(anonymous_client, fixture_accounts):
    """An attacker tries 5 wrong passwords for "ali": the 6th attempt gets 429, even with the right password."""
    client = anonymous_client()
    for i in range(5):
        r = client.post(LOGIN_PATH, json={"username": "ali", "password": f"wrong-EXAMPLE-{i}"})
        assert r.status_code == 401
    r = client.post(LOGIN_PATH, json={"username": "ali", "password": TEST_PASSWORD})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    assert int(r.headers["Retry-After"]) > 0
