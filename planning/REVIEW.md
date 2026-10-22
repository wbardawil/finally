# Review of PLAN.md

Reviewed against sections 1–13, `planning/MARKET_DATA_SUMMARY.md`, and the existing market-data source. This is a specification review; no runtime tests or external provider checks were performed.

The architecture fits the capstone well. A static frontend, one FastAPI process, SQLite, and a shared price cache keep implementation manageable. Before building the remaining application, resolve the contracts below. Section 13 already identifies useful issues, but several recommendations remain separate from—and conflict with—the main specification.

## High priority

### 1. Consolidate the authoritative specification

**References:** sections 4, 6–8, 11–13.

The document currently describes subscriptions as equivalent to the watchlist despite needing held tickers; mixes named volumes and directory mounts; proposes both raw and calculated portfolio responses; and describes both host-based and containerized E2E testing. Section 13's simplifications are not clearly accepted decisions.

**Recommendation:** fold accepted rules into the sections they modify and keep a short decisions log. Specify request/response examples, errors, timestamp units, and ordering. Add chat-history retrieval if persisted conversations should reappear after a browser reload; the current API only exposes sending messages.

### 2. Define the complete subscription lifecycle

**References:** sections 6, 8, 9; section 13 A1/B8.

Both data sources remove cached prices when `remove_ticker()` runs. Tracking watchlist union open positions, as section 13 proposes, must also cover startup restoration, first buys, final sells, and failed subscription updates. Manual orders and chat can name unwatched tickers. In Massive mode, adding a ticker waits for a later poll; the simulator supplies an immediate seed price.

**Recommendation:** restore subscriptions from the database before serving traffic. Decide whether an unwatched buy is rejected until a quote is ready or subscribes and waits with a bounded timeout. Apply watchlist additions before dependent chat trades. Removing a watchlist entry must never remove pricing for an open position.

**Acceptance:** buy a ticker, remove it from the watchlist, restart, then still value and sell it. Test adding and buying a new ticker through chat in both data modes.

### 3. Require valid, fresh quotes for execution

**References:** sections 6–8; section 13 B8/B18.

`MassiveDataSource._poll_once()` logs failures and retains prior quotes. A non-null `cache.get_price()` therefore does not establish that a quote is executable. An SSE connection can remain open while upstream data has stopped. Missing quotes also need valuation behavior: substituting zero would corrupt portfolio totals and snapshots.

**Recommendation:** define freshness thresholds by source, timestamp semantics, and behavior outside market hours. Reject fills against missing, stale, non-positive, or non-finite quotes. Show last-known valuations as stale or report incomplete valuation. Expose source mode and freshness separately from SSE connection status. Define how provider authorization or entitlement failures appear; this review did not verify provider availability.

### 4. Make trades atomic, precise, and retry-safe

**References:** sections 7–9; section 13 A3/B9/B10.

A transaction is necessary, but it does not prevent duplicate fills when a response is lost and the client retries. Fractional shares also make “round cash to cents on every trade” insufficient: a tiny order can round to zero cost while increasing holdings.

**Recommendation:** choose consistent fixed precision for quantity, price, notional, cash, and average cost. Define minimum order notional and reject non-finite inputs. In one transaction, validate balances, update cash/positions, append the trade, and record its snapshot. Define SQLite lock timeout/error behavior. Persist request IDs for manual orders and chat submissions and return the prior result on retry. Give chat actions stable IDs and persist each committed outcome so partial completion can be recovered without replaying fills.

**Acceptance:** concurrent buys cannot overspend; concurrent sells cannot oversell; replayed requests do not duplicate fills; tiny fractional orders cannot create free holdings.

### 5. Separate proposed LLM actions from actual outcomes

**References:** section 9; section 13 B10–B14.

Structured JSON does not establish user intent or successful execution. The assistant writes its message before trades run, so it may claim success for a rejected action. Section 9 says the error lets the LLM inform the user, while section 13 explicitly avoids a second call.

**Recommendation:** preserve automatic execution for this simulation, but require explicit user intent to trade. Validate all actions through the manual-trade service, bound action counts, and define action ordering and partial failures. Render backend execution outcomes as authoritative. Define provider timeout, missing-key, malformed-output, and network-error responses. Malformed output must execute no actions; prefer a clear failure message to displaying raw JSON. Serialize chat turns or define ordering to avoid contradictory history. Keep inference outside database write transactions and use asynchronous inference or offload synchronous calls.

