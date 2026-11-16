# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exercise the source gate without compiling or running vendored code."""

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class SourceGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        make = self.bin / "make"
        make.write_text("#!/bin/sh\necho unexpected-build >&2\nexit 23\n")
        make.chmod(0o755)
        shutil.copyfile(
            Path(__file__).resolve().parents[1] / "build-zupt.sh",
            self.root / "build-zupt.sh",
        )
        shutil.copyfile(
            Path(__file__).resolve().parents[1] / "verify-vendor.py",
            self.root / "verify-vendor.py",
        )
        self.source = self.root / "zupt-5.2.10"
        (self.source / "include").mkdir(parents=True)
        (self.source / "scripts").mkdir()
        (self.source / "include/zupt.h").write_text(
            '#define ZUPT_VERSION_STRING "5.2.10"\n'
        )
        (self.source / "scripts/check-source-only.sh").write_text("#!/bin/sh\nexit 0\n")
        (self.source / "scripts/check-source-only.sh").chmod(0o755)
        # Any accidental Make invocation fails instead of compiling anything.
        (self.source / "Makefile").write_text(
            "clean all check:\n\t@echo unexpected-build >&2; exit 23\n"
        )
        self.manifest = self.root / "zupt-5.2.10.SHA256SUMS"
        self.manifest.write_text(
            "".join(
                f"{hashlib.sha256(p.read_bytes()).hexdigest()}  "
                f"{p.relative_to(self.source).as_posix()}\n"
                for p in sorted(self.source.rglob("*"))
                if p.is_file()
            )
        )

    def verify(self):
        result = subprocess.run(
            ["sh", str(self.root / "build-zupt.sh"), "--verify-only"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env={**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"]},
        )
        self.assertNotIn("unexpected-build", result.stderr)
        self.assertNotIn("not found", result.stderr)
        return result

    def test_verify_only_accepts_exact_source_without_building(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_modified_source_is_rejected(self):
        (self.source / "include/zupt.h").write_text("modified\n")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Source checksum mismatch", result.stderr)

    def test_unlisted_file_is_rejected(self):
        (self.source / "unlisted.c").write_text("unlisted\n")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing or unlisted files", result.stderr)

    def test_unlisted_symlink_is_rejected(self):
        (self.source / "unlisted").symlink_to("include/zupt.h")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(
            "symlink or special file" in result.stderr
            or "Not a regular source file" in result.stderr
        )

    def test_symlink_in_place_of_listed_file_is_rejected(self):
        header = self.source / "include/zupt.h"
        target = self.root / "outside.h"
        target.write_bytes(header.read_bytes())
        header.unlink()
        header.symlink_to(target)
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(
            "symlink or special file" in result.stderr
            or "Not a regular source file" in result.stderr
        )


if __name__ == "__main__":
    unittest.main()
