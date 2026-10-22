# Review of changes since HEAD

Reviewed all changes relative to HEAD: the tracked diff in `planning/PLAN.md` and all six untracked files, including this existing feedback file, the two review-agent definitions, the doc-review command, and both review documents. There are no staged changes or application-code changes. Checked recommendations against the existing market-data implementation, backend dependency configuration, and main plan. Findings below concern the changed documents; existing runtime issues are included only where a new recommendation would preserve or introduce them.

## Findings

### [P1] Reject orders whose rounded notional is zero

**Location:** `planning/REVIEW-claude.md:73`; also `planning/PLAN.md:471`.

The proposed positive quantity with four decimal places and cent-rounded notional still permits free holdings. At a $10 quote, buying 0.0001 shares costs $0.001, which rounds to $0.00. Repeating the order accumulates shares without debiting cash, and selling the combined position can produce cash. Rounding the cash balance alone has the same problem.

Require a minimum executable notional and reject orders that round to zero. Define one rounding rule used consistently for balance checks, cash changes, and recorded fills. For example, ten such buys create 0.001 shares for zero cash; selling them together at the unchanged $10 quote returns $0.01. `planning/REVIEW.md` already identifies this problem; reconcile the two reviews before adopting the proposed precision rules.

### [P2] Restore simulator quotes from market state, not trade history

**Location:** `planning/REVIEW-claude.md:11`.

Seeding held tickers from their last trade price does not preserve simulator continuity. If a stock was bought at $100 and rises to $150 without another trade, restarting resets it to $100 and erases its unrealized gain. A partial sale also changes the restart baseline even though it should not determine the market price. The recommendation therefore retains the restart-driven valuation jumps it aims to fix.

Persist and restore the latest simulator quotes independently of trades, with a documented checkpoint policy, or explicitly define a restart as a new market session. This also resolves the conflicting advice in `planning/REVIEW.md`.

### [P2] Require a letter in validated ticker symbols

**Location:** `planning/PLAN.md:470`.

The new validation rule `^[A-Z.]{1,6}$` accepts `.` and `...`. The simulator assigns unknown strings a random price, so these invalid symbols become tradable assets rather than failing at the boundary. Uppercasing does not address this.

Use a format requiring letters with an optional supported class suffix, normalize whitespace and case, and apply the same validator to manual requests and LLM actions. If the intention is to reject invented companies as well, syntax validation alone cannot provide that guarantee; specify symbol lookup or an allowed universe.

### [P2] Fold accepted decisions into the main specification

**Location:** `planning/PLAN.md:474`, `planning/PLAN.md:503–505`.

The appended rules introduce competing implementation instructions without declaring their precedence. For example, A6 selects a named volume while section 4 still describes the repository database directory as the runtime mount point; D2 drops Compose despite its inclusion in the architecture and testing sections; D4 removes user identifiers that section 7 explicitly requires. `CLAUDE.md` imports this entire document as the shared contract, so implementers can follow different instructions and produce incompatible persistence or test setups.

Mark proposals as pending until accepted. Move accepted decisions into the relevant architecture, schema, deployment, and testing sections, then retain only a short decision log. Both new review documents recognize this conflict, but the changed plan itself still leaves it unresolved.

## Validation

This was a documentation and instruction review. Confirmed finding locations and inspected the simulator's seeding/removal behavior, cache, Massive client, dependency configuration, ignore rules, and `CLAUDE.md`'s plan import. No runtime tests were run because no executable application code changed. External provider entitlements and product/version claims were not independently verified. No additional actionable findings were identified in the review-agent definitions, doc-review command, or `planning/REVIEW.md`.
