# PLAN.md Review

Scope: sections 1-12, the existing Section 13 (doc-review), and the built market module in `backend/app/market/`. `[code]` means checked against source. `[S13]` marks where Section 13 conflicts with the rest of the plan, missed something, or where I disagree with it.

---

## Blocking (decide before step 1)

**1. Prices reset on every restart, but positions persist. `[code]` `[S13 missed]`** (§6, §7)
On every boot the simulator re-seeds from `SEED_PRICES`, and unknown tickers get a fresh `random.uniform(50, 300)` (`simulator.py:151`, `simulator.py:219-228`). Positions and `avg_cost` survive in SQLite. So a restart moves P&L at random. A PYPL bought at $120 can come back at $280: free money, which the LLM can also find.
**Change:** at startup, seed each held ticker from its last trade price in `trades`. This needs a small interface addition, e.g. `start(tickers, seed_prices: dict[str, float] | None = None)`, with `GBMSimulator` using the override ahead of `SEED_PRICES`. Add one test for it.

**2. Section 13 is not folded into sections 1-12, so agents get two specs. `[S13]`** (§4, §6, §8, §11, §12)
`CLAUDE.md` loads PLAN.md as the contract. Right now it says both things:
- A1 vs §6 ("tickers known to the system… equivalent to the user's watchlist"). Under A1 the SSE feed also carries position-only tickers. The interface docstring has the same problem: `remove_ticker` "also removes the ticker from the PriceCache" (`interface.py:52`).
- A6 vs §4 ("`db/` at the top level is the runtime volume mount point") and §11 ("The `db/` directory in the project root maps to `/app/db`").
- D2/D9 vs §4 (lists `docker-compose.yml` and `test/docker-compose.test.yml`) and §12 (Playwright container).
- D6 vs §8 (`GET /api/portfolio` returns "total value, unrealized P&L").

**Change:** write the accepted rules into the sections they modify. Then cut Section 13 down to a short decisions log, or delete it.

