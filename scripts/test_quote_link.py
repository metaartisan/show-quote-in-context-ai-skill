#!/usr/bin/env python3
"""AI 2026.10.24 - Local verification, encoding, network boundaries and CLI tests."""

import contextlib
import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import unquote, urlsplit
from urllib.request import Request

import quote_link as q

URL = "https://example.org/report?edition=2#findings:~:text=old"


class LinkTests(unittest.TestCase):
    def verify(self, html, quote, **kwargs):
        return q.verify_html(html, URL, quote, **kwargs)

    def test_exact_and_anchor(self):
        result = self.verify("<p>Read the exact words here.</p>", "the exact words")
        self.assertEqual(result["status"], "fixture_text_verified")
        self.assertFalse(result["verified"])
        self.assertEqual(result["vdl"], "https://example.org/report?edition=2#findings:~:text=the%20exact%20words")
        self.assertFalse(result["highlight_tested"])

    def test_reserved_characters_and_unicode(self):
        quote = "Café 日本語 - comma, ampersand & 100% #? / 'quoted'"
        result = self.verify("<p>Café 日本語 - comma, ampersand &amp; 100% #? / 'quoted'</p>", quote)
        encoded = urlsplit(result["vdl"]).fragment.split("text=", 1)[1]
        self.assertEqual(unquote(encoded), quote)
        self.assertIn("%2D", encoded)
        self.assertNotIn(",", encoded)
        self.assertNotIn("&", encoded)
        self.assertNotIn("'", encoded)

    def test_whitespace_and_inline_markup(self):
        result = self.verify("<p>One <em>exact</em>\n quote&nbsp;here.</p>", "One exact quote here.")
        self.assertIn("vdl", result)

    def test_hidden_content_is_not_evidence(self):
        for hidden in ["<script>hidden quote</script>", "<style>hidden quote</style>",
                       "<template>hidden quote</template>", "<head><title>hidden quote</title></head>",
                       '<div hidden>hidden quote</div>', '<div style="display: none">hidden quote</div>',
                       '<div aria-hidden="true">hidden quote</div>', '<iframe>hidden quote</iframe>',
                       '<!-- hidden quote -->']:
            with self.subTest(hidden=hidden):
                self.assertNotIn("vdl", self.verify(hidden + "<p>Different words.</p>", "hidden quote"))

    def test_hidden_inline_does_not_invent_spaces(self):
        result = self.verify('<p>one<span hidden>skip</span>two</p>', "onetwo")
        self.assertIn("vdl", result)
        self.assertNotIn("vdl", self.verify('<p>one<span hidden>skip</span>two</p>', "one two"))

    def test_missing_quote(self):
        result = self.verify("<p>Original statement.</p>", "A paraphrased statement.")
        self.assertNotIn("vdl", result)
        self.assertEqual(result["matches"], 0)

    def test_ambiguous_quote(self):
        result = self.verify("<p>First: same quote.</p><p>Second: same quote.</p>", "same quote.")
        self.assertNotIn("vdl", result)
        self.assertEqual(result["matches"], 2)
        self.assertEqual(len(result["candidates"]), 2)

    def test_prefix_disambiguates(self):
        result = self.verify("<p>First: same quote.</p><p>Second: same quote.</p>", "same quote.", prefix="Second:")
        self.assertIn("text=Second%3A-,same%20quote.", result["vdl"])
        self.assertEqual(result["matched_text"], "same quote.")

    def test_suffix_disambiguates(self):
        result = self.verify("<p>same quote first.</p><p>same quote second.</p>", "same quote", suffix="second.")
        self.assertTrue(result["vdl"].endswith("same%20quote,-second."))

    def test_invented_context_fails(self):
        self.assertNotIn("vdl", self.verify("<p>Original statement.</p>", "Original statement.", prefix="Invented"))

    def test_cross_block_range(self):
        result = self.verify("<p>First passage.</p><p>Second passage.</p>", "First passage. Second passage.")
        self.assertTrue(result["vdl"].endswith("text=First%20passage.,Second%20passage."))
        self.assertEqual(result["selector"]["end"], "Second passage.")

    def test_range_ending_too_early_is_rejected(self):
        result = self.verify("<p>Start.</p><p>End.</p><p>Middle.</p><p>End.</p>", "Start. End. Middle. End.")
        self.assertNotIn("vdl", result)
        self.assertIn("ends before", result["reason"])

    def test_long_quotes_are_not_truncated(self):
        quote = "A long source passage " * 60 + "with a unique ending."
        result = self.verify("<p>" + quote + "</p>", quote)
        self.assertEqual(unquote(result["vdl"].split("text=", 1)[1]), quote)

    def test_subword_is_not_a_match(self):
        self.assertNotIn("vdl", self.verify("<p>concatenate</p>", "cat"))

    def test_no_smart_quote_or_punctuation_fabrication(self):
        self.assertNotIn("vdl", self.verify("<p>It’s exact.</p>", "It's exact."))

    def test_invalid_inputs(self):
        for url in ["file:///tmp/a", "javascript:alert(1)", "https://user:secret@example.org/"]:
            with self.assertRaises(ValueError):
                q.verify_html("<p>quote</p>", url, "quote")
        for quote in ["", " " * 4, "a" * 16001]:
            with self.assertRaises(ValueError):
                self.verify("<p>quote</p>", quote)

    def test_cli_fixture_never_claims_live_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "page.html"
            source.write_text("<p>Exact quote.</p>", encoding="utf-8")
            output = io.StringIO()
            with patch("sys.argv", ["quote_link.py", "--url", URL, "--quote", "Exact quote.", "--html-file", str(source)]), contextlib.redirect_stdout(output):
                self.assertEqual(q.main(), 0)
            result = json.loads(output.getvalue())
            self.assertFalse(result["verified"])
            self.assertEqual(result["status"], "fixture_text_verified")


