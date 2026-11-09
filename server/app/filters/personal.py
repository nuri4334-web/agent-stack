"""Personal data rules (S3-07): e-mail, phone, TC identity number, IBAN, card number."""
from .types import Span


def find_personal(text: str) -> list[Span]:
    """The personal data in a normalized text."""
    # Skeleton (S3-01). Rules: Görkem, Wed 11 Nov (S3-07).
    return []
