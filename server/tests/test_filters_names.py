"""S3-07: name rules — Slack people names as whole words, Turkish case rules, the longest name wins.

Only made-up names are used. Results are checked by kind, position and count.
"""
import pytest

from app.filters.names import find_names, turkish_lower
from app.filters.normalize import normalize

PEOPLE = ["Ali Kaya", "Ayşe Yılmaz", "Işık Demir", "İrem Çelik"]


def spans(text, people=PEOPLE):
    return [(s.start, s.end) for s in find_names(text, people)]


def at(text, value, start=0):
    i = text.index(value, start)
    return i, i + len(value)


def test_full_name_is_one_span():
    text = "Ali Kaya deploy etti."
    result = find_names(text, PEOPLE)
    assert [(s.kind, s.confidence) for s in result] == [("person", "certain")]
    assert spans(text) == [at(text, "Ali Kaya")]


def test_full_name_with_extra_space_or_line_break_is_one_span():
    for text in ["Ali  Kaya geldi", "Ali\nKaya geldi"]:
        assert spans(text) == [(0, text.index(" geldi"))]


def test_first_name_and_surname_are_found_alone():
    text = "Ali geldi, Kaya ise gelmedi."
    assert spans(text) == [at(text, "Ali"), at(text, "Kaya")]


@pytest.mark.parametrize("text, value", [
    ("@Ali bakar mısın", "Ali"),
    ("Ali'nin PR'ı", "Ali"),
    ("(Ali)", "Ali"),
    ("Ali, Ayşe.", "Ali"),
], ids=["slack_mention", "turkish_suffix_with_apostrophe", "brackets", "punctuation"])
def test_whole_word_match_next_to_punctuation(text, value):
    assert spans(text)[0] == at(text, value)


@pytest.mark.parametrize("text", [
    "Alican geldi", "Kayahan", "MaliKaya", "ali_kaya", "Ali2", "Kayalar",
], ids=["prefix_of_word", "surname_prefix", "inside_word", "underscore", "digit_after", "suffix_without_apostrophe"])
def test_name_inside_a_longer_word_is_not_found(text):
    assert spans(text) == []


@pytest.mark.parametrize("text, value", [
    ("IŞIK geldi", "IŞIK"),
    ("ışık geldi", "ışık"),
    ("Işık Demir geldi", "Işık Demir"),
    ("IŞIK DEMİR geldi", "IŞIK DEMİR"),
    ("AYŞE geldi", "AYŞE"),
    ("ayşe geldi", "ayşe"),
    ("İREM geldi", "İREM"),
    ("irem geldi", "irem"),
    ("ALİ KAYA", "ALİ KAYA"),
], ids=["isik_upper", "isik_lower", "isik_full", "isik_full_upper", "ayse_upper", "ayse_lower", "irem_upper",
        "irem_lower", "ali_kaya_upper"])
def test_turkish_case_rules(text, value):
    assert spans(text) == [at(text, value)]


@pytest.mark.parametrize("text", ["isik geldi", "ISIK geldi", "IREM geldi", "ALI geldi", "ırem geldi"],
                         ids=["isik_dotted_i", "isik_ascii_upper", "irem_dotless_upper", "ali_dotless_upper",
                              "irem_dotless_lower"])
def test_turkish_dotted_and_dotless_i_are_different_letters(text):
    assert spans(text) == []


def test_turkish_lower_keeps_length():
    for text in ["İIıi", "IŞIK DEMİR", "ǅ ẞ ŉ"]:
        assert len(turkish_lower(text)) == len(text)
    assert turkish_lower("IŞIK İREM") == "ışık irem"


def test_longest_match_wins_and_parts_are_not_returned_again():
    text = "Ali Kaya ve Ayşe Yılmaz"
    assert spans(text) == [at(text, "Ali Kaya"), at(text, "Ayşe Yılmaz")]


def test_a_name_that_is_also_a_part_of_another_name():
    people = ["Ali", "Ali Kaya", "Kaya Su"]
    text = "Ali Kaya Su"
    result = spans(text, people)
    assert result == [(0, 8), (9, 11)] or result == [(0, 3), (4, 11)]
    assert all(a[1] <= b[0] for a, b in zip(result, result[1:]))


def test_spans_never_overlap_and_are_sorted():
    text = "Ali Kaya, Kaya, Ali, Ayşe Yılmaz, Yılmaz, İrem Çelik"
    result = spans(text)
    assert len(result) == 6
    assert all(a[1] <= b[0] for a, b in zip(result, result[1:]))


def test_positions_refer_to_the_normalized_text():
    raw = "\u200bSelam A\u200bli Ka\u2060ya, I\u200dŞIK!"
    text = normalize(raw)
    assert spans(raw) == [at(text, "Ali Kaya"), at(text, "IŞIK")]


def test_names_with_invisible_characters_in_the_people_list():
    assert spans("Ali Kaya", ["A\u200bli Kaya"]) == [(0, 8)]


@pytest.mark.parametrize("people", [[], [""], ["   "], ["A"]], ids=["empty", "empty_name", "blank_name", "initial"])
def test_empty_or_too_short_people_find_nothing(people):
    assert find_names("A Ali Kaya", people) == []


def test_single_letter_initial_is_not_a_part_but_the_surname_is():
    text = "A. Kaya ve A geldi"
    assert spans(text, ["A. Kaya"]) == [at(text, "Kaya")]


def test_special_regex_characters_in_names_are_literal():
    text = "Ali (PM) ve Ali.PM ve AliXPM"
    result = find_names(text, ["Ali (PM)", "C++ Dev"])
    assert [(s.start, s.end) for s in result] == [(0, 3), (5, 7), (12, 15), (16, 18)]


def test_no_people_text_without_names():
    assert find_names("Deploy bitti, testler yeşil.", PEOPLE) == []
