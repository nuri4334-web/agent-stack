import logging

import httpx
import pytest

from app.slack_connector import sync, seed
from app.slack_connector.client import HttpxSlackClient, SlackError
from app.database.schema import connect
from tests.fake_slack import NOW, ts

TOKEN = "xoxb-EXAMPLE-0000-TEST"


def _client(handler):
    waits = []
    client = HttpxSlackClient(TOKEN, waits.append, transport=httpx.MockTransport(handler))
    return client, waits


def test_429_waits_retry_after_and_retries():
    responses = [
        httpx.Response(429, headers={"Retry-After": "3"}),
        httpx.Response(200, json={"ok": True, "channels": []}),
    ]
    client, waits = _client(lambda request: responses.pop(0))
    assert client.call("conversations.list", {"limit": "200"}) == {"ok": True, "channels": []}
    assert waits == [3]
    assert responses == []


def test_ratelimited_error_if_429_continues():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "abc"})

    client, waits = _client(handler)
    with pytest.raises(SlackError) as error:
        client.call("conversations.history", {"channel": "C1"})
    assert error.value.code == "ratelimited"
    assert len(requests) == 5
    assert waits == [5.0] * 4


def test_slack_error_code_is_sanitized():
    for response, expected in [
        (httpx.Response(200, json={"ok": False, "error": "not_in_channel"}), "not_in_channel"),
        (httpx.Response(200, json={"ok": False, "error": "Not In Channel! <script>"}), "unknown_error"),
        (httpx.Response(200, json={"ok": False}), "unknown_error"),
        (httpx.Response(500, text="server"), "http_500"),
        (httpx.Response(200, text="not json"), "invalid_response"),
    ]:
        client, _ = _client(lambda request, r=response: r)
        with pytest.raises(SlackError) as error:
            client.call("users.list", {})
        assert error.value.code == expected
        assert str(error.value) == expected


def test_token_in_no_output(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    requests = []
    members_attempts = []

    def handler(request):
        requests.append(request)
        endpoint = request.url.path.rsplit("/", 1)[-1]
        channel = request.url.params.get("channel")
        if endpoint == "conversations.list":
            return httpx.Response(200, json={"ok": True, "channels": [
                {"id": "C_DEV", "name": "dev", "is_private": False, "is_member": True},
                {"id": "C_GENEL", "name": "genel", "is_private": False, "is_member": True},
            ]})
        if endpoint == "users.list":
            return httpx.Response(200, json={"ok": True, "members": [{"id": "U_ALI"}]})
        if endpoint == "conversations.members":
            members_attempts.append(channel)
            if members_attempts.count(channel) == 1:
                return httpx.Response(429, headers={"Retry-After": "1"})
            return httpx.Response(200, json={"ok": True, "members": ["U_ALI"]})
        if endpoint == "conversations.history" and channel == "C_DEV":
            return httpx.Response(200, json={"ok": True, "messages": [
                {"type": "message", "user": "U_ALI", "text": "login page", "ts": ts(1)},
            ]})
        return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})

    db_path = tmp_path / "test.db"
    waits = []
    result = sync.run_command(
        [], token=TOKEN,
        client_factory=lambda t: HttpxSlackClient(t, waits.append, transport=httpx.MockTransport(handler)),
        database_path=db_path, allowed_channels=["C_DEV", "C_GENEL"], blocked_channels=[], now=lambda: NOW,
        write=print,
    )
    assert result == 1
    assert waits == [1, 1]

    # The token goes only in the header, not in the URL.
    assert requests
    for request in requests:
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in str(request.url)

    # Network error and repr do not show the token.
    def broken(request):
        raise httpx.ConnectError(f"no connection: {request.url} {request.headers}")

    client = HttpxSlackClient(TOKEN, lambda s: None, transport=httpx.MockTransport(broken))
    with pytest.raises(SlackError) as error:
        client.call("users.list", {})
    assert error.value.code == "connection_error"
    assert error.value.__cause__ is None
    assert TOKEN not in str(error.value)
    assert TOKEN not in repr(client)

    # Seed export.
    seed_path = tmp_path / "seed.json"
    assert seed.run_command(
        ["export", "--file", str(seed_path)], database_path=db_path, allowed_channels=["C_DEV"],
        blocked_channels=[], now=lambda: NOW, write=print, token=TOKEN,
    ) == 0

    connection = connect(db_path)
    dump = "\n".join(connection.iterdump())
    connection.close()
    assert "login page" in dump
    assert TOKEN not in dump
    assert TOKEN not in seed_path.read_text(encoding="utf-8")
    output = capsys.readouterr()
    assert "invalid_auth" in output.out
    assert TOKEN not in output.out + output.err
    assert TOKEN not in caplog.text