## Medium priority

### 6. Specify application lifecycle and simulator continuity

**References:** sections 3, 4, 6, 7, 11.

Initialize and seed the database idempotently in application lifespan, restore subscriptions, then start market and snapshot tasks. Stop tasks cleanly at shutdown. Explicitly require one application worker: multiple workers would have separate simulated markets, caches, and periodic tasks.

The simulator currently restarts from seed prices, including new random prices for unknown tickers, while holdings persist. Decide whether a restart begins a new market session or preserves prices. For continuity, persist and restore latest simulator quotes at a defined interval and shutdown, documenting crash tolerance. Last trade prices are not the latest market prices and should not be treated as complete continuity. Also define what happens when switching data modes with existing holdings. Add a schema version and upgrade policy even if the first build needs no migration framework.

### 7. Document the actual SSE contract

**References:** sections 6, 10; `stream.py`, `cache.py`, `models.py`.

The existing stream sends a full ticker-keyed map when the cache version changes, rather than an individual event per ticker at a guaranteed 500 ms cadence. Timestamps are Unix seconds. `change_percent` measures the previous update, not the previous day's close.

`PriceCache.remove()` does not increment the version, and the stream emits no data for an empty cache. Removing the final ticker can therefore leave clients with stale displayed state. Reconnects resend current state without replaying missed ticks.

**Recommendation:** define full-snapshot replacement semantics, increment versions on removals, and publish empty snapshots. Add heartbeats and quote freshness handling. Deduplicate unchanged ticker timestamps before appending chart points or flashing prices. Choose an explicit baseline for daily/session change and label it accurately. Document chart gaps after reconnect unless historical backfill is added.

### 8. Complete portfolio and chart semantics

**References:** sections 7, 8, 10; section 13 B15–B17.

Equity, unrealized P&L, and total profit differ. Selling a profitable holding removes unrealized profit but should not erase overall performance. Define equity as cash plus holdings, unrealized P&L from open positions, and total profit as equity minus the initial $10,000 while deposits and withdrawals remain unsupported.

Specify the treemap denominator and whether cash appears. Seed an initial history point. Define timestamp ordering, time ranges, downsampling, and retention. Limiting API responses alone does not bound database growth. Cap frontend chart buffers too. Refresh authoritative cash and holdings after manual and chat mutations before applying quote-based valuation.

### 9. Finish run and development contracts

**References:** sections 5, 9, 11; section 13 A6/B19/B20.

Use a named Docker volume consistently and document a separate local-development database path. Bind the unauthenticated app to localhost in every example command, including README instructions. Specify no-key behavior: the terminal should work while chat explains its unavailable state; mock mode should need no external keys.

Point to the actual repository skill `.claude/skills/cerebras/SKILL.md` rather than relying on the unresolved name `cerebras-inference`. Define static-serving precedence so unknown `/api/*` paths return API errors rather than frontend HTML. Include a frontend development proxy strategy and reproducible frontend installs with a committed lockfile. Address the already identified database ignore patterns, `.env.example`, and runtime directories. Distinguish server health from market-data and chat availability.

## Validation and recommended sequence

Keep existing provider parsing/unit tests. Section 13's simulator-only simplification should not remove mocked Massive regression coverage. Mocking the LLM alone does not make prices deterministic: use a fixed-price fixture or seeded controllable simulator, with isolated databases/volumes. Assert financial invariants rather than exact cash changes against moving prices.

Prioritize integration checks for stale/missing quotes, held-ticker removal, request replay, concurrent trades, partial chat failures, restart persistence, empty SSE snapshots, and operation without keys. Retain browser coverage for reconnection and both successful and rejected chat actions. These are proposed checks, not tests run during this review.

Recommended build order:

1. Consolidate the specification and settle payloads and execution rules.
2. Build application lifespan, database initialization, and the shared transactional trade service.
3. Integrate subscription management, quote validity, REST endpoints, and SSE.
4. Add mock chat, then real inference and failure handling.
5. Build the frontend against agreed contracts, then Docker/scripts and end-to-end verification.

Prioritize a complete buy/sell/chat workflow with correct accounting and recovery before expanding deployment options or chart complexity.
