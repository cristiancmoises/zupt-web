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
        self.write_manifest()

    def write_manifest(self):
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

    def test_build_restores_self_executing_fixtures_from_extracted_modes(self):
        project = Path(__file__).resolve().parents[1]
        wrappers = (
            "test_frama_aes_nist_wrapper.sh",
            "test_frama_ans_decode_bounds_wrapper.sh",
            "test_jasmin_source_wrapper.sh",
        )
        tests = self.source / "tests"
        tests.mkdir()
        for name in wrappers:
            target = tests / name
            target.write_bytes((project / "zupt-5.2.10/tests" / name).read_bytes())
            target.chmod(0o600)
        data = tests / "not-an-entrypoint.sh"
        data.write_text("nonexecutable data\n")
        data.chmod(0o600)
        self.write_manifest()
        # Compile/check doubles exercise real upstream fixtures, not a native build.
        (self.bin / "make").write_text(
            """#!/bin/sh
set -eu
case " $* " in *" clean "*|*" check "*) exit 0 ;; esac
ln -s "$PWD/tests/test_frama_aes_nist_wrapper.sh" "$SOURCE_GATE_PROBE_DIR/frama-aes-fixture"
ln -s "$PWD/tests/test_frama_ans_decode_bounds_wrapper.sh" "$SOURCE_GATE_PROBE_DIR/frama-bounds-fixture"
ln -s "$PWD/tests/test_jasmin_source_wrapper.sh" "$SOURCE_GATE_PROBE_DIR/jasmin-warning-version"
FRAMA_AES_CASE=clean "$SOURCE_GATE_PROBE_DIR/frama-aes-fixture" -version
FRAMA_BOUNDS_CASE=clean "$SOURCE_GATE_PROBE_DIR/frama-bounds-fixture" -version
"$SOURCE_GATE_PROBE_DIR/jasmin-warning-version" --version
printf '#!/bin/sh\\nprintf "test CLI double\\\\n"\\n' > zupt
chmod 700 zupt
"""
        )
        for name in ("strip", "readelf"):
            helper = self.bin / name
            helper.write_text("#!/bin/sh\nexit 0\n")
            helper.chmod(0o700)
        before = {name: (tests / name).read_bytes() for name in wrappers}
        result = subprocess.run(
            ["sh", str(self.root / "build-zupt.sh")],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env={
                **os.environ,
                "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                "SOURCE_GATE_PROBE_DIR": str(self.bin),
            },
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in wrappers:
            self.assertTrue(os.access(tests / name, os.X_OK))
            self.assertEqual((tests / name).read_bytes(), before[name])
        self.assertEqual(data.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
