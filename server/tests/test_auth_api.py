"""S2-03: login, logout, who am I, session rules and the session check of /api/ask (API contract 2, 5-8)."""
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import ai, gateway, main, settings
from app.accounts import login as login_flow
from app.accounts import rules, store
from app.accounts.rules import hash_session_token, new_session_token
from app.database.schema import connect
from app.main import app
from tests.auth_clients import (
    BASE_URL, FIXTURE_ACCOUNTS, LOGIN_PATH, SESSION_COOKIE, TEST_PASSWORD, TEST_PERSON, session_cookie,
    set_session_cookie,
)

ME_PATH = "/api/auth/me"
LOGOUT_PATH = "/api/auth/logout"
ASK_PATH = "/api/ask"
WRONG_PASSWORD = "TEST-wrong-password-2026"
QUESTION = {"question": "#dev'i özetle"}

INVALID_CREDENTIALS = {"error": {"code": "INVALID_CREDENTIALS", "message": "Username or password is incorrect."}}
TOO_MANY_ATTEMPTS = {"error": {"code": "TOO_MANY_ATTEMPTS", "message": "Too many login attempts. Try again later."}}
UNAUTHENTICATED = {"error": {"code": "UNAUTHENTICATED", "message": "Please sign in."}}
INVALID_REQUEST = {"error": {"code": "INVALID_REQUEST", "message": "Invalid request format. See the API contract."}}


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


def _person_id(username):
    return _query("SELECT id FROM people WHERE username = ?", (username,))[0][0]


def _deactivate_by_store(username):
    connection = connect(settings.DATABASE_PATH)
    try:
        store.deactivate(connection, _person_id(username))
    finally:
        connection.close()


def _login(c, username="ali", password=TEST_PASSWORD):
    return c.post(LOGIN_PATH, json={"username": username, "password": password})


def _events():
    return _query(
        "SELECT step, decision, reason_code, person_id FROM audit_events WHERE step IN ('login', 'logout') ORDER BY id"
    )


def _cookie_parts(response):
    """The attributes of the Set-Cookie line as a set of lower case texts, without the value."""
    return {part.strip().lower() for part in response.headers["set-cookie"].split(";")[1:]}


@pytest.fixture
def clock(monkeypatch):
    """The server clock of the auth endpoints, moved by hand: clock.now = ..."""
    class Clock:
        now = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(main, "_utc_now", lambda: Clock.now)
    return Clock


# --- Login


@pytest.mark.parametrize("username", ["ali", "ayse"])
def test_ali_and_ayse_log_in_with_own_password(fixture_accounts, anonymous_client, username):
    c = anonymous_client()
    r = _login(c, username)
    account = FIXTURE_ACCOUNTS[username]
    assert r.status_code == 200
    assert r.json() == {"username": username, "name": account.name, "role": "user", "slack_linked": True}
    assert session_cookie(c)


def test_login_body_of_account_without_slack(fixture_accounts, anonymous_client):
    r = _login(anonymous_client(), "admin")
    assert r.json() == {"username": "admin", "name": "Admin", "role": "admin", "slack_linked": False}


@pytest.mark.parametrize("written", [" ali ", "ALI", " Ali"])
def test_login_username_is_normalized(fixture_accounts, anonymous_client, written):
    r = _login(anonymous_client(), written)
    assert r.status_code == 200
    assert r.json()["username"] == "ali"


def _prepare_failure(case):
    """Sets up one failure reason; returns the user name and password of that login."""
    if case == "wrong_password":
        return "ali", WRONG_PASSWORD
    if case == "no_such_user":
        return "nobody", TEST_PASSWORD
    if case == "inactive":
        _write("UPDATE people SET is_active = 0 WHERE username = 'ali'")
        return "ali", TEST_PASSWORD
    if case == "no_password":
        _write("UPDATE people SET password_hash = NULL WHERE username = 'ali'")
        return "ali", TEST_PASSWORD
    assert case == "bad_format"
    return "!! not a user name !!", TEST_PASSWORD


FAILURE_CASES = ["wrong_password", "no_such_user", "inactive", "no_password", "bad_format"]


