"""S3-01: normalize removes invisible characters and nothing else."""
import pytest

from app.filters.normalize import normalize

# The invisible characters of the filter interface, written as escapes (never pasted).
INVISIBLE = (
    [chr(c) for c in range(0x200B, 0x2010)]
    + [chr(c) for c in range(0x202A, 0x202F)]
    + [chr(c) for c in range(0x2060, 0x2065)]
    + ["\ufeff"]
)


def test_zero_width_space_inside_a_slack_token_is_removed():
    hidden = "xo\u200bxb-0000000000-0000000000000-EXAMPLE"
    assert normalize(hidden) == "xoxb-0000000000-0000000000000-EXAMPLE"


@pytest.mark.parametrize("char", INVISIBLE, ids=[f"U+{ord(c):04X}" for c in INVISIBLE])
def test_every_invisible_character_is_removed(char):
    assert normalize(f"a{char}b{char}") == "ab"


@pytest.mark.parametrize("text", [
    "Şişli'de çay içtik: ğüşıöç İĞÜŞÖÇ",
    "Toplantı 14:00'te 🎉👍🏽",
    "satır bir\nsatır iki\r\nsatır üç\tsekme",
    "AbC dEf",
    "",
])
def test_visible_text_case_and_line_breaks_stay(text):
    assert normalize(text) == text


@pytest.mark.parametrize("char", [" ", "‐", " ", "⁥", " "],
                         ids=["U+200A", "U+2010", "U+2029", "U+2065", "U+00A0"])
def test_characters_just_outside_the_ranges_stay(char):
    assert normalize(f"a{char}b") == f"a{char}b"


def test_normalize_is_idempotent():
    once = normalize("x\u200by\u202ez\ufeff")
    assert normalize(once) == once == "xyz"
