"""S2-01: the shared identity test fixtures (client_as, anonymous_client, sent_to_ai) work as promised."""
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from app import ai, settings
from app.accounts.rules import verify_password
from app.database.schema import connect
from app.main import app
from tests.auth_clients import (
    FIXTURE_ACCOUNTS, LOGIN_PATH, MESSAGE_LINE, SESSION_COOKIE, TEST_PASSWORD,
    channels_sent_to_ai, has_login_route, make_anonymous_client, make_client_as, session_cookie,
    set_session_cookie,
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


def test_fixture_accounts_written_to_database(fixture_accounts):
    connection = connect(settings.DATABASE_PATH)
    try:
        rows = connection.execute(
            "SELECT p.username, p.display_name, p.role, p.is_active, p.password_hash, a.source_account_id "
            "FROM people p LEFT JOIN linked_accounts a ON a.person_id = p.id AND a.source = 'slack'"
        ).fetchall()
    finally:
        connection.close()
    assert {r[0]: (r[1], r[2], r[5]) for r in rows} == {
        a.username: (a.name, a.role, a.slack_user_id) for a in FIXTURE_ACCOUNTS.values()
    }
    assert all(r[3] == 1 for r in rows)
    for r in rows:
        assert TEST_PASSWORD not in r[4]
        assert verify_password(r[4], TEST_PASSWORD)


def test_people_empty_without_fixture_accounts():
    connection = connect(settings.DATABASE_PATH)
    try:
        assert connection.execute("SELECT count(*) FROM people").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM linked_accounts").fetchone() == (0,)
    finally:
        connection.close()


def _ask(anonymous_client, question):
    r = anonymous_client().post("/api/ask", json={"question": question})
    assert r.status_code == 200
    return r.json()


def test_channels_sent_to_ai_one_channel(sent_to_ai, anonymous_client):
    _ask(anonymous_client, "#dev'i özetle")
    assert channels_sent_to_ai(sent_to_ai) == [{"dev"}]


def test_channels_sent_to_ai_no_channel_name(sent_to_ai, anonymous_client):
    _ask(anonymous_client, "geçen hafta neler oldu?")
    assert channels_sent_to_ai(sent_to_ai) == [{"dev", "genel", "yonetim"}]


def test_channels_sent_to_ai_empty_if_ai_not_called(sent_to_ai, anonymous_client):
    assert _ask(anonymous_client, "#ik'i özetle")["status"] == "no_access"
    assert channels_sent_to_ai(sent_to_ai) == []


def _dev_texts():
    connection = connect(settings.DATABASE_PATH)
    try:
        return [t for (t,) in connection.execute(
            "SELECT m.clean_text FROM messages m JOIN channels c ON c.slack_id = m.channel_id WHERE c.name = 'dev'"
        )]
    finally:
        connection.close()


def test_message_line_pattern_matches_gateway_format(sent_to_ai, anonymous_client):
    # Goes red if the line format of gateway.ask_ai changes without MESSAGE_LINE.
    _ask(anonymous_client, "#dev'i özetle")
    _, marker, block = sent_to_ai[0].partition("Relevant messages:\n")
    assert marker
    lines = block.split("\n")
    texts = _dev_texts()
    matching = [line for line in lines if MESSAGE_LINE.match(line)]
    assert len(matching) == len(texts) == 27
    # Every other line is the continuation of a message text with a line break.
    assert len(lines) - len(matching) == sum(t.count("\n") for t in texts)


def _cookie_echo_app():
    small = FastAPI()

    @small.get("/echo")
    def echo(request: Request):
        return {"cookie": request.headers.get("cookie")}

    return small


def test_set_session_cookie_is_sent_on_next_request():
    c = make_anonymous_client(_cookie_echo_app())
    assert session_cookie(c) is None
    set_session_cookie(c, "TEST-made-up-token")
    assert session_cookie(c) == "TEST-made-up-token"
    assert c.get("/echo").json() == {"cookie": f"{SESSION_COOKIE}=TEST-made-up-token"}


def test_set_session_cookie_replaces_login_cookie():
    small = _app_with_login(200, set_cookie=True)
    c = make_client_as(small, "ali")
    set_session_cookie(c, "TEST-logged-out-token")
    assert session_cookie(c) == "TEST-logged-out-token"
    assert len(c.cookies.jar) == 1


def test_set_session_cookie_is_secure():
    c = TestClient(_cookie_echo_app())  # http://testserver
    set_session_cookie(c, "TEST-made-up-token")
    assert c.get("/echo").json() == {"cookie": None}
