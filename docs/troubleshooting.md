# Troubleshooting

Run with `-v` / `--verbose` for debug logging on stderr; it usually makes the
cause obvious.

## Connection

**It says `connecting…` then nothing / times out.**
The live feed is raw TCP to `telnet.reversebeacon.net:7000`. Many corporate,
guest and cloud networks allow only standard web ports (80/443) and silently
drop the rest. Test reachability:

```bash
python3 -c "import socket; socket.create_connection(('telnet.reversebeacon.net',7000),10); print('ok')"
```

If that hangs or errors, the port is blocked — run on a network that permits it,
or use `--replay samples/sample_feed.txt` to work offline. The client retries
with exponential backoff and reconnects automatically if the socket drops.

**Login prompt never appears.**
The client waits up to ~10 s for a recognisable prompt, then sends the callsign
anyway, so a non-standard banner is handled. If you see repeated reconnects,
it's almost certainly the port-blocking case above.

## Display

**Boxes show as `+`, `-`, `|` and arrows as `^ v -`.**
That's the ASCII fallback. It's automatic when the terminal encoding isn't UTF-8
and forced by `--ascii`. To get the Unicode look, ensure a UTF-8 locale
(e.g. `LANG=en_GB.UTF-8`) and don't pass `--ascii`.

**Box borders don't line up — the bottom border runs past the sides.**
Your terminal is drawing "ambiguous-width" characters (box-drawing glyphs,
arrows, sparkline blocks) as *two* columns instead of one. The viewer detects
this automatically and adjusts the layout, but detection can fail on some
terminals/multiplexers. Force it with `RBN_AMBIGUOUS_WIDTH=wide` (or
`=narrow` to force single-width). Many terminals also have a setting to turn
this off — e.g. iTerm2: *Profiles → Text → "Treat ambiguous-width characters as
double width"*; macOS Terminal: *Profiles → Advanced → "East Asian ambiguous
characters are wide"*. `--ascii` sidesteps it entirely (all width-1 glyphs).

**Layout looks cramped or columns are clipped.**
Panels size to the terminal width (clamped ~44–120 columns). Widen the window;
content is clipped rather than wrapped so borders stay aligned. Very narrow
terminals drop the right-most matrix columns first.

**Nothing happens for the first minute.**
The first window needs up to `--window` seconds (default 60) of spots before
there's anything to show. Lower `--window` for a faster first paint, or use
`--replay` which advances a simulated clock immediately.

**The viewer didn't open — I got scrolling text.**
The viewer only starts when stdout is an interactive terminal. If you piped or
redirected output, or used `--once` / `--replay`, you get the line report by
design. Force the viewer with `--tui`.

## Your Station panel

**`MM1E not spotted in the last 15min`.**
RBN skimmers only spot stations **calling CQ**. If you're doing S&P you won't be
spotted even though you're on the air. Otherwise the band may be dead toward the
skimmers, or you genuinely aren't being heard. Confirm you're tracking the right
call with `--mycall`.

**Wrong band shown as my run band.**
Run detection is heuristic, inferred from where your CQ spots appear on a 60 s
grid. A brief excursion or a gap in skimmer coverage can mislead it; it
self-corrects as fresh spots arrive.

## Opponents

**`contestonlinescore.com unavailable: got an HTML page, not a JSON feed`.**
`--score-url` is pointing at the human scoreboard page, not a data endpoint.
The `auto` source needs a JSON feed (and, for contestonlinescore.com, an API
key via `--score-api-key` / `COS_API_KEY`). This part is incomplete — see
[roadmap.md](roadmap.md#known-limitations). Use `--opponents manual` with a
local file in the meantime.

**`auto` shows `waiting for scores…` forever.**
The endpoint is unreachable or returning an unexpected shape. Run with `-v` to
see the fetch error; fall back to `manual`.

**Manual leaderboard doesn't rank around me.**
Include your own call (matching `--mycall`) with a score in the file; otherwise
the tool shows the top of the list because it can't find your position.

## General

**`SyntaxError` / it won't start on older Python.**
Python 3.10+ is required. Check `python3 --version`.

**A malformed spot line — does it crash?**
No. Unparseable lines are counted and skipped (visible at `-v`). If you ever see
a traceback from the feed reader, that's a bug worth reporting with the line.
