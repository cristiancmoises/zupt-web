# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integrity regressions for signed Git blobs and checkout line endings."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
VERIFIER = PROJECT / 'verify-vendor.py'
MANIFEST = PROJECT / 'zupt-5.2.10.SHA256SUMS'
BATCH = 'gui/packaging/windows/build-windows.bat'
PORTABLE = 'packaging/portable/zupt-gui.bat'


class VendorManifestTests(unittest.TestCase):
    def require_git_history(self):
        if not shutil.which('git'):
            self.skipTest('Git checkout integration requires the git executable')
        top = subprocess.run(
            ['git', '-C', str(PROJECT), 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, check=False)
        if top.returncode or Path(top.stdout.strip()).resolve() != PROJECT:
            self.skipTest('Git checkout integration requires this source tree to be a Git worktree')
        for tag in ('v5.2.10', 'v5.2.11'):
            history = subprocess.run(
                ['git', '-C', str(PROJECT), 'rev-parse', '--verify', f'{tag}:zupt-5.2.10'],
                capture_output=True, text=True, check=False)
            if history.returncode:
                self.skipTest(f'Git checkout integration requires immutable {tag} vendor history')

    def verify(self, root, manifest):
        return subprocess.run(
            [sys.executable, str(VERIFIER), str(manifest), str(root)],
            capture_output=True, text=True, check=False)

    def fixture(self, path, content, expected=b'@echo off\necho hello\n'):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / 'source'
        target = root / path
        target.parent.mkdir(parents=True)
        target.write_bytes(content)
        manifest = Path(temporary.name) / 'SHA256SUMS'
        manifest.write_text(hashlib.sha256(expected).hexdigest() + '  ' + path + '\n')
        return root, manifest, target

    def test_declared_batch_accepts_canonical_lf(self):
        for path in (BATCH, PORTABLE):
            with self.subTest(path=path):
                root, manifest, _ = self.fixture(path, b'@echo off\necho hello\n')
                result = self.verify(root, manifest)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_declared_batch_accepts_exact_crlf(self):
        for path in (BATCH, PORTABLE):
            with self.subTest(path=path):
                root, manifest, _ = self.fixture(path, b'@echo off\r\necho hello\r\n')
                result = self.verify(root, manifest)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_mixed_newlines_are_rejected(self):
        for data in (b'@echo off\r\necho hello\n', b'@echo off\necho hello\r\n'):
            root, manifest, _ = self.fixture(BATCH, data)
            self.assertNotEqual(self.verify(root, manifest).returncode, 0)

    def test_bare_carriage_return_is_rejected(self):
        root, manifest, _ = self.fixture(BATCH, b'@echo off\recho hello\r')
        self.assertNotEqual(self.verify(root, manifest).returncode, 0)

    def test_lf_and_crlf_tampering_are_rejected(self):
        for data in (b'@echo off\necho evil\n', b'@echo off\r\necho evil\r\n'):
            root, manifest, _ = self.fixture(BATCH, data)
            self.assertNotEqual(self.verify(root, manifest).returncode, 0)

    def test_undeclared_batch_and_other_files_are_byte_exact(self):
        for path in ('other.bat', 'other.cmd', 'other.ps1', 'src/file.c'):
            with self.subTest(path=path):
                root, manifest, _ = self.fixture(path, b'@echo off\r\necho hello\r\n')
                self.assertNotEqual(self.verify(root, manifest).returncode, 0)
                root.joinpath(path).write_bytes(b'@echo off\necho hello\n')
                self.assertEqual(self.verify(root, manifest).returncode, 0)

    def test_missing_file_and_symlink_are_rejected(self):
        root, manifest, target = self.fixture(BATCH, b'@echo off\necho hello\n')
        target.unlink()
        self.assertNotEqual(self.verify(root, manifest).returncode, 0)
        outside = target.parent / 'outside.txt'
        outside.write_bytes(b'@echo off\necho hello\n')
        target.symlink_to(outside)
        self.assertNotEqual(self.verify(root, manifest).returncode, 0)

    def test_duplicate_or_traversing_manifest_entries_are_rejected(self):
        root, manifest, _ = self.fixture(BATCH, b'@echo off\necho hello\n')
        line = manifest.read_text()
        for text in (line + line, line.replace(BATCH, '../outside.bat')):
            manifest.write_text(text)
            self.assertNotEqual(self.verify(root, manifest).returncode, 0)

    def test_pristine_git_checkout_with_declared_crlf(self):
        self.require_git_history()
        with tempfile.TemporaryDirectory() as temporary:
            clone = Path(temporary) / 'clone'
            subprocess.run(['git', 'clone', '--quiet', '--no-local', str(PROJECT), str(clone)], check=True)
            source = clone / 'zupt-5.2.10'
            for path in (BATCH, PORTABLE):
                data = source.joinpath(path).read_bytes()
                self.assertIn(b'\r\n', data)
                self.assertNotIn(b'\n', data.replace(b'\r\n', b''))
            result = self.verify(source, clone / MANIFEST.name)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_historical_tag_exports_use_their_own_manifests(self):
        self.require_git_history()
        for tag in ('v5.2.10', 'v5.2.11'):
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'source'
                root.mkdir()
                manifest = Path(temporary) / MANIFEST.name
                manifest.write_bytes(subprocess.check_output([
                    'git', '-C', str(PROJECT), 'show', f'{tag}:{MANIFEST.name}']))
                entries = subprocess.check_output([
                    'git', '-C', str(PROJECT), 'ls-tree', '-r', '-z', f'{tag}:zupt-5.2.10'])
                for entry in entries.split(b'\0'):
                    if not entry:
                        continue
                    metadata, filename = entry.split(b'\t', 1)
                    mode, kind, oid = metadata.decode().split()
                    self.assertEqual(kind, 'blob')
                    path = root / os.fsdecode(filename)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(subprocess.check_output(['git', '-C', str(PROJECT), 'cat-file', 'blob', oid]))
                    path.chmod(int(mode, 8) & 0o777)
                for path in (BATCH, PORTABLE):
                    self.assertNotIn(b'\r', root.joinpath(path).read_bytes())
                result = self.verify(root, manifest)
                if tag == 'v5.2.10':
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr.strip(), f'Error: Source checksum mismatch: {BATCH}')
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
