"""Command-line entry point: wires the feed, processor, reporting and CSV."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time

from .csvout import CsvWriter
from .feed import ReplayFeed, TelnetFeed
from .processing import SpotProcessor
from .report import RenderConfig, format_report
from .runstate import normalize_category
from .spots import SpotParseError, parse_spot


def _category(text: str) -> str:
    """argparse type: normalise a contest-category string (or error out)."""
    import argparse
    try:
        return normalize_category(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc

log = logging.getLogger("rbn")

DEFAULT_CALLSIGN = "M0TTT"
DEFAULT_MYCALL = "MM1E"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rbn-contest-tracker",
        description="Once-per-minute RBN propagation / band-recommendation "
                    "report for UK/IE CW activity, with trend tracking and a "
                    "dedicated section for your own station.",
    )
    p.add_argument("--callsign", default=DEFAULT_CALLSIGN,
                   help="callsign used to log in to the RBN feed "
                        f"(default {DEFAULT_CALLSIGN})")
    p.add_argument("--mycall", default=DEFAULT_MYCALL,
                   help=f"station to track in the 'me' section "
                        f"(default {DEFAULT_MYCALL})")
    p.add_argument("--window", type=int, default=60, metavar="SECONDS",
                   help="base sampling/commit window in seconds (default 60)")
    p.add_argument("--avg-window", type=float, default=15.0, metavar="MINUTES",
                   help="averaging window (minutes) for the band matrix, "
                        "recommendation and your-station sections (default 15)")
    p.add_argument("--category", type=_category, default="single",
                   metavar="CAT",
                   help="contest category for run/band-change tracking: "
                        "single (default), m2 (multi-two), mm (multi-multi)")
    p.add_argument("--history", type=int, default=5, metavar="N",
                   help="number of windows kept for trend analysis (default 5)")
    p.add_argument("--csv", metavar="FILE", help="append per-window stats to CSV")
    p.add_argument("--min-snr", type=int, default=None, metavar="DB",
                   help="ignore spots below this SNR (dB)")
    p.add_argument("--once", action="store_true",
                   help="emit a single window then exit (testing)")
    p.add_argument("--replay", metavar="FILE",
                   help="replay raw spot lines from FILE instead of connecting; "
                        "lines may be prefixed '@<offset_secs>\\t' to set "
                        "receive time, otherwise times auto-increment")
    p.add_argument("--ascii", action="store_true",
                   help="force ASCII sparklines/arrows (no Unicode)")
    p.add_argument("--tui", action="store_true",
                   help="force the full-screen interactive viewer")
    p.add_argument("--no-tui", action="store_true",
                   help="force the classic scrolling line report")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p


def _supports_unicode() -> bool:
    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "utf" in enc


class Reader:
    """Background thread: pulls lines from a feed, parses, feeds the processor."""

    def __init__(self, feed, processor: SpotProcessor, lock: threading.Lock,
                 state=None):
        self.feed = feed
        self.processor = processor
        self.lock = lock
        self.state = state  # optional TuiState to update live counters
        self.thread = threading.Thread(target=self._run, daemon=True)
        self._stop = False
        self.parsed = 0
        self.skipped = 0

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop = True
        self.feed.stop()

    def _run(self) -> None:
        for line in self.feed.lines():
            if self._stop:
                break
            try:
                spot = parse_spot(line, recv_time=time.time())
            except SpotParseError:
                self.skipped += 1
                if self.state is not None:
                    self.state.skipped = self.skipped
                log.debug("skip line: %r", line)
                continue
            except Exception as exc:  # never crash the reader on a bad line
                self.skipped += 1
                log.debug("error parsing %r: %s", line, exc)
                continue
            self.parsed += 1
            if self.state is not None:
                self.state.spots_seen = self.parsed
            with self.lock:
                self.processor.add(spot)


def run_tui_live(args, processor, cfg, csv_writer) -> int:
    """Live feed rendered in the full-screen curses viewer."""
    from .tui import TuiState, run_tui

    feed = TelnetFeed(args.callsign)
    lock = threading.Lock()
    state = TuiState(source="live", started_at=time.time())
    reader = Reader(feed, processor, lock, state=state)
    reader.start()
    log.info("starting interactive viewer (press q to quit)")

    def pre(st: TuiState) -> None:
        st.connected = getattr(feed, "connected", False)

    def on_commit(summary, history) -> None:
        if csv_writer:
            csv_writer.write_window(summary, history)

    try:
        run_tui(processor, cfg, state, lock, on_commit=on_commit, pre_render=pre)
    finally:
        reader.stop()
        if csv_writer:
            csv_writer.close()
    return 0


def run_live(args, processor, cfg, csv_writer) -> int:
    feed = TelnetFeed(args.callsign)
    lock = threading.Lock()
    reader = Reader(feed, processor, lock)

    stop_event = threading.Event()

    def _handle_sigint(signum, frame):
        log.info("interrupt received -- shutting down")
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_sigint)
    try:
        signal.signal(signal.SIGTERM, _handle_sigint)
    except (ValueError, AttributeError):
        pass

    reader.start()
    log.info("collecting spots; first report in ~%ds ...", args.window)

    next_tick = time.time() + args.window
    try:
        while not stop_event.is_set():
            now = time.time()
            if now >= next_tick:
                with lock:
                    summary = processor.roll(now)
                _emit(summary, processor, cfg, csv_writer)
                if args.once:
                    break
                next_tick += args.window
            stop_event.wait(timeout=0.5)
    finally:
        reader.stop()
        if csv_writer:
            csv_writer.close()
    return 0


def _parse_replay_line(raw: str, fallback_time: float) -> tuple[float, str]:
    if raw.startswith("@"):
        head, _, rest = raw.partition("\t")
        try:
            return float(head[1:]), rest
        except ValueError:
            return fallback_time, raw
    return fallback_time, raw


def run_replay(args, processor, cfg, csv_writer) -> int:
    """Deterministic replay: drive simulated time so windows roll naturally."""
    feed = ReplayFeed(args.replay)
    base = 0.0
    seq = 0.0
    window_end = None
    emitted = 0

    for raw in feed.lines():
        if not raw.strip():
            continue
        seq += 0.001  # default spacing if no explicit offset
        recv_time, line = _parse_replay_line(raw, base + seq)
        try:
            spot = parse_spot(line, recv_time=recv_time)
        except SpotParseError:
            log.debug("skip replay line: %r", line)
            continue
        except Exception as exc:
            log.debug("error parsing replay %r: %s", line, exc)
            continue

        if window_end is None:
            window_end = recv_time + args.window
        # Roll as many windows as the simulated clock has passed.
        while recv_time >= window_end:
            summary = processor.roll(window_end)
            _emit(summary, processor, cfg, csv_writer)
            emitted += 1
            window_end += args.window
            if args.once:
                break
        if args.once and emitted:
            break
        processor.add(spot)

    # Flush the final partial window.
    if not (args.once and emitted) and processor.pending():
        end = window_end if window_end is not None else args.window
        summary = processor.roll(end)
        _emit(summary, processor, cfg, csv_writer)

    if csv_writer:
        csv_writer.close()
    return 0


def _emit(summary, processor, cfg, csv_writer) -> None:
    history = list(processor.history)
    print(format_report(summary, history, cfg))
    print()
    sys.stdout.flush()
    if csv_writer:
        csv_writer.write_window(summary, history)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    processor = SpotProcessor(
        mycall=args.mycall, window_secs=args.window,
        history=args.history, min_snr=args.min_snr,
    )
    cfg = RenderConfig(
        mycall=args.mycall.strip().upper(),
        use_unicode=(not args.ascii) and _supports_unicode(),
        window_secs=args.window,
        avg_window_secs=int(round(args.avg_window * 60)),
        category_key=args.category,
    )
    csv_writer = CsvWriter(args.csv) if args.csv else None

    # The full-screen viewer is the default for an interactive live session.
    # It's disabled for --replay/--once and when stdout isn't a TTY (piped or
    # redirected), unless explicitly forced with --tui.
    interactive = sys.stdout.isatty() and not args.once and not args.replay
    use_tui = args.tui or (interactive and not args.no_tui)

    try:
        if args.replay:
            return run_replay(args, processor, cfg, csv_writer)
        if use_tui:
            try:
                return run_tui_live(args, processor, cfg, csv_writer)
            except Exception as exc:  # curses unavailable -> fall back gracefully
                log.warning("interactive viewer unavailable (%s); "
                            "falling back to line report", exc)
        return run_live(args, processor, cfg, csv_writer)
    except KeyboardInterrupt:
        if csv_writer:
            csv_writer.close()
        return 0


if __name__ == "__main__":
    sys.exit(main())
