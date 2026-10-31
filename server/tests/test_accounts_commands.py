"""S2-02: account commands (python -m app.accounts) and account storage, on the temporary seeded database."""
from datetime import datetime, timezone

import pytest

from app import settings
from app.accounts import commands, store
from app.accounts.commands import run_command
from app.accounts.rules import hash_session_token, new_session_token, verify_password
from app.database.schema import connect
from tests.auth_clients import TEST_PASSWORD

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
ALI_SLACK = "U0CA5HH3M1V"
AYSE_SLACK = "U0CAQKKLXTN"
BOT_SLACK = "U0C9UDSFKUP"
NEW_PASSWORD = "TEST-new-password-2026"
SHORT_PASSWORD = "TEST-short1"  # 11 characters


class Run:
    def __init__(self, code, output, prompts):
        self.code, self.output, self.prompts = code, output, prompts

    @property
    def text(self):
        return "\n".join(self.output)


def _run(*argv, passwords=()):
    output, prompts = [], []
    answers = iter(passwords)

    def read_password(prompt):
        prompts.append(prompt)
        answer = next(answers)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    code = run_command(
        list(argv), database_path=settings.DATABASE_PATH, now=lambda: NOW,
        write=output.append, read_password=read_password,
    )
    return Run(code, output, prompts)


def _query(sql, params=()):
    connection = connect(settings.DATABASE_PATH)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _create(username="ali", name="Ali Kaya", *extra, password=TEST_PASSWORD):
    return _run("create", "--username", username, "--name", name, *extra, passwords=[password, password])


def _person(username):
    rows = _query(
        "SELECT id, display_name, role, is_active, password_hash, created_at FROM people WHERE username = ?",
        (username,),
    )
    return rows[0] if rows else None


def _add_sessions(person_id, count):
    connection = connect(settings.DATABASE_PATH)
    try:
        with connection:
            for _ in range(count):
                connection.execute(
                    "INSERT INTO sessions (person_id, token_hash, created_at, expires_at, last_seen_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (person_id, hash_session_token(new_session_token()), NOW.isoformat(), NOW.isoformat(),
                     NOW.isoformat()),
                )
    finally:
        connection.close()


def _session_count(person_id):
    return _query("SELECT count(*) FROM sessions WHERE person_id = ?", (person_id,))[0][0]


def test_create_asks_password_twice_and_stores_hash():
    r = _create()
    assert r.code == 0
    assert r.prompts == ["Password: ", "Password again: "]
    assert r.output == ["Account created: ali (Ali Kaya, role user). No Slack account is linked yet."]
    _, name, role, is_active, password_hash, created_at = _person("ali")
    assert (name, role, is_active, created_at) == ("Ali Kaya", "user", 1, NOW.isoformat())
    assert password_hash != TEST_PASSWORD and TEST_PASSWORD not in password_hash
    assert verify_password(password_hash, TEST_PASSWORD)


def test_create_admin_role():
    assert _create("admin", "Admin", "--role", "admin").code == 0
    assert _person("admin")[2] == "admin"
    assert _run("create", "--username", "x1x", "--name", "X", "--role", "superadmin").code == 2
    assert _person("x1x") is None


def test_create_normalizes_username_and_rejects_duplicate():
    assert _create(" Ali ").code == 0
    assert _person("ali") is not None
    r = _run("create", "--username", "ALI", "--name", "Ali 2")
    assert r.code == 2
    assert r.prompts == []  # rejected before asking for a password
    assert "already exists" in r.text
    assert _query("SELECT count(*) FROM people")[0][0] == 1


def test_create_rejects_invalid_username_and_name():
    for username, name in [("a", "Ali"), ("ali kaya", "Ali"), ("ali", "   "), ("ali", "x" * 101)]:
        r = _run("create", "--username", username, "--name", name)
        assert r.code == 2 and r.prompts == []
    assert _query("SELECT count(*) FROM people")[0][0] == 0


def test_short_password_asked_again():
    r = _run("create", "--username", "ali", "--name", "Ali", passwords=[SHORT_PASSWORD, TEST_PASSWORD, TEST_PASSWORD])
    assert r.code == 0
    assert r.prompts == ["Password: ", "Password: ", "Password again: "]
    assert "Password must be at least 12 characters." in r.output
    assert verify_password(_person("ali")[4], TEST_PASSWORD)


def test_three_failed_attempts_exit_2_nothing_written():
    passwords = [TEST_PASSWORD, NEW_PASSWORD, SHORT_PASSWORD, "TEST-" + "x" * 130, TEST_PASSWORD, "other"]
    r = _run("create", "--username", "ali", "--name", "Ali", passwords=passwords)
    assert r.code == 2
    assert len(r.prompts) == 6 - 2  # two rule failures need only one prompt each
    assert "No valid password after 3 attempts. No change was made." in r.text
    assert _person("ali") is None


def test_three_mismatches_exit_2():
    r = _run("create", "--username", "ali", "--name", "Ali", passwords=[TEST_PASSWORD, "x"] * 3)
    assert r.code == 2
    assert r.output.count("The two passwords do not match.") == 3
    assert _person("ali") is None


