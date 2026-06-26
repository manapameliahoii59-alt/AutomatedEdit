from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import UsageEvent, User, UserSecret
from app.schemas import SecretsOut, UsageReport

router = APIRouter(prefix="/api/client", tags=["client"])


@router.get("/secrets", response_model=SecretsOut)
def get_secrets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(UserSecret).filter(UserSecret.user_id == user.id).first()
    if row is None:
        return SecretsOut()
    return SecretsOut(deepseek_keys=row.deepseek_keys or "", dashscope_key=row.dashscope_key or "")


@router.post("/usage", status_code=201)
def report_usage(
    body: UsageReport,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = UsageEvent(
        user_id=user.id,
        event=body.event,
        success=body.success,
        duration_ms=max(0, body.duration_ms),
        meta=body.meta or "",
        client_version=body.client_version or "",
    )
    db.add(event)
    db.commit()
    return {"ok": True}
