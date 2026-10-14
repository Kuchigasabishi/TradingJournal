"""Phase 2: the day screen, and day notes from first word to deletion, with the calendar following along."""
import re
from datetime import date

import pytest
from playwright.sync_api import Page, expect

from support.journal import unique
from support.ui import day_label, expect_api, open_app, wall_to_utc

DAY = "2042-06-10"


@pytest.fixture
def busy_day(journal):
    """One closed trade (+12.5) and one trade opened the same day and still open."""
    closed = journal.trade(instrument=unique("DY"), opened_at=f"{DAY}T13:00:00Z", closed_at=f"{DAY}T14:00:00Z", pnl="12.5")
    still_open = journal.open_trade(instrument=unique("DY"), opened_at=f"{DAY}T15:00:00Z")
    return {"closed": closed, "open": still_open}


def test_the_day_screen_totals_and_lists_its_trades(page: Page, busy_day, shot):
    open_app(page, f"/day/{DAY}")
    expect(page.get_by_test_id("page-title")).to_have_text(day_label(date(2042, 6, 10)))
    expect(page.get_by_test_id("day-net-value")).to_have_text("+$12.50")
    expect(page.get_by_test_id("day-net-caption")).to_have_text("1 trade closed")
    expect(page.get_by_test_id("day-closed-value")).to_have_text("1")
    expect(page.get_by_test_id("day-open-value")).to_have_text("1")  # opened that day, still open
    expect(page.locator("[data-testid^='trade-row-']")).to_have_count(2)
    expect(page.get_by_test_id(f"trade-status-{busy_day['open']['id']}")).to_have_text("Open")
    expect(page.get_by_test_id("day-notes-empty")).to_be_visible()
    shot("01-day")


def test_the_day_screen_steps_to_the_neighbouring_days(page: Page, busy_day):
    open_app(page, f"/day/{DAY}")
    page.get_by_test_id("day-next").click()
    expect(page).to_have_url(re.compile(r"/day/2042-06-11$"))
    expect(page.get_by_test_id("page-title")).to_have_text(day_label(date(2042, 6, 11)))
    expect(page.get_by_test_id("day-trades-empty")).to_be_visible()
    page.get_by_test_id("day-prev").click()
    page.get_by_test_id("day-prev").click()
    expect(page).to_have_url(re.compile(r"/day/2042-06-09$"))


def test_a_trade_can_be_started_from_a_day(page: Page, api, journal, busy_day, shot):
    open_app(page, f"/day/{DAY}")
    page.get_by_test_id("day-new-trade").click()
    expect(page).to_have_url(re.compile(rf"/trades/new\?day={DAY}$"))
    expect(page.get_by_test_id("field-opened-at")).to_have_value(f"{DAY} 09:00")
    page.get_by_test_id("field-instrument").fill(unique("DY"))
    page.get_by_test_id("field-lot-size").fill("0.2")
    page.get_by_test_id("field-entry-price").fill("1.2")
    with expect_api(page, "POST", r"^/api/trades$") as call:
        page.get_by_test_id("form-submit").click()
    journal.track_trade(call.json()["id"])
    assert call.request_json["opened_at"] == wall_to_utc(f"{DAY} 09:00")
    shot("01-started-from-the-day")


def test_a_note_written_on_the_day_screen_marks_the_calendar(page: Page, api, journal, shot):
    open_app(page, f"/day/{DAY}")
    posts: list[str] = []
    page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)

    page.get_by_test_id("note-save").click()  # empty
    expect(page.get_by_test_id("field-day-note-error")).to_contain_text("Write something first.")
    assert posts == []

    page.get_by_test_id("field-day-note").fill("Stayed patient.")
    with expect_api(page, "POST", r"^/api/notes$") as call:
        page.get_by_test_id("note-save").click()
    assert call.request_json == {"day": DAY, "body": "Stayed patient."}
    assert call.status == 201 and call.request_id.startswith("web-")
    note = call.json()
    journal.track_note(note["id"])
    expect(page.get_by_test_id("flash-message")).to_contain_text("Note saved.")
    expect(page.get_by_test_id(f"note-body-{note['id']}")).to_have_text("Stayed patient.")
    expect(page.get_by_test_id("field-day-note")).to_have_value("")
    shot("01-note-saved")

    # Moving to the calendar without a page load: the marker must already be there, so the cache was refreshed.
    page.evaluate("window.__spa_marker = 'same document'")
    page.get_by_test_id("back-link").click()
    expect(page).to_have_url(re.compile(r"/calendar\?month=2042-06$"))
    expect(page.get_by_test_id(f"note-mark-{DAY}")).to_be_visible()
    assert page.evaluate("window.__spa_marker") == "same document"
    shot("02-marked-on-the-calendar")


