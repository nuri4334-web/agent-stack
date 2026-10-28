"""S2-01: the shared identity test fixtures (client_as, anonymous_client, sent_to_ai) work as promised."""
import pytest
from fastapi import FastAPI, Response

from app import ai, settings
from app.database.schema import connect
from app.main import app
from tests.auth_clients import (
    FIXTURE_ACCOUNTS, LOGIN_PATH, SESSION_COOKIE, TEST_PASSWORD, has_login_route, make_client_as,
)


def _app_with_login(status_code, set_cookie):
    """A small app whose fake login endpoint answers with the given status, records what it received."""
    small = FastAPI()
    small.state.received = []

    @small.post(LOGIN_PATH)
    def login(body: dict, response: Response):
        small.state.received.append(body)
        response.status_code = status_code
        if set_cookie:
            response.set_cookie(SESSION_COOKIE, "TEST-session", httponly=True, secure=True, samesite="lax")
        return {}

    return small


@pytest.mark.parametrize("name", sorted(FIXTURE_ACCOUNTS))
def test_client_as_every_account_https_client(client_as, name):
    c = client_as(name)
    assert str(c.base_url) == "https://testserver"
    assert not c.cookies  # no login endpoint yet (S2-03)


def test_client_as_unknown_name_fails(client_as):
    with pytest.raises(pytest.fail.Exception) as error:
        client_as("nuri")
    assert "unknown test account 'nuri'" in str(error.value)
    assert "admin_linked" in str(error.value)


def test_client_as_without_login_route_is_cookieless(client_as):
    assert not has_login_route(app)
    assert not client_as("ali").cookies


def test_client_as_fails_if_login_route_rejects():
    small = _app_with_login(401, set_cookie=False)
    with pytest.raises(pytest.fail.Exception) as error:
        make_client_as(small, "ali")
    assert "login returned 401" in str(error.value)


def test_client_as_fails_if_login_sets_no_cookie():
    small = _app_with_login(200, set_cookie=False)
    with pytest.raises(pytest.fail.Exception) as error:
        make_client_as(small, "ali")
    assert SESSION_COOKIE in str(error.value)


def test_client_as_keeps_session_cookie_on_success():
    small = _app_with_login(200, set_cookie=True)
    c = make_client_as(small, "ayse")
    assert c.cookies[SESSION_COOKIE] == "TEST-session"
    assert small.state.received == [{"username": "ayse", "password": TEST_PASSWORD}]


def test_anonymous_client_https_and_cookieless(anonymous_client):
    c = anonymous_client()
    assert str(c.base_url) == "https://testserver"
    assert not c.cookies
    assert c is not anonymous_client()


def test_sent_to_ai_captures_and_counter_starts_at_zero(sent_to_ai, anonymous_client):
    assert ai.fake_call_count() == 0
    assert sent_to_ai == []
    r = anonymous_client().post("/api/ask", json={"question": "#dev'i özetle"})
    assert r.status_code == 200
    assert ai.fake_call_count() == 1
    assert len(sent_to_ai) == 1
    assert "[#dev | " in sent_to_ai[0]


def _memberships(slack_user_id):
    connection = connect(settings.DATABASE_PATH)
    try:
        return {name for (name,) in connection.execute(
            "SELECT c.name FROM channel_memberships m JOIN channels c ON c.slack_id = m.channel_id "
            "WHERE m.slack_user_id = ?", (slack_user_id,),
        )}
    finally:
        connection.close()


def test_fixture_accounts_match_seed_memberships():
    accounts = FIXTURE_ACCOUNTS
    assert {n: a.role for n, a in accounts.items()} == {
        "ali": "user", "ayse": "user", "admin": "admin", "unlinked": "user", "admin_linked": "admin",
    }
    assert all(a.username == n for n, a in accounts.items())
    assert _memberships(accounts["ali"].slack_user_id) == {"dev", "genel"}
    assert _memberships(accounts["ayse"].slack_user_id) == {"dev", "genel", "yonetim"}
    assert _memberships(accounts["admin_linked"].slack_user_id) == {"dev", "genel"}
    assert accounts["admin"].slack_user_id is None
    assert accounts["unlinked"].slack_user_id is None
    assert len(TEST_PASSWORD) >= 12
