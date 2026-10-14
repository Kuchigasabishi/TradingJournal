import json
import logging
import re
import sys

import pytest

from app.core.logging import MASK, JsonFormatter

SECRET = "https://calendar.example.test/ical/me/private-0123456789abcdef0123456789abcdef/basic.ics"


def record(msg="hello", level=logging.INFO, exc_info=None, **extra):
    rec = logging.LogRecord("app.test", level, __file__, 1, msg, (), exc_info)
    rec.__dict__.update(extra)
    return rec


def line(rec, **formatter_args):
    return JsonFormatter(**formatter_args).format(rec)


def entry(rec, **formatter_args):
    return json.loads(line(rec, **formatter_args))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("REDACT_ENV", "GCAL_ICAL_URL", "MY_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_required_fields_and_utc_timestamp():
    result = entry(record())
    assert {"ts", "source", "level", "logger", "msg"} <= set(result)
    assert result["source"] == "server"
    assert result["level"] == "info"
    assert result["logger"] == "app.test"
    assert result["msg"] == "hello"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", result["ts"])


def test_the_request_id_in_context_is_added_to_every_record():
    from app.core.context import request_id_var

    token = request_id_var.set("ctx-42")
    try:
        assert entry(record())["request_id"] == "ctx-42"
        assert entry(record(request_id="explicit"))["request_id"] == "explicit"  # an explicit value wins
    finally:
        request_id_var.reset(token)
    assert "request_id" not in entry(record())


def test_source_can_be_overridden():
    assert entry(record(), source="harness")["source"] == "harness"


@pytest.mark.parametrize(
    ("level", "expected"),
    [(logging.DEBUG, "debug"), (logging.WARNING, "warning"), (logging.ERROR, "error"), (logging.CRITICAL, "error")],
)
def test_level_mapping(level, expected):
    assert entry(record(level=level))["level"] == expected


def test_extra_fields_are_included_and_internals_are_not():
    result = entry(record(request_id="abc", status=200, color_message="\x1b[32mcoloured\x1b[0m"))
    assert result["request_id"] == "abc"
    assert result["status"] == 200
    assert "color_message" not in result
    assert "args" not in result and "pathname" not in result


def test_exception_traceback_goes_into_exc():
    try:
        raise ValueError("bad value")
    except ValueError:
        result = entry(record("failed", level=logging.ERROR, exc_info=sys.exc_info()))
    assert "Traceback" in result["exc"]
    assert "ValueError: bad value" in result["exc"]


def test_output_is_a_single_ascii_line():
    output = line(record("multi\nline café ✓"))
    assert "\n" not in output
    assert output.isascii()
    assert json.loads(output)["msg"] == "multi\nline café ✓"


def test_env_secret_is_masked_in_message_extras_and_traceback(monkeypatch):
    monkeypatch.setenv("GCAL_ICAL_URL", SECRET)
    try:
        raise RuntimeError(f"fetch failed for {SECRET}")
    except RuntimeError:
        rec = record(f"fetching {SECRET}", level=logging.ERROR, exc_info=sys.exc_info(), nested={"urls": [SECRET]})
    output = line(rec)
    assert SECRET not in output
    assert output.count(MASK) >= 3


def test_ical_private_token_is_masked_even_when_not_in_env():
    output = line(record("token private-0123456789abcdef0123 leaked"))
    assert "private-0123456789abcdef0123" not in output
    assert MASK in output


def test_values_named_by_redact_env_are_masked(monkeypatch):
    monkeypatch.setenv("REDACT_ENV", "MY_TOKEN")
    monkeypatch.setenv("MY_TOKEN", "super-secret-value")
    output = line(record("using super-secret-value now"))
    assert "super-secret-value" not in output


def test_short_values_are_not_treated_as_secrets(monkeypatch):
    monkeypatch.setenv("GCAL_ICAL_URL", "short")
    assert entry(record("a short message"))["msg"] == "a short message"
