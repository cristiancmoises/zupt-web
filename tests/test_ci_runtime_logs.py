# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exercise the CI runtime-log gate without a container engine."""

import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class RuntimeLogGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = (
            Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")
        start = '          log_file="$RUNNER_TEMP/zupt-web-ci.log"\n'
        end = "      - name: Export the tested image and source revision\n"
        if workflow.count(start) != 1 or workflow.count(end) != 1:
            raise AssertionError("CI runtime-log gate markers must each occur once")
        start_index = workflow.index(start)
        end_index = workflow.index(end)
        if end_index <= start_index:
            raise AssertionError("CI runtime-log gate markers are out of order")
        cls.fragment = textwrap.dedent(workflow[start_index:end_index])
        cls.bash = shutil.which("bash")
        if cls.bash is None:
            raise AssertionError("Bash is required to exercise the CI shell fragment")

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("cat", "grep"):
            command = shutil.which(name)
            self.assertIsNotNone(command, f"Required shell command is missing: {name}")
            (self.bin / name).symlink_to(command)
        self.write_stub(
            "docker",
            'if [ "$#" -ne 2 ] || [ "$1" != logs ] || [ "$2" != zupt-web-ci ]; then\n'
            '  printf "%s\\n" "unexpected Docker invocation" >&2\n'
            "  exit 64\n"
            "fi\n"
            'printf "%s\\n" "$DOCKER_LOG_TEXT"\n'
            'exit "$DOCKER_LOG_STATUS"\n',
        )

    def write_stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o700)

    def run_gate(self, logs, docker_status=0):
        return subprocess.run(
            [
                self.bash,
                "--noprofile",
                "--norc",
                "-e",
                "-o",
                "pipefail",
                "-c",
                self.fragment,
            ],
            cwd=self.root,
            env={
                "PATH": str(self.bin),
                "RUNNER_TEMP": str(self.root),
                "LC_ALL": "C",
                "DOCKER_LOG_TEXT": logs,
                "DOCKER_LOG_STATUS": str(docker_status),
            },
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def test_clean_logs_are_accepted(self):
        result = self.run_gate("[INFO] Listening at: http://0.0.0.0:8080")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_control_server_error_is_rejected(self):
        result = self.run_gate("[ERROR] Control server error: synthetic failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Gunicorn control server failed", result.stderr)

    def test_log_collection_failure_is_rejected(self):
        result = self.run_gate(
            "synthetic Docker log collection failure", docker_status=23
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not collect container logs", result.stderr)

    def test_grep_diagnostic_is_rejected(self):
        (self.bin / "grep").unlink()
        self.write_stub(
            "grep", 'printf "%s\\n" "grep: synthetic read failure" >&2\nexit 2\n'
        )
        result = self.run_gate("[INFO] Worker ready")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("grep: synthetic read failure", result.stderr)


if __name__ == "__main__":
    unittest.main()
