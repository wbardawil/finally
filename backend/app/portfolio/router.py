"""Portfolio REST endpoints: /api/portfolio, /trade, /history."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.db import get_connection

from . import service

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class TradeRequest(BaseModel):
    # Typed Any on purpose: execute_trade owns all validation so manual and
    # LLM trades share one rule set and one set of error messages.
    ticker: Any
    quantity: Any
    side: Any


# Sync handlers run in FastAPI's threadpool; each opens its own SQLite connection.
@router.get("")
def get_portfolio(request: Request) -> dict:
    with get_connection(request.app.state.db_path) as conn:
        return service.get_portfolio(conn, request.app.state.price_cache)


@router.post("/trade")
def trade(body: TradeRequest, request: Request) -> dict:
    with get_connection(request.app.state.db_path) as conn:
        result = service.execute_trade(
            conn, request.app.state.price_cache, body.ticker, body.side, body.quantity
        )
    return result.to_dict()


@router.get("/history")
def history(request: Request) -> dict:
    with get_connection(request.app.state.db_path) as conn:
        return {"snapshots": service.get_history(conn)}
