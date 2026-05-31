"""Locks the public command-line surface.

The CLI is part of the project's public API and follows SemVer from 1.0.0:
flag names, defaults, types, choices and required-ness must not change without
a deliberate (and, for removals/renames/incompatible-default changes, a
major-version) bump.

This test is intentionally a tripwire. If it fails because you changed the
parser, update the expectations here *and* the user-facing docs
(docs/configuration.md, usage/getting-started, CHANGELOG) in the same commit,
so the surface and its documentation never drift apart.
"""

import argparse
import contextlib
import io
import unittest

from rbn_tracker.cli import build_parser


# dest -> expected (option_strings, default, required, choices)
# Only the deliberately public options are listed. `--help` is argparse's and
# is checked separately.
EXPECTED = {
    "callsign":         (("--callsign",),        None,     False, None),
    "mycall":           (("--mycall",),          None,     True,  None),
    "window":           (("--window",),          60,       False, None),
    "avg_window":       (("--avg-window",),      15.0,     False, None),
    "category":         (("--category",),        "single", False, None),
    "history":          (("--history",),         5,        False, None),
    "opponents":        (("--opponents",),       "off",    False, ("auto", "manual", "off")),
    "opponents_file":   (("--opponents-file",),  None,     False, None),
    "score_url":        (("--score-url",),       None,     False, None),
    "contest":          (("--contest",),         None,     False, None),
    "score_api_key":    (("--score-api-key",),   None,     False, None),
    "opponents_window": (("--opponents-window",), 5,       False, None),
    "csv":              (("--csv",),             None,     False, None),
    "min_snr":          (("--min-snr",),         None,     False, None),
    "once":             (("--once",),            False,    False, None),
    "replay":           (("--replay",),          None,     False, None),
    "ascii":            (("--ascii",),           False,    False, None),
    "tui":              (("--tui",),             False,    False, None),
    "no_tui":           (("--no-tui",),          False,    False, None),
    "verbose":          (("-v", "--verbose"),    False,    False, None),
}


class CliSurfaceTest(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()
        # dest -> Action, excluding argparse's built-in --help and --version.
        self.actions = {
            a.dest: a
            for a in self.parser._actions
            if a.dest not in ("help", "version")
        }

    def test_no_unexpected_options(self):
        """Adding or removing a flag must be a deliberate change to this test."""
        self.assertEqual(set(self.actions), set(EXPECTED))

    def test_each_option_is_stable(self):
        for dest, (opts, default, required, choices) in EXPECTED.items():
            with self.subTest(dest=dest):
                action = self.actions[dest]
                self.assertEqual(tuple(action.option_strings), opts)
                self.assertEqual(action.default, default)
                self.assertEqual(action.required, required)
                self.assertEqual(
                    tuple(action.choices) if action.choices else None, choices
                )

    def test_version_action_present(self):
        version = next(
            (a for a in self.parser._actions if a.dest == "version"), None
        )
        self.assertIsInstance(version, argparse._VersionAction)

    def test_tui_and_no_tui_are_mutually_exclusive(self):
        groups = self.parser._mutually_exclusive_groups
        pairs = [
            {a.dest for a in g._group_actions}
            for g in groups
        ]
        self.assertIn({"tui", "no_tui"}, pairs)

    def test_mycall_is_required(self):
        with self.assertRaises(SystemExit), \
                contextlib.redirect_stderr(io.StringIO()):
            self.parser.parse_args(["--replay", "f"])

    def test_callsign_required_for_live_but_not_replay(self):
        from rbn_tracker import cli

        # Live (no --replay) without --callsign is rejected.
        with self.assertRaises(SystemExit), \
                contextlib.redirect_stderr(io.StringIO()):
            cli.main(["--mycall", "MM1E", "--once"])

        # Replay supplies no live connection, so --callsign is not required.
        # --once keeps it non-interactive and terminating; a missing replay
        # file surfaces as a handled error, not an argparse failure.
        args = self.parser.parse_args(
            ["--replay", "f", "--mycall", "MM1E", "--once"]
        )
        self.assertIsNone(args.callsign)
        self.assertEqual(args.mycall, "MM1E")


if __name__ == "__main__":
    unittest.main()
