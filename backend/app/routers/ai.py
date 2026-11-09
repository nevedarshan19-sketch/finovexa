from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import ChatIn
from ..security import get_current_user, rate_limit
from ..services.ai.orchestrator import answer_question, chat_history
from ..services.ai.tools import TOOLS

router = APIRouter(prefix="/ai", tags=["AI orchestrator"])


@router.post("/chat", dependencies=[Depends(rate_limit("ai_chat", 20, 60))])
def chat(
    payload: ChatIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    answer = answer_question(db, user, payload.question.strip())
    return {
        "answer": answer.model_dump(),
        "agent_note": (
            "Facts come from authorized backend tools. The assistant cannot change payment, "
            "approval or order status. External news is treated as untrusted data."
        ),
    }


@router.get("/history")
def history(
    limit: int = Query(default=40, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"items": chat_history(db, user, limit)}


@router.get("/tools")
def tools(user: User = Depends(get_current_user)):
    return {
        "items": [
            {
                "name": spec.name,
                "description": spec.description,
                "arguments": spec.args_model.model_json_schema(),
                "read_only": True,
            }
            for spec in TOOLS.values()
        ],
        "policy": (
            "Tools are read-only, authorized on the server for the authenticated business, and cannot "
            "send reminders, move money or place orders. Consequential actions require the Approval Center."
        ),
    }
