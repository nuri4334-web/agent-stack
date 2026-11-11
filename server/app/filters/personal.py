"""Personal data rules (S3-07): e-mail, phone, TC identity number, IBAN, card number (S1-11 catalog, K1-K5).

Confidence follows the catalog:
  K1 email  certain
  K2 phone  +90 5xx: certain; 05xx: suspicious
  K3 tckn   certain when "TC" or "kimlik" is near, suspicious otherwise
  K4 iban   certain (TR + 24 digits, mod-97 checked)
  K5 card   certain (13-19 digits, Luhn checked; dates and labelled order numbers are skipped)

The rules only read the text: no value is kept, logged or put in an error message.
"""
import re
from collections.abc import Iterator

from .normalize import normalize
from .types import Confidence, Span

# Numbers: a digit run is never a part of a longer word or number.
_NUM_START = r"(?<![0-9A-Za-z])"
_NUM_END = r"(?![0-9A-Za-z])"

# K1. Local part and domain labels may hold Unicode letters; the top-level domain is letters only.
# "@Ali" (no local part, no domain) is not an e-mail.
_EMAIL = re.compile(
    r"(?<![\w.%+-])[\w%+-]+(?:\.[\w%+-]+)*@[^\W_](?:[\w-]*[^\W_])?(?:\.[^\W_](?:[\w-]*[^\W_])?)*\.[^\W\d_]{2,}(?![\w-])"
)
# git@github.com:org/repo (SSH remote), ssh://git@host/... and https://user@host/... are addresses, not e-mails.
_SSH_AFTER = re.compile(r":[\w~./-]")
_URL_BEFORE = re.compile(r"://$")

# K2. Separators inside a phone number: one space or one hyphen; the area code may be in brackets.
_PHONE_BODY = r"\(?5[0-9]{2}\)?[ -]?[0-9]{3}[ -]?[0-9]{2}[ -]?[0-9]{2}"
_PHONE_INTL = re.compile(r"(?<![\w+])\+90[ -]?" + _PHONE_BODY + _NUM_END)
_PHONE_LOCAL = re.compile(r"(?<![\w+])0[ -]?" + _PHONE_BODY + _NUM_END)

# K3. 11 digits, the first is not 0. "TC12345678901" (label glued to the number) is allowed.
_TCKN = re.compile(r"(?:(?<=[Tt][Cc])|" + _NUM_START + r")[1-9][0-9]{10}" + _NUM_END)
_TCKN_LABEL = re.compile(r"(?<![a-zçğıöşü])(?:t\.?\s?c\.?(?:\s?k\.?\s?n\.?|\s?no)?|tckn\w*|kimlik\w*)(?![a-zçğıöşü])")
_TCKN_LABEL_BEFORE = 30
_TCKN_LABEL_AFTER = 20

# K4. TR + 2 check digits + 22 digits, written in groups of four or without spaces.
_IBAN = re.compile(r"(?<![0-9A-Za-z])[Tt][Rr][0-9]{2}(?: ?[0-9]{4}){5} ?[0-9]{2}" + _NUM_END)

# K5. 13-19 digits: plain, in groups of four with one kind of separator, or the Amex 4-6-5 form.
_CARD = re.compile(
    _NUM_START
    + r"(?:[0-9]{13,19}"
    + r"|[0-9]{4}([ -])[0-9]{4}\1[0-9]{4}\1[0-9]{1,4}(?:\1[0-9]{1,3})?"
    + r"|[0-9]{4}([ -])[0-9]{6}\2[0-9]{5})"
    + _NUM_END
)

# An explicit order/invoice/tracking label right before a number: "sipariş no: 1234...", "Order #1234...".
_ORDER_LABEL = re.compile(
    r"(?:sipari[sş]\w*|order\w*|fatura\w*|invoice\w*|takip\w*|tracking|kargo\w*)"
    r"(?:\s*(?:no|numaras[ıi]|number|num|id|kodu|code))?\.?\s*[:#-]?\s*$"
)
_ORDER_LABEL_WINDOW = 40


def find_personal(text: str) -> list[Span]:
    """The personal data in normalize(text), sorted by position, never overlapping.

    Positions refer to the normalized text (normalize is idempotent, so a normalized input is unchanged).
    """
    text = normalize(text)
    candidates = [
        *_emails(text), *_ibans(text), *_cards(text), *_phones(text), *_tckns(text),
    ]
    return _without_overlaps(candidates)


