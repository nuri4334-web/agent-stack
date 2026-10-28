"""Shared pytest configuration for all tests."""
from datetime import datetime, timezone

import pytest

from app import settings
from app.data_selection import selection
from app.slack_connector import seed
from app.database.schema import connect

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
