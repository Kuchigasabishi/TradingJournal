#!/usr/bin/env python3
"""Run a phase's verification loop and write logs/phase_N.log plus screenshots and metrics.

Contract: docs/BLUEPRINT.md, sections 6.2 to 6.4. Standard library only, so any Python can start it.

    python scripts/verify.py 1            verify phase 1 (earlier phases run as regression), native backend
    python scripts/verify.py 2            phase 2 also checks, builds and serves the Expo web app (needs Node, see below)
    python scripts/verify.py 3            phase 3 also runs the feed connectors against a local stub of both hosts, offline
    python scripts/verify.py --self-test  prove the gates fail when they should

From phase 2 on the run also needs Node.js 24 LTS and `npm ci` done once in frontend/.

Exit codes: 0 pass, 1 a test or gate failed, 2 environment or usage problem.
"""
import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
ARTIFACTS = ROOT / "artifacts"
BACKEND = ROOT / "backend"
E2E = ROOT / "e2e"
STUB_WEB = BACKEND / "app" / "stub_web"
FRONTEND = ROOT / "frontend"
FIXTURES = ROOT / "fixtures"
FEED_STUB = E2E / "support" / "feed_stub.py"

MAX_PHASE = 4
RESTART_STAGE_FROM = 1  # from this phase on, the server is restarted mid-run to prove persistence
FRONTEND_FROM = 2  # from this phase on, the Expo web app is checked, built and served in place of the stub page
FEEDS_FROM = 3  # from this phase on, the feed connectors run, against a local stub of both hosts and never the internet
VERIFY_TIMEZONE = "America/New_York"  # the e2e calendar tests assume it (see test_health_and_ready.py)
HARNESS_ID_PREFIX = "harness-"  # request IDs the harness itself uses, so its probes never count as test traffic
WEB_ID_PREFIX = "web-"  # request IDs the app's own API client sends (frontend/src/api/client.ts)
POLL_ID_PREFIX = "poll-"  # request IDs a test uses while it waits for a background sync: as many polls as the wait takes (e2e/support/feeds.py)
HEALTHCHECK_ID = "healthcheck"  # the request ID the container's own probe sends (docker/app.Dockerfile, docker-compose.yml): one per 10 s of the container's life
FEED_CLOCK = "2044-05-11T12:00:00Z"  # where the app's feed clock starts, so "this week" in the fixtures is a fixed week (fixtures/README.md)
FEED_COOLDOWN_SECONDS = 2  # least time between two manual syncs of one feed: long enough to test, short enough not to slow the run
FEED_POLL_MINUTES = 720  # far longer than any run, so no scheduled sync ever lands in the middle of a test (the schedule is covered by the unit tests)
GCAL_TOKEN = "private-0123456789abcdef0123456789abcdef"  # the stub's idea of a secret calendar address, so redaction is exercised for real
LOOPBACK = ("127.0.0.1", "localhost", "::1")
# The outcomes a verified run must have seen for each feed, so the failure paths are proven to have run and not only the happy one.
FEED_OUTCOMES = {
    "forexfactory": ("ok", "unchanged", "throttled", "bad_content", "error"),
    "gcal": ("ok", "unchanged", "bad_content", "error"),
}
REQUIRED_SOURCES = ("server", "client", "test")
FEED_SOURCES = ("server", "client", "test", "stub")
REQUIRED_PACKAGES = ("fastapi", "uvicorn", "sqlalchemy", "alembic", "pydantic-settings", "pytest", "playwright", "pytest-playwright")
ALLOWED_WRITE_PREFIXES = ("logs/", "artifacts/")
HTTP_METHODS = ("get", "post", "put", "patch", "delete")
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ICAL_TOKEN = re.compile(r"private-[0-9a-fA-F]{16,}")
MASK = "***"
SETUP_HINT = (
    "Set up the dev venv once:\n"
    "  py -3.14 -m venv .venv\n"
    "  .venv\\Scripts\\python.exe -m pip install uv\n"
    "  .venv\\Scripts\\uv.exe pip sync backend\\requirements-dev.txt e2e\\requirements.txt\n"
    "  .venv\\Scripts\\python.exe -m playwright install chromium"
)
NODE_MIN = (22, 18)  # the first release that runs .ts files without a flag, which the frontend unit tests rely on
FRONTEND_SETUP_HINT = "Set up the frontend once (Node.js 24 LTS from https://nodejs.org):\n  cd frontend\n  npm ci"
FRONTEND_ENV = {
    "EXPO_NO_TELEMETRY": "1",
    "CI": "1",
    "FORCE_COLOR": "0",
    "NO_COLOR": "1",
    "NPM_CONFIG_AUDIT": "false",
    "NPM_CONFIG_FUND": "false",
    "NPM_CONFIG_UPDATE_NOTIFIER": "false",
    "PYTHONIOENCODING": "utf-8",
}
# Source rules for frontend/src, each learned the hard way (docs/BLUEPRINT.md, section 6.5). (name, pattern, why, files exempt from it)
FRONTEND_RULES: list[tuple[str, re.Pattern[str], str, tuple[str, ...]]] = [
    (
        "no-float-money",
        re.compile(r"parseFloat\(|\.toFixed\(|Intl\.NumberFormat|toLocaleString\("),
        "money, prices and lot sizes go through src/lib/decimal.ts (exact bigint decimals), never a float or the locale formatter",
        (),
    ),
    (
        "links-via-pressablelink",
        re.compile(r"\basChild\b"),
        "navigating pressables go through PressableLink in src/ui/controls.tsx: expo-router's Slot merges `style` with an object spread, "
        "which turns an array or function style into garbage in a production build and crashes the page",
        ("src/ui/controls.tsx",),
    ),
    ("no-alert", re.compile(r"\bAlert\.alert\b"), "Alert.alert does nothing on the web; use ConfirmDialog", ()),
    ("no-console", re.compile(r"\bconsole\.\w+"), "the app reports problems in the UI; a stray console call hides a bug or breaks the clean-run rule", ()),
]
# Proxies must never sit between the harness and its own loopback server.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class HarnessError(Exception):
    """The environment is unusable (exit code 2)."""


@dataclass
class Gate:
    name: str
    ok: bool
    detail: str


@dataclass
class Server:
    proc: subprocess.Popen
    base_url: str
    out: Any
    err: Any
    directory: Path
    stack: Any = None  # a ComposeStack, when the server is a container
    container: str = ""
    service: str = ""


# --- small helpers -------------------------------------------------------------------------------


def say(text: str = "") -> None:
    sys.stdout.write(text.encode("ascii", "replace").decode("ascii") + "\n")
    sys.stdout.flush()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def write_text_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


class HarnessLog:
    """The harness's own records (source=harness), merged into the phase log at the end."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def add(self, level: str, msg: str, **fields: Any) -> None:
        self.records.append({"ts": utc_now(), "source": "harness", "level": level, "msg": msg, **fields})


# --- pure gate logic (exercised by --self-test) --------------------------------------------------


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8000]


def find_cr_files(root: Path, relative_paths: list[str]) -> list[str]:
    """Text files containing a carriage return. Binary and missing files are skipped."""
    bad = []
    for relative in relative_paths:
        try:
            data = (root / relative).read_bytes()
        except OSError:
            continue
        if not is_binary(data) and b"\r" in data:
            bad.append(relative)
    return bad


def scan_log_errors(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Error-level records from the server, the browser or the feed stub. Test failures are covered by pytest itself."""
    return [r for r in records if r.get("level") == "error" and r.get("source") in ("server", "client", "stub")]


def secret_values(env: Any) -> list[str]:
    names = [name.strip() for name in env.get("REDACT_ENV", "GCAL_ICAL_URL").split(",") if name.strip()]
    return [value for value in (env.get(name, "") for name in names) if len(value) >= 8]


def _forms(secret: str) -> list[str]:
    return [secret, json.dumps(secret)[1:-1]]  # as typed, and as it appears inside a JSON string


def find_secret_leaks(text: str, secrets: list[str]) -> list[str]:
    leaks = [f"value of a REDACT_ENV variable ({len(secret)} chars)" for secret in secrets if any(f in text for f in _forms(secret))]
    if ICAL_TOKEN.search(text):
        leaks.append("Google iCal private token pattern")
    return leaks


def mask_secrets(text: str, secrets: list[str]) -> str:
    for secret in sorted(secrets, key=len, reverse=True):
        for form in _forms(secret):
            text = text.replace(form, MASK)
    return ICAL_TOKEN.sub(MASK, text)


def check_screenshots(directory: Path, since: float) -> tuple[bool, str]:
    good = 0
    if directory.is_dir():
        for path in directory.glob("*.png"):
            stat = path.stat()
            if stat.st_size > len(PNG_SIGNATURE) and stat.st_mtime >= since and path.read_bytes()[:8] == PNG_SIGNATURE:
                good += 1
    return good >= 1, f"{good} valid PNG(s) written this run"


def unexpected_changes(before: set[str], after: set[str]) -> list[str]:
    """Entries of `git status --porcelain` that appeared or vanished outside logs/ and artifacts/."""
    changed = before ^ after
    return sorted(entry for entry in changed if not entry[3:].replace("\\", "/").startswith(ALLOWED_WRITE_PREFIXES))


def is_harness(record: dict[str, Any]) -> bool:
    return str(record.get("request_id", "")).startswith(HARNESS_ID_PREFIX)


def is_web(record: dict[str, Any]) -> bool:
    return str(record.get("request_id", "")).startswith(WEB_ID_PREFIX)


def is_poll(record: dict[str, Any]) -> bool:
    return str(record.get("request_id", "")).startswith(POLL_ID_PREFIX)


def is_probe(record: dict[str, Any]) -> bool:
    return record.get("request_id") == HEALTHCHECK_ID


def is_timing_dependent(record: dict[str, Any]) -> bool:
    """Records whose number depends on timing, not on what the tests did: the app's own requests (refetches and
    polling), the browser's logged view of them, the browser's navigation events, and a test's polls while it waits
    for a background sync, and the container's own healthcheck probes. The app's are counted as operations under `ui`,
    never as volume. A navigation event is timing-dependent because the app's own navigation after a form submit is
    superseded when the test moves on first (one test's count was 10 or 11 from run to run, nothing else differed). A
    probe is timing-dependent because one arrives every 10 s the container lives (a 20 s server logged 2 or 3)."""
    if record.get("source") == "client" and record.get("msg") in ("api_response", "navigated"):
        return True
    if record.get("source") == "test" and record.get("msg") == "api_request":
        return is_poll(record)
    return record.get("source") == "server" and record.get("msg") == "request" and (is_web(record) or is_poll(record) or is_probe(record))


def request_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Server `request` records caused by tests or the browser, not by the harness's own probes or the container's."""
    return [r for r in records if r.get("source") == "server" and r.get("msg") == "request" and not is_harness(r) and not is_probe(r)]


def write_requests(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in request_records(records) if r.get("method") in WRITE_METHODS and 200 <= int(r.get("status", 0)) < 300]


def operations_of(schema: dict[str, Any]) -> list[tuple[str, str, re.Pattern[str], int]]:
    """(METHOD, path template, matcher for concrete paths, phase) for every operation in an OpenAPI document. The phase
    is the operation's `x-phase` extension: the phase that introduced it, 1 when it has none."""
    operations = []
    for path, item in schema.get("paths", {}).items():
        parts = [part for part in re.split(r"(\{[^}/]+\})", path) if part]
        matcher = re.compile("^" + "".join("[^/]+" if part.startswith("{") else re.escape(part) for part in parts) + "$")
        for method in HTTP_METHODS:
            if method in item:
                operations.append((method.upper(), path, matcher, int(item[method].get("x-phase", 1))))
    return operations


def api_coverage(schema: dict[str, Any], records: list[dict[str, Any]], only_web: bool = False, phase: int | None = None) -> tuple[list[str], list[str]]:
    """Operations that answered 2xx at least once, and those that never did. `only_web` counts only requests
    the app's own API client made (their IDs start with "web-"), which is what proves the UI reaches them. `phase`
    leaves out operations a later phase introduced, so verifying phase 2 does not demand the connectors' endpoints.
    An operation with no `x-phase` belongs to phase 1, so phase 0 is asked for what phase 1 is (its metrics have always listed them)."""
    answered = [(r["method"], r["path"]) for r in request_records(records) if 200 <= int(r.get("status", 0)) < 300 and (is_web(r) or not only_web)]
    exercised, uncovered = [], []
    for method, path, matcher, introduced in operations_of(schema):
        if phase is not None and introduced > max(phase, 1):
            continue
        hit = any(m == method and matcher.match(p) for m, p in answered)
        (exercised if hit else uncovered).append(f"{method} {path}")
    return exercised, uncovered


def ui_coverage(schema: dict[str, Any], records: list[dict[str, Any]], phase: int | None = None) -> tuple[list[str], list[str]]:
    return api_coverage(schema, records, only_web=True, phase=phase)


def feed_syncs(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r.get("source") == "server" and r.get("msg") == "feed_sync"]


def check_feed_traffic(server: list[dict[str, Any]], stub: list[dict[str, Any]], allowed: tuple[str, ...] = LOOPBACK) -> tuple[bool, str]:
    """The run was offline: the app was started in fixture mode, every feed sync it logged went to a loopback host, and
    the stub (which listens on loopback only) is where it asked. Without a sync of each feed the claim is empty."""
    syncs = feed_syncs(server)
    problems = []
    modes = {r.get("mode") for r in server if r.get("msg") == "feeds_started"}
    if modes != {"fixture"}:
        problems.append(f"the app was started in feed mode {sorted(map(str, modes)) or 'none'}, not fixture")
    outside = sorted({str(r.get("host")) for r in syncs if r.get("host") not in allowed})
    if outside:
        problems.append("feed syncs went to " + ", ".join(outside))
    for feed in ("forexfactory", "gcal"):
        if not any(r.get("feed") == feed for r in syncs):
            problems.append(f"no sync of {feed}")
    served = [r for r in stub if r.get("msg") == "stub_request" and r.get("feed") in ("forexfactory", "gcal")]
    agents = {str(r.get("user_agent")) for r in served}
    if not served:
        problems.append("the stub saw no feed requests")
    elif not all(a.startswith("TradingJournal/") for a in agents):
        problems.append("a request did not identify itself as TradingJournal: " + ", ".join(sorted(agents)))
    if problems:
        return False, "; ".join(problems)
    where = "loopback" if allowed == LOOPBACK else "the stub container"
    return True, f"{len(syncs)} syncs, all to {where}; the stub served {len(served)} feed requests; fixture mode"