**3. "Lazy init on first request" can't work with A1. `[code]`** (§4 Key Boundaries, §7)
`source.start(tickers)` must be called exactly once with the starting set (`interface.py:26-31`). Under A1 that set is watchlist ∪ positions, which comes from the DB. So the DB has to exist before the first request.
**Change:** use a FastAPI `lifespan` that does init/seed DB → build `PriceCache` → `source.start(watchlist ∪ held)` (seeded per #1) → start the snapshot task. Remove "lazily… on first request" in both places.

**4. Must run as a single process. `[S13 missed]`** (§3, §11)
The price cache, simulator and snapshot task all live in memory. `uvicorn --workers 2` would run two separate markets with different prices, and trades would fill against whichever one served the request.
**Change:** §11 CMD becomes `uvicorn app.main:app --host 0.0.0.0 --port 8000` (one worker, stated explicitly). This also makes #10's in-process lock enough.

**5. Blocking calls will freeze the price stream. `[code]` `[S13 missed]`** (§9, §6)
The simulator loop and the SSE generator share the event loop (`simulator.py:260-270`, `stream.py:68-85`). The cerebras skill's snippet uses the synchronous `litellm.completion` (`.claude/skills/cerebras/SKILL.md`). Called inside an `async def` endpoint, it stops all prices for the length of the LLM call. Synchronous `sqlite3` inside `async def` does the same, on a smaller scale.
**Change:** call `litellm.acompletion` with the same arguments (`response_format`, `reasoning_effort`, `extra_body`). Write DB-only routes as plain `def` so they run in the threadpool, and open one SQLite connection per request.

**6. Trading a ticker that has no feed: undefined, and LLM action order is unspecified. `[code]` `[S13 missed]`** (§8, §9, B8)
The trade bar and the LLM can name any ticker. A ticker outside the feed has `cache.get_price() is None`, so the trade fails. If the LLM sends `watchlist_changes: [add PYPL]` plus `trades: [buy PYPL]` in one response, success depends on execution order. In Massive mode, `add_ticker` doesn't poll (`massive_client.py:66-70`), so a new ticker has no price for up to 15s.
**Change:** (a) run `watchlist_changes` before `trades`. (b) A buy of a ticker not on the watchlist adds it to the watchlist first; the simulator seeds the price immediately (`simulator.py:242-248`). (c) If there is still no price (Massive), return `400 {"error": "No price yet for PYPL, retry shortly"}`.

**7. Response contracts are only half defined. `[code]` `[S13 partial]`** (§6, §8; extends A5)
A5 covers trade errors and `/api/chat`. Three contracts are still missing:
- **SSE:** §6 says "each event contains ticker, price…". The code actually sends **one event per tick: an object keyed by ticker, holding all tickers**. Each value is `{ticker, price, previous_price, timestamp (unix seconds, float), change, change_percent, direction}` (`stream.py:80-83`, `models.py:39-49`). Events go out only when the cache version changes, every 15s on Massive. Put this exact shape in §6.
- **`GET /api/portfolio`, `GET /api/portfolio/history`, `GET /api/watchlist`:** list their JSON fields.
- **Errors:** one shape for all of them, `{"error": str}` with 400 (validation) or 404 (unknown ticker on DELETE).

---

## Should-fix

**8. `create_stream_router` registers routes on a module-level router. `[code]`** (§12 API route tests)
`router` is created at import time (`stream.py:17`), and every call to the factory adds another `/prices` route to it (`stream.py:26`). A test fixture that builds a fresh app and cache per test therefore gets the **first** cache's handler, because the first route matches first.
**Change:** move `router = APIRouter(...)` inside `create_stream_router`. It's a one-line move; add a test that builds two apps.

**9. A1 is incomplete. `[S13]`** (§6, §8)
A1 covers removing a ticker from the watchlist. It leaves out (a) selling a position to zero on a ticker that isn't on the watchlist, which should drop it from the feed, and (b) building the starting set (#3).
**Change:** one helper, `sync_feed(conn, source)`. It computes watchlist ∪ held, then adds and removes the difference. Call it after every watchlist change and every trade.

**10. B9 transaction: there's a simpler option. `[S13 disagree, mild]`** (§8)
`BEGIN IMMEDIATE` works, but Python's `sqlite3` transaction handling is easy to get wrong. With a single process (#4), a module-level `threading.Lock` around `execute_trade()` is simpler, and manual and LLM trades go through the same path.
**Change:** use the lock, and do the check and update in one `with conn:` block.

**11. D6 ("keep `GET /api/portfolio` raw") saves nothing. `[S13 disagree]`** (§8, §9)
§9 step 1 already requires the backend to compute positions with P&L and the total value for the LLM context. So that code gets written anyway.
**Change:** a single backend `portfolio_view(conn, cache)` that serves both `GET /api/portfolio` and the LLM context. The frontend still recomputes live values on each SSE tick (B15).

**12. D4 (drop `user_id`) works against a stated goal; the schema is inconsistent anyway. `[S13 disagree]`** (§7)
The cost of the column is one constant, `USER_ID = "default"`, in every query. Dropping it removes a requirement §7 states on purpose. Separately, §7 says "All tables include a `user_id` column", but `users_profile` uses `id`.
**Change:** keep `user_id` and filter with the constant. Reword §7 to "all tables except `users_profile` (keyed by `id`)".

**13. A2 regex is loose, and the code normalizes inconsistently. `[code]` `[S13]`** (§8)
`^[A-Z.]{1,6}$` accepts `.` and `...`. Massive uppercases in `add_ticker` (`massive_client.py:67`); the simulator doesn't (`simulator.py:242`).
**Change:** `^[A-Z]{1,5}(\.[A-Z]{1,2})?$`, applied once with `.strip().upper()` at the API boundary and in the LLM action executor. Keep the ticker list open, not a fixed whitelist. §9's own example uses PYPL, which isn't in `SEED_PRICES`.

**14. A3 and A4 offer options instead of decisions. `[S13]`** (§7, §10)
- A3: store `REAL`. Round `cash_balance` to cents after every trade, and round trade notional to cents. **Do not** round `avg_cost` to cents, because the error accumulates; keep 6 decimals. Require `quantity > 0` with at most 4 decimals.
- A4: compute it on the frontend as change from the first SSE price seen since page load. The column label is "Chg" with a tooltip saying "since session start". There's no backend change, and it resets with the sparklines, so the two stay consistent. (Massive snapshots carry `todays_change_perc`, but the client discards it, and plumbing it through isn't worth it.)

**15. Chat history should carry action outcomes. `[S13 missed]`** (§9, B13)
If a stored assistant message holds only `content`, the next turn's LLM doesn't know its earlier trade failed.
**Change:** when loading history, append a short summary of `actions` to each assistant message (e.g. `[executed: buy 10 AAPL @190.12; failed: sell 5 TSLA - insufficient shares]`).

**16. Structured output: "optional" fields can conflict with strict schemas. `[S13 missed]`** (§9)
Strict JSON-schema mode generally requires every property to be listed as required. Whether LiteLLM sends a Pydantic model as strict for this route is unverified, so treat this as likely, not certain.
**Change:** make `message`, `trades` and `watchlist_changes` all required, with the lists allowed to be empty. Use Pydantic enums for `side` (`buy`/`sell`) and `action` (`add`/`remove`), and `quantity: float > 0`.

**17. `LLM_MOCK` has no defined behavior, so E2E can't assert on it. `[S13 missed]`** (§9, §12)
**Change:** specify the mock in §9. For example: a message containing "buy" → `trades: [{AAPL, buy, 1}]`; "add" → `watchlist_changes: [{PYPL, add}]`; otherwise it echoes a fixed reply. D8's "just another implementation of `get_llm_response()`" stays right.

**18. E2E isn't repeatable against the named volume. `[S13 missed]`** (§12, D9)
"Fresh start: $10k shown" fails on the second run, because `finally-data` keeps earlier trades. The start script also passes `--env-file .env`, where `LLM_MOCK=false`.
**Change:** the E2E run uses its own container name and a throwaway volume, e.g. `docker run --rm -e LLM_MOCK=true -v finally-test:/app/db ...`, then `docker volume rm finally-test`. `-e` after `--env-file` overrides it.

