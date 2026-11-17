# SPDX-License-Identifier: AGPL-3.0-or-later
"""Network-free checks for the stdlib live HTTP smoke client."""

import io
import unittest
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from unittest import mock

import live_smoke


class TrackingBody(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.read_sizes = []

    def read(self, size: int | None = -1):
        self.read_sizes.append(size)
        return super().read(size)


class HttpClientTests(unittest.TestCase):
    def setUp(self):
        no_network = mock.patch(
            "socket.socket", side_effect=AssertionError("No network in unit tests")
        )
        no_network.start()
        self.addCleanup(no_network.stop)
        self.opener = mock.Mock()
        self.opener.addheaders = []
        with mock.patch.object(
            urllib.request, "build_opener", return_value=self.opener
        ):
            self.client = live_smoke.HttpClient("http://127.0.0.1:8181", timeout=3)

    def raw_response(self, code, body):
        stream = TrackingBody(body)
        return urllib.response.addinfourl(
            stream, Message(), self.client.base_url, code
        ), stream

    def http_error(self, code, body):
        stream = TrackingBody(body)
        return urllib.error.HTTPError(
            self.client.base_url, code, "error", Message(), stream
        ), stream

    def request_for_status(self, expected):
        if expected is None:
            return self.client.request("/")
        return self.client.request("/", expected_status=expected)

    def test_default_success_keeps_complete_attachment_and_closes_response(self):
        body = b"attachment" * 1000
        raw, stream = self.raw_response(200, body)
        self.opener.open.return_value = raw
        response = self.client.request("/")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, body)
        self.assertTrue(stream.closed)

    def test_expected_http_error_is_bounded_and_closed(self):
        error, stream = self.http_error(413, b"x" * 5000)
        self.opener.open.side_effect = error
        response = self.client.request("/", expected_status=413)
        self.assertEqual(response.status, 413)
        self.assertEqual(response.body, b"x" * 4096)
        self.assertEqual(stream.read_sizes, [4096])
        self.assertTrue(stream.closed)

    def test_unexpected_http_errors_remain_redacted_failures_and_close(self):
        secret = "synthetic-private-response-marker"
        self.client.add_secret(secret)
        for code, expected in ((413, None), (500, 413)):
            with self.subTest(code=code, expected=expected):
                error, stream = self.http_error(code, secret.encode() + b"x" * 5000)
                self.opener.open.side_effect = error
                with self.assertRaises(live_smoke.SmokeFailure) as raised:
                    self.request_for_status(expected)
                self.assertNotIn(secret, str(raised.exception))
                self.assertIn(f"HTTP {code}", str(raised.exception))
                self.assertEqual(stream.read_sizes, [4096])
                self.assertTrue(stream.closed)

    def test_normal_responses_must_match_expected_status_and_bound_error_body(self):
        for code, expected, accepted in (
            (201, None, False),
            (200, 413, False),
            (413, 413, True),
        ):
            with self.subTest(code=code, expected=expected):
                raw, stream = self.raw_response(code, b"x" * 5000)
                self.opener.open.return_value = raw
                if accepted:
                    response = self.request_for_status(expected)
                    self.assertEqual(response.status, expected)
                    self.assertEqual(len(response.body), 4096)
                else:
                    with self.assertRaises(live_smoke.SmokeFailure):
                        self.request_for_status(expected)
                self.assertTrue(stream.closed)

    def test_transport_errors_are_never_an_expected_http_status(self):
        secret = "synthetic-private-transport-marker"
        self.client.add_secret(secret)
        for error in (urllib.error.URLError(secret), TimeoutError(secret)):
            with self.subTest(error=type(error).__name__):
                self.opener.open.side_effect = error
                with self.assertRaises(live_smoke.SmokeFailure) as raised:
                    self.client.request("/", expected_status=413)
                self.assertNotIn(secret, str(raised.exception))

    def test_iterable_body_uses_stdlib_chunked_framing_without_network(self):
        chunks = iter((b"first", b"second"))
        handler = urllib.request.HTTPHandler()
        handler.add_parent(self.opener)
        raw, _stream = self.raw_response(200, b"ok")

        def prepared(request, *, timeout):
            self.assertEqual(timeout, 3)
            request = handler.do_request_(request)
            self.assertIs(request.data, chunks)
            self.assertEqual(request.get_header("Transfer-encoding"), "chunked")
            self.assertIsNone(request.get_header("Content-length"))
            return raw

        self.opener.open.side_effect = prepared
        self.assertEqual(
            self.client.request("/", data=chunks, method="POST").body, b"ok"
        )

    def test_form_budget_stage_sends_exact_body_as_bytes_and_two_chunks(self):
        csrf = "a" * 64
        audit = live_smoke.Audit()
        response = live_smoke.Response(413, Message(), b"bounded error")
        with (
            mock.patch.object(self.client, "request", return_value=response) as request,
            mock.patch("sys.stdout", new=io.StringIO()),
        ):
            live_smoke.check_urlencoded_form_budget(audit, self.client, csrf)
        self.assertEqual(request.call_count, 2)
        bodies = []
        for call in request.call_args_list:
            self.assertEqual(call.args, ("/",))
            self.assertEqual(call.kwargs["expected_status"], 413)
            self.assertEqual(call.kwargs["method"], "POST")
            self.assertEqual(
                call.kwargs["headers"]["Content-Type"],
                "application/x-www-form-urlencoded",
            )
            body = call.kwargs["data"]
            if isinstance(body, bytes):
                bodies.append(body)
            else:
                chunks = list(body)
                self.assertEqual(len(chunks), 2)
                self.assertTrue(
                    all(isinstance(chunk, bytes) and chunk for chunk in chunks)
                )
                bodies.append(b"".join(chunks))
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(len(bodies[0]), 500_001)
        self.assertTrue(bodies[0].startswith(f"csrf_token={csrf}&padding=".encode()))
        self.assertEqual(audit.stages, 1)

    def test_form_budget_stage_never_posts_to_non_loopback_service(self):
        self.client.base_url = "https://production.invalid"
        audit = live_smoke.Audit()
        output = io.StringIO()
        with (
            mock.patch.object(self.client, "request") as request,
            mock.patch("sys.stdout", new=output),
        ):
            live_smoke.check_urlencoded_form_budget(audit, self.client, "a" * 64)
        request.assert_not_called()
        self.assertIn("[NOT RUN]", output.getvalue())
        self.assertNotIn("[ok]", output.getvalue())
        self.assertEqual(audit.stages, 0)


if __name__ == "__main__":
    unittest.main()