def check_secret_registered(secrets: Iterable[str], address: str) -> tuple[bool, str]:
    """The calendar address must be among the secrets the leak gate scans for. Without that, `no-secret-leaks` would say
    nothing about the one secret the app holds, and a run could pass with the address spread through the log."""
    if not address:
        return False, "the run had no calendar address, so there was nothing to protect and nothing proved"
    if address not in secrets:
        return False, "the calendar address was not among the secrets the leak gate scans for"
    return True, "the calendar address is among the secrets the leak gate scans for"


def check_feed_paths(server: list[dict[str, Any]]) -> tuple[bool, str]:
    """Every outcome in FEED_OUTCOMES happened at least once for its feed, so the throttle, bad-content and outage
    paths were exercised in this run, not just assumed."""
    seen: dict[str, set[str]] = {}
    for record in feed_syncs(server):
        seen.setdefault(str(record.get("feed")), set()).add(str(record.get("outcome")))
    missing = [f"{feed}: {', '.join(sorted(set(wanted) - seen.get(feed, set())))}" for feed, wanted in FEED_OUTCOMES.items() if set(wanted) - seen.get(feed, set())]
    if missing:
        return False, "never seen: " + "; ".join(missing)
    return True, "; ".join(f"{feed} {', '.join(wanted)}" for feed, wanted in FEED_OUTCOMES.items())


def feed_metrics(server: list[dict[str, Any]]) -> dict[str, Any]:
    """What the run's syncs amounted to, by feed and outcome. None of it depends on timing: syncs happen when a test asks."""
    syncs = feed_syncs(server)
    outcomes: dict[str, Counter] = {}
    for record in syncs:
        outcomes.setdefault(str(record.get("feed")), Counter())[str(record.get("outcome"))] += 1
    return {
        "syncs": {feed: dict(sorted(counts.items())) for feed, counts in sorted(outcomes.items())},
        "triggers": dict(sorted(Counter(str(r.get("trigger")) for r in syncs).items())),
        "hosts": sorted({str(r.get("host")) for r in syncs}),
    }


def correlate_network(client: list[dict[str, Any]], server: list[dict[str, Any]]) -> tuple[int, int, list[str]]:
    """Each API response the browser logged must be one the server logged too, with the same request ID, method,
    path and status. A response that carries no echoed request ID never came from the server (a test mocked it).
    Returns (matched, mocked, problems)."""
    served = {(r.get("request_id"), r.get("method"), r.get("path"), int(r.get("status", 0))) for r in server if r.get("msg") == "request"}
    matched = mocked = 0
    problems: list[str] = []
    for record in client:
        if record.get("msg") != "api_response":
            continue
        if not record.get("echoed_id"):
            mocked += 1
            continue
        key = (record["echoed_id"], record.get("method"), record.get("path"), int(record.get("status", 0)))
        if key in served:
            matched += 1
        else:
            problems.append(f"{key[1]} {key[2]} -> {key[3]} ({key[0]}): seen by the browser, not logged by the server")
    return matched, mocked, problems


def parse_node_test_summary(output: str) -> tuple[int, int] | None:
    """(passed, failed) from the node:test summary, in its spec form ("<info sign> pass 49") or TAP form ("# pass 49")."""
    counts = {name: int(m.group(1)) for name in ("pass", "fail") if (m := re.search(rf"^[\u2139#]\s+{name}\s+(\d+)\s*$", output, re.M))}
    return (counts["pass"], counts["fail"]) if len(counts) == 2 else None


def contract_in_sync(generated: str, committed: str) -> bool:
    """Whether the checked-in API types equal what the running server's schema generates, ignoring line endings."""

    def normal(text: str) -> str:
        return text.replace("\r\n", "\n").rstrip("\n")

    return normal(generated) == normal(committed)


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"(?<!:)//[^\n]*", "", text)


def scan_frontend_sources(files: dict[str, str]) -> list[str]:
    """Rule violations in frontend source files, keyed by path relative to frontend/ (for example "src/ui/data.tsx")."""
    problems = []
    for name, text in sorted(files.items()):
        code = _strip_comments(text)
        for rule, pattern, _why, exempt in FRONTEND_RULES:
            if name in exempt:
                continue
            for number, line in enumerate(code.splitlines(), 1):
                if pattern.search(line):
                    problems.append(f"{name}:{number} [{rule}]")
    return problems


def uncommitted_writes(records: list[dict[str, Any]]) -> list[str]:
    """Successful write requests with no `db_transaction` commit record carrying the same request ID."""
    committed = {r.get("request_id") for r in records if r.get("msg") == "db_transaction" and r.get("outcome") == "commit"}
    return [f"{r['method']} {r['path']} ({r.get('request_id')})" for r in write_requests(records) if r.get("request_id") not in committed]


def rollbacks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r.get("msg") == "db_transaction" and r.get("outcome") == "rollback"]


