"""S1-05: data selection rules and query."""
import pytest

from app import settings
from app.data_selection.rules import (
    MESSAGE_LIMIT, find_target_channels, resolve_slack_mentions, channels_in_question, author_name,
)
from app.data_selection import selection as selection_module
from app.data_selection.selection import select_messages
from app.database.schema import connect, create_tables

DEV, GENEL, YONETIM = "C0C83M051QD", "C0C8ATRM073", "C0CB44VUCF2"
CHANNELS = [(DEV, "dev", "allowed"), (GENEL, "genel", "allowed"), (YONETIM, "yonetim", "allowed"),
            ("C0OLD000001", "old", "excluded")]


@pytest.fixture
def seeded():
    connection = connect(settings.DATABASE_PATH)
    yield connection
    connection.close()


def _add_excluded_channel(connection):
    with connection:
        connection.execute("INSERT INTO channels (slack_id, name, is_private, status) VALUES ('C0OLD000001', 'old', 0, 'excluded')")
        connection.execute(
            "INSERT INTO messages (channel_id, ts, author_id, sent_at, clean_text) "
            "VALUES ('C0OLD000001', '1792665999.000001', 'U0CA5HH3M1V', '2026-10-22T10:46:39+00:00', 'TEST - excluded message')"
        )


@pytest.mark.parametrize("question, expected", [
    ("#dev'i özetle", ["dev"]),
    ("#yonetim'de neler var?", ["yonetim"]),
    ("#DEV ne durumda", ["dev"]),
    ("#dev, sonra", ["dev"]),
])
def test_hashed_channel_name_with_turkish_suffix_is_recognized(question, expected):
    assert channels_in_question(question) == expected


@pytest.mark.parametrize("question", ["genel olarak neler oldu", "yonetim hakkında", "dev bir sorun var"])
def test_channel_name_without_hash_not_recognized_goes_to_all_allowed_channels(question):
    assert channels_in_question(question) == []
    assert find_target_channels(question, CHANNELS) == ("ok", [DEV, GENEL, YONETIM])


@pytest.mark.parametrize("question", ["PR #17 ne durumda", "#1 öncelik ne?", "#17'yi kim aldı"])
def test_digits_only_hash_is_not_a_channel_name(question):
    assert channels_in_question(question) == []
    assert find_target_channels(question, CHANNELS) == ("ok", [DEV, GENEL, YONETIM])


def test_multiple_channel_names_all_in_order():
    assert channels_in_question("#genel ve #dev, bir de #genel") == ["genel", "dev"]
    assert find_target_channels("#genel ve #dev", CHANNELS) == ("ok", [GENEL, DEV])


def test_target_channel_decision():
    assert find_target_channels("#dev", []) == ("no_slack_data", [])
    for question in ("#bugs neler var", "#ik'i özetle", "#old kanalı", "#dev ve #ik"):
        assert find_target_channels(question, CHANNELS) == ("channel_not_allowed", [])
    assert find_target_channels("neler oldu?", CHANNELS) == ("ok", [DEV, GENEL, YONETIM])


def test_author_name_order():
    assert author_name("Ali Kaya", "ali", "U1") == "Ali Kaya"
    assert author_name(None, "ali", "U1") == "ali"
    assert author_name("  ", "", "U1") == "U1"


def test_slack_mentions_turned_into_readable_names():
    users = {"U0CA5HH3M1V": "Ali Kaya"}
    channels = {YONETIM: "yonetim"}
    text = ("<@U0CA5HH3M1V> ve <@U0CA5HH3M1V|ali> bak <#C0CB44VUCF2> <#C0CB44VUCF2|other> "
            "<@U0UNKNOWN01> <#C0UNKNOWN01> <tel:+905000000000|+90 500> <https://example.test|link> <!here>")
    assert resolve_slack_mentions(text, users, channels) == (
        "@Ali Kaya ve @Ali Kaya bak #yonetim #yonetim "
        "<@U0UNKNOWN01> <#C0UNKNOWN01> <tel:+905000000000|+90 500> <https://example.test|link> <!here>"
    )


def test_dev_selection_only_dev_oldest_to_newest(seeded):
    selection = select_messages(seeded, "#dev'i özetle")
    assert selection.result == "ok"
    assert len(selection.messages) == 27
    assert {m.channel for m in selection.messages} == {"dev"}
    times = [m.time for m in selection.messages]
    assert times == sorted(times)
    assert not any("<@U" in m.text for m in selection.messages)


def test_no_name_only_allowed_channels(seeded):
    _add_excluded_channel(seeded)
    selection = select_messages(seeded, "geçen hafta neler oldu?")
    assert selection.result == "ok"
    assert len(selection.messages) == 39
    assert {m.channel for m in selection.messages} == {"dev", "genel", "yonetim"}


