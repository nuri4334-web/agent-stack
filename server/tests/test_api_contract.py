"""S2-01: API contract v3 changes in effect now (request body, CORS with credentials)."""
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app import ai, settings
from app.main import ORIGIN_ERROR, app, cors_options

client = TestClient(app)

ALLOWED_ORIGIN = "http://localhost:5173"
OTHER_ORIGIN = "https://evil.example"
RESPONSE_FIELDS = {"request_id", "status", "answer", "sources", "security"}


def _cors_client():
    """A small app with the same CORS settings as the server, independent of the developer's .env."""
    small = FastAPI()
    small.add_middleware(CORSMiddleware, **cors_options([ALLOWED_ORIGIN]))

    @small.get("/health")
    def health():
        return {"status": "up"}

    @small.post("/api/ask")
    def ask():
        return {}

    return TestClient(small)


def _preflight(c, origin):
    return c.options("/api/ask", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })


def test_ask_without_user_field_returns_200(sent_to_ai):
    r = client.post("/api/ask", json={"question": "#dev'i özetle"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == RESPONSE_FIELDS
    assert body["status"] == "ok"
    assert ai.fake_call_count() == 1


def test_ask_with_user_field_still_200_until_s2_03(sent_to_ai):
    # S2-03 removes the field; from then on this request gets 422.
    r = client.post("/api/ask", json={"question": "#dev'i özetle", "user": "ali"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.parametrize("extra", [{"role": "admin"}, {"person_id": 1}])
def test_ask_unknown_field_returns_422(sent_to_ai, extra):
    r = client.post("/api/ask", json={"question": "#dev'i özetle", **extra})
    assert r.status_code == 422
    assert r.json() == {
        "error": {"code": "INVALID_REQUEST", "message": "Invalid request format. See the API contract."}
    }
    assert ai.fake_call_count() == 0
    assert sent_to_ai == []


def test_ask_non_json_content_type_returns_422(sent_to_ai):
    r = client.post(
        "/api/ask", content='{"question": "#dev\'i özetle"}', headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_REQUEST"
    assert sent_to_ai == []


def test_cors_preflight_allowed_origin_allows_credentials():
    r = _preflight(_cors_client(), ALLOWED_ORIGIN)
    assert r.status_code == 200
    assert r.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert r.headers["Access-Control-Allow-Credentials"] == "true"


def test_cors_response_exposes_retry_after():
    r = _cors_client().get("/health", headers={"Origin": ALLOWED_ORIGIN})
    assert r.status_code == 200
    assert r.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert r.headers["Access-Control-Allow-Credentials"] == "true"
    assert "Retry-After" in r.headers["Access-Control-Expose-Headers"].split(", ")


def test_cors_disallowed_origin_gets_no_allow_origin():
    c = _cors_client()
    preflight = _preflight(c, OTHER_ORIGIN)
    assert preflight.status_code == 400
    assert "Access-Control-Allow-Origin" not in preflight.headers
    simple = c.get("/health", headers={"Origin": OTHER_ORIGIN})
    assert "Access-Control-Allow-Origin" not in simple.headers


def test_server_cors_uses_cors_options_of_settings():
    [cors] = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert cors.kwargs == cors_options(settings.FRONTEND_ORIGINS)


@pytest.mark.parametrize("origins", [
    ["*"],
    ["http://localhost:5173", "*"],
    ["https://*.example.com"],
    ["null"],
    ["http://localhost:5173/"],
    ["localhost:5173"],
    ["http://localhost:5173/app"],
])
def test_cors_options_refuse_inexact_origins(origins):
    with pytest.raises(ValueError) as error:
        cors_options(origins)
    assert str(error.value) == ORIGIN_ERROR


@pytest.mark.parametrize("origins", [[], ["http://localhost:5173", "https://demo.example.com:8443"]])
def test_cors_options_exact_list(origins):
    assert cors_options(origins) == {
        "allow_origins": origins,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST"],
        "allow_headers": ["Content-Type"],
        "expose_headers": ["Retry-After"],
    }
