"""S3-12: the Vault (app/filters/api.py): placeholders for personal data and names, and back.

Pure tests (no database, no AI). Values never appear in test output: a bool is computed first and asserted with a
message that names only the kind. The personal data comes from tests/attack_samples.py (made up, valid checksums);
the people names are made up for these tests.
"""
import logging

import pytest

from app.filters.api import Vault
from app.filters.normalize import normalize
from app.filters.types import FilterResult
from tests import attack_samples as s

PEOPLE = ["Deniz Aydın"]
OTHER_EMAIL = "second.user@example.com"
ELEVEN = ["Ada", "Bora", "Cem", "Derya", "Ece", "Fikret", "Gül", "Hakan", "Irmak", "Jale", "Kaan"]


def test_same_value_same_placeholder():
    vault = Vault()
    first = vault.mask(f"a {s.EMAIL} b {s.EMAIL}", [])
    second = vault.mask(f"c {s.EMAIL}", [])
    assert (first.text, dict(first.counts)) == ("a EMAIL_1 b EMAIL_1", {"email": 2})
    assert (second.text, dict(second.counts)) == ("c EMAIL_1", {"email": 1})


def test_numbers_per_kind():
    vault = Vault()
    result = vault.mask(f"{s.EMAIL} {s.PHONE_INTL} Deniz {OTHER_EMAIL}", PEOPLE)
    assert result.text == "EMAIL_1 PHONE_1 PERSON_1 EMAIL_2"
    assert dict(result.counts) == {"email": 2, "phone": 1, "person": 1}
    assert result.alarm is False


def test_case_variants_are_separate_and_restore_exactly():
    vault = Vault()
    result = vault.mask("Deniz ve deniz geldi", PEOPLE)
    assert result.text == "PERSON_1 ve PERSON_2 geldi"
    assert vault.restore("PERSON_2, PERSON_1") == "deniz, Deniz"


def test_overlap_longer_wins_counted_once():
    """An e-mail that contains a person's name is one e-mail; the name is not counted too."""
    vault = Vault()
    result = vault.mask("yaz: deniz.aydin@example.com", PEOPLE)
    assert (result.text, dict(result.counts)) == ("yaz: EMAIL_1", {"email": 1})
    assert vault.restore(result.text) == "yaz: deniz.aydin@example.com"


def test_restore_boundaries():
    vault = Vault()
    vault.mask(" ".join(ELEVEN) + f" {s.EMAIL}", ELEVEN)
    restored = {
        "PERSON_1 PERSON_10 PERSON_11": "Ada Jale Kaan",
        "PERSON_1'in": "Ada'in",
        "PERSON_1.": "Ada.",
        "PERSON_1,PERSON_2": "Ada,Bora",
        "PERSON_12": "PERSON_12",  # not given out
        "EMAIL_12": "EMAIL_12",  # not given out; EMAIL_1 is never read inside it
    }
    for answer, expected in restored.items():
        assert vault.restore(answer) == expected, answer
    email_back = vault.restore("(EMAIL_1)") == f"({s.EMAIL})"
    assert email_back, "email was not restored inside brackets"


def test_letters_glued_to_a_placeholder():
    """The AI glues letters to a placeholder. Chosen rule (logged): only a digit on the right stops a placeholder,
    so a letter on either side does not; the value of another placeholder never comes back."""
    vault = Vault()
    vault.mask(" ".join(ELEVEN), ELEVEN)
    assert vault.restore("xPERSON_1y") == "xAday"
    assert vault.restore("PERSON_1abc") == "Adaabc"
    assert vault.restore("PERSON_1ın") == "Adaın"
    assert vault.restore("PERSON_10abc") == "Jaleabc"
    assert vault.restore("PERSON_100") == "PERSON_100"  # PERSON_10 is not read inside PERSON_100


def test_letters_glued_placeholder_in_input_is_a_literal():
    """The same pattern is used on inputs: "xPERSON_1y" written in an input reserves PERSON_1."""
    vault = Vault()
    result = vault.mask("xPERSON_1y Ada", ["Ada"])
    assert result.text == "xPERSON_1y PERSON_2"
    assert vault.restore(result.text) == "xPERSON_1y Ada"


