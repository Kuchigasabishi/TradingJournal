"""Server half of the harness self-test: the real app plus two routes that misbehave. Never shipped.

`scripts/verify.py --self-test` serves this and checks that the harness notices both failures:
an unhandled exception (logged as a 500 error with a traceback) and a write that answers 200 but is
never committed (no commit record, and a rolled-back transaction instead). It lives here, not in the
app, so the app carries no test-only endpoint.
"""
from datetime import date

from fastapi import Request

from app.db.models import Note
from app.main import create_app

app = create_app()


@app.get("/boom")
def boom() -> None:
    raise RuntimeError("canary: unhandled server exception")


@app.post("/canary/forgotten-commit")
def forgotten_commit(request: Request) -> dict[str, str]:
    session = request.app.state.session_factory()
    try:
        session.add(Note(day=date(2030, 1, 1), body="never committed"))
        session.flush()  # the INSERT reaches the database...
    finally:
        session.close()  # ...but nobody commits it, so it rolls back
    return {"status": "ok"}  # and the request still answers 200
