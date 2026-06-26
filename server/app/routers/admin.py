from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.models import UsageEvent, User
from app.schemas import UsageEventOut

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/usage", response_model=list[UsageEventOut])
def list_usage(
    user_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(UsageEvent).order_by(desc(UsageEvent.id)).limit(limit)
    if user_id is not None:
        stmt = stmt.where(UsageEvent.user_id == user_id)
    rows = db.scalars(stmt).all()
    return [UsageEventOut.model_validate(r) for r in rows]
