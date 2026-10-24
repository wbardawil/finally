# Market Data Backend — Summary

**Status:** Built, tested (90 tests passing, ruff check + format clean), reviewed. Matches PLAN.md, including the session-start price (A4). One caller-side rule remains for step 2 (see [Known Gaps](#known-gaps-vs-planmd)).

Last verified: 2026-10-24.

## What Was Built

A market data subsystem in `backend/app/market/` (8 modules, ~500 lines) that provides live simulated prices or real market data through one interface.

### Architecture

```
MarketDataSource (ABC)
├── SimulatorDataSource  →  GBM simulator (default, no API key needed)
└── MassiveDataSource    →  Polygon.io REST poller (when MASSIVE_API_KEY set)
        │
        ▼
   PriceCache (thread-safe, in-memory)
        │
        ├──→ SSE stream endpoint (/api/stream/prices)
        ├──→ Portfolio valuation      (not built yet)
        └──→ Trade execution          (not built yet)
```

### Modules

| File | Purpose |
|------|---------|
| `models.py` | `PriceUpdate`: immutable frozen dataclass (ticker, price, previous_price, timestamp, session_start_price; derived change, change_percent, session_change, session_change_percent, direction) |
| `interface.py` | `MarketDataSource`: abstract base class defining `start/stop/add_ticker/remove_ticker/get_tickers` |
| `cache.py` | `PriceCache`: thread-safe price store with a version counter for SSE change detection and a session-start price per ticker |
| `seed_prices.py` | Realistic seed prices, per-ticker GBM params (drift/volatility), correlation groups |
| `simulator.py` | `GBMSimulator` (Geometric Brownian Motion with Cholesky-correlated moves) + `SimulatorDataSource` |
| `massive_client.py` | `MassiveDataSource`: REST polling client for Polygon.io via the `massive` package |
| `factory.py` | `create_market_data_source()`: selects simulator or Massive based on the `MASSIVE_API_KEY` env var |
| `stream.py` | `create_stream_router()`: FastAPI SSE endpoint factory using version-based change detection |

### Key Design Decisions

- **Strategy pattern**: both data sources implement the same ABC, so downstream code doesn't care which one is running
- **PriceCache as the single source of truth**: producers write to it and consumers read from it, with no direct coupling between them
- **GBM with correlated moves**: Cholesky decomposition of a sector-based correlation matrix. Tech stocks correlate at 0.6, finance at 0.5, and cross-sector pairs at 0.3
- **Random shock events**: about a 0.1% chance per tick per ticker of a 2-5% move, for visual drama
- **Unknown tickers** get a random seed price ($50–$300) in the simulator, so ticker validation (PLAN §8) must happen at the API boundary

## Actual SSE Wire Format

`GET /api/stream/prices` first sends `retry: 1000`. After that, every ~500ms, **only when the cache version changed**, it sends one event holding a dict of all tracked tickers keyed by ticker:

```
data: {"AAPL": {"ticker": "AAPL", "price": 190.5, "previous_price": 190.42,
                "session_start_price": 190.0, "timestamp": 1761300000.1,
                "change": 0.08, "change_percent": 0.042,
                "session_change_percent": 0.2632, "direction": "up"}, ...}
```

- `change` / `change_percent` are **tick-over-tick** (vs `previous_price`). They drive the flash direction.
- `session_change_percent` is **vs `session_start_price`**. It is the watchlist "change %" (PLAN §6, §10).
- `session_start_price` is the first price the cache recorded for the ticker since it began being tracked. `PriceCache.remove()` resets it: sources reseed a re-added ticker (unknown tickers get a *random* seed), so keeping the old start would show a fake move.

## Known Gaps vs PLAN.md

| # | Gap | PLAN ref | Impact | Owner |
|---|-----|----------|--------|-------|
| 1 | `remove_ticker()` evicts the ticker from the cache. This is correct for a data source, but the module cannot know about positions | A1, §6 | The step-2 watchlist/portfolio code must only call it when the ticker is neither watched nor held, or held positions lose their price | Backend step 2 |
| 2 | Massive free tier updates every 15s | B18 | Price flashes will be sparse. The frontend must not assume 500ms | Frontend |

Resolved 2026-10-24: the session-start price (A4) was added to the cache, model, and SSE payload. `create_stream_router()` now builds a fresh router per call (it used to share a module-level router, so a second call duplicated routes).

## Test Suite

**90 tests, all passing.** There are 7 test modules in `backend/tests/market/`.

| Module | Tests | Coverage |
|--------|-------|----------|
| test_models.py | 16 | models.py: 100% |
| test_cache.py | 18 | cache.py: 100% |
| test_simulator.py | 19 | simulator.py: 98% |
| test_simulator_source.py | 10 | (integration tests) |
| test_factory.py | 7 | factory.py: 100% |
| test_massive.py | 13 | massive_client.py: 94% (API calls are mocked) |
| test_stream.py | 7 | stream.py: 92% (generator driven with a fake request) |

Overall coverage: 97% (measured 2026-10-24). I also checked `/api/stream/prices` by hand against a real uvicorn server running the simulator.

```bash
cd backend
uv run pytest -v
uv run pytest --cov=app
```

## Code Review & Fixes Applied

A code review found 7 issues, and all of them were fixed. The full review is in `archive/MARKET_DATA_REVIEW.md`. In short: hatch wheel packaging config, top-level `massive` imports, the SSE generator return type, a public `GBMSimulator.get_tickers()`, cleanup of the correlation constants, removal of unused test imports, and corrected Massive test mocks.

## Demo

`backend/market_data_demo.py` is a Rich terminal dashboard driven by the real `SimulatorDataSource` + `PriceCache`:

```bash
cd backend
uv run market_data_demo.py                          # 10 default tickers, 60s
uv run market_data_demo.py --duration 20 --tickers AAPL,TSLA,NVDA
```

It shows price, tick change, tick %, **session %** (`PriceUpdate.session_change_percent`), a direction arrow, a sparkline, and an event log for >1% ticks. When it exits (timeout or Ctrl+C) it prints a seed-vs-final summary.

`rich` is a **dev-only** dependency (`[dependency-groups] dev`). Plain `uv sync` / `uv run` include it. The production image (`uv sync --frozen --no-dev`) does not, so the demo will not run inside the Docker container.

## Usage for Downstream Code

```python
from app.market import PriceCache, create_market_data_source, create_stream_router

# Startup (e.g. in a FastAPI lifespan)
cache = PriceCache()
source = create_market_data_source(cache)  # Reads MASSIVE_API_KEY; returns an unstarted source
await source.start(["AAPL", "GOOGL", "MSFT", ...])  # watchlist ∪ held tickers (A1)
app.include_router(create_stream_router(cache))

# Read prices
update = cache.get("AAPL")          # PriceUpdate or None
price = cache.get_price("AAPL")     # float or None. None means reject the trade (B8)
all_prices = cache.get_all()        # dict[str, PriceUpdate]

# Dynamic tracking
await source.add_ticker("TSLA")
await source.remove_ticker("GOOGL") # only if not watched AND not held (gap #1)

# Shutdown
await source.stop()
```
