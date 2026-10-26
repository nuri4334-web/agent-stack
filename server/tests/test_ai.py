"""S1-08: AI connection v1 tests."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app import settings, gateway, ai
from app.main import app
from app.ai import gemini

client = TestClient(app)


def test_fake_provider_fixed_answer_and_counter(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "fake")
    ai.reset_fake_counter()

    assert ai.fake_call_count() == 0
    result1 = ai.ask(instruction="Summarize", data="Message 1")
    result2 = ai.ask(instruction="Summarize", data="Message 2")

    assert result1.answer == ai.FAKE_FIXED_ANSWER
    assert result2.answer == ai.FAKE_FIXED_ANSWER
    assert result1.model == "fake-v1"
    assert result1.duration_ms >= 0
    assert result1.input_tokens > 0
    assert result1.output_tokens > 0
    assert ai.fake_call_count() == 2


def test_stopped_request_does_not_increase_fake_counter(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "fake")
    ai.reset_fake_counter()

    def deny(c):
        c.status = "no_access"
        c.stopped = True

    monkeypatch.setattr(
        gateway,
        "STEPS",
        [
            ("authorization", deny),
            ("ask_ai", gateway.ask_ai),
        ],
    )
    answer = gateway.handle_question("yonetim ne konuştu?", "ali")
    assert answer.status == "no_access"
    assert ai.fake_call_count() == 0


def test_gemini_puts_instruction_and_data_in_separate_fields_and_gives_no_tools(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-secret-key-123")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-3.5-flash-lite")

    captured_request = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "Gemini test summary."}]}}
                ],
                "usageMetadata": {
                    "promptTokenCount": 15,
                    "candidatesTokenCount": 4,
                },
            }

    class FakeClient:
        def __init__(self, timeout):
            captured_request["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, json, headers):
            captured_request["url"] = url
            captured_request["json"] = json
            captured_request["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    result = ai.ask(instruction="System rule", data="Slack messages")
    assert result.answer == "Gemini test summary."
    assert result.model == "gemini-3.5-flash-lite"
    assert result.input_tokens == 15
    assert result.output_tokens == 4

    # Instruction and data must be in separate fields, no tools (Cage)
    body = captured_request["json"]
    assert body["system_instruction"]["parts"][0]["text"] == "System rule"
    assert body["contents"][0]["parts"][0]["text"] == "Slack messages"
    assert "tools" not in body


def test_gemini_does_not_leak_key_on_error_and_timeout(monkeypatch):
    secret = "AIzaSySECRET_TEST_KEY_999"
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", secret)

    class TimeoutClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, json, headers):
            raise httpx.TimeoutException(f"Timeout for key {secret}")

    monkeypatch.setattr(httpx, "Client", TimeoutClient)

    with pytest.raises(ai.AIError) as exc_info:
        gemini.ask(instruction="Instruction", data="Data")

    assert exc_info.value.code == "TIMEOUT"
    assert secret not in exc_info.value.message
    assert secret not in str(exc_info.value)

    # API contract: on timeout the server must return 504 and TIMEOUT
    r_504 = client.post("/api/ask", json={"question": "test question", "user": "ali"})
    assert r_504.status_code == 504
    body_504 = r_504.json()
    assert body_504["error"]["code"] == "TIMEOUT"
    assert secret not in str(body_504)

    # On other provider errors the server must return 502 and PROVIDER_ERROR
    class ServerErrorClient(TimeoutClient):
        def post(self, url, json, headers):
            class ErrorResponse:
                status_code = 503
            return ErrorResponse()

    monkeypatch.setattr(httpx, "Client", ServerErrorClient)
    r_502 = client.post("/api/ask", json={"question": "test question", "user": "ali"})
    assert r_502.status_code == 502
    body_502 = r_502.json()
    assert body_502["error"]["code"] == "PROVIDER_ERROR"
    assert secret not in str(body_502)