def _emails(text: str) -> Iterator[Span]:
    for match in _EMAIL.finditer(text):
        if _SSH_AFTER.match(text, match.end()) or _URL_BEFORE.search(text, 0, match.start()):
            continue
        yield Span(match.start(), match.end(), "email", "certain")


def _phones(text: str) -> Iterator[Span]:
    for match in _PHONE_INTL.finditer(text):
        yield Span(match.start(), match.end(), "phone", "certain")
    for match in _PHONE_LOCAL.finditer(text):
        if _balanced_brackets(match.group()) and not _after_order_label(text, match.start()):
            yield Span(match.start(), match.end(), "phone", "suspicious")


def _tckns(text: str) -> Iterator[Span]:
    for match in _TCKN.finditer(text):
        if not _tckn_checksum_ok(match.group()) or _after_order_label(text, match.start()):
            continue
        confidence: Confidence = "certain" if _has_tckn_label(text, match.start(), match.end()) else "suspicious"
        yield Span(match.start(), match.end(), "tckn", confidence)


def _ibans(text: str) -> Iterator[Span]:
    for match in _IBAN.finditer(text):
        if _iban_checksum_ok(match.group()):
            yield Span(match.start(), match.end(), "iban", "certain")


def _cards(text: str) -> Iterator[Span]:
    for match in _CARD.finditer(text):
        digits = _digits(match.group())
        if not 13 <= len(digits) <= 19 or not _luhn_ok(digits):
            continue
        if _looks_like_timestamp(digits) or _after_order_label(text, match.start()):
            continue
        yield Span(match.start(), match.end(), "card", "certain")


# --- checks ---------------------------------------------------------------------------------------------------


def _digits(value: str) -> str:
    return "".join(c for c in value if "0" <= c <= "9")


def _balanced_brackets(value: str) -> bool:
    return value.count("(") == value.count(")")


def _tckn_checksum_ok(number: str) -> bool:
    d = [int(c) for c in number]
    if len(d) != 11 or d[0] == 0:
        return False
    tenth = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    return d[9] == tenth and d[10] == sum(d[:10]) % 10


def _iban_checksum_ok(value: str) -> bool:
    compact = value.replace(" ", "").upper()
    rearranged = compact[4:] + compact[:4]
    as_digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(as_digits) % 97 == 1


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(digits)):
        n = int(c)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _looks_like_timestamp(digits: str) -> bool:
    """A 14-digit date-time (YYYYMMDDhhmmss) or a 13-digit Unix time in milliseconds (2001-2033)."""
    if len(digits) == 14:
        year, month, day = int(digits[0:4]), int(digits[4:6]), int(digits[6:8])
        hour, minute, second = int(digits[8:10]), int(digits[10:12]), int(digits[12:14])
        return (1900 <= year <= 2199 and 1 <= month <= 12 and 1 <= day <= 31
                and hour <= 23 and minute <= 59 and second <= 59)
    if len(digits) == 13:
        return 1_000_000_000_000 <= int(digits) < 2_000_000_000_000
    return False


def _fold(text: str) -> str:
    """Lower case for label search; every i form (I, İ, ı, i) becomes i. Same length as the input."""
    out = []
    for c in text:
        if c in "Iİı":
            out.append("i")
        else:
            lower = c.lower()
            out.append(lower if len(lower) == 1 else c)
    return "".join(out)


def _has_tckn_label(text: str, start: int, end: int) -> bool:
    before = _fold(text[max(0, start - _TCKN_LABEL_BEFORE):start])
    after = _fold(text[end:end + _TCKN_LABEL_AFTER])
    # A label glued to the number ("TC12345678901") is found in the text before it.
    return bool(_TCKN_LABEL.search(before + " ") or _TCKN_LABEL.search(" " + after))


def _after_order_label(text: str, start: int) -> bool:
    return bool(_ORDER_LABEL.search(_fold(text[max(0, start - _ORDER_LABEL_WINDOW):start])))


def _without_overlaps(spans: list[Span]) -> list[Span]:
    """Certain before suspicious, then the longer, then the earlier; a span overlapping a kept one is dropped."""
    kept: list[Span] = []
    for span in sorted(spans, key=lambda s: (s.confidence != "certain", s.start - s.end, s.start)):
        if all(span.end <= k.start or k.end <= span.start for k in kept):
            kept.append(span)
    return sorted(kept, key=lambda s: s.start)

