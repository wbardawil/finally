"""FinAlly Market Data Simulator Demo.

Run with:  uv run market_data_demo.py [--duration 60] [--tickers AAPL,TSLA,...]

Displays a live-updating terminal dashboard of simulated stock prices
using the GBM simulator and Rich library. Rich is a dev-only dependency,
so this needs the default `uv sync` (not `--no-dev`).
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections import deque

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.market.cache import PriceCache
from app.market.seed_prices import SEED_PRICES
from app.market.simulator import SimulatorDataSource

# Sparkline characters, low to high
SPARK_CHARS = "▁▂▃▄▅▆▇█"

# Ordered ticker list matching the default watchlist
DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

DEFAULT_DURATION = 60  # seconds


def sparkline(values: list[float]) -> str:
    """Render a sequence of values as a unicode sparkline."""
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    spread = hi - lo
    if spread == 0:
        return SPARK_CHARS[3] * len(values)
    n = len(SPARK_CHARS) - 1
    return "".join(SPARK_CHARS[int((v - lo) / spread * n)] for v in values)


def format_price(price: float) -> str:
    """Format a price with comma separator."""
    if price >= 1000:
        return f"{price:,.2f}"
    return f"{price:.2f}"


def build_table(
    cache: PriceCache,
    tickers: list[str],
    history: dict[str, deque],
    session_start: dict[str, float],
) -> Table:
    """Build the price table."""
    table = Table(
        title=None,
        expand=True,
        border_style="bright_black",
        header_style="bold bright_white",
        pad_edge=True,
        padding=(0, 1),
    )
    table.add_column("Ticker", style="bold bright_white", width=8)
    table.add_column("Price", justify="right", width=10)
    table.add_column("Tick", justify="right", width=9)
    table.add_column("Tick %", justify="right", width=8)
    table.add_column("Session %", justify="right", width=10)
    table.add_column("", width=3)  # arrow
    table.add_column("Sparkline", width=42, no_wrap=True)

    for ticker in tickers:
        update = cache.get(ticker)
        if update is None:
            table.add_row(ticker, "---", "---", "---", "---", "", "")
            continue

        # Direction styling
        if update.direction == "up":
            color = "green"
            arrow = "[bold green]\u25b2[/]"
        elif update.direction == "down":
            color = "red"
            arrow = "[bold red]\u25bc[/]"
        else:
            color = "bright_black"
            arrow = "[bright_black]\u2500[/]"

        price_str = f"[{color}]${format_price(update.price)}[/]"
        change_str = f"[{color}]{update.change:+.2f}[/]"
        pct_str = f"[{color}]{update.change_percent:+.2f}%[/]"

        # Change since this demo's first observed price (what PLAN.md calls
        # "session-start price"; computed here because the cache lacks it)
        start = session_start.get(ticker)
        session_pct = (update.price - start) / start * 100 if start else 0.0
        s_color = "green" if session_pct > 0 else "red" if session_pct < 0 else "bright_black"
        session_str = f"[{s_color}]{session_pct:+.2f}%[/]"

        # Sparkline from history
        vals = list(history.get(ticker, []))
        spark_str = f"[bright_cyan]{sparkline(vals)}[/]" if len(vals) > 1 else ""

        table.add_row(ticker, price_str, change_str, pct_str, session_str, arrow, spark_str)

    return table


def build_event_log(events: deque) -> Panel:
    """Build the event log panel."""
    text = Text()
    for evt in events:
        text.append(evt)
        text.append("\n")
    if not events:
        text.append("Watching for notable moves (>1% change)...", style="bright_black italic")
    return Panel(
        text,
        title="[bold bright_yellow]Recent Events[/]",
        border_style="bright_black",
        height=8,
    )


def build_dashboard(
    cache: PriceCache,
    tickers: list[str],
    history: dict[str, deque],
    session_start: dict[str, float],
    events: deque,
    start_time: float,
    duration: float,
) -> Layout:
    """Build the full dashboard layout."""
    elapsed = time.time() - start_time
    remaining = max(0, duration - elapsed)

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=10),
    )

    # Header
    header_text = Text.assemble(
        ("  FinAlly ", "bold bright_yellow"),
        ("Market Data Simulator", "bold bright_white"),
        ("  |  ", "bright_black"),
        (f"{elapsed:5.1f}s elapsed", "bright_cyan"),
        ("  |  ", "bright_black"),
        (f"{remaining:4.1f}s remaining", "bright_cyan"),
        ("  |  ", "bright_black"),
        (f"{len(cache)} tickers", "bright_white"),
        ("  |  ", "bright_black"),
        ("Ctrl+C to exit", "bright_black italic"),
    )
    layout["header"].update(Panel(header_text, border_style="bright_yellow"))

    # Body: price table
    layout["body"].update(
        Panel(
            build_table(cache, tickers, history, session_start),
            title="[bold bright_white]Live Prices[/]",
            border_style="bright_black",
        )
    )

    # Footer: event log
    layout["footer"].update(build_event_log(events))

    return layout


def print_summary(cache: PriceCache, tickers: list[str]) -> None:
    """Print final summary comparing to seed prices."""
    console = Console()
    console.print()
    console.print("[bold bright_yellow]  FinAlly[/] [bold]Session Summary[/]")
    console.print()

    table = Table(border_style="bright_black", header_style="bold bright_white", expand=False)
    table.add_column("Ticker", style="bold bright_white", width=8)
    table.add_column("Seed Price", justify="right", width=12)
    table.add_column("Final Price", justify="right", width=12)
    table.add_column("Session Change", justify="right", width=14)

    for ticker in tickers:
        seed = SEED_PRICES.get(ticker, 0)
        update = cache.get(ticker)
        if update is None:
            continue
        final = update.price
        session_change = ((final - seed) / seed) * 100 if seed else 0

        if session_change > 0:
            color = "green"
        elif session_change < 0:
            color = "red"
        else:
            color = "bright_black"

        table.add_row(
            ticker,
            f"${format_price(seed)}",
            f"[{color}]${format_price(final)}[/]",
            f"[{color}]{session_change:+.2f}%[/]",
        )

    console.print(table)
    console.print()


async def run(tickers: list[str], duration: float) -> None:
    """Main demo loop."""
    cache = PriceCache()
    source = SimulatorDataSource(price_cache=cache, update_interval=0.5)

    # Per-ticker price history for sparklines
    history: dict[str, deque] = {t: deque(maxlen=40) for t in tickers}

    # First price seen per ticker, for the Session % column
    session_start: dict[str, float] = {}

    # Recent event log
    events: deque = deque(maxlen=12)

    await source.start(tickers)
    start_time = time.time()

    # Seed initial history points
    for ticker in tickers:
        update = cache.get(ticker)
        if update:
            history[ticker].append(update.price)
            session_start[ticker] = update.price

    def dashboard() -> Layout:
        return build_dashboard(cache, tickers, history, session_start, events, start_time, duration)

    try:
        with Live(dashboard(), refresh_per_second=4, screen=True) as live:
            last_version = cache.version
            while time.time() - start_time < duration:
                await asyncio.sleep(0.25)

                # Check for updates
                if cache.version == last_version:
                    continue
                last_version = cache.version

                # Record history & detect events
                for ticker in tickers:
                    update = cache.get(ticker)
                    if update is None:
                        continue
                    history[ticker].append(update.price)
                    session_start.setdefault(ticker, update.price)

                    # Log notable moves
                    if abs(update.change_percent) > 1.0:
                        direction = "\u25b2" if update.direction == "up" else "\u25bc"
                        color = "green" if update.direction == "up" else "red"
                        timestamp = time.strftime("%H:%M:%S")
                        events.appendleft(
                            f"[bright_black]{timestamp}[/]  "
                            f"[bold {color}]{direction} {ticker}[/]  "
                            f"[{color}]{update.change_percent:+.2f}%[/]  "
                            f"${format_price(update.price)}"
                        )

                live.update(dashboard())

    except asyncio.CancelledError:
        # asyncio.run() turns Ctrl+C into cancellation of this task, not a
        # KeyboardInterrupt here; fall through so the summary still prints
        pass
    finally:
        await source.stop()

    print_summary(cache, tickers)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FinAlly market data simulator demo")
    parser.add_argument(
        "--duration", type=float, default=DEFAULT_DURATION, help="seconds to run (default 60)"
    )
    parser.add_argument(
        "--tickers",
        default=",".join(DEFAULT_TICKERS),
        help="comma-separated tickers (default: the 10-ticker default watchlist)",
    )
    args = parser.parse_args()
    args.tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if not args.tickers:
        parser.error("--tickers needs at least one ticker")
    return args


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(run(args.tickers, args.duration))
    except KeyboardInterrupt:
        pass  # Raised by asyncio.run() after run() finished on Ctrl+C
