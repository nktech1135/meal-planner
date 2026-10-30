from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_db
from app.models import Food, User
from app.routers.foods import food_out
from app.schemas import FoodOut, ImportIn, SearchHitOut, SourceOut
from app.security import current_user
from app.settings_store import get_runtime
from app.sources.base import DataSource, SourceError
from app.sources.registry import build_sources, upsert_external_food

router = APIRouter(prefix="/api/sources", tags=["sources"])


def get_sources(settings: Settings = Depends(get_runtime)) -> dict[str, DataSource]:
    return build_sources(settings)


def _source(key: str, sources: dict[str, DataSource]) -> DataSource:
    src = sources.get(key)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown source")
    if not src.enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, src.disabled_reason or "Source disabled")
    return src


@router.get("", response_model=list[SourceOut])
def list_sources(_: User = Depends(current_user), sources: dict = Depends(get_sources)):
    return [
        SourceOut(key=s.key, name=s.name, description=s.description, homepage=s.homepage,
                  trust_level=str(s.trust_level), paid=s.paid, enabled=s.enabled, disabled_reason=s.disabled_reason)
        for s in sources.values()
    ]


@router.get("/{key}/search", response_model=list[SearchHitOut])
def search_source(
    key: str,
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(20, le=50),
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
    sources: dict = Depends(get_sources),
):
    src = _source(key, sources)
    try:
        hits = src.search(q, limit)
    except SourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    imported = dict(db.execute(
        select(Food.source_id, Food.id).where(Food.source == key, Food.source_id.in_([h.source_id for h in hits]))
    ).all())
    return [SearchHitOut(**h.__dict__, imported_food_id=imported.get(h.source_id)) for h in hits]


@router.post("/{key}/import", response_model=FoodOut)
def import_food(
    key: str,
    body: ImportIn,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
    sources: dict = Depends(get_sources),
):
    src = _source(key, sources)
    try:
        ext = src.fetch(body.source_id, body.name_hint)
    except SourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id for this source") from None
    return food_out(upsert_external_food(db, ext))
