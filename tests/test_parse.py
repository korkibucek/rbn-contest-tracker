"""Tests for spot-line parsing, band mapping and continent lookup."""

import unittest

from rbn_tracker.bands import band_for
from rbn_tracker.continents import continent_for
from rbn_tracker.spots import SpotParseError, parse_spot


class TestParse(unittest.TestCase):
    def test_standard_line(self):
        line = ("DX de DL8TG-#:     14036.0  G4ABC          CW    "
                "12 dB  28 wpm  CQ      1234Z")
        s = parse_spot(line, recv_time=100.0)
        self.assertEqual(s.spotter, "DL8TG-#")
        self.assertEqual(s.spotted, "G4ABC")
        self.assertEqual(s.freq_khz, 14036.0)
        self.assertEqual(s.mode, "CW")
        self.assertEqual(s.snr_db, 12)
        self.assertEqual(s.speed_wpm, 28)
        self.assertEqual(s.zulu, "1234")
        self.assertEqual(s.band, "20m")
        self.assertEqual(s.spotter_continent, "EU")  # DL = Germany
        self.assertTrue(s.is_uk)
        self.assertEqual(s.recv_time, 100.0)

    def test_na_spotter(self):
        line = ("DX de W3LPL-#:     21025.0  MM1E           CW    "
                "20 dB  30 wpm  CQ      0959Z")
        s = parse_spot(line)
        self.assertEqual(s.spotter_continent, "NA")
        self.assertEqual(s.band, "15m")
        self.assertEqual(s.spotted, "MM1E")
        self.assertTrue(s.is_uk)

    def test_negative_snr_and_no_wpm(self):
        line = "DX de VK6XX-#: 7005.0 GW4XYZ RTTY -3 dB CQ 1200Z"
        s = parse_spot(line)
        self.assertEqual(s.snr_db, -3)
        self.assertIsNone(s.speed_wpm)
        self.assertEqual(s.spotter_continent, "OC")
        self.assertEqual(s.band, "40m")

    def test_non_uk_spotted_filtered(self):
        line = ("DX de K1TTT-#:     14005.0  DL1XYZ         CW    "
                "15 dB  25 wpm  CQ      1234Z")
        s = parse_spot(line)
        self.assertFalse(s.is_uk)

    def test_garbage_raises(self):
        for bad in ["", "hello world", "login: ", "Welcome to RBN"]:
            with self.subTest(bad=bad):
                with self.assertRaises(SpotParseError):
                    parse_spot(bad)


class TestBands(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(band_for(1810), "160m")
        self.assertEqual(band_for(3573), "80m")
        self.assertEqual(band_for(7040), "40m")
        self.assertEqual(band_for(14036), "20m")
        self.assertEqual(band_for(21025), "15m")
        self.assertEqual(band_for(28020), "10m")
        self.assertEqual(band_for(12345), "?")

    def test_non_hf_contest_bands_excluded(self):
        # WARC (30/17/12m), 60m and 6m are not HF contest bands -> unknown.
        self.assertEqual(band_for(5357), "?")   # 60m
        self.assertEqual(band_for(10136), "?")  # 30m
        self.assertEqual(band_for(18100), "?")  # 17m
        self.assertEqual(band_for(24905), "?")  # 12m
        self.assertEqual(band_for(50100), "?")  # 6m


class TestContinents(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(continent_for("W3LPL"), "NA")
        self.assertEqual(continent_for("K1TTT-#"), "NA")
        self.assertEqual(continent_for("VE3XYZ"), "NA")
        self.assertEqual(continent_for("DL8TG-#"), "EU")
        self.assertEqual(continent_for("G4ABC"), "EU")
        self.assertEqual(continent_for("JA1XYZ"), "AS")
        self.assertEqual(continent_for("VK6ABC"), "OC")
        self.assertEqual(continent_for("ZL2ABC"), "OC")
        self.assertEqual(continent_for("PY2XYZ"), "SA")
        self.assertEqual(continent_for("ZS6XYZ"), "AF")

    def test_longest_prefix_overrides(self):
        # US Pacific overrides plain K -> OC.
        self.assertEqual(continent_for("KH6XYZ"), "OC")
        # Canary Is. via prepend overrides EA (Spain/EU) -> AF.
        self.assertEqual(continent_for("EA8/G4ABC"), "AF")
        self.assertEqual(continent_for("EA3XYZ"), "EU")


if __name__ == "__main__":
    unittest.main()
