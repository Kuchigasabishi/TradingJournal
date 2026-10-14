from datetime import date

from fastapi import APIRouter, Depends, Path, Query, Response

from app.api.deps import note_service
from app.schemas.common import Page
from app.schemas.notes import NoteCreate, NoteRead, NoteUpdate
from app.services.notes import NoteService

router = APIRouter(prefix="/api/notes", tags=["notes"])

NoteId = Path(ge=1, description="Note id")


@router.post("", response_model=NoteRead, status_code=201)
def create_note(body: NoteCreate, response: Response, service: NoteService = Depends(note_service)) -> NoteRead:
    """Create a note for one calendar day."""
    note = service.create(body)
    response.headers["Location"] = f"/api/notes/{note.id}"
    return NoteRead.from_note(note)


@router.get("", response_model=Page[NoteRead])
def list_notes(
    from_day: date | None = Query(None, alias="from", description="First day, inclusive"),
    to_day: date | None = Query(None, alias="to", description="Last day, inclusive"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: NoteService = Depends(note_service),
) -> Page[NoteRead]:
    rows, total = service.list(from_day, to_day, limit, offset)
    return Page[NoteRead](items=[NoteRead.from_note(note) for note in rows], total=total, limit=limit, offset=offset)


@router.get("/{note_id}", response_model=NoteRead, responses={404: {"description": "No such note"}})
def get_note(note_id: int = NoteId, service: NoteService = Depends(note_service)) -> NoteRead:
    return NoteRead.from_note(service.get(note_id))


@router.patch("/{note_id}", response_model=NoteRead, responses={404: {"description": "No such note"}})
def update_note(body: NoteUpdate, note_id: int = NoteId, service: NoteService = Depends(note_service)) -> NoteRead:
    return NoteRead.from_note(service.update(note_id, body))


@router.delete("/{note_id}", status_code=204, responses={404: {"description": "No such note"}})
def delete_note(note_id: int = NoteId, service: NoteService = Depends(note_service)) -> Response:
    service.delete(note_id)
    return Response(status_code=204)
