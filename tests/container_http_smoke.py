#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exercise a running ZUPT Web service using only the Python standard library."""

import argparse
import http.cookiejar
import json
import os
import re
import secrets
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

FIXTURE = bytes(range(256)) * 16
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REQUESTS = 24


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument(
        "--expected-version", "--expected-web-version", default="5.2.13"
    )
    parser.add_argument("--expected-cli-version", default="5.2.10")
    parser.add_argument(
        "--timeout", type=float, default=60, help="request timeout in seconds"
    )
    parser.add_argument("--total-timeout", type=float, default=300)
    args = parser.parse_args(argv)
    target = urllib.parse.urlsplit(args.base_url)
    if (
        target.scheme not in ("http", "https")
        or not target.hostname
        or target.username is not None
        or target.password is not None
        or target.query
        or target.fragment
    ):
        parser.error("base URL must be HTTP(S), without credentials, query or fragment")
    if not 0 < args.timeout <= 120 or not 0 < args.total_timeout <= 600:
        parser.error("timeouts must be positive: request <= 120s, total <= 600s")
    args.base_url = args.base_url.rstrip("/")
    return args


class CsrfInputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tokens = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "input" and attributes.get("name") == "csrf_token":
            self.tokens.append(attributes.get("value"))


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def multipart(fields, file_field, filename, contents):
    boundary = "zupt-smoke-" + secrets.token_hex(16)
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
        f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
    )
    parts.extend((contents, f"\r\n--{boundary}--\r\n".encode()))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class ContainerHttpSmoke(unittest.TestCase):
    options = parse_args([])
    request_count = 0

    def setUp(self):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.cookies),
            NoRedirects(),
        )

    def request(self, path, data=None, content_type=None):
        type(self).request_count += 1
        self.assertLessEqual(
            self.request_count, MAX_REQUESTS, "HTTP request budget exceeded"
        )
        headers = {"Accept-Encoding": "identity"}
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(
            self.options.base_url + path, data=data, headers=headers
        )
        try:
            try:
                response = self.opener.open(request, timeout=self.options.timeout)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                self.assertLessEqual(
                    len(body), MAX_RESPONSE_BYTES, "HTTP response exceeded byte limit"
                )
                return response.status, response.headers, body
        except (OSError, urllib.error.URLError) as error:
            self.fail(f"HTTP request to {path} failed ({type(error).__name__})")

    def home(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "text/html")
        html = body.decode("utf-8")
        version = re.search(r'<span class="header-ver">([^<]+)</span>', html)
        self.assertIsNotNone(version, "Home page is missing its CLI version")
        self.assert_cli_version(version.group(1))
        self.assertNotIn("zupt (offline)", html.lower())
        tokens = CsrfInputs()
        tokens.feed(html)
        cookie_values = [
            cookie.value for cookie in self.cookies if cookie.name == "csrf_token"
        ]
        self.assertEqual(len(cookie_values), 1, "Home page must set one CSRF cookie")
        self.assertTrue(tokens.tokens, "Home page is missing CSRF form fields")
        self.assertTrue(
            all(token == cookie_values[0] for token in tokens.tokens),
            "CSRF form fields must match the cookie",
        )
        return cookie_values[0]

    def assert_cli_version(self, version):
        self.assertRegex(
            version,
            rf"^zupt\s+{re.escape(self.options.expected_cli_version)}(?:\s|\(|$)",
        )
        self.assertNotIn("offline", version.lower())

    def upload(self, path, fields, file_field, filename, contents):
        data, content_type = multipart(fields, file_field, filename, contents)
        return self.request(path, data, content_type)

    def assert_download(self, response, filename):
        status, headers, body = response
        self.assertEqual(status, 200)
        disposition = headers.get("Content-Disposition", "")
        self.assertTrue(
            disposition.startswith("attachment;"), "Expected a file download"
        )
        self.assertEqual(headers.get_filename(), filename)
        self.assertIn("no-store", headers.get("Cache-Control", ""))
        return body

    def compress(self, token, filename, contents, password=None):
        fields = {"csrf_token": token, "codec": "vv", "level": "9"}
        if password:
            fields["password"] = password
        return self.assert_download(
            self.upload("/compress", fields, "file", filename, contents),
            filename + ".zupt",
        )

    def extract(self, token, filename, archive, password=None):
        fields = {"csrf_token": token}
        if password:
            fields["password"] = password
        return self.upload("/extract", fields, "archive", filename + ".zupt", archive)

    def test_health_and_public_versions(self):
        status, headers, body = self.request("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "application/json")
        self.assertEqual(
            json.loads(body),
            {
                "ok": True,
                "service": "zupt-web",
                "version": self.options.expected_version,
            },
        )
        self.home()
        status, headers, body = self.request("/version")
        self.assertEqual(status, 200, "CLI readiness must succeed")
        self.assertEqual(headers.get_content_type(), "application/json")
        version = json.loads(body)
        self.assertIs(version.get("ok"), True)
        self.assert_cli_version(version["version"])

    def test_vv_level_nine_roundtrip(self):
        token = self.home()
        filename = "fixture.bin"
        archive = self.compress(token, filename, FIXTURE)
        self.assertTrue(archive, "Compression returned an empty archive")
        restored = self.assert_download(
            self.extract(token, filename, archive), filename
        )
        self.assertEqual(restored, FIXTURE)

    def test_empty_file_roundtrip(self):
        token = self.home()
        filename = "empty.bin"
        archive = self.compress(token, filename, b"")
        self.assertTrue(archive, "Compression returned an empty archive")
        restored = self.assert_download(
            self.extract(token, filename, archive), filename
        )
        self.assertEqual(restored, b"")

    def test_password_roundtrip_and_wrong_password_rejection(self):
        token = self.home()
        filename = "protected.bin"
        password = secrets.token_urlsafe(24)
        wrong_password = secrets.token_urlsafe(24) + "-wrong"
        archive = self.compress(token, filename, FIXTURE, password)
        self.assertTrue(archive, "Compression returned an empty archive")
        restored = self.assert_download(
            self.extract(token, filename, archive, password), filename
        )
        self.assertEqual(restored, FIXTURE)
        status, headers, body = self.extract(token, filename, archive, wrong_password)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "text/html")
        self.assertIsNone(headers.get("Content-Disposition"))
        self.assertTrue(
            b"<title>Error" in body, "Wrong password must return an error page"
        )
        self.assertTrue(
            b"Extraction failed:" in body, "Wrong password must fail extraction"
        )
        self.assertFalse(
            any(value.encode() in body for value in (password, wrong_password)),
            "Error response exposed a submitted password",
        )

    def test_missing_csrf_is_forbidden(self):
        self.home()
        for path, field in (("/compress", "file"), ("/extract", "archive")):
            with self.subTest(path=path):
                status, _, _ = self.upload(path, {}, field, "fixture.bin", FIXTURE)
                self.assertEqual(status, 403)


def main(argv=None):
    ContainerHttpSmoke.options = parse_args(argv)

    def timeout():
        os.write(2, b"HTTP smoke test exceeded its total timeout\n")
        os._exit(1)

    timer = threading.Timer(ContainerHttpSmoke.options.total_timeout, timeout)
    timer.daemon = True
    timer.start()
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ContainerHttpSmoke)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        timer.cancel()


if __name__ == "__main__":
    sys.exit(main())
