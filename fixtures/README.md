# Feed fixtures

Static files the Phase 3 tests serve in place of the internet, so the suite is deterministic and works offline. The app reads them through a small local HTTP stub (`e2e/support/feed_stub.py`), so the whole fetch path is exercised (headers, conditional requests, status codes, size limits) without ever leaving the machine.

All dates are in **May 2044**. The verification server's clock starts at **Wednesday 2044-05-11 12:00 UTC** (`APP_NOW_OVERRIDE`) and then runs in real time, so "this week" is always the same week and no test depends on today's date.

## ForexFactory (`forexfactory/`)

| File | What it is |
|------|------------|
| `recorded/ff_calendar_thisweek_2026-10-13.json`, `.xml` | The public weekly export exactly as the host served it on 2026-10-13, in both of its forms (108 events each). Provenance only; unchanged. |
| `week_a.json`, `week_a.xml` | The same 108 events moved by whole weeks into the week of Sunday 2044-05-08 (weekdays and New York clock times are preserved: both weeks are in US daylight time). |
| `week_b.json`, `week_b.xml` | Week A a day later, 107 events: one future event removed (Unemployment Claims), one forecast changed (Core Retail Sales), one impact changed (BOE Gov Bailey, Medium to Low), one event moved 30 minutes (BOC Gov Macklem), one added (Cash Rate, AUD, High), and one **past** event removed (MPC Member Mann), which the app must keep. |
| `synthetic_cp1252.xml` | Hand-made. The real week happened to be plain ASCII, so this carries what it lacked: windows-1252 bytes (curly apostrophe, accents), `&amp;`, a CDATA title, and times that are not a time of day (`All Day`, `Tentative`) with an impact the app does not know. |
| `request_denied.html`, `maintenance.html`, `truncated.xml` | Failure bodies: the host's over-limit page (synthetic; the real wording is not documented), an unrelated HTML page, and an XML file cut off mid-event. |

**What the recorded pair settled.** The XML has no time zone. Compared event by event with the JSON, which carries explicit offsets (`-04:00`), all 108 events agree if the XML's `MM-DD-YYYY` date and `h:mmam/pm` time are read as **UTC**. The parser and its unit tests rest on that.

Regenerate A, B and the synthetic file from the recorded originals with `python fixtures/tools/build_forexfactory_fixtures.py`. The script first checks that its templates reproduce the recorded files byte for byte and that the two recorded forms agree.

## Google Calendar (`gcal/`)

| File | What it is |
|------|------------|
| `personal_a.ics` | A Google-style calendar (VTIMEZONE blocks, `X-WR-TIMEZONE`) with every hard case: a weekly series with an exception (EXDATE), a moved instance (RECURRENCE-ID) and a cancelled instance; a UTC time, a London-zone time, a floating time, an all-day day, a three-day all-day span, an event that crosses midnight; escaped commas and newlines, a folded long line, a UTF-8 title, an HTML description; and two events outside the sync window (more than 60 days back, more than 400 days ahead) that must not be mirrored. |
| `personal_b.ics` | Calendar A a little later: one event deleted, one added, one renamed, one moved. Made by `python fixtures/tools/build_gcal_fixtures.py`. |
| `malformed.ics`, `no_start_dates.ics`, `sign_in_page.html` | Failure bodies: a calendar cut off mid-event, a calendar whose every event lacks a start, and the HTML page Google shows when a secret address is no longer valid. |

Files are stored with LF line endings like everything else in the repository; the stub serves `.ics` files with CRLF, as Google does.