def normalize(record: Any, default_source: str, fallback_ts: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        record = {"msg": str(record)}
    record.setdefault("ts", fallback_ts)
    record.setdefault("source", default_source)
    record.setdefault("level", "info")
    record.setdefault("msg", "")
    return record


def parse_server_output(stdout: str, stderr: str, fallback_ts: str) -> list[dict[str, Any]]:
    """JSON lines stay as they are. Stray stdout lines become info, any stderr line becomes an error."""
    records: list[dict[str, Any]] = []
    last_ts = fallback_ts
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            record = normalize(json.loads(line), "server", last_ts)
        except json.JSONDecodeError:
            record = {"ts": last_ts, "source": "server", "level": "info", "msg": line.strip()}
        last_ts = record["ts"]
        records.append(record)
    for line in stderr.splitlines():
        if line.strip():
            records.append({"ts": last_ts, "source": "server", "level": "error", "msg": line.rstrip(), "stream": "stderr"})
    return records


def read_jsonl(path: Path, default_source: str, fallback_ts: str) -> list[dict[str, Any]]:
    records = []
    for line in read_text(path).splitlines():
        if not line.strip():
            continue
        try:
            records.append(normalize(json.loads(line), default_source, fallback_ts))
        except json.JSONDecodeError:
            records.append({"ts": fallback_ts, "source": default_source, "level": "warning", "msg": line.strip()})
    return records


def merge_records(harness: list[dict[str, Any]], *streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable sort by timestamp, with run_start pinned first and run_end pinned last."""
    first = [r for r in harness if r["msg"] == "run_start"]
    last = [r for r in harness if r["msg"] == "run_end"]
    middle = [r for r in harness if r["msg"] not in ("run_start", "run_end")]
    for stream in streams:
        middle.extend(stream)
    middle.sort(key=lambda r: r["ts"])
    return first + middle + last


def render(records: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(record, default=str) + "\n" for record in records)


def summarize_tests(records: list[dict[str, Any]]) -> dict[str, str]:
    """Final outcome per test: any failed phase (setup, call or teardown) makes it failed."""
    result: dict[str, str] = {}
    for record in records:
        if record.get("source") != "test" or record.get("msg") != "test_report":
            continue
        node, outcome = record["test"], record["outcome"]
        if outcome == "failed":
            result[node] = "failed"
        elif result.get(node) != "failed" and (record.get("when") == "call" or outcome == "skipped"):
            result[node] = outcome
    return result


def compute_metrics(
    *,
    phase: int,
    backend: str,
    outcomes: dict[str, str],
    unit_summary: str,
    exercised: list[str],
    uncovered: list[str],
    server_records: list[dict[str, Any]],
    e2e_records: list[dict[str, Any]],
    gates: list[Gate],
    restarts_survived: int,
    frontend: dict[str, Any] | None = None,
    ui: dict[str, Any] | None = None,
    feeds: dict[str, Any] | None = None,
    container: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The validation summary written to artifacts/phase_N/metrics.json. Nothing in it depends on timing, so the
    app's own requests (how many a page makes depends on timing) are counted under `ui`, as operations, not volume."""
    requests = [r for r in request_records(server_records) if not is_web(r) and not is_poll(r)]
    transactions = [r for r in server_records if r.get("msg") == "db_transaction"]
    by_marker = Counter(m.group(1) for node in outcomes if (m := re.search(r"tests/(p\d)_", node)))
    extra: dict[str, Any] = {}
    if frontend is not None:
        extra["frontend"] = frontend
    if ui is not None:
        extra["ui"] = ui
    if feeds is not None:
        extra["feeds"] = feeds
    if container is not None:
        extra["container"] = container
    return {
        "phase": phase,
        "backend": backend,
        "result": "pass" if all(gate.ok for gate in gates) else "fail",
        "tests": {
            "passed": sum(1 for value in outcomes.values() if value == "passed"),
            "failed": sum(1 for value in outcomes.values() if value == "failed"),
            "skipped": sum(1 for value in outcomes.values() if value == "skipped"),
            "by_marker": dict(sorted(by_marker.items())),
        },
        "unit_tests": re.sub(r"\s+in\s+[0-9.]+s.*$", "", unit_summary),  # the summary's wall-clock time is dropped
        "api": {
            "operations": len(exercised) + len(uncovered),
            "exercised": len(exercised),
            "uncovered": uncovered,
            "requests_by_status_class": dict(sorted(Counter(f"{int(r['status']) // 100}xx" for r in requests).items())),
        },
        "database": {
            "commits": sum(1 for t in transactions if t.get("outcome") == "commit"),
            "rollbacks": sum(1 for t in transactions if t.get("outcome") == "rollback"),
            "statements": sum(int(t.get("statements", 0)) for t in transactions),
            "writes": sum(int(t.get("writes", 0)) for t in transactions),
            "write_requests_committed": len(write_requests(server_records)) - len(uncommitted_writes(server_records)),
            "server_restarts_survived": restarts_survived,
        },
        "journal_events": dict(sorted(Counter(r["msg"] for r in server_records if r.get("logger") == "app.journal").items())),
        "log_records": dict(sorted(Counter(r["source"] for r in server_records + e2e_records if not is_timing_dependent(r)).items())),
        "gates": {gate.name: gate.ok for gate in gates},
        **extra,
    }


# --- environment ---------------------------------------------------------------------------------


def resolve_python(explicit: Path | None) -> Path:
    if explicit:
        return explicit
    for candidate in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def tool_versions(py: Path) -> dict[str, Any]:
    code = (
        "import importlib.metadata as m, json, platform\n"
        "out = {'python': platform.python_version()}\n"
        f"for name in {list(REQUIRED_PACKAGES)!r}:\n"
        "    try:\n"
        "        out[name] = m.version(name)\n"
        "    except m.PackageNotFoundError:\n"
        "        out[name] = None\n"
        "print(json.dumps(out))\n"
    )
    result = subprocess.run([str(py), "-c", code], capture_output=True, text=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise HarnessError(f"cannot run {py}: {result.stderr.strip() or 'no output'}\n{SETUP_HINT}") from None


def check_packages(versions: dict[str, Any]) -> None:
    missing = [name for name in REQUIRED_PACKAGES if not versions.get(name)]
    if missing:
        raise HarnessError("missing in the dev venv: " + ", ".join(missing) + "\n" + SETUP_HINT)


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True)


def git_rev() -> str:
    result = git("rev-parse", "--short", "HEAD")
    return result.stdout.decode().strip() if result.returncode == 0 else "no-commits"


def list_repo_files() -> list[str]:
    result = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if result.returncode != 0:
        raise HarnessError("git ls-files failed: " + result.stderr.decode("utf-8", "replace").strip())
    return sorted({p for p in result.stdout.decode("utf-8", "surrogateescape").split("\0") if p})


def repo_snapshot() -> set[str]:
    result = git("status", "--porcelain", "--untracked-files=all", "-z")
    if result.returncode != 0:
        raise HarnessError("git status failed: " + result.stderr.decode("utf-8", "replace").strip())
    return {entry for entry in result.stdout.decode("utf-8", "surrogateescape").split("\0") if entry}


def static_dir_for(phase: int, run_dir: Path) -> Path:
    """The folder the server serves at /. Until Phase 2 that is the stub page; from then on the run builds the
    Expo web export into its own folder, so a stale build can never stand in for the current source."""
    return STUB_WEB if phase < FRONTEND_FROM else run_dir / "web-dist"


# --- guards --------------------------------------------------------------------------------------


def gate_line_endings() -> Gate:
    bad = find_cr_files(ROOT, list_repo_files())
    if not bad:
        return Gate("lf-endings", True, "no CRLF in any non-ignored text file")
    return Gate("lf-endings", False, "CRLF found in: " + ", ".join(bad[:10]) + (" ..." if len(bad) > 10 else ""))


def gate_playwright_pin(installed: dict[str, Any]) -> Gate:
    match = re.search(r"^playwright==([0-9.]+)", read_text(E2E / "requirements.txt"), re.M)
    if not match:
        return Gate("playwright-pin", False, "e2e/requirements.txt has no playwright== pin")
    pinned = match.group(1)
    problems = []
    if installed.get("playwright") != pinned:
        problems.append(f"pinned {pinned} but {installed.get('playwright')} is installed")
    dockerfile = E2E / "Dockerfile"
    if dockerfile.exists():
        tag = re.search(r"playwright/python:v([0-9.]+)", read_text(dockerfile))
        if not tag or tag.group(1) != pinned:
            problems.append(f"e2e/Dockerfile image tag is {tag.group(1) if tag else 'missing'}")
    note = "Dockerfile checked" if dockerfile.exists() else "no e2e/Dockerfile yet"
    return Gate("playwright-pin", not problems, "; ".join(problems) or f"{pinned} installed and pinned ({note})")


# --- processes -----------------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def harness_get(url: str, request_id: str, timeout: float = 5.0) -> bytes:
    request = urllib.request.Request(url, headers={"X-Request-ID": HARNESS_ID_PREFIX + request_id})
    with _OPENER.open(request, timeout=timeout) as response:
        return response.read()


def wait_ready(server: Server, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.proc.poll() is not None:
            raise HarnessError(f"server exited early with code {server.proc.returncode}; see {server.directory}")
        try:
            harness_get(f"{server.base_url}/api/ready", "ready", timeout=2)  # 200 only once the schema is at head
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    raise HarnessError(f"server did not become ready within {timeout:.0f}s; see {server.directory}")


def fetch_openapi(server: Server) -> dict[str, Any]:
    try:
        return json.loads(harness_get(f"{server.base_url}/api/openapi.json", "openapi"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"could not fetch the OpenAPI schema: {exc}") from None


def stop_server(server: Server | None) -> int | None:
    if server is None:
        return None
    if server.stack is not None:
        return stop_compose_service(server)
    proc = server.proc
    if proc.poll() is None:
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)  # uvicorn shuts down gracefully and logs it
            else:
                proc.terminate()
            proc.wait(timeout=8)
        except (subprocess.TimeoutExpired, OSError):
            proc.kill()
            proc.wait(timeout=5)
    server.out.close()
    server.err.close()
    return proc.returncode


def start_server(
    py: Path,
    directory: Path,
    port: int,
    env_extra: dict[str, str],
    app: str = "app.main:app",
    app_dir: Path | None = None,
) -> Server:
    directory.mkdir(parents=True, exist_ok=True)
    base_url = f"http://127.0.0.1:{port or free_port()}"
    env = {
        **os.environ,
        "APP_ENV": "test",
        "LOG_LEVEL": "INFO",
        "APP_TIMEZONE": VERIFY_TIMEZONE,
        "DATABASE_URL": "sqlite:///" + (directory / "journal.db").as_posix(),
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        **env_extra,
    }
    command = [str(py), "-m", "uvicorn", app, "--host", "127.0.0.1", "--port", base_url.rsplit(":", 1)[1], "--log-config", "log_config.json"]
    if app_dir:
        command += ["--app-dir", str(app_dir)]
    out = open(directory / "server.out", "wb")
    err = open(directory / "server.err", "wb")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    server = Server(subprocess.Popen(command, cwd=BACKEND, env=env, stdout=out, stderr=err, creationflags=flags), base_url, out, err, directory)
    try:
        wait_ready(server)
    except HarnessError:
        stop_server(server)
        raise
    return server


def start_stub(py: Path, directory: Path, port: int) -> Server:
    """The feed stub (e2e/support/feed_stub.py): both hosts, from the static files in fixtures/, on loopback."""
    directory.mkdir(parents=True, exist_ok=True)
    out = open(directory / "server.out", "wb")
    err = open(directory / "server.err", "wb")
    command = [str(py), str(FEED_STUB), "--port", str(port), "--fixtures", str(FIXTURES), "--log", str(directory.parent / "feed-stub.jsonl"), "--gcal-token", GCAL_TOKEN]
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    stub = Server(subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err, creationflags=flags), f"http://127.0.0.1:{port}", out, err, directory)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if stub.proc.poll() is not None:
            stop_server(stub)
            raise HarnessError(f"the feed stub exited early with code {stub.proc.returncode}; see {directory}")
        try:
            harness_get(f"{stub.base_url}/__state", "stub", timeout=2)
            return stub
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    stop_server(stub)
    raise HarnessError(f"the feed stub did not answer within 15s; see {directory}")


def run_pytest(py: Path, cwd: Path, args: list[str], env: dict[str, str], transcript: Path) -> tuple[int, str]:
    """Runs pytest, echoing its output and keeping a transcript. Returns (exit code, summary line)."""
    return stream_command([str(py), "-m", "pytest", *args], cwd, {**os.environ, "PYTHONIOENCODING": "utf-8", **env}, transcript)


def stream_command(command: list[str], cwd: Path, full_env: dict[str, str], transcript: Path) -> tuple[int, str]:
    """Runs a command whose output is pytest's, echoing it and keeping a transcript. Returns (exit code, summary line)."""
    transcript.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    with open(transcript, "w", encoding="utf-8", newline="\n") as sink:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sink.write(line)
            say(line.rstrip("\r\n"))
            lines.append(line.strip("= \r\n"))
        code = proc.wait()
    summary = next((line for line in reversed(lines) if line), "no output")
    return code, summary


def e2e_env(base_url: str, phase: int, log_file: Path, artifacts: Path) -> dict[str, str]:
    return {"BASE_URL": base_url, "VERIFY_PHASE": str(phase), "E2E_LOG_FILE": str(log_file), "ARTIFACTS_DIR": str(artifacts)}


def run_e2e(py: Path, markers: str, server: Server, phase: int, run_dir: Path, phase_dir: Path, stage: str, extra_env: dict[str, str] | None = None) -> tuple[int, str]:
    if server.stack is not None:
        return run_e2e_in_stack(markers, server, phase, run_dir, stage, extra_env)
    args = ["-m", markers, "--output", str(phase_dir / "traces" / stage), "--tracing", "retain-on-failure", "--screenshot", "only-on-failure"]
    env = {**e2e_env(server.base_url, phase, run_dir / "e2e.jsonl", ARTIFACTS), **(extra_env or {})}
    return run_pytest(py, E2E, args, env, run_dir / f"pytest-e2e-{stage}.txt")


# --- the compose backend (Phase 4) ---------------------------------------------------------------
#
# The same verification, with the app, the feed stub and the test runner each in a container: the production image
# built from docker/app.Dockerfile, the stack of docker-compose.yml plus docker/compose.verify.yml, Playwright's own
# image running the suite over the compose network. The gates, the log merge and the metrics are shared with the
# native backend; what differs is how the stack is built, started, restarted and read, and a handful of gates
# about the container itself.

COMPOSE_BASE = ROOT / "docker-compose.yml"
COMPOSE_VERIFY = ROOT / "docker" / "compose.verify.yml"
COMPOSE_SMOKE = ROOT / "docker" / "compose.smoke.yml"
IMAGE_TAG = "verify"  # the images a run builds and verifies, never the `local` ones a person runs
APP_IMAGE = f"tradingjournal/app:{IMAGE_TAG}"
STUB_HOST = "feedstub"  # the stub's service name: the one non-loopback host fixture mode is told to accept
STUB_PORT = 8765
SMOKE_FROM = 4  # from this phase on, a compose run also smoke-tests the production definition itself
# The settings of a run that reach the compose files by interpolation (docker/compose.verify.yml): the same values the
# native backend hands the server, so the two backends are configured from one place.
COMPOSE_SETTINGS = ("FEEDS_MODE", "FF_FEED_URL", "GCAL_ICAL_URL", "APP_NOW_OVERRIDE", "SYNC_COOLDOWN_SECONDS", "FF_POLL_MINUTES", "GCAL_POLL_MINUTES", "FEED_TICK_SECONDS", "FEED_TIMEOUT_SECONDS")
CLOCK_SKEW_ALLOWED = 300  # seconds: the Docker VM's clock and the host's may differ a little, and file times come from the VM

# What the app's container is asked, from inside, once the suite has run. It reports facts; the gates judge them.
CONTAINER_PROBE = r"""
import json, os, sqlite3
out = {"uid": os.getuid(), "gid": os.getgid(), "writable": {}}
for path in ("/app/probe", "/etc/probe", "/usr/probe", "/data/probe", "/tmp/probe"):
    try:
        open(path, "w").close()
        os.unlink(path)
        out["writable"][path] = True
    except OSError:
        out["writable"][path] = False
status = open("/proc/self/status").read()
out["cap_eff"] = status.split("CapEff:")[1].split()[0]
out["no_new_privs"] = status.split("NoNewPrivs:")[1].split()[0] == "1"
out["pid1"] = open("/proc/1/cmdline", "rb").read().replace(b"\0", b" ").decode().strip()
try:
    db = sqlite3.connect("file:/data/tj.db?mode=ro", uri=True)
    out["journal_mode"] = db.execute("PRAGMA journal_mode").fetchone()[0]
    out["tables"] = sorted(row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'"))
    db.close()
    out["db_bytes"] = os.path.getsize("/data/tj.db")
except Exception as error:
    out["db_error"] = type(error).__name__
print(json.dumps(out))
"""

# What the image holds, asked of a throwaway container of it: a runtime image carries no build tools, no tests, no secrets.
IMAGE_PROBE = r"""
import importlib.util, json, os, shutil, sys
out = {
    "python": sys.version.split()[0],
    "tools": {name: bool(shutil.which(name)) for name in ("node", "npm", "npx", "gcc", "cc", "make", "git", "curl", "uv")},
    "modules": {name: importlib.util.find_spec(name) is not None for name in ("pytest", "playwright", "uv")},
    "paths": {path: os.path.exists(path) for path in ("/app/tests", "/app/requirements-dev.txt", "/app/.env", "/app/.git", "/app/node_modules", "/app/frontend")},
    "web_index": os.path.isfile("/app/web/index.html"),
    "web_files": sum(len(files) for _, _, files in os.walk("/app/web")),
    "swagger": os.path.isdir("/app/app/static/swagger"),
}
print(json.dumps(out))
"""


class ComposeStack:
    """One docker compose project: the app, the feed stub (from Phase 3) and, on demand, the test runner."""

    def __init__(self, project: str, files: list[Path], env: dict[str, str]) -> None:
        self.project = project
        self.env = dict(env)
        self.base = ["docker", "compose", "-p", project, *[arg for path in files for arg in ("-f", str(path))]]

    def command(self, *args: str, profiles: str | None = None) -> list[str]:
        return [*self.base, *(["--profile", profiles] if profiles else []), *args]

    def process_env(self) -> dict[str, str]:
        return {**os.environ, "PYTHONIOENCODING": "utf-8", **self.env}

    def run(self, *args: str, timeout: float = 900, check: bool = True, profiles: str | None = None) -> subprocess.CompletedProcess:
        try:
            result = subprocess.run(
                self.command(*args, profiles=profiles), cwd=ROOT, env=self.process_env(), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
            )
        except subprocess.TimeoutExpired:
            raise HarnessError(f"docker compose {' '.join(args)} did not finish within {timeout:.0f}s") from None
        if check and result.returncode != 0:
            raise HarnessError(f"docker compose {' '.join(args)} failed with {result.returncode}: {tail(result.stdout + result.stderr, 15)}")
        return result

    def container_of(self, service: str) -> str:
        found = self.run("ps", "-a", "-q", service, check=False).stdout.split()
        if not found:
            raise HarnessError(f"compose has no container for {service}")
        return found[0]

    def inspect(self, container: str) -> dict[str, Any]:
        return json.loads(docker("inspect", container).stdout)[0]

    def exec_python(self, container: str, code: str) -> dict[str, Any]:
        result = docker("exec", container, "python", "-c", code, check=False)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            raise HarnessError(f"the probe inside {container} said nothing usable: {tail(result.stdout + result.stderr, 6)}") from None

    def logs_of(self, container: str) -> tuple[str, str]:
        result = docker("logs", container, check=False)
        return result.stdout, result.stderr

    def clock_of(self, container: str) -> str:
        """The container's own clock as an ISO instant: the Docker VM's, which stamps the records the container writes."""
        result = docker("exec", container, "python", "-c", "import datetime; print(datetime.datetime.now(datetime.timezone.utc).isoformat())", check=False)
        return result.stdout.strip()

    def exec_python_in_image(self, image: str, code: str) -> dict[str, Any]:
        result = docker("run", "--rm", "--entrypoint", "python", image, "-c", code, check=False)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            raise HarnessError(f"the probe of image {image} said nothing usable: {tail(result.stdout + result.stderr, 6)}") from None

    def down(self, volumes: bool = True) -> None:
        self.run("down", *(["--volumes"] if volumes else []), "--remove-orphans", check=False, timeout=180, profiles="*")


def docker(*args: str, check: bool = True, timeout: float = 300) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError:
        raise HarnessError("docker is not on PATH. Install Docker Desktop (docs/BLUEPRINT.md, section 9)") from None
    except subprocess.TimeoutExpired:
        raise HarnessError(f"docker {' '.join(args[:2])} did not finish within {timeout:.0f}s") from None
    if check and result.returncode != 0:
        raise HarnessError(f"docker {' '.join(args[:2])} failed with {result.returncode}: {tail(result.stdout + result.stderr, 10)}")
    return result


def docker_versions() -> dict[str, Any]:
    server = docker("version", "--format", "{{.Server.Version}}", check=False)
    if server.returncode != 0 or not server.stdout.strip():
        raise HarnessError("the Docker engine is not answering: start Docker Desktop and wait for it to say it is running\n" + tail(server.stderr, 4))
    compose = docker("compose", "version", "--short", check=False)
    return {"docker": server.stdout.strip(), "compose": compose.stdout.strip() or None}


def image_facts(image: str) -> dict[str, Any]:
    info = json.loads(docker("image", "inspect", image).stdout)[0]
    return {"image": image, "id": info["Id"], "size_mb": round(info["Size"] / 1_000_000, 1), "created": info["Created"], "user": info["Config"].get("User"), "base": info["Config"].get("Labels") or {}}


def start_compose_service(stack: ComposeStack, service: str, directory: Path, base_url: str) -> Server:
    directory.mkdir(parents=True, exist_ok=True)
    stack.run("up", "--detach", "--wait", "--wait-timeout", "180", service, timeout=420)
    return Server(None, base_url, None, None, directory, stack=stack, container=stack.container_of(service), service=service)  # type: ignore[arg-type]


def stop_compose_service(server: Server) -> int | None:
    """A graceful stop (the container's stop signal, then the grace period), its logs written where the native backend's
    server output goes, and for the app its container removed: a restart is a new container on the same volume."""
    stack = server.stack
    assert stack is not None
    stack.run("stop", server.service, check=False, timeout=120)
    exit_code: int | None
    try:
        exit_code = int(stack.inspect(server.container)["State"]["ExitCode"])
    except (HarnessError, KeyError, ValueError):
        exit_code = None
    out, err = stack.logs_of(server.container)
    write_text_lf(server.directory / "server.out", out)
    write_text_lf(server.directory / "server.err", err)
    if server.service == "app":
        stack.run("rm", "--force", server.service, check=False)
    return exit_code


def run_e2e_in_stack(markers: str, server: Server, phase: int, run_dir: Path, stage: str, extra_env: dict[str, str] | None) -> tuple[int, str]:
    """The suite, in Playwright's container, over the compose network. Its logs and screenshots reach the host through the
    two bind mounts, where the native backend writes them: logs/_run/phase_N and artifacts/phase_N."""
    stack = server.stack
    assert stack is not None
    flags = [flag for name, value in (extra_env or {}).items() for flag in ("-e", f"{name}={value}")]
    pytest_args = ["-m", markers, "--output", f"/artifacts/phase_{phase}/traces/{stage}", "--tracing", "retain-on-failure", "--screenshot", "only-on-failure"]
    command = stack.command("run", "--rm", "--no-deps", "-T", *flags, "e2e", "python", "-m", "pytest", *pytest_args)
    return stream_command(command, ROOT, stack.process_env(), run_dir / f"pytest-e2e-{stage}.txt")


def collect_container_facts(stack: ComposeStack, server: Server) -> dict[str, Any]:
    """What the running app container is, as Docker reports it, and what it can do, as it reports itself."""
    info = stack.inspect(server.container)
    host, state, config = info["HostConfig"], info["State"], info["Config"]
    health = state.get("Health") or {}
    return {
        "id": info["Id"],
        "image": info["Image"],
        "user": config.get("User"),
        "healthcheck": (config.get("Healthcheck") or {}).get("Test") or [],
        "health": health.get("Status"),
        "failing_streak": health.get("FailingStreak"),
        "restart_count": info.get("RestartCount"),
        "read_only": bool(host.get("ReadonlyRootfs")),
        "cap_drop": [str(cap).upper() for cap in host.get("CapDrop") or []],
        "security_opt": host.get("SecurityOpt") or [],
        "init": bool(host.get("Init")),
        "memory": host.get("Memory"),
        "pids": host.get("PidsLimit"),
        "ports": [binding.get("HostIp") for bindings in (host.get("PortBindings") or {}).values() for binding in bindings or []],
        "mounts": [{"type": mount.get("Type"), "name": mount.get("Name"), "destination": mount.get("Destination")} for mount in info.get("Mounts") or []],
        "tmpfs": sorted((host.get("Tmpfs") or {}).keys()),
        "probe": stack.exec_python(server.container, CONTAINER_PROBE),
    }


def check_container_health(facts: dict[str, Any]) -> tuple[bool, str]:
    """The container reports itself healthy through a check that asks /api/health, and nothing restarted it."""
    problems = []
    if facts.get("health") != "healthy":
        problems.append(f"health is {facts.get('health')}")
    command = " ".join(str(part) for part in facts.get("healthcheck") or [])
    if "/api/health" not in command:
        problems.append("the healthcheck does not ask /api/health")
    elif f"'X-Request-ID': '{HEALTHCHECK_ID}'" not in command:
        problems.append(f"the healthcheck does not send the request id {HEALTHCHECK_ID!r}, so its probes would be counted as test traffic")
    if facts.get("failing_streak"):
        problems.append(f"{facts.get('failing_streak')} failed checks in a row")
    if facts.get("restart_count"):
        problems.append(f"restarted {facts.get('restart_count')} time(s)")
    return not problems, "; ".join(problems) or "healthy through a check of /api/health, never restarted"


def check_container_hardening(facts: dict[str, Any]) -> tuple[bool, str]:
    """Not root, nothing writable but the data volume and a scratch area, no capabilities, no new privileges, published on
    loopback only, and exactly one mount: the named volume at /data. Judged from Docker's configuration and from inside."""
    probe = facts.get("probe") or {}
    writable = probe.get("writable") or {}
    problems = []
    if probe.get("uid") in (None, 0) or facts.get("user") in (None, "", "0", "root"):
        problems.append("it runs as root")
    if not facts.get("read_only"):
        problems.append("the root filesystem is writable")
    for path in ("/app/probe", "/etc/probe", "/usr/probe"):
        if writable.get(path) is not False:
            problems.append(f"{path.rsplit('/', 1)[0]} is writable from inside")
    for path in ("/data/probe", "/tmp/probe"):
        if writable.get(path) is not True:
            problems.append(f"{path.rsplit('/', 1)[0]} is not writable, so the app cannot work")
    if facts.get("cap_drop") != ["ALL"] or probe.get("cap_eff") != "0" * 16:
        problems.append(f"capabilities are not dropped (drop {facts.get('cap_drop')}, effective {probe.get('cap_eff')})")
    if "no-new-privileges:true" not in facts.get("security_opt", []) or probe.get("no_new_privs") is not True:
        problems.append("new privileges are not forbidden")
    if not facts.get("ports") or any(host != "127.0.0.1" for host in facts["ports"]):
        problems.append(f"published on {facts.get('ports') or 'nothing'}, not loopback only")
    mounts = [(m.get("type"), m.get("destination")) for m in facts.get("mounts") or []]
    if mounts != [("volume", "/data")]:
        problems.append(f"mounts are {mounts}, not just the data volume")
    if not facts.get("init"):
        problems.append("no init process to reap children")
    if not facts.get("memory") or not facts.get("pids"):
        problems.append("no memory or process limit")
    return not problems, "; ".join(problems) or f"uid {probe.get('uid')}, read-only root, no capabilities, loopback only, one volume, limits set"


def check_volume_persistence(first: dict[str, Any], second: dict[str, Any]) -> tuple[bool, str]:
    """The restart replaced the container and kept the data: two containers, one named volume, a WAL-mode database with
    the journal's tables in it that the second one opened. (That its content survived is the after-restart tests' job.)"""
    problems = []
    if first.get("id") == second.get("id"):
        problems.append("the second server is the same container, not a new one")
    volumes = [next((m.get("name") for m in f.get("mounts") or [] if m.get("destination") == "/data"), None) for f in (first, second)]
    if not volumes[0] or volumes[0] != volumes[1]:
        problems.append(f"the data volume is {volumes[0]} then {volumes[1]}")
    probe = second.get("probe") or {}
    if probe.get("db_error") or not probe.get("db_bytes"):
        problems.append(f"the database on the volume could not be read ({probe.get('db_error')})")
    elif probe.get("journal_mode") != "wal":
        problems.append(f"the database journal mode is {probe.get('journal_mode')}, not wal")
    elif not {"trades", "notes", "external_events", "feed_state"} <= set(probe.get("tables") or []):
        problems.append("the database on the volume lacks the journal's tables")
    return not problems, "; ".join(problems) or f"a new container found the data on volume {volumes[1]}: {probe.get('db_bytes')} bytes, WAL, all tables"


def check_image_contents(facts: dict[str, Any]) -> tuple[bool, str]:
    """A runtime image: Python 3.14 and the web export, with no Node, no compilers, no test tooling, no tests, no secrets."""
    problems = []
    if not str(facts.get("python", "")).startswith("3.14"):
        problems.append(f"Python is {facts.get('python')}")
    present = [name for name, found in {**(facts.get("tools") or {}), **(facts.get("modules") or {})}.items() if found]
    if present:
        problems.append("it contains " + ", ".join(sorted(present)))
    stray = [path for path, found in (facts.get("paths") or {}).items() if found]
    if stray:
        problems.append("it contains " + ", ".join(sorted(stray)))
    if not facts.get("web_index") or not facts.get("web_files"):
        problems.append("the web export is missing")
    if not facts.get("swagger"):
        problems.append("the vendored Swagger UI is missing")
    return not problems, "; ".join(problems) or f"Python {facts.get('python')}, the web export ({facts.get('web_files')} files) and nothing to build or test with"


def copy_web_export(destination: Path) -> None:
    """The web export the image serves, copied out so the same check as the native build applies to it."""
    created = docker("create", APP_IMAGE).stdout.strip()
    try:
        docker("cp", f"{created}:/app/web", str(destination))
    finally:
        docker("rm", "--volumes", created, check=False)  # the image declares /data a volume, so `create` made an anonymous one that a plain `rm` leaves behind


def docker_footprint() -> dict[str, list[str]]:
    """What a run must not leave in Docker: containers, volumes and networks (images and the build cache are meant to stay)."""
    def names(*command: str) -> list[str]:
        return sorted(docker(*command, check=False).stdout.split())

    return {
        "containers": names("ps", "--all", "--format", "{{.Names}}"),
        "volumes": names("volume", "ls", "--quiet"),
        "networks": names("network", "ls", "--format", "{{.Name}}"),
    }


def check_docker_footprint(before: dict[str, list[str]], after: dict[str, list[str]]) -> tuple[bool, str]:
    """Anything new after the run is left behind by it. Something that went away meanwhile is not the run's doing and is not judged."""
    left = [f"{kind[:-1]} {name}" for kind in ("containers", "volumes", "networks") for name in after.get(kind, []) if name not in before.get(kind, [])]
    return not left, "left behind: " + ", ".join(left) if left else "no container, volume or network left behind"


def check_each(entries: list[tuple[str, dict[str, Any]]], check: Any) -> tuple[bool, str]:
    """A gate over every container the run started: it passes only if each does, and names the ones that do not."""
    results = [(label, *check(facts)) for label, facts in entries]
    bad = [f"{label}: {detail}" for label, ok, detail in results if not ok]
    return not bad, "; ".join(bad) or f"{len(results)} container(s): {results[0][2]}"


def run_production_smoke(py: Path, phase: int, run_dir: Path, phase_dir: Path) -> tuple[bool, str, list[dict[str, Any]], list[tuple[Path, int | None]]]:
    """A second stack from docker-compose.yml alone, as a person would run it: APP_ENV=prod, the feeds off, the zone UTC, an
    empty volume. The deployment tests write through the browser, the container is replaced (the volume stays), and the
    after-restart test finds the data. Returns whether both passes passed, their summaries, the app containers' facts and
    the two servers' log folders."""
    port = free_port()
    smoke = ComposeStack(
        f"tj-smoke-phase{phase}",
        [COMPOSE_BASE, COMPOSE_SMOKE],
        {"TJ_IMAGE_TAG": IMAGE_TAG, "APP_PORT": str(port), "RUN_DIR": run_dir.as_posix(), "ARTIFACTS_DIR": ARTIFACTS.as_posix(), "VERIFY_PHASE": str(phase)},
    )
    facts: list[dict[str, Any]] = []
    stopped: list[tuple[Path, int | None]] = []
    smoke.down()
    try:
        say("production smoke: the stack of docker-compose.yml alone, on an empty volume")
        server = start_compose_service(smoke, "app", run_dir / "server-smoke-1", f"http://127.0.0.1:{port}")
        code, first = run_e2e(py, "deployment and not after_restart", server, phase, run_dir, phase_dir, "smoke-1", None)
        facts.append(collect_container_facts(smoke, server))
        # A backup taken inside the running, read-only container, with the app writing to the same database
        said = smoke.run("exec", "-T", "app", "python", "-m", "app.tools.backup", "--to", "/data/backups", check=False)
        try:
            made = json.loads(said.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            made = {"error": tail(said.stdout + said.stderr, 4)}
        stopped.append((server.directory, stop_server(server)))  # the container goes, the volume stays
        say("production smoke: a new container on the same volume")
        server = start_compose_service(smoke, "app", run_dir / "server-smoke-2", f"http://127.0.0.1:{port}")
        again, second = run_e2e(py, "deployment and after_restart", server, phase, run_dir, phase_dir, "smoke-2", None)
        facts.append(collect_container_facts(smoke, server))
        listed = smoke.run("exec", "-T", "app", "python", "-c", "import json, os; print(json.dumps(sorted(os.listdir('/data/backups'))))", check=False)
        try:
            kept = json.loads(listed.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            kept = []
        stopped.append((server.directory, stop_server(server)))
    finally:
        smoke.down()
    backed_up = made.get("integrity") == "ok" and made.get("rows", {}).get("trades") == 1 and len(kept) == 1 and kept[0] in str(made.get("backup", ""))
    backup_note = f"backup {made.get('bytes')} bytes with {made.get('rows', {}).get('trades')} trade, kept on the volume" if backed_up else f"backup failed: {made} then {kept}"
    return code == 0 and again == 0 and backed_up, f"{first}; after the container was replaced: {second}; {backup_note}", facts, stopped


# --- the frontend (Phase 2 on) -------------------------------------------------------------------


def find_node_tools() -> dict[str, str]:
    tools = {name: shutil.which(name) for name in ("node", "npm", "npx")}
    missing = [name for name, found in tools.items() if not found]
    if missing:
        raise HarnessError("not on PATH: " + ", ".join(missing) + "\n" + FRONTEND_SETUP_HINT)
    found_tools = {name: str(found) for name, found in tools.items()}
    version = subprocess.run([found_tools["node"], "--version"], capture_output=True, text=True).stdout.strip()
    numbers = tuple(int(part) for part in re.findall(r"\d+", version)[:2])
    if numbers < NODE_MIN:
        raise HarnessError(f"node {version} is too old: {'.'.join(map(str, NODE_MIN))} or newer runs TypeScript test files directly\n{FRONTEND_SETUP_HINT}")
    if not (FRONTEND / "node_modules").is_dir():
        raise HarnessError("frontend/node_modules is missing\n" + FRONTEND_SETUP_HINT)
    return {**found_tools, "version": version}


def frontend_versions(tools: dict[str, str]) -> dict[str, Any]:
    def installed(name: str) -> str | None:
        try:
            return json.loads(read_text(FRONTEND / "node_modules" / name / "package.json")).get("version")
        except json.JSONDecodeError:
            return None

    npm = subprocess.run([tools["npm"], "--version"], capture_output=True, text=True).stdout.strip()
    packages = ("expo", "expo-router", "react", "react-native", "react-native-web", "typescript", "@tanstack/react-query")
    return {"node": tools["version"].lstrip("v"), "npm": npm, **{name: installed(name) for name in packages}}


def run_tool(command: list[str], cwd: Path, transcript: Path, timeout: float = 900) -> tuple[int, str]:
    """Runs a command with the frontend's quiet environment, keeps all of its output in `transcript`, and returns
    (exit code, output). Nothing is echoed here: the caller reports what matters."""
    transcript.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            command, cwd=cwd, env={**os.environ, **FRONTEND_ENV}, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
        code, output = result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired as exc:
        code, output = 124, f"timed out after {timeout:.0f}s\n{exc.stdout or ''}"
    write_text_lf(transcript, output)
    return code, output


def tail(text: str, lines: int = 8) -> str:
    return " | ".join(line.strip() for line in text.strip().splitlines()[-lines:] if line.strip())


def check_web_build(out: Path) -> tuple[bool, str]:
    bundles = sorted((out / "_expo" / "static" / "js" / "web").glob("*.js"))
    biggest = max((b.stat().st_size for b in bundles), default=0)
    ok = (out / "index.html").is_file() and biggest > 100_000
    return ok, f"index.html and {len(bundles)} bundle(s), largest {biggest // 1024} KB" if ok else "the export has no index.html or no real JavaScript bundle"


def check_native_bundles(out: Path) -> tuple[bool, str]:
    sizes = {platform: max((b.stat().st_size for b in (out / "_expo" / "static" / "js" / platform).glob("*.hbc")), default=0) for platform in ("ios", "android")}
    bad = [platform for platform, size in sizes.items() if size < 100_000]
    return not bad, ", ".join(f"{platform} {size // 1024} KB" for platform, size in sizes.items()) if not bad else "no Hermes bundle for: " + ", ".join(bad)


def frontend_source_files() -> dict[str, str]:
    root = FRONTEND / "src"
    return {path.relative_to(FRONTEND).as_posix(): read_text(path) for path in sorted(root.rglob("*")) if path.suffix in (".ts", ".tsx") and path.is_file()}


def frontend_checks(tools: dict[str, str], run_dir: Path, web_dir: Path, harness: HarnessLog, build_web: bool = True) -> tuple[list[Gate], bool, dict[str, Any]]:
    """Dependencies, types, unit tests, source rules, then the web build the server will serve and the two native
    bundles. Returns the gates, whether the web build is usable, and what metrics.json records about the frontend."""
    gates: list[Gate] = []
    info: dict[str, Any] = {}
    npm, npx = tools["npm"], tools["npx"]

    def step(name: str, command: list[str], transcript: str) -> tuple[int, str]:
        say(f"  frontend: {name}")
        began = time.time()
        code, output = run_tool(command, FRONTEND, run_dir / transcript)
        harness.add("info" if code == 0 else "error", "frontend_step", step=name, exit_code=code, duration_s=round(time.time() - began, 1), transcript=transcript)
        return code, output

    code, output = step("npm ls", [npm, "ls", "--depth=0"], "frontend-deps.txt")
    gates.append(Gate("frontend-deps", code == 0, "node_modules matches package.json" if code == 0 else "npm ls found problems: " + tail(output)))

    code, output = step("typecheck", [npm, "run", "typecheck"], "frontend-typecheck.txt")
    gates.append(Gate("frontend-typecheck", code == 0, "app and tests type-check under strict TypeScript" if code == 0 else tail(output, 12)))
    info["typecheck"] = "pass" if code == 0 else "fail"

    code, output = step("unit tests", [npm, "test"], "frontend-unit-tests.txt")
    counts = parse_node_test_summary(output)
    unit_ok = code == 0 and counts is not None and counts[1] == 0 and counts[0] > 0
    unit_text = f"{counts[0]} passed, {counts[1]} failed" if counts else "no summary found"
    gates.append(Gate("frontend-unit-tests", unit_ok, unit_text if unit_ok else f"{unit_text}: {tail(output, 12)}"))
    info["unit_tests"] = f"{counts[0]} passed" if unit_ok and counts else "fail"

    problems = scan_frontend_sources(frontend_source_files())
    broken = sorted({match.group(1) for problem in problems if (match := re.search(r"\[([\w-]+)\]$", problem))})
    reasons = " ".join(f"{rule}: {why}." for rule, _pattern, why, _exempt in FRONTEND_RULES if rule in broken)
    gates.append(
        Gate(
            "frontend-rules",
            not problems,
            f"{len(FRONTEND_RULES)} source rules hold in frontend/src" if not problems else f"{len(problems)} violation(s): {', '.join(problems[:4])}. {reasons}",
        )
    )

    built = True
    if build_web:  # the compose backend takes the web export from the image it builds, and checks it there
        code, output = step("web build", [npx, "expo", "export", "--platform", "web", "--output-dir", str(web_dir)], "frontend-web-build.txt")
        built, detail = check_web_build(web_dir) if code == 0 else (False, tail(output, 12))
        gates.append(Gate("web-build", built, detail))
        info["web_build"] = "pass" if built else "fail"

    native_dir = run_dir / "native-dist"
    code, output = step("native bundles", [npx, "expo", "export", "--platform", "ios", "--platform", "android", "--output-dir", str(native_dir)], "frontend-native-bundles.txt")
    bundled, detail = check_native_bundles(native_dir) if code == 0 else (False, tail(output, 12))
    gates.append(Gate("native-bundles", bundled, detail))
    info["native_bundles"] = ["android", "ios"] if bundled else "fail"
    return gates, built, info


def gate_api_contract(tools: dict[str, str], schema: dict[str, Any], run_dir: Path) -> Gate:
    """The typed client is generated from the API's OpenAPI document. This regenerates it from the running server
    and compares, so a changed endpoint cannot leave the frontend compiling against the old shape."""
    source, generated = run_dir / "openapi-live.json", run_dir / "schema.generated.d.ts"
    write_text_lf(source, json.dumps(schema))
    code, output = run_tool([tools["npx"], "openapi-typescript", str(source), "-o", str(generated)], FRONTEND, run_dir / "frontend-contract.txt")
    if code != 0 or not generated.is_file():
        return Gate("api-contract", False, "openapi-typescript failed: " + tail(output))
    ok = contract_in_sync(read_text(generated), read_text(FRONTEND / "src" / "api" / "schema.d.ts"))
    return Gate("api-contract", ok, "frontend/src/api/schema.d.ts matches the running API" if ok else "frontend/src/api/schema.d.ts is stale: run `npm run gen:api` against a running server and commit it")


# --- the phase run -------------------------------------------------------------------------------


def describe_errors(errors: list[dict[str, Any]]) -> str:
    if not errors:
        return "no error records from the server or the browser"
    shown = "; ".join(f"[{r['source']}] {str(r['msg'])[:100]}" for r in errors[:3])
    return f"{len(errors)} error record(s): {shown}"


def run_phase(phase: int, py: Path, port: int, backend: str = "native") -> int:
    started = time.time()
    log_path = LOGS / f"phase_{phase}.log"
    run_dir = LOGS / "_run" / f"phase_{phase}"
    phase_dir = ARTIFACTS / f"phase_{phase}"
    shots = phase_dir / "screenshots"
    frontend = phase >= FRONTEND_FROM
    feeds = phase >= FEEDS_FROM
    compose = backend == "compose"
    serves_expo = frontend or compose  # the image always carries the Expo app, so the Phase 0 stub page is never there to test

    versions = tool_versions(py)
    check_packages(versions)
    tools = find_node_tools() if frontend else {}
    if frontend:
        versions.update(frontend_versions(tools))
    docker_before: dict[str, list[str]] = {}
    if compose:
        versions.update(docker_versions())
        docker_before = docker_footprint()
    static_dir = static_dir_for(phase, run_dir)

    for target in (log_path, run_dir, phase_dir):
        remove(target)
    run_dir.mkdir(parents=True)
    shots.mkdir(parents=True)

    harness = HarnessLog()
    before = repo_snapshot()
    harness.add("info", "run_start", phase=phase, backend=backend, git_rev=git_rev(), versions=versions, platform=sys.platform, timezone=VERIFY_TIMEZONE)
    say(f"verify phase {phase} ({backend} backend)")

    # Both servers share one database file, so the second one proves the data outlived the first.
    # FEEDS_MODE=off unless the phase runs the connectors: a developer's own .env must never make a verification run call out.
    env_extra = {"STATIC_DIR": str(static_dir), "DATABASE_URL": "sqlite:///" + (run_dir / "journal.db").as_posix(), "FEEDS_MODE": "off"}
    restart = phase >= RESTART_STAGE_FROM
    gates: list[Gate] = []
    stopped: list[tuple[Path, int | None]] = []
    server: Server | None = None
    stub: Server | None = None
    stack: ComposeStack | None = None
    facts: list[dict[str, Any]] = []  # what each app container was, as Docker and the container itself reported it
    smoke_facts: list[dict[str, Any]] = []  # the same, for the containers of the production smoke stage
    images: dict[str, Any] = {}
    app_port = port or free_port()
    test_env: dict[str, str] = {}
    schema: dict[str, Any] | None = None
    unit_summary = "not run"
    restarts_survived = 0
    frontend_info: dict[str, Any] | None = None
    try:
        gates += [gate_line_endings(), gate_playwright_pin(versions)]
        if all(gate.ok for gate in gates):
            serve = True
            if frontend:
                say("checking the frontend: dependencies, types, unit tests, source rules, web and native builds")
                front_gates, serve, frontend_info = frontend_checks(tools, run_dir, static_dir, harness, build_web=not compose)
                gates += front_gates
            say("running backend unit tests")
            code, unit_summary = run_pytest(py, BACKEND, ["-q"], {}, run_dir / "pytest-unit.txt")
            gates.append(Gate("unit-tests", code == 0, unit_summary))

            if serve and compose:
                stack = ComposeStack(
                    f"tj-verify-phase{phase}",
                    [COMPOSE_BASE, COMPOSE_VERIFY],
                    {
                        "TJ_IMAGE_TAG": IMAGE_TAG,
                        "APP_PORT": str(app_port),
                        "RUN_DIR": run_dir.as_posix(),
                        "ARTIFACTS_DIR": ARTIFACTS.as_posix(),
                        "VERIFY_PHASE": str(phase),
                        "APP_TIMEZONE": VERIFY_TIMEZONE,
                        "FEEDS_MODE": "off",
                        "GCAL_TOKEN": GCAL_TOKEN,
                        "COMPOSE_PROFILES": "feeds" if feeds else "",
                    },
                )
                stack.down()  # a leftover of an interrupted run must not lend its volume to this one
                say("building the images (the app from docker/app.Dockerfile, the test runner from e2e/Dockerfile)")
                began = time.time()
                built = stack.run("build", "app", "e2e", timeout=1800)
                write_text_lf(run_dir / "docker-build.txt", built.stdout + built.stderr)
                images = {"app": image_facts(APP_IMAGE), "e2e": image_facts(f"tradingjournal/e2e:{IMAGE_TAG}")}
                harness.add("info", "docker_build", duration_s=round(time.time() - began, 1), images=images)
                static_dir = run_dir / "web-dist"
                copy_web_export(static_dir)
                built_web, web_detail = check_web_build(static_dir)
                if frontend:
                    gates.append(Gate("web-build", built_web, f"{web_detail}, from the image"))
                    if frontend_info is not None:
                        frontend_info["web_build"] = "pass" if built_web else "fail"
                gates.append(Gate("image-contents", *check_image_contents(stack.exec_python_in_image(APP_IMAGE, IMAGE_PROBE))))
                serve = built_web

            if serve and feeds:
                # The app reads the feeds from the stub, in fixture mode (which refuses any address that is not loopback), on a
                # clock that starts in the fixtures' week. The calendar address is a secret-shaped URL so the redaction is real.
                if compose:
                    stack.env.update({"FEEDS_MODE": "fixture"})
                    stub = start_compose_service(stack, "feedstub", run_dir / "feed-stub", f"http://{STUB_HOST}:{STUB_PORT}")
                else:
                    stub = start_stub(py, run_dir / "feed-stub", free_port())
                gcal_url = f"{stub.base_url}/gcal/ical/me/{GCAL_TOKEN}/basic.ics"
                env_extra.update(
                    {
                        "FEEDS_MODE": "fixture",
                        "FF_FEED_URL": f"{stub.base_url}/ff/thisweek.xml",
                        "GCAL_ICAL_URL": gcal_url,
                        "APP_NOW_OVERRIDE": FEED_CLOCK,
                        "SYNC_COOLDOWN_SECONDS": str(FEED_COOLDOWN_SECONDS),
                        "FF_POLL_MINUTES": str(FEED_POLL_MINUTES),
                        "GCAL_POLL_MINUTES": str(FEED_POLL_MINUTES),
                        "FEED_TICK_SECONDS": "1",
                        "FEED_TIMEOUT_SECONDS": "2",
                    }
                )
                os.environ["GCAL_ICAL_URL"] = gcal_url  # the run's own secret: the leak gate scans for it, and the tests read it
                test_env = {"FEED_STUB_URL": stub.base_url, "FEEDS_NOW": FEED_CLOCK, "FEED_COOLDOWN": str(FEED_COOLDOWN_SECONDS)}
                harness.add("info", "feed_stub_started", base_url=stub.base_url, clock=FEED_CLOCK)

            def start_app(instance: int, settings: dict[str, str]) -> Server:
                if stack is None:
                    return start_server(py, run_dir / f"server-{instance}", port, settings)
                stack.env.update({name: value for name, value in settings.items() if name in COMPOSE_SETTINGS})
                return start_compose_service(stack, "app", run_dir / f"server-{instance}", f"http://127.0.0.1:{app_port}")

            if serve:
                clock_origin = datetime.now(timezone.utc)  # the app's feed clock starts a moment after this, and runs in real time
                server = start_app(1, env_extra)
                harness.add("info", "server_started", instance=1, base_url=server.base_url, static_dir=("image:/app/web" if compose else str(static_dir.relative_to(ROOT))))
                say(f"server up at {server.base_url}; running e2e tests")
                markers = " or ".join(f"p{n}" for n in range(phase + 1))
                # The Expo app replaces the stub page in Phase 2 (and is all an image holds), so the test that needs the stub is left out from then on.
                selector = f"({markers}) and not after_restart and not deployment" + (" and not stub_page" if serves_expo else "") + ("" if compose else " and not expo_app")
                code, summary = run_e2e(py, selector, server, phase, run_dir, phase_dir, "stage-1", test_env)
                ok, detail = code == 0, summary
                schema = fetch_openapi(server)
                if frontend:
                    gates.append(gate_api_contract(tools, schema, run_dir))
                if stack is not None:
                    facts.append(collect_container_facts(stack, server))

                if restart:
                    say("restarting the server on the same database")
                    stopped.append((server.directory, stop_server(server)))
                    restart_env, restart_test_env = env_extra, test_env
                    if feeds:
                        # A restart does not turn a clock back: the second server's feed clock carries on from where the first one's had got to,
                        # so what the first one scheduled (the next sync, the cooldown) is still in the future, as it would be for real.
                        restarted = datetime.now(timezone.utc)
                        carried = datetime.fromisoformat(FEED_CLOCK.replace("Z", "+00:00")) + (restarted - clock_origin)
                        restart_env = {**env_extra, "APP_NOW_OVERRIDE": carried.isoformat()}
                        restart_test_env = {**test_env, "SERVER_RESTARTED_AT": restarted.isoformat()}
                    if stack is not None and stub is not None:
                        # The stub stamps its records with the Docker VM's clock, so "since the restart" must be told in that clock.
                        restart_test_env["SERVER_RESTARTED_AT"] = stack.clock_of(stub.container) or restart_test_env.get("SERVER_RESTARTED_AT", "")
                    server = start_app(2, restart_env)
                    harness.add("info", "server_started", instance=2, base_url=server.base_url, restart=True)
                    code, summary = run_e2e(py, f"after_restart and ({markers}) and not deployment", server, phase, run_dir, phase_dir, "stage-2", restart_test_env)
                    restarts_survived = 1 if code == 0 else 0
                    ok, detail = ok and code == 0, f"{detail}; after restart: {summary}"
                    if stack is not None:
                        facts.append(collect_container_facts(stack, server))
                gates.append(Gate("e2e-tests", ok, detail))
                if compose and phase >= SMOKE_FROM:
                    smoke_ok, smoke_detail, smoke_facts, smoke_stopped = run_production_smoke(py, phase, run_dir, phase_dir)
                    gates.append(Gate("production-smoke", smoke_ok, smoke_detail))
                    stopped += smoke_stopped
            else:
                harness.add("error", "server_skipped", reason="the web build failed, so there is nothing to serve")
    except HarnessError as exc:
        harness.add("error", "harness_error", detail=str(exc))
        gates.append(Gate("harness", False, str(exc)))
    finally:
        if server is not None:
            stopped.append((server.directory, stop_server(server)))
        if stub is not None:
            stop_server(stub)
        if stack is not None:
            stack.down()

    streams: list[list[dict[str, Any]]] = []
    secrets = secret_values(os.environ)  # after the feed environment is set: the calendar address is one of them
    leaks: list[str] = []
    outcomes: dict[str, str] = {}
    if stopped:
        fallback = harness.records[0]["ts"]
        server_records: list[dict[str, Any]] = []
        for index, (directory, exit_code) in enumerate(stopped, 1):
            records = parse_server_output(read_text(directory / "server.out"), read_text(directory / "server.err"), fallback)
            # Exit code 3 is normal on Windows: uvicorn re-raises SIGBREAK after a clean shutdown.
            graceful = any(record.get("msg") == "Application shutdown complete." for record in records)
            harness.add("info", "server_stopped", instance=index, exit_code=exit_code, graceful=graceful)
            server_records += records
        e2e_records = read_jsonl(run_dir / "e2e.jsonl", "test", fallback) + read_jsonl(run_dir / "e2e-smoke.jsonl", "test", fallback)
        streams = [server_records, e2e_records]
        stub_records: list[dict[str, Any]] = []
        if stub is not None:
            stub_records = read_jsonl(run_dir / "feed-stub.jsonl", "stub", fallback)
            # Anything the stub wrote to stderr is a crash in the harness itself, and it fails the run like a server error.
            stub_records += [
                {"ts": fallback, "source": "stub", "level": "error", "msg": line.rstrip(), "stream": "stderr"}
                for line in read_text(stub.directory / "server.err").splitlines()
                if line.strip()
            ]
            streams.append(stub_records)
        outcomes = summarize_tests(e2e_records)

        gates.append(Gate("screenshots", *check_screenshots(shots, started - (CLOCK_SKEW_ALLOWED if compose else 2))))
        errors = scan_log_errors(server_records + e2e_records + stub_records)
        gates.append(Gate("no-unexpected-errors", not errors, describe_errors(errors)))
        present = {record["source"] for record in server_records + e2e_records + stub_records}
        absent = [source for source in (FEED_SOURCES if feeds else REQUIRED_SOURCES) if source not in present]
        gates.append(Gate("log-sources", not absent, "server, client and test records present" if not absent else "no records from: " + ", ".join(absent)))

        exercised: list[str] = []
        uncovered: list[str] = []
        if schema is not None:
            exercised, uncovered = api_coverage(schema, server_records, phase=phase)
        if phase >= 1:
            if schema is None:
                gates.append(Gate("api-coverage", False, "the OpenAPI schema was not retrieved"))
            else:
                total = len(exercised) + len(uncovered)
                gates.append(Gate("api-coverage", not uncovered, f"{len(exercised)} of {total} operations answered 2xx" + (f"; never succeeded: {', '.join(uncovered)}" if uncovered else "")))
            missing_commits, rolled_back = uncommitted_writes(server_records), rollbacks(server_records)
            gates.append(
                Gate(
                    "db-transactions",
                    not missing_commits and not rolled_back,
                    f"{len(write_requests(server_records))} successful write requests, each with a commit record; {len(rolled_back)} rollbacks"
                    if not missing_commits and not rolled_back
                    else f"{len(missing_commits)} write(s) without a commit: {', '.join(missing_commits[:3])}; {len(rolled_back)} rollback(s)",
                )
            )

        feeds_info: dict[str, Any] | None = None
        if feeds:
            gates.append(Gate("feeds-offline", *check_feed_traffic(server_records, stub_records, (*LOOPBACK, STUB_HOST) if compose else LOOPBACK)))
            gates.append(Gate("feed-paths", *check_feed_paths(server_records)))
            feeds_info = feed_metrics(server_records)
            gates.append(Gate("secret-registered", *check_secret_registered(secrets, os.environ.get("GCAL_ICAL_URL", ""))))

        container_info: dict[str, Any] | None = None
        if compose:
            if not facts:
                gates.append(Gate("container-health", False, "the app container was never inspected"))
            else:
                started_by_run = [("verification stack", facts[0])]
                if len(facts) > 1:
                    started_by_run.append(("verification stack, replaced", facts[-1]))
                started_by_run += [(f"production stack {n}", f) for n, f in enumerate(smoke_facts, 1)]
                healthy = check_each(started_by_run, check_container_health)
                hardened = check_each(started_by_run, check_container_hardening)
                gates.append(Gate("container-health", *healthy))
                gates.append(Gate("container-hardening", *hardened))
                pairs = [("verification stack", facts[0], facts[-1])] if len(facts) > 1 else []
                if len(smoke_facts) > 1:
                    pairs.append(("production stack", smoke_facts[0], smoke_facts[-1]))
                persisted = (False, "no restart happened, so nothing shows the data outlives its container")
                if restart:
                    outcomes_by_pair = [(label, *check_volume_persistence(a, b)) for label, a, b in pairs]
                    bad = [f"{label}: {detail}" for label, ok, detail in outcomes_by_pair if not ok]
                    persisted = (bool(outcomes_by_pair) and not bad, "; ".join(bad) or f"{len(outcomes_by_pair)} restart(s): " + outcomes_by_pair[0][2]) if outcomes_by_pair else persisted
                    gates.append(Gate("volume-persistence", *persisted))
                container_info = {
                    "healthy": healthy[0],
                    "hardened": hardened[0],
                    "volume_persists": persisted[0] if restart else None,
                    "containers_checked": len(started_by_run),
                    "non_root": all(f["probe"].get("uid") not in (None, 0) for _, f in started_by_run),
                    "read_only_root": all(f["read_only"] for _, f in started_by_run),
                    "capabilities": "none" if all(f["probe"].get("cap_eff") == "0" * 16 for _, f in started_by_run) else "some",
                    "published_on": sorted({host for _, f in started_by_run for host in f["ports"]}),
                    "journal_mode": facts[-1]["probe"].get("journal_mode"),
                }
            gates.append(Gate("docker-hygiene", *check_docker_footprint(docker_before, docker_footprint())))

        ui_info: dict[str, Any] | None = None
        if frontend:
            ui_exercised: list[str] = []
            ui_uncovered: list[str] = []
            if schema is None:
                gates.append(Gate("ui-coverage", False, "the OpenAPI schema was not retrieved"))
            else:
                ui_exercised, ui_uncovered = ui_coverage(schema, server_records, phase)
                total = len(ui_exercised) + len(ui_uncovered)
                gates.append(
                    Gate(
                        "ui-coverage",
                        not ui_uncovered,
                        f"{len(ui_exercised)} of {total} operations answered 2xx to requests the app itself made"
                        + (f"; never from the app: {', '.join(ui_uncovered)}" if ui_uncovered else ""),
                    )
                )
            matched, mocked, mismatched = correlate_network([r for r in e2e_records if r.get("source") == "client"], server_records)
            if mismatched:
                correlation = f"{len(mismatched)} mismatch(es): {'; '.join(mismatched[:2])}"
            elif matched == 0:
                correlation = "the browser logged no API responses"
            else:
                correlation = f"{matched} API responses seen by the browser match the server's own records; {mocked} were mocked by tests"
            gates.append(Gate("net-correlation", matched > 0 and not mismatched, correlation))
            ui_info = {
                "operations": len(ui_exercised) + len(ui_uncovered),
                "exercised": len(ui_exercised),
                "uncovered": ui_uncovered,
                "write_requests": dict(sorted(Counter(r["method"] for r in write_requests(server_records) if is_web(r)).items())),
            }
            if frontend_info is not None and schema is not None:
                frontend_info["api_contract"] = "in sync" if next((g.ok for g in gates if g.name == "api-contract"), False) else "stale"

        leaks = find_secret_leaks(render(merge_records(harness.records, *streams)), secrets)
        gates.append(Gate("no-secret-leaks", not leaks, "; ".join(leaks) or "none found"))
        stray = unexpected_changes(before, repo_snapshot())
        gates.append(Gate("repo-hygiene", not stray, "wrote only under logs/ and artifacts/" if not stray else "unexpected changes: " + ", ".join(stray[:10])))

        if schema is not None and phase >= 1:
            write_text_lf(phase_dir / "openapi.json", json.dumps(schema, indent=2, sort_keys=True) + "\n")
        metrics = compute_metrics(
            phase=phase,
            backend=backend,
            outcomes=outcomes,
            unit_summary=unit_summary,
            exercised=exercised,
            uncovered=uncovered,
            server_records=server_records,
            e2e_records=e2e_records,
            gates=gates,
            restarts_survived=restarts_survived,
            frontend=frontend_info,
            ui=ui_info,
            feeds=feeds_info,
            container=container_info,
        )
        write_text_lf(phase_dir / "metrics.json", json.dumps(metrics, indent=2, sort_keys=True) + "\n")

    failed = [gate for gate in gates if not gate.ok]
    counts = {kind: sum(1 for value in outcomes.values() if value == kind) for kind in ("passed", "failed", "skipped")} if outcomes else {}
    for gate in gates:
        harness.add("info" if gate.ok else "error", "gate", name=gate.name, ok=gate.ok, detail=gate.detail)
    harness.add(
        "info" if not failed else "error",
        "run_end",
        result="fail" if failed else "pass",
        tests=counts,
        gates_failed=[gate.name for gate in failed],
        duration_s=round(time.time() - started, 1),
    )
    text = render(merge_records(harness.records, *streams))
    write_text_lf(log_path, mask_secrets(text, secrets) if leaks else text)

    say("")
    for gate in gates:
        say(f"  [{'PASS' if gate.ok else 'FAIL'}] {gate.name:<21} {gate.detail}")
    say(f"result: {'FAIL' if failed else 'PASS'}   tests: {counts or 'not run'}")
    say(f"log: {log_path.relative_to(ROOT)}   artifacts: {phase_dir.relative_to(ROOT)}")
    return 1 if failed else 0


# --- self-test: prove the gates bite -------------------------------------------------------------


def self_test(py: Path, port: int) -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, ok: bool) -> None:
        checks.append((name, bool(ok)))

    secret = "https://calendar.example.test/ical/me/private-0123456789abcdef0123456789abcdef/basic.ics"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "crlf.txt").write_bytes(b"a\r\nb\r\n")
        (root / "lf.txt").write_bytes(b"a\nb\n")
        (root / "image.png").write_bytes(PNG_SIGNATURE + b"\0\0\0\rIHDR")
        found = find_cr_files(root, ["crlf.txt", "lf.txt", "image.png", "missing.txt"])
        check("LF guard flags CRLF text and ignores LF, binary and missing files", found == ["crlf.txt"])

        empty, valid, fake = root / "empty", root / "valid", root / "fake"
        for folder in (empty, valid, fake):
            folder.mkdir()
        (valid / "a.png").write_bytes(PNG_SIGNATURE + b"data")
        (fake / "b.png").write_bytes(b"not really a png at all")
        check("screenshot gate fails on an empty folder", not check_screenshots(empty, 0)[0])
        check("screenshot gate fails on a file that is not a PNG", not check_screenshots(fake, 0)[0])
        check("screenshot gate passes with a valid PNG", check_screenshots(valid, 0)[0])
        check("screenshot gate ignores PNGs older than the run", not check_screenshots(valid, time.time() + 60)[0])

    errors = scan_log_errors(
        [
            {"source": "server", "level": "error", "msg": "boom"},
            {"source": "client", "level": "error", "msg": "console"},
            {"source": "test", "level": "error", "msg": "assertion"},
            {"source": "server", "level": "warning", "msg": "careful"},
        ]
    )
    check("error gate flags server and browser errors only", [r["msg"] for r in errors] == ["boom", "console"])
    check("secret gate finds an env secret", bool(find_secret_leaks("x " + secret, [secret])))
    check("secret gate finds a JSON-escaped env secret", bool(find_secret_leaks(json.dumps({"u": secret + '"'}), [secret + '"'])))
    check("secret gate finds an iCal private token without any env", bool(find_secret_leaks("private-0123456789abcdef0123", [])))
    check("secret gate accepts clean text", not find_secret_leaks("nothing to see", [secret]))
    check("masking removes the secret and the token", secret not in mask_secrets("x " + secret, [secret]) and "private-0123" not in mask_secrets("private-0123456789abcdef", []))
    check(
        "hygiene gate allows logs/ and artifacts/ and flags anything else",
        unexpected_changes({"?? a.txt"}, {"?? a.txt", "?? logs/x", "?? artifacts/y", "?? src/z.py"}) == ["?? src/z.py"],
    )
    parsed = parse_server_output(
        '{"ts":"2026-01-01T00:00:01.000Z","source":"server","level":"info","msg":"a"}\r\nstray line\r\n',
        "Traceback: boom\r\n",
        "2026-01-01T00:00:00.000Z",
    )
    check(
        "server output parser keeps JSON, wraps stray stdout as info and stderr as error",
        [(r["level"], r["msg"]) for r in parsed] == [("info", "a"), ("info", "stray line"), ("error", "Traceback: boom")],
    )
    merged = merge_records(
        [
            {"ts": "2026-01-01T00:00:09.000Z", "source": "harness", "level": "info", "msg": "run_end"},
            {"ts": "2026-01-01T00:00:05.000Z", "source": "harness", "level": "info", "msg": "run_start"},
        ],
        [
            {"ts": "2026-01-01T00:00:03.000Z", "source": "server", "level": "info", "msg": "later"},
            {"ts": "2026-01-01T00:00:01.000Z", "source": "server", "level": "info", "msg": "earlier"},
        ],
    )
    check("merge sorts by time with run_start first and run_end last", [r["msg"] for r in merged] == ["run_start", "earlier", "later", "run_end"])
    outcomes = summarize_tests(
        [
            {"source": "test", "msg": "test_report", "test": "t::a", "when": "call", "outcome": "passed"},
            {"source": "test", "msg": "test_report", "test": "t::b", "when": "call", "outcome": "passed"},
            {"source": "test", "msg": "test_report", "test": "t::b", "when": "teardown", "outcome": "failed"},
            {"source": "test", "msg": "test_report", "test": "t::c", "when": "setup", "outcome": "skipped"},
        ]
    )
    check("a teardown failure turns a passed test into a failed one", outcomes == {"t::a": "passed", "t::b": "failed", "t::c": "skipped"})

    schema = {"paths": {"/api/trades": {"get": {}, "post": {}}, "/api/trades/{trade_id}": {"get": {}, "delete": {}}}}

    def request(method: str, path: str, status: int, request_id: str = "t1") -> dict[str, Any]:
        return {"source": "server", "msg": "request", "method": method, "path": path, "status": status, "request_id": request_id}

    exercised, uncovered = api_coverage(
        schema,
        [request("GET", "/api/trades", 200), request("POST", "/api/trades", 422), request("GET", "/api/trades/7", 200), request("DELETE", "/api/trades/7", 204, "harness-x")],
    )
    check("coverage counts 2xx answers and matches path parameters", exercised == ["GET /api/trades", "GET /api/trades/{trade_id}"])
    check("coverage reports operations that only failed or were hit by the harness", uncovered == ["POST /api/trades", "DELETE /api/trades/{trade_id}"])
    commit = {"source": "server", "msg": "db_transaction", "outcome": "commit", "request_id": "t1"}
    check("a successful write without a commit record is flagged", uncommitted_writes([request("POST", "/api/trades", 201)]) == ["POST /api/trades (t1)"])
    check("a committed write passes", uncommitted_writes([request("POST", "/api/trades", 201), commit]) == [])
    check("rejected, harness and read requests need no commit", uncommitted_writes([request("POST", "/api/trades", 422), request("DELETE", "/api/trades/1", 204, "harness-x"), request("GET", "/api/trades", 200)]) == [])
    check("rollbacks are found", len(rollbacks([{"msg": "db_transaction", "outcome": "rollback"}, commit])) == 1)

    # Phase 3: coverage knows which phase introduced an operation, and the feed gates read what the app logged.
    phased = {"paths": {"/api/trades": {"get": {}}, "/api/events": {"get": {"x-phase": 3}}, "/api/sync": {"post": {"x-phase": 3}}}}
    done = [request("GET", "/api/trades", 200)]
    check("coverage of phase 2 does not ask for an operation phase 3 introduced", api_coverage(phased, done, phase=2) == (["GET /api/trades"], []))
    check("coverage of phase 3 does", api_coverage(phased, done, phase=3) == (["GET /api/trades"], ["GET /api/events", "POST /api/sync"]))
    check("coverage with no phase asks for everything", len(api_coverage(phased, done)[1]) == 2)
    check("coverage of phase 0 asks for what phase 1 does, as it always has", api_coverage(phased, done, phase=0) == api_coverage(phased, done, phase=1))
    sync = {"source": "server", "msg": "feed_sync", "feed": "forexfactory", "outcome": "ok", "host": "127.0.0.1", "trigger": "startup"}
    both = [sync, {**sync, "feed": "gcal"}, {"source": "server", "msg": "feeds_started", "mode": "fixture"}]
    served = [{"source": "stub", "msg": "stub_request", "feed": "gcal", "user_agent": "TradingJournal/0.3 (personal, single-user)"}]
    check("the offline gate passes for loopback syncs in fixture mode", check_feed_traffic(both, served)[0])
    check("the offline gate fails when a sync went to a real host", not check_feed_traffic([*both, {**sync, "host": "nfs.faireconomy.media"}], served)[0])
    check("the offline gate fails outside fixture mode", not check_feed_traffic([sync, {**sync, "feed": "gcal"}, {"source": "server", "msg": "feeds_started", "mode": "live"}], served)[0])
    check("the offline gate fails when a feed was never synced", not check_feed_traffic([sync, {"source": "server", "msg": "feeds_started", "mode": "fixture"}], served)[0])
    check("the offline gate fails when the stub saw nothing or an unidentified client", not check_feed_traffic(both, [])[0] and not check_feed_traffic(both, [{**served[0], "user_agent": "curl/8"}])[0])
    outcomes = [{**sync, "feed": feed, "outcome": outcome} for feed, wanted in FEED_OUTCOMES.items() for outcome in wanted]
    check("the feed-paths gate passes when every outcome was seen", check_feed_paths(outcomes)[0])
    check("the feed-paths gate names the outcome that never happened", check_feed_paths([r for r in outcomes if not (r["feed"] == "gcal" and r["outcome"] == "error")]) == (False, "never seen: gcal: error"))
    check("feed metrics count syncs by feed and outcome and leave timing out", feed_metrics([sync, sync, {**sync, "outcome": "throttled", "trigger": "manual"}]) == {"syncs": {"forexfactory": {"ok": 2, "throttled": 1}}, "triggers": {"manual": 1, "startup": 2}, "hosts": ["127.0.0.1"]})
    check("the secret-registered gate passes when the address is among the scanned secrets", check_secret_registered([secret], secret)[0])
    check("it fails when the address is not among them, or when the run had none", not check_secret_registered(["something else"], secret)[0] and not check_secret_registered([secret], "")[0])
    check("an error from the stub fails the error gate", [r["msg"] for r in scan_log_errors([{"source": "stub", "level": "error", "msg": "boom"}])] == ["boom"])
    # The stub treats a client that hung up as normal and any other exception as a bug that must reach stderr, where it fails the run.
    spec = importlib.util.spec_from_file_location("feed_stub", FEED_STUB)
    assert spec is not None and spec.loader is not None
    feed_stub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(feed_stub)

    def stub_stderr(error: BaseException) -> str:
        noise = io.StringIO()
        server = feed_stub.FeedServer.__new__(feed_stub.FeedServer)  # handle_error needs no socket
        with contextlib.redirect_stderr(noise):
            try:
                raise error
            except BaseException:  # noqa: BLE001 - this is the handler's own situation
                server.handle_error(None, ("127.0.0.1", 1))
        return noise.getvalue()

    check("the stub is quiet about a client that hung up", stub_stderr(ConnectionResetError()) == "" and stub_stderr(ConnectionAbortedError()) == "")
    check("the stub still reports any other exception", "ValueError" in stub_stderr(ValueError("boom")))
    # Phase 4: the container gates judge facts about the app container, so each is shown to pass on a good container and to fail,
    # for its own reason, on a container that is wrong in one way.
    healthy_check = ["CMD", "python", "-c", f"import urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:8000/api/health', headers={{'X-Request-ID': '{HEALTHCHECK_ID}'}}))"]
    untagged_check = ["CMD", "python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health')"]
    good = {
        "id": "aaa", "user": "app", "health": "healthy", "failing_streak": 0, "restart_count": 0, "healthcheck": healthy_check,
        "read_only": True, "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"], "init": True, "memory": 1 << 30, "pids": 256,
        "ports": ["127.0.0.1"], "mounts": [{"type": "volume", "name": "tj_data", "destination": "/data"}], "tmpfs": ["/tmp"],
        "probe": {
            "uid": 10001, "cap_eff": "0" * 16, "no_new_privs": True, "journal_mode": "wal", "db_bytes": 4096,
            "tables": ["trades", "notes", "external_events", "feed_state"],
            "writable": {"/app/probe": False, "/etc/probe": False, "/usr/probe": False, "/data/probe": True, "/tmp/probe": True},
        },
    }

    def worse(**changes: Any) -> dict[str, Any]:
        return {**good, **changes}

    def worse_probe(**changes: Any) -> dict[str, Any]:
        return {**good, "probe": {**good["probe"], **changes}}

    check("the health gate passes a healthy container checked through /api/health", check_container_health(good)[0])
    check("it fails an unhealthy one, one that is checked elsewhere, and one that was restarted", not any(check_container_health(bad)[0] for bad in (
        worse(health="unhealthy"), worse(healthcheck=["CMD", "true"]), worse(restart_count=2), worse(failing_streak=1))))
    check("it fails a healthcheck whose probes would be counted as test traffic", not check_container_health(worse(healthcheck=untagged_check))[0] and "request id" in check_container_health(worse(healthcheck=untagged_check))[1])
    probe = {"source": "server", "msg": "request", "request_id": HEALTHCHECK_ID, "method": "GET", "path": "/api/health", "status": 200}
    check("the container's own probe is not test traffic, whatever their number", is_probe(probe) and is_timing_dependent(probe) and request_records([probe]) == [] and not is_probe({**probe, "request_id": "t1ab"}))
    shelf = {"containers": ["mine"], "volumes": ["v1"], "networks": ["n1"]}
    check("the docker-hygiene gate passes a run that leaves Docker as it found it, even when something else went away meanwhile", check_docker_footprint(shelf, shelf)[0] and check_docker_footprint(shelf, {**shelf, "containers": []})[0])
    ok_left, why_left = check_docker_footprint(shelf, {"containers": ["mine", "tj-x"], "volumes": ["v1", "0bb4"], "networks": ["n1", "tj-net"]})
    check("it fails, naming each container, volume and network the run left", not ok_left and all(part in why_left for part in ("container tj-x", "volume 0bb4", "network tj-net")))
    check("the hardening gate passes a locked-down container", check_container_hardening(good)[0])
    bad_containers = {
        "root": worse_probe(uid=0), "writable root": worse(read_only=False), "capabilities": worse_probe(cap_eff="0000000000200000"),
        "privileges": worse(security_opt=[]), "all interfaces": worse(ports=["0.0.0.0"]), "an extra mount": worse(mounts=good["mounts"] + [{"type": "bind", "name": "", "destination": "/logs"}]),
        "writable app": worse_probe(writable={**good["probe"]["writable"], "/app/probe": True}), "no scratch space": worse_probe(writable={**good["probe"]["writable"], "/tmp/probe": False}),
        "no init": worse(init=False), "no limits": worse(memory=0),
    }
    check("the hardening gate fails each way a container can be left open", all(not check_container_hardening(bad)[0] for bad in bad_containers.values()))
    again = worse(id="bbb")
    check("the persistence gate passes a new container on the same volume with the database in it", check_volume_persistence(good, again)[0])
    check("it fails the same container, another volume, and a database that is not in WAL mode", not any(check_volume_persistence(good, bad)[0] for bad in (
        good, worse(id="bbb", mounts=[{"type": "volume", "name": "other", "destination": "/data"}]), worse_probe(journal_mode="delete") | {"id": "bbb"}, worse_probe(db_bytes=0) | {"id": "bbb"})))
    lean = {"python": "3.14.5", "tools": {"node": False, "gcc": False}, "modules": {"pytest": False}, "paths": {"/app/tests": False, "/app/.env": False}, "web_index": True, "web_files": 40, "swagger": True}
    check("the image gate passes a runtime image", check_image_contents(lean)[0])
    check("it fails an image with Node, pytest, tests, a secret, no web export or the wrong Python", not any(check_image_contents(bad)[0] for bad in (
        {**lean, "tools": {"node": True}}, {**lean, "modules": {"pytest": True}}, {**lean, "paths": {"/app/tests": True}}, {**lean, "paths": {"/app/.env": True}},
        {**lean, "web_index": False}, {**lean, "python": "3.12.1"})))
    check("the offline gate accepts the stub's container name only when told to", check_feed_traffic([{"source": "server", "msg": "feeds_started", "mode": "fixture"}, {"source": "server", "msg": "feed_sync", "feed": "forexfactory", "host": "feedstub"}, {"source": "server", "msg": "feed_sync", "feed": "gcal", "host": "feedstub"}], served, (*LOOPBACK, STUB_HOST))[0] and not check_feed_traffic([{"source": "server", "msg": "feeds_started", "mode": "fixture"}, {"source": "server", "msg": "feed_sync", "feed": "forexfactory", "host": "feedstub"}, {"source": "server", "msg": "feed_sync", "feed": "gcal", "host": "feedstub"}], served)[0])
    polled = {"source": "server", "msg": "request", "request_id": "poll-ab12cd", "method": "GET", "path": "/api/sources/status", "status": 200}
    check("a test's polls while it waits for a sync are timing-dependent, on both sides of the wire", is_timing_dependent(polled) and is_timing_dependent({"source": "test", "msg": "api_request", "request_id": "poll-ab12cd"}))
    check("an ordinary test request is not", not is_timing_dependent({"source": "server", "msg": "request", "request_id": "t1ab"}) and not is_timing_dependent({"source": "test", "msg": "api_request", "request_id": "t1ab"}))
    steady = [{"source": "server", "msg": "request", "request_id": "t1ab", "method": "GET", "path": "/api/trades", "status": 200}]
    flat = dict(phase=3, backend="native", outcomes={}, unit_summary="1 passed", exercised=[], uncovered=[], e2e_records=[], gates=[], restarts_survived=0)
    check("metrics do not change with the number of polls", compute_metrics(server_records=steady, **flat) == compute_metrics(server_records=steady + [polled] * 7, **flat))
    ticked = {"source": "server", "msg": "request", "request_id": HEALTHCHECK_ID, "method": "GET", "path": "/api/health", "status": 200}
    check("metrics do not change with the number of healthcheck probes", compute_metrics(server_records=steady, **flat) == compute_metrics(server_records=steady + [ticked] * 3, **flat))

    # The frontend gates (Phase 2): pure logic first, then real toolchain canaries further down.
    check("UI coverage counts only requests the app itself made", ui_coverage(schema, [request("GET", "/api/trades", 200, "t9")])[0] == [] and ui_coverage(schema, [request("GET", "/api/trades", 200, "web-ab12")])[0] == ["GET /api/trades"])
    check("UI coverage ignores the app's failed requests", ui_coverage(schema, [request("POST", "/api/trades", 422, "web-ab12")])[0] == [])
    served = {"source": "server", "msg": "request", "method": "GET", "path": "/api/trades", "status": 200, "request_id": "web-1"}
    seen = {"source": "client", "msg": "api_response", "method": "GET", "path": "/api/trades", "status": 200, "echoed_id": "web-1"}
    check("a response the browser saw and the server logged correlates", correlate_network([seen], [served]) == (1, 0, []))
    check("a response the server never logged is a problem", len(correlate_network([{**seen, "echoed_id": "web-2"}], [served])[2]) == 1)
    check("a different status on the two sides is a problem", len(correlate_network([{**seen, "status": 500}], [served])[2]) == 1)
    check("a mocked response (no echoed request id) is counted, not matched", correlate_network([{**seen, "echoed_id": None}], [])[:2] == (0, 1))
    with_web = compute_metrics(
        phase=2, backend="native", outcomes={}, unit_summary="", exercised=[], uncovered=[], gates=[], restarts_survived=0, e2e_records=[],
        server_records=[request("GET", "/api/trades", 200, "web-1"), request("GET", "/api/trades", 200, "t1")],
    )
    check("metrics leave the app's request volume out, so they stay identical from run to run", with_web["api"]["requests_by_status_class"] == {"2xx": 1})
    quiet = compute_metrics(
        phase=2, backend="native", outcomes={}, unit_summary="", exercised=[], uncovered=[], gates=[], restarts_survived=0,
        server_records=[request("GET", "/api/trades", 200, "web-1"), request("GET", "/api/trades", 200, "t1")],
        e2e_records=[seen, {"source": "client", "level": "info", "msg": "navigated", "url": "http://127.0.0.1:8000/trades/1"}, {"source": "test", "level": "info", "msg": "api_request"}],
    )
    check("log record counts leave out the app's requests and the browser's view of them and of its navigation", quiet["log_records"] == {"server": 1, "test": 1})
    check("a navigation event is timing-dependent, a page opening or a console warning is not", is_timing_dependent({"source": "client", "msg": "navigated"}) and not any(is_timing_dependent({"source": "client", "msg": msg}) for msg in ("page_open", "page_close", "HTTP 404: GET /api/trades/9")))
    check("browser records that are not timing-dependent are still counted", compute_metrics(phase=2, backend="native", outcomes={}, unit_summary="", exercised=[], uncovered=[], gates=[], restarts_survived=0, server_records=[], e2e_records=[{"source": "client", "level": "info", "msg": "page_open"}])["log_records"] == {"client": 1})
    check("the stub page is served until Phase 2 and a fresh build after", static_dir_for(1, Path("run")) == STUB_WEB and static_dir_for(2, Path("run")) == Path("run") / "web-dist")
    check("frontend rules accept exact-decimal code and ignore comments", scan_frontend_sources({"src/a.tsx": "const total = sum(values); // parseFloat( here is fine\n/* so is toFixed( here */\n"}) == [])
    for label, source in (
        ("parseFloat", "const x = parseFloat(text);"),
        ("toFixed", "const y = value.toFixed(2);"),
        ("Intl.NumberFormat", "new Intl.NumberFormat('en-US')"),
        ("toLocaleString", "n.toLocaleString('en-US')"),
        ("Alert.alert", "Alert.alert('Sure?')"),
        ("console", "console.log(x)"),
        ("asChild", "<Link href='/x' asChild>"),
    ):
        check(f"frontend rules flag {label}", len(scan_frontend_sources({"src/features/x.tsx": source})) == 1)
    check("asChild is allowed only in the PressableLink file", scan_frontend_sources({"src/ui/controls.tsx": "<Link asChild>"}) == [])
    check("a // inside a URL does not hide the code after it", len(scan_frontend_sources({"src/a.ts": "const u = 'http://x'; parseFloat(u)"})) == 1)
    check("the node:test summary is read in its spec form", parse_node_test_summary("\u2139 tests 5\n\u2139 pass 4\n\u2139 fail 1\n") == (4, 1))
    check("the node:test summary is read in its TAP form", parse_node_test_summary("# tests 5\n# pass 5\n# fail 0\n") == (5, 0))
    check("no summary means unknown, never zero failures", parse_node_test_summary("something else entirely") is None)
    check("API types in sync: line endings are ignored, real changes are not", contract_in_sync("a\r\nb\r\n", "a\nb\n") and not contract_in_sync("a\nb\n", "a\nc\n"))

    metrics = compute_metrics(
        phase=1, backend="native", outcomes={}, unit_summary="197 passed, 1 warning in 3.10s", exercised=[], uncovered=[],
        server_records=[], e2e_records=[], gates=[], restarts_survived=0,
    )
    check("metrics carry no timing, so they are identical from run to run", metrics["unit_tests"] == "197 passed, 1 warning")

    versions = tool_versions(py)
    check_packages(versions)
    run_dir = LOGS / "_run" / "selftest"
    remove(run_dir)
    run_dir.mkdir(parents=True)

    say("self-test: browser canaries (two must fail, one must pass)")
    server = start_server(py, run_dir / "web", port, {"STATIC_DIR": str(STUB_WEB)})
    try:
        code, _ = run_pytest(
            py,
            E2E,
            ["tests/_canary/test_clean_run_gate.py", "--output", str(run_dir / "pw-output")],
            e2e_env(server.base_url, 0, run_dir / "e2e.jsonl", run_dir / "artifacts"),
            run_dir / "pytest-canary.txt",
        )
    finally:
        stop_server(server)
    records = read_jsonl(run_dir / "e2e.jsonl", "test", utc_now())
    by_name = {node.split("::")[-1].split("[")[0]: result for node, result in summarize_tests(records).items()}
    client_errors = [r for r in records if r["source"] == "client" and r["level"] == "error"]
    allowed = [r for r in records if r["source"] == "client" and r.get("allowed")]
    check("canary: an unexpected console.error fails the test", by_name.get("test_unallowed_console_error") == "failed")
    check("canary: an uncaught page error fails the test", by_name.get("test_unallowed_page_error") == "failed")
    check("canary: an allow-listed console.error passes", by_name.get("test_allowed_console_error_passes") == "passed")
    check("canary: both unexpected errors reached the log at error level", len(client_errors) == 2)
    check("canary: the allow-listed error is logged as a warning that carries its reason", len(allowed) == 1 and allowed[0]["level"] == "warning")
    check("canary: pytest exits non-zero", code != 0)

    say("self-test: persistence canary (the after-restart tests must fail on a database that never saw the canary)")
    fresh = start_server(py, run_dir / "fresh", port, {"STATIC_DIR": str(STUB_WEB)})
    try:
        code, _ = run_pytest(
            py,
            E2E,
            ["-m", "after_restart and p1", "--output", str(run_dir / "pw-fresh")],
            e2e_env(fresh.base_url, 1, run_dir / "e2e-fresh.jsonl", run_dir / "artifacts"),
            run_dir / "pytest-fresh.txt",
        )
    finally:
        stop_server(fresh)
    fresh_outcomes = {node.split("::")[-1].split("[")[0]: result for node, result in summarize_tests(read_jsonl(run_dir / "e2e-fresh.jsonl", "test", utc_now())).items()}
    check("canary: the after-restart tests fail when the data did not survive", code != 0 and fresh_outcomes.get("test_the_canary_survived_the_restart_unchanged") == "failed")

    say("self-test: server canaries (an unhandled exception, and a write that is never committed)")
    status = None
    boom = start_server(py, run_dir / "boom", 0, {}, app="canary_app:app", app_dir=E2E / "tests" / "_canary")
    try:
        try:
            _OPENER.open(f"{boom.base_url}/boom", timeout=5)
        except urllib.error.HTTPError as exc:
            status = exc.code
        forgotten = urllib.request.Request(f"{boom.base_url}/canary/forgotten-commit", method="POST", headers={"X-Request-ID": "canary-write-1"})
        with _OPENER.open(forgotten, timeout=5):
            pass
    finally:
        stop_server(boom)
    boom_records = parse_server_output(read_text(run_dir / "boom" / "server.out"), read_text(run_dir / "boom" / "server.err"), utc_now())
    flagged = scan_log_errors(boom_records)
    check("canary: an unhandled server exception answers 500", status == 500)
    check("canary: it is logged as a 500 error with the request id", any(r.get("path") == "/boom" and r.get("status") == 500 and r.get("request_id") for r in flagged))
    check("canary: the traceback is logged as an error", any("RuntimeError" in str(r.get("exc", "")) for r in flagged))
    check("canary: a write that answers 200 but never commits is flagged", uncommitted_writes(boom_records) == ["POST /canary/forgotten-commit (canary-write-1)"])
    check(
        "canary: its rolled-back transaction is logged with the writes it discarded",
        any(r.get("request_id") == "canary-write-1" and int(r.get("writes", 0)) >= 1 for r in rollbacks(boom_records)),
    )

    say("self-test: the fixture-mode guard (an app pointed at a real feed host must refuse to start)")
    try:
        refused = start_server(py, run_dir / "live-guard", 0, {"FEEDS_MODE": "fixture"})  # FF_FEED_URL is left at the real host
    except HarnessError:
        refused = None
    else:
        stop_server(refused)
    check("canary: FEEDS_MODE=fixture with a real feed address keeps the app from starting", refused is None)
    guard_log = read_text(run_dir / "live-guard" / "server.err") + read_text(run_dir / "live-guard" / "server.out")
    check("canary: the refusal says which setting is wrong", "FF_FEED_URL points elsewhere" in guard_log)

    say("self-test: container canaries (a container left open, and one that cannot pass its healthcheck, must be caught)")
    try:
        docker_versions()
        have_docker = True
    except HarnessError:
        have_docker = False
    if not have_docker:
        say("  Docker is not running: the container canaries are skipped, and the run says so")
    else:
        # A real container of the real image, started the way a careless person would: every protection compose adds left off,
        # and a healthcheck that always fails. The gates must read Docker's own account of it and refuse it, each for its reasons.
        docker("build", "--file", str(ROOT / "docker" / "app.Dockerfile"), "--tag", APP_IMAGE, str(ROOT), timeout=1800)
        canary = ComposeStack("tj-canary", [], {})
        name = "tj-canary-open"
        docker("rm", "--force", "--volumes", name, check=False)
        docker("run", "--detach", "--name", name, "--publish", "0.0.0.0::8000", "--health-cmd", "exit 1", "--health-interval", "1s", "--health-retries", "1", APP_IMAGE)
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and canary.inspect(name)["State"].get("Health", {}).get("Status") != "unhealthy":
                time.sleep(1)
            open_facts = collect_container_facts(canary, Server(None, "", None, None, run_dir, stack=canary, container=name, service="app"))  # type: ignore[arg-type]
        finally:
            docker("rm", "--force", "--volumes", name, check=False)
        ok_open, why_open = check_container_hardening(open_facts)
        check("canary: a container with no protections is refused by the hardening gate", not ok_open)
        check("canary: the refusal names the open root filesystem, the capabilities, the new privileges and the interfaces", all(
            phrase in why_open for phrase in ("root filesystem is writable", "capabilities are not dropped", "new privileges", "not loopback only")))
        ok_health, why_health = check_container_health(open_facts)
        check("canary: a container whose healthcheck fails is refused by the health gate", not ok_health and "unhealthy" in why_health)
        check("canary: the probe really ran inside it (it saw the image's non-root user and a writable root)", open_facts["probe"].get("uid") == 10001 and open_facts["probe"]["writable"].get("/app/probe") is not None)
        # The image declares /data a volume, so a container made from it owns an anonymous one. Removed the careless way (plain `rm`), the
        # volume stays: the docker-hygiene gate must see it. Removed with its volumes, nothing stays.
        leak = "tj-canary-leak"
        docker("rm", "--force", "--volumes", leak, check=False)
        before = docker_footprint()
        docker("create", "--name", leak, APP_IMAGE)
        docker("rm", leak)
        ok_leak, why_leak = check_docker_footprint(before, docker_footprint())
        for volume in docker_footprint()["volumes"]:
            if volume not in before["volumes"]:
                docker("volume", "rm", "--force", volume, check=False)  # the canary's own leftover
        check("canary: a volume left behind by removing a container the careless way is caught by the docker-hygiene gate", not ok_leak and "volume" in why_leak)
        docker("create", "--name", leak, APP_IMAGE)
        docker("rm", "--volumes", leak)
        check("canary: removing the container with its volumes leaves Docker as it was", check_docker_footprint(before, docker_footprint())[0])

    say("self-test: frontend toolchain canaries (a type error and a failing unit test must be caught)")
    tools = find_node_tools()
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        write_text_lf(folder / "bad.ts", 'const count: number = "not a number";\n')
        write_text_lf(folder / "tsconfig.json", json.dumps({"compilerOptions": {"strict": True, "noEmit": True, "types": []}, "files": ["bad.ts"]}))
        tsc = FRONTEND / "node_modules" / "typescript" / "bin" / "tsc"
        code, output = run_tool([tools["node"], str(tsc), "-p", str(folder / "tsconfig.json")], folder, run_dir / "canary-tsc.txt")
        check("canary: tsc rejects a type error with a non-zero exit", code != 0 and "TS2322" in output)
        write_text_lf(folder / "failing.test.mjs", 'import test from "node:test";\ntest("fails on purpose", () => { throw new Error("boom"); });\n')
        code, output = run_tool([tools["node"], "--test", str(folder / "failing.test.mjs")], folder, run_dir / "canary-node-test.txt")
        check("canary: a failing unit test exits non-zero and its summary shows the failure", code != 0 and parse_node_test_summary(output) == (0, 1))
        check("canary: the web build check fails on an empty export", not check_web_build(folder / "no-such-export")[0])
        check("canary: the native bundle check fails when a platform has no Hermes bundle", not check_native_bundles(folder / "no-such-export")[0])

    say("")
    for name, ok in checks:
        say(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    bad = [name for name, ok in checks if not ok]
    say(f"self-test: {len(checks) - len(bad)}/{len(checks)} checks passed")
    return 1 if bad else 0


# --- entry point ---------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a phase's verification loop.")
    parser.add_argument("phase", nargs="?", type=int, choices=range(MAX_PHASE + 1), help="phase to verify; earlier phases run as regression")
    parser.add_argument("--backend", choices=("native", "compose"), default="native")
    parser.add_argument("--port", type=int, default=0, help="server port (default: any free port)")
    parser.add_argument("--python", type=Path, help="interpreter holding the dev dependencies (default: .venv, else this one)")
    parser.add_argument("--self-test", action="store_true", help="prove the gates fail when they should")
    args = parser.parse_args(argv)
    if args.phase is None and not args.self_test:
        parser.error("give a phase number or --self-test")
    py = resolve_python(args.python)
    try:
        if args.self_test:
            return self_test(py, args.port)
        return run_phase(args.phase, py, args.port, args.backend)
    except HarnessError as exc:
        say(f"verify: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
