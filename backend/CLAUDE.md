# Backend — Developer Guide

## Project Setup

```bash
cd backend
uv sync --extra dev   # Install all dependencies including test/lint tools
```

## Market Data API

The market data subsystem lives in `app/market/`. Use these imports:

```python
from app.market import PriceCache, PriceUpdate, MarketDataSource, create_market_data_source
```

### Core Types

- **`PriceUpdate`** — Immutable dataclass: `ticker`, `price`, `previous_price`, `timestamp`, plus properties `change`, `change_percent`, `direction` ("up"/"down"/"flat"), and `to_dict()` for JSON serialization.

- **`PriceCache`** — Thread-safe in-memory store. Key methods:
  - `update(ticker, price, timestamp=None) -> PriceUpdate`
  - `get(ticker) -> PriceUpdate | None`
  - `get_price(ticker) -> float | None`
  - `get_all() -> dict[str, PriceUpdate]`
  - `remove(ticker)`
  - `version` property — monotonic counter, increments on every update (for SSE change detection)

- **`MarketDataSource`** — Abstract interface implemented by `SimulatorDataSource` and `MassiveDataSource`. Lifecycle: `start(tickers)` -> `add_ticker()` / `remove_ticker()` -> `stop()`.

- **`create_market_data_source(cache)`** — Factory. Returns `MassiveDataSource` if `MASSIVE_API_KEY` is set, otherwise `SimulatorDataSource`.

### SSE Streaming

```python
from app.market import create_stream_router

router = create_stream_router(price_cache)  # Returns FastAPI APIRouter
# Endpoint: GET /api/stream/prices (text/event-stream)
```

### Seed Data

Default tickers: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX. Seed prices and per-ticker volatility/drift params are in `app/market/seed_prices.py`.

## App, Database, Portfolio

- **`app/main.py`** — `create_app(price_cache=None, db_path=None, snapshot_interval=30)`. Lifespan creates/seeds the DB and runs the 30s snapshot loop. Module-level `app` for uvicorn. Market source + SSE are not wired yet (build step 2).
- **`app/db/`** — `schema.sql` + `get_connection(db_path)` (lazy init: creates tables, seeds the default user and 10-ticker watchlist only when the user row is absent) and `transaction(conn)` (`BEGIN IMMEDIATE`). DB file: `DB_PATH` env var, else `<repo>/db/finally.db`. Connections are autocommit (`isolation_level=None`); wrap writes in `transaction()`.
- **`app/validation.py`** — `normalize_ticker`, `normalize_side`, `parse_quantity` (returns `Decimal`). Reuse these for watchlist and LLM actions.
- **`app/errors.py`** — raise `AppError(msg, status_code=400)`; handlers turn every non-2xx (incl. request validation, 404, 500) into `{"error": "..."}`.
- **`app/portfolio/`** — `execute_trade(conn, cache, ticker, side, quantity)` is the single trade path (manual and LLM): validates, prices from `cache.get_price`, cent-rounds the notional half-up with `Decimal`, and does check + writes + snapshot in one transaction. Raises `AppError` on any failure. `get_portfolio`, `record_snapshot`, `get_history` (last 500, oldest first).

## Running Tests

```bash
uv run --extra dev pytest -v              # All tests
uv run --extra dev pytest --cov=app       # With coverage
uv run --extra dev ruff check app/ tests/ # Lint
```

## Demo

```bash
uv run market_data_demo.py   # Live terminal dashboard with simulated prices
```
