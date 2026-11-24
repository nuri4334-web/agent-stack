"""Pre-commit check (S4-08): local validation before commit.

Verifies:
1. No unencrypted secrets in staged files (using app.filters.api.mask_secrets).
2. No .env files staged (except .env.example).
3. If server/ changed, runs pytest -q.
4. If web/ changed, runs npm run lint.
"""
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path, PurePath

# Ensure server package can be imported
REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

try:
    from app.filters.api import mask_secrets
except ImportError:
    mask_secrets = None

_ZERO_REPEAT = re.compile(r"0{8,}")


def is_blocked_env_file(path: str) -> bool:
    """Returns True if path is a forbidden .env file (.env or .env.* except .env.example)."""
    name = PurePath(path).name
    if name == ".env.example":
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    return False


def is_ignored_path(path: str) -> bool:
    """demo-data/ files are ignored by the hook."""
    norm = path.replace("\\", "/")
    return norm.startswith("demo-data/") or norm == "demo-data"


def is_fake_value(text: str) -> bool:
    """Returns True if text contains EXAMPLE/example or is filled with zeros (fake test values)."""
    if "EXAMPLE" in text or "example" in text:
        return True
    if _ZERO_REPEAT.search(text):
        return True
    return False


def check_content(path: str, content: str) -> list[tuple[str, int, str]]:
    """Scans content using mask_secrets.
    Returns a list of (path, line_number, kind).
    NEVER returns or logs the secret value itself.
    """
    if mask_secrets is None or is_ignored_path(path):
        return []

    findings: list[tuple[str, int, str]] = []
    lines = content.splitlines()

    # 1. Single line scan
    for lineno, line in enumerate(lines, start=1):
        if is_fake_value(line):
            continue
        res = mask_secrets(line)
        if res.alarm:
            for kind in res.counts:
                findings.append((path, lineno, kind))

    # 2. Multiline window scan across consecutive lines
    alarm_lines = {f[1] for f in findings}
    for idx in range(len(lines) - 1):
        # If either line was already alarmed, skip
        if (idx + 1) in alarm_lines or (idx + 2) in alarm_lines:
            continue
        pair = f"{lines[idx]}\n{lines[idx+1]}"
        if is_fake_value(pair):
            continue
        res = mask_secrets(pair)
        if res.alarm:
            for kind in res.counts:
                findings.append((path, idx + 1, kind))

    return findings


def decide_commit(
    staged_files: list[str],
    file_reader: Callable[[str], str],
) -> tuple[bool, list[str]]:
    """Pure decision function: (staged_files, file_reader) -> (allowed, errors)."""
    errors: list[str] = []

    for file_path in staged_files:
        if is_blocked_env_file(file_path):
            errors.append(f"Blocked environment file: {file_path}")

    for file_path in staged_files:
        if is_blocked_env_file(file_path) or is_ignored_path(file_path):
            continue
        try:
            content = file_reader(file_path)
        except Exception:
            continue
        findings = check_content(file_path, content)
        for path, lineno, kind in findings:
            errors.append(f"Secret detected in {path}:{lineno} ({kind})")

    return (len(errors) == 0, errors)


def needs_server_tests(staged_files: list[str]) -> bool:
    """Returns True if any staged file is in server/."""
    for f in staged_files:
        norm = f.replace("\\", "/")
        if norm.startswith("server/"):
            return True
    return False


def needs_web_lint(staged_files: list[str]) -> bool:
    """Returns True if any staged file is in web/."""
    for f in staged_files:
        norm = f.replace("\\", "/")
        if norm.startswith("web/"):
            return True
    return False


def get_staged_files() -> list[str]:
    """Retrieves list of staged files using git."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            text=True,
            cwd=str(REPO_ROOT),
        )
        return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def read_staged_file(file_path: str) -> str:
    """Reads staged file content from git."""
    try:
        out = subprocess.check_output(
            ["git", "show", f":{file_path}"],
            cwd=str(REPO_ROOT),
        )
        return out.decode("utf-8", errors="ignore")
    except Exception:
        full_path = REPO_ROOT / file_path
        if full_path.is_file():
            return full_path.read_text(encoding="utf-8", errors="ignore")
        return ""


def find_python_executable() -> str:
    """Finds best python interpreter (venv preferred)."""
    venv_python_unix = REPO_ROOT / "server" / ".venv" / "bin" / "python"
    if venv_python_unix.exists():
        return str(venv_python_unix)
    venv_python_win = REPO_ROOT / "server" / ".venv" / "Scripts" / "python.exe"
    if venv_python_win.exists():
        return str(venv_python_win)
    return sys.executable


def run_server_tests() -> int:
    """Runs server tests with pytest -q."""
    py = find_python_executable()
    print("[pre-commit] Running server tests (pytest -q)...")
    res = subprocess.run(
        [py, "-m", "pytest", "-q"],
        cwd=str(REPO_ROOT / "server"),
    )
    return res.returncode


def run_web_lint() -> int:
    """Runs web lint with npm run lint."""
    print("[pre-commit] Running web lint (npm run lint)...")
    env = dict(os.environ)
    # Ensure homebrew or system node/npm paths are in PATH
    extra_paths = ["/opt/homebrew/bin", "/usr/local/bin"]
    env["PATH"] = ":".join(extra_paths) + ":" + env.get("PATH", "")
    res = subprocess.run(
        ["npm", "run", "lint"],
        cwd=str(REPO_ROOT / "web"),
        env=env,
        shell=False,
    )
    return res.returncode


def main() -> int:
    staged = get_staged_files()
    if not staged:
        return 0

    allowed, errors = decide_commit(staged, read_staged_file)
    if not allowed:
        print("\n[pre-commit] Commit blocked by security check:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        print("\nNever commit secret keys or forbidden .env files.", file=sys.stderr)
        print("To bypass in emergency: git commit --no-verify (document reason in PR).\n", file=sys.stderr)
        return 1

    if needs_server_tests(staged):
        code = run_server_tests()
        if code != 0:
            print("[pre-commit] Server tests failed. Commit aborted.", file=sys.stderr)
            return code

    if needs_web_lint(staged):
        code = run_web_lint()
        if code != 0:
            print("[pre-commit] Web lint failed. Commit aborted.", file=sys.stderr)
            return code

    return 0


if __name__ == "__main__":
    sys.exit(main())
