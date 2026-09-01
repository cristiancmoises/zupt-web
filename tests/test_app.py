# SPDX-License-Identifier: AGPL-3.0-or-later

import io
import os
import re
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app as zupt_web


class ZuptWebTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_workdir = zupt_web.WORKDIR
        self.previous_version_cache = zupt_web._VERSION_CACHE
        self.previous_version_ok = zupt_web._VERSION_OK
        zupt_web.WORKDIR = Path(self.tempdir.name)
        zupt_web._rate.clear()
        zupt_web._VERSION_CACHE = 'zupt 5.2.8 (format v1.6, VaptVupt 2.65.3)'
        zupt_web._VERSION_OK = True
        zupt_web.app.config.update(TESTING=True)
        self.client = zupt_web.app.test_client()

    def tearDown(self):
        zupt_web.WORKDIR = self.previous_workdir
        zupt_web._VERSION_CACHE = self.previous_version_cache
        zupt_web._VERSION_OK = self.previous_version_ok
        self.tempdir.cleanup()

    def csrf(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        cookie = self.client.get_cookie('csrf_token')
        self.assertIsNotNone(cookie)
        return cookie.value

    def test_health_and_security_headers(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.get_json(), {
            'ok': True,
            'service': 'zupt-web',
            'version': '5.2.8',
        })
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        csp = response.headers['Content-Security-Policy']
        self.assertIn("default-src 'none'", csp)
        self.assertNotIn('fonts.googleapis.com', csp)

    def test_version_is_readiness_not_false_success(self):
        zupt_web._VERSION_CACHE = None
        zupt_web._VERSION_OK = False
        with mock.patch.object(zupt_web, 'run_zupt', return_value=(-1, '', 'missing')):
            response = self.client.get('/version')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {
            'ok': False,
            'version': 'zupt (offline)',
        })

    def test_index_uses_only_current_supported_modes(self):
        response = self.client.get('/')
        body = response.get_data(as_text=True)
        self.assertIn('ZUPT CLI', body)
        self.assertIn('5.2.8', body)
        self.assertIn('VaptVupt 2.65.3', body)  # codec name is intentional
        self.assertNotIn('action="/keygen-sdk"', body)
        self.assertNotIn('name="pq_sdk_key"', body)
        self.assertNotIn('fonts.googleapis.com', body)
        self.assertEqual(self.client.get('/keygen-sdk').status_code, 404)

    def test_csrf_is_required(self):
        response = self.client.post('/compress', data={})
        self.assertEqual(response.status_code, 403)

    def test_environment_prefers_zupt_and_falls_back(self):
        with mock.patch.dict(os.environ, {
            'ZUPT_BIN': '/canonical/zupt',
            'VAPTVUPT_BIN': '/compat/vaptvupt',
        }, clear=True):
            self.assertEqual(zupt_web.env('BIN'), '/canonical/zupt')
        with mock.patch.dict(os.environ, {
            'VAPTVUPT_BIN': '/compat/vaptvupt',
        }, clear=True):
            self.assertEqual(zupt_web.env('BIN'), '/compat/vaptvupt')

    def test_password_validation_is_byte_accurate(self):
        self.assertIsNone(zupt_web._password_error('  -leading and spaced  '))
        self.assertIn('line-break', zupt_web._password_error('bad\nvalue'))
        self.assertIn('255-byte', zupt_web._password_error('é' * 128))

    def test_compress_sends_password_over_fd_not_argv(self):
        token = self.csrf()
        calls = []
        secret = '  -exact password  '

        def fake_run(args, timeout=600, input_data=None, cwd=None):
            calls.append((list(args), timeout, input_data, cwd))
            Path(args[-3]).write_bytes(b'archive')
            return 0, 'ok', ''

        with mock.patch.object(zupt_web, 'run_zupt', side_effect=fake_run):
            response = self.client.post('/compress', data={
                'csrf_token': token,
                'password': secret,
                'level': '9',
                'codec': 'vv',
                'file': (io.BytesIO(b'payload'), '-payload.txt'),
            }, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 200)
        args, _, input_data, cwd = calls[0]
        self.assertIn('--pass-fd', args)
        self.assertEqual(args[args.index('--pass-fd') + 1], '0')
        self.assertIn('--vv', args)
        self.assertIn('9', args)
        self.assertNotIn(secret, args)
        self.assertEqual(input_data, secret + '\n')
        self.assertEqual(Path(cwd).name, 'in')
        self.assertEqual(args[-2:], ['--', '-payload.txt'])
        response.close()
        self.assertEqual(list(zupt_web.WORKDIR.iterdir()), [])

    def test_compress_rejects_solid_plus_dedup(self):
        token = self.csrf()
        with mock.patch.object(zupt_web, 'run_zupt') as runner:
            response = self.client.post('/compress', data={
                'csrf_token': token,
                'solid': 'on',
                'dedup': 'on',
                'file': (io.BytesIO(b'payload'), 'payload.txt'),
            }, content_type='multipart/form-data')
        self.assertIn('cannot be combined', response.get_data(as_text=True))
        runner.assert_not_called()

    def test_compress_rejects_multiple_credentials(self):
        token = self.csrf()
        with mock.patch.object(zupt_web, 'run_zupt') as runner:
            response = self.client.post('/compress', data={
                'csrf_token': token,
                'password': 'secret',
                'pq_key': (io.BytesIO(b'key'), 'public.key'),
                'file': (io.BytesIO(b'payload'), 'payload.txt'),
            }, content_type='multipart/form-data')
        self.assertIn('Choose ONE', response.get_data(as_text=True))
        runner.assert_not_called()

    def test_verify_accepts_hybrid_private_key(self):
        token = self.csrf()
        calls = []

        def fake_run(args, timeout=600, input_data=None):
            calls.append((list(args), input_data))
            return 0, 'Archive OK', ''

        with mock.patch.object(zupt_web, 'run_zupt', side_effect=fake_run):
            response = self.client.post('/test-archive', data={
                'csrf_token': token,
                'archive': (io.BytesIO(b'archive'), 'backup.zupt'),
                'pq_key': (io.BytesIO(b'key'), 'private.key'),
            }, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 200)
        args, input_data = calls[0]
        self.assertEqual(args[0], 'test')
        self.assertIn('--pq', args)
        self.assertIsNone(input_data)
        self.assertIn('Archive OK', response.get_data(as_text=True))

    def test_extract_packages_multiple_regular_files(self):
        token = self.csrf()

        def fake_run(args, timeout=600, input_data=None):
            outdir = Path(args[args.index('-o') + 1])
            (outdir / 'one.txt').write_text('one', encoding='utf-8')
            nested = outdir / 'nested'
            nested.mkdir()
            (nested / 'two.txt').write_text('two', encoding='utf-8')
            return 0, '', ''

        with mock.patch.object(zupt_web, 'run_zupt', side_effect=fake_run):
            response = self.client.post('/extract', data={
                'csrf_token': token,
                'archive': (io.BytesIO(b'archive'), 'backup.zupt'),
            }, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 200)
        with tarfile.open(fileobj=io.BytesIO(response.data), mode='r:gz') as archive:
            self.assertEqual(sorted(archive.getnames()),
                             ['nested/two.txt', 'one.txt'])
        response.close()
        self.assertEqual(list(zupt_web.WORKDIR.iterdir()), [])

    def test_keygen_download_names_are_zupt(self):
        token = self.csrf()

        def fake_run(args, timeout=600, input_data=None):
            Path(args[args.index('-o') + 1]).write_bytes(b'key')
            return 0, '', ''

        with mock.patch.object(zupt_web, 'run_zupt', side_effect=fake_run):
            response = self.client.post('/keygen', data={'csrf_token': token})

        body = response.get_data(as_text=True)
        self.assertIn('zupt_private.key', body)
        self.assertIn('zupt_public.key', body)
        match = re.search(r'/download-key/([a-f0-9]+)/private', body)
        self.assertIsNotNone(match)
        self.assertEqual(len(match.group(1)), 32)
        self.assertEqual(
            self.client.get('/download-key/not-a-capability/private').status_code,
            404)
        download = self.client.get(match.group(0))
        self.assertIn('filename=zupt_private.key',
                      download.headers['Content-Disposition'])
        self.assertIn('no-store', download.headers['Cache-Control'])
        download.close()

        job_dir = zupt_web.WORKDIR / match.group(1)
        expired = time.time() - zupt_web.MAX_KEY_AGE - 1
        os.utime(job_dir, (expired, expired))
        self.assertEqual(self.client.get(match.group(0)).status_code, 404)
        self.assertFalse(job_dir.exists())

    def test_safe_filename_rejects_directory_components(self):
        self.assertEqual(zupt_web.safe_filename('.'), 'file')
        self.assertEqual(zupt_web.safe_filename('..'), 'file')

    def test_sdk_compatibility_error_has_migration_hint(self):
        message = zupt_web.compatibility_hint(
            'Error: this build has no libvuptsdk support for Argon2id')
        self.assertIn('v5.2.1', message)
        self.assertIn('MIGRATION.md', message)


if __name__ == '__main__':
    unittest.main()
