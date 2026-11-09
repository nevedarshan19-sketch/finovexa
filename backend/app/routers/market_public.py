from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..services.nifty_recommendations import screen

router = APIRouter(tags=["Public market research"])


@router.get("/market/nifty50/recommendations")
def nifty50_recommendations(
    horizon: str = Query(default="3m", pattern="^(1m|3m|6m)$"),
    q: str | None = Query(default=None, max_length=80),
    sort: str = Query(default="upside", pattern="^(upside|confidence|name)$"),
    confidence: str | None = Query(default=None, pattern="^(low|medium|high)$"),
    min_upside: float | None = Query(default=None, ge=0, le=100),
):
    try:
        return screen(
            horizon=horizon,
            min_upside=min_upside,
            confidence=confidence,
            query=q,
            sort=sort,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
