"""What the calendar grid and the day page should show, checked against the fixture oracles (support/feeds.py).

The expected figures are worked out here from the fixture files; nothing is read back from the app to decide what it
should have shown.
"""
from collections import Counter

from playwright.sync_api import Page, expect

from support.feeds import day_news, day_personal

IMPACTS = ("high", "medium", "low", "holiday")


def expect_grid(page: Page, news, personal, days, impacts: tuple[str, ...] = (), currency: str | None = None, show: str = "all") -> None:
    """Every listed day of the grid shows exactly the news badges and the personal badge the filters leave.

    `news` and `personal` are lists of oracle events (support.feeds); `impacts`, `currency` and `show` are the filters in force."""
    for day in days:
        counts = day_news(news, day, impacts, currency) if show != "personal" else Counter()
        for impact in IMPACTS:
            if counts[impact]:
                expect(page.get_by_test_id(f"news-count-{day}-{impact}")).to_have_text(str(counts[impact]))
            else:
                expect(page.get_by_test_id(f"news-badge-{day}-{impact}")).to_have_count(0)
        mine = day_personal(personal, day) if show != "news" else []
        if mine:
            expect(page.get_by_test_id(f"personal-title-{day}")).to_have_text(mine[0]["title"])
            more = page.get_by_test_id(f"personal-title-{day}-more")
            if len(mine) > 1:
                expect(more).to_have_text(f"+{len(mine) - 1}")
            else:
                expect(more).to_have_count(0)
        else:
            expect(page.get_by_test_id(f"personal-badge-{day}")).to_have_count(0)
