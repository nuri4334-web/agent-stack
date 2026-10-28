import pytest

from app.database.rules import (
    BLOCKED, EXCLUDED, ALLOWED, blocked_list_error, channel_list_warnings, channel_status, is_channel_id,
)

DEV, GENEL, YONETIM = "C0C83M051QD", "C0C8ATRM073", "C0CB44VUCF2"
ALLOW_LIST = [GENEL, DEV, YONETIM]
BLOCK_LIST = ["C_IK"]


# yonetim is private but allowed: being private does not affect the decision.
@pytest.mark.parametrize("channel", [GENEL, DEV, YONETIM])
def test_channel_on_list_is_allowed(channel):
    assert channel_status(channel, ALLOW_LIST, BLOCK_LIST) == ALLOWED


def test_channel_not_on_list_is_excluded():
    assert channel_status("C_SALES", ALLOW_LIST, BLOCK_LIST) == EXCLUDED


def test_empty_list_excludes_everything():
    for channel in ALLOW_LIST:
        assert channel_status(channel, [], []) == EXCLUDED


def test_blocked_id_always_wins():
    assert channel_status("C_IK", ALLOW_LIST + ["C_IK"], BLOCK_LIST) == BLOCKED
    # A name on the allow list never opens a channel, not even the blocked one.
    allow_list = ALLOW_LIST + ["ik", "#ik", "IK"]
    assert channel_status("C_IK", allow_list, []) == EXCLUDED
    assert channel_status("C_IK", allow_list, BLOCK_LIST) == BLOCKED


def test_channel_name_never_allows():
    assert channel_status(DEV, ["dev", "#dev", " #Dev "], []) == EXCLUDED
    # Only spaces around an id are removed; the case is not changed.
    assert channel_status(DEV, [f" {DEV} "], []) == ALLOWED
    assert channel_status(DEV, [DEV.lower()], []) == EXCLUDED


def test_empty_channel_id_excluded():
    for channel in ["", "  "]:
        assert channel_status(channel, ALLOW_LIST + [""], BLOCK_LIST) == EXCLUDED


@pytest.mark.parametrize("value, expected", [
    (DEV, True), ("G01ABCDEF", True), ("C_DEV", True),
    ("dev", False), ("#dev", False), (DEV.lower(), False), ("C", False), ("", False), (" ", False),
    (f" {DEV}", False), (None, False),
])
def test_channel_id_format(value, expected):
    assert is_channel_id(value) is expected


def test_blocked_wins_even_with_invalid_allow_values():
    assert channel_status("C_IK", ["ik", "", "C_IK", "genel"], ["C_IK"]) == BLOCKED


def test_warnings_for_old_names():
    warnings = channel_list_warnings(["genel", "dev", "yonetim"], [])
    assert warnings[0] == (
        "ALLOWED_CHANNELS now takes channel IDs (e.g. C0123ABCDEF); these values are ignored: genel, dev, yonetim"
    )
    assert "ALLOWED_CHANNELS is empty; no channel will be read." in warnings
    assert channel_list_warnings(ALLOW_LIST, ["ik"]) == [
        "BLOCKED_CHANNELS takes channel IDs; invalid values: ik"
    ]
    assert blocked_list_error(["C_IK", " ik ", "", "ik"]) == "BLOCKED_CHANNELS takes channel IDs; invalid values: ik"
    assert blocked_list_error(["C_IK"]) is None


def test_warning_for_id_in_both_lists():
    assert channel_list_warnings(ALLOW_LIST + ["C_IK"], BLOCK_LIST) == [
        "These channel IDs are on both lists; BLOCKED_CHANNELS wins: C_IK"
    ]


def test_warning_for_empty_allowlist_and_none_for_empty_blocklist():
    assert channel_list_warnings([], BLOCK_LIST) == ["ALLOWED_CHANNELS is empty; no channel will be read."]
    assert channel_list_warnings(ALLOW_LIST, []) == []
    assert blocked_list_error([]) is None
