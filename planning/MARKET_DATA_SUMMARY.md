# Market Data Backend — Summary

**Status:** Built, tested (73 tests passing, ruff clean), reviewed. **One gap against PLAN.md:** the session-start price required by decision A4 is not implemented yet (see [Known Gaps](#known-gaps-vs-planmd)).

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
| `models.py` | `PriceUpdate`: immutable frozen dataclass (ticker, price, previous_price, timestamp; derived change, change_percent, direction) |
| `interface.py` | `MarketDataSource`: abstract base class defining `start/stop/add_ticker/remove_ticker/get_tickers` |
| `cache.py` | `PriceCache`: thread-safe price store with a version counter for SSE change detection |
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
                "timestamp": 1761300000.1, "change": 0.08,
                "change_percent": 0.042, "direction": "up"}, ...}
```

`change` and `change_percent` are **tick-over-tick** (vs `previous_price`), not session change. The frontend should not label them "change %" in the watchlist (see Known Gaps).

## Known Gaps vs PLAN.md

| # | Gap | PLAN ref | Impact | Owner |
|---|-----|----------|--------|-------|
| 1 | **No session-start price** in `PriceCache` / `PriceUpdate` / SSE payload | A4, §6, §10 | Watchlist "change % since session start" cannot be built from SSE as specified. Fix: store the first price per ticker in the cache, add `session_start_price` to `PriceUpdate.to_dict()`, and add tests | Backend, before frontend watchlist |
| 2 | `remove_ticker()` evicts the ticker from the cache unconditionally | A1, §6 | The caller (watchlist/portfolio layer) must only call it when the ticker is neither watched nor held, or held positions lose their price | Backend step 2 |
| 3 | `stream.py` registers routes on a module-level `router`, so calling `create_stream_router()` twice adds duplicate routes | n/a | Harmless with one app instance, but it surprises tests that build several apps | Low priority |
| 4 | Massive free tier updates every 15s | B18 | Price flashes will be sparse. The frontend must not assume 500ms | Frontend |

## Test Suite

**73 tests, all passing.** There are 6 test modules in `backend/tests/market/`.

| Module | Tests | Coverage |
|--------|-------|----------|
| test_models.py | 11 | models.py: 100% |
| test_cache.py | 13 | cache.py: 100% |
| test_simulator.py | 17 | simulator.py: 98% |
| test_simulator_source.py | 10 | (integration tests) |
| test_factory.py | 7 | factory.py: 100% |
| test_massive.py | 13 | massive_client.py: 56% (API methods are mocked) |

Overall coverage: 84%. `stream.py` has no direct tests.

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

It shows price, tick change, tick %, **session %** (computed by the demo from the first price it saw, which previews gap #1), a direction arrow, a sparkline, and an event log for >1% ticks. When it exits (timeout or Ctrl+C) it prints a seed-vs-final summary.

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
await source.remove_ticker("GOOGL") # only if not watched AND not held (gap #2)

# Shutdown
await source.stop()
```
