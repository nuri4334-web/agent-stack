"""First provider: Gemini (S1-08 Steps 2, 4, 5, 6).

All Gemini-specific details live only in this file.
- Instruction -> system_instruction field
- Data -> contents field
- Cage: no tools, no history, only plain text is returned.
- Security: the key is never written to logs or error messages.
"""
import time
import httpx

from .. import settings
from . import AIResponse, AIError

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def ask(instruction: str, data: str) -> AIResponse:
    """Sends a single (caged) request to the Gemini REST API."""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise AIError(
            code="MISSING_KEY",
            message="Gemini API key is not set. Check the server settings.",
        )

    model_name = settings.GEMINI_MODEL.strip().removeprefix("models/")
    url = f"{GEMINI_API_BASE}/{model_name}:generateContent"

    # Steps 2 & 5: system instruction and data in separate fields; no tools are given
    body = {
        "system_instruction": {
            "parts": [{"text": instruction}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": data}],
            }
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    start = time.perf_counter()
    try:
        with httpx.Client(timeout=settings.AI_TIMEOUT_SECONDS) as client:
            response = client.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        raise AIError(
            code="TIMEOUT",
            message="The AI service did not respond in time (timeout).",
        ) from None
    except httpx.RequestError:
        # The original exception text is not shown, so the key or internal network details cannot leak
        raise AIError(
            code="CONNECTION_ERROR",
            message="The AI service cannot be reached right now.",
        ) from None

    duration_ms = round((time.perf_counter() - start) * 1000, 2)

    if response.status_code == 429:
        raise AIError(
            code="QUOTA_EXCEEDED",
            message="The AI request limit (quota) was exceeded. Please wait a little and try again.",
        )

    if response.status_code in (400, 401, 403):
        raise AIError(
            code="AUTH_OR_REQUEST_ERROR",
            message="The AI service rejected the request (configuration or authorization error).",
        )

    if response.status_code >= 500:
        raise AIError(
            code="PROVIDER_ERROR",
            message="A temporary server error occurred in the AI service.",
        )

    if response.status_code != 200:
        raise AIError(
            code="UNKNOWN_ERROR",
            message=f"The AI service returned an unexpected status (HTTP {response.status_code}).",
        )

    try:
        response_json = response.json()
        candidates = response_json.get("candidates") or []
        parts = candidates[0]["content"]["parts"]
        answer_text = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError, ValueError):
        raise AIError(
            code="UNPARSEABLE_RESPONSE",
            message="No valid text response could be read from the AI service.",
        ) from None

    usage = response_json.get("usageMetadata") or {}
    input_tokens = int(usage.get("promptTokenCount", 0))
    output_tokens = int(usage.get("candidatesTokenCount", 0))

    return AIResponse(
        answer=answer_text,
        model=model_name,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
