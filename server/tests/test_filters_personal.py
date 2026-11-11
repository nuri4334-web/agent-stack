"""S3-07: personal data rules (S1-11 catalog K1-K5).

Only fake values are used (example.com, test card numbers, all-zero bank codes, checksum-built numbers).
Results are checked by kind, confidence, position and count; test ids are labels, never the values.
"""
import pytest

from app.filters.normalize import normalize
from app.filters.personal import find_personal
from app.filters.types import Span

EMAIL = "ornek.kisi@example.com"
PHONE_INTL = "+90 500 000 00 00"
PHONE_LOCAL = "0500 000 00 00"
TCKN = "10000000146"
TCKN_2 = "20000000046"
TCKN_BAD_10TH = "10000000156"
TCKN_BAD_11TH = "10000000147"
IBAN_SPACED = "TR20 0000 0000 0000 0000 0000 01"
IBAN_COMPACT = "TR200000000000000000000001"
IBAN_BAD = "TR21 0000 0000 0000 0000 0000 01"
CARD_VISA = "4111 1111 1111 1111"
CARD_VISA_COMPACT = "4111111111111111"
CARD_VISA_DASHED = "4111-1111-1111-1111"
CARD_AMEX = "3782 822463 10005"
CARD_MASTERCARD = "5555555555554444"
CARD_VISA_13 = "4222222222222"
CARD_BAD_LUHN = "4111 1111 1111 1112"
DATETIME_LUHN_VALID = "20261111143008"  # passes Luhn, but it is 11 Nov 2026 14:30:08
EPOCH_MS_LUHN_VALID = "1731312000002"  # passes Luhn, but it is a Unix time in milliseconds
ORDER_LUHN_VALID = "1000000000000008"  # passes Luhn


def found(text):
    return [(s.kind, s.confidence) for s in find_personal(text)]


def at(text, value):
    start = text.index(value)
    return start, start + len(value)


def positions(text):
    return [(s.start, s.end) for s in find_personal(text)]


# --- K1 email --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    f"Bana {EMAIL} adresinden yaz.",
    f"<mailto:{EMAIL}|x>",
    f"({EMAIL})",
    f"{EMAIL}.",
], ids=["sentence", "slack_mailto", "brackets", "trailing_dot"])
def test_email_is_certain(text):
    assert found(text) == [("email", "certain")]
    assert positions(text) == [at(text, EMAIL)]


@pytest.mark.parametrize("text", [
    "@Ali bakar mısın?",
    "<@U0123ABCD> deploy bitti",
    "git clone git@github.com:example/repo.git",
    "ssh://git@github.com/example/repo.git",
    "https://user@example.com/path",
    "ali@localhost",
    "toplantı @ 14:00",
], ids=["slack_mention", "slack_user_id", "ssh_remote", "ssh_url", "url_userinfo", "no_tld", "at_sign_alone"])
def test_not_an_email(text):
    assert find_personal(text) == []


# --- K2 phone --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    PHONE_INTL, "+905000000000", "+90 (500) 000 00 00", "+90-500-000-00-00", "+90 500 000 0000",
], ids=["spaced", "compact", "brackets", "dashed", "four_digit_end"])
def test_phone_with_plus_90_is_certain(text):
    message = f"Arayın: {text} lütfen"
    assert found(message) == [("phone", "certain")]
    assert positions(message) == [at(message, text)]


@pytest.mark.parametrize("text", [PHONE_LOCAL, "05000000000", "0 (500) 000 00 00", "0500-000-00-00"],
                         ids=["spaced", "compact", "brackets", "dashed"])
def test_phone_starting_with_05_is_suspicious(text):
    message = f"tel {text}"
    assert found(message) == [("phone", "suspicious")]
    assert positions(message) == [at(message, text)]


@pytest.mark.parametrize("text", [
    "+90 400 000 00 00",  # not a mobile number
    "0400 000 00 00",
    "050000000000",  # 12 digits
    "105000000000",
    "05.11.2026 tarihinde",
    "sipariş no: 05000000000",
], ids=["plus90_not_5", "local_not_5", "too_long", "inside_longer_number", "date", "order_label"])
def test_not_a_phone(text):
    assert [k for k, _ in found(text) if k == "phone"] == []


# --- K3 tckn ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    f"TC: {TCKN}", f"T.C. kimlik no {TCKN}", f"TCKN {TCKN}", f"Kimlik numaram {TCKN}",
    f"KİMLİK NO: {TCKN}", f"KIMLIK: {TCKN}", f"{TCKN} (TC kimlik)", f"TC{TCKN}",
], ids=["tc", "tc_kimlik_no", "tckn", "kimlik", "upper_dotted_i", "upper_ascii_i", "label_after", "label_glued"])
def test_tckn_with_label_is_certain(text):
    assert found(text) == [("tckn", "certain")]
    assert positions(text) == [at(text, TCKN)]


@pytest.mark.parametrize("value", [TCKN, TCKN_2], ids=["sample_1", "sample_2"])
def test_tckn_without_label_is_suspicious(value):
    text = f"numara: {value}"
    assert found(text) == [("tckn", "suspicious")]


@pytest.mark.parametrize("text", [
    f"TC {TCKN_BAD_10TH}", f"TC {TCKN_BAD_11TH}", "TC 00000000146", f"TC {TCKN}7", f"TC 9{TCKN}",
    f"etc {TCKN}x", f"sipariş no {TCKN}", f"Order #{TCKN}",
], ids=["bad_10th_digit", "bad_11th_digit", "starts_with_zero", "12_digits", "inside_longer", "glued_letter_after",
        "order_label_tr", "order_label_en"])
