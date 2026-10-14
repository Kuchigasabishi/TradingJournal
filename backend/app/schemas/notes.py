from datetime import date as Date

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.db.models import Note
from app.schemas.common import NoteBody


class NoteCreate(BaseModel):
    """A journal note for one calendar day. Notes about a single trade go in the trade's own `notes` field."""

    model_config = ConfigDict(extra="forbid")

    day: Date
    body: NoteBody


class NoteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: Date | None = None
    body: NoteBody | None = None


class NoteRead(BaseModel):
    id: int
    day: Date
    body: str
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @classmethod
    def from_note(cls, note: Note) -> "NoteRead":
        return cls(id=note.id, day=note.day, body=note.body, created_at=note.created_at, updated_at=note.updated_at)
