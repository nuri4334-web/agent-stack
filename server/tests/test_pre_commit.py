"""Tests for S4-08: Pre-commit local check."""
import sys
from pathlib import Path

# Add .githooks to path so we can import pre_commit
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GITHOOKS_DIR = REPO_ROOT / ".githooks"
if str(GITHOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(GITHOOKS_DIR))

import pre_commit


def _make_sample_token() -> str:
    # Constructed dynamically so the test source file itself doesn't contain a raw token
    return "xoxb-" + "9" * 10 + "-" + "9" * 13 + "-abcdefghijklmnopqrstuvwx"


def _make_multiline_sample() -> str:
    # Constructed dynamically so the test source file doesn't trigger the filter
    prefix = "WEBHOOK_" + "SECRET"
    val = "raw_secret_" + "token_99999"
    return f"{prefix}=\n\"{val}\"\n"


def test_k1_cross_platform_hooks_exist():
    assert (GITHOOKS_DIR / "pre-commit").is_file()
    assert (GITHOOKS_DIR / "pre_commit.py").is_file()


def test_k2_real_secret_blocks_commit_and_never_leaks_value():
    real_secret = _make_sample_token()
    files = {
        "server/app/config.py": f"# Configuration\n# Some line\nSLACK_TOKEN = '{real_secret}'\n",
    }
    allowed, errors = pre_commit.decide_commit(["server/app/config.py"], lambda f: files[f])
    assert allowed is False
    assert len(errors) == 1
    err = errors[0]
    assert "server/app/config.py:3" in err
    assert "slack_token" in err
    # CRITICAL: secret value must never be in the error message
    assert real_secret not in err

    # Also test multiline secret detection
    multiline_files = {
        "server/app/env_config.py": _make_multiline_sample(),
    }
    allowed_ml, errors_ml = pre_commit.decide_commit(
        ["server/app/env_config.py"], lambda f: multiline_files[f]
    )
    assert allowed_ml is False
    assert len(errors_ml) == 1
    assert "server/app/env_config.py:1" in errors_ml[0]
    assert "env_secret" in errors_ml[0]


def test_k3_env_files_blocked_except_example():
    blocked_files = [".env", ".env.local", "server/.env", "web/.env.staging"]
    for path in blocked_files:
        assert pre_commit.is_blocked_env_file(path) is True
        allowed, errors = pre_commit.decide_commit([path], lambda f: "")
        assert allowed is False
        assert any(path in e for e in errors)

    allowed_files = [".env.example", "server/.env.example", "web/.env.example"]
    for path in allowed_files:
        assert pre_commit.is_blocked_env_file(path) is False
        allowed, errors = pre_commit.decide_commit([path], lambda f: "FOO=bar")
        assert allowed is True
        assert len(errors) == 0


def test_k4_demo_data_and_fake_values_do_not_block():
    real_secret = _make_sample_token()
    files = {
        # demo-data/ is ignored
        "demo-data/payloads.txt": f"pasted: {real_secret}\n",
        # EXAMPLE or zeros are ignored
        "server/tests/test_foo.py": (
            "SLACK = 'xoxb-0000000000-0000000000000-EXAMPLEexampleEXAMPLEexa'\n"
            "AWS = 'AKIA0000000000000000'\n"
            "TOKEN = 'ghp_EXAMPLE00000000000000000000000000000'\n"
        ),
    }
    allowed, errors = pre_commit.decide_commit(list(files.keys()), lambda f: files[f])
    assert allowed is True
    assert len(errors) == 0


def test_k5_selective_test_and_lint_triggers():
    assert pre_commit.needs_server_tests(["server/app/filters/secrets.py"]) is True
    assert pre_commit.needs_web_lint(["server/app/filters/secrets.py"]) is False

    assert pre_commit.needs_server_tests(["web/src/App.jsx"]) is False
    assert pre_commit.needs_web_lint(["web/src/App.jsx"]) is True

    assert pre_commit.needs_server_tests(["docs/api-contract.md"]) is False
    assert pre_commit.needs_web_lint(["docs/api-contract.md"]) is False

    both = ["server/app/main.py", "web/src/index.css"]
    assert pre_commit.needs_server_tests(both) is True
    assert pre_commit.needs_web_lint(both) is True


def test_k6_readme_documentation():
    readme = (REPO_ROOT / "server" / "README.md").read_text(encoding="utf-8")
    assert "git config core.hooksPath .githooks" in readme
    assert "PowerShell" in readme or "Windows" in readme
    assert "--no-verify" in readme


def test_k7_pure_logic_isolation():
    # Test completely operates on memory data without invoking git or network
    fake_fs = {
        "server/app/test.py": "x = 1\n",
        "README.md": "# Project\n",
    }
    allowed, errors = pre_commit.decide_commit(list(fake_fs.keys()), lambda f: fake_fs[f])
    assert allowed is True
    assert errors == []
