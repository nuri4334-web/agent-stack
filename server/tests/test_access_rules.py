"""S2-05: the pure access decision (API contract 8, 11) and the source id."""
import pytest

from app.data_selection.rules import AccessDecision, decide_access, find_target_channels, source_id

CHANNELS = [
    ("C_DEV", "dev", "allowed"),
    ("C_GENEL", "genel", "allowed"),
    ("C_YON", "yonetim", "allowed"),
    ("C_BUGS", "bugs", "excluded"),
    ("C_IK", "ik", "blocked"),
    ("C_OLD1", "old", "allowed"),
    ("C_OLD2", "Old", "allowed"),
]
ALI = {"C_DEV", "C_GENEL"}
EVERYWHERE = {slack_id for slack_id, _, _ in CHANNELS}
NOT_MEMBER = AccessDecision("NOT_CHANNEL_MEMBER")
NOT_ALLOWED = AccessDecision("CHANNEL_NOT_ALLOWED")


def _decide(question, members=frozenset(ALI), channels=CHANNELS):
    return decide_access(question, channels, members, slack_linked=True)


@pytest.mark.parametrize("question", ["#dev'i özetle", "geçen hafta neler oldu?", "#ik", "#yok"])
@pytest.mark.parametrize("channels", [CHANNELS, []])
def test_no_slack_account_comes_first(question, channels):
    assert decide_access(question, channels, EVERYWHERE, slack_linked=False) == AccessDecision("NO_SLACK_ACCOUNT")


@pytest.mark.parametrize("question", ["#dev'i özetle", "geçen hafta neler oldu?"])
def test_empty_table_passes_with_no_channels(question):
    assert _decide(question, channels=[]) == AccessDecision()


def test_no_name_gives_allowed_channels_of_the_member():
    assert _decide("geçen hafta neler oldu?") == AccessDecision(channel_ids=("C_DEV", "C_GENEL"))


def test_no_name_never_gives_a_channel_that_is_not_allowed():
    assert _decide("neler oldu?", EVERYWHERE).channel_ids == ("C_DEV", "C_GENEL", "C_YON", "C_OLD1", "C_OLD2")


def test_digits_only_hash_is_not_a_channel_name():
    assert _decide("PR #17 ne durumda?") == AccessDecision(channel_ids=("C_DEV", "C_GENEL"))


@pytest.mark.parametrize("question", ["#bugs neler var", "#ik'i özetle", "#yok neler var"])
def test_excluded_blocked_and_unknown_are_not_allowed_even_for_a_member(question):
    assert _decide(question, EVERYWHERE) == NOT_ALLOWED


def test_same_name_two_rows_is_not_allowed():
    assert _decide("#old neler var", EVERYWHERE) == NOT_ALLOWED


def test_allowed_but_not_member():
    assert _decide("#yonetim'de neler var?") == NOT_MEMBER


def test_all_named_channels_readable_in_order():
    assert _decide("#genel ve #dev") == AccessDecision(channel_ids=("C_GENEL", "C_DEV"))


@pytest.mark.parametrize("question", ["#dev ve #yonetim", "#yonetim ve #dev", "#dev ve #ik", "#ik ve #dev"])
def test_one_refused_name_refuses_all(question):
    decision = _decide(question)
    assert decision.reason_code is not None
    assert decision.channel_ids == ()


@pytest.mark.parametrize("question, expected", [
    ("#yonetim ve #ik", NOT_MEMBER),
    ("#ik ve #yonetim", NOT_ALLOWED),
])
def test_first_refused_name_gives_the_reason(question, expected):
    assert _decide(question) == expected


def test_no_membership_and_no_name_passes_with_no_channels():
    assert _decide("neler oldu?", frozenset()) == AccessDecision()


def test_no_membership_and_a_name_is_not_member():
    assert _decide("#dev", frozenset()) == NOT_MEMBER


@pytest.mark.parametrize("question", [
    "#dev", "#DEV özet", "#genel ve #dev", "#dev ve yine #dev", "neler oldu?", "#ik", "#bugs", "#old", "#dev ve #ik",
])
def test_same_channel_rule_as_find_target_channels_for_a_member_of_everything(question):
    result, targets = find_target_channels(question, CHANNELS)
    decision = _decide(question, EVERYWHERE)
    assert (decision.reason_code is None) == (result == "ok")
    assert list(decision.channel_ids) == targets


def test_source_id_keeps_ts_as_it_is():
    assert source_id("C0C83M051QD", "1792665328.994100") == "C0C83M051QD:1792665328.994100"
