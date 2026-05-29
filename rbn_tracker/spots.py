"""Parsing of Reverse Beacon Network / DX-cluster spot lines."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .bands import band_for
from .callsign import classify_uk
from .continents import continent_for

# Example line:
#   DX de DL8TG-#:     14036.0  G4ABC          CW    12 dB  28 wpm  CQ      1234Z
#
# Fields, left to right: spotter (the skimmer, before ':'), frequency in kHz,
# the spotted DX call, mode, SNR in dB, speed in wpm (CW), a comment/type, and
# the Zulu time. We keep the regex permissive: SNR may be negative, the wpm
# field may be absent (non-CW), and the comment is free text.
_SPOT_RE = re.compile(
    r"""^DX\s+de\s+
        (?P<spotter>[A-Z0-9/#\-]+?):?\s+      # spotter call (skimmer), maybe -# / SSID
        (?P<freq>\d{3,7}(?:\.\d+)?)\s+         # frequency in kHz
        (?P<dx>[A-Z0-9/]+)\s+                  # spotted DX call
        (?P<mode>[A-Z0-9]+)\s+                 # mode (CW, RTTY, ...)
        (?P<snr>[-+]?\d+)\s*dB                  # SNR in dB
        (?:\s+(?P<speed>\d+)\s*wpm)?           # optional speed in wpm
        (?:\s+(?P<comment>.*?))?               # optional free-text comment/type
        \s+(?P<time>\d{3,4})Z\s*$              # Zulu time, e.g. 1234Z
    """,
    re.VERBOSE | re.IGNORECASE,
)


@dataclass
class Spot:
    """A single parsed RBN spot, enriched with band / continent / cohort flags."""

    spotter: str  # the skimmer that heard the DX
    spotted: str  # the DX station that was heard
    freq_khz: float
    mode: str
    snr_db: int
    speed_wpm: int | None
    zulu: str  # e.g. "1234"
    comment: str = ""
    raw: str = ""
    recv_time: float = 0.0  # wall-clock receive time (epoch seconds)

    # Derived (filled in __post_init__)
    band: str = field(default="?", init=False)
    spotter_continent: str = field(default="?", init=False)
    is_uk: bool = field(default=False, init=False)
    uk_region: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.band = band_for(self.freq_khz)
        self.spotter_continent = continent_for(self.spotter)
        ok, region, _parts = classify_uk(self.spotted)
        self.is_uk = ok
        self.uk_region = region


class SpotParseError(ValueError):
    """Raised when a line cannot be parsed as a spot."""


def parse_spot(line: str, recv_time: float = 0.0) -> Spot:
    """Parse one feed line into a :class:`Spot`.

    Raises :class:`SpotParseError` on anything that is not a recognisable spot
    (status lines, banners, blanks, garbage) so callers can log-and-skip.
    """
    if not line or "DX de" not in line:
        raise SpotParseError("not a spot line")
    m = _SPOT_RE.match(line.strip())
    if not m:
        raise SpotParseError(f"unparseable spot: {line!r}")

    try:
        freq = float(m.group("freq"))
    except ValueError as exc:  # pragma: no cover - regex guarantees digits
        raise SpotParseError(str(exc)) from exc

    speed_raw = m.group("speed")
    speed = int(speed_raw) if speed_raw else None

    spotter = m.group("spotter").upper()
    spotted = m.group("dx").upper()

    return Spot(
        spotter=spotter,
        spotted=spotted,
        freq_khz=freq,
        mode=m.group("mode").upper(),
        snr_db=int(m.group("snr")),
        speed_wpm=speed,
        zulu=m.group("time"),
        comment=(m.group("comment") or "").strip(),
        raw=line.rstrip("\r\n"),
        recv_time=recv_time,
    )
