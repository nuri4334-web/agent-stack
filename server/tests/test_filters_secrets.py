"""S3-09: secret rules (S1-11 catalog S1-S14) and mask_secrets.

Every fake value comes from the S1-11 catalog (EXAMPLE or zeros). Assertions compare booleans, so a test failure
never prints a value.
"""
import time

import pytest

from app.filters.api import choose_spans, mask_secrets
from app.filters.secrets import REDACTED, find_secrets
from app.filters.types import Span

# --- Fake values of the S1-11 catalog --------------------------------------------------------------------------
SLACK_BOT = "xoxb-0000000000-0000000000000-EXAMPLEexampleEXAMPLEexa"
SLACK_USER = "xoxp-0000000000-0000000000-0000000000000-" + "EXAMPLE" + "0" * 25
SLACK_APP = "xapp-1-A0000000000-0000000000000-" + "0" * 57 + "example"
GITHUB_CLASSIC = "ghp_EXAMPLE" + "0" * 29
GITHUB_FINE = "github_pat_" + "EXAMPLE" + "0" * 75
AWS_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
GOOGLE = "AIzaSyEXAMPLE" + "0" * 26
OPENAI = "sk-proj-" + "EXAMPLE" + "0" * 67 + "T3BlbkFJ" + "0" * 67 + "EXAMPLE"
OPENAI_UNMARKED = "sk-proj-" + "EXAMPLE" + "0" * 40
ANTHROPIC = "sk-ant-api03-" + "EXAMPLE" + "0" * 86 + "AA"
PRIVATE_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAAEXAMPLEexampleEXAMPLEexampleEXAMPLEexample0000\n"
    "-----END OPENSSH PRIVATE KEY-----"
)
JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJvcm5layJ9.EXAMPLEexampleEXAMPLE000"
DB_SECRET = "Ornek-Sifre-2026"
ENV_SECRET = "ornek-jwt-gizli-anahtar-degistir"


def leaks(result_text: str, *values: str) -> bool:
    return any(v in result_text for v in values)


def same(a: str, b: str) -> bool:
    return a == b


# --- One caught and one not caught example per kind ----------------------------------------------------------
@pytest.mark.parametrize("kind, value", [
    ("slack_token", SLACK_BOT), ("slack_token", SLACK_USER), ("slack_token", SLACK_APP),
    ("github_token", GITHUB_CLASSIC), ("github_token", GITHUB_FINE),
    ("aws_key", AWS_ID), ("google_key", GOOGLE), ("openai_key", OPENAI), ("openai_key", OPENAI_UNMARKED),
    ("anthropic_key", ANTHROPIC), ("private_key", PRIVATE_KEY), ("bearer_token", JWT),
], ids=["slack-bot", "slack-user", "slack-app", "github-classic", "github-fine", "aws-id", "google", "openai",
        "openai-unmarked", "anthropic", "private-key", "jwt"])
def test_certain_secret_in_a_message_is_masked_with_alarm(kind, value):
    r = mask_secrets(f"şuna bak: {value} tamam mı?")
    assert not leaks(r.text, value)
    assert same(r.text, f"şuna bak: {REDACTED} tamam mı?")
    assert dict(r.counts) == {kind: 1}
    assert r.alarm is True


@pytest.mark.parametrize("text", [
    "xoxb- ile başlayan token bot token'ıdır",
    "ghp_short123 diye bir branch açtım",
    "AKIA ile başlayan anahtarlar AWS'ye ait: AKIA0000000000000",
    "AIza önekli Google anahtarları",
    "sk-proj-short anahtarı denedim",
    "sk-proj-" + "a" * 20 + " (kısa, işaretsiz)",
    "sk-" + "A1b2C3d4" * 6 + " işaretsiz ve öneksiz",
    "sk-ant-api03-short",
    "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAEXAMPLE\n-----END PUBLIC KEY-----",
    "-----BEGIN CERTIFICATE-----\nMIIDdzCCAl+gAwIBAgIEAgAAuTANBgkqhkiG9w0BAQUFADBaEXAMPLE\n-----END CERTIFICATE-----",
    "Bearer token nedir, kısaca anlatır mısın?",
    "postgres://db.staging.example:5432/shop adresine bağlan",
    "https://ali@git.example/repo.git",
])
def test_near_misses_are_not_masked(text):
    r = mask_secrets(text)
    assert same(r.text, text)
    assert (dict(r.counts), r.alarm) == ({}, False)


def test_aws_secret_needs_its_name():
    named = mask_secrets(f"aws_secret_access_key = {AWS_SECRET}")
    assert not leaks(named.text, AWS_SECRET)
    assert (dict(named.counts), named.alarm) == ({"aws_key": 1}, False)
    bare = mask_secrets(f"şu dizi: {AWS_SECRET}")
    assert same(bare.text, f"şu dizi: {AWS_SECRET}")


