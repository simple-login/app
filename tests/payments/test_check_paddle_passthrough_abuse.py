import arrow

from app.user_audit_log_utils import UserAuditLogAction
from commands.check_paddle_passthrough_abuse import (
    DEFAULT_WINDOW_DAYS,
    suspicious_extensions,
)


class FakeEntry:
    """just the two UserAuditLog fields the detector looks at"""

    def __init__(self, action: UserAuditLogAction, day: int):
        self.action = action.value
        self.created_at = arrow.get("2026-01-01").shift(days=day)


def _upgrade(day: int) -> FakeEntry:
    return FakeEntry(UserAuditLogAction.Upgrade, day)


def _extended(day: int) -> FakeEntry:
    return FakeEntry(UserAuditLogAction.SubscriptionExtended, day)


def _cancelled(day: int) -> FakeEntry:
    return FakeEntry(UserAuditLogAction.SubscriptionCancelled, day)


def _find(entries, ignore_window: bool = False):
    return suspicious_extensions(
        entries, window_days=DEFAULT_WINDOW_DAYS, ignore_window=ignore_window
    )


def test_takeover_of_an_active_subscription_is_reported():
    """the attack: an extension lands while the plan cannot have lapsed"""
    entries = [_upgrade(0), _extended(3)]
    assert [e.created_at.day for e in _find(entries)] == [4]


def test_cancel_then_resubscribe_is_clean():
    entries = [_upgrade(0), _cancelled(10), _extended(20)]
    assert _find(entries) == []


def test_lapse_then_resubscribe_is_clean():
    """no cancellation, but late enough that the plan had expired"""
    entries = [_upgrade(0), _extended(DEFAULT_WINDOW_DAYS + 1)]
    assert _find(entries) == []


def test_extension_right_on_the_window_edge_is_reported():
    entries = [_upgrade(0), _extended(DEFAULT_WINDOW_DAYS)]
    assert len(_find(entries)) == 1


def test_first_purchase_alone_is_clean():
    assert _find([_upgrade(0)]) == []


def test_each_period_is_judged_on_its_own():
    """a clean re-subscription does not excuse a later takeover"""
    entries = [
        _upgrade(0),
        _cancelled(10),
        _extended(20),  # legitimate: cancelled before
        _extended(23),  # takeover: no cancellation since day 20
    ]
    assert [e.created_at.day for e in _find(entries)] == [24]


def test_cancellation_only_excuses_the_next_extension():
    entries = [_upgrade(0), _cancelled(5), _extended(10), _extended(12)]
    assert [e.created_at.day for e in _find(entries)] == [13]


def test_repeated_takeovers_are_all_reported():
    entries = [_upgrade(0), _extended(2), _extended(4)]
    assert len(_find(entries)) == 2


def test_ignore_window_reports_a_lapsed_looking_extension():
    entries = [_upgrade(0), _extended(DEFAULT_WINDOW_DAYS + 1)]
    assert _find(entries) == []
    assert len(_find(entries, ignore_window=True)) == 1


def test_ignore_window_still_respects_cancellations():
    entries = [_upgrade(0), _cancelled(10), _extended(400)]
    assert _find(entries, ignore_window=True) == []


def test_extension_without_a_known_start_needs_ignore_window():
    """audit log starting mid-history: no Upgrade to anchor the period"""
    entries = [_extended(5)]
    assert _find(entries) == []
    assert len(_find(entries, ignore_window=True)) == 1