def test_a_note_can_be_edited_and_moved_to_another_day(page: Page, api, journal, shot):
    note = journal.note(DAY, "Stayed patient.")
    open_app(page, f"/day/{DAY}")
    with expect_api(page, "GET", rf"^/api/notes/{note['id']}$") as read:
        page.get_by_test_id(f"note-open-{note['id']}").click()
    assert read.status == 200 and read.request_id.startswith("web-")
    expect(page).to_have_url(re.compile(rf"/notes/{note['id']}$"))
    expect(page.get_by_test_id("field-note-body")).to_have_value("Stayed patient.")
    expect(page.get_by_test_id("field-note-day")).to_have_value(DAY)
    shot("01-note")

    page.get_by_test_id("field-note-body").fill("Stayed patient. Took profit at the target.")
    with expect_api(page, "PATCH", rf"^/api/notes/{note['id']}$") as call:
        page.get_by_test_id("note-update").click()
    assert call.request_json == {"body": "Stayed patient. Took profit at the target."}, "the unchanged day is not sent"
    expect(page).to_have_url(re.compile(rf"/day/{DAY}$"))
    expect(page.get_by_test_id(f"note-body-{note['id']}")).to_have_text("Stayed patient. Took profit at the target.")

    page.get_by_test_id(f"note-open-{note['id']}").click()
    page.get_by_test_id("field-note-day").fill("2042-06-11")
    with expect_api(page, "PATCH", rf"^/api/notes/{note['id']}$") as call:
        page.get_by_test_id("note-update").click()
    assert call.request_json == {"day": "2042-06-11"}
    expect(page).to_have_url(re.compile(r"/day/2042-06-11$"))
    expect(page.get_by_test_id(f"note-{note['id']}")).to_be_visible()
    assert api.get(f"/api/notes/{note['id']}").json()["day"] == "2042-06-11"
    page.get_by_test_id("day-prev").click()
    expect(page.get_by_test_id("day-notes-empty")).to_be_visible()


def test_a_note_form_explains_mistakes_before_sending(page: Page, journal):
    note = journal.note(DAY, "Stayed patient.")
    patches: list[str] = []
    page.on("request", lambda request: patches.append(request.url) if request.method == "PATCH" else None)
    open_app(page, f"/notes/{note['id']}")
    page.get_by_test_id("field-note-day").fill("2042-13-40")
    page.get_by_test_id("note-update").click()
    expect(page.get_by_test_id("field-note-day-error")).to_contain_text("Use YYYY-MM-DD")
    page.get_by_test_id("field-note-day").fill(DAY)
    page.get_by_test_id("field-note-body").fill("   ")
    page.get_by_test_id("note-update").click()
    expect(page.get_by_test_id("field-note-body-error")).to_contain_text("Write something first.")
    page.get_by_test_id("field-note-body").fill("Stayed patient.")
    page.get_by_test_id("note-update").click()  # back to what it was: nothing to send
    expect(page.get_by_test_id("flash-message")).to_contain_text("Nothing was changed.")
    assert patches == []


def test_deleting_a_note_asks_first_and_clears_the_calendar_marker(page: Page, api, journal, shot):
    note = journal.note(DAY, "Delete me.")
    open_app(page, f"/notes/{note['id']}")
    page.get_by_test_id("note-delete").click()
    dialog = page.get_by_test_id("delete-note-dialog")
    expect(dialog).to_contain_text(day_label(date(2042, 6, 10)))
    shot("01-confirm")
    page.get_by_test_id("delete-note-dialog-cancel").click()
    expect(dialog).to_have_count(0)
    assert api.get(f"/api/notes/{note['id']}").status == 200

    page.get_by_test_id("note-delete").click()
    with expect_api(page, "DELETE", rf"^/api/notes/{note['id']}$") as call:
        page.get_by_test_id("delete-note-dialog-confirm").click()
    assert call.status == 204 and call.request_id.startswith("web-")
    expect(page).to_have_url(re.compile(rf"/day/{DAY}$"))
    expect(page.get_by_test_id("flash-message")).to_contain_text("Note deleted.")
    expect(page.get_by_test_id("day-notes-empty")).to_be_visible()
    assert api.get(f"/api/notes/{note['id']}").status == 404
    journal.forget_note(note["id"])

    page.get_by_test_id("back-link").click()
    expect(page.get_by_test_id(f"day-{DAY}")).to_be_visible()
    expect(page.get_by_test_id(f"note-mark-{DAY}")).to_have_count(0)


@pytest.mark.allow_console_errors(r"status of 404", reason="the test reloads a note that was deleted behind the page's back")
def test_a_deleted_note_is_reported_as_missing(page: Page, journal):
    note = journal.note(DAY, "Short-lived.")
    open_app(page, f"/notes/{note['id']}")
    expect(page.get_by_test_id("field-note-body")).to_have_value("Short-lived.")
    # Deleted behind the page's back (say, from another tab); the next look at it says so.
    journal.api.delete(f"/api/notes/{note['id']}")
    journal.forget_note(note["id"])
    page.reload()
    expect(page.get_by_test_id("not-found")).to_contain_text("Note not found")
