# Usage

This page explains how to run the tool and how to read each part of the display.
For the full flag reference and the maths behind the recommendation, see
[configuration.md](configuration.md).

## Running

```bash
# Live full-screen viewer (default when stdout is a terminal)
python3 -m rbn_tracker --mycall MM1E

# Classic scrolling line report (one block per window)
python3 -m rbn_tracker --mycall MM1E --no-tui

# Offline, against the bundled synthetic feed
python3 -m rbn_tracker --replay samples/sample_feed.txt --ascii
```

The viewer is used automatically when standard output is an interactive
terminal. It falls back to the line report when output is piped/redirected, when
`--no-tui` is given, or with `--once` / `--replay`. Force the viewer with
`--tui`.

### Interactive keys

| Key | Action |
|-----|--------|
| `q` | Quit |
| `p` | Pause / resume the refresh (freezes the data; the layout still adapts on terminal resize) |

`Ctrl-C` quits cleanly from either mode and flushes pending CSV writes.

## How time windows work

Spots are bucketed into fixed **windows** (`--window`, default 60 s). Most of
the display is computed over an **averaging window** (`--avg-window`, default
15 min) so the numbers don't lurch on a single noisy minute. Trends are reported
over several horizons (current interval, 10 / 30 / 60 min). Up to an hour of
window history is retained to feed the longest horizon.

So: counts you see are **totals over the last 15 minutes** (by default), while
the arrows tell you the **direction** over each horizon.

## Reading the display

### Header bar

UTC clock, uptime, connection state (`LIVE` / `CONNECTING` / `REPLAY`), the
averaging window in use, spot counts (total and UK/IE) over that window, and the
tracked call. Shows `PAUSED` when paused.

### Band × Continent

Rows are active HF contest bands; columns are continents `NA SA EU AF AS OC`.
Each cell shows `spots(distinct-spotters)` — how many times UK/IE stations were
heard in that continent, and by how many distinct skimmers — totalled over the
averaging window. The right-hand column is the **current-interval** trend arrow
for the band. A `·`/`.` means no spots into that continent.

A band stays visible while it fades through quiet windows (so you can see it
die), and drops off only after a full hour of silence.

### Band Trends

For each band: a sparkline of recent distinct-spotter counts, then the trend at
four horizons — `now`, `10min`, `30min`, `60min`. Trend labels:

| Label | Meaning |
|-------|---------|
| `RISING` | activity increasing |
| `STEADY` | roughly flat |
| `FADING` | activity decreasing |
| `NEW` | essentially nothing before, meaningful activity now |
| `GONE` | had activity, now essentially none |

Use the longer horizons to tell a one-window blip from a genuine, sustained
opening.

### Recommendation

Bands ranked for working DX (non-EU), by **reach fraction** rather than raw
counts — see [configuration.md](configuration.md#reach-not-raw-counts). You get:

- a **TOP DX BAND** with its best continent and reach;
- the best band into each open DX continent, showing reach% (of the active UK
  population), spot count, median SNR, the skimmer-coverage estimate (`cov~N`),
  and the trend;
- `closed` where no UK/IE spots were heard into a continent.

### Your Station

Tracks `--mycall`. The **RUN** block shows:

- the band(s) you're currently **running CQ** on and your run frequency
  (e.g. `CQ on 20m @ 14026.0`);
- **band changes** inferred when one band goes quiet as another lights up
  (`band change: 40m → 15m`);
- bands you've **gone quiet** on (`no CQ for ~3m — gone S&P or off this band`);
- category-specific checks (see below).

Below that, per band you were spotted on: distinct spotters, the continents
reaching you, your best/median SNR, and reported CW speed. If you haven't been
spotted, it says so. If you're running a band other than the recommended one, it
prints a **QSY** suggestion.

If you weren't spotted at all in the window, that's stated plainly rather than
left blank — usually it means you're doing S&P (skimmers only spot CQ callers),
or the band is dead where you are.

### Opponents *(optional, off by default)*

The ±N stations around you in your category, with QSO / mult / score and the
delta versus you, plus each rival's current run frequency from RBN (or
`(no CQ)`). Enable and configure it via the `--opponents*` flags — see
[configuration.md](configuration.md#opponents).

## Contest categories

`--category` tunes the run/band-change logic to your entry class, by number of
simultaneously transmitted "run" signals:

| `--category` | Class | Behaviour |
|--------------|-------|-----------|
| `single` (default) | Single-Op / Multi-Single (1 TX) | Expects one run band; warns if two appear at once; suggests a QSY when a better DX band is open |
| `m2` | Multi-Two (2 TX) | Shows `transmitters in use N/2`; if a transmitter is idle while a DX band is open, suggests putting a radio there; notes the CQ WW 8 band-changes/hour/TX limit |
| `mm` | Multi-Multi (one signal per band) | Flags open DX bands you aren't running |

## Logging to CSV

`--csv FILE` appends one row per (band × continent) per window, including reach%,
active-UK count, coverage and the four trend labels. The file is flushed after
every window and gains a header row when created. Column details are in
[configuration.md](configuration.md#csv-output).

## Common workflows

- **Pick a run band at the start of a session:** launch live, glance at the
  Recommendation panel's TOP DX BAND and the per-continent reach, and start
  there.
- **Decide whether to QSY:** watch the trend arrows on your current band versus
  the recommendation; the Your Station panel will surface a QSY hint when the
  data favours a move.
- **Sanity-check you're getting out:** keep an eye on the Your Station panel —
  distinct spotters per band and the continents reaching you.
- **Review afterwards:** run with `--csv` and analyse the per-window data later.
- **Demo / develop offline:** use `--replay samples/sample_feed.txt`.
