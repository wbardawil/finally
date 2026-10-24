"""Tests for the SSE streaming endpoint."""

import json

from fastapi import FastAPI

from app.market.cache import PriceCache
from app.market.stream import _generate_events, create_stream_router


class FakeRequest:
    """Minimal stand-in for a Starlette Request: disconnects after N checks."""

    def __init__(self, checks_before_disconnect: int) -> None:
        self._remaining = checks_before_disconnect
        self.client = None

    async def is_disconnected(self) -> bool:
        self._remaining -= 1
        return self._remaining < 0


async def collect(cache: PriceCache, checks: int) -> list[str]:
    return [e async for e in _generate_events(cache, FakeRequest(checks), interval=0)]


class TestStreamRouter:
    def test_route_registered(self):
        router = create_stream_router(PriceCache())
        assert [r.path for r in router.routes] == ["/api/stream/prices"]

    def test_factory_returns_independent_routers(self):
        """Calling the factory twice must not duplicate routes."""
        first = create_stream_router(PriceCache())
        second = create_stream_router(PriceCache())
        assert first is not second
        assert len(first.routes) == 1
        assert len(second.routes) == 1

    def test_mounts_on_app(self):
        app = FastAPI()
        app.include_router(create_stream_router(PriceCache()))
        paths = [r.path for r in app.routes]
        assert paths.count("/api/stream/prices") == 1


class TestGenerateEvents:
    async def test_starts_with_retry_directive(self):
        events = await collect(PriceCache(), checks=0)
        assert events == ["retry: 1000\n\n"]

    async def test_empty_cache_sends_no_data(self):
        events = await collect(PriceCache(), checks=2)
        assert events == ["retry: 1000\n\n"]

    async def test_payload_shape_includes_session_start(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.update("AAPL", 209.00)

        events = await collect(cache, checks=1)

        assert len(events) == 2
        assert events[1].startswith("data: ") and events[1].endswith("\n\n")
        payload = json.loads(events[1][len("data: ") :])
        aapl = payload["AAPL"]
        assert aapl["price"] == 209.00
        assert aapl["previous_price"] == 190.00
        assert aapl["session_start_price"] == 190.00
        assert aapl["session_change_percent"] == 10.0
        assert aapl["direction"] == "up"

    async def test_unchanged_cache_is_not_resent(self):
        """Only sends when the cache version changes."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        events = await collect(cache, checks=3)
        assert len([e for e in events if e.startswith("data: ")]) == 1