def test_restore_is_single_pass():
    """A restored value that contains a placeholder text is not opened again."""
    vault = Vault()
    vault.mask("Ada Bora", ["Ada", "Bora"])  # PERSON_1, PERSON_2
    masked = vault.mask("PERSON_2@example.com", [])  # an e-mail whose local part looks like PERSON_2
    assert masked.text == "EMAIL_1"
    assert vault.restore("EMAIL_1") == "PERSON_2@example.com"


def test_invented_placeholder_stays():
    vault = Vault()
    vault.mask(f"Deniz {s.EMAIL}", PEOPLE)
    assert vault.restore("EMAIL_9 PERSON_99 CARD_1") == "EMAIL_9 PERSON_99 CARD_1"


def test_redacted_never_restored():
    vault = Vault()
    result = vault.mask("token [REDACTED], Deniz", PEOPLE)
    assert result.text == "token [REDACTED], PERSON_1"
    assert vault.restore(result.text + " [REDACTED]") == "token [REDACTED], Deniz [REDACTED]"


def test_literal_placeholder_in_same_input_is_skipped():
    vault = Vault()
    result = vault.mask(f"EMAIL_1 ve {s.EMAIL}", [])
    assert result.text == "EMAIL_1 ve EMAIL_2"
    restored = vault.restore(result.text)
    literal_kept = restored.startswith("EMAIL_1 ve ")
    real_back = restored.endswith(s.EMAIL)
    assert literal_kept, "the written EMAIL_1 changed"
    assert real_back, "email was not restored"


def test_literal_after_issued_is_never_restored():
    vault = Vault()
    vault.mask(f"iletişim {s.EMAIL}", [])  # EMAIL_1
    vault.mask("EMAIL_1 ne demek?", [])  # the user's own text
    restored = vault.restore("EMAIL_1 dedi")
    leaked = s.EMAIL in restored
    assert not leaked, "a written EMAIL_1 became a real email"
    assert restored == "EMAIL_1 dedi"


def test_tc_glued_to_label_restores():
    vault = Vault()
    result = vault.mask(f"TC{s.TCKN} kayıtlı", [])
    assert result.text == "TCTCKN_1 kayıtlı"
    back = vault.restore(result.text) == f"TC{s.TCKN} kayıtlı"
    assert back, "tckn was not restored"


@pytest.mark.parametrize("case", list(s.PERSONAL_SAMPLES))
def test_each_personal_kind_masked_and_restored(case):
    value, prefix = s.PERSONAL_SAMPLES[case]
    text = f"iletişim: {value}"
    vault = Vault()
    result = vault.mask(text, [])
    leaked = value in result.text
    assert not leaked, f"{case} left in the text"
    assert result.text == f"iletişim: {prefix}_1"
    back = vault.restore(result.text) == normalize(text)
    assert back, f"{case} was not restored"


def test_people_names_case_and_turkish():
    vault = Vault()
    result = vault.mask("ismail ışık geldi, İSMAİL IŞIK da", ["İsmail Işık"])
    assert result.text == "PERSON_1 geldi, PERSON_2 da"
    assert vault.restore(result.text) == "ismail ışık geldi, İSMAİL IŞIK da"


def test_text_without_findings_is_unchanged():
    vault = Vault()
    assert vault.mask("deploy yine düştü", PEOPLE) == FilterResult("deploy yine düştü", {}, False)
    assert vault.restore("deploy yine düştü") == "deploy yine düştü"


def test_repr_and_str_have_no_values():
    vault = Vault()
    vault.mask(f"Deniz {s.EMAIL} {s.PHONE_INTL}", PEOPLE)
    for text in (repr(vault), str(vault)):
        leaked = s.EMAIL in text or s.PHONE_INTL in text or "Deniz" in text
        assert not leaked, "a value is in the repr"
        assert "EMAIL_" not in text and "PERSON_" not in text
        assert text == "Vault(3 placeholders)"


def test_vault_does_not_log(caplog):
    """Correction 1: nothing is logged at any level, by the app ("agentstack") or by any other logger."""
    with caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, logger="agentstack"), \
            caplog.at_level(logging.DEBUG, logger="app"), caplog.at_level(logging.DEBUG, logger="app.filters"):
        vault = Vault()
        masked = vault.mask(f"Deniz {s.EMAIL} EMAIL_9", PEOPLE)
        vault.restore(masked.text)
    assert caplog.records == []