class NetworkTests(unittest.TestCase):
    def test_numeric_connection_uses_validated_address(self):
        address = (q.socket.AF_INET, q.socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))
        connection = Mock()
        with patch.object(q.socket, "getaddrinfo", return_value=[address]) as resolve, patch.object(q.socket, "socket", return_value=connection):
            self.assertIs(q.public_connection(("example.org", 443), timeout=20), connection)
            resolve.assert_called_once_with("example.org", 443, type=q.socket.SOCK_STREAM)
            connection.connect.assert_called_once_with(("93.184.215.14", 443))

    def test_rebinding_between_precheck_and_dial_is_rejected(self):
        public = (q.socket.AF_INET, q.socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))
        private = (q.socket.AF_INET, q.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        with patch.object(q.socket, "getaddrinfo", side_effect=[[public], [private]]), patch.object(q.socket, "socket") as create:
            q.public_url("https://example.org")
            with self.assertRaises(ValueError):
                q.public_connection(("example.org", 443))
            create.assert_not_called()

    def test_mixed_dns_answers_fail_before_any_dial(self):
        addresses = [(q.socket.AF_INET, q.socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ["93.184.215.14", "192.168.1.1"]]
        with patch.object(q.socket, "getaddrinfo", return_value=addresses), patch.object(q.socket, "socket") as create:
            with self.assertRaises(ValueError):
                q.public_connection(("example.org", 443))
            create.assert_not_called()

    def test_failed_socket_is_closed(self):
        address = (q.socket.AF_INET, q.socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))
        connection = Mock()
        connection.connect.side_effect = OSError("Connection refused")
        with patch.object(q.socket, "getaddrinfo", return_value=[address]), patch.object(q.socket, "socket", return_value=connection):
            with self.assertRaises(OSError):
                q.public_connection(("example.org", 443))
            connection.close.assert_called_once()

    def test_https_preserves_hostname_and_certificate_checks(self):
        connection = q.PublicHTTPSConnection("example.org", timeout=20)
        self.assertIs(connection._create_connection, q.public_connection)
        self.assertEqual(connection.host, "example.org")
        self.assertTrue(connection._context.check_hostname)
        self.assertEqual(connection._context.verify_mode, q.ssl.CERT_REQUIRED)
        context = Mock()
        connection = q.PublicHTTPSConnection("example.org", context=context)
        with patch.object(q, "public_connection", return_value=Mock()):
            connection._create_connection = q.public_connection
            connection.connect()
        self.assertEqual(context.wrap_socket.call_args.kwargs["server_hostname"], "example.org")

    def test_fetch_disables_environment_proxies(self):
        with patch.object(q, "public_url"), patch.object(q, "build_opener") as builder:
            builder.return_value.open.return_value = self.response()
            q.fetch_html("https://example.org")
            handlers = builder.call_args.args
            proxy = next(handler for handler in handlers if isinstance(handler, q.ProxyHandler))
            self.assertEqual(proxy.proxies, {})
            self.assertTrue(any(isinstance(handler, q.PublicHTTPSHandler) for handler in handlers))

    def response(self, content=b"<p>Exact quote.</p>", content_type="text/html; charset=utf-8", final="https://example.org/final"):
        headers = Message()
        headers["Content-Type"] = content_type
        result = Mock(headers=headers, url=final)
        result.read.return_value = content
        result.__enter__ = Mock(return_value=result)
        result.__exit__ = Mock(return_value=False)
        return result

    def test_reject_private_and_mixed_dns(self):
        for address in ["127.0.0.1", "192.168.1.2", "169.254.169.254", "::1"]:
            with patch.object(q.socket, "getaddrinfo", return_value=[(None, None, None, None, (address, 80))]):
                with self.assertRaises(ValueError):
                    q.public_url("http://example.org/")

    def test_fresh_fetch_and_live_receipt(self):
        opener = Mock()
        opener.open.side_effect = [self.response(), self.response(b"<p>Changed quote.</p>")]
        with patch.object(q, "public_url"), patch.object(q, "build_opener", return_value=opener):
            html, url = q.fetch_html(URL)
            self.assertEqual(url, "https://example.org/final#findings")
            result = q.verify_html(html, url, "Exact quote.", live=True)
            self.assertEqual(result["status"], "destination_text_verified")
            self.assertTrue(result["verified"])
            self.assertIn("checked_at", result)
            self.assertEqual(len(result["html_sha256"]), 64)
            html, url = q.fetch_html(URL)
            self.assertNotIn("vdl", q.verify_html(html, url, "Exact quote.", live=True))
            self.assertEqual(opener.open.call_count, 2)

    def test_content_type_size_and_optout(self):
        optout = self.response()
        optout.headers["Document-Policy"] = "force-load-at-top"
        for response in [self.response(content_type="application/pdf"), self.response(b"x" * (q.MAX_BYTES + 1)), optout]:
            with patch.object(q, "public_url"), patch.object(q, "build_opener") as builder:
                builder.return_value.open.return_value = response
                with self.assertRaises(ValueError):
                    q.fetch_html("https://example.org/")

    def test_meta_charset(self):
        response = self.response('<meta charset="windows-1252"><p>Café.</p>'.encode("cp1252"), "text/html")
        with patch.object(q, "public_url"), patch.object(q, "build_opener") as builder:
            builder.return_value.open.return_value = response
            html, _ = q.fetch_html("https://example.org/")
            self.assertIn("Café", html)

    def test_redirect_safety(self):
        handler = q.PublicRedirects()
        with patch.object(q, "public_url"):
            with self.assertRaises(ValueError):
                handler.redirect_request(Request("https://example.org"), None, 302, "", {}, "http://example.org")
            request = Request("https://example.org")
            request.vdl_redirects = 5
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, "", {}, "https://example.org/other")


if __name__ == "__main__":
    unittest.main(verbosity=2)
