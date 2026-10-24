# FinAlly Backend

FastAPI backend for the FinAlly AI Trading Workstation.

## Structure

- `app/` - Application code
  - `market/` - Market data subsystem
    - `models.py` - PriceUpdate dataclass
    - `cache.py` - Thread-safe price cache
    - `interface.py` - MarketDataSource abstract interface
    - `simulator.py` - GBM-based market simulator
    - `massive_client.py` - Massive/Polygon.io API client
    - `factory.py` - Data source factory
    - `stream.py` - SSE streaming endpoint
    - `seed_prices.py` - Default ticker prices and parameters

- `tests/` - Unit and integration tests
  - `market/` - Market data tests

- `market_data_demo.py` - Rich terminal demo of the simulator (dev-only)

## Setup

```bash
uv sync            # Runtime deps + the dev group (pytest, ruff, rich)
uv sync --no-dev   # Runtime deps only (what the Docker image uses)
```

## Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=app --cov-report=html

# Run specific test file
uv run pytest tests/market/test_simulator.py

# Run with verbose output
uv run pytest -v
```

## Demo

```bash
uv run market_data_demo.py                                  # 10 default tickers, 60s
uv run market_data_demo.py --duration 20 --tickers AAPL,TSLA
```

## Environment Variables

- `MASSIVE_API_KEY` - Optional. If set, use real market data from Massive API. If not set, use the built-in simulator.

## Development

```bash
# Run linter
uv run ruff check .

# Format code
uv run ruff format .
```
