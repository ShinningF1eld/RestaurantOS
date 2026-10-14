from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

from app.modules.analytics.domain.projection import (
    Contribution,
    creation_date,
    should_apply,
)


def test_creation_date_is_utc_not_completion_or_local_date():
    assert creation_date(datetime(2026, 1, 2)) == date(2026, 1, 2)
    assert creation_date(
        datetime(2026, 1, 2, tzinfo=timezone(timedelta(hours=7)))
    ) == date(2026, 1, 1)
    assert creation_date(datetime(2026, 1, 2, tzinfo=UTC)) == date(2026, 1, 2)


def test_revisions_skip_duplicates_stale_events_and_terminal_deletions():
    original = Contribution(1, 4, date(2026, 1, 1), Decimal("1.23"), "completed")
    deleted = Contribution(1, 5, original.creation_date, Decimal("0"), "deleted")
    assert should_apply(None, original)
    assert not should_apply(original, original)
    assert should_apply(original, deleted)
    assert not should_apply(deleted, original)
    assert not should_apply(
        deleted,
        Contribution(1, 6, original.creation_date, Decimal("1.23"), "completed"),
    )
