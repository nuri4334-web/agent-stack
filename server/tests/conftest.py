"""Shared pytest configuration for all tests."""
from datetime import datetime, timezone

import pytest

from app import ai, settings
from app.data_selection import selection
from app.main import app
from app.slack_connector import seed
from app.database.schema import connect
from app.accounts.rules import hash_password
from tests.auth_clients import TEST_PASSWORD, make_anonymous_client, make_client_as, write_fixture_accounts

# Channel id lists for tests (independent of .env): genel, dev, yonetim of the demo seed; C_IK is the fake #ik.
TEST_ALLOWED_CHANNELS = ["C0C8ATRM073", "C0C83M051QD", "C0CB44VUCF2"]
TEST_BLOCKED_CHANNELS = ["C_IK"]


@pytest.fixture(scope="session")
def _seed_data():
    return seed.read_seed(seed.SEED_PATH)


@pytest.fixture(autouse=True)
def _temporary_database(monkeypatch, tmp_path, _seed_data):
    """In every test, a temporary database with the seed loaded instead of the real server/agentstack.db."""
    path = tmp_path / "test-agentstack.db"
    connection = connect(path)
    try:
        seed.load_seed(
            connection, _seed_data, TEST_ALLOWED_CHANNELS,
            lambda: datetime(2026, 10, 24, tzinfo=timezone.utc),
            blocked_channels=TEST_BLOCKED_CHANNELS,
        )
    finally:
        connection.close()
    monkeypatch.setattr(settings, "DATABASE_PATH", path)
    return path


@pytest.fixture(autouse=True)
def _channel_settings(monkeypatch):
    """In every test, the channel lists of the question-time check come from here, not from the developer's .env."""
    monkeypatch.setattr(settings, "ALLOWED_CHANNELS", list(TEST_ALLOWED_CHANNELS))
    monkeypatch.setattr(settings, "BLOCKED_CHANNELS", list(TEST_BLOCKED_CHANNELS))
    selection.reset_reported_warnings()
    yield
    selection.reset_reported_warnings()


@pytest.fixture(autouse=True)
def _default_fake_provider(monkeypatch):
    """In every test, force the fake provider and an empty key by default.

    So even if the developer's .env file says AI_PROVIDER=gemini,
    general tests such as test_skeleton.py never send a request to the real Gemini API.
    """
    monkeypatch.setattr(settings, "AI_PROVIDER", "fake")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")


@pytest.fixture(autouse=True)
def _reset_login_attempts():
    """S2-03 resets the login attempt counter here before every test; there is no counter yet."""
    yield


@pytest.fixture(scope="session")
def _fixture_password_hash():
    """One real scrypt hash of TEST_PASSWORD per test session (scrypt is slow; its parameters are not lowered)."""
    return hash_password(TEST_PASSWORD)


@pytest.fixture
def fixture_accounts(_temporary_database, _fixture_password_hash):
    """Writes the five test accounts (auth_clients.FIXTURE_ACCOUNTS) to the temporary database.

    Not autouse: other tests see an empty people table.
    """
    connection = connect(_temporary_database)
    try:
        write_fixture_accounts(connection, _fixture_password_hash, "2026-10-24T00:00:00+00:00")
    finally:
        connection.close()


@pytest.fixture
def client_as(fixture_accounts):
    """client_as("ali") -> a new client signed in as that test account (names: auth_clients.FIXTURE_ACCOUNTS)."""
    return lambda name: make_client_as(app, name)


@pytest.fixture
def anonymous_client():
    """anonymous_client() -> a new client without a session cookie."""
    return lambda: make_anonymous_client(app)


@pytest.fixture
def sent_to_ai(monkeypatch):
    """Captures the data texts sent to the AI; calls the real fake provider (the counter works, starts at 0)."""
    captured = []
    real = ai.ask

    def spy(instruction, data):
        captured.append(data)
        return real(instruction=instruction, data=data)

    monkeypatch.setattr(ai, "ask", spy)
    ai.reset_fake_counter()
    return captured
