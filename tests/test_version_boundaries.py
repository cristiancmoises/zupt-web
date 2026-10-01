# SPDX-License-Identifier: AGPL-3.0-or-later

import unittest

import app
import live_smoke


class VersionBoundaryTests(unittest.TestCase):
    def test_web_release_is_distinct_from_bundled_cli(self):
        self.assertEqual(app.APP_VERSION, '5.2.12')
        args = live_smoke.parse_args([])
        self.assertEqual(args.expected_version, '5.2.12')
        self.assertEqual(args.expected_cli_version, '5.2.10')

    def test_smoke_accepts_separate_explicit_version_expectations(self):
        args = live_smoke.parse_args([
            '--expected-version', '5.2.12', '--expected-cli-version', '5.2.10'])
        self.assertEqual(args.expected_version, '5.2.12')
        self.assertEqual(args.expected_cli_version, '5.2.10')
