"""Filter entry points (S3-01): what the Slack sync and the gateway call.

(A) Before a Slack message is written to the database: mask_secrets only.
(B) At question time, gateway step 4 (sanitization): mask_secrets, then Vault.mask; step 7 (presentation):
    Vault.restore. [REDACTED] is never restored.
"""
from collections.abc import Sequence

from .types import FilterResult

REDACTED = "[REDACTED]"


def mask_secrets(text: str) -> FilterResult:
    """Secrets replaced by [REDACTED]; counts by kind; alarm=True if a certain secret was found."""
    # Skeleton (S3-01). Body: Musa, Thu 12 Nov (S3-09).
    return FilterResult(text=text)


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