def test_password_is_not_a_command_line_argument(capsys):
    r = _run("create", "--username", "ali", "--name", "Ali", "--password", TEST_PASSWORD)
    assert r.code == 2
    assert r.prompts == []
    assert _person("ali") is None
    captured = capsys.readouterr()
    for text in (r.text, captured.out, captured.err):
        assert TEST_PASSWORD not in text
    assert "never given on the command line" in r.text
    options = [
        option for action in commands._parser()._subparsers._group_actions[0].choices.values()
        for argument in action._actions for option in argument.option_strings
    ]
    assert options and not [o for o in options if "pass" in o.lower()]


def test_outputs_never_contain_password_hash_or_token():
    outputs = list(_create().output)
    ali_id = _person("ali")[0]
    token = new_session_token()
    connection = connect(settings.DATABASE_PATH)
    try:
        with connection:
            connection.execute(
                "INSERT INTO sessions (person_id, token_hash, created_at, expires_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?)", (ali_id, hash_session_token(token), "t", "t", "t"),
            )
    finally:
        connection.close()
    stored_before = _person("ali")[4]
    runs = [
        _run("create", "--username", "ayse", "--name", "Ayşe", passwords=[SHORT_PASSWORD, "TEST-abc-123456", "x"] * 2),
        _run("set-password", "--username", "ali", passwords=[NEW_PASSWORD, NEW_PASSWORD]),
        _run("link-slack", "--username", "ali", "--slack-id", ALI_SLACK),
        _run("list"),
        _run("deactivate", "--username", "ali"),
        _run("set-password", "--username", "ali", passwords=[KeyboardInterrupt()]),
    ]
    for r in runs:
        outputs.extend(r.output)
    stored_after = _person("ali")[4]
    text = "\n".join(outputs)
    for secret in [TEST_PASSWORD, NEW_PASSWORD, SHORT_PASSWORD, "TEST-abc-123456", stored_before, stored_after,
                   stored_after.split("$")[5], token, hash_session_token(token)]:
        assert secret not in text


def test_link_slack_admin_method():
    _create()
    r = _run("link-slack", "--username", "ali", "--slack-id", ALI_SLACK)
    assert r.code == 0
    assert r.output == [f"Slack account {ALI_SLACK} linked to ali."]
    assert _query(
        "SELECT p.username, a.source, a.link_method, a.linked_at FROM linked_accounts a "
        "JOIN people p ON p.id = a.person_id WHERE a.source_account_id = ?", (ALI_SLACK,),
    ) == [("ali", "slack", "admin", NOW.isoformat())]


def test_same_slack_account_cannot_link_to_two_people():
    _create()
    _create("deniz", "Deniz Aydın")
    assert _run("link-slack", "--username", "ali", "--slack-id", ALI_SLACK).code == 0
    r = _run("link-slack", "--username", "deniz", "--slack-id", ALI_SLACK)
    assert r.code == 2
    assert r.output == ["ERROR: This Slack account is already linked to another account (ali)."]
    assert _query("SELECT count(*) FROM linked_accounts WHERE source_account_id = ?", (ALI_SLACK,)) == [(1,)]


def test_same_slack_account_blocked_even_without_command_checks():
    # The table itself stops it too (e.g. two commands at the same time).
    connection = connect(settings.DATABASE_PATH)
    try:
        ali = store.create_account(connection, username="ali", name="Ali", role="user",
                                   password_hash=None, created_at=NOW.isoformat())
        deniz = store.create_account(connection, username="deniz", name="Deniz", role="user",
                                     password_hash=None, created_at=NOW.isoformat())
        store.link_slack_account(connection, ali, ALI_SLACK, linked_at=NOW.isoformat())
        with pytest.raises(store.AccountError, match=r"already linked to another account \(ali\)"):
            store.link_slack_account(connection, deniz, ALI_SLACK, linked_at=NOW.isoformat())
    finally:
        connection.close()


@pytest.mark.parametrize("slack_id, message", [
    ("u0ca5hh3m1v", "must look like"),
    ("C0C8ATRM073", "must look like"),
    ("U0000000000", "not in the database"),
    (BOT_SLACK, "is a bot"),
])
def test_link_slack_rejects_bad_unknown_or_bot_id(slack_id, message):
    _create()
    r = _run("link-slack", "--username", "ali", "--slack-id", slack_id)
    assert r.code == 2
    assert message in r.text
    assert _query("SELECT count(*) FROM linked_accounts") == [(0,)]


def test_link_slack_person_already_linked():
    _create()
    assert _run("link-slack", "--username", "ali", "--slack-id", ALI_SLACK).code == 0
    r = _run("link-slack", "--username", "ali", "--slack-id", AYSE_SLACK)
    assert r.code == 2
    assert "already has a linked Slack account" in r.text


