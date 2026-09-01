#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end HTTP smoke test for a running ZUPT Web container.

The test intentionally uses only the Python standard library. It exercises the
public web boundary (including cookies, CSRF, multipart uploads, and attachment
downloads), rather than importing the Flask application directly.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import html
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import Message
from typing import Mapping


DEFAULT_URL = "http://127.0.0.1:8181"
DEFAULT_VERSION = "5.2.8"
PASSWORD = "  -ZUPT live smoke passphrase 2026!  "
PAYLOAD = (
    b"ZUPT Web live HTTP smoke test\n"
    + bytes(range(256)) * 16
    + b"\x00binary-tail\xff\n"
    + (b"compressible-block-0123456789\n" * 128)
)


class SmokeFailure(RuntimeError):
    """A concise, user-facing smoke-test failure."""


@dataclass(frozen=True)
class FilePart:
    filename: str
    data: bytes
    content_type: str = "application/octet-stream"


@dataclass(frozen=True)
class Response:
    status: int
    headers: Message
    body: bytes

    def text(self) -> str:
        charset = self.headers.get_content_charset() or "utf-8"
        return self.body.decode(charset, errors="replace")


class Audit:
    def __init__(self) -> None:
        self.assertions = 0
        self.stages = 0

    def check(self, condition: object, message: str) -> None:
        self.assertions += 1
        if not condition:
            raise SmokeFailure(message)

    def stage(self, message: str) -> None:
        self.stages += 1
        print(f"[ok] {message}", flush=True)


class HttpClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )
        self._secrets: list[str] = []

    def add_secret(self, value: str) -> None:
        if value:
            self._secrets.append(value)

    def _scrub(self, value: str) -> str:
        for secret in self._secrets:
            value = value.replace(secret, "***")
        return value

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            raise SmokeFailure(f"internal test error: non-absolute path {path!r}")
        return self.base_url + path

    def request(
        self,
        path: str,
        *,
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        method: str | None = None,
    ) -> Response:
        request_headers = {
            "Accept": "*/*",
            "Connection": "close",
            "User-Agent": "zupt-web-live-smoke/1",
        }
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(
            self._url(path), data=data, headers=request_headers, method=method
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as raw:
                return Response(raw.status, raw.headers, raw.read())
        except urllib.error.HTTPError as exc:
            body = exc.read(4096).decode("utf-8", errors="replace")
            excerpt = self._scrub(" ".join(body.split()))[:500]
            raise SmokeFailure(
                f"{request.method} {path} returned HTTP {exc.code}: {excerpt}"
            ) from exc
        except urllib.error.URLError as exc:
            raise SmokeFailure(
                f"cannot reach {self._url(path)}: {self._scrub(str(exc.reason))}"
            ) from exc
        except TimeoutError as exc:
            raise SmokeFailure(
                f"{request.method} {path} exceeded the {self.timeout:g}s timeout"
            ) from exc

    def get(self, path: str) -> Response:
        return self.request(path, method="GET")

    def post_form(self, path: str, fields: Mapping[str, str]) -> Response:
        body = urllib.parse.urlencode(fields).encode("utf-8")
        return self.request(
            path,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

    def post_multipart(
        self,
        path: str,
        fields: Mapping[str, str],
        files: Mapping[str, FilePart],
    ) -> Response:
        boundary = "----zupt-web-smoke-" + secrets.token_hex(16)
        body = encode_multipart(boundary, fields, files)
        return self.request(
            path,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )


def _quoted_header_value(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise SmokeFailure("internal test error: newline in multipart header value")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def encode_multipart(
    boundary: str,
    fields: Mapping[str, str],
    files: Mapping[str, FilePart],
) -> bytes:
    marker = boundary.encode("ascii")
    chunks: list[bytes] = []
    for name, value in fields.items():
        safe_name = _quoted_header_value(name)
        chunks.extend(
            (
                b"--" + marker + b"\r\n",
                f'Content-Disposition: form-data; name="{safe_name}"\r\n'.encode(
                    "ascii"
                ),
                b"Content-Type: text/plain; charset=utf-8\r\n\r\n",
                value.encode("utf-8"),
                b"\r\n",
            )
        )
    for name, part in files.items():
        safe_name = _quoted_header_value(name)
        safe_filename = _quoted_header_value(part.filename)
        safe_content_type = _quoted_header_value(part.content_type)
        chunks.extend(
            (
                b"--" + marker + b"\r\n",
                (
                    f'Content-Disposition: form-data; name="{safe_name}"; '
                    f'filename="{safe_filename}"\r\n'
                ).encode("ascii"),
                f"Content-Type: {safe_content_type}\r\n\r\n".encode("ascii"),
                part.data,
                b"\r\n",
            )
        )
    chunks.append(b"--" + marker + b"--\r\n")
    return b"".join(chunks)


def success_page(audit: Audit, response: Response, operation: str) -> str:
    audit.check(response.status == 200, f"{operation} did not return HTTP 200")
    body = response.text()
    audit.check("<title>Success" in body, f"{operation} returned an error page")
    audit.check("<title>Error" not in body, f"{operation} returned an error page")
    return body


def attachment(audit: Audit, response: Response, operation: str) -> bytes:
    audit.check(response.status == 200, f"{operation} did not return HTTP 200")
    disposition = response.headers.get("Content-Disposition", "")
    audit.check(
        disposition.lower().startswith("attachment;"),
        f"{operation} did not return a downloadable attachment",
    )
    audit.check(bool(response.body), f"{operation} returned an empty attachment")
    audit.check(
        not response.body.lstrip().lower().startswith(b"<!doctype html"),
        f"{operation} returned HTML instead of an attachment",
    )
    return response.body


def csrf_from_index(audit: Audit, client: HttpClient, body: str) -> str:
    match = re.search(
        r'name=["\']csrf_token["\'][^>]*value=["\']([0-9a-f]{64})["\']', body
    )
    audit.check(match is not None, "index did not contain a valid CSRF token")
    assert match is not None
    token = html.unescape(match.group(1))
    cookie_values = [cookie.value for cookie in client.cookies if cookie.name == "csrf_token"]
    audit.check(len(cookie_values) == 1, "server did not set exactly one CSRF cookie")
    audit.check(cookie_values[0] == token, "CSRF form token and cookie do not match")
    return token


def generate_keypair(
    audit: Audit, client: HttpClient, csrf: str, endpoint: str, kind: str
) -> tuple[bytes, bytes]:
    page = client.post_form(endpoint, {"csrf_token": csrf})
    audit.check(page.status == 200, f"{kind} key generation did not return HTTP 200")
    body = page.text()
    audit.check("Keypair Generated" in body, f"{kind} key generation failed")
    audit.check("<title>Error" not in body, f"{kind} key generation returned an error")

    private_match = re.search(
        r'href=["\'](/download-key/[0-9a-f]+/private)["\']', body
    )
    public_match = re.search(
        r'href=["\'](/download-key/[0-9a-f]+/public)["\']', body
    )
    audit.check(private_match is not None, f"{kind} private-key link is missing")
    audit.check(public_match is not None, f"{kind} public-key link is missing")
    assert private_match is not None and public_match is not None
    private_path = html.unescape(private_match.group(1))
    public_path = html.unescape(public_match.group(1))
    audit.check(
        private_path.rsplit("/", 1)[0] == public_path.rsplit("/", 1)[0],
        f"{kind} key links refer to different jobs",
    )

    private_response = client.get(private_path)
    public_response = client.get(public_path)
    private_key = attachment(audit, private_response, f"{kind} private-key download")
    public_key = attachment(audit, public_response, f"{kind} public-key download")
    audit.check(private_key != public_key, f"{kind} public and private keys are identical")
    audit.check(
        "zupt_private.key" in private_response.headers.get("Content-Disposition", ""),
        f"{kind} private key has a stale download name",
    )
    audit.check(
        "zupt_public.key" in public_response.headers.get("Content-Disposition", ""),
        f"{kind} public key has a stale download name",
    )
    return public_key, private_key


def credential_parts(
    mode: str, keypairs: Mapping[str, tuple[bytes, bytes]]
) -> tuple[dict[str, str], dict[str, FilePart], dict[str, FilePart]]:
    fields: dict[str, str] = {}
    compress_files: dict[str, FilePart] = {}
    read_files: dict[str, FilePart] = {}
    if mode == "password":
        fields["password"] = PASSWORD
    elif mode == "hybrid":
        public_key, private_key = keypairs["hybrid"]
        compress_files["pq_key"] = FilePart("zupt_public.key", public_key)
        read_files["pq_key"] = FilePart("zupt_private.key", private_key)
    elif mode == "pq-only":
        public_key, private_key = keypairs["pq-only"]
        compress_files["pq_only_key"] = FilePart("zupt_public.key", public_key)
        read_files["pq_only_key"] = FilePart("zupt_private.key", private_key)
    elif mode != "plain":
        raise SmokeFailure(f"internal test error: unknown credential mode {mode!r}")
    return fields, compress_files, read_files


def round_trip(
    audit: Audit,
    client: HttpClient,
    csrf: str,
    keypairs: Mapping[str, tuple[bytes, bytes]],
    *,
    mode: str,
    codec: str,
    level: str,
) -> None:
    credential_fields, encrypt_files, decrypt_files = credential_parts(mode, keypairs)
    source_name = f"{'-' if mode == 'plain' else ''}live-{mode}.bin"

    compress_fields = {
        "csrf_token": csrf,
        "codec": codec,
        "level": level,
        **credential_fields,
    }
    compress_files = {
        "file": FilePart(source_name, PAYLOAD),
        **encrypt_files,
    }
    archive_response = client.post_multipart(
        "/compress", compress_fields, compress_files
    )
    archive = attachment(audit, archive_response, f"{mode} compression")
    audit.check(archive != PAYLOAD, f"{mode} compression returned the input unchanged")
    audit.check(
        source_name + ".zupt"
        in archive_response.headers.get("Content-Disposition", ""),
        f"{mode} archive has an unexpected download name",
    )

    archive_part = FilePart(source_name + ".zupt", archive)
    info_response = client.post_multipart(
        "/info", {"csrf_token": csrf}, {"archive": archive_part}
    )
    info_body = success_page(audit, info_response, f"{mode} archive info")
    audit.check("Format" in info_body or "format" in info_body,
                f"{mode} archive info did not report format metadata")

    verify_fields = {"csrf_token": csrf, **credential_fields}
    verify_response = client.post_multipart(
        "/test-archive",
        verify_fields,
        {"archive": archive_part, **decrypt_files},
    )
    success_page(audit, verify_response, f"{mode} archive verification")

    extract_response = client.post_multipart(
        "/extract",
        verify_fields,
        {"archive": archive_part, **decrypt_files},
    )
    extracted = attachment(audit, extract_response, f"{mode} extraction")
    audit.check(extracted == PAYLOAD, f"{mode} extraction did not reproduce input bytes")
    audit.check(
        source_name in extract_response.headers.get("Content-Disposition", ""),
        f"{mode} extraction has an unexpected download name",
    )


def run(base_url: str, timeout: float, expected_version: str) -> Audit:
    audit = Audit()
    client = HttpClient(base_url, timeout)
    client.add_secret(PASSWORD)

    health = client.get("/healthz")
    audit.check(health.status == 200, "health probe did not return HTTP 200")
    try:
        health_json = json.loads(health.body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SmokeFailure("health probe did not return valid JSON") from exc
    audit.check(health_json.get("ok") is True, "health probe reports not-ok")
    audit.check(health_json.get("service") == "zupt-web", "health service name is stale")
    audit.check(
        health_json.get("version") == expected_version,
        f"health version is not {expected_version}",
    )
    for header in (
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
    ):
        audit.check(bool(health.headers.get(header)), f"health response is missing {header}")

    version = client.get("/version")
    audit.check(version.status == 200, "version endpoint did not return HTTP 200")
    try:
        version_json = json.loads(version.body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SmokeFailure("version endpoint did not return valid JSON") from exc
    audit.check(version_json.get("ok") is True, "version endpoint reports not-ok")
    audit.check(
        expected_version in str(version_json.get("version", "")),
        f"CLI version does not contain {expected_version}",
    )

    index = client.get("/")
    audit.check(index.status == 200, "index did not return HTTP 200")
    index_body = index.text()
    audit.check("ZUPT CLI" in index_body, "index is missing current ZUPT branding")
    audit.check(expected_version in index_body, "index is missing the expected version")
    audit.check('action="/keygen"' in index_body, "hybrid key form is missing")
    audit.check('action="/keygen-pqonly"' in index_body, "PQ-only key form is missing")
    audit.check("/keygen-sdk" not in index_body, "retired SDK key form is still exposed")
    csrf = csrf_from_index(audit, client, index_body)
    audit.stage("health, version, security headers, CSRF, and current UI")

    hybrid_keys = generate_keypair(audit, client, csrf, "/keygen", "hybrid")
    pq_only_keys = generate_keypair(
        audit, client, csrf, "/keygen-pqonly", "PQ-only"
    )
    keypairs = {"hybrid": hybrid_keys, "pq-only": pq_only_keys}
    audit.stage("hybrid and full-PQ key generation plus key downloads")

    matrix = (
        ("plain", "lzhp", "1"),
        ("password", "store", "5"),
        ("hybrid", "vv", "9"),
        ("pq-only", "auto", "5"),
    )
    for mode, codec, level in matrix:
        round_trip(
            audit,
            client,
            csrf,
            keypairs,
            mode=mode,
            codec=codec,
            level=level,
        )
        audit.stage(
            f"{mode} compress/info/verify/extract round trip "
            f"(codec={codec}, level={level})"
        )

    rejection = client.post_multipart(
        "/compress",
        {
            "csrf_token": csrf,
            "codec": "auto",
            "level": "5",
            "solid": "on",
            "dedup": "on",
        },
        {"file": FilePart("invalid-combination.bin", PAYLOAD)},
    )
    audit.check(rejection.status == 200, "solid+dedup rejection did not return HTTP 200")
    rejection_body = rejection.text()
    audit.check("<title>Error" in rejection_body, "solid+dedup was not rejected")
    audit.check(
        "Solid mode and block dedup cannot be combined" in rejection_body,
        "solid+dedup rejection did not explain the conflict",
    )
    audit.stage("solid plus dedup is rejected explicitly")
    return audit


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run stdlib-only live HTTP checks against ZUPT Web."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ZUPT_WEB_URL", DEFAULT_URL),
        help=f"running service URL (default: $ZUPT_WEB_URL or {DEFAULT_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=700.0,
        help="per-request timeout in seconds (default: 700)",
    )
    parser.add_argument(
        "--expected-version",
        default=DEFAULT_VERSION,
        help=f"expected app/CLI version (default: {DEFAULT_VERSION})",
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    parsed = urllib.parse.urlsplit(args.base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        parser.error("--base-url must be an absolute HTTP(S) URL")
    if parsed.query or parsed.fragment:
        parser.error("--base-url must not include a query or fragment")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    started = time.monotonic()
    try:
        audit = run(args.base_url, args.timeout, args.expected_version)
    except (SmokeFailure, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    elapsed = time.monotonic() - started
    print(
        f"PASS: {audit.stages} stages, {audit.assertions} assertions, "
        f"4 credential-mode round trips in {elapsed:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
