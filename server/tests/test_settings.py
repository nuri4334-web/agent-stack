"""S2-10: an empty GEMINI_MODEL falls back to the default model.

The setting is read when the module loads, so the real setting is tested in a new process. That process does not
load .env and sets the variable itself, so the result never depends on the developer's .env. No test calls Gemini.
"""
import subprocess
import sys

import pytest

from app import settings


def _gemini_model_in_new_process(set_variable):
    done = subprocess.run(
        [sys.executable, "-B", "-c", "import os, dotenv; dotenv.load_dotenv = lambda *a, **k: False; "
                                     f"{set_variable}; "
                                     "from app import settings; print(repr(settings.GEMINI_MODEL))"],
        cwd=settings.ROOT / "server",
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0
    return done.stdout.strip()


@pytest.mark.parametrize("value", [None, "", " ", "\t\n"])
def test_text_or_default_gives_default(value):
    assert settings._text_or_default(value, "default") == "default"


def test_text_or_default_strips_a_value():
    assert settings._text_or_default(" gemini-x ", "default") == "gemini-x"


@pytest.mark.parametrize("value, expected", [
    ("", settings.DEFAULT_GEMINI_MODEL),
    ("   ", settings.DEFAULT_GEMINI_MODEL),
    ("gemini-test-model", "gemini-test-model"),
    (" gemini-test-model ", "gemini-test-model"),
])
def test_gemini_model_setting(value, expected):
    assert _gemini_model_in_new_process(f"os.environ['GEMINI_MODEL'] = {value!r}") == repr(expected)


def test_gemini_model_default_when_not_set():
    result = _gemini_model_in_new_process("os.environ.pop('GEMINI_MODEL', None)")
    assert result == repr(settings.DEFAULT_GEMINI_MODEL)


def test_env_example_has_the_default_model():
    lines = (settings.ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert [line for line in lines if line.startswith("GEMINI_MODEL=")] == [
        f"GEMINI_MODEL={settings.DEFAULT_GEMINI_MODEL}",
    ]
