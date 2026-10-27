"""Slack client (S1-04): Web API call, 429 wait and pagination.

The token lives only in the Authorization header; it never goes into the URL, a log, the screen or an error message.
Tests never go to real Slack: the flow uses the SlackClient interface and tests give a fake.
"""
from collections.abc import Callable
from typing import Protocol

import httpx

from .transform import sanitize_error_code

SLACK_API_URL = "https://slack.com/api/"
TIMEOUT_SECONDS = 30.0

# 429 (too many requests): wait used when Retry-After is missing or invalid, and the upper limit of one wait.
DEFAULT_WAIT_SECONDS = 5.0
MAX_WAIT_SECONDS = 120.0

# Against an endless loop: at most this many pages are read in one list.
MAX_PAGES = 1000


class SlackError(Exception):
    """A Slack call failed. Carries only the sanitized error code (e.g. "not_in_channel")."""

    def __init__(self, code: object):
        self.code = sanitize_error_code(code)
        super().__init__(self.code)

    def __str__(self) -> str:
        return self.code


class SlackClient(Protocol):
    def call(self, endpoint: str, params: dict[str, str]) -> dict:
        """Calls one Slack endpoint and returns the JSON body; SlackError on error."""
        ...


def _wait_seconds(retry_after: str | None) -> float:
    try:
        seconds = int(retry_after)
    except (TypeError, ValueError):
        return DEFAULT_WAIT_SECONDS
    if seconds < 0:
        return DEFAULT_WAIT_SECONDS
    return float(min(seconds, MAX_WAIT_SECONDS))


class HttpxSlackClient:
    """Real Slack client with httpx. On 429 it waits for Retry-After and repeats the same request."""

    def __init__(
        self,
        token: str,
        sleep: Callable[[float], None],
        *,
        max_attempts: int = 5,
        transport: httpx.BaseTransport | None = None,
    ):
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._http = httpx.Client(
            base_url=SLACK_API_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_SECONDS,
            transport=transport,
        )

    def __repr__(self) -> str:
        return "HttpxSlackClient(token=<secret>)"

    def call(self, endpoint: str, params: dict[str, str]) -> dict:
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._http.get(endpoint, params=params)
            except httpx.HTTPError:
                # The original exception is not chained: it may contain request details.
                raise SlackError("connection_error") from None
            if response.status_code == 429:
                if attempt == self._max_attempts:
                    break
                self._sleep(_wait_seconds(response.headers.get("Retry-After")))
                continue
            if response.status_code != 200:
                raise SlackError(f"http_{response.status_code}")
            try:
                body = response.json()
            except ValueError:
                raise SlackError("invalid_response") from None
            if not isinstance(body, dict):
                raise SlackError("invalid_response")
            if body.get("ok") is not True:
                raise SlackError(body.get("error"))
            return body
        raise SlackError("ratelimited")

    def close(self) -> None:
        self._http.close()


def paginate(client: SlackClient, endpoint: str, params: dict[str, str], field: str) -> list:
    """Reads all pages of a list (until next_cursor ends) and joins the "field" lists."""
    items: list = []
    cursor = ""
    for _ in range(MAX_PAGES):
        request = dict(params)
        if cursor:
            request["cursor"] = cursor
        body = client.call(endpoint, request)
        page = body.get(field)
        if not isinstance(page, list):
            raise SlackError("invalid_response")
        items.extend(page)
        metadata = body.get("response_metadata")
        cursor = metadata.get("next_cursor") if isinstance(metadata, dict) else ""
        if not cursor or not isinstance(cursor, str):
            return items
    raise SlackError("page_limit")