def test_deactivate_keeps_person_and_deletes_only_its_sessions():
    _create()
    _create("ayse", "Ayşe Demir")
    ali, ayse = _person("ali")[0], _person("ayse")[0]
    _add_sessions(ali, 2)
    _add_sessions(ayse, 1)
    r = _run("deactivate", "--username", "ali")
    assert r.code == 0
    assert r.output == ["ali deactivated; 2 sessions ended."]
    assert _person("ali")[3] == 0
    assert (_session_count(ali), _session_count(ayse)) == (0, 1)
    assert _query("SELECT count(*) FROM people") == [(2,)]
    again = _run("deactivate", "--username", "ali")
    assert again.code == 0 and again.output == ["ali is already inactive."]


def test_activate():
    _create()
    assert _run("activate", "--username", "ali").output == ["ali is already active."]
    _run("deactivate", "--username", "ali")
    r = _run("activate", "--username", "ali")
    assert r.code == 0
    assert r.output == ["ali activated."]
    assert _person("ali")[3] == 1
    assert _session_count(_person("ali")[0]) == 0


def test_set_password_replaces_hash_and_deletes_sessions():
    _create()
    ali = _person("ali")[0]
    _add_sessions(ali, 3)
    r = _run("set-password", "--username", "ali", passwords=[NEW_PASSWORD, NEW_PASSWORD])
    assert r.code == 0
    assert r.output == ["Password changed for ali; 3 sessions ended."]
    stored = _person("ali")[4]
    assert not verify_password(stored, TEST_PASSWORD)
    assert verify_password(stored, NEW_PASSWORD)
    assert _session_count(ali) == 0


def test_failed_set_password_changes_nothing():
    _create()
    ali, stored = _person("ali")[0], _person("ali")[4]
    _add_sessions(ali, 1)
    r = _run("set-password", "--username", "ali", passwords=[SHORT_PASSWORD] * 3)
    assert r.code == 2
    assert _person("ali")[4] == stored
    assert _session_count(ali) == 1


@pytest.mark.parametrize("argv", [
    ["set-password", "--username", "nobody"],
    ["link-slack", "--username", "nobody", "--slack-id", ALI_SLACK],
    ["deactivate", "--username", "nobody"],
    ["activate", "--username", "nobody"],
])
def test_unknown_username_exit_2(argv):
    r = _run(*argv)
    assert r.code == 2
    assert r.output == ["ERROR: No account with the user name 'nobody'."]
    assert r.prompts == []


def test_list_shows_accounts_without_hash():
    assert _run("list").output == ["No accounts yet; create one with 'python -m app.accounts create'."]
    _create()
    _create("admin", "Admin", "--role", "admin")
    _run("link-slack", "--username", "ali", "--slack-id", ALI_SLACK)
    _run("deactivate", "--username", "admin")
    r = _run("list")
    assert r.code == 0
    assert [line.split() for line in r.output] == [
        ["username", "name", "role", "active", "password", "slack"],
        ["admin", "Admin", "admin", "no", "set", "-"],
        ["ali", "Ali", "Kaya", "user", "yes", "set", ALI_SLACK],
    ]
    assert "scrypt" not in r.text


def test_account_without_password_cannot_log_in():
    connection = connect(settings.DATABASE_PATH)
    try:
        store.create_account(connection, username="nopass", name="No Password", role="user",
                             password_hash=None, created_at=NOW.isoformat())
    finally:
        connection.close()
    stored = _person("nopass")[4]
    assert stored is None
    for password in [TEST_PASSWORD, "", "x" * 12]:
        assert verify_password(stored, password) is False
    assert "not set" in _run("list").text


def test_role_default_user_in_store():
    connection = connect(settings.DATABASE_PATH)
    try:
        connection.execute("INSERT INTO people (username, display_name, created_at) VALUES ('deniz', 'Deniz', 't')")
        assert connection.execute("SELECT role FROM people WHERE username = 'deniz'").fetchone() == ("user",)
    finally:
        connection.close()


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), EOFError()])
def test_cancel_at_password_prompt(interrupt):
    r = _run("create", "--username", "ali", "--name", "Ali", passwords=[interrupt])
    assert r.code == 2
    assert r.output == ["Cancelled. No change was made."]
    assert _person("ali") is None


def test_old_schema_database_exit_1(tmp_path):
    path = tmp_path / "old.db"
    connection = connect(path)
    connection.execute("PRAGMA user_version = 3")
    connection.close()
    output = []
    code = run_command(["list"], database_path=path, now=lambda: NOW, write=output.append,
                       read_password=lambda prompt: pytest.fail("no password needed"))
    assert code == 1
    assert "older than the code" in output[0] and "seed load" in output[0]


def test_empty_database_works(tmp_path):
    output = []
    code = run_command(["list"], database_path=tmp_path / "new.db", now=lambda: NOW, write=output.append,
                       read_password=lambda prompt: pytest.fail("no password needed"))
    assert code == 0
    assert output == ["No accounts yet; create one with 'python -m app.accounts create'."]


def test_help_and_missing_command():
    assert _run("--help").code == 0
    assert _run().code == 2
    assert _run("delete", "--username", "ali").code == 2
