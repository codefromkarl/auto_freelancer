from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database.connection import get_db
from services.approved_bids import prepare_bid
from services.qqbot_service import QQBotConfig
from services.qqbot_store import QQBotStore
from config import settings
import time

router = APIRouter()


class PrepareRequest(BaseModel):
    project_id: int = Field(gt=0)
    amount: float = Field(gt=0)
    period: int = Field(ge=1, le=365)
    amount_currency: str | None = None
    description: str | None = None


@router.post('/prepare')
async def prepare(request: PrepareRequest, db: Session = Depends(get_db)):
    try:
        snapshot = await prepare_bid(db, request.project_id, request.amount, request.period,
                                    request.description, request.amount_currency)
        snapshot['submission_enabled'] = settings.BID_SUBMISSION_ENABLED
        return {'status': 'success', 'data': snapshot}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get('/{approval_id}')
async def read_approval(approval_id: str):
    try:
        snapshot = QQBotStore(QQBotConfig.from_env().state_path).get(approval_id)
        if snapshot['expires_at'] <= time.time() and snapshot['state'] in {'pending', 'approved', 'auto_pending', 'auto_authorized'}:
            snapshot['state'] = 'expired'
        snapshot['submission_enabled'] = settings.BID_SUBMISSION_ENABLED
        return {'status': 'success', 'data': snapshot}
    except ValueError as exc:
        raise HTTPException(404, str(exc))