@pytest.mark.parametrize("case", FAILURE_CASES)
def test_all_login_failures_same_status_and_body(fixture_accounts, anonymous_client, case):
    username, password = _prepare_failure(case)
    c = anonymous_client()
    r = _login(c, username, password)
    assert r.status_code == 401
    assert r.json() == INVALID_CREDENTIALS
    assert "set-cookie" not in r.headers
    assert "retry-after" not in r.headers
    assert not c.cookies
    assert _query("SELECT count(*) FROM sessions") == [(0,)]


@pytest.mark.parametrize("case", FAILURE_CASES)
def test_every_login_failure_runs_scrypt_once(fixture_accounts, anonymous_client, monkeypatch, case):
    # A similar response time, measured without a clock: the slow step runs exactly once in every case.
    username, password = _prepare_failure(case)
    calls = []
    real = rules._scrypt

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(rules, "_scrypt", spy)
    assert _login(anonymous_client(), username, password).status_code == 401
    assert len(calls) == 1


@pytest.mark.parametrize("body", [
    {"username": "", "password": TEST_PASSWORD},
    {"username": "a" * 65, "password": TEST_PASSWORD},
    {"username": "ali", "password": ""},
    {"username": "ali", "password": "a" * 129},
    {"username": "ali"},
    {"password": TEST_PASSWORD},
    {"username": "ali", "password": TEST_PASSWORD, "role": "admin"},
])
def test_login_invalid_body_returns_422_and_is_not_counted(fixture_accounts, anonymous_client, body):
    c = anonymous_client()
    for _ in range(6):
        r = c.post(LOGIN_PATH, json=body)
        assert r.status_code == 422
        assert r.json() == INVALID_REQUEST
    assert _login(c).status_code == 200
    assert _events() == [("login", "passed", None, _person_id("ali"))]


