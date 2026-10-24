# FinAlly — Project Summary

Snapshot of what exists, what doesn't, and what's next. `PLAN.md` is the contract. This file only tracks progress against it. When it disagrees with `PLAN.md`, `PLAN.md` wins and this file is stale.

Last updated: 2026-10-24.

## Build Status

Build order from `PLAN.md` §13:

| Step | Scope | Status |
|------|-------|--------|
| 0 | Market data module (`backend/app/market/`) | **Done**, session-start price included. 90 tests passing |
| 1 | DB init + portfolio/trade endpoints (`backend/app/db/`) | Not started. **Next action** |
| 2 | Watchlist endpoints + SSE route wired to market data (rule A1) | Not started |
| 3 | Chat endpoint (`LLM_MOCK` first, then LiteLLM/OpenRouter) | Not started |
| 4 | Frontend (Next.js static export) | Not started |
| 5 | Dockerfile, start/stop scripts, E2E | Not started |

There is no FastAPI `main.py` / app entrypoint yet. The SSE router exists but is not mounted anywhere.

## What Exists in the Repo

| Path | What it is |
|------|------------|
| `backend/app/market/` | Market data subsystem. See `MARKET_DATA_SUMMARY.md` |
| `backend/tests/market/` | 90 pytest tests, 97% coverage |
| `backend/market_data_demo.py` | Rich terminal demo: `cd backend && uv run market_data_demo.py` |
| `planning/PLAN.md` | Project spec and decision log (the contract) |
| `planning/MARKET_DATA_SUMMARY.md` | Market data API, wire format, known gaps |
| `planning/REVIEW*.md`, `CHANGES.md` | Plan reviews whose accepted items are already folded into `PLAN.md` §13 |
| `planning/archive/` | Original market data design docs (historical) |
| `.env.example`, `db/.gitkeep` | Env template. `db/*.db` is gitignored |

## Open Gaps Between PLAN.md and Code

1. **`remove_ticker()` evicts from the cache.** The step-2 watchlist/portfolio code must compute `watchlist ∪ held` before calling it (A1). This is a rule for the caller, not a bug in the market module.
2. **SSE payload shape**: one event holds a dict of all tickers, sent only when the cache version changes. The plan describes per-ticker fields, and the shape is compatible, but the frontend must parse a dict. Use `session_change_percent` for the watchlist and `direction` for flashes.

## Decisions Recently Applied

- **C24**: `rich` moved to `[dependency-groups] dev`, so `uv sync --frozen --no-dev` (Docker) no longer ships it. Dev commands became plain `uv run pytest` (no `--extra dev`).
- **C23**: `db/*.db` gitignored, and `db/.gitkeep` and `.env.example` added.
- **A4**: session-start price implemented in `PriceCache` and the SSE payload. It resets when a ticker stops being tracked (clarified in PLAN §6).
- `create_stream_router()` returns a fresh router per call. All backend files pass `ruff format --check`.

## Next Action

Build step 1 in `backend/app/db/`: schema + lazy init + seed, then `POST /api/portfolio/trade` with the money rules in `PLAN.md` §7 and `BEGIN IMMEDIATE` atomicity (B9), with unit tests first.
