"""Filter entry points (S3-01): what the Slack sync and the gateway call.

(A) Before a Slack message is written to the database: mask_secrets only.
(B) At question time, gateway step 4 (sanitization): mask_secrets, then Vault.mask; step 7 (presentation):
    Vault.restore. [REDACTED] is never restored.
"""
import re
from collections import Counter
from collections.abc import Iterable, Sequence

from .names import find_names
from .normalize import normalize
from .personal import find_personal
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


_PLACEHOLDER_PREFIX = {
    "email": "EMAIL", "phone": "PHONE", "tckn": "TCKN", "iban": "IBAN", "card": "CARD", NAME_KIND: "PERSON",
}
# A placeholder, as the Vault writes it and as it is recognized in any text (input or answer).
# No left boundary: a TC number glued to its label ("TC123...") becomes "TCTCKN_1" and must still be restored.
# Right boundary: digits only, so PERSON_1 is never read inside PERSON_10. A letter right after it does not stop it
# ("PERSON_1ın" is restored), because the personal rules allow a non-ASCII letter right after a number.
_PLACEHOLDER = re.compile(r"(?:EMAIL|PHONE|TCKN|IBAN|CARD|PERSON)_[0-9]+(?![0-9])")


class Vault:
    """One per request, in memory only: personal data and names -> EMAIL_1, PHONE_1, TCKN_1, IBAN_1, CARD_1,
    PERSON_1, and back.

    - The same value (same kind and exactly the same normalized text) -> the same placeholder; numbers count per kind
      from 1, in the order the values are first seen.
    - A placeholder text already written in an input is never given out (Clarification 3), and a placeholder that was
      given out and later appears written in an input is never restored: a user's own "EMAIL_1" never becomes a real
      e-mail.
    - restore() opens only placeholders this Vault gave out; [REDACTED] and any other text stay.
    Nothing is logged or written; repr() shows only a count. No error raised here carries a value or a text.
    """

    def __init__(self) -> None:
        self._placeholder_of: dict[tuple[str, str], str] = {}  # (kind, value) -> placeholder
        self._value_of: dict[str, str] = {}  # placeholder -> value
        self._last_number: dict[str, int] = {}  # kind -> last number given out
        self._literals: set[str] = set()  # placeholder texts seen written in an input
        self._ambiguous: set[str] = set()  # given out and later seen written in an input: never restored

    def __repr__(self) -> str:
        return f"Vault({len(self._value_of)} placeholders)"

    def mask(self, text: str, people: Sequence[str]) -> FilterResult:
        """Personal data and names replaced by placeholders; counts per kind (every occurrence)."""
        clean = normalize(text)
        written = set(_PLACEHOLDER.findall(clean))
        self._literals |= written
        self._ambiguous |= written & self._value_of.keys()
        spans = choose_spans([*find_personal(clean), *find_names(clean, people)])
        placeholders = [self._placeholder(span.kind, clean[span.start:span.end]) for span in spans]
        masked = clean
        for span, placeholder in reversed(list(zip(spans, placeholders))):
            masked = masked[:span.start] + placeholder + masked[span.end:]
        return FilterResult(text=masked, counts=dict(Counter(span.kind for span in spans)))

    def restore(self, answer: str) -> str:
        """Placeholders of this Vault replaced by the real values, in one pass; [REDACTED] stays."""
        def put_back(match: re.Match[str]) -> str:
            placeholder = match.group(0)
            if placeholder in self._ambiguous:
                return placeholder
            return self._value_of.get(placeholder, placeholder)

        return _PLACEHOLDER.sub(put_back, answer)

    def _placeholder(self, kind: str, value: str) -> str:
        known = self._placeholder_of.get((kind, value))
        if known is not None:
            return known
        number = self._last_number.get(kind, 0)
        while True:
            number += 1
            placeholder = f"{_PLACEHOLDER_PREFIX[kind]}_{number}"
            if placeholder not in self._literals and placeholder not in self._value_of:
                break
        self._last_number[kind] = number
        self._placeholder_of[(kind, value)] = placeholder
        self._value_of[placeholder] = value
        return placeholder
