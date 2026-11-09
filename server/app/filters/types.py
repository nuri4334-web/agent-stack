"""Filter types (S3-01): what every rule returns and what the gateway reads.

Span has no value field on purpose: a span says where a finding is and what kind it is, never what it is,
so spans and results can be logged.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

SECRET_KINDS = (
    "slack_token", "github_token", "aws_key", "google_key", "openai_key", "anthropic_key",
    "private_key", "env_secret", "db_password", "bearer_token",
)
PERSONAL_KINDS = ("email", "phone", "tckn", "iban", "card")
NAME_KIND = "person"
KINDS = SECRET_KINDS + PERSONAL_KINDS + (NAME_KIND,)

Kind = Literal[
    "slack_token", "github_token", "aws_key", "google_key", "openai_key", "anthropic_key",
    "private_key", "env_secret", "db_password", "bearer_token",
    "email", "phone", "tckn", "iban", "card",
    "person",
]
# A weak finding (a random string alone) is never returned: weak means "do not touch".
Confidence = Literal["certain", "suspicious"]
CONFIDENCES = ("certain", "suspicious")


@dataclass(frozen=True)
class Span:
    """A finding in a normalized text: text[start:end] is the value to mask."""

    start: int
    end: int
    kind: Kind
    confidence: Confidence

    def __post_init__(self) -> None:
        if not 0 <= self.start < self.end:
            raise ValueError("Span needs 0 <= start < end.")
        if self.kind not in KINDS:
            raise ValueError(f"Unknown span kind: {self.kind!r}.")
        if self.confidence not in CONFIDENCES:
            raise ValueError(f"Unknown span confidence: {self.confidence!r}.")


@dataclass(frozen=True)
class FilterResult:
    """A masked text, how many values of each kind were masked, and whether a certain secret was found."""

    text: str
    counts: Mapping[str, int] = field(default_factory=dict)  # kind -> count; only kinds with a count >= 1
    alarm: bool = False

    @property
    def masked(self) -> int:
        """The sum of the counts."""
        return sum(self.counts.values())
