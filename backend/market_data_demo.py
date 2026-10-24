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

# Vertical space the price panel needs beyond one line per ticker:
# panel border (2) + table top border, header, separator, bottom border (4).
# When space is short Rich drops the table's bottom border before any row,
# so the rows themselves need one line less.
TABLE_CHROME_LINES = 6
TABLE_MIN_CHROME_LINES = 5

# Horizontal space the price panel needs besides the sparkline: data column
# widths (48) + their padding (12) + sparkline padding (2) + table borders (8)
# + panel border and padding (4). The sparkline gets whatever is left.
TABLE_FIXED_COLUMNS = 74
SPARKLINE_MIN_WIDTH = 4  # Narrower than this, the column is dropped
SPARKLINE_MAX_WIDTH = 40  # Matches the history kept per ticker
EVENT_LOG_MAX_LINES = 10
EVENT_LOG_MIN_LINES = 5  # Below this the log shows too little to be worth it


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
    spark_width: int,
) -> Table:
    """Build the price table. Data columns keep their full width; the
    sparkline shows the newest `spark_width` points, or is dropped if < min."""
    show_spark = spark_width >= SPARKLINE_MIN_WIDTH
    table = Table(
        title=None,
        expand=True,
        border_style="bright_black",
        header_style="bold bright_white",
        pad_edge=True,
        padding=(0, 1),
    )
    for name, width, justify in (
        ("Ticker", 8, "left"),
        ("Price", 10, "right"),
        ("Tick", 9, "right"),
        ("Tick %", 8, "right"),
        ("Session %", 10, "right"),
        ("", 3, "left"),  # arrow
    ):
        # min_width stops Rich from squeezing data columns to make room
        table.add_column(name, justify=justify, width=width, min_width=width, no_wrap=True)
    table.columns[0].style = "bold bright_white"
    if show_spark:
        table.add_column("Sparkline", width=spark_width, no_wrap=True, overflow="crop")

    for ticker in tickers:
        update = cache.get(ticker)
        if update is None:
            table.add_row(ticker, "---", "---", "---", "---", "", *([""] if show_spark else []))
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

        # Change since the cache's session-start price (what the watchlist shows)
        session_pct = update.session_change_percent
        s_color = "green" if session_pct > 0 else "red" if session_pct < 0 else "bright_black"
        session_str = f"[{s_color}]{session_pct:+.2f}%[/]"

        cells = [ticker, price_str, change_str, pct_str, session_str, arrow]
        if show_spark:
            # Newest points that fit the column
            vals = list(history.get(ticker, []))[-spark_width:]
            cells.append(f"[bright_cyan]{sparkline(vals)}[/]" if len(vals) > 1 else "")
        table.add_row(*cells)

    return table


def build_event_log(events: deque, height: int) -> Panel:
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
        height=height,
    )


def build_dashboard(
    cache: PriceCache,
    tickers: list[str],
    history: dict[str, deque],
    events: deque,
    start_time: float,
    duration: float,
    height: int,
    width: int,
) -> Layout:
    """Build the full dashboard layout for a `width` x `height` terminal.

    The price table gets space first; the event log only takes what is left,
    and the header collapses to one line when space is tight. If the table
    still can't fit, the header says how many tickers are hidden.
    """
    elapsed = time.time() - start_time
    remaining = max(0, duration - elapsed)

    table_lines = len(tickers) + TABLE_CHROME_LINES
    header_lines = 3 if height >= table_lines + 3 else 1
    spare = height - header_lines - table_lines
    footer_lines = min(EVENT_LOG_MAX_LINES, spare) if spare >= EVENT_LOG_MIN_LINES else 0
    shown = max(0, min(len(tickers), height - header_lines - TABLE_MIN_CHROME_LINES))

    sections = [Layout(name="header", size=header_lines), Layout(name="body")]
    if footer_lines:
        sections.append(Layout(name="footer", size=footer_lines))
    layout = Layout()
    layout.split_column(*sections)

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
        no_wrap=True,  # Truncate rather than wrap: a wrapped header steals table rows
        overflow="ellipsis",
    )
    if header_lines == 3:
        layout["header"].update(Panel(header_text, border_style="bright_yellow"))
    else:
        layout["header"].update(header_text)

    # Body: price table
    layout["body"].update(
        Panel(
            build_table(
                cache,
                tickers,
                history,
                min(SPARKLINE_MAX_WIDTH, width - TABLE_FIXED_COLUMNS),
            ),
            title=(
                "[bold bright_white]Live Prices[/]"
                if shown == len(tickers)
                # In the title, not the header: the header line can be cut off
                # on the right, and this warning must stay visible
                else f"[bold red]Showing {shown} of {len(tickers)}: enlarge the terminal[/]"
            ),
            border_style="bright_black",
        )
    )

    # Footer: event log, only if there is room left after the table
    if footer_lines:
        layout["footer"].update(build_event_log(events, footer_lines))

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

    # Recent event log
    events: deque = deque(maxlen=12)

    await source.start(tickers)
    start_time = time.time()

    # Seed initial history points
    for ticker in tickers:
        update = cache.get(ticker)
        if update:
            history[ticker].append(update.price)

    console = Console()

    def dashboard() -> Layout:
        # Re-read the size every frame so resizing the window adapts the layout
        width, height = console.size
        return build_dashboard(cache, tickers, history, events, start_time, duration, height, width)

    try:
        with Live(dashboard(), console=console, refresh_per_second=4, screen=True) as live:
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
