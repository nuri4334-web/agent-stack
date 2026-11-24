"""S4-10: GET /api/admin/masked-texts endpoint tests."""
import pytest

from app import settings
from app.database.schema import connect
from tests.auth_clients import set_session_cookie

ENDPOINT = "/api/admin/masked-texts"
UNAUTHENTICATED = {"error": {"code": "UNAUTHENTICATED", "message": "Please sign in."}}
FORBIDDEN = {"error": {"code": "FORBIDDEN", "message": "You don't have permission for this page."}}
INVALID_REQUEST = {"error": {"code": "INVALID_REQUEST", "message": "Invalid request format. See the API contract."}}
BAD_LIMITS = [
    "limit=0", "limit=101", "limit=-1", "limit=1.5", "limit=abc", "limit=", "limit=5.0",
    "limit=%2B5", "limit=5&limit=6",
]
EXPECTED_FIELDS = {"request_id", "created_at", "kind", "channel", "text"}


def _add_masked_text(request_id: str, created_at: str, masked_text: str):
    connection = connect(settings.DATABASE_PATH)
    try:
        with connection:
            connection.execute(
                "INSERT INTO masked_texts (request_id, created_at, masked_text) VALUES (?, ?, ?)",
                (request_id, created_at, masked_text),
            )
    finally:
        connection.close()


def _add_suspicious_message(request_id: str, created_at: str, channel_name: str, masked_text: str):
    connection = connect(settings.DATABASE_PATH)
    try:
        with connection:
            connection.execute(
                "INSERT INTO suspicious_messages (request_id, created_at, channel_name, masked_text) VALUES (?, ?, ?, ?)",
                (request_id, created_at, channel_name, masked_text),
            )
    finally:
        connection.close()


def _set_inactive(username: str):
    connection = connect(settings.DATABASE_PATH)
    try:
        with connection:
            connection.execute("UPDATE people SET is_active = 0 WHERE username = ?", (username,))
    finally:
        connection.close()


def _count_audit_events() -> int:
    connection = connect(settings.DATABASE_PATH)
    try:
        return connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    finally:
        connection.close()


# --- K1: Auth & Role -----------------------------------------------------------------------------------------
def test_k1_unauthenticated_without_session(anonymous_client):
    r = anonymous_client().get(ENDPOINT)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED


def test_k1_forbidden_for_non_admin_user(client_as):
    r = client_as("ali").get(ENDPOINT)
    assert r.status_code == 403
    assert r.json() == FORBIDDEN


def test_k1_admin_gets_200(client_as):
    r = client_as("admin").get(ENDPOINT)
    assert r.status_code == 200
    assert "items" in r.json()


# --- K2: Both sources merged newest first --------------------------------------------------------------------
def test_k2_both_sources_combined_newest_first(client_as):
    _add_masked_text("1a", "2026-11-24T10:00:00+00:00", "sent text older")
    _add_suspicious_message("1b", "2026-11-24T11:00:00+00:00", "dev", "suspicious text middle")
    _add_masked_text("1c", "2026-11-24T12:00:00+00:00", "sent text newest")

    r = client_as("admin").get(ENDPOINT)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 3

    top3 = items[:3]
    # Newest first
    assert top3[0]["request_id"] == "1c"
    assert top3[0]["kind"] == "sent"
    assert top3[0]["channel"] is None
    assert top3[0]["text"] == "sent text newest"

    assert top3[1]["request_id"] == "1b"
    assert top3[1]["kind"] == "removed_suspicious"
    assert top3[1]["channel"] == "dev"
    assert top3[1]["text"] == "suspicious text middle"

    assert top3[2]["request_id"] == "1a"
    assert top3[2]["kind"] == "sent"
    assert top3[2]["channel"] is None
    assert top3[2]["text"] == "sent text older"


# --- K3: Limit rules -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad_param", BAD_LIMITS)
def test_k3_invalid_limits_return_422(client_as, bad_param):
    r = client_as("admin").get(f"{ENDPOINT}?{bad_param}")
    assert r.status_code == 422
    assert r.json() == INVALID_REQUEST


def test_k3_valid_limit_and_default(client_as):
    # Insert 60 rows
    for i in range(1, 61):
        _add_masked_text(f"{i:x}", f"2026-11-24T08:{i:02d}:00+00:00", f"text {i}")

    # Default is 50
    r_default = client_as("admin").get(ENDPOINT)
    assert r_default.status_code == 200
    assert len(r_default.json()["items"]) == 50

    # Custom limit: 10
    r_10 = client_as("admin").get(f"{ENDPOINT}?limit=10")
    assert r_10.status_code == 200
    assert len(r_10.json()["items"]) == 10

    # Custom limit: 60
    r_60 = client_as("admin").get(f"{ENDPOINT}?limit=60")
    assert r_60.status_code == 200
    assert len(r_60.json()["items"]) == 60


# --- K4: Only five fields & no unmasking ----------------------------------------------------------------------
def test_k4_exact_five_fields_and_placeholders_preserved(client_as):
    masked = "User PERSON_1 sent password [REDACTED] to EMAIL_1"
    _add_masked_text("99", "2026-11-24T15:00:00+00:00", masked)

    r = client_as("admin").get(f"{ENDPOINT}?limit=1")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1
    item = items[0]

    assert set(item.keys()) == EXPECTED_FIELDS
    assert item["text"] == masked
    assert "[REDACTED]" in item["text"]
    assert "PERSON_1" in item["text"]
    assert "EMAIL_1" in item["text"]


# --- K5: Authenticated against database, inactive gets 401 ---------------------------------------------------
def test_k5_inactive_admin_session_is_rejected(client_as):
    c = client_as("admin")
    assert c.get(ENDPOINT).status_code == 200

    _set_inactive("admin")
    r = c.get(ENDPOINT)
    assert r.status_code == 401
    assert r.json() == UNAUTHENTICATED


# --- K6: No audit events written -----------------------------------------------------------------------------
def test_k6_no_audit_events_recorded_for_masked_texts(client_as):
    c = client_as("admin")
    events_before = _count_audit_events()

    r = c.get(ENDPOINT)
    assert r.status_code == 200

    events_after = _count_audit_events()
    assert events_before == events_after
