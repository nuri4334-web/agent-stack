from fastapi.testclient import TestClient

from app import gateway
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "up"}


def test_ask_returns_contract_compliant_answer():
    r = client.post("/api/ask", json={"question": "#dev'i özetle", "user": "ali"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"request_id", "status", "answer", "sources", "security"}
    assert body["status"] == "ok"
    assert body["sources"] == []
    assert body["security"] == {"blocked": 0, "masked": 0, "suspicious": 0}


def test_invalid_request_returns_clear_error():
    r = client.post("/api/ask", json={"question": ""})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_REQUEST"


def test_gateway_seven_steps_in_order():
    assert [name for name, _ in gateway.STEPS] == [
        "identity", "authorization", "data_selection", "sanitization",
        "ask_ai", "response_check", "presentation",
    ]


def test_stopped_request_does_not_reach_ai(monkeypatch):
    called = []

    def deny(c):
        c.status = "no_access"
        c.stopped = True

    monkeypatch.setattr(gateway, "STEPS", [
        ("authorization", deny),
        ("ask_ai", lambda c: called.append(1)),
    ])
    answer = gateway.handle_question("yonetim ne konuştu?", "ali")
    assert answer.status == "no_access"
    assert called == []
