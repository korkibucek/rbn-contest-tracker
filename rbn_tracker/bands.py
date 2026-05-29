"""Amateur-radio band mapping (frequency in kHz -> band label).

Kept in its own module so the band plan is easy to extend or tweak.
"""

from __future__ import annotations

# (low_khz, high_khz, label) -- inclusive ranges, edges as given in the spec.
BAND_PLAN: list[tuple[float, float, str]] = [
    (1800.0, 2000.0, "160m"),
    (3500.0, 4000.0, "80m"),
    (5351.0, 5366.0, "60m"),
    (7000.0, 7300.0, "40m"),
    (10100.0, 10150.0, "30m"),
    (14000.0, 14350.0, "20m"),
    (18068.0, 18168.0, "17m"),
    (21000.0, 21450.0, "15m"),
    (24890.0, 24990.0, "12m"),
    (28000.0, 29700.0, "10m"),
    (50000.0, 54000.0, "6m"),
]

UNKNOWN_BAND = "?"

# Canonical ordering used when we present bands (low band -> high band).
BAND_ORDER: list[str] = [b[2] for b in BAND_PLAN] + [UNKNOWN_BAND]
_BAND_RANK = {label: i for i, label in enumerate(BAND_ORDER)}


def band_for(freq_khz: float) -> str:
    """Return the band label for a frequency in kHz, or ``"?"`` if unknown."""
    try:
        f = float(freq_khz)
    except (TypeError, ValueError):
        return UNKNOWN_BAND
    for low, high, label in BAND_PLAN:
        if low <= f <= high:
            return label
    return UNKNOWN_BAND


def band_sort_key(label: str) -> int:
    """Sort key so bands appear low-to-high; unknown sorts last."""
    return _BAND_RANK.get(label, len(BAND_ORDER))
