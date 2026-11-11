"""Filter entry points (S3-01): what the Slack sync and the gateway call.

(A) Before a Slack message is written to the database: mask_secrets only.
(B) At question time, gateway step 4 (sanitization): mask_secrets, then Vault.mask; step 7 (presentation):
    Vault.restore. [REDACTED] is never restored.
"""
from collections import Counter
from collections.abc import Iterable, Sequence

from .normalize import normalize
from .secrets import REDACTED, find_secrets
from .types import NAME_KIND, PERSONAL_KINDS, SECRET_KINDS, FilterResult, Span

_GROUP = {kind: 0 for kind in SECRET_KINDS} | {kind: 1 for kind in PERSONAL_KINDS} | {NAME_KIND: 2}


def choose_spans(spans: Iterable[Span]) -> list[Span]:
    """Overlapping findings: the longer one wins; at equal length secret > personal data > name.

    Among secrets of equal length a specific kind beats env_secret (one value is counted once, under its most specific
    kind: GITHUB_TOKEN=ghp_... counts as github_token), then a certain one beats a suspicious one.
    Returns non-overlapping spans by start.
    """
    def rank(s: Span):
        return (-(s.end - s.start), _GROUP[s.kind], s.kind == "env_secret", s.confidence != "certain", s.start)

    chosen: list[Span] = []
    for span in sorted(set(spans), key=rank):
        if all(span.end <= c.start or span.start >= c.end for c in chosen):
            chosen.append(span)
    return sorted(chosen, key=lambda s: s.start)


def _replace(text: str, spans: Sequence[Span], placeholder: str) -> str:
    for span in reversed(spans):
        text = text[:span.start] + placeholder + text[span.end:]
    return text


def mask_secrets(text: str) -> FilterResult:
    """Secrets replaced by [REDACTED]; counts by kind; alarm=True if a certain secret was found.

    normalize -> find_secrets -> overlap rule -> [REDACTED]. The alarm looks at every certain finding, also one
    that lost an overlap. An already masked [REDACTED] is never counted again.
    """
    clean = normalize(text)
    found = find_secrets(clean)
    chosen = choose_spans(found)
    return FilterResult(
        text=_replace(clean, chosen, REDACTED),
        counts=dict(Counter(s.kind for s in chosen)),
        alarm=any(s.confidence == "certain" for s in found),
    )


class Vault:
    """One per request, in memory only: personal data and names -> EMAIL_1, PHONE_1, TCKN_1, IBAN_1, CARD_1,
    PERSON_1 (the same value -> the same placeholder), and back."""

    def mask(self, text: str, people: Sequence[str]) -> FilterResult:
        """Personal data and names replaced by placeholders."""
        # Skeleton (S3-01). Body: Nuri, Thu-Fri 12-13 Nov.
        return FilterResult(text=text)

    def restore(self, answer: str) -> str:
        """Placeholders replaced by the real values; [REDACTED] stays."""
        # Skeleton (S3-01). Body: Nuri, Thu-Fri 12-13 Nov.
        return answer
