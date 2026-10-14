# Trading Journal & Calendar: Blueprint

**Status:** Phases 0 to 4 are built and verified: 0a to 3 natively (2026-10-13), and 0b and 4 in containers with `--backend compose` (2026-10-14). Blueprint locked 2026-10-13. This file records what was decided and why. [CLAUDE.md](../CLAUDE.md) stays the short rule sheet. Change a decision by adding a dated row to the change log (section 11), not by editing it silently.

**Legend:** *Locked* = decided by the project owner. *Accepted* = proposed by Claude and approved by the owner (P1 to P10 and the Phase 2 frontend decisions F1 to F8 on 2026-10-13; the Phase 3 connector decisions C1 to C9 in section 4.3 and frontend decisions F9 to F14 in section 5 on 2026-10-14). *Built* = a choice Claude made while building a later phase and recorded for review (the Phase 4 decisions K1 onwards in section 6.1 are of this kind). Amendments made while building are noted inline.

## 1. Scope

**V1 product.** A single-user, local-first, forex-first trading journal. Trades are entered by hand (instrument, side, lot size, entry and exit price, direct P&L), annotated with notes and tags, and reviewed on a month calendar. The calendar overlays two read-only feeds: upcoming ForexFactory economic events and one Google Calendar.

**Constraints (from CLAUDE.md).** Zero paid APIs. Free or public feeds only. Docker plus headless Playwright verification. Structured logs in `logs/`. Screenshots in `artifacts/phase_{N}/screenshots/`.

**Not in V1.** Auth or multi-user. CSV or broker import. Market data or computed P&L. Event actuals or historical backfill. Writing to Google Calendar. Native-device E2E. Hosted deployment. Scraping any site's HTML.

## 2. Decisions

