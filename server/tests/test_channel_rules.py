import pytest

from app.database.rules import EXCLUDED, ALLOWED, channel_status

ALLOW_LIST = ["genel", "dev", "yonetim"]


# yonetim is private but allowed: being private does not affect the decision.
@pytest.mark.parametrize("channel", ["genel", "dev", "yonetim"])
def test_channel_on_list_is_allowed(channel):
    assert channel_status(channel, ALLOW_LIST) == ALLOWED


def test_channel_not_on_list_is_excluded():
    assert channel_status("sales", ALLOW_LIST) == EXCLUDED


def test_empty_list_excludes_everything():
    for channel in ALLOW_LIST:
        assert channel_status(channel, []) == EXCLUDED


def test_ik_always_excluded():
    allow_list = ALLOW_LIST + ["ik", "#ik", "IK"]
    for channel in ["ik", "#ik", " IK "]:
        assert channel_status(channel, allow_list) == EXCLUDED


def test_name_format_is_normalized():
    assert channel_status(" #Dev ", ALLOW_LIST) == ALLOWED
    assert channel_status("dev", ["#dev"]) == ALLOWED


def test_empty_channel_name_excluded():
    for channel in ["", "#", "  "]:
        assert channel_status(channel, ALLOW_LIST + [""]) == EXCLUDED
