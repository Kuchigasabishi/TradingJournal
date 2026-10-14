from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session


@contextmanager
def transaction(session: Session) -> Iterator[None]:
    """Commit when the block succeeds, roll back when it raises.

    Services commit here, before the endpoint returns. Committing in a FastAPI dependency's teardown
    would run after the response is sent, so a client could see success for a write that then fails.
    """
    try:
        yield
        session.commit()
    except BaseException:
        session.rollback()
        raise