def test_authorization_bearer_header_masks_only_the_token():
    token = "EXAMPLEexampleEXAMPLE0000"
    r = mask_secrets(f"Authorization: Bearer {token}")
    assert same(r.text, f"Authorization: Bearer {REDACTED}")
    assert (dict(r.counts), r.alarm) == ({"bearer_token": 1}, True)


def test_database_address_masks_only_the_password():
    r = mask_secrets(f"DATABASE_URL=postgres://app_user:{DB_SECRET}@db.staging.example:5432/shop")
    assert same(r.text, f"DATABASE_URL=postgres://app_user:{REDACTED}@db.staging.example:5432/shop")
    assert (dict(r.counts), r.alarm) == ({"db_password": 1}, True)


@pytest.mark.parametrize("line, masked", [
    (f"JWT_SECRET={ENV_SECRET}", f"JWT_SECRET={REDACTED}"),
    (f"DB_PASSWORD={DB_SECRET}", f"DB_PASSWORD={REDACTED}"),
    (f"export API_TOKEN='{DB_SECRET}'", f"export API_TOKEN='{REDACTED}'"),
    ('SMTP_PASS="ornek sifre 2026"', f'SMTP_PASS="{REDACTED}"'),
])
def test_env_line_masks_only_the_value_and_alarms(line, masked):
    r = mask_secrets(line)
    assert same(r.text, masked)
    assert (dict(r.counts), r.alarm) == ({"env_secret": 1}, True)  # decision N5: a pasted .env secret alarms


@pytest.mark.parametrize("line", [
    "PASSWORD_MIN_LENGTH=8",
    "TOKEN_URL=https://auth.example/oauth/token",
    "SSH_KEY_PATH=~/.ssh/id_ed25519",
    "API_KEY=",
    "DEBUG_TOKEN=false",
    "SECRET_KEY=${SECRET_KEY}",
    "DB_PASSWORD=[REDACTED]",
    "api_key ne işe yarıyor?",
])
def test_env_settings_and_references_are_not_masked(line):
    r = mask_secrets(line)
    assert same(r.text, line)
    assert dict(r.counts) == {}


# --- The 12 innocent look-alikes of the catalog ----------------------------------------------------------------
INNOCENT = [
    "Hotfix main'e girdi: commit a663950014a53b5bd5db54211e2fbc919bf98ff3",
    "a663950'da düzelttim",
    "Testlerde bu kullanıcıyı kullanıyorum, ID'si: 3f2b8c1e-7a4d-4e9b-b1c2-9d8e7f6a5b4c",
    "release-1.4.2.zip SHA-256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "md5: d41d8cd98f00b204e9800998ecf8427e",
    "Yeni tasarım dosyası: https://tasarim.example/file/AbCdEf123456GhIjKl/Login-v3?node-id=12-345&t=Xy9Zk2Lm8Np4Qr7S",
    "U0CA5HH3M1V kişisini C07DEV1234 kanalına ekledim",
    "şu mesaj: 1792059120.000100",
    "sipariş no 20261020001 kargoya verildi",
    "rol: arn:aws:iam::123456789012:role/S3Access",
    "v1.4.2 sürümü 2026-10-20'de çıktı",
    "logo: data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk",
    "şunu dene: Xy9Zk2Lm8Np4Qr7SaB3cD5eF6gH",  # S15: weak, never touched
]


@pytest.mark.parametrize("text", INNOCENT, ids=[f"M{i}" for i in range(1, 13)] + ["S15"])
def test_innocent_look_alikes_are_never_masked(text):
    r = mask_secrets(text)
    assert same(r.text, text)
    assert (dict(r.counts), r.alarm) == ({}, False)


# --- Demo 2: the .env message pasted into #dev -----------------------------------------------------------------
def test_demo2_env_message_hides_every_value_and_keeps_the_names():
    message = (
        "Staging yine ayağa kalkmıyor, benim .env'im bu. Sizinkinden farkı ne?\n```\n"
        f"DATABASE_URL=postgres://app_user:{DB_SECRET}@db.staging.example:5432/shop\n"
        f"AWS_ACCESS_KEY_ID={AWS_ID}\n"
        f"AWS_SECRET_ACCESS_KEY={AWS_SECRET}\n"
        f"SLACK_BOT_TOKEN={SLACK_BOT}\n"
        f"GITHUB_TOKEN={GITHUB_CLASSIC}\n"
        f"GEMINI_API_KEY={GOOGLE}\n"
        f"JWT_SECRET={ENV_SECRET}\n```"
    )
    r = mask_secrets(message)
    assert not leaks(r.text, DB_SECRET, AWS_ID, AWS_SECRET, SLACK_BOT, GITHUB_CLASSIC, GOOGLE, ENV_SECRET)
    for name in ("DATABASE_URL=postgres://app_user:", "AWS_ACCESS_KEY_ID=", "AWS_SECRET_ACCESS_KEY=",
                 "SLACK_BOT_TOKEN=", "GITHUB_TOKEN=", "GEMINI_API_KEY=", "JWT_SECRET="):
        assert name in r.text
    assert dict(r.counts) == {
        "db_password": 1, "aws_key": 2, "slack_token": 1, "github_token": 1, "google_key": 1, "env_secret": 1,
    }
    assert (r.masked, r.alarm) == (7, True)