**19. Frontend dev loop: rewrites don't work with `output: 'export'`. `[S13]`** (B20, §10)
**Change:** set `output: 'export'` only in production builds, and add the `/api/*` rewrite to `localhost:8000` only in dev. Check SSE through the dev proxy on day one: dev-server compression or buffering can break streaming (unverified). If it does, test through the container.

**20. C24's reasoning is wrong for this `pyproject.toml`. `[code]` `[S13]`** (§11)
Dev tools sit in `[project.optional-dependencies] dev` (`pyproject.toml:15-21`), not in `[dependency-groups]`. `--no-dev` only affects dependency groups. Extras are never installed unless you ask for them, so `rich` (`pyproject.toml:12`) is the only real leak.
**Change:** move `rich` into the existing optional `dev` extra (one line), and keep `uv run --extra dev` as in `backend/CLAUDE.md`. Don't put a second "dev" in `[dependency-groups]`.

**21. Paths and static mount aren't specified. `[S13 missed]`** (§4, §11)
- The DB path depends on the working directory: `backend/` locally, `/app` in the container. **Change:** a single `DB_PATH` env var, set to `/app/db/finally.db` in the Dockerfile, with the default pointing at the repo-root `db/finally.db`.
- **Change:** mount `StaticFiles(directory="static", html=True)` at `/` **after** all `/api` routers. Otherwise it shadows them.

**22. Massive free tier may not deliver what §6 claims. `[S13 missed]`** (§6, B18, D10)
Basic (free) data is end-of-day or 15-minute delayed. I couldn't confirm that the snapshot endpoint the client calls (`massive_client.py:125`) is on the free plan at all. **Change:** say "paid tier recommended; free tier unverified" until D10's smoke test runs with a real key.

**23. A missing `OPENROUTER_API_KEY` must not stop the app. `[S13 missed]`** (§5)
§5 calls the key "Required", but everything except chat works without it.
**Change:** the app starts. `/api/chat` returns `{message: "Chat unavailable: OPENROUTER_API_KEY not set", trades: [], watchlist_changes: []}`.

**24. The frontend must refetch after state changes. `[S13 missed]`** (§10, B15)
B15 computes the header total from SSE prices × positions, but positions only come from `GET /api/portfolio`.
**Change:** after a manual trade, and after any chat response with non-empty actions, refetch `/api/portfolio` and `/api/watchlist`.

---

## Nice-to-have

**25. P&L chart is empty for the first 30s.** (§7) Write one snapshot at startup. Skip a snapshot if any held ticker has no price; otherwise it records a fake dip.
**26. Re-adding a removed ticker resets it to the seed price. `[code]`** (`simulator.py:127-134`, `:151`) Under A1 this only affects tickers you don't hold. Accept it and note it in §6.
**27. B11 cheap mitigation.** The system prompt tells the LLM to phrase trades as "placing order…", not "done". Agree: no second LLM call.
**28. Heatmap details.** (§10) State whether cash is a tile (recommend no), the color scale (±5% vs avg cost saturates), and an empty state when there are no positions.
**29. §10 factual slip.** "Canvas-based… (Lightweight Charts or Recharts)": Recharts is SVG. D5 is right; adopt it and remove Recharts from §10. Use the current Lightweight Charts API (`chart.addSeries(LineSeries)`) and Tailwind v4's CSS-first `@theme` config.
**30. Trim frontend unit tests.** (§12) Keep three: the portfolio-math helper, the price-flash trigger, and chat rendering. D9 trimmed E2E; this list is still the long version.
**31. D2: one more reason.** The cloud-deploy stretch goal would put an unauthenticated app online that trades and spends the owner's OpenRouter credits. Agree: drop it.
**32. D3: pick Windows.** You're on Windows, so build `start_windows.ps1` / `stop_windows.ps1` first.
**33. Local `.env`.** Use `uv run --env-file ../.env uvicorn ...` locally instead of adding `python-dotenv`. It matches Docker's `--env-file`.
**34. §3 diagram** is missing the 30s snapshot task.

### Section 13 items I checked and agree with
A1 (citations correct: `simulator.py:254`, `massive_client.py:75`), A2 (`simulator.py:151` correct), A5, A6, B7, B8, B10, B12, B14, B16-B19, C21 (Node 20 EOL April 2026), C22, C23 (`.gitignore` has `.env` but no `db/*.db`; `db/` and `.env.example` don't exist), D1, D2, D3, D5, D7, D8, D9 (with #18), D10. Suggested build order: fine. Step 1 trade tests can use a hand-filled `PriceCache`, so no data source is needed.

---

**Next action today:** write the blocking decisions (#1-#7) and the accepted Section 13 rules into §4-§11, then start build step 1 with `backend/app/db/` plus the `lifespan` startup from #3.
