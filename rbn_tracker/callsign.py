"""Callsign parsing and UK/Ireland DXCC prefix matching.

This module is deliberately standalone so the matching rules can be unit-tested
and tuned independently of the rest of the application.

Design notes / decisions (see the unit tests for the authoritative behaviour):

* We split a callsign into an optional *prepended prefix*, a *base call*, and
  zero or more *portable suffixes* (``/P``, ``/M``, ``/QRP`` ...).
* For the UK/Ireland cohort filter, a callsign counts as UK/IE only when it has
  **no prepended prefix** and its base call resolves to a UK/IE region. A
  prepended prefix means the operator is working away from (or into) the base
  call's home DXCC, and per the spec it is treated as *not* the UK cohort --
  e.g. ``EA8/G4ABC`` (Canary Is.) and ``MD/DL1ABC`` (a DL visiting the Isle of
  Man) are both excluded. ``G4ABC/P`` keeps its UK identity because ``/P`` is a
  portable suffix, not a prepend.
* Prefix matching is structural, not ``startswith`` -- ``M0TTT`` is England (M +
  digit) while ``MM1E`` is Scotland (the two-letter ``MM`` prefix).
"""

from __future__ import annotations

from dataclasses import dataclass

# Portable / operational suffixes that do NOT change the station's DXCC.
# Single digits (re-districting, e.g. ``G4ABC/9``) are handled separately.
PORTABLE_SUFFIXES = {
    "P",  # portable
    "M",  # mobile
    "MM",  # maritime mobile
    "AM",  # aeronautical mobile
    "A",  # alternate / portable (region dependent)
    "QRP",  # low power
    "QRPP",
    "B",  # beacon
    "LH",  # lighthouse
    "T",  # temporary
}

# Two-character UK/IE regional prefixes -> human-readable region.
# Note: G / M followed by a *digit* is England (the base allocation); only the
# specific two-letter combinations below denote the devolved/crown territories.
UK_TWO_CHAR = {
    # England (explicit two-char form for 2E)
    "2E": "England",
    # Scotland
    "GM": "Scotland",
    "MM": "Scotland",
    "2M": "Scotland",
    # Wales
    "GW": "Wales",
    "MW": "Wales",
    "2W": "Wales",
    # Northern Ireland
    "GI": "Northern Ireland",
    "MI": "Northern Ireland",
    "2I": "Northern Ireland",
    # Isle of Man
    "GD": "Isle of Man",
    "MD": "Isle of Man",
    "2D": "Isle of Man",
    # Jersey
    "GJ": "Jersey",
    "MJ": "Jersey",
    "2J": "Jersey",
    # Guernsey
    "GU": "Guernsey",
    "MU": "Guernsey",
    "2U": "Guernsey",
}


@dataclass(frozen=True)
class CallParts:
    """Structured view of a (possibly compound) callsign."""

    raw: str
    base: str  # the home callsign, suffixes stripped
    prepend: str | None  # location prefix before a '/', if any (e.g. EA8)
    suffixes: tuple[str, ...]  # portable suffixes, e.g. ('P',)

    @property
    def has_prepend(self) -> bool:
        return self.prepend is not None


def _is_suffix_token(tok: str) -> bool:
    """A token after '/' that does not change DXCC (portable indicators)."""
    if not tok:
        return False
    if tok in PORTABLE_SUFFIXES:
        return True
    if tok.isdigit():  # re-district indicator, e.g. /9
        return True
    return False


def _looks_like_full_call(tok: str) -> bool:
    """Heuristic: a full callsign has both letters and at least one digit."""
    return any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok)


def split_callsign(call: str) -> CallParts:
    """Split a raw callsign into prepend / base / suffixes.

    Handles forms like ``G4ABC``, ``G4ABC/P``, ``EA8/G4ABC``, ``MD/DL1ABC``,
    ``EA8/G4ABC/P`` and the RBN skimmer SSID marker (``W3LPL-#`` / ``-1``).
    """
    raw = (call or "").strip().upper()
    # Strip an SSID / skimmer marker such as "-#", "-1", "-DXC" (everything
    # after the first hyphen). RBN spotters frequently carry one.
    core = raw.split("-", 1)[0]

    parts = [p for p in core.split("/") if p != ""]
    if not parts:
        return CallParts(raw=raw, base=core, prepend=None, suffixes=())

    if len(parts) == 1:
        return CallParts(raw=raw, base=parts[0], prepend=None, suffixes=())

    # Peel trailing suffix tokens off the end.
    suffixes: list[str] = []
    while len(parts) > 1 and _is_suffix_token(parts[-1]):
        suffixes.insert(0, parts.pop())

    if len(parts) == 1:
        # Only a base call plus suffixes, e.g. G4ABC/P.
        return CallParts(
            raw=raw, base=parts[0], prepend=None, suffixes=tuple(suffixes)
        )

    # Two or more non-suffix tokens remain -> there is a prepended prefix.
    # Convention: shorter token is the location prefix, the full call is the
    # base. If both look like full calls (unusual), the first is the prepend.
    a, b = parts[0], parts[1]
    if _looks_like_full_call(a) and not _looks_like_full_call(b):
        prepend, base = b, a
    else:
        prepend, base = a, b
    return CallParts(raw=raw, base=base, prepend=prepend, suffixes=tuple(suffixes))


def uk_region(base: str) -> str | None:
    """Return the UK/IE region for a *base* callsign, or ``None`` if not UK/IE.

    ``base`` must already be free of prepends/suffixes (see :func:`split_callsign`).
    """
    if not base:
        return None
    c0 = base[0]

    if c0 in ("G", "M"):
        if len(base) < 2:
            return "England"
        c1 = base[1]
        if c1.isalpha():
            two = base[:2]
            # Specific devolved/crown prefix, else plain G/M = England.
            return UK_TWO_CHAR.get(two, "England")
        # G/M followed by a digit -> England (e.g. G4ABC, M0TTT).
        return "England"

    if c0 == "2":
        if len(base) < 2:
            return None
        two = base[:2]
        return UK_TWO_CHAR.get(two)  # 2E/2M/2W/... else None

    if c0 == "E":
        two = base[:2]
        if two in ("EI", "EJ"):
            return "Ireland"
        return None

    return None


def classify_uk(call: str) -> tuple[bool, str | None, CallParts]:
    """Classify a callsign for the UK/IE cohort.

    Returns ``(is_uk, region_or_None, parts)``. A prepended prefix disqualifies
    the call from the cohort even if the prepend itself looks UK.
    """
    parts = split_callsign(call)
    if parts.has_prepend:
        return False, None, parts
    region = uk_region(parts.base)
    return (region is not None), region, parts


def is_uk(call: str) -> bool:
    """Convenience: True iff ``call`` is a UK/IE cohort station."""
    ok, _region, _parts = classify_uk(call)
    return ok


def location_token(call: str) -> str:
    """The token that determines a station's *operating location*.

    For continent lookup of a spotter we want the prepend when present
    (``EA8/G4ABC`` is in Africa), otherwise the base call.
    """
    parts = split_callsign(call)
    return parts.prepend if parts.has_prepend else parts.base


def base_callsign(call: str) -> str:
    """The base/home callsign with SSID and suffixes removed (uppercased)."""
    return split_callsign(call).base


def same_station(call: str, target: str) -> bool:
    """True if ``call`` is ``target`` allowing portable suffixes (no prepend).

    Used for the "my own station" tracking, e.g. MM1E and MM1E/P match, but
    GM/MM1E or DL1ABC do not.
    """
    parts = split_callsign(call)
    if parts.has_prepend:
        return False
    return parts.base == (target or "").strip().upper()
