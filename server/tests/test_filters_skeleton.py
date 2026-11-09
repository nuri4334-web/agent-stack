"""S3-01: the filter skeleton has the shared signatures and its empty bodies change nothing."""
import ast
import dataclasses
import re
from pathlib import Path

import pytest

from app.filters import api, injection, names, output, personal, secrets
from app.filters.types import KINDS, NAME_KIND, PERSONAL_KINDS, SECRET_KINDS, FilterResult, Span

FILTERS_DIR = Path(api.__file__).parent
TEXT = "Deniz: deploy failed, ali@example.com"


def test_kinds_are_the_shared_list():
    assert SECRET_KINDS == (
        "slack_token", "github_token", "aws_key", "google_key", "openai_key", "anthropic_key",
        "private_key", "env_secret", "db_password", "bearer_token",
    )
    assert PERSONAL_KINDS == ("email", "phone", "tckn", "iban", "card")
    assert NAME_KIND == "person"
    assert len(KINDS) == len(set(KINDS)) == 16


def test_span_has_no_value_field():
    assert [f.name for f in dataclasses.fields(Span)] == ["start", "end", "kind", "confidence"]


@pytest.mark.parametrize("start, end, kind, confidence", [
    (3, 3, "email", "certain"),
    (-1, 2, "email", "certain"),
    (0, 2, "password", "certain"),
    (0, 2, "email", "weak"),
])
def test_span_rejects_invalid_values(start, end, kind, confidence):
    with pytest.raises(ValueError):
        Span(start, end, kind, confidence)


def test_filter_result_masked_is_the_sum_of_counts():
    assert FilterResult("x", {"slack_token": 2, "email": 1}).masked == 3
    empty = FilterResult("x")
    assert (empty.counts, empty.alarm, empty.masked) == ({}, False, 0)


def test_rule_skeletons_find_nothing():
    assert secrets.find_secrets(TEXT) == []
    assert personal.find_personal(TEXT) == []
    assert names.find_names(TEXT, ["Deniz Aydın"]) == []


def test_mask_secrets_skeleton_returns_the_text_unchanged():
    assert api.mask_secrets(TEXT) == FilterResult(TEXT, {}, False)


def test_vault_skeleton_masks_and_restores_nothing():
    vault = api.Vault()
    assert vault.mask(TEXT, ["Deniz Aydın"]) == FilterResult(TEXT, {}, False)
    assert vault.restore(TEXT) == TEXT


def test_detect_skeleton_is_not_suspicious():
    assert injection.detect(TEXT) == injection.InjectionResult(suspicious=False, score=0.0)


def test_clean_answer_skeleton_returns_the_text_unchanged():
    assert output.clean_answer(TEXT) == output.OutputResult(TEXT, 0, 0, {})


# Rule files must be pure: no database, network, clock or settings.
_FORBIDDEN = ("sqlite3", "socket", "http", "urllib", "requests", "httpx", "app.settings", "app.database", "time")


def _imported_modules(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level + (node.module or "")
            modules.add(prefix)
            modules.update(f"{prefix}.{alias.name}" for alias in node.names if node.level)
    return modules


@pytest.mark.parametrize("path", sorted(FILTERS_DIR.glob("*.py")), ids=lambda p: p.name)
def test_filter_files_use_no_database_network_or_settings(path):
    for module in _imported_modules(path):
        name = module.lstrip(".")
        for forbidden in _FORBIDDEN:
            assert not (name == forbidden or name.startswith(forbidden + ".")), f"{path.name} imports {module}"
        assert not module.startswith(".."), f"{path.name} imports outside the filters package: {module}"


def test_filter_package_does_not_shadow_the_standard_library():
    import secrets as std_secrets
    import types as std_types

    assert hasattr(std_secrets, "token_bytes")
    assert hasattr(std_types, "SimpleNamespace")


# Invisible characters are written as escapes (\\u200b), never raw: a raw direction mark is flagged by GitHub as
# hidden bidirectional Unicode, and an editor that silently removes it would break normalize.
_RAW_INVISIBLE = re.compile("[\\u200b-\\u200f\\u202a-\\u202e\\u2060-\\u2064\\ufeff]")
_SOURCES = sorted(FILTERS_DIR.glob("*.py")) + sorted((FILTERS_DIR.parents[1] / "tests").glob("test_filters_*.py"))


@pytest.mark.parametrize("path", _SOURCES, ids=lambda p: p.name)
def test_no_raw_invisible_characters_in_filter_sources(path):
    lines = [i for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
             if _RAW_INVISIBLE.search(line)]
    assert lines == [], f"{path.name}: raw invisible characters on lines {lines}; write them as \\uXXXX escapes"
