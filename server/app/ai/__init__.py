"""AI common interface and fake provider (S1-08).

The only thing the gateway knows is the `ask(instruction, data)` function here.
The architecture principle 'the gate is fixed, the brain changes' is applied here.
"""
import time
from dataclasses import dataclass

from .. import settings


@dataclass
class AIResponse:
    """Common interface output: answer, model name used, duration, token counts."""

    answer: str
    model: str
    duration_ms: float
    input_tokens: int = 0
    output_tokens: int = 0


class AIError(Exception):
    """Safe error raised when the provider fails or times out.

    It never contains an API key or a secret URL.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --- Second provider: fake (Step 3) ---
FAKE_FIXED_ANSWER = "This is a fixed test answer from the fake provider."
_fake_call_count: int = 0


def reset_fake_counter() -> None:
    """Helper to reset the call counter in tests."""
    global _fake_call_count
    _fake_call_count = 0


def fake_call_count() -> int:
    """Returns how many times the fake provider was called."""
    return _fake_call_count


def _fake_ask(instruction: str, data: str) -> AIResponse:
    global _fake_call_count
    start = time.perf_counter()
    _fake_call_count += 1
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    return AIResponse(
        answer=FAKE_FIXED_ANSWER,
        model="fake-v1",
        duration_ms=duration_ms,
        input_tokens=len((instruction + " " + data).split()),
        output_tokens=len(FAKE_FIXED_ANSWER.split()),
    )


# --- Common Interface (Step 1) ---
def ask(instruction: str, data: str) -> AIResponse:
    """The single common function the gateway calls.

    Input: instruction text and data text, separately.
    Output: AIResponse (answer, model, duration_ms, input_tokens, output_tokens).
    """
    provider = settings.AI_PROVIDER

    if provider == "fake":
        return _fake_ask(instruction=instruction, data=data)

    if provider == "gemini":
        from . import gemini

        return gemini.ask(instruction=instruction, data=data)

    raise AIError(
        code="INVALID_PROVIDER",
        message=f"Unknown AI provider: '{provider}'. (must be 'fake' or 'gemini')",
    )
