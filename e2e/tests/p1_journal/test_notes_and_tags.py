"""Phase 1: day notes and tags. Day notes use their own year (2034) so ranges stay exact."""
import pytest
from support.journal import unique


def test_a_day_note_round_trips(api, journal):
    response = api.post("/api/notes", data={"day": "2034-05-06", "body": "  Choppy session, sat out the afternoon.  "})
    assert response.status == 201
    note = response.json()
    journal.notes.append(note["id"])
    assert response.headers["location"] == f"/api/notes/{note['id']}"
    assert (note["day"], note["body"]) == ("2034-05-06", "Choppy session, sat out the afternoon.")
    assert api.get(f"/api/notes/{note['id']}").json() == note


def test_notes_filter_by_inclusive_day_range_and_page(api, journal):
    for day in ("2034-06-05", "2034-06-06", "2034-06-07"):
        journal.note(day, f"note for {day}")
    page = api.get("/api/notes?from=2034-06-06&to=2034-06-07").json()
    assert page["total"] == 2 and [n["day"] for n in page["items"]] == ["2034-06-07", "2034-06-06"]
    assert len(api.get("/api/notes?from=2034-06-01&to=2034-06-30&limit=1").json()["items"]) == 1
    assert api.get("/api/notes?from=2034-07-01&to=2034-06-01").status == 422


def test_a_note_can_be_edited_and_deleted(api, journal):
    note = journal.note("2034-07-01", "first draft")
    url = f"/api/notes/{note['id']}"
    edited = api.patch(url, data={"body": "second draft"}).json()
    assert (edited["body"], edited["day"]) == ("second draft", "2034-07-01")
    assert api.patch(url, data={}).json() == edited
    assert api.patch(url, data={"body": None}).status == 422
    assert api.delete(url).status == 204
    journal.forget_note(note["id"])
    assert api.get(url).status == 404


@pytest.mark.parametrize(
    "payload",
    [{"day": "2034-07-01", "body": "   "}, {"day": "not-a-date", "body": "x"}, {"body": "x"}, {"day": "2034-07-01", "body": "x", "extra": 1}],
)
def test_invalid_notes_are_rejected(api, payload):
    assert api.post("/api/notes", data=payload).status == 422


def test_unknown_notes_are_404(api):
    assert api.get("/api/notes/999999999").status == 404
    assert api.patch("/api/notes/999999999", data={"body": "x"}).status == 404
    assert api.delete("/api/notes/999999999").status == 404


def usage(api) -> dict[str, int]:
    return {tag["name"]: tag["count"] for tag in api.get("/api/tags").json()}


def test_tags_are_shared_ignoring_case_and_disappear_with_their_last_trade(api, journal):
    shared, only = unique("Tag"), unique("Only")
    first = journal.trade(tags=[shared, only])
    second = journal.trade(tags=[shared.lower()])
    assert second["tags"] == [shared]  # the first spelling wins
    assert (usage(api)[shared], usage(api)[only]) == (2, 1)

    api.delete(f"/api/trades/{first['id']}")
    journal.forget_trade(first["id"])
    assert usage(api)[shared] == 1 and only not in usage(api)

    api.patch(f"/api/trades/{second['id']}", data={"tags": []})
    assert shared not in usage(api)


def test_tags_list_the_most_used_first(api, journal):
    busy, quiet = unique("Busy"), unique("Quiet")
    for _ in range(3):
        journal.trade(tags=[busy])
    journal.trade(tags=[quiet])
    names = [tag["name"] for tag in api.get("/api/tags").json()]
    assert names.index(busy) < names.index(quiet)
