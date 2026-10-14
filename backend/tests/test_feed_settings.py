"""Configuration of the feeds: the fixture-mode guard, the test-only clock, and the secret address."""
import json
import logging
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core import logging as app_logging
from app.core.clock import ShiftedClock, SystemClock, make_clock
from app.core.config import Settings, url_host
from app.main import create_app

SECRET = "https://calendar.example.test/calendar/ical/me%40gmail.com/private-0123456789abcdef0123456789abcdef/basic.ics"


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    monkeypatch.setattr(app_logging, "_registered", set())
    for name in ("FEEDS_MODE", "FF_FEED_URL", "GCAL_ICAL_URL", "APP_NOW_OVERRIDE", "APP_ENV", "REDACT_ENV"):
        monkeypatch.delenv(name, raising=False)


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_feeds_are_off_by_default_and_nothing_is_configured():
    s = settings()
    assert (s.feeds_mode, s.gcal_url, s.app_now_override) == ("off", None, None)
    assert s.ff_feed_url == "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    assert (s.ff_poll_minutes, s.gcal_poll_minutes, s.sync_cooldown_seconds) == (60, 30, 300)


def test_fixture_mode_refuses_any_address_that_is_not_loopback():
    with pytest.raises(ValidationError, match="FF_FEED_URL points elsewhere"):
        settings(feeds_mode="fixture")  # the default feed address is the real host
    with pytest.raises(ValidationError) as caught:
        settings(feeds_mode="fixture", ff_feed_url="http://127.0.0.1:9000/ff", gcal_ical_url=SECRET)
    assert "GCAL_ICAL_URL points elsewhere" in str(caught.value)
    assert "private-" not in str(caught.value) and "calendar.example.test" not in str(caught.value), "the error names the setting, never the secret"
    ok = settings(feeds_mode="fixture", ff_feed_url="http://127.0.0.1:9000/ff", gcal_ical_url="http://localhost:9000/ical/private-0123456789abcdef0123456789abcdef.ics")
    assert ok.feeds_mode == "fixture"


def test_fixture_mode_can_name_the_stub_container_and_nothing_with_a_dot():
    gcal = "http://feedstub:8765/gcal/ical/me/private-0123456789abcdef0123456789abcdef/basic.ics"
    ok = settings(feeds_mode="fixture", feeds_fixture_hosts="feedstub", ff_feed_url="http://feedstub:8765/ff/thisweek.xml", gcal_ical_url=gcal)
    assert ok.fixture_hosts == {"feedstub"}
    with pytest.raises(ValidationError, match="FF_FEED_URL points elsewhere"):  # a named host is allowed, any other still is not
        settings(feeds_mode="fixture", feeds_fixture_hosts="feedstub", ff_feed_url="https://nfs.faireconomy.media/x.json")
    with pytest.raises(ValidationError, match="plain host names"):  # a public site cannot be smuggled in
        settings(feeds_mode="fixture", feeds_fixture_hosts="nfs.faireconomy.media")
    with pytest.raises(ValidationError, match="plain host names"):
        settings(feeds_mode="fixture", feeds_fixture_hosts="feedstub, a b")
    assert settings(feeds_fixture_hosts=" Feedstub , other ").fixture_hosts == {"feedstub", "other"}  # case and spaces do not matter
    assert settings().fixture_hosts == frozenset()


def test_live_and_off_modes_accept_remote_addresses():
    assert settings(feeds_mode="live", gcal_ical_url=SECRET).gcal_url == SECRET
    assert settings(feeds_mode="off", gcal_ical_url=SECRET).gcal_url == SECRET


def test_the_secret_is_hidden_from_reprs_dumps_and_the_host_helper_keeps_only_the_host():
    s = settings(feeds_mode="live", gcal_ical_url=SECRET)
    assert "private-" not in repr(s) and "private-" not in str(s.model_dump()) and "private-" not in s.model_dump_json()
    assert url_host(SECRET) == "calendar.example.test"
    assert url_host("http://user:pass@LOCALHOST:8080/x?y=1") == "localhost"


@pytest.mark.parametrize("override", ["", "   "])
def test_a_blank_secret_or_override_means_unset(override):
    s = settings(gcal_ical_url=override, app_now_override=override)
    assert s.gcal_url is None and s.app_now_override is None


def test_the_clock_override_is_honored_only_in_test_and_needs_a_zone():
    assert settings(app_env="test", app_now_override="2044-05-11T12:00:00Z").app_now_override == datetime(2044, 5, 11, 12, tzinfo=timezone.utc)
    with pytest.raises(ValidationError, match="only when APP_ENV=test"):
        settings(app_env="prod", app_now_override="2044-05-11T12:00:00Z")
    with pytest.raises(ValidationError, match="explicit UTC offset"):
        settings(app_env="test", app_now_override="2044-05-11T12:00:00")
    assert settings(app_env="test", app_now_override="2044-05-11T08:00:00-04:00").app_now_override == datetime(2044, 5, 11, 12, tzinfo=timezone.utc)


def test_polling_has_floors_so_a_misconfiguration_cannot_hammer_a_host():
    with pytest.raises(ValidationError):
        settings(ff_poll_minutes=10)
    with pytest.raises(ValidationError):
        settings(gcal_poll_minutes=1)


def test_the_shifted_clock_starts_where_it_is_told_and_then_runs():
    start = datetime(2044, 5, 11, 12, tzinfo=timezone.utc)
    clock = make_clock(start)
    assert isinstance(clock, ShiftedClock) and isinstance(make_clock(None), SystemClock)
    first = clock.now()
    assert first >= start and (first - start).total_seconds() < 1
    import time

    time.sleep(0.05)
    assert clock.now() > first
    with pytest.raises(ValueError):
        ShiftedClock(datetime(2044, 5, 11, 12))


# --- the address from .env is secret too -----------------------------------------------------------------------------------


def test_a_secret_from_the_env_file_is_masked_in_the_logs_although_it_never_reached_os_environ(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"FEEDS_MODE=live\nGCAL_ICAL_URL={SECRET}\n", encoding="utf-8")
    loaded = Settings(_env_file=env_file, app_env="test", database_url="sqlite://", auto_migrate=False)
    assert loaded.gcal_url == SECRET
    import os

    assert "GCAL_ICAL_URL" not in os.environ  # which is exactly why the redactor needs to be told
    create_app(loaded)

    record = logging.LogRecord("app.test", logging.WARNING, __file__, 1, f"could not fetch {SECRET}", (), None)
    record.address = SECRET
    entry = json.loads(app_logging.JsonFormatter().format(record))
    assert SECRET not in json.dumps(entry) and "private-0123" not in json.dumps(entry)
    assert entry["msg"] == f"could not fetch {app_logging.MASK}" and entry["address"] == app_logging.MASK


def test_a_short_value_is_not_registered_because_it_would_mask_ordinary_words():
    app_logging.register_secret("short")
    app_logging.register_secret(None)
    assert app_logging.Redactor().text("a short story") == "a short story"
