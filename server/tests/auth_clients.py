"""Test accounts and HTTP clients for the identity tests (S2-01; API contract v3).

The interface (`client_as`, `anonymous_client` in conftest.py) does not change after S2-01;
S2-02/S2-03 only write these accounts to the database and turn on the login endpoint.
"""
from dataclasses import dataclass

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

# Fake password for every test account: at least 12 characters, no secret pattern of the seed check.
TEST_PASSWORD = "TEST-password-2026"
SESSION_COOKIE = "agentstack_session"
LOGIN_PATH = "/api/auth/login"
# The session cookie is Secure: an http client would never send it back.
BASE_URL = "https://testserver"


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
