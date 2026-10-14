from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.db.repositories import TagRepository
from app.schemas.trades import TagUsage

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[TagUsage])
def list_tags(session: Session = Depends(get_session)) -> list[TagUsage]:
    """Tags in use, most used first. A tag disappears when its last trade does."""
    return [TagUsage(name=name, count=count) for name, count in TagRepository(session).usage()]
