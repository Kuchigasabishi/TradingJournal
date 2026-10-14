"""Client half of the harness self-test (docs/BLUEPRINT.md, section 6.4).

These tests deliberately break the clean-run rule. Only `scripts/verify.py --self-test` runs them,
and it expects the first two to FAIL and the third to PASS. If a canary ever passes when it should
fail, the gate has gone vacuous.
"""
import pytest


def test_unallowed_console_error(page):
    page.goto("/")
    page.evaluate("console.error('canary: unexpected console error')")


def test_unallowed_page_error(page):
    page.goto("/")
    with page.expect_event("pageerror"):
        page.evaluate("setTimeout(() => { throw new Error('canary: unhandled page error') }, 0)")


@pytest.mark.allow_console_errors("canary: allowed", reason="canary proving the allow-list works")
def test_allowed_console_error_passes(page):
    page.goto("/")
    page.evaluate("console.error('canary: allowed console error')")
