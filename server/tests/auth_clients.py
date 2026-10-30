"""Test accounts and HTTP clients for the identity tests (S2-01; API contract v3).

The interface (`client_as`, `anonymous_client` in conftest.py) does not change after S2-01;
S2-02 writes these accounts to the database (`fixture_accounts`), S2-03 turns on the login endpoint.
"""
import re
import sqlite3
from dataclasses import dataclass
from http.cookiejar import Cookie

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.accounts import store

# Fake password for every test account: at least 12 characters, no secret pattern of the seed check.
TEST_PASSWORD = "TEST-password-2026"
SESSION_COOKIE = "agentstack_session"
LOGIN_PATH = "/api/auth/login"
# The session cookie is Secure: an http client would never send it back.
BASE_URL = "https://testserver"
# Python's cookie jar stores cookies of a host name without a dot under "<host>.local".
COOKIE_DOMAIN = "testserver.local"

# One message line of the data sent to the AI: "[#{channel} | {author} | {time}]: {text}".
# This is the line format of gateway.ask_ai; if that format changes, this pattern changes too.
# A message text with a line break continues on lines that do not match.
MESSAGE_LINE = re.compile(r"^\[#(?P<channel>[\w-]+) \| [^|\n]+ \| [^\]\n]+\]: ", re.MULTILINE)


@dataclass(frozen=True)
class FixtureAccount:
    username: str
    name: str
    role: str
    slack_user_id: str | None


FIXTURE_ACCOUNTS: dict[str, FixtureAccount] = {
    # Member of #dev and #genel.
    "ali": FixtureAccount("ali", "Ali Kaya", "user", "U0CA5HH3M1V"),
    # Member of #dev, #genel and #yonetim.
    "ayse": FixtureAccount("ayse", "Ayşe Demir", "user", "U0CAQKKLXTN"),
    # Panel only: no Slack account, so a channel question gets no_access (NO_SLACK_ACCOUNT).
    "admin": FixtureAccount("admin", "Admin", "admin", None),
    "unlinked": FixtureAccount("unlinked", "Unlinked User", "user", None),
    # Deniz's Slack account, not a member of #yonetim: the admin role gives no channel access.
    "admin_linked": FixtureAccount("admin_linked", "Deniz Aydın", "admin", "U0CAKNQPNKD"),
}


def write_fixture_accounts(connection: sqlite3.Connection, password_hash: str, created_at: str) -> None:
    """Writes the five test accounts with their Slack links, through the same store functions as the commands.

    All share one hash of TEST_PASSWORD (scrypt runs once per test session; its parameters are never lowered).
    """
    for account in FIXTURE_ACCOUNTS.values():
        person_id = store.create_account(
            connection, username=account.username, name=account.name, role=account.role,
            password_hash=password_hash, created_at=created_at,
        )
        if account.slack_user_id:
            store.link_slack_account(connection, person_id, account.slack_user_id, linked_at=created_at)


def has_login_route(target_app) -> bool:
    return any(
        isinstance(route, APIRoute) and route.path == LOGIN_PATH and "POST" in route.methods
        for route in target_app.routes
    )


def make_anonymous_client(target_app) -> TestClient:
    return TestClient(target_app, base_url=BASE_URL)


def make_client_as(target_app, name: str) -> TestClient:
    """A client signed in as a test account.

    Until the login endpoint exists (S2-03) it returns a client without a cookie, so attack tests stay xfail.
    Once the endpoint exists, a failed login is a test error: no test may pass with a cookieless client by mistake.
    """
    if name not in FIXTURE_ACCOUNTS:
        pytest.fail(f"client_as: unknown test account '{name}'; use one of: {', '.join(FIXTURE_ACCOUNTS)}")
    client = make_anonymous_client(target_app)
    if not has_login_route(target_app):
        return client
    r = client.post(LOGIN_PATH, json={"username": name, "password": TEST_PASSWORD})
    if r.status_code != 200:
        pytest.fail(f"client_as('{name}'): login returned {r.status_code}, expected 200")
    if SESSION_COOKIE not in client.cookies:
        pytest.fail(f"client_as('{name}'): login did not set the {SESSION_COOKIE} cookie")
    return client


def set_session_cookie(client: TestClient, token: str) -> None:
    """Puts a session cookie on the client by hand (e.g. a logged-out or made-up token); replaces the old one."""
    client.cookies.jar.set_cookie(Cookie(
        version=0, name=SESSION_COOKIE, value=token, port=None, port_specified=False,
        domain=COOKIE_DOMAIN, domain_specified=False, domain_initial_dot=False,
        path="/", path_specified=True, secure=True, expires=None, discard=True,
        comment=None, comment_url=None, rest={"HttpOnly": None}, rfc2109=False,
    ))


def session_cookie(client: TestClient) -> str | None:
    """The session cookie value the client holds, or None."""
    return client.cookies.get(SESSION_COOKIE)


def channels_sent_to_ai(sent: list[str]) -> list[set[str]]:
    """For every AI call captured by sent_to_ai, the set of channel names in its message lines.

    A question or message text that contains a line in the same format is counted too
    (more channels, never fewer), so a "this channel was not sent" check cannot pass by mistake.
    """
    return [set(MESSAGE_LINE.findall(data)) for data in sent]
