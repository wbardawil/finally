"""FastAPI application factory.

Step 1 scope: DB init, portfolio endpoints, health. The market data source and
SSE route are wired in step 2; until then the price cache is empty unless one
is injected, so trades return "No price available".
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI

from app.db import default_db_path, get_connection
from app.errors import register_error_handlers
from app.market import PriceCache
from app.portfolio import record_snapshot
from app.portfolio import router as portfolio_router

logger = logging.getLogger(__name__)

SNAPSHOT_INTERVAL_SECONDS = 30.0


async def _snapshot_loop(db_path: Path, cache: PriceCache, interval: float) -> None:
    def _record() -> None:
        with get_connection(db_path) as conn:
            record_snapshot(conn, cache)

    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(_record)
        except Exception:
            logger.exception("Portfolio snapshot failed")


def create_app(
    price_cache: PriceCache | None = None,
    db_path: Path | None = None,
    snapshot_interval: float = SNAPSHOT_INTERVAL_SECONDS,
) -> FastAPI:
    cache = price_cache if price_cache is not None else PriceCache()
    path = db_path or default_db_path()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        with get_connection(path):  # create + seed the DB at startup
            pass
        task = asyncio.create_task(_snapshot_loop(path, cache, snapshot_interval))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="FinAlly", lifespan=lifespan)
    app.state.price_cache = cache
    app.state.db_path = path
    register_error_handlers(app)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(portfolio_router)
    return app


app = create_app()
