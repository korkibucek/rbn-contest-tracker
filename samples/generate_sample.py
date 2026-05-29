#!/usr/bin/env python3
"""Generate a synthetic RBN replay feed for testing/verification.

Lines are emitted in the form ``@<offset_secs>\t<raw spot line>`` so the
tracker's --replay mode can roll deterministic 60s windows from them.

The data is SYNTHETIC TEST DATA -- it is shaped to exercise the trend engine
(15m into NA rising, 40m fading) and to include the tracked station MM1E so the
"me" section and QSY suggestion render. It is NOT real propagation.
"""
import random

random.seed(42)

# Skimmers by continent (callsign -> continent is inferred by the tracker).
NA = ["W3LPL-#", "K1TTT-#", "W1NT-6-#", "K9IMM-#", "VE3EID-#", "N4ZR-#"]
EU = ["DL8TG-#", "SM7IUN-#", "G4ZFE-#", "OH6BG-#", "F5MUX-#", "DK9IP-#"]
OC = ["VK6ANC-#", "ZL3X-#"]
AS = ["JA1ZGP-#"]

UK = ["G4ABC", "M0XYZ", "2E0PQR", "GW4ZZZ", "MM3AAA", "GM4DEF", "EI7GH", "MI0JKL"]

lines = []


def add(offset, spotter, dx, freq, snr, wpm=28):
    lines.append(f"@{offset:.1f}\tDX de {spotter}: {freq:.1f} {dx} CW "
                 f"{snr} dB {wpm} wpm CQ {1200 + int(offset // 60):04d}Z")


def scatter(t0, t1, spotters, calls, freq, n, snr_lo, snr_hi):
    for _ in range(n):
        add(random.uniform(t0, t1), random.choice(spotters),
            random.choice(calls), freq + random.uniform(-3, 3),
            random.randint(snr_lo, snr_hi))


# --- Window 1: 0-60s -- EU busy on 20m, modest NA on 40m, a touch of 15m NA ---
scatter(1, 58, EU, UK, 14036, 18, 8, 25)
scatter(1, 58, NA, UK, 7035, 10, 5, 18)   # 40m into NA
scatter(1, 58, NA, UK, 21025, 4, 8, 15)   # 15m into NA (small)
# MM1E getting out on 40m to a couple of NA skimmers
add(20, "W3LPL-#", "MM1E", 7032.0, 9, 30)
add(35, "K1TTT-#", "MM1E", 7032.0, 7, 30)

# --- Window 2: 60-120s -- 15m into NA building, 40m fading ---
scatter(61, 118, EU, UK, 14036, 16, 8, 25)
scatter(61, 118, NA, UK, 7035, 5, 4, 14)   # 40m NA fading
scatter(61, 118, NA, UK, 21025, 9, 10, 20)  # 15m NA rising
scatter(61, 118, OC, UK, 21030, 2, 5, 10)   # a whiff of OC on 15m
# MM1E now also heard on 15m into NA, stronger
add(70, "W3LPL-#", "MM1E", 21024.0, 14, 30)
add(95, "K1TTT-#", "MM1E", 21024.0, 18, 30)
add(110, "N4ZR-#", "MM1E", 21024.0, 16, 30)
add(80, "W3LPL-#", "MM1E", 7032.0, 4, 30)   # still a weak 40m report

# --- Window 3: 120-180s -- 15m NA strong, 40m nearly gone ---
scatter(121, 178, EU, UK, 14036, 14, 8, 25)
scatter(121, 178, NA, UK, 7035, 2, 3, 9)    # 40m almost gone
scatter(121, 178, NA, UK, 21025, 16, 12, 22)  # 15m NA strong
scatter(121, 178, AS, UK, 21028, 2, 5, 12)   # JA appears on 15m
# MM1E firmly on 15m into NA
add(130, "W3LPL-#", "MM1E", 21024.0, 19, 32)
add(145, "K1TTT-#", "MM1E", 21024.0, 21, 32)
add(160, "N4ZR-#", "MM1E", 21024.0, 17, 32)
add(170, "VE3EID-#", "MM1E", 21024.0, 15, 32)

lines.sort(key=lambda s: float(s.split("\t", 1)[0][1:]))
print("\n".join(lines))
