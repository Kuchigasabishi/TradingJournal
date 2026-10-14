"""Day-note use cases."""
import logging
from collections.abc import Sequence
from datetime import date

from sqlalchemy.orm import Session

from app.core.errors import InvalidStateError, NotFoundError, field_error
from app.db.models import Note
from app.db.repositories import NoteRepository
from app.schemas.notes import NoteCreate, NoteUpdate
from app.services.uow import transaction

log = logging.getLogger("app.journal")


class NoteService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = NoteRepository(session)

    def create(self, data: NoteCreate) -> Note:
        note = Note(day=data.day, body=data.body)
        with transaction(self.session):
            self.repo.add(note)
        self.session.refresh(note)
        log.info("note_created", extra={"note_id": note.id, "day": note.day.isoformat()})
        return note

    def get(self, note_id: int) -> Note:
        note = self.repo.get(note_id)
        if note is None:
            raise NotFoundError("Note", note_id)
        return note

    def list(self, from_day: date | None, to_day: date | None, limit: int, offset: int) -> tuple[Sequence[Note], int]:
        if from_day and to_day and from_day > to_day:
            raise InvalidStateError([field_error("from", "from must not be later than to", "range", where="query")])
        return self.repo.list(from_day, to_day, limit, offset)

    def update(self, note_id: int, patch: NoteUpdate) -> Note:
        note = self.get(note_id)
        changes = patch.model_dump(exclude_unset=True)
        if nulls := [name for name, value in changes.items() if value is None]:
            raise InvalidStateError([field_error(name, f"{name} cannot be null", "null_not_allowed") for name in nulls])
        # Even an empty patch goes through the transaction, so every successful write request logs a commit.
        with transaction(self.session):
            for name, value in changes.items():
                setattr(note, name, value)
        self.session.refresh(note)
        log.info("note_updated", extra={"note_id": note.id, "changed_fields": sorted(changes)})
        return note

    def delete(self, note_id: int) -> None:
        note = self.get(note_id)
        with transaction(self.session):
            self.repo.delete(note)
        log.info("note_deleted", extra={"note_id": note_id})
