"""Derives gcal/personal_b.ics, the calendar a few hours later, from gcal/personal_a.ics.

    python fixtures/tools/build_gcal_fixtures.py

B differs from A in four ways, so a second sync has something of every kind to reconcile: one event deleted
("Broker call"), one added ("FOMC watch party"), one renamed ("Trading course"), one moved ("Call with the prop firm"
from 14:00 to 15:00 UTC). Everything else, including the recurring series with its exception, its moved instance and
its cancelled instance, is untouched.
"""
import re
import sys
from pathlib import Path

GCAL = Path(__file__).resolve().parent.parent / "gcal"
VEVENT = re.compile(r"BEGIN:VEVENT\n.*?END:VEVENT\n", re.S)

NEW_EVENT = """BEGIN:VEVENT
DTSTART;TZID=America/New_York:20440512T140000
DTEND;TZID=America/New_York:20440512T160000
DTSTAMP:20440511T120000Z
UID:fomc-watch@fixture.example
DESCRIPTION:Watch the statement together.
LOCATION:Discord
SEQUENCE:0
STATUS:CONFIRMED
SUMMARY:FOMC watch party
TRANSP:OPAQUE
END:VEVENT
"""


def main() -> int:
    text = (GCAL / "personal_a.ics").read_text(encoding="utf-8")
    blocks = VEVENT.findall(text)

    def replace_block(uid: str, change) -> None:
        nonlocal text
        block = next(b for b in blocks if f"UID:{uid}@" in b)
        text = text.replace(block, change(block))

    replace_block("broker-call", lambda b: "")
    replace_block("course", lambda b: b.replace("SUMMARY:Trading course", "SUMMARY:Trading course (advanced)"))
    replace_block("utc-call", lambda b: b.replace("DTSTART:20440510T140000Z", "DTSTART:20440510T150000Z").replace("DTEND:20440510T150000Z", "DTEND:20440510T160000Z"))
    text = text.replace("END:VCALENDAR\n", NEW_EVENT + "END:VCALENDAR\n")
    (GCAL / "personal_b.ics").write_text(text, encoding="utf-8", newline="\n")
    print("personal_b.ics written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
