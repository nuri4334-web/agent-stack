"""S2-02: password, user name and session token rules (pure functions)."""
import hashlib
import re
from datetime import datetime, timedelta, timezone

import pytest

from app.accounts import rules
from app.accounts.rules import (
    hash_password, hash_session_token, is_slack_user_id, name_problem, new_session_token,
    normalize_username, password_problem, session_expires_at, username_problem, verify_password,
)
from tests.auth_clients import FIXTURE_ACCOUNTS, TEST_PASSWORD

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def stored():
    return hash_password(TEST_PASSWORD)


@pytest.fixture
def scrypt_calls(monkeypatch):
    """Records every hashlib.scrypt call; the real function still runs."""
    calls = []
    real = hashlib.scrypt

    def spy(password, **kwargs):
        calls.append(kwargs)
        return real(password, **kwargs)

    monkeypatch.setattr(hashlib, "scrypt", spy)
    return calls


def test_correct_password_verifies(stored):
    assert verify_password(stored, TEST_PASSWORD) is True


def test_wrong_password_rejected(stored):
    for wrong in ["TEST-password-2025", TEST_PASSWORD.upper(), TEST_PASSWORD + " ", TEST_PASSWORD[:-1]]:
        assert verify_password(stored, wrong) is False


@pytest.mark.parametrize("empty", [None, ""])
def test_empty_hash_never_verifies(empty):
    for password in [TEST_PASSWORD, "", "x" * 12]:
        assert verify_password(empty, password) is False


def test_empty_hash_still_runs_scrypt(scrypt_calls):
    assert verify_password(None, TEST_PASSWORD) is False
    assert len(scrypt_calls) == 1
    call = scrypt_calls[0]
    assert (call["n"], call["r"], call["p"], call["dklen"]) == (2**14, 8, 5, 32)


MALFORMED = [
    "plain",
    "scrypt$",
    "scrypt$16384$8$5$00",
    "scrypt$16384$8$5$" + "00" * 16 + "$" + "00" * 32 + "$extra",
    "scrypt$16384$8$5$" + "zz" * 16 + "$" + "00" * 32,
    "scrypt$16000$8$5$" + "00" * 16 + "$" + "00" * 32,
    "scrypt$1073741824$8$5$" + "00" * 16 + "$" + "00" * 32,
    "scrypt$16384$0$5$" + "00" * 16 + "$" + "00" * 32,
    "scrypt$16384$8$5$" + "00" * 4 + "$" + "00" * 32,
    "scrypt$-16384$8$5$" + "00" * 16 + "$" + "00" * 32,
    "md5$16384$8$5$" + "00" * 16 + "$" + "00" * 32,
    TEST_PASSWORD,
]


@pytest.mark.parametrize("bad", MALFORMED)
def test_malformed_hash_returns_false_and_still_runs_scrypt(monkeypatch, bad):
    calls = []

    def fast_scrypt(password, **kwargs):
        calls.append(kwargs)
        return bytes(kwargs["dklen"])

    monkeypatch.setattr(hashlib, "scrypt", fast_scrypt)
    assert verify_password(bad, TEST_PASSWORD) is False
    assert len(calls) == 1
    assert (calls[0]["n"], calls[0]["r"], calls[0]["p"]) == (2**14, 8, 5)


@pytest.mark.parametrize("length, ok", [(11, False), (12, True), (128, True), (129, False)])
def test_password_length_rule(length, ok):
    password = "p" * length
    assert (password_problem(password) is None) is ok
    if not ok:
        with pytest.raises(ValueError):
            hash_password(password)


def test_twelve_characters_can_be_hashed():
    stored = hash_password("TEST-12chars")
    assert verify_password(stored, "TEST-12chars")


def test_rule_error_text_has_no_password():
    for password in ["TEST-short", "TEST-" + "x" * 130]:
        problem = password_problem(password)
        assert problem and password not in problem
        with pytest.raises(ValueError) as error:
            hash_password(password)
        assert password not in str(error.value)


def test_same_password_two_hashes_differ(stored):
    other = hash_password(TEST_PASSWORD)
    assert other != stored
    assert other.split("$")[4] != stored.split("$")[4]
    assert verify_password(other, TEST_PASSWORD)


def test_hash_format_and_parameters(stored):
    assert re.fullmatch(r"scrypt\$16384\$8\$5\$[0-9a-f]{32}\$[0-9a-f]{64}", stored)
    assert TEST_PASSWORD not in stored
    assert TEST_PASSWORD.encode().hex() not in stored


def test_verify_never_applies_length_rule(stored):
    for password in ["x" * 11, "", "x" * 500]:
        assert verify_password(stored, password) is False


def test_password_nfc_normalized():
    composed = "TEST-şifre-2026"
    decomposed = "TEST-şifre-2026"
    assert composed != decomposed
    assert verify_password(hash_password(composed), decomposed)


def test_session_token_random_and_urlsafe():
    first, second = new_session_token(), new_session_token()
    assert first != second
    for token in (first, second):
        assert len(token) >= 43
        assert re.fullmatch(r"[A-Za-z0-9_-]+", token)


def test_session_token_hash_is_64_hex():
    token = new_session_token()
    digest = hash_session_token(token)
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert digest == hash_session_token(token)
    assert digest != hash_session_token(new_session_token())
    assert token not in digest


def test_session_expires_after_8_hours():
    assert session_expires_at(NOW) == NOW + timedelta(hours=8)
    with pytest.raises(ValueError):
        session_expires_at(datetime(2026, 10, 30, 9, 0))


def test_username_normalization():
    assert normalize_username(" Ali ") == "ali"
    assert normalize_username("ADMIN_linked") == "admin_linked"


@pytest.mark.parametrize("name", sorted(FIXTURE_ACCOUNTS) + ["a.b", "x-1", "a" * 32, "0ali"])
def test_valid_usernames(name):
    assert username_problem(name) is None


@pytest.mark.parametrize("name", ["ab", "a" * 33, "_ali", ".ali", "ali kaya", "ali@x", "Ali", "", "ayşe",
                                  normalize_username("alİ")])
def test_invalid_usernames(name):
    assert username_problem(name)


def test_name_rule():
    assert name_problem("Ali Kaya") is None
    assert name_problem("Ayşe Demir") is None
    for bad in ["", "x" * 101, "Ali\nKaya"]:
        assert name_problem(bad)


def test_slack_user_id_format():
    for good in ["U0CA5HH3M1V", "W0CA5HH3M1V"]:
        assert is_slack_user_id(good)
    for bad in ["u0ca5hh3m1v", "C0C8ATRM073", "U_ALI", "", " U0CA5HH3M1V", "U", None]:
        assert not is_slack_user_id(bad)


def test_rules_constants_match_contract():
    assert (rules.PASSWORD_MIN_LENGTH, rules.PASSWORD_MAX_LENGTH) == (12, 128)
    assert rules.SESSION_LIFETIME == timedelta(hours=8)