def test_excluded_channel_not_read_in_query_layer_either(seeded, monkeypatch):
    _add_excluded_channel(seeded)
    # Even if the target decision is wrong (excluded channel in the list), the query does not return the excluded channel.
    monkeypatch.setattr(selection_module, "find_target_channels", lambda question, c: ("ok", ["C0OLD000001", DEV]))
    selection = select_messages(seeded, "herhangi")
    assert {m.channel for m in selection.messages} == {"dev"}
    assert not any("excluded message" in m.text for m in selection.messages)


def test_fifty_message_limit_newest_fifty():
    assert MESSAGE_LIMIT == 50
    connection = connect(":memory:")
    create_tables(connection)
    with connection:
        connection.execute("INSERT INTO slack_users (slack_id, real_name) VALUES ('U1', 'TEST - Person')")
        connection.execute("INSERT INTO channels (slack_id, name, is_private, status) VALUES ('C1', 'dev', 0, 'allowed')")
        for i in range(1, 61):
            connection.execute(
                "INSERT INTO messages (channel_id, ts, author_id, sent_at, clean_text) VALUES ('C1', ?, 'U1', ?, ?)",
                (f"{1792000000 + i}.000000", f"2026-10-22T10:{i // 60:02d}:{i % 60:02d}+00:00", f"message {i}"),
            )
    selection = select_messages(connection, "#dev'i özetle", allowed_channels=["C1"], blocked_channels=[])
    connection.close()
    assert len(selection.messages) == 50
    assert [m.text for m in selection.messages] == [f"message {i}" for i in range(11, 61)]


def test_empty_list_if_allowed_channel_has_no_messages():
    connection = connect(":memory:")
    create_tables(connection)
    with connection:
        connection.execute("INSERT INTO channels (slack_id, name, is_private, status) VALUES ('C1', 'dev', 0, 'allowed')")
    selection = select_messages(connection, "#dev'i özetle", allowed_channels=["C1"], blocked_channels=[])
    connection.close()
    assert selection.result == "ok"
    assert selection.messages == []


def test_same_name_two_rows_rejected():
    for statuses in [("allowed", "excluded"), ("allowed", "allowed"), ("excluded", "allowed")]:
        channels = [("C1", "dev", statuses[0]), ("C2", "Dev", statuses[1]), (GENEL, "genel", "allowed")]
        assert find_target_channels("#dev'i özetle", channels) == ("channel_not_allowed", [])
        assert find_target_channels("#genel ve #dev", channels) == ("channel_not_allowed", [])
        assert find_target_channels("#genel", channels) == ("ok", [GENEL])


def test_renamed_channel_question_mapping():
    # #dev was renamed to dev-eski; a new channel was opened with the name dev (not on the allow list).
    channels = [(DEV, "dev-eski", "allowed"), ("C0NEWDEV001", "dev", "excluded")]
    assert find_target_channels("#dev'i özetle", channels) == ("channel_not_allowed", [])
    assert find_target_channels("#dev-eski'yi özetle", channels) == ("ok", [DEV])


def test_question_time_blocklist_wins(seeded):
    # The table still says "allowed" for dev (no sync since the setting changed).
    assert seeded.execute("SELECT status FROM channels WHERE slack_id = ?", (DEV,)).fetchone() == ("allowed",)
    lists = {"allowed_channels": [DEV, GENEL, YONETIM], "blocked_channels": [DEV]}
    selection = select_messages(seeded, "#dev'i özetle", **lists)
    assert (selection.result, selection.messages) == ("channel_not_allowed", [])
    selection = select_messages(seeded, "geçen hafta neler oldu?", **lists)
    assert selection.result == "ok"
    assert {m.channel for m in selection.messages} == {"genel", "yonetim"}


def test_question_time_removed_from_allowlist_not_read(seeded):
    selection = select_messages(seeded, "#dev'i özetle", allowed_channels=[GENEL, YONETIM], blocked_channels=[])
    assert (selection.result, selection.messages) == ("channel_not_allowed", [])
    selection = select_messages(seeded, "#genel", allowed_channels=[], blocked_channels=[])
    assert (selection.result, selection.messages) == ("channel_not_allowed", [])


def test_question_time_uses_settings_by_default(seeded, monkeypatch):
    monkeypatch.setattr(settings, "BLOCKED_CHANNELS", [DEV])
    assert select_messages(seeded, "#dev'i özetle").result == "channel_not_allowed"


def test_query_layer_drops_blocked_even_if_target_decision_wrong(seeded, monkeypatch):
    monkeypatch.setattr(selection_module, "find_target_channels", lambda question, c: ("ok", [DEV, GENEL]))
    selection = select_messages(seeded, "herhangi", allowed_channels=[DEV, GENEL, YONETIM], blocked_channels=[DEV])
    assert {m.channel for m in selection.messages} == {"genel"}