def test_not_a_tckn(text):
    assert [k for k, _ in found(text) if k == "tckn"] == []


def test_etc_is_not_a_tc_label():
    assert found(f"vs, etc {TCKN}") == [("tckn", "suspicious")]


def test_far_label_does_not_make_tckn_certain():
    text = "TC" + " bu cümle etiketten epey uzakta kalıyor ve" + f" {TCKN}"
    assert found(text) == [("tckn", "suspicious")]


# --- K4 iban ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [IBAN_SPACED, IBAN_COMPACT, IBAN_SPACED.lower()], ids=["spaced", "compact", "lower"])
def test_iban_is_certain(value):
    text = f"IBAN: {value} (hesap)"
    assert found(text) == [("iban", "certain")]
    assert positions(text) == [at(text, value)]


@pytest.mark.parametrize("text", [
    IBAN_BAD,  # mod-97 fails
    "TR20 0000 0000 0000 0000 0000 0",  # too short
    "TR20 0000 0000 0000 0000 0000 012",  # too long
    "XTR200000000000000000000001",
    "DE89 3704 0044 0532 0130 00",  # only TR is in scope
], ids=["bad_checksum", "too_short", "too_long", "glued_letter_before", "other_country"])
def test_not_an_iban(text):
    assert [k for k, _ in found(text) if k == "iban"] == []


def test_iban_is_one_span_not_a_card_inside_it():
    assert found(f"IBAN {IBAN_SPACED}") == [("iban", "certain")]


# --- K5 card ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    CARD_VISA, CARD_VISA_COMPACT, CARD_VISA_DASHED, CARD_AMEX, CARD_MASTERCARD, CARD_VISA_13,
], ids=["visa_spaced", "visa_compact", "visa_dashed", "amex_4_6_5", "mastercard", "visa_13"])
def test_card_is_certain(value):
    text = f"kart: {value}, son kullanma 12/28"
    assert found(text) == [("card", "certain")]
    assert positions(text) == [at(text, value)]


@pytest.mark.parametrize("text", [
    CARD_BAD_LUHN,
    "4111 1111 11111 111",  # irregular groups
    "4111 1111-1111 1111",  # mixed separators
    "411111111111",  # 12 digits
    "41111111111111111111",  # 20 digits
    f"log {DATETIME_LUHN_VALID}",
    f"ts={EPOCH_MS_LUHN_VALID}",
    f"Sipariş No: {ORDER_LUHN_VALID}",
    f"siparis numarasi {ORDER_LUHN_VALID}",
    f"Order #{ORDER_LUHN_VALID}",
    f"takip kodu: {ORDER_LUHN_VALID}",
    f"id-{CARD_VISA_COMPACT}x",
], ids=["bad_luhn", "irregular_groups", "mixed_separators", "too_short", "too_long", "datetime", "epoch_ms",
        "order_label_tr", "order_label_ascii", "order_label_en", "tracking_label", "glued_letters"])
def test_not_a_card(text):
    assert [k for k, _ in found(text) if k == "card"] == []


def test_order_word_far_from_the_number_does_not_hide_a_card():
    text = f"Siparişimi şu kartla ödedim: {CARD_VISA}"
    assert found(text) == [("card", "certain")]


# --- normalize, positions, overlaps -----------------------------------------------------------------------------

def test_invisible_characters_do_not_hide_values_and_positions_refer_to_normalized_text():
    raw = f"\u200bmail: orn\u200bek.kisi@exa\u2060mple.com, kart 4111\u200b 1111 1111 1111"
    text = normalize(raw)
    assert find_personal(raw) == find_personal(text)
    assert found(raw) == [("email", "certain"), ("card", "certain")]
    assert positions(raw) == [at(text, EMAIL), at(text, CARD_VISA)]


def test_turkish_text_around_values_keeps_positions():
    text = f"İşçi Şükrü'nün ğüşıöç notu: {EMAIL} — İBAN {IBAN_SPACED}; tel {PHONE_INTL}"
    assert found(text) == [("email", "certain"), ("iban", "certain"), ("phone", "certain")]
    assert positions(text) == [at(text, EMAIL), at(text, IBAN_SPACED), at(text, PHONE_INTL)]


def test_many_values_in_one_text_are_sorted_and_do_not_overlap():
    text = (f"{EMAIL} {PHONE_INTL} {PHONE_LOCAL} TC {TCKN} {IBAN_COMPACT} {CARD_VISA} "
            f"ikinci {EMAIL} ve {TCKN_2}")
    spans = find_personal(text)
    assert [s.kind for s in spans] == ["email", "phone", "phone", "tckn", "iban", "card", "email", "tckn"]
    assert [s.confidence for s in spans] == [
        "certain", "certain", "suspicious", "certain", "certain", "certain", "certain", "suspicious"]
    assert all(a.end <= b.start for a, b in zip(spans, spans[1:]))
    assert all(isinstance(s, Span) for s in spans)


def test_plain_text_and_innocent_numbers_find_nothing():
    text = "Deploy 14:30'da, sürüm 2.4.1, PR #1234, 2026-11-11, port 8080, issue 123456789."
    assert find_personal(text) == []


def test_empty_text_finds_nothing():
    assert find_personal("") == []
