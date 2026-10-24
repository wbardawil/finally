# Backend — Developer Guide

## Project Setup

```bash
cd backend
uv sync          # Runtime deps + [dependency-groups] dev (pytest, ruff, rich)
uv sync --no-dev # Runtime only, as in the Docker image
```

Add runtime deps with `uv add <pkg>`, dev-only deps with `uv add --dev <pkg>`.

## Market Data API

The market data subsystem lives in `app/market/`. Use these imports:

```python
from app.market import PriceCache, PriceUpdate, MarketDataSource, create_market_data_source
```

### Core Types

- **`PriceUpdate`** — Immutable dataclass: `ticker`, `price`, `previous_price`, `timestamp`, plus properties `change`, `change_percent`, `direction` ("up"/"down"/"flat"), and `to_dict()` for JSON serialization. `change`/`change_percent` are tick-over-tick. **There is no session-start price yet** (PLAN A4); see `planning/MARKET_DATA_SUMMARY.md` "Known Gaps".

- **`PriceCache`** — Thread-safe in-memory store. Key methods:
  - `update(ticker, price, timestamp=None) -> PriceUpdate`
  - `get(ticker) -> PriceUpdate | None`
  - `get_price(ticker) -> float | None`
  - `get_all() -> dict[str, PriceUpdate]`
  - `remove(ticker)`
  - `version` property — monotonic counter, increments on every update (for SSE change detection)

- **`MarketDataSource`** — Abstract interface implemented by `SimulatorDataSource` and `MassiveDataSource`. Lifecycle: `start(tickers)` -> `add_ticker()` / `remove_ticker()` -> `stop()`. `remove_ticker()` also evicts the ticker from the cache, so only call it when the ticker is neither on the watchlist nor held (PLAN A1).

- **`create_market_data_source(cache)`** — Factory. Returns `MassiveDataSource` if `MASSIVE_API_KEY` is set, otherwise `SimulatorDataSource`.

### SSE Streaming

```python
from app.market import create_stream_router

router = create_stream_router(price_cache)  # Returns FastAPI APIRouter
# Endpoint: GET /api/stream/prices (text/event-stream)
```

### Seed Data

Default tickers: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX. Seed prices and per-ticker volatility/drift params are in `app/market/seed_prices.py`.

## Running Tests

```bash
uv run pytest -v               # All tests
uv run pytest --cov=app        # With coverage
uv run ruff check .            # Lint
uv run ruff format --check .   # Format check
```

## Demo

```bash
uv run market_data_demo.py                                  # 10 default tickers, 60s
uv run market_data_demo.py --duration 20 --tickers AAPL,TSLA
```

`rich` is dev-only, so the demo does not run in the production image.