# --- Behaviour of mask_secrets ---------------------------------------------------------------------------------
def test_invisible_character_does_not_hide_a_token():
    hidden = SLACK_BOT[:2] + "\u200b" + SLACK_BOT[2:]
    r = mask_secrets(f"token: {hidden}")
    assert same(r.text, f"token: {REDACTED}")
    assert r.alarm is True


def test_masking_twice_counts_nothing_new():
    first = mask_secrets(f"SLACK_BOT_TOKEN={SLACK_BOT}\nDB_PASSWORD={DB_SECRET}")
    second = mask_secrets(first.text)
    assert same(second.text, first.text)
    assert (dict(second.counts), second.alarm) == ({}, False)


def test_only_suspicious_findings_give_no_alarm():
    r = mask_secrets(f"aws_secret_access_key: {AWS_SECRET}")
    assert (dict(r.counts), r.alarm) == ({"aws_key": 1}, False)


def test_certain_secret_inside_a_longer_env_value_still_gives_the_alarm():
    r = mask_secrets(f'API_KEY="eski anahtar {AWS_ID} idi"')
    assert not leaks(r.text, AWS_ID)
    assert (dict(r.counts), r.alarm) == ({"env_secret": 1}, True)


def test_specific_kind_beats_env_secret_on_the_same_value():
    r = mask_secrets(f"OPENAI_API_KEY={OPENAI}")
    assert (dict(r.counts), r.alarm) == ({"openai_key": 1}, True)


def test_find_secrets_spans_point_at_the_value_only():
    text = f"DB_PASSWORD={DB_SECRET}"
    spans = find_secrets(text)
    assert [(s.start, s.end, s.kind, s.confidence) for s in spans] == [
        (len("DB_PASSWORD="), len(text), "env_secret", "certain"),
    ]


# Crafted long messages: no rule may backtrack catastrophically (a slow rule would stall the Slack sync).
CRAFTED = {
    "env-name": "A_KEY_" * 20000,
    "env-no-value": "PASSWORD:" * 20000,
    "slack": "xoxb-" + "1-" * 30000,
    "xapp": "xapp-1-" + "A" * 50000,
    "openai": "sk-" * 30000 + "A" * 1000,
    "anthropic": "sk-ant-api03-" * 5000,
    "db-address": "a." * 50000 + "://",
    "db-user": "x://" + "u" * 100000,
    "private-key": "-----BEGIN " * 10000,
    "jwt": "eyJ" + "a" * 50000 + ".eyJ",
    "bearer": "Bearer " * 20000,
    "plain": "x" * 200000,
}


@pytest.mark.parametrize("text", CRAFTED.values(), ids=CRAFTED.keys())
def test_crafted_long_text_is_fast(text):
    start = time.perf_counter()
    mask_secrets(text)
    assert time.perf_counter() - start < 1


# --- Overlap rule (shared with the Vault) ----------------------------------------------------------------------
def test_longer_span_wins():
    assert choose_spans([Span(0, 10, "env_secret", "suspicious"), Span(2, 6, "aws_key", "certain")]) == [
        Span(0, 10, "env_secret", "suspicious"),
    ]


def test_equal_length_secret_beats_personal_beats_name():
    spans = [Span(0, 5, "person", "certain"), Span(0, 5, "email", "certain"), Span(0, 5, "slack_token", "certain")]
    assert choose_spans(spans) == [Span(0, 5, "slack_token", "certain")]
    assert choose_spans(spans[:2]) == [Span(0, 5, "email", "certain")]


def test_equal_length_specific_then_certain_win_among_secrets():
    assert choose_spans([Span(0, 5, "env_secret", "suspicious"), Span(0, 5, "aws_key", "suspicious")]) == [
        Span(0, 5, "aws_key", "suspicious"),
    ]
    assert choose_spans([Span(0, 5, "aws_key", "suspicious"), Span(0, 5, "google_key", "certain")]) == [
        Span(0, 5, "google_key", "certain"),
    ]
    # The most specific kind wins even over a certain env_secret: AWS_SECRET_ACCESS_KEY=... counts as aws_key.
    assert choose_spans([Span(0, 5, "env_secret", "certain"), Span(0, 5, "aws_key", "suspicious")]) == [
        Span(0, 5, "aws_key", "suspicious"),
    ]


def test_non_overlapping_spans_all_stay_in_order():
    spans = [Span(10, 12, "email", "certain"), Span(0, 3, "slack_token", "certain"), Span(3, 5, "person", "certain")]
    assert choose_spans(spans) == sorted(spans, key=lambda s: s.start)
