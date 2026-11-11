"""Name rules (S3-07): the names of the Slack people.

Every full name and every part of it (first name, surname) is looked up as a whole word, case-insensitively with
the Turkish rules (I <-> ı, İ <-> i). The longest name wins: "Ali Kaya" is one span, never "Ali" + "Kaya".
"""
import re
from collections.abc import Sequence

from .normalize import normalize
from .types import Span

# A name is not a part of a longer word: "Ali" is not found in "Alican", but it is in "@Ali" and "Ali'nin".
_WORD_START = r"(?<!\w)"
_WORD_END = r"(?!\w)"
_MIN_PART_LENGTH = 2  # a single letter ("A.") is an initial, not a name
_WORD = re.compile(r"\w+(?:[-'’]\w+)*")


def find_names(text: str, people: Sequence[str]) -> list[Span]:
    """Whole-word, case-insensitive matches (Turkish İ/ı handled) of people, the shown names of non-bot Slack users.

    Positions refer to normalize(text); spans are sorted by position and never overlap.
    """
    pattern = _pattern(people)
    if pattern is None:
        return []
    folded = turkish_lower(normalize(text))  # same length as the normalized text, so positions carry over
    return [Span(m.start(), m.end(), "person", "certain") for m in pattern.finditer(folded)]


def turkish_lower(text: str) -> str:
    """Lower case with the Turkish rules (I -> ı, İ -> i), one character for one character."""
    out = []
    for c in text:
        if c == "I":
            out.append("ı")
        elif c == "İ":
            out.append("i")
        else:
            lower = c.lower()
            out.append(lower if len(lower) == 1 else c)
    return "".join(out)


def _pattern(people: Sequence[str]) -> re.Pattern[str] | None:
    terms: set[tuple[str, ...]] = set()
    for person in people:
        # Words only: "Ali Kaya (PM)" -> ali, kaya, pm; a hyphen or apostrophe inside a word stays ("Ayşe-Nur").
        words = tuple(_WORD.findall(turkish_lower(normalize(person))))
        if len(" ".join(words)) < _MIN_PART_LENGTH:
            continue
        terms.add(words)
        terms.update((w,) for w in words if len(w) >= _MIN_PART_LENGTH)
    if not terms:
        return None
    # Longest first, so at any position the full name is tried before its parts.
    ordered = sorted(terms, key=lambda t: (-len(" ".join(t)), t))
    alternatives = "|".join(r"\s+".join(re.escape(w) for w in words) for words in ordered)
    return re.compile(_WORD_START + "(?:" + alternatives + ")" + _WORD_END)