@pytest.mark.parametrize("field", ["username", "password"])
def test_login_unencodable_text_returns_422_not_500(fixture_accounts, anonymous_client, field):
    values = {"username": "ali", "password": TEST_PASSWORD, field: "\\ud800"}
    content = '{"username": "%(username)s", "password": "%(password)s"}' % values
    r = anonymous_client().post(LOGIN_PATH, content=content, headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert r.json() == INVALID_REQUEST


@pytest.mark.parametrize("content, content_type", [
    ('{"username": "ali", "password": "TEST-password-2026"}', "text/plain"),
    ("{broken", "application/json"),
])
def test_login_non_json_returns_422(fixture_accounts, anonymous_client, content, content_type):
    r = anonymous_client().post(LOGIN_PATH, content=content, headers={"Content-Type": content_type})
    assert r.status_code == 422
    assert r.json() == INVALID_REQUEST


# --- Attempt limit


def test_five_failures_then_429_and_correct_password_also_429(fixture_accounts, anonymous_client, clock):
    c = anonymous_client()
    for _ in range(5):
        r = _login(c, password=WRONG_PASSWORD)
        assert r.status_code == 401
        assert r.json() == INVALID_CREDENTIALS
    r = _login(c, password=WRONG_PASSWORD)
    assert r.status_code == 429
    assert r.json() == TOO_MANY_ATTEMPTS
    assert r.headers["Retry-After"] == "900"
    clock.now += timedelta(seconds=60.5)
    r = _login(c)
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "840"
    assert "set-cookie" not in r.headers
    assert _query("SELECT count(*) FROM sessions") == [(0,)]


def test_429_same_for_existing_and_missing_username(fixture_accounts, anonymous_client, clock):
    answers = {}
    for username in ("ali", "nobody"):
        c = anonymous_client()
        for _ in range(5):
            assert _login(c, username, WRONG_PASSWORD).status_code == 401
        r = _login(c, username, WRONG_PASSWORD)
        answers[username] = (r.status_code, r.json(), r.headers["Retry-After"])
    assert answers["ali"] == answers["nobody"] == (429, TOO_MANY_ATTEMPTS, "900")


def test_limit_counts_normalized_username(fixture_accounts, anonymous_client):
    c = anonymous_client()
    for written in ("ali", "ALI", " ali", "Ali ", "aLi"):
        assert _login(c, written, WRONG_PASSWORD).status_code == 401
    assert _login(c, "ali").status_code == 429


def test_ip_limit_31st_attempt_is_429(fixture_accounts, anonymous_client, monkeypatch):
    # Thirty real scrypt runs add nothing here; the counter is what this test checks.
    monkeypatch.setattr(login_flow, "verify_password", lambda stored, password: False)
    c = anonymous_client()
    for number in range(30):
        assert _login(c, f"user{number}", WRONG_PASSWORD).status_code == 401
    r = _login(c, "another-user", WRONG_PASSWORD)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    other_ip = TestClient(app, base_url=BASE_URL, client=("203.0.113.9", 50000))
    assert _login(other_ip, "another-user", WRONG_PASSWORD).status_code == 401


def test_forwarded_header_does_not_change_the_ip(fixture_accounts, anonymous_client, monkeypatch):
    monkeypatch.setattr(login_flow, "verify_password", lambda stored, password: False)
    c = anonymous_client()
    for number in range(30):
        r = c.post(
            LOGIN_PATH, json={"username": f"user{number}", "password": WRONG_PASSWORD},
            headers={"X-Forwarded-For": f"198.51.100.{number}"},
        )
        assert r.status_code == 401
    r = c.post(
        LOGIN_PATH, json={"username": "another-user", "password": WRONG_PASSWORD},
        headers={"X-Forwarded-For": "198.51.100.200"},
    )
    assert r.status_code == 429


def test_login_works_again_after_window(fixture_accounts, anonymous_client, clock):
    c = anonymous_client()
    for _ in range(5):
        _login(c, password=WRONG_PASSWORD)
    clock.now += timedelta(minutes=15) - timedelta(seconds=1)
    assert _login(c).status_code == 429
    clock.now += timedelta(seconds=1)
    assert _login(c).status_code == 200


def test_success_resets_username_counter(fixture_accounts, anonymous_client):
    c = anonymous_client()
    for _ in range(4):
        assert _login(c, password=WRONG_PASSWORD).status_code == 401
    assert _login(c).status_code == 200
    for _ in range(5):
        assert _login(c, password=WRONG_PASSWORD).status_code == 401
    assert _login(c, password=WRONG_PASSWORD).status_code == 429


@pytest.mark.parametrize("round_number", [1, 2])
def test_login_counters_reset_between_tests(fixture_accounts, anonymous_client, round_number):
    # Passes in both rounds only if the conftest fixture really resets the counter.
    c = anonymous_client()
    for _ in range(5):
        assert _login(c, password=WRONG_PASSWORD).status_code == 401
    assert _login(c).status_code == 429


def test_temporary_failure_does_not_consume_attempt(fixture_accounts, monkeypatch):
    c = TestClient(app, base_url=BASE_URL, raise_server_exceptions=False)
    for _ in range(4):
        assert _login(c, password=WRONG_PASSWORD).status_code == 401
    real = login_flow.create_session

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("TEST - database is locked")

    monkeypatch.setattr(login_flow, "create_session", broken)
    for _ in range(3):
        r = _login(c)
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "SERVER_ERROR"
    monkeypatch.setattr(login_flow, "create_session", real)
    assert _login(c).status_code == 200


# --- Cookie and session


def test_cookie_attributes_secure_on(fixture_accounts, anonymous_client):
    r = _login(anonymous_client())
    assert _cookie_parts(r) == {"httponly", "secure", "samesite=lax", "path=/", "max-age=28800"}
    assert r.headers["set-cookie"].startswith(f"{SESSION_COOKIE}=")


def test_cookie_attributes_secure_off_by_setting(fixture_accounts, anonymous_client, monkeypatch):
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", False)
    r = _login(anonymous_client())
    assert _cookie_parts(r) == {"httponly", "samesite=lax", "path=/", "max-age=28800"}


@pytest.mark.parametrize("value, expected", [
    ("true", True), ("false", False), (" TRUE ", True), ("False", False),
])
def test_parse_bool_setting_accepts(value, expected):
    assert settings.parse_bool_setting("SESSION_COOKIE_SECURE", value) is expected


@pytest.mark.parametrize("value", ["", " ", "1", "0", "yes", "no", "on", "belki", "true false"])
def test_parse_bool_setting_refuses(value):
    with pytest.raises(ValueError) as error:
        settings.parse_bool_setting("SESSION_COOKIE_SECURE", value)
    assert str(error.value) == "SESSION_COOKIE_SECURE must be true or false."


@pytest.mark.parametrize("value, exit_code", [("belki", 1), ("false", 0)])
def test_invalid_secure_setting_stops_server(value, exit_code):
    done = subprocess.run(
        [sys.executable, "-B", "-c", "import app.main"],
        cwd=settings.ROOT / "server",
        env={**os.environ, "SESSION_COOKIE_SECURE": value},
        capture_output=True,
        text=True,
    )
    assert done.returncode == exit_code
    if exit_code:
        assert "SESSION_COOKIE_SECURE must be true or false." in done.stderr


def test_secure_setting_default_is_true():
    done = subprocess.run(
        [sys.executable, "-B", "-c", "import os, dotenv; dotenv.load_dotenv = lambda *a, **k: False; "
                                     "os.environ.pop('SESSION_COOKIE_SECURE', None); "
                                     "from app import settings; print(settings.SESSION_COOKIE_SECURE)"],
        cwd=settings.ROOT / "server",
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0
    assert done.stdout.strip() == "True"


def test_every_login_gets_new_token_and_old_session_stays(fixture_accounts, anonymous_client):
    first, second = anonymous_client(), anonymous_client()
    _login(first)
    _login(second)
    assert session_cookie(first) != session_cookie(second)
    assert first.get(ME_PATH).status_code == 200
    assert second.get(ME_PATH).status_code == 200
    assert _query("SELECT count(*) FROM sessions") == [(2,)]


def test_table_keeps_only_token_hash(fixture_accounts, anonymous_client):
    c = anonymous_client()
    _login(c)
    token = session_cookie(c)
    rows = _query("SELECT * FROM sessions")
    assert len(rows) == 1
    assert token not in " ".join(str(value) for value in rows[0])
    assert _query("SELECT token_hash FROM sessions") == [(hash_session_token(token),)]


def test_session_times_are_absolute_eight_hours(fixture_accounts, anonymous_client, clock):
    _login(anonymous_client())
    start = clock.now
    assert _query("SELECT created_at, expires_at, last_seen_at FROM sessions") == [(
        start.isoformat(), (start + timedelta(hours=8)).isoformat(), start.isoformat(),
    )]


@pytest.mark.parametrize("method, path, body", [("GET", ME_PATH, None), ("POST", ASK_PATH, QUESTION)])
def test_expired_session_401_and_row_deleted(fixture_accounts, anonymous_client, clock, sent_to_ai, method, path, body):
    c = anonymous_client()
    _login(c)
    clock.now += timedelta(hours=8)
    r = c.request(method, path, json=body)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED
    assert _query("SELECT count(*) FROM sessions") == [(0,)]
    assert sent_to_ai == []


def test_session_is_not_extended_by_use(fixture_accounts, anonymous_client, clock):
    c = anonymous_client()
    _login(c)
    start = clock.now
    clock.now = start + timedelta(hours=8) - timedelta(seconds=1)
    assert c.get(ME_PATH).status_code == 200
    assert _query("SELECT expires_at FROM sessions") == [((start + timedelta(hours=8)).isoformat(),)]
    clock.now = start + timedelta(hours=8)
    assert c.get(ME_PATH).status_code == 401


def test_login_deletes_own_expired_sessions_only(fixture_accounts, anonymous_client, clock):
    _login(anonymous_client(), "ali")
    _login(anonymous_client(), "ayse")
    clock.now += timedelta(hours=8)
    _login(anonymous_client(), "ali")
    rows = _query("SELECT person_id, expires_at FROM sessions ORDER BY id")
    assert rows == [
        (_person_id("ayse"), clock.now.isoformat()),
        (_person_id("ali"), (clock.now + timedelta(hours=8)).isoformat()),
    ]


def test_last_seen_written_only_after_one_minute(fixture_accounts, anonymous_client, clock):
    c = anonymous_client()
    _login(c)
    start = clock.now
    clock.now = start + timedelta(minutes=1)
    assert c.get(ME_PATH).status_code == 200
    assert _query("SELECT last_seen_at FROM sessions") == [(start.isoformat(),)]
    clock.now = start + timedelta(minutes=1, seconds=1)
    assert c.get(ME_PATH).status_code == 200
    assert _query("SELECT last_seen_at FROM sessions") == [(clock.now.isoformat(),)]


def test_last_seen_write_failure_keeps_identity(fixture_accounts, anonymous_client, clock, monkeypatch, caplog):
    c = anonymous_client()
    _login(c)
    clock.now += timedelta(minutes=2)
    real_connect = main.connect

    class ReadOnlySessions(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.startswith("UPDATE sessions"):
                raise sqlite3.OperationalError("TEST - database is locked")
            return super().execute(sql, *args)

    def connect_read_only(path):
        real_connect(path).close()
        connection = sqlite3.connect(path, factory=ReadOnlySessions)
        return connection

    monkeypatch.setattr(main, "connect", connect_read_only)
    with caplog.at_level(logging.ERROR, logger="agentstack"):
        r = c.get(ME_PATH)
    assert r.status_code == 200
    assert r.json()["username"] == "ali"
    assert "Failed to write session last seen time: OperationalError" in caplog.text
    assert "TEST - database is locked" not in caplog.text


@pytest.mark.parametrize("token", [
    "TEST-made-up-token",
    "short",
    "a" * 42,
    "a" * 44,
    "!" * 43,
    "a" * 4000,
])
def test_malformed_cookie_never_reaches_database(anonymous_client, monkeypatch, token):
    opened = []
    monkeypatch.setattr(main, "connect", lambda path: opened.append(path))
    c = anonymous_client()
    set_session_cookie(c, token)
    assert c.get(ME_PATH).status_code == 401
    assert c.post(ASK_PATH, json=QUESTION).status_code == 401
    assert c.post(LOGOUT_PATH).status_code == 204
    assert opened == []


def test_unknown_well_formed_token_401(anonymous_client):
    c = anonymous_client()
    set_session_cookie(c, new_session_token())
    r = c.get(ME_PATH)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED


# --- Logout


def test_same_cookie_401_after_logout(fixture_accounts, anonymous_client):
    c = anonymous_client()
    _login(c)
    token = session_cookie(c)
    r = c.post(LOGOUT_PATH)
    assert r.status_code == 204
    assert r.content == b""
    assert _query("SELECT count(*) FROM sessions") == [(0,)]
    assert session_cookie(c) is None
    # The same cookie, sent again by hand, is no longer a session.
    set_session_cookie(c, token)
    assert c.get(ME_PATH).status_code == 401
    assert c.post(ASK_PATH, json=QUESTION).status_code == 401


def test_logout_deletes_only_this_session(fixture_accounts, anonymous_client):
    first, second = anonymous_client(), anonymous_client()
    _login(first)
    _login(second)
    first.post(LOGOUT_PATH)
    assert first.get(ME_PATH).status_code == 401
    assert second.get(ME_PATH).status_code == 200


def test_logout_clears_cookie_with_same_attributes(fixture_accounts, anonymous_client):
    c = anonymous_client()
    _login(c)
    r = c.post(LOGOUT_PATH)
    parts = _cookie_parts(r)
    assert "max-age=0" in parts
    assert {"httponly", "secure", "samesite=lax", "path=/"} <= parts


def test_logout_clear_cookie_follows_secure_setting(anonymous_client, monkeypatch):
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", False)
    parts = _cookie_parts(anonymous_client().post(LOGOUT_PATH))
    assert "secure" not in parts
    assert {"httponly", "samesite=lax", "path=/", "max-age=0"} <= parts


@pytest.mark.parametrize("case", ["no_cookie", "bad_format", "unknown_token", "expired"])
def test_logout_without_valid_session_204(fixture_accounts, anonymous_client, clock, case):
    c = anonymous_client()
    if case == "bad_format":
        set_session_cookie(c, "TEST-made-up-token")
    elif case == "unknown_token":
        set_session_cookie(c, new_session_token())
    elif case == "expired":
        _login(c)
        clock.now += timedelta(hours=8)
    r = c.post(LOGOUT_PATH)
    assert r.status_code == 204
    assert r.content == b""
    assert "max-age=0" in _cookie_parts(r)
    assert _query("SELECT count(*) FROM sessions") == [(0,)]
    assert c.post(LOGOUT_PATH).status_code == 204


# --- Who am I and inactive accounts


@pytest.mark.parametrize("username", ["ali", "admin", "unlinked", "admin_linked"])
def test_me_body_matches_login(fixture_accounts, anonymous_client, username):
    c = anonymous_client()
    body = _login(c, username).json()
    r = c.get(ME_PATH)
    assert r.status_code == 200
    assert r.json() == body
    assert body["slack_linked"] is (FIXTURE_ACCOUNTS[username].slack_user_id is not None)


def test_me_without_session_401(anonymous_client):
    r = anonymous_client().get(ME_PATH)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED


def test_deactivate_during_session_401(fixture_accounts, anonymous_client):
    c = anonymous_client()
    _login(c)
    _deactivate_by_store("ali")
    r = c.get(ME_PATH)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED


def test_manual_inactive_flag_401_and_session_not_revived(fixture_accounts, anonymous_client, sent_to_ai):
    c = anonymous_client()
    _login(c)
    # By hand in the database, not with the command: the session row is still there.
    _write("UPDATE people SET is_active = 0 WHERE username = 'ali'")
    assert _query("SELECT count(*) FROM sessions") == [(1,)]
    r = c.post(ASK_PATH, json=QUESTION)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED
    assert sent_to_ai == []
    assert _query("SELECT count(*) FROM sessions") == [(0,)]
    _write("UPDATE people SET is_active = 1 WHERE username = 'ali'")
    assert c.get(ME_PATH).status_code == 401


def test_inactive_account_cannot_log_in_and_can_after_activate(fixture_accounts, anonymous_client):
    c = anonymous_client()
    _deactivate_by_store("ali")
    assert _login(c).status_code == 401
    assert not c.cookies
    _write("UPDATE people SET is_active = 1 WHERE username = 'ali'")
    assert _login(c).status_code == 200


# --- /api/ask and the session


def test_ask_without_session_401_ai_zero(anonymous_client, sent_to_ai):
    r = anonymous_client().post(ASK_PATH, json=QUESTION)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED
    assert ai.fake_call_count() == 0
    assert sent_to_ai == []
    assert _query("SELECT count(*) FROM ai_calls") == [(0,)]


def test_ask_without_session_runs_no_gateway_step(anonymous_client, monkeypatch):
    calls = []
    monkeypatch.setattr(gateway, "handle_question", lambda **kwargs: calls.append(kwargs))
    assert anonymous_client().post(ASK_PATH, json=QUESTION).status_code == 401
    assert calls == []


NO_SESSION_BODIES = {
    "unknown_field": {"json": {"question": "#dev", "role": "admin"}},
    "missing_field": {"json": {}},
    "empty_question": {"json": {"question": ""}},
    "user_field": {"json": {"question": "#dev", "user": "ali"}},
    "broken_json": {"content": "{broken", "headers": {"Content-Type": "application/json"}},
    "not_utf8": {"content": b"\xff\xfe", "headers": {"Content-Type": "application/json"}},
    "text_plain": {"content": '{"question": "#dev"}', "headers": {"Content-Type": "text/plain"}},
    "no_body": {},
}


@pytest.mark.parametrize("case", sorted(NO_SESSION_BODIES))
def test_ask_without_session_bad_body_401_not_422(anonymous_client, sent_to_ai, case):
    r = anonymous_client().post(ASK_PATH, **NO_SESSION_BODIES[case])
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED
    assert sent_to_ai == []


@pytest.mark.parametrize("case", sorted(NO_SESSION_BODIES))
def test_ask_with_session_bad_body_422(client_as, sent_to_ai, case):
    r = client_as("ali").post(ASK_PATH, **NO_SESSION_BODIES[case])
    assert r.status_code == 422
    assert r.json() == INVALID_REQUEST
    assert sent_to_ai == []


@pytest.mark.parametrize("content_type", ["application/json", "application/json; charset=utf-8", "APPLICATION/JSON"])
def test_ask_accepts_json_content_type(client_as, sent_to_ai, content_type):
    r = client_as("ali").post(
        ASK_PATH, content='{"question": "#dev"}'.encode(), headers={"Content-Type": content_type},
    )
    assert r.status_code == 200
    assert len(sent_to_ai) == 1


def test_ask_expired_session_bad_body_401(fixture_accounts, anonymous_client, clock):
    c = anonymous_client()
    _login(c)
    clock.now += timedelta(hours=8)
    assert c.post(ASK_PATH, content="{broken", headers={"Content-Type": "application/json"}).status_code == 401


def test_ask_user_field_cannot_change_identity(client_as, monkeypatch):
    calls = []
    monkeypatch.setattr(gateway, "handle_question", lambda **kwargs: calls.append(kwargs))
    r = client_as("ali").post(ASK_PATH, json={"question": "#dev", "user": "ayse"})
    assert r.status_code == 422
    assert calls == []


@pytest.mark.parametrize("username", ["ali", "ayse", "admin"])
def test_ask_passes_session_person_to_gateway(client_as, monkeypatch, username):
    seen = []
    real = gateway.handle_question

    def spy(question, person):
        seen.append(person)
        return real(question=question, person=person)

    monkeypatch.setattr(gateway, "handle_question", spy)
    assert client_as(username).post(ASK_PATH, json=QUESTION).status_code == 200
    account = FIXTURE_ACCOUNTS[username]
    assert len(seen) == 1
    assert (seen[0].id, seen[0].username, seen[0].display_name, seen[0].role, seen[0].slack_user_id) == (
        _person_id(username), username, account.name, account.role, account.slack_user_id,
    )


def test_identity_stops_without_person(sent_to_ai):
    answer = gateway.handle_question("#dev'i özetle", None)
    assert answer.status == "no_access"
    assert answer.answer == gateway.NO_ACCESS_ANSWER
    assert ai.fake_call_count() == 0
    assert sent_to_ai == []
    assert _query("SELECT count(*) FROM ai_calls") == [(0,)]


def test_identity_keeps_person_in_context(monkeypatch):
    seen = []
    monkeypatch.setattr(gateway, "STEPS", [("identity", gateway.identity), ("check", seen.append)])
    gateway.handle_question("#dev'i özetle", TEST_PERSON)
    assert seen[0].person == TEST_PERSON
    assert seen[0].stopped is False


def test_ask_openapi_keeps_request_body():
    operation = app.openapi()["paths"][ASK_PATH]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert operation["requestBody"]["required"] is True
    assert set(schema["properties"]) == {"question"}
    assert schema["required"] == ["question"]
    assert schema["additionalProperties"] is False


# --- Events and leaks


@pytest.mark.parametrize("case, expected", [
    ("success", ("login", "passed", None, "ali")),
    ("wrong_password", ("login", "stopped", "INVALID_CREDENTIALS", "ali")),
    ("no_such_user", ("login", "stopped", "INVALID_CREDENTIALS", None)),
    ("bad_format", ("login", "stopped", "INVALID_CREDENTIALS", None)),
])
def test_login_events_written(fixture_accounts, anonymous_client, case, expected):
    if case == "success":
        username, password = "ali", TEST_PASSWORD
    else:
        username, password = _prepare_failure(case)
    _login(anonymous_client(), username, password)
    step, decision, reason_code, person = expected
    assert _events() == [(step, decision, reason_code, _person_id(person) if person else None)]


@pytest.mark.parametrize("username, has_person", [("ali", True), ("nobody", False)])
def test_too_many_attempts_event(fixture_accounts, anonymous_client, username, has_person):
    c = anonymous_client()
    for _ in range(6):
        _login(c, username, WRONG_PASSWORD)
    person_id = _person_id(username) if has_person else None
    assert _events()[-1] == ("login", "stopped", "TOO_MANY_ATTEMPTS", person_id)
    assert len(_events()) == 6


def test_logout_event_only_when_session_deleted(fixture_accounts, anonymous_client):
    c = anonymous_client()
    c.post(LOGOUT_PATH)
    set_session_cookie(c, new_session_token())
    c.post(LOGOUT_PATH)
    assert _events() == []
    _login(c)
    c.post(LOGOUT_PATH)
    assert _events() == [
        ("login", "passed", None, _person_id("ali")),
        ("logout", "passed", None, _person_id("ali")),
    ]


def test_event_rows_have_no_username_password_or_token(fixture_accounts, anonymous_client):
    # A password typed into the user name field must not be written either.
    typed_in_name_field = "TEST-secret-in-name-field"
    c = anonymous_client()
    _login(c, typed_in_name_field, WRONG_PASSWORD)
    _login(c, "ali", WRONG_PASSWORD)
    _login(c)
    token = session_cookie(c)
    c.post(LOGOUT_PATH)
    rows = _query("SELECT * FROM audit_events")
    assert len(rows) == 4
    text = " ".join(str(value) for row in rows for value in row)
    for secret in (typed_in_name_field, WRONG_PASSWORD, TEST_PASSWORD, token, hash_session_token(token), "ali"):
        assert secret not in text


def test_event_request_ids_are_new_for_every_event(fixture_accounts, anonymous_client):
    c = anonymous_client()
    _login(c, password=WRONG_PASSWORD)
    _login(c)
    ids = [row[0] for row in _query("SELECT request_id FROM audit_events")]
    assert len(ids) == len(set(ids)) == 2


def test_login_succeeds_if_event_cannot_be_written(fixture_accounts, anonymous_client, monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("TEST - write failed")

    monkeypatch.setattr(login_flow, "write_event", broken)
    c = anonymous_client()
    with caplog.at_level(logging.ERROR, logger="agentstack"):
        assert _login(c, password=WRONG_PASSWORD).status_code == 401
        assert _login(c).status_code == 200
        assert c.post(LOGOUT_PATH).status_code == 204
    assert "Failed to write login event" in caplog.text
    assert "Failed to write logout event" in caplog.text
    assert "OperationalError" in caplog.text
    assert "TEST - write failed" not in caplog.text
    assert _events() == []


def test_logs_contain_no_password_or_token(fixture_accounts, monkeypatch, caplog, capfd):
    typed_in_name_field = "TEST-secret-in-name-field"
    c = TestClient(app, base_url=BASE_URL, raise_server_exceptions=False)
    with caplog.at_level(logging.DEBUG):
        _login(c, typed_in_name_field, WRONG_PASSWORD)
        _login(c)
        token = session_cookie(c)
        c.get(ME_PATH)
        c.post(ASK_PATH, json=QUESTION)
        c.post(LOGOUT_PATH)

        # An unexpected error during login: the 500 path writes to the log too.
        def broken(*args, **kwargs):
            raise sqlite3.OperationalError(f"TEST - {TEST_PASSWORD}")

        monkeypatch.setattr(login_flow, "create_session", broken)
        assert _login(c).status_code == 500
    captured = capfd.readouterr()
    output = caplog.text + captured.out + captured.err
    assert "Unexpected error: OperationalError" in output
    for secret in (typed_in_name_field, WRONG_PASSWORD, TEST_PASSWORD, token, hash_session_token(token)):
        assert secret not in output


def test_error_bodies_contain_no_password(fixture_accounts, anonymous_client):
    c = anonymous_client()
    answers = [_login(c, "admin_linked", WRONG_PASSWORD) for _ in range(6)]
    answers.append(c.post(LOGIN_PATH, json={"username": "admin_linked", "password": WRONG_PASSWORD, "role": "admin"}))
    assert {r.status_code for r in answers} == {401, 422, 429}
    for r in answers:
        assert WRONG_PASSWORD not in r.text
        assert "admin_linked" not in r.text
