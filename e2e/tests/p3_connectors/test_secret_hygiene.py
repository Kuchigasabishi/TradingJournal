"""Phase 3: the secret Google Calendar address (GCAL_ICAL_URL) is a password. It lives in the server's environment and
nowhere else: not in an API answer, not in an error message, not in the API's own description, not in a page.

scripts/verify.py checks the same thing in every log line the run produced; this is the API half of it.
"""
import pytest

from support.feeds import assert_no_secret, secret_url


def test_the_run_really_has_a_secret_to_protect():
    assert "/gcal/ical/me/private-" in secret_url()  # the stub's address looks like Google's: a long token in the path


@pytest.mark.parametrize(
    "path",
    ["/api/sources/status", "/api/events?limit=500", "/api/events?source=gcal&limit=500", "/api/ready", "/api/openapi.json", "/api/events?impact=urgent"],
)
def test_no_answer_carries_the_address(api, path):
    response = api.get(path)
    assert response.status in (200, 422)
    assert_no_secret(response.text(), path)


def test_a_failed_sync_does_not_leak_it_either(feeds):
    for mode in ("http_404", "html", "malformed"):  # the failures an address that went wrong produces
        feeds.script(gcal={"mode": mode})
        row = feeds.sync("gcal")["gcal"]
        assert row["status"] in ("error", "bad_content"), mode
        assert_no_secret(row["message"] or "", f"the {mode} message")
        assert_no_secret(str(feeds.status()), f"the status after {mode}")