| ID | Decision | Status | Revisit when |
|----|----------|--------|--------------|
| D1 | Forex-first generic schema. Manual entry of instrument, side, lot size, entry/exit price and **user-entered P&L**. No market-data feed. | Locked | CSV import or non-forex instruments |
| D2 | Expo **Web** is the only E2E-verified target. iOS and Android only have to bundle (`expo export`). Single-user, local-first, no auth. | Locked | Device testing, or any exposure beyond loopback (add a static token first) |
| D3 | ForexFactory: upcoming events only, from the public weekly export (JSON by default; its XML form is read too, section 4.3). No HTML scraping. History accumulates from snapshots. No `actual` values. | Locked | Actuals or backfill become necessary (FRED, CSV) |
| D4 | Google Calendar: read-only through the calendar's secret iCal URL. No OAuth, no service account. | Locked | Write-back or multiple users |
| D5 | Playwright for Python (`pytest-playwright`), one suite: an `api` fixture (Playwright's `APIRequestContext`) for API tests, the `page` fixture for DOM tests. | Locked | n/a |
| D6 | One app image: a Node stage builds the Expo web export, FastAPI serves it at `/` and the API at `/api`. A Playwright `e2e` sidecar tests it. Same origin, no CORS outside dev. | Locked | n/a |
| D7 | SQLAlchemy 2.0 + Alembic. SQLite (WAL) on named volume `tj_data`. PostgreSQL stays a config swap. Pin `sqlalchemy>=2.0.54,<2.1`. | Locked | Adopting SQLAlchemy 2.1 (2.1.4 exists): read its migration notes first |
| D8 | Native dev loop (`uvicorn --reload`, `expo start`). Docker only for automated verification. | Locked | n/a |
| D9 | JSONL structured logs. LF line endings enforced. `git init` in Phase 0 (done). No commits until asked. | Locked | n/a |
| D10 | Paths follow CLAUDE.md: `artifacts/phase_{N}/screenshots/` and `logs/phase_{N}.log`. | Locked | n/a |

| ID | Accepted proposal | Why |
|----|----------|-----|
| P1 | Sync stack: sync SQLAlchemy sessions, sync `httpx2`, plain `def` route handlers, no async DB driver. Amended 2026-10-13: `httpx2`, the maintained successor by the same author, replaces `httpx` (last release 2024-12; Starlette 1.7 deprecates `httpx` for `httpx2`). | SQLite serializes writes anyway; fewer moving parts. |
| P2 | No scheduler library. One lifespan-managed thread per feed, schedule state persisted in `feed_state`, exactly one uvicorn worker. | Two periodic jobs do not justify a dependency. A second worker would double-fetch and trip the feed's rate limit. |
| P3 | Money is `Decimal` everywhere and JSON carries strings, never `float`. Stored as scaled integers through a `TypeDecorator`, with one uniform scale of 1e-8 for every money, price and lot field, so cents and pips are display formatting only. | SQLite's `Numeric` is float-backed, so sums drift. |
| P4 | All instants are stored and sent as UTC (ISO 8601 with `Z`). A trade's calendar day is the date of `closed_at` in `APP_TIMEZONE` (default `UTC`; set your zone in `.env`). Open trades are excluded from aggregates, and in list filters an open trade counts on the day it opened. | One unambiguous rule for the calendar view. |
| P5 | Chromium only in V1. The `e2e` service runs with `ipc: host` and `init: true`. | Playwright's Docker guidance; keeps runs stable. |
| P6 | `scripts/verify.py` (stdlib-only Python) drives verification. Backends: `compose` (canonical) and `native` (fallback while Docker is unavailable; recorded in the log header so it is never mistaken for container evidence). | One script for Windows and Linux. Tests only need `BASE_URL`, so the same suite runs on both backends. |
| P7 | Compose publishes `127.0.0.1:8000` only. | No auth in V1; default publishing would expose the app to the LAN. |
| P8 | Determinism: verification never calls live feeds (`FEEDS_MODE=fixture`). Tests do not depend on today's date (fixed-date seeds, injectable clock `APP_NOW_OVERRIDE`, honored only when `APP_ENV=test`). No test-only HTTP endpoints (fresh volume per run, seed through the public API). | Repeatable runs, protects the feed's rate limit, no backdoors in the shipped image. |
| P9 | Clean-run rule: an unexpected browser `console.error`, `pageerror`, failed request or HTTP 5xx, or an `error`-level server log line (any stderr output included), fails the run. Browser errors can be allow-listed per test with `@pytest.mark.allow_console_errors(regex, reason=...)`. Server-side allow-listing arrives with the first test that needs it (Phase 4 failure paths). | Client and server problems surface without per-test assertions. |
| P10 | Python deps: `requirements.in` compiled to a pinned `requirements.txt` with `uv pip compile` (uv lives in the dev venv, not in Docker). Python 3.14 on host and in the image; fall back to 3.13 if a dependency lacks a 3.14 wheel. | Reproducible without extra runtime tooling. |

## 3. Architecture

### 3.1 Topology

```text
e2e container (Playwright, Chromium)  --HTTP-->  app container (FastAPI, 1 worker)
  API tests: api fixture                           /api/*  routers
  DOM tests: page fixture                          /*      Expo web export (static files)
  writes client + test JSONL                       SQLite (WAL) on named volume tj_data
                                                   feed threads --> ForexFactory weekly JSON
                                                                --> Google secret iCal URL

Host publishes 127.0.0.1:8000 only. ./logs/_run and ./artifacts are bind-mounted.
In verification, feeds point at fixtures (FEEDS_MODE=fixture); nothing calls out.
```

### 3.2 Repository layout

```text
TradingJournal/
  CLAUDE.md
  docs/BLUEPRINT.md
  backend/               FastAPI app, Alembic, unit tests (no browser)
    app/                 main.py, api/, core/ (config, clock, logging), db/, schemas/, services/ (incl. feeds, scheduler), static/swagger/, connectors/
    migrations/  alembic.ini  log_config.json  requirements{,-dev}.{in,txt}
  frontend/              Expo (TypeScript, Expo Router): src/{app,features,ui,lib,api,state}, test/, tools/
  e2e/                   Dockerfile, requirements.txt, conftest.py, support/ (journal, ui, feeds, events_ui, feed_stub), tests/p0_*, p1_*, p2_*, p3_*, ...
  fixtures/              the recorded ForexFactory week (JSON and XML), the fixture weeks, sample .ics files, build tools, README
  scripts/verify.py
  docker-compose.yml     the production definition: one container, one named volume
  docker/                app.Dockerfile, compose.verify.yml, compose.smoke.yml, and an allow-list ignore file for the app image
  .env.example  .dockerignore  docs/RUNBOOK.md
  logs/                  gitignored, regenerated
  artifacts/phase_N/screenshots/   tracked as phase evidence
```

Phase 0a added `backend/log_config.json`, `backend/app/stub_web/`, `backend/requirements-dev.in` and `.txt`, `backend/pytest.ini`, `backend/tests/`, `e2e/pytest.ini`, `e2e/tests/_canary/` and `scripts/verify.py`. Dependencies are `*.in` files compiled to pinned `*.txt` locks by uv (section 6.5). Phase 1 added `backend/app/{api,db,schemas,services}`, `backend/app/static/swagger/` (vendored Swagger UI), `backend/migrations/`, `backend/alembic.ini`, `.env.example` and `e2e/tests/p1_journal/`. Phase 2 added `frontend/` (section 5), `e2e/support/` (the shared `Journal` helper and the browser helpers in `ui.py`) and `e2e/tests/p2_frontend/`, and moved the `journal` fixture into the root `e2e/conftest.py`. Phase 3 added `backend/app/connectors/` (base, http, forexfactory, gcal, registry), `backend/app/services/{feeds,events,scheduler}.py`, `backend/app/core/clock.py`, migration `0002`, `fixtures/`, `e2e/support/{feed_stub,feeds,events_ui}.py`, `e2e/tests/p3_connectors/` and, in the frontend, `features/{events,sources}.tsx`, `ui/impact.tsx`, `lib/events.ts` and `tools/derive-impact-ramp.mjs`. Phase 4 added `docker-compose.yml`, `docker/`, `e2e/Dockerfile`, `.dockerignore`, `docs/RUNBOOK.md`, `backend/app/core/security.py`, `backend/app/tools/backup.py`, `e2e/tests/p4_hardening/` and `e2e/tests/p4_deployment/`, and the compose backend of `scripts/verify.py`.

### 3.3 Runtime modes

| | dev (native loop) | test (verification) | prod |
|---|---|---|---|
| `APP_ENV` | `dev` | `test` | `prod` |
| API | `uvicorn --reload` on :8000 | container (or subprocess on the native backend) on :8000 | container on :8000 |
| Web | `expo start --web` on :8081 | static export that `verify.py` builds into `logs/_run/phase_N/web-dist`, served by FastAPI | static export served by FastAPI |
| API base URL | `EXPO_PUBLIC_API_URL=http://localhost:8000` | same origin, `/api` | same origin, `/api` |
| CORS | allow `http://localhost:8081` only | off | off |
| Feeds | `live` or `off` | `fixture` (the app refuses any feed address that is not loopback) | `live` |
| Clock | system | system for everything but the feeds, whose clock starts at `APP_NOW_OVERRIDE` | system |
| Database | `<repo>/data/dev.db` | fresh volume or temp file per run | volume `tj_data` |

### 3.4 Configuration

| Variable | Default | Notes |
|----------|---------|-------|
| `APP_ENV` | `prod` | `dev`, `test` or `prod` (section 3.3) |
| `DATABASE_URL` | `sqlite:////data/tj.db` in the container, `sqlite:///<repo>/data/dev.db` natively | The container file lives on volume `tj_data`. The folder of a file database is created on first use |
| `APP_TIMEZONE` | `UTC` | IANA name. Decides which calendar day a trade falls on |
| `LOG_LEVEL` | `INFO` | |
| `AUTO_MIGRATE` | `true` | Run `alembic upgrade head` at startup. Safe because the app runs a single worker |
| `STATIC_DIR` | `/app/web` in the image, unset natively | Expo web export served at `/` |
| `FEEDS_MODE` | `off` | `live` (the real hosts), `fixture` (loopback hosts only: the app refuses to start if an address is anywhere else) or `off`. Nothing runs until you choose `live` |
| `FF_FEED_URL` | `https://nfs.faireconomy.media/ff_calendar_thisweek.json` | The XML form of the export works too. Pointed at the fixture stub in tests |
| `FF_POLL_MINUTES` | `60` | Minimum 30. The feed refreshes hourly and the host limits downloads per IP |
| `GCAL_ICAL_URL` | unset | **Secret.** `.env` only, redacted everywhere. Without it the calendar feed is off and the app says why |
| `GCAL_POLL_MINUTES` | `30` | Minimum 5 |
| `SYNC_COOLDOWN_SECONDS` | `300` | Least time between two manual syncs of one feed |
| `FEED_TICK_SECONDS`, `FEED_TIMEOUT_SECONDS`, `FEED_MAX_BYTES` | `5`, `15`, `10000000` | How often a feed's worker looks at its schedule, how long a host may take (a host that drips bytes is cut off at twice that), and the largest answer accepted |
| `REDACT_ENV` | `GCAL_ICAL_URL` | Env var names whose values are masked in logs and errors |
| `APP_NOW_OVERRIDE` | unset | ISO instant with a UTC offset. The feeds' clock starts there and then runs in real time. Honored only when `APP_ENV=test` |
| `MAX_REQUEST_BYTES` | `1048576` | The largest request body the API accepts. A larger one is answered with 413 |
| `FEEDS_FIXTURE_HOSTS` | unset | Verification only: plain host names, besides loopback, that `FEEDS_MODE=fixture` may talk to (the stub's container name) |
| `APP_PORT`, `TJ_IMAGE_TAG` | `8000`, `local` | Compose only: the port published on 127.0.0.1, and the tag of the image it builds |
| `EXPO_PUBLIC_API_URL` | unset | Build-time, dev and native only. Unset means same-origin `/api` |

## 4. Backend

### 4.1 Data model (V1)

```text
trades
  id            integer, primary key (never reused: SQLite AUTOINCREMENT)
  instrument    text, not null          uppercased, [A-Z0-9][A-Z0-9/._-]{0,19} (EURUSD, EUR/USD, XAUUSD)
  side          text, not null          long or short
  lot_size      scaled int, not null    > 0
  entry_price   scaled int, not null    > 0
  exit_price    scaled int, null        > 0; null while open
  opened_at     utc datetime, not null
  closed_at     utc datetime, null      null = open; must be >= opened_at
  pnl           scaled int, null        user-entered, account currency, any sign; null while open
  notes         text, null              the trade's own journal note, at most 10,000 characters
  created_at, updated_at
  indexes on instrument, opened_at and closed_at

tags          id, name (unique, case-insensitive; the first spelling is kept), at most 40 characters
trade_tags    trade_id -> trades (cascade), tag_id -> tags (cascade), primary key (trade_id, tag_id)
notes         id, day (date, not null), body (text, not null), created_at, updated_at    a note for a calendar day

external_events   (Phase 3)
  id (never reused), source (forexfactory or gcal), external_key (a hash, or the iCal UID and instance), title,
  description, location, url (null), currency (news: USD ... or ALL), impact (news: low, medium, high, holiday or unknown),
  forecast, previous, all_day, start_at and end_at (UTC, null for an all-day event), start_date and end_date
  (all-day only, the end exclusive as iCalendar writes it), first_seen_at, updated_at
  unique (source, external_key); a CHECK makes an event timed or all-day, never both

feed_state        (Phase 3, one row per source)
  source (primary key), state (idle, queued or running), status (never, ok, throttled, bad_content or error),
  message (a short fixed phrase, never an address), http_status, last_attempt_at, last_success_at, next_due_at,
  next_manual_at, consecutive_failures, etag, last_modified, updated_at
```

Rules:
- A trade is open (no `exit_price`, `closed_at` or `pnl`) or closed (all three). `closure_errors` in `services/trades.py` is the single source of that rule and reports errors per field. The database repeats it, with the positive lot, price and ordering checks, as CHECK constraints that the migration tests exercise.
- Money input allows at most 10 whole digits and 8 decimals, so it always fits the scaled-integer column. Anything finer is rejected, never rounded. Timestamps must carry a UTC offset.
- Tags are passed by name (at most 20 per trade; letters, digits, spaces and `-/.#+_`), deduplicated ignoring case, created on demand and deleted with their last trade.
- A trade's own notes are its `notes` field. The `notes` table holds day notes.
- Events: a timed event is a UTC instant (two for a span), an all-day event is a date (two for a span), so a holiday keeps its own day whatever zone is displayed. `start_day` and `end_day` (inclusive) are computed when read, in `APP_TIMEZONE`, like trade days: an event that crosses local midnight covers both days, one that ends exactly at midnight does not spill into the next.
- Revision `0001` is the baseline migration, and `0002` adds `external_events` and `feed_state`. The app runs `alembic upgrade head` at startup and `/api/ready` checks the database is at head. SQLite runs with WAL, `foreign_keys=ON` and a busy timeout. Alembic uses batch mode for SQLite.

### 4.2 API surface (V1)

| Endpoint | Purpose | Phase |
|----------|---------|-------|
| `GET /api/health` | Liveness. 200 whenever the process is up | 1 |
| `GET /api/ready` | DB reachable and migrations at head. Used by the compose healthcheck | 1 |
| `POST /api/trades`, `GET /api/trades`, `GET/PATCH/DELETE /api/trades/{id}` | Trade CRUD. POST answers 201 with a `Location` header and DELETE answers 204. PATCH is a JSON merge patch: omitted fields stay, `null` clears `exit_price`, `closed_at`, `pnl` and `notes`. List filters: `from` and `to` (inclusive days in `APP_TIMEZONE`), `instrument`, `side`, `status`, `tag` (repeatable, all must match), `sort` (`journal_at`, `opened_at`, `closed_at`, `pnl`), `order`, `limit`, `offset`. A trade belongs to the day it was closed, or opened while still open. Lists return `{items, total, limit, offset}` | 1 |
| `POST /api/notes`, `GET /api/notes`, `GET/PATCH/DELETE /api/notes/{id}` | Notes for a calendar day. List filters: `from`, `to`, `limit`, `offset` | 1 |
| `GET /api/tags` | Tag names with usage counts | 1 |
| `GET /api/calendar/month?year=&month=` | Per-day P&L, trade count, wins and losses, plus month total, bucketed in `APP_TIMEZONE` | 1 |
| `GET /api/docs`, `GET /api/openapi.json` | OpenAPI UI and schema, kept under `/api` so the SPA owns every other path | 1 |
| `GET /api/events?from=&to=&source=&impact=&currency=&limit=&offset=` | Events from outside calendars (news and the personal calendar) that cover any day of the range (inclusive days in `APP_TIMEZONE`), ordered by day, all-day first, then time. A multi-day event is listed once and carries `start_day` and `end_day`. `impact` repeats; `currency` also matches news for every currency (`ALL`). Lists return `{items, total, limit, offset}` | 3 |
| `GET /api/sources/status` | Per feed: label, enabled (and why not), state, status, a short message, HTTP status, last attempt and last success, next due, next manual, consecutive failures, event count, poll minutes. Never returns an address | 3 |
| `POST /api/sync?source=` | Ask for a refresh now: every feed, or each `source` named. Answers at once: 202 with what became of each feed, 429 with `Retry-After` inside the cooldown, 409 when nothing could be queued (already syncing, or switched off). The fetch runs on the feed's own worker thread. Replaces the planned `POST /api/events/refresh` | 3 |

**Errors.** Unknown ids answer 404 with `{"detail": "Trade 42 not found"}`. Invalid input answers 422 with FastAPI's `{"detail": [{loc, msg, type}]}` shape, where `loc` names the field, for example `["body", "pnl"]`. Unknown JSON fields are rejected.

**Transactions and logging.** Services commit before the endpoint returns (`services/uow.py`). FastAPI runs a `yield` dependency's teardown after the response has been sent, so committing there would let a client see success for a write that then fails. Repositories flush but never commit. Every commit, and every rolled-back transaction that had written something, is logged as a `db_transaction` record carrying the request ID of the request that caused it. Services also log domain events (`trade_created`, `trade_updated` with the changed field names, `trade_deleted`, `note_*`) with ids and names only, never amounts or note text.

**Hardening (Phase 4).** Every answer carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, a permissions policy that turns the camera, microphone, location, payment and USB off, and same-origin cross-origin opener and resource policies. HTML carries a content security policy (`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'` and a few more), and the API's own answers say `Cache-Control: no-store`. The docs page's one inline script is allowed by its hash. A request body over `MAX_REQUEST_BYTES` is answered with 413 (`{"detail": ...}`): a declared length before a byte is read, a chunked body as it is counted. `python -m app.tools.backup` takes a consistent, integrity-checked copy of the database while the app runs (`docs/RUNBOOK.md`).

### 4.3 Connectors (Phase 3, as built)

**ForexFactory (D3).**
- Source: the public weekly export, `https://nfs.faireconomy.media/ff_calendar_thisweek.json` by default, a public file with no formal API or schema guarantee. The host publishes the same week as XML too, and the parser reads either, telling them apart by the body, never by the content type.
- JSON, observed 2026-10-13: an array of objects with exactly `title`, `country` (currency code or `All`), `date` (ISO 8601 with UTC offset, for example `2026-10-11T19:00:00-04:00`), `impact` (`Low`, `Medium`, `High`, `Holiday`), `forecast` and `previous` (strings, possibly empty). 108 events covering one week. No `actual`, no ID.
- XML, observed the same day: `<weeklyevents>` of `<event>` with `title`, `country`, `date` (`MM-DD-YYYY`), `time` (`h:mmam` or `h:mmpm`), `impact`, `forecast`, `previous` and `url`, declared `windows-1252`, most values in CDATA. **It carries no zone, and its date and time are UTC.** Compared event by event with the JSON, all 108 events agree when read that way. The recorded pair is in `fixtures/forexfactory/recorded/` as the evidence, and a time that is not a clock time (`All Day`, `Tentative`) makes an all-day event. Only the public export is read. No HTML page is ever scraped.
- Reported limits (ForexFactory forum post, Aug 2024, "subject to change", not independently verified): 2 downloads per 5 minutes per IP across all formats, file refreshed hourly, and an over-limit request returns an HTML "Request Denied" page instead of the data.
- Polling: hourly (floor 30 minutes). The schedule is persisted in `feed_state` so restarts do not refetch early, and a conditional request (ETag, Last-Modified) is sent whenever the host gave validators, so an unchanged week is a 304. HTML, unusable data or HTTP 429 sets status `throttled` or `bad_content`, backs off 15, 30, 60, then 120 minutes (cap) and keeps serving the stored events. A throttled request is never retried in the same cycle.
- Parsing: `date` to UTC, `impact` lower-cased (anything else is kept as `unknown`, never guessed), currency upper-cased (`All` becomes `ALL`). A malformed item is dropped and counted. If more than half the items are unusable the fetch is `bad_content`, and so is a feed with no events at all. A body that is the host's "Request Denied" page is `throttled`. XML with a DOCTYPE or entity declarations is refused.
- Key: `sha1(title|currency|start_utc)`, so an event moved by the host is a removal and an addition. Reconcile (`upsert_window`): add and update what the feed holds, delete only future rows inside the fetched window that it no longer lists, never delete the past. Forecast and previous revisions overwrite (no revision history in V1).
- Sends `User-Agent: TradingJournal/0.3 (personal, single-user)`.

**Google Calendar (D4).**
- Source: the calendar's secret iCal address (Google Calendar settings, Integrate calendar, Secret address in iCal format), held in `GCAL_ICAL_URL` (a `SecretStr`). It is a bearer credential: `.env` only, masked in logs, never returned by the API or rendered in the UI.
- Parsed with `icalendar`, recurrences expanded by `recurring-ical-events` (RRULE, EXDATE, RECURRENCE-ID overrides, TZID and VTIMEZONE, all-day dates, a UTC time, `X-WR-TIMEZONE`). Each UID's events are expanded on their own, so one broken series costs one series. A floating time is read in the calendar's own zone, else `APP_TIMEZONE`. A cancelled instance is dropped. A description Google wrote as HTML becomes plain text.
- Identity: a one-off event is its UID, so moving or renaming it updates its row. An occurrence of a series is its UID plus the slot it was generated for, and a moved occurrence keeps the slot it was moved from.
- Mirror (`mirror`): each successful fetch makes the stored events exactly the expansion of the window [now - 60 days, now + 400 days]. A failed fetch leaves them as they were. A body that is not a calendar is refused, and so is one that does not end with `END:VCALENDAR`: a download cut off mid-event would otherwise read as a calendar with fewer events, and the mirror would delete the rest. A calendar that is valid and empty empties the mirror.
- Google does not guarantee iCal freshness, so the UI shows "last synced" per source from `feed_state`.

**Common (as built).**
- A feed is a `Source` (name, label, schedule, reconcile policy, `fetch`, `parse`) made from the settings in `connectors/registry.py`. A connector never touches the database: it returns events or raises a `FeedError` (`Throttled`, `BadContent` or `FetchFailed`) whose message is a short fixed phrase, never the text of an exception, because those carry the address.
- `FeedService` runs a sync as three steps (mark it running, fetch and parse with no transaction open, reconcile and record the outcome in one transaction). A failure of any kind leaves the stored events untouched. One daemon thread per enabled feed (`FeedWorker`), started and stopped with the app, sleeps until its feed is due or is poked, so a slow or dead host can only ever hold up its own worker.
- A manual sync is queued by the request itself, in its own transaction (`feed_state.state = queued`), and the worker is poked: the request is answered at once and is always backed by a commit. A feed that is queued or running answers 409, one inside its cooldown 429. A `running` mark left by a crash is cleared at startup.
- HTTP through `httpx2`: a per-read timeout plus an overall deadline of twice that, redirects limited, a size limit, `trust_env` only in `live` mode.
- Time comes from an injectable `Clock`. In verification the feeds' clock is a `ShiftedClock` that starts at `APP_NOW_OVERRIDE` and runs in real time, so "this week" in the fixtures is a fixed week.
- Fixture mode refuses to start when `FF_FEED_URL` or `GCAL_ICAL_URL` is not a loopback address (the error names the setting, not the secret), so a test run cannot reach the internet by accident. The verification stub serves `fixtures/` over real HTTP on loopback and is scripted from the tests (variants a and b of each feed, the XML or JSON form, and the failures: 429, 500, 503, 404, the host's refusal page, a maintenance page, a truncated body, an empty feed and a slow answer).

**Connector decisions (Accepted 2026-10-14).**

- **C1, both forms of the ForexFactory export are read.** JSON is the default address (D3), and the XML form works too, because you asked for the XML or RSS feed and the host publishes both. Their times were reconciled empirically, not assumed (above).
- **C2, one endpoint for refreshing.** `POST /api/sync` (repeat `source`) replaces the planned `POST /api/events/refresh?source=`: one request can refresh every feed, and the answer says what happened to each.
- **C3, two reconcile policies.** News accumulates and never forgets the past; the calendar is a mirror. The truncated-download guard exists because a mirror believes what it is given.
- **C4, an empty but valid calendar empties the mirror,** because that is what deleting every event in Google means. Say so if you would rather a mirror never shrank to nothing.
- **C5, days are worked out when read,** in `APP_TIMEZONE`, the same way trade days are, so changing the zone re-buckets events as it re-buckets trades.
- **C6, a moved news event is a new event.** The feed has no ids, so a release rescheduled by the host is a removal and an addition (only future events inside the fetched window are removed).
- **C7, a manual sync ignores the backoff and respects the cooldown.** Pressing "Sync now" after a failure tries again at once, at most every `SYNC_COOLDOWN_SECONDS` per feed (300 s by default).
- **C8, the schedule is stored, not remembered.** `next_due_at`, the cooldown and the validators survive a restart, so restarting the app never refetches early.
- **C9, the test clock only moves the feeds.** `APP_NOW_OVERRIDE` shifts the feeds' clock and nothing else, and only when `APP_ENV=test`.

## 5. Frontend

**Stack (as built, Phase 2).** Expo SDK 57 with Expo Router (`src/app`), React 19.2 and React Native 0.86 with react-native-web 0.21, TypeScript 6 in strict mode, the React Compiler on, `web.output: "single"`. Server state is TanStack Query v5. The API client is `openapi-fetch` over types that `openapi-typescript` generates from `/api/openapi.json` (`src/api/schema.d.ts`, never edited by hand). Light theme only. There is no UI library: the primitives in `src/ui` are about 700 lines.

**Serving.** `expo export --platform web` writes static files. FastAPI serves them at `/`, falls back to `index.html` for any extension-less path outside `/api`, and answers unknown `/api/*` paths with a JSON 404. The app and the API share one origin, so `EXPO_PUBLIC_API_URL` is empty and no CORS is needed. In dev, `expo start --web` runs on :8081 and the API allows that origin when `APP_ENV=dev`.

**Layout.**

```text
frontend/src/
  app/        routes: _layout (providers, shell, error boundary), index, calendar, trades/{index,new,[id]}, day/[date], notes/[id], +not-found
  features/   screens and their parts: dashboard, calendar, months (month switcher, daily chart, table twin), trades (table, filters, pager),
              trade-form, trade-detail, trade-delete, day, notes, shell, common, events (filters, day events), sources (feed status, Sync now)
  ui/         primitives: text, layout, controls (Button, PressableLink, TextField, Segmented, Toggle, Chip, TagEditor), feedback, data (StatTile, Meter, TrendMark, Tooltip), status, impact (impact glyph, badges)
  lib/        pure logic, unit-tested with node:test: decimal, money, time, calendar, validation, filters, summary, events
  api/        client (typed, adds X-Request-ID), endpoints (the 17 operations), queries (TanStack hooks, cache invalidation, sync polling), schema.d.ts (generated)
  state/      providers: QueryClient, flash messages, server info (/api/ready)
```

**Screens.** The month and every filter live in the address, so any view can be linked, reloaded and tested.

| Route | What it shows |
|-------|---------------|
| `/?month=YYYY-MM` | Dashboard: net P&L as the one hero figure, win rate with a meter, average per trade, best and worst day, open trades and closed this month, a daily P&L chart (Chart or Table), and the open trades |
| `/calendar?month=YYYY-MM&show&impact&currency` | Month grid shaded by daily P&L on one diverging scale, with a legend, a diamond on days that have notes, today outlined, a hover tooltip, and a Grid or Table toggle. Each day also shows its economic news (bars filled to the impact, with how many releases) and its personal calendar events (a ring and the first title), the event filters, a table twin with News and Calendar columns, and the Sources card (each feed's status, "Sync now") |
| `/trades?status&side&instrument&tag&from&to&sort&order&page` | Trades table: sort by Date or P&L, filters, 25 per page, edit and delete per row |
| `/trades/new?day=` | Trade form. Open or closed, tags with suggestions, validation before anything is sent |
| `/trades/{id}`, `?edit=1` | Trade detail, edit form (sends changed fields only), delete behind a confirm dialog |
| `/day/YYYY-MM-DD?show&impact&currency` | The day's net, its events (calendar events first, then the news in time order, in the server's zone, with impact, currency, forecast and previous), its trades, its notes and a note composer, previous and next day |
| `/notes/{id}` | Edit, move to another day, or delete a day note |

**The 17 operations and where the UI reaches them.** `GET /api/health`: status chip, every 30 seconds. `GET /api/ready`: the boot gate, and it supplies the time zone. `GET /api/trades`: the table, the dashboard's open-trade card and counts, the day screen. `POST`, `PATCH` and `DELETE /api/trades`: the form, the edit form, row and detail delete. `GET /api/trades/{id}`: detail and edit. `GET`, `POST`, `PATCH` and `DELETE /api/notes`, `GET /api/notes/{id}`: calendar markers, the day composer, the note page. `GET /api/tags`: suggestions and filter chips. `GET /api/calendar/month`: dashboard and calendar. `GET /api/events`: the month on the calendar and the day's events, all pages of a range. `GET /api/sources/status`: the Sources card, looked at again every second while a feed is syncing. `POST /api/sync`: "Sync now". The `ui-coverage` gate proves each one answers 2xx to a request the app itself sent.

**Accepted decisions (F1 to F8).** Made while building Phase 2 and accepted by the owner on 2026-10-13.

- **F1, money and quantities are exact.** Values are strings from the API to the screen and `bigint` counts of 1e-8 in between (`src/lib/decimal.ts`). Nothing touches `number`. Stored amounts keep every decimal (two at least, eight at most), so 0.00000001 never shows as $0.00. A figure the app derives, such as the average, rounds half away from zero to the cent. Prices are padded to the precision the instrument is quoted in (the server drops trailing zeros: 1.274 is shown 1.2740 next to 1.2728), and one instrument keeps one precision down the table. Percentages and bar heights are exact ratios. `frontend-rules` rejects `parseFloat`, `toFixed`, `Intl.NumberFormat` and `toLocaleString`.
- **F2, time is the server's.** `/api/ready` reports `APP_TIMEZONE`. People type and read wall-clock text in that zone (`2039-01-12 09:30`), and the app converts to UTC with daylight saving handled: a time inside the spring-forward gap is an error, a time that happens twice takes the earlier instant. The browser's own zone is never used, so the same journal reads the same anywhere. The tests run the browser in UTC against a New York server.
- **F3, colour is never the only channel.** Gains and losses are a blue and red diverging scale with a neutral midpoint (four steps per arm, loss lightness matched to gain lightness; `tools/derive-diverging-ramp.mjs` reproduces it), chosen so they stay apart without red-green vision. Every amount also carries a sign and a triangle (an equals sign for break-even). Text stays in ink. Every chart has a table twin and every cell and bar a spoken label.
- **F4, one hero figure per screen,** thin bars on one scale and one axis, hover and keyboard-focus tooltips that repeat what the labels already say, and a "no closed trades" line instead of an empty plot.
- **F5, stale data is dimmed, not blanked.** Changing month or page keeps the previous figures at half opacity (`aria-busy`) until the new ones arrive. A failed load shows the reason and a Retry. A first-run journal shows an invitation instead of zeros.
- **F6, writes refresh what they changed.** Each mutation invalidates only the queries it can have changed. A delete does not refresh its own detail query, which would log a 404.
- **F7, every request says where it came from.** The client sends `X-Request-ID: web-<hex>`. That is how the `ui-coverage` and `net-correlation` gates tell the app's traffic from the harness's.
- **F8, narrow screens degrade on purpose.** Below 720 px the calendar cell drops its amount and keeps its shade, triangle and note mark, the table scrolls sideways, and the table view carries every exact value.

**Frontend decisions of Phase 3 (F9 to F14, Accepted 2026-10-14).**

- **F9, events are marks on the day, not a second calendar.** News is bars filled to its impact with the number of releases, the owner's own events are a ring and the first title with how many more, both on a neutral chip so they read the same on a gain, a loss or an empty day. The P&L shade is never touched. Each cell's spoken label says what is in it ("22 news events (6 high, 3 medium, 13 low), 1 personal event"), the tooltip repeats it, the table twin has News and Calendar columns, and on a narrow screen a cell keeps the top level and the ring and drops the numbers.
- **F10, impact is an amber ordinal ramp,** never the blue or red of money. Low, medium and high use the P&L shades' lightness steps in one amber hue (`#eda107`, `#b47905`, `#7e5403`; the lightest is the design system's documented yellow). `tools/derive-impact-ramp.mjs` reproduces them and runs the ordinal checks (monotone lightness, visible steps, 2:1 on the surface for the pale end, one hue). Amber stays at least 17 away from the blue arm under every colour-vision model. It sits 2.8 from the red arm under deuteranopia, which is why colour is the third channel: the bars carry the level, the number the count and the words the name.
- **F11, filters live in the address and narrow only what is drawn.** `show` (everything, news or personal), `impact` (repeatable) and `currency`; a month's events load once and are narrowed in the browser, so a click is instant. Impact and currency narrow news only. News for every currency (`ALL`) matches any currency. A link to a day carries the filters, and the day's "back" link returns with them. The address is written one way (`impact=high&impact=medium`) and read either way, because expo-router writes a list as one comma-joined value (found when this broke the trade list's multi-tag filter, below).
- **F12, a sync is a request, not a wait.** "Sync now" gets its answer at once; the card follows the feed status (every second while a feed is queued or running), and the grid reloads its events the moment a feed's last success or event count changes, with no page reload. A refusal inside the cooldown shows the wait the server named (from `Retry-After`) and disables the button for that long. Nothing compares a server time with the browser's clock, so the screen is right whatever either clock says.
- **F13, a feed's address never reaches the screen,** and neither does anything from it that could run: a link from a feed is opened only if it is `http` or `https`. A failing feed shows the server's fixed phrase, says that the stored events are kept, and says when it will try again.
- **F14, the day screen puts the owner's own events first.** They are a handful and personal; the news can run to dozens and follows in time order, narrowed by the same filters.

**Fixed while building Phase 3.** The trade list's multi-tag filter was broken in Phase 2 and nobody saw it: expo-router writes two tags as `tag=a%2Cb`, which the page read as one tag with a comma in it. The tests had only ever chosen one tag. The list parser now splits on commas (tags cannot contain them), with unit tests and `test_two_tags_narrow_to_the_trades_that_carry_both_and_the_address_keeps_them`.

**Not yet.** Dark mode. Sorting by opened or closed time in the UI (the API supports it). Native-device behaviour (D2). Events on the dashboard.

**Test IDs.** Kebab-case, descriptive, and stable: `stat-net`, `day-2038-08-05`, `trade-row-12`, `field-lot-size`. A screen's title is `page-title`, an error under a field is `<field>-error`, a confirm dialog is `<thing>-dialog` with `-confirm` and `-cancel`. React Native Web renders `testID` as `data-testid`.

- Native must bundle. `verify.py` runs `expo export --platform ios --platform android` and requires a Hermes bundle for each. No Xcode or Android SDK is needed. Device smoke tests stay out of scope until D2 is revisited. Web-only calls are guarded (`useDocumentTitle` checks for `document`) and web-only style properties such as `outline*` are ignored by React Native, so nothing needs a `*.web.tsx` split yet.

## 6. Verification harness

### 6.1 Services (as built, Phases 0b and 4)

- `app`, from `docker/app.Dockerfile`, a multi-stage build from the repository root. Stage 1 is `node:24-slim`: `npm ci` (cached) and `expo export --platform web` into `web-dist`. Stage 2 is `python:3.14-slim`: the pinned runtime lock only (no pytest, no uv), the backend, the web export at `/app/web`, bytecode compiled at build time, a user with no shell (uid 10001), `/data` as the only writable volume, one `uvicorn` worker. The app applies its migrations itself as it starts. The image is about 270 MB. Nothing enters it but what `docker/app.Dockerfile.dockerignore` allows: no `.env`, no `data/`, no tests.
- `docker-compose.yml` is the production definition: the `app` service published on `127.0.0.1:8000` only (P7), the named volume `tj_data` for `/data`, `restart: unless-stopped`, a healthcheck on `/api/health`, a read-only root filesystem with a 16 MB `/tmp`, `cap_drop: ALL`, `no-new-privileges`, an init process, 1 GB and 256 processes, rotated JSON logs, and a 20 second stop grace (the feed workers stop and SQLite checkpoints its log before the kill). It reads its settings from the environment or `.env`.
- `docker/compose.verify.yml` layers the verification onto it: the app's test settings (`APP_ENV=test`, fixture feeds, the pinned feed clock), `feedstub` (the fixtures over HTTP, profile `feeds`, from Phase 3), and `e2e`. `docker/compose.smoke.yml` adds only `e2e` for the production smoke stage.
- `e2e`, from `e2e/Dockerfile`: `mcr.microsoft.com/playwright/python:v1.63.0-noble` (about 3.5 GB: the browsers are in it) plus the pinned test lock, the suite and the fixtures. It shares the app container's network namespace, runs with `ipc: host` and `init: true`, and writes through two bind mounts, `logs/_run/phase_N` and `artifacts`. Chromium's own sandbox cannot start in an unprivileged container, so `E2E_NO_SANDBOX=1` adds `--no-sandbox` there: the container is the isolation, and holds nothing but the suite.
- Source is copied into images, never bind-mounted. The images the harness builds are tagged `verify`, so a run never replaces the `local` image a person runs, and each stack has its own project name and volume, destroyed when the run ends.

**Container decisions (Built, for your review).**

- **K1, one image, two stacks.** The verification stack (the compose file plus the verify override: test settings, the stub, the runner) runs the whole suite. A second stack from `docker-compose.yml` alone (`APP_ENV=prod`, feeds off, UTC, an empty volume) proves the file you would deploy. The override changes settings, never the image, and takes them from the same constants the native backend uses.
- **K2, the healthcheck asks `/api/health`,** as you asked: strictly (200 and the body `{"status": "ok"}`), every 10 seconds, unhealthy after three misses. Each probe sends the request id `healthcheck`, so the logs and the verification's counts can tell it from real traffic (found when two compose runs differed by one request: a server that lives 20 seconds logs two or three probes). It is liveness. The blueprint had planned `/api/ready`, which asks the stricter question (database and migrations) and is what the harness waits for before testing.
- **K3, the test browser shares the app container's network namespace,** so it reaches `http://127.0.0.1:8000`, the origin a person uses. Found the hard way: Chromium upgrades the bare host name `app` to HTTPS (`.app` is a Google-owned top-level domain on its HSTS preload list), and ignores the opener policy header, with a console error, on any origin that is neither loopback nor HTTPS. The app's own traffic to the stub still crosses the compose network.
- **K4, fixture mode names the stub.** `FEEDS_FIXTURE_HOSTS=feedstub` lets `FEEDS_MODE=fixture` reach the stub's container as well as loopback. A name must be a plain host name with no dot, so a public site cannot be listed, and `feeds-offline` checks that every sync went to loopback or to that name.
- **K5, the hardening is in the definition and checked on the running container.** The gates read Docker's own account of every container the run starts (user, read-only root, dropped capabilities, `no-new-privileges`, published addresses, mounts, limits) and ask the container itself (its uid, which paths it can write, its effective capabilities, its database's journal mode).
- **K6, the web export is built in the image,** and the `web-build` gate checks that export, copied out of the image, not a host build: what is verified is what ships. The frontend's other gates (types, unit tests, source rules, native bundles) still run on the host.
- **K7, the server sends security headers and a content security policy** (section 4.2). Styles allow `'unsafe-inline'` because react-native-web writes its styles at runtime; scripts do not. A browser test opens every screen and the docs page with a violation listener, and none fires. The Phase 0 stub page's inline script moved to a file for it.
- **K8, a request body is limited to 1 MiB.**
- **K9, backups are online and tried.** The smoke stage takes one inside the running, read-only production container, with the app writing, and checks that it passes SQLite's integrity check, holds the trade the test wrote and is still on the volume after the container is replaced. `docs/RUNBOOK.md` has the restore, run for real: two trades, restored to the one at the backup.
- **K10, a restart replaces the container,** not just the process: `stop` (the graceful path, its logs kept), `rm`, then `up` on the same volume. The after-restart tests run in a new container and the `volume-persistence` gate asks that the container differs and the volume does not.

### 6.2 Flow and gates

```text
python scripts/verify.py <phase> [--backend native|compose] [--port N] [--python PATH]
python scripts/verify.py --self-test

1. Guards       LF check, Playwright pin equals the installed version, required packages present
2. Reset        delete logs/phase_N.log and artifacts/phase_N/, fresh database file
3. Frontend     from phase 2: dependencies, typecheck, unit tests, source rules, web build, native bundles
4. Unit tests   backend/tests (plain pytest)
5. Start        compose: build both images, up --wait the stub and the app (the stack's healthchecks) | native: uvicorn subprocess (APP_ENV=test, APP_TIMEZONE=America/New_York), serving the web build from phase 2; from phase 3 the feed stub first, and the app in fixture mode against it on a pinned clock
6. Test         pytest markers p0..pN except after_restart and deployment (regression included), VERIFY_PHASE=N; compose runs it in the e2e container
7. Contract     from phase 2: regenerate the API types from the running server and compare
8. Restart      from phase 1: stop the server gracefully, start it on the same database, run the after_restart tests (the feeds' clock carries on from where it was)
9. Smoke        compose, from phase 4: a second stack from docker-compose.yml alone, written to, its container replaced, a backup taken (section 6.1)
10. Gate, merge write logs/phase_N.log, metrics.json and openapi.json, apply gates, tear down (compose: the container logs are read with `docker logs` and written where the native server's output goes, so one pipeline reads both)
```

`--keep-up` and `--live-feeds` were planned and are not built (parking lot). Exit codes: 0 pass, 1 a failed test or gate, 2 an environment problem. The run fails unless every gate passes:

1. `lf-endings`: no CRLF in any non-ignored text file (`git ls-files --cached --others --exclude-standard`).
2. `playwright-pin`: `playwright==` in `e2e/requirements.txt` equals the installed version and, once it exists, the tag in `e2e/Dockerfile`.
3. `unit-tests` and `e2e-tests`: backend unit tests and the e2e tests for phases 0..N all pass, including the after-restart pass.
4. `screenshots`: at least one valid, non-empty PNG in `artifacts/phase_N/screenshots/` was written during this run.
5. `no-unexpected-errors`: no `error` record from the server (any stderr line counts) or the browser.
6. `log-sources`: the merged log contains `server`, `client` and `test` records.
7. `api-coverage` (phase 1 and up): every operation in the app's OpenAPI document that the phase being verified has introduced (`x-phase`, 1 when absent) answered 2xx at least once during the run. The harness's own probes do not count.
8. `db-transactions` (phase 1 and up): every successful write request (POST, PUT, PATCH or DELETE answering 2xx) has a `db_transaction` commit record with the same request ID, and the run has no rollbacks.
9. `no-secret-leaks`: no value of a `REDACT_ENV` variable and no `private-<hex>` iCal token appears in the log. A leak is masked in the written file and fails the run.
10. `repo-hygiene`: `git status` shows no files added or removed outside `logs/` and `artifacts/`.

From phase 2 on, nine more gates cover the frontend:

11. `frontend-deps`: `npm ls --depth=0` is clean, so `node_modules` matches `package.json`.
12. `frontend-typecheck`: `tsc --noEmit` passes for the app and, in a separate project with Node's types, for the tests.
13. `frontend-unit-tests`: the `node:test` suites for `src/lib` pass, and their summary was actually read (no summary is a failure, not zero failures).
14. `frontend-rules`: no `parseFloat`, `toFixed`, `Intl.NumberFormat` or `toLocaleString` (money stays exact), `asChild` only inside `PressableLink`, no `Alert.alert` (a no-op on the web), no `console` calls. Comments are ignored. Each rule exists because of something that went wrong, section 8.
15. `web-build`: `expo export --platform web` succeeds into a fresh folder under `logs/_run/`, so a stale build can never stand in for the current source, and it holds an `index.html` and a real bundle.
16. `native-bundles`: `expo export --platform ios --platform android` succeeds and each platform has a Hermes bundle.
17. `api-contract`: `src/api/schema.d.ts` equals what `openapi-typescript` generates from the running server's schema.
18. `ui-coverage`: every operation answered 2xx to a request whose ID starts with `web-`, that is, to the app's own client and not to a test.
19. `net-correlation`: every API response the browser logged (`api_response`, section 6.3) matches a server `request` record with the same ID, method, path and status. A response with no echoed ID was mocked by a test and is counted, not matched.

From phase 3 on, three more gates cover the feeds:

20. `feeds-offline`: the app was started in `fixture` mode, every sync it logged went to a loopback host, each feed was synced at least once, and the stub saw feed requests and every one identified itself as `TradingJournal/`. The run touched no network but its own.
21. `feed-paths`: every outcome in a table (news: ok, unchanged, throttled, bad_content, error; calendar: ok, unchanged, bad_content, error) happened at least once, so the throttle, bad-data and outage paths ran in this run and were not only assumed.
22. `secret-registered`: the calendar address was among the secret values the leak gate scans for, so `no-secret-leaks` is not vacuous for the one secret the app has.

Under `--backend compose` six more gates cover the containers and what the run leaves behind, and the frontend's `web-build` gate checks the export inside the image:

23. `image-contents`: the runtime image holds Python 3.14 and the web export and no Node, compiler, `pytest`, Playwright, `uv`, tests, `.env` or `.git`.
24. `container-health`: every app container the run started (the verification stack's two, the production stack's two) is healthy through a check of `/api/health` that sends the request id `healthcheck`, with no failing streak and no restart.
25. `container-hardening`: every one of them runs as a non-root user, cannot write `/app`, `/etc` or `/usr` and can write `/data` and `/tmp`, has no effective capabilities and no new privileges, is published on `127.0.0.1` only, mounts nothing but the named volume at `/data`, and has an init process and limits.
26. `volume-persistence`: each restart replaced the container and kept the volume, and the database on it (WAL mode, all the journal's tables) was opened by the new container.
27. `production-smoke`: both passes of `e2e/tests/p4_deployment/` passed against the stack of `docker-compose.yml` alone, and a backup taken inside its container passed the integrity check, held the trade and survived the container's replacement.
28. `docker-hygiene`: the run left no container, volume or network behind (images and the build cache are meant to stay). The image declares `/data` a volume, so a container made from it, such as the one the harness uses to copy the web export out, owns an anonymous volume that a plain `docker rm` leaves behind: 11 empty ones had piled up over the runs of this phase before the gate existed. The gate takes a snapshot before the run and after it, and judges only what is new.

Each run also writes `artifacts/phase_N/metrics.json`: tests by marker, API coverage, requests by status class, database commits, rollbacks, statements and writes, server restarts survived, journal events, log record counts and every gate's result. From phase 2 it adds a `frontend` block (unit tests, typecheck, builds, contract) and a `ui` block (operations the app reached, and its write requests by method), from phase 3 a `feeds` block (syncs by feed and outcome, by trigger, and the hosts they went to), and under compose a `container` block (healthy, hardened, non-root, read-only root, capabilities, published addresses, whether the volume persisted). Nothing in it depends on timing, so it is identical from run to run. That is why the app's own traffic, whose volume depends on timing (refetches, polling), is counted under `ui` as operations and left out of `api.requests_by_status_class` and of the log record counts. A test's own polling while it waits for a background sync is left out the same way: those requests carry an id that starts `poll-`. The browser's navigation events (`navigated`) are left out of the log record counts as well: whether the app's own navigation after a form submit happens before the test moves on is a race, and under compose one test's count was 10 in some runs and 11 in others while nothing else differed (found in Phase 4). The container's own healthcheck probes (request id `healthcheck`, one for every 10 seconds the container lives) are left out of the request and log counts for the same reason: a server that lives 20 seconds logged two probes in one run and three in another. The records stay in the log; they are not counted. Two consecutive runs produce byte-identical files. From phase 1 it writes `artifacts/phase_N/openapi.json` too, the API contract as the server served it.

### 6.3 Log contract

One JSON object per line.

```json
{"ts":"2026-10-13T14:03:22.123Z","source":"server","level":"info","logger":"app.http","msg":"request","request_id":"b7e1c0","method":"GET","path":"/api/health","status":200,"duration_ms":2.1}
```

- Required: `ts` (UTC, milliseconds, `Z`), `source` (`server`, `client`, `test` or `harness`), `level` (`debug`, `info`, `warning`, `error`), `msg`. Optional: `logger`, `request_id`, `test` (pytest node id), `phase`, `url`, `status`, `duration_ms`, `exc`.
- Server: stdlib `logging` with `JsonFormatter` (`backend/app/core/logging.py`). Redaction happens inside the formatter (`Redactor`), so tracebacks and extra fields are masked, not only the message. Output is ASCII-only JSON. `backend/log_config.json` is passed to uvicorn with `--log-config`, so uvicorn's own lines are JSON too. `RequestLogMiddleware` writes one `request` record per request (5xx is error, 4xx is warning) and echoes `X-Request-ID`; an inbound ID is reused only if it matches `[A-Za-z0-9_.-]{1,64}`. Every other record written while a request is handled picks up the same ID through a context variable. Values registered with `register_secret` (the calendar address, read from `.env` and not only from the environment) are masked like `REDACT_ENV` values.
- Database and domain records (Phase 1): `db_transaction` (`outcome` commit or rollback, `statements`, `writes`, `duration_ms`, and the request ID) for every commit and for every rollback that had written something. `migrations` (`from_revision`, `to_revision`, `applied`) once at startup. Journal events `trade_created`, `trade_updated` (`changed_fields`), `trade_deleted`, `note_created`, `note_updated` and `note_deleted`, with ids and names only. Alembic's own logger is muted at WARNING. Feeds (Phase 3): `feeds_started` and `feeds_stopped`, and one `feed_sync` record per sync with the feed, the trigger (startup, schedule or manual), the outcome (ok, unchanged, throttled, bad_content or error), the HTTP status, the host (never the address), the items read, dropped, added, updated, unchanged and removed, the backoff chosen and a fixed-phrase reason. The verification stub writes one `source=stub` record per request it served (with the secret in the path masked), merged into the log.
- Client: captured by Playwright, not by app code. Every DOM test writes `page_open`, `navigated` and `page_close`, so `client` records exist even when the page logs nothing. Console messages map to levels (`log` and `info` to info, `debug` and `trace` to debug, `warning` to warning, `error` and `assert` to error). `pageerror` and `requestfailed` are errors, HTTP 4xx is a warning, HTTP 5xx is an error. An allow-listed error is written as a warning carrying `allowed=<reason>`. Every record carries the `test` id. From phase 2 each API response the browser receives is an `api_response` record (method, path, status, the request ID the app sent, and `echoed_id`, the ID the server answered with), so the browser's view of the network sits in the log next to the server's.
- Test and harness: pytest hooks write `test_start`, a `test_report` for the call phase and for any failing phase, `api_request` (carrying the `X-Request-ID` the server also logs) and `screenshot`. `verify.py` writes `run_start` (with the Node and frontend package versions from phase 2), `frontend_step` (one per frontend command, with its exit code and transcript file), `server_started`, `server_stopped` (with `graceful`), one `gate` record per gate, and `run_end`.
- Merge: `verify.py` sorts server, e2e and harness records by `ts` (stable) into `logs/phase_N.log`. First line is `run_start` (phase, backend, versions, git revision or `no-commits`). Last line is `run_end` (counts and result). Stray non-JSON server stdout lines are wrapped as `source=server, level=info`, and every stderr line becomes `level=error`.

### 6.4 Test rules

- Locators are `data-testid` only. Assertions are web-first (auto-waiting). No fixed sleeps.
- Browser context: viewport 1280x800, device scale factor 1, locale `en-US`, timezone `UTC`, reduced motion, animations disabled for screenshots.
- Layout: `e2e/tests/p<N>_<topic>/`. The directory name applies marker `pN`, and `verify.py N` runs `p0` through `pN`. Fixtures: `api` (logged API client), `journal` (creates records through the API and removes them afterwards), `page` (client capture and the clean-run rule), `shot` (screenshots). `e2e/support/` holds what several suites share: `journal.py` and `ui.py` (`open_app`, `expect_api`, which waits for one API response and exposes its request body, query string and request ID, `wall_to_utc` and `utc_to_wall` as an independent time zone oracle, and `capture_tall`).
- Screenshots: `artifacts/phase_N/screenshots/<test>__<step>.png`. The app scrolls inside its own container, so a plain full-page shot only sees the viewport. From phase 2 the `shot` fixture (`e2e/tests/p2_frontend/conftest.py`) grows the viewport by the hidden height, captures, and restores it. Steps are numbered by the tests (`01-empty-form`), so a folder listing reads as a story. Failure traces go to `artifacts/phase_N/traces/` (gitignored). Screenshots are evidence, not visual-diff baselines.
- Self-test: `python scripts/verify.py --self-test` proves the gates are not vacuous. It checks each gate against synthetic good and bad input, runs `e2e/tests/_canary/` (two tests that must fail on an unexpected browser error and one allow-listed test that must pass), serves `e2e/tests/_canary/canary_app.py` (the real app plus two misbehaving routes) to confirm that an unhandled exception answers 500 and is logged as an error with a traceback, and that a write which answers 200 but is never committed is flagged and its rollback logged, and runs the after-restart tests against a database that never held the canary, which must fail. From phase 2 it also checks the frontend gates against synthetic input (the source rules, the unit test summary parser, the contract comparison, the correlation of browser and server records, the UI coverage rule) and runs two toolchain canaries: `tsc` must reject a file with a type error, and `node --test` must exit non-zero on a failing test whose summary reads one failure. The canaries live under `e2e/`, so the shipped app carries no test-only endpoint. Run it after changing the harness, and in Phase 4's final run.
- Restart pass: tests marked `after_restart` run in a second pytest pass, after `verify.py` has stopped the server and started it again on the same database file. `test_persistence.py` writes a canary with eight-decimal values in the first pass and checks it, its calendar day and its tags after the restart. `p2_frontend/test_persistence_ui.py` does the same through the browser: it logs a trade and a note in the UI, and after the restart the table, the detail page and the calendar must show them.
- Each test file owns its own dates so results are exact: 2030 for CRUD, 2031 for the calendar, 2032 for filters, 2033 for the restart canary, 2034 for day notes. The Phase 2 files use 2036 to 2043 (dashboard 2037, calendar 2038, forms 2039, trade lists 2040, precision 2041, day and notes 2042, UI restart canary 2043). The server runs in America/New_York, and a test asserts that.
- Browser tests assert on exact text and on what crossed the wire: the request body the app sent (exact decimal strings, UTC instants, only the changed fields for a PATCH), the response, and the record the API holds afterwards. Error and slow-network states are made by answering or holding requests from the test (`page.route`), so the app meets a dead network, a 500 or a slow list on demand. Every such test allow-lists the browser error it causes, with a reason. `pytest.mark.stub_page` marks the one Phase 0 test that needs the stub page; `verify.py` leaves it out from phase 2, when the app replaces the stub.
- Backend unit tests (`backend/tests/`, plain pytest) cover pure logic and the database layer: money types, schemas, time bucketing including both daylight-saving transitions, repositories, migrations (the models and the migration must describe the same schema), transaction logging, and the API through Starlette's test client. They run natively in seconds and count toward each phase's proof.
- Seed data goes through the public API, with unique values per test and fixed dates, so tests are order-independent.
- Phase 4 tests: `e2e/tests/p4_hardening/` runs in the main stack on either backend (security headers on every kind of answer, the policy that the app and the docs page run under without one violation, and the size limit). `e2e/tests/p4_deployment/` is marked `deployment` and runs only in the production smoke stage, against `docker-compose.yml` alone: a new installation, a trade written through the browser and its UTC day, the feeds reported off, the docs offline, the server's production answers, and, after the container is replaced, the trade. Tests marked `expo_app` (one, in Phase 0) run only under compose, where the image serves the Expo app from the start.
- Phase 3 tests (`e2e/tests/p3_connectors/`) read static files and never the internet. The fixtures are in May 2044: the week of Sunday 2044-05-08 (ForexFactory week A, and week B a day later with an event removed, changed, moved and added, plus a past event the app must keep), a Google-style `personal_a.ics` with every hard case and a changed `personal_b.ics`, and the failure bodies. The app's feed clock starts on Wednesday 2044-05-11 at 12:00 UTC. A stub (`e2e/support/feed_stub.py`) serves them over loopback and is scripted from the tests (`support/feeds.py`). Expected results are written out from the fixture files (`ff_week`, `calendar_events`), never read back from the app. A test that changes what the stub says gets the baseline back afterwards, because the feed state is shared by the whole run. The poll interval is 720 minutes and the cooldown 2 seconds, so no scheduled sync lands in the middle of a test and a test waits out the cooldown instead of probing it.

### 6.5 Running natively on Windows

One-time setup (Python 3.14 and Node 24 are already installed):

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install uv
.venv\Scripts\uv.exe pip sync backend\requirements-dev.txt e2e\requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
cd frontend; npm ci; cd ..    # from Phase 2
```

Every run:

```powershell
.venv\Scripts\python.exe scripts\verify.py 0            # phase 0 only, writes logs\phase_0.log
.venv\Scripts\python.exe scripts\verify.py 1            # phases 0 and 1 with a server restart, writes logs\phase_1.log and the artifacts\phase_1 folder
.venv\Scripts\python.exe scripts\verify.py 2            # phases 0 to 2: frontend checks and builds, then every e2e test through the real web app
.venv\Scripts\python.exe scripts\verify.py 3            # phases 0 to 3: also the feed stub and the connectors, offline, on a pinned clock
.venv\Scripts\python.exe scripts\verify.py --self-test  # after any change to the harness
```

The frontend's own commands (`npm run typecheck`, `npm test`, `npm run export:web`, `npm run gen:api`) and the dev loop are in [frontend/README.md](../frontend/README.md).

To explore the API by hand, run the server and open `http://127.0.0.1:8000/api/docs`. The database is `<repo>\data\dev.db`, created on first start. Set `APP_TIMEZONE` first (for example `$env:APP_TIMEZONE='America/New_York'`) so the calendar buckets days in your zone, and drop `--log-config` for plain console logs.

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --log-config log_config.json
```

New migrations: `..\.venv\Scripts\alembic.exe revision --autogenerate -m "describe the change"` from `backend`, then review the generated file, because autogenerate does not see CHECK constraints.

Changing dependencies: edit the `*.in` file, recompile, then sync. The backend locks target Python 3.14. The e2e lock targets Python 3.12 because the Playwright image runs 3.12.

```powershell
.venv\Scripts\uv.exe pip compile backend\requirements.in -o backend\requirements.txt --universal --python-version 3.14
.venv\Scripts\uv.exe pip compile backend\requirements-dev.in -o backend\requirements-dev.txt --universal --python-version 3.14
.venv\Scripts\uv.exe pip compile e2e\requirements.in -o e2e\requirements.txt --universal --python-version 3.12
.venv\Scripts\uv.exe pip sync backend\requirements-dev.txt e2e\requirements.txt
```

Backend unit tests alone: `cd backend`, then `..\.venv\Scripts\python.exe -m pytest -q`.

### 6.6 Running in Docker

Needs Docker Desktop with the WSL 2 backend (section 9). Verification in containers, with the same gates plus the container ones (section 6.2):

```powershell
.venv\Scripts\python.exe scripts\verify.py 4 --backend compose     # builds the images, runs everything in containers, ends with the production smoke stage
```

The first run downloads the Playwright image (3.5 GB on disk) and builds both images; later runs use the layer cache. Running the app itself, and looking after it, is in [RUNBOOK.md](RUNBOOK.md): `docker compose up -d --build --wait`, backups, restore, settings and what to do when something is wrong.

## 7. Roadmap and proof gates

Each phase ends with its own `verify.py` run, so verification is never deferred to Phase 4.

### Phase 0: blueprint and harness proof

- [x] Pre-flight checks (section 9)
- [x] This blueprint
- [x] `git init -b main`, `.gitignore`, `.gitattributes`, `.editorconfig`, `.vscode/settings.json` (LF enforcement). No commits.
- [x] `CLAUDE.md` converted to LF, stale git note removed, pointer to this blueprint added.
- [x] **You (2026-10-14):** enabled CPU virtualization, installed WSL 2 and Docker Desktop (section 9).
- [x] **0a, native harness proof (2026-10-13):** `scripts/verify.py`, `e2e/` with the log-capture and screenshot fixtures, stub `backend/app/main.py` (`/api/health`), JSONL logging with redaction, request-ID middleware, backend unit tests, and a stub page at `/` with `data-testid="harness-ok"`. The stub is the seed of Phase 1, not throwaway.
- [x] **0b, container harness proof (2026-10-14):** `docker/app.Dockerfile`, `e2e/Dockerfile`, `docker-compose.yml`, `.dockerignore` and `verify.py --backend compose` (section 6.1). `python scripts/verify.py 0 --backend compose` passes its 13 gates: the suite runs in Playwright's container against the app's container, the browser evidence comes from the served app (`expo_app`), and the container gates pass.
- **Proof:** `python scripts/verify.py 0 --backend native` and then `--backend compose` both exit 0, producing `logs/phase_0.log` (server, client and test lines merged) and `artifacts/phase_0/screenshots/*.png`. Native passed on 2026-10-13 and still passes as the Phase 1 regression: 9 of 9 gates and 4 e2e tests. `--self-test` passed 34 of 34 checks then and passes 61 of 61 now (Phase 2 added the frontend gates). Compose is pending Docker.

### Phase 1: core journal API (done natively 2026-10-13)

- [x] **Built:** pydantic-settings, SQLAlchemy 2.0 models with scaled-integer money columns, Alembic baseline `0001` applied at startup, a sync engine (WAL, foreign keys, busy timeout) and `/api/ready`. A repository layer (`app/db/repositories.py`), services that own the transaction (`app/services/`) and routers (`app/api/`): trade CRUD with filters, sorting and paging, day notes, tags and the month summary. `db_transaction` logging, domain events and request IDs on every record. Swagger UI vendored at `/api/docs`, so it works offline.
- [x] **Harness:** `verify.py` gained the restart pass, the `api-coverage` and `db-transactions` gates and the `metrics.json` and `openapi.json` artifacts (section 6.2).
- [x] **Containers (Phase 4):** the compose healthcheck (now on `/api/health`, K2) and the container restart check (the container is replaced, K10).
- **Proof (native, 2026-10-13):** 197 unit tests, 67 e2e tests (65, plus 2 after a server restart on the same database file) and all 11 gates. 14 of 14 API operations answered 2xx, and 154 successful write requests each have a commit record, with no rollbacks. Money is exact: eight decimal places round-trip, 0.1 + 0.2 is 0.3, ten times 0.1 is 1, and `100` sorts after `2`. Calendar days are bucketed in New York time across winter, summer and both daylight-saving transition days. Evidence: `logs/phase_1.log`, `artifacts/phase_1/metrics.json`, `artifacts/phase_1/openapi.json` and the Swagger UI screenshot.

### Phase 2: Expo Web UI (done natively 2026-10-13)

- [x] **Built:** the Expo app in `frontend/` (section 5): dashboard, month calendar, trades table with filters, sorting and paging, trade form with create, edit and delete, day screen with notes, note page. All 14 operations are reached from the UI. Exact decimals and server-zone times on the client. Loading, empty, error and offline states. Typed API client generated from the live schema.
- [x] **Harness:** `verify.py` gained the frontend stage (dependencies, types, unit tests, source rules, web build, native bundles), serves the fresh web build instead of the stub page, and checks the API contract, UI coverage and the browser-to-server correlation (section 6.2). The browser records every API response (section 6.3). `e2e/tests/p2_frontend/` drives the real DOM.
- [x] **Containers (Phase 4):** the Node stage of `docker/app.Dockerfile` that runs the same `expo export`, whose output the `web-build` gate checks under compose.
- **Proof (native, 2026-10-13):** 208 backend unit tests and 51 frontend unit tests, 142 e2e tests (3 p0, 63 p1, 76 p2, counting the tests that run after a server restart) and all 20 gates. 14 of 14 API operations answered 2xx to requests the app itself made (3 DELETE, 6 PATCH, 12 POST); 856 successful write requests across the run each have a commit record, with 0 rollbacks. The browser tests create, edit and delete trades through the form and compare the request body, the response and the stored record; keep money exact beyond what a double can hold (9,999,999,999.99999999 and 0.00000001); convert New York time in winter and summer; page, sort and filter 27 trades with the right query on the wire; shade a month by one scale and mark days with notes; and meet a dead network, a 500, a slow list and a restarted server. Both native bundles build. Evidence: `logs/phase_2.log`, `artifacts/phase_2/metrics.json` and `artifacts/phase_2/screenshots/`.

### Phase 3: data connectors (done natively 2026-10-13)

- [x] **Built:** migration `0002` (`external_events`, `feed_state`), the ForexFactory connector (JSON and XML) and the Google Calendar connector (section 4.3), a feed service with persisted schedule, backoff, conditional requests and a manual sync that never holds up the request, one worker thread per feed, `GET /api/events`, `GET /api/sources/status` and `POST /api/sync`, secret redaction that includes `.env` values, and the injectable feed clock.
- [x] **Frontend:** events on the calendar grid (impact bars with counts, personal ring and title), filters in the address, the day screen's events, a table twin, the Sources card with "Sync now", a validated impact colour ramp (section 5).
- [x] **Harness:** `verify.py` starts the feed stub and the app in fixture mode on a pinned clock, three feed gates, phase-aware API coverage, a `feeds` block in the metrics, poll requests left out of the counts, and a second pass whose feed clock carries on. Fixtures with provenance, and tools that rebuild them (`fixtures/`).
- [ ] **Not built, parked:** the opt-in `--live-feeds` smoke test. The real ForexFactory week was recorded once and both forms are parsed from the recording; verification never calls a live host (P8). The Google address is yours alone, so a live test of it can only be yours to run.
- **Proof (native, 2026-10-13):** 329 backend unit tests and 66 frontend unit tests, 246 e2e tests (3 p0, 63 p1, 77 p2, 103 p3, counting the 5 that run after a server restart) and all 23 gates. 17 of 17 API operations answered 2xx, and 17 of 17 to requests the app itself made. 120 feed syncs ran, every one to a loopback host, and 973 successful write requests each have a commit record, with no rollbacks. The calendar and the news are read from the fixture files through a local stub and checked against expectations written out from those files, independently of the app's own parsers: every event of a week is compared field by field (UTC instant, New York day, impact, currency, forecast, previous); a later week updates, adds and removes the right events and keeps the past; and a Google-style calendar with a weekly series, an exception, a moved and a cancelled instance, three time zones, a floating time, all-day and multi-day events and HTML descriptions arrives as the file says. Fourteen scripted failures (rate limit, outage, refusal page, maintenance page, truncated download, revoked address, an empty feed) each give the right status and fixed phrase, a backoff and no lost event, five failures in a row back off 15, 30, 60, 120 and 120 minutes and one success ends it, and a host that never answers times out without holding anything up. The secret address appears in no API answer, page or log line. A manual sync is answered at once even when the host is slow, a second press inside the cooldown is refused with the wait, and the grid redraws without a reload when a sync finishes. A restart neither refetches early nor forgets the events, and the stored validators produce a 304. The browser tests check the colour of the impact bars and of the P&L shade they sit beside, every day of the month against the fixtures, the filters in the address, the day screen and the phone layout, and what the screens do when the events or the feed status fail or the feeds are off. Regression: Phase 2 passes its 20 gates with 143 e2e tests (the 142 it had and one for the bug below), Phase 1 its 11 and Phase 0 its 9; `--self-test` passes 83 of 83 checks. `metrics.json` is identical from one run to the next. Evidence: `logs/phase_3.log`, `artifacts/phase_3/metrics.json` and `artifacts/phase_3/screenshots/`.

### Phase 4: containers and hardening (done in containers 2026-10-14)

- [x] **Built:** the production image and `docker-compose.yml` (section 6.1), `e2e/Dockerfile`, the verification and smoke overrides, the compose backend of `verify.py`, security headers with a content security policy, a request size limit, an online backup tool with a tried restore procedure (`docs/RUNBOOK.md`), 17 hardening tests, 7 production-stack tests and the container gates. Decisions K1 to K10 await your review.
- [x] **Covered by running the whole suite in containers:** the journeys (create, review, filter, edit, events overlay, restart persistence) and the failure paths (upstream 429, malformed ICS, outage with cached events still served, a replaced container), because Phases 1 to 3's tests are the journeys and they now run against the image.
- [ ] **Not built, parked:** a dependency audit report, verification that the lockfiles are in step with their `.in` files (both need the package index and so the network), a JSON export of the journal, `--keep-up` and `--live-feeds`.
- **Proof (compose, 2026-10-14):** `python scripts/verify.py 4 --backend compose` passes all 29 gates: 344 backend and 66 frontend unit tests, and 271 end-to-end tests (259 in the verification stack, 5 more after its restart, and 7 in the production stack, 6 and then 1 after its container was replaced), all in Playwright's container. 17 of 17 API operations answered 2xx, 120 feed syncs all went to the stub container, and 974 successful write requests each have a commit record, with no rollbacks. 4 app containers were started and each was healthy, non-root, read-only, capability-free, loopback-only and on one volume; both restarts replaced the container and the data was found by the new one. The production stack (`docker-compose.yml` alone) started healthy on an empty volume, took a trade through the browser, had its container replaced, and showed the trade again; a backup taken inside it passed its integrity check and survived. The image is 267 MB. Regression: native Phases 0 to 4 pass (4, 67, 143, 246 and 263 tests), and `--self-test` passes 105 checks, including real-Docker canaries: a container left open and one that cannot pass its healthcheck are refused by the gates, and a volume left behind by a careless `docker rm` is caught. `metrics.json` is identical between two consecutive compose runs (and each native phase's between two sequences). Evidence: `logs/phase_4.log`, `artifacts/phase_4/metrics.json` and `artifacts/phase_4/screenshots/`.

## 8. Risks

| Risk | Mitigation |
|------|------------|
| Docker missing, WSL missing, CPU virtualization disabled | Retired on 2026-10-14: Docker Desktop and WSL 2 work and the compose proof passes. The native backend remains as the faster loop and the cross-check |
| Chromium upgrades the bare container name `app` to HTTPS (`.app` is an HSTS-preloaded Google TLD) and ignores security headers on a non-loopback HTTP origin | The test browser shares the app's network namespace and uses `http://127.0.0.1:8000` (K3). Any new service name should not be a TLD |
| A strict content security policy blocks an inline script the policy has not been told about (found: the Phase 0 stub page; FastAPI's docs page) | A browser test opens every screen with a violation listener; the docs script is allowed by hash; the stub's script is a file |
| The Playwright image is 3.5 GB on disk, so the first pull is slow on a slow line (about 0.6 MB/s here) | Pulled once, then cached. The pin keeps the browser and the client in step (gate `playwright-pin`) |
| A backup on the same disk as the data protects against a mistake, not a dead disk | `docs/RUNBOOK.md` says to copy the folder elsewhere |
| ForexFactory throttles or changes the feed | Hourly polling, persisted schedule, backoff, HTML detection, schema validation, `CalendarSource` interface, fixture-driven tests |
| Google iCal is stale or recurrences are expanded wrongly | `recurring-ical-events`, fixture `.ics` covering the hard cases (checked against a hand-written oracle), "last synced" in the UI |
| A truncated calendar download reads as a calendar with fewer events, and the mirror would delete the rest | The parser requires `END:VCALENDAR`; the fixture `malformed.ics` and its e2e test prove it |
| The ForexFactory XML has no time zone, and reading it as local time would shift every event | Settled by comparing the XML and JSON forms of one recorded week (108 of 108 agree as UTC); unit tests and the fixtures rest on it |
| A restarted test clock goes back in time, so persisted schedules and cooldowns are in the future | `verify.py` starts the second server's feed clock from where the first one's had got to |
| expo-router writes a list parameter comma-joined, which broke the trade list's multi-tag filter unnoticed | List parsers split on commas, the event filters write their own address, and both have unit and browser tests |
| Secret iCal URL leaks | `.env` only, redaction filter, log-scan gate, never in API or UI, `.gitignore` |
| 15.3 GB RAM, 2.8 GB free at probe | Cap WSL via `.wslconfig`, build sequentially, close heavy apps for Metro and Docker builds |
| CRLF breaks Linux containers | `.gitattributes`, `.editorconfig`, VS Code `files.eol`, verify guard |
| Playwright package and browser image drift | Exact pins. The guard compares `playwright==` with the image tag. |
| Expo SDK churn (57 now, 58 in `next`) | Stay on SDK 57 through Phase 4, upgrade deliberately afterwards |
| Python 3.14 wheel gaps on Windows | Retired for now: all 29 pinned packages installed from wheels on 2026-10-13. Re-check whenever a dependency is added. Still no `uvicorn[standard]`. |
| SQLite on Windows bind mounts | Named volume. Bind-mount only `logs/_run` and `artifacts`. |
| Noisy React Native Web console warnings | Allow-list per test with a stated reason, never blanket-ignore |
| Native behaviour is untested | Bundle check only (D2). Manual device smoke is deferred. |
| expo-router `<Link asChild>` merges the child's `style` with an object spread, so an array or function style becomes `{0: ...}` in a production build and the page crashes (found by the first browser run of the first production build) | `PressableLink` flattens styles and tracks hover and focus itself. The `frontend-rules` gate rejects `asChild` anywhere else. |
| A `204` response whose body is never read keeps its request open in Chromium, and the clean-run rule reports it as aborted when the page closes (found through the delete tests) | The API client reads the empty body of every 204. |
| TypeScript 6 includes no `@types/*` packages unless asked, so test files could not see Node's types | The tests are a separate TypeScript project with `types: ["node"]`, which keeps Node's globals out of the app. |
| The React Compiler is on and still young | Strict typecheck and the full browser suite run against the compiled output, which is what ships. Turn it off in `app.json` if a bug is traced to it. |
| Vendored Swagger UI (1.6 MB of minified JavaScript) | The npm tarball's SHA-512 was checked against the registry's published value before extraction. It is excluded from diffs (`-diff linguist-vendored`), and `backend/app/static/swagger/README.md` records the update procedure. |

## 9. Environment baseline and toolchain pins

**Pre-flight, 2026-10-13.**

| Item | Found | Status |
|------|-------|--------|
| Machine | ASUS desktop, AMD Ryzen 5 5600G, Windows 11 Home build 26200, BIOS 3607 (2024-03-22) | OK |
| Memory and disk | 15.3 GB RAM (2.8 GB free at probe), 307 GB free on C: | RAM is tight |
| git | 2.55.0. System config sets `core.autocrlf=true` | OK, overridden by `.gitattributes` |
| Node and npm | 24.19.0 (nvm4w) and 11.17.0. 24.x is the current LTS | OK |
| Python | 3.14.5 (`py` launcher and `python` alias) | OK, every pinned package installed from a wheel |
| uv | not installed globally | 0.13.0 installed into `.venv` in Phase 0a. While compiling the e2e lock, uv downloaded its own private CPython 3.12 (21 MB) into its managed-Python directory. Remove it with `uv python uninstall 3.12` if unwanted. |
| Ports 8000 and 8081 | free | OK |
| Long paths | enabled | OK |
| Shell policy | The probe ran with ExecutionPolicy Bypass, your terminal may differ | Use `.venv\Scripts\python.exe` and `npm.cmd` directly, never `.ps1` activation scripts |
| Docker and Compose | Docker Desktop 4.95.0 (engine 29.8.2, containerd 2.3.6), Compose v5.6.0, 12 CPUs and 7.4 GiB for the VM, checked 2026-10-14 | OK (was a blocker) |
| WSL | WSL 2, Docker Desktop's own distribution | OK (was a blocker) |
| CPU virtualization | enabled in firmware by the owner | OK (was a blocker) |

**How Docker was unblocked (done by the owner, 2026-10-14; kept for a rebuild of this machine).**

1. Reboot into UEFI and enable **SVM Mode** (AMD-V). On ASUS AM4 boards it is usually under Advanced, CPU Configuration. Menu names vary by board.
2. In an elevated PowerShell run `wsl --install --no-distribution`, then reboot.
3. Run `winget install -e --id Docker.DockerDesktop` (winget 1.29 is present), start Docker Desktop once, accept the terms and keep the WSL 2 backend.
4. Recommended: create `%UserProfile%\.wslconfig` containing the three lines below, then run `wsl --shutdown`.
5. Verify with `docker version`, `docker compose version` and `docker run --rm hello-world`.

```ini
[wsl2]
memory=6GB
processors=4
```

**Toolchain pins** (queried 2026-10-13). The lockfiles `backend/requirements*.txt` and `e2e/requirements.txt` are the source of truth. This table is a summary.

| Component | Pin | Note |
|-----------|-----|------|
| Python | 3.14 (host 3.14.5, image `python:3.14-slim`) | Docker Hub tag exists |
| Node | 24 LTS (host 24.19.0, image `node:24-slim`) | Docker Hub tag exists |
| Expo SDK | 57 (`expo@57.0.28`) | 58 is `next`, not used |
| Playwright | 1.63.0, image `mcr.microsoft.com/playwright/python:v1.63.0-noble` | Tag exists on MCR |
| pytest-playwright / pytest | 0.10.0 / 9.1.1 | |
| FastAPI / Uvicorn / Starlette | 0.143.0 / 0.54.0 / 1.7.0 | Plain `uvicorn`, no `[standard]` extra. FastAPI now pulls in `opentelemetry-api`. |
| SQLAlchemy / Alembic | 2.0.54 (`>=2.0.54,<2.1`) / 1.20.0 | Alembic requires SQLAlchemy 2.0 or newer |
| Pydantic / pydantic-settings | 2.14.1 / 2.15.0 | |
| httpx2 (with httpcore2) | 2.13.1 | Replaces httpx 0.28.1 (last release 2024-12). Same author, now under the Pydantic org. |
| icalendar / recurring-ical-events | 7.3.0 / 3.8.2 | recurring-ical-events needs icalendar `>=6.1,<8` |
| tzdata | 2026.5 | Time zone data for Windows, which ships none |
| swagger-ui-dist | 5.33.2 | Vendored, Apache-2.0 |
| Docker base images | `node:24-slim`, `python:3.14-slim` (3.14.8 at the 2026-10-14 build), `mcr.microsoft.com/playwright/python:v1.63.0-noble` (Python 3.12.3) | Tags, resolved by the build; the build log records each image's id |
| React / React Native / react-native-web | 19.2.3 / 0.86.3 / 0.21.4 | Expo SDK 57's set. The lock is `frontend/package-lock.json` |
| expo-router | 57.0.26 | |
| TanStack Query | 5.104.2 | |
| openapi-fetch / openapi-typescript | 0.17.0 / 7.13.0 | `openapi-typescript` declares a peer range that stops at TypeScript 5, so `package.json` has an `overrides` entry. The generated output is checked by the `api-contract` gate |
| TypeScript | 6.0.3 | Strict. `@types/node` 24 for the tests only |

## 10. Conventions

- LF line endings and UTF-8, enforced by `.gitattributes`, `.editorconfig`, VS Code `files.eol` and the verify guard.
- Integer primary keys, never reused. Money, prices and lot sizes travel as canonical decimal strings (`1.1`, not `1.10`), so clients compare them as numbers. Instants are UTC with a `Z`. JSON is snake_case, and generated TypeScript types keep it. Errors use FastAPI's `{"detail": ...}` shape. List endpoints take `limit` (default 100, max 500) and `offset`.
- Test IDs are kebab-case and descriptive (section 5): `stat-net`, `day-2038-08-05`, `trade-row-12`, `field-lot-size`.
- Frontend money rule: amounts, prices and lot sizes are never a `number`. Use `src/lib/decimal.ts` and `src/lib/money.ts`.
- Secrets live in `.env` (gitignored). `.env.example` documents names only.
- Git: branch `main`, no commits until asked. Screenshots are tracked, logs are not.

## 11. Parking lot and change log

**Parking lot (deliberately out of V1).**

- CSV or broker import (MT4/MT5, cTrader, TradingView, IBKR).
- Event actuals (FRED with a free key, or manual entry) and one-off historical backfill. The ForexFactory `nextweek` file (URL unverified). Event revision history.
- Forex trading-day boundary (5 pm New York) instead of the calendar day.
- A dependency audit report (`pip-audit`, `npm audit`) and a check that the lockfiles match their `.in` files: both need the package index. A JSON export of the journal. Image signing and a pinned digest for each base image. Scheduled backups (the runbook shows the command). The secret calendar address as a Docker secret instead of an environment variable. HTTPS and a login before any exposure beyond loopback.
- The opt-in `--live-feeds` smoke test (one request per source). A per-feed "Sync" button next to each feed. Events on the dashboard. Event detail screens. Attendees, reminders and conferencing links from the calendar. Showing news times in the viewer's own zone as an option.
- Google: multiple calendars, write-back, retention beyond the 60-day mirror window.
- Static API token before any non-loopback exposure. Hosted deployment with PostgreSQL.
- Native device testing (Expo Go over LAN, HTTPS tunnel), EAS builds, a paid Apple developer account for iOS distribution.
- Visual-regression baselines. WebKit and Firefox matrix.
- SQLAlchemy 2.1 adoption.
- Several timestamped notes per trade (today a trade has one `notes` text and day notes are separate). Optimistic locking for concurrent edits.
- Dark mode (the palette is validated for the light surface only). A keyboard and screen-reader audit with an automated checker such as axe-core. Locale-aware number formats (today `1,234.50` everywhere). A pip size per instrument instead of inferring precision from the stored prices. Sorting by opened or closed time in the UI. Moving the calendar's month with the keyboard.
- Calendar days are computed when read, so changing `APP_TIMEZONE` re-buckets history. A stored closing day would pin it if that ever matters.

**Change log.**

- 2026-10-13: initial lock. D1 to D10 come from the Phase 0 Q&A. P1 to P10 proposed by Claude. Pre-flight found Docker and WSL missing and CPU virtualization disabled (section 9).
- 2026-10-13: P1 to P10 accepted. Phase 0a built and verified natively. `CLAUDE.md` converted to LF. Amendments while building: `httpx` replaced by `httpx2` (P1), uniform 1e-8 money scale spelled out (P3), the Playwright API fixture is named `api` (D5), harness gates and log records documented as implemented (sections 6.2 to 6.4).
- 2026-10-13: Phase 1 built and verified natively. Amendments while building: a trade has its own `notes` field and the `notes` table holds day notes (the owner listed notes as a field of the journal entry); `GET /api/notes/{id}` added; `AUTO_MIGRATE` setting; `verify.py` gained the restart pass, the `api-coverage` and `db-transactions` gates and the `metrics.json` and `openapi.json` artifacts; Swagger UI vendored (swagger-ui-dist 5.33.2); the canary app now carries two misbehaving routes; the folder of a file database is created on first use (found by reasoning about a fresh checkout, since the verify runs already had their folders).
- 2026-10-13: Phase 2 built and verified natively. The Expo web app, the frontend stage of `verify.py` (nine new gates, section 6.2) and `e2e/tests/p2_frontend/`. Decisions F1 to F8 (section 5) were made while building; the owner accepted them the same day (next entry). Amendments: the Phase 0 stub-page test is skipped from phase 2 on (`stub_page` marker); the web build is made fresh by every run into `logs/_run/phase_N/web-dist` instead of being served from `frontend/dist`; `/api/ready` reports `timezone`; `metrics.json` leaves the app's own request volume out of `api.requests_by_status_class` (it varies with timing) and reports `frontend` and `ui` blocks instead; the browser's API responses are logged as `api_response`.
- 2026-10-13: the owner accepted F1 to F8 (section 5) after reviewing Phase 2 and asked for Phase 3, the external data connectors.
- 2026-10-13: Phase 3 built and verified natively. Connector decisions C1 to C9 (section 4.3) and frontend decisions F9 to F14 (section 5) were made while building and await review. Amendments: D3 now also reads the XML form of the export (you asked for the XML or RSS feed); `POST /api/sync` replaces the planned `POST /api/events/refresh`; the opt-in `--live-feeds` test is parked; `api-coverage` asks only for the operations a phase has introduced (`x-phase`); three feed gates (`feeds-offline`, `feed-paths`, `secret-registered`) and a `feeds` metrics block; test traffic that waits for a background sync carries a `poll-` request id and is left out of the counts; a latent Phase 2 bug was fixed (the trade list's multi-tag filter, section 5); `.env.example` documents the feed settings.
- 2026-10-14: the owner accepted C1 to C9 (section 4.3) and F9 to F14 (section 5) after reviewing Phase 3, and asked for Phase 4: the production image, Docker Compose and the `--backend compose` verification, now that Docker Desktop and WSL 2 are working.
- 2026-10-14: Phase 4 built and verified in containers. Container decisions K1 to K10 (section 6.1) were made while building and await review. Amendments: the healthcheck targets `/api/health` at the owner's request (the blueprint had `/api/ready`); the test runner shares the app's network namespace; fixture mode gained `FEEDS_FIXTURE_HOSTS`; security headers, a content security policy and a 1 MiB request limit were added to the app; the Phase 0 stub page's script is a file; an online backup tool and `docs/RUNBOOK.md` were added; the e2e image installs the pinned lock into its own Python (it has no `venv`); `.cc-history/` (an editor's live session transcript, CRLF) was added to `.gitignore` after it failed the line-ending gate; `api-coverage` asks phase 0 for what phase 1 does, as it always had. Two pairs of consecutive compose runs each differed in `metrics.json`, and each difference was traced to its source rather than tolerated. First `log_records.client` (930 against 928): the browser's `navigated` events vary by one when the app's post-submit navigation loses a race with the test's next page load. Then `api.requests_by_status_class` and `log_records.server` (one request): the container's own healthcheck probe, one per 10 seconds the container lives, was counted as test traffic. Navigation events are no longer counted, the probe sends the request id `healthcheck` and is left out (section 6.2), the `container-health` gate demands that tag, and every phase's `metrics.json` was regenerated under the rules. Looking at Docker after those runs also found 11 empty anonymous volumes, one per run, left by the harness's own `docker create` (the image declares `/data` a volume): the harness now removes the container with its volumes and a new `docker-hygiene` gate fails a run that leaves anything behind. The 11 volumes the earlier runs had left are empty and were not removed by the harness; `docker volume ls` shows them (the anonymous ones have a 64-character hexadecimal name).
