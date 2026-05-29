"""Unit tests for UK/IE prefix matching -- the heart of the cohort filter."""

import unittest

from rbn_tracker.callsign import (
    classify_uk,
    is_uk,
    location_token,
    same_station,
    split_callsign,
    uk_region,
)


class TestUkMatching(unittest.TestCase):
    # The exact cases mandated by the spec.
    UK_CASES = {
        "MM1E": "Scotland",
        "M0TTT": "England",
        "2E0ABC": "England",
        "GW4XYZ": "Wales",
        "EI5XYZ": "Ireland",
        "GD1A": "Isle of Man",
        "GJ2A": "Jersey",
        "G4ABC/P": "England",  # portable suffix keeps UK identity
        "2M0ZZZ": "Scotland",
    }
    NOT_UK = ["EA8/G4ABC", "MD/DL1ABC"]

    def test_uk_cases_are_uk(self):
        for call, region in self.UK_CASES.items():
            with self.subTest(call=call):
                ok, got, _ = classify_uk(call)
                self.assertTrue(ok, f"{call} should be UK")
                self.assertEqual(got, region)

    def test_not_uk_cases(self):
        for call in self.NOT_UK:
            with self.subTest(call=call):
                self.assertFalse(is_uk(call), f"{call} should NOT be UK")

    def test_extra_regions(self):
        self.assertEqual(uk_region("GM3X"), "Scotland")
        self.assertEqual(uk_region("2E0XYZ"), "England")
        self.assertEqual(uk_region("MW0ABC"), "Wales")
        self.assertEqual(uk_region("MI0XYZ"), "Northern Ireland")
        self.assertEqual(uk_region("GU4ABC"), "Guernsey")
        self.assertEqual(uk_region("MU0ABC"), "Guernsey")
        self.assertEqual(uk_region("EJ9XYZ"), "Ireland")
        self.assertEqual(uk_region("2D0ABC"), "Isle of Man")

    def test_non_uk_prefixes_return_none(self):
        for call in ["EA8ABC", "DL1ABC", "W3LPL", "F5IN", "EA3XYZ", "ON4XYZ"]:
            with self.subTest(call=call):
                self.assertIsNone(uk_region(call))

    def test_g_and_m_with_digit_is_england(self):
        self.assertEqual(uk_region("G4ABC"), "England")
        self.assertEqual(uk_region("M0TTT"), "England")
        # G/M with a non-regional letter still England (clubs/specials).
        self.assertEqual(uk_region("GB2ABC"), "England")
        self.assertEqual(uk_region("MX0ABC"), "England")

    def test_prepended_prefix_excluded_even_if_uk_looking(self):
        # A prepend means operating away from home -> excluded from cohort.
        self.assertFalse(is_uk("EA8/G4ABC"))
        self.assertFalse(is_uk("MD/DL1ABC"))
        self.assertFalse(is_uk("F/G4ABC"))


class TestSplit(unittest.TestCase):
    def test_plain(self):
        p = split_callsign("MM1E")
        self.assertEqual(p.base, "MM1E")
        self.assertIsNone(p.prepend)
        self.assertEqual(p.suffixes, ())

    def test_portable_suffix(self):
        p = split_callsign("G4ABC/P")
        self.assertEqual(p.base, "G4ABC")
        self.assertIsNone(p.prepend)
        self.assertEqual(p.suffixes, ("P",))

    def test_prepend(self):
        p = split_callsign("EA8/G4ABC")
        self.assertEqual(p.prepend, "EA8")
        self.assertEqual(p.base, "G4ABC")

    def test_prepend_with_suffix(self):
        p = split_callsign("MD/DL1ABC/P")
        self.assertEqual(p.prepend, "MD")
        self.assertEqual(p.base, "DL1ABC")
        self.assertEqual(p.suffixes, ("P",))

    def test_skimmer_ssid_stripped(self):
        p = split_callsign("W3LPL-#")
        self.assertEqual(p.base, "W3LPL")
        p2 = split_callsign("DL8TG-1")
        self.assertEqual(p2.base, "DL8TG")

    def test_redistrict_digit_suffix(self):
        p = split_callsign("G4ABC/9")
        self.assertEqual(p.base, "G4ABC")
        self.assertIsNone(p.prepend)

    def test_location_token(self):
        self.assertEqual(location_token("EA8/G4ABC"), "EA8")
        self.assertEqual(location_token("G4ABC/P"), "G4ABC")
        self.assertEqual(location_token("W3LPL-#"), "W3LPL")


class TestSameStation(unittest.TestCase):
    def test_exact_and_suffix(self):
        self.assertTrue(same_station("MM1E", "MM1E"))
        self.assertTrue(same_station("MM1E/P", "MM1E"))
        self.assertTrue(same_station("mm1e/qrp", "MM1E"))

    def test_prepend_is_not_me(self):
        self.assertFalse(same_station("GM/MM1E", "MM1E"))

    def test_other_station(self):
        self.assertFalse(same_station("MM1F", "MM1E"))
        self.assertFalse(same_station("M0TTT", "MM1E"))


if __name__ == "__main__":
    unittest.main()
