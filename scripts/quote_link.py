#!/usr/bin/env python3
"""AI 2026.10.24 - Destination-text verification and deterministic VDL encoding."""

import argparse
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import sys
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urldefrag, urlsplit, urlunsplit
from urllib.request import HTTPHandler, HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_BYTES = 4 * 1024 * 1024
BLOCKS = set("address article aside blockquote br dd div dl dt fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header hr li main nav ol p pre section table tbody td th thead tr ul".split())
SKIP = set("head script style template noscript iframe object svg canvas textarea select".split())
VOID = set("area base br col embed hr img input link meta param source track wbr".split())


def normalize(value):
    return re.sub(r"\s+", " ", value).strip()


class DestinationText(HTMLParser):
    """Conservative HTML extraction; deliberately not a rendering engine."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.parts, self.blocks = [], [], []

    def flush(self):
        text = normalize("".join(self.parts))
        if text:
            self.blocks.append(text)
        self.parts = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        parent_hidden = bool(self.stack and self.stack[-1][1])
        hidden = parent_hidden or tag in SKIP or "hidden" in attrs or "inert" in attrs
        hidden = hidden or attrs.get("aria-hidden", "").lower() == "true"
        hidden = hidden or bool(re.search(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important)?\s*(?:;|$)", attrs.get("style", ""), re.I))
        if not hidden and tag in BLOCKS:
            self.flush()
        if tag not in VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in BLOCKS and not (self.stack and self.stack[-1][1]):
            self.flush()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not self.stack or not self.stack[-1][1]:
            self.parts.append(data)


# AI 2026.10.24 - Validate the actual addresses dialed, not just a prior DNS answer.
def public_addresses(host, port):
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise ValueError("Private, loopback, and reserved network destinations are not supported.")
    return addresses


def public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use a public HTTP(S) destination URL without credentials.")
    return public_addresses(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))


def public_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    last_error = None
    for family, kind, protocol, _, sockaddr in public_addresses(*address):
        connection = socket.socket(family, kind, protocol)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                connection.settimeout(timeout)
            if source_address:
                connection.bind(source_address)
            # sockaddr is already numeric: connect cannot perform another DNS lookup.
            connection.connect(sockaddr)
            return connection
        except OSError as error:
            last_error = error
            connection.close()
    raise last_error or OSError("No public destination address was available.")


class PublicHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = public_connection


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = public_connection


class PublicHTTPHandler(HTTPHandler):
    def http_open(self, request):
        return self.do_open(PublicHTTPConnection, request)


class PublicHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        # Keep the original hostname for TLS SNI and certificate verification.
        return self.do_open(PublicHTTPSConnection, request, context=self._context)


class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        public_url(newurl)
        if urlsplit(request.full_url).scheme == "https" and urlsplit(newurl).scheme != "https":
            raise ValueError("Refusing an HTTPS-to-HTTP redirect.")
        if getattr(request, "vdl_redirects", 0) >= 5:
            raise ValueError("Too many redirects.")
        redirected = super().redirect_request(request, fp, code, message, headers, newurl)
        if redirected:
            redirected.vdl_redirects = getattr(request, "vdl_redirects", 0) + 1
        return redirected


def fetch_html(url):
    public_url(url)
    request = Request(urldefrag(url)[0], headers={"User-Agent": "ShowQuoteInContext/0.1", "Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "identity"})
    # Previously build_opener(PublicRedirects()) used a second unchecked DNS lookup.
    # Disable environment proxies so they cannot bypass the validated socket path.
    opener = build_opener(ProxyHandler({}), PublicRedirects(), PublicHTTPHandler(),
                          PublicHTTPSHandler(context=ssl.create_default_context()))
    with opener.open(request, timeout=20) as response:
        if response.headers.get_content_type() not in ("text/html", "application/xhtml+xml"):
            raise ValueError("Destination is not HTML; PDF/audio/other formats need a different verifier.")
        if "force-load-at-top" in response.headers.get("Document-Policy", "").lower():
            raise ValueError("Destination explicitly disables text-fragment navigation.")
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Destination HTML exceeds the verification size limit.")
        charset = response.headers.get_content_charset()
        if not charset:
            match = re.search(br"<meta\b[^>]*charset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)", data[:4096], re.I)
            charset = match[1].decode("ascii") if match else "utf-8"
        html = data.decode(charset, errors="strict")
        final = urlsplit(response.url)
        anchor = urlsplit(url).fragment.split(":~:", 1)[0]
        return html, urlunsplit((final.scheme, final.netloc, final.path, final.query, anchor))


def word_character(character):
    return character.isalnum() or character == "_" or unicodedata.category(character).startswith("M")


def occurrences(text, needle, spans=None):
    if not needle:
        return []
    result = []
    # Lookahead retains overlapping occurrences rather than hiding ambiguity.
    for match in re.finditer("(?=" + re.escape(needle) + ")", text, re.I):
        start, end = match.start(), match.start() + len(needle)
        if start and word_character(needle[0]) and word_character(text[start - 1]):
            continue
        if end < len(text) and word_character(needle[-1]) and word_character(text[end]):
            continue
        if spans is None or any(left <= start and end <= right for left, right in spans):
            result.append((start, end))
    return result


def context_matches(text, start, end, prefix, suffix, spans):
    before, after = text[:start].rstrip(), text[end:].lstrip()
    if prefix and (len(before) - len(prefix), len(before)) not in occurrences(text, prefix, spans):
        return False
    suffix_start = len(text) - len(after)
    if suffix and (suffix_start, suffix_start + len(suffix)) not in occurrences(text, suffix, spans):
        return False
    return True


def encode_term(value):
    # urllib leaves hyphens unescaped even with safe=''; directive syntax cannot.
    return quote(value, safe="").replace("-", "%2D")


def verify_html(html, url, quotation, prefix="", suffix="", live=False):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an HTTP(S) source URL without credentials.")
    wanted, prefix, suffix = map(normalize, (quotation, prefix, suffix))
    if not wanted or len(wanted) > 16000:
        raise ValueError("Provide a nonempty exact quotation of at most 16000 characters.")
    parser = DestinationText()
    parser.feed(html)
    parser.close()
    parser.flush()
    text = " ".join(parser.blocks)
    spans, offset = [], 0
    for block in parser.blocks:
        spans.append((offset, offset + len(block)))
        offset += len(block) + 1
    candidates = [pair for pair in occurrences(text, wanted) if context_matches(text, *pair, prefix, suffix, spans)]
    base = {"source_url": url, "quote": quotation, "verified": False, "verification_scope": "server-returned HTML text; no JavaScript or CSS rendering", "highlight_tested": False}
    if len(candidates) != 1:
        return dict(base, status="not_verified", reason="Quote not found in destination text." if not candidates else "Quote is ambiguous; provide immediately adjacent prefix/suffix from the source.", matches=len(candidates), candidates=[{"before": text[max(0, start-140):start], "passage": text[start:end], "after": text[end:end+140]} for start, end in candidates[:5]])
    start, end = candidates[0]
    first = next(span for span in spans if span[0] <= start < span[1])
    last = next(span for span in spans if span[0] < end <= span[1])
    text_start = text[start:min(end, first[1])]
    text_end = text[last[0]:end] if first != last else ""
    # Independently check that the emitted range selects the whole intended quote.
    selector_matches = []
    for left, right in occurrences(text, text_start, spans):
        if text_end:
            ends = [pair for pair in occurrences(text, text_end, spans) if pair[0] >= right]
            if not ends:
                continue
            right = ends[0][1]
        if context_matches(text, left, right, prefix, suffix, spans):
            selector_matches.append((left, right))
    if selector_matches != [(start, end)]:
        return dict(base, status="not_verified", reason="The range selector is ambiguous or ends before the intended passage; add source context or select a shorter exact quotation.", matches=len(selector_matches))
    directive = (encode_term(prefix) + "-," if prefix else "") + encode_term(text_start)
    if text_end:
        directive += "," + encode_term(text_end)
    if suffix:
        directive += ",-" + encode_term(suffix)
    anchor = parsed.fragment.split(":~:", 1)[0]
    vdl = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, anchor + ":~:text=" + directive))
    return dict(base, status="destination_text_verified" if live else "fixture_text_verified", verified=live, vdl=vdl, matched_text=text[start:end], before=text[max(0,start-140):start], after=text[end:end+140], selector={"prefix":prefix, "start":text_start, "end":text_end, "suffix":suffix}, checked_at=datetime.now(timezone.utc).isoformat(), html_sha256=hashlib.sha256(html.encode("utf-8")).hexdigest())


def main():
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--url", required=True)
    arguments.add_argument("--quote", required=True)
    arguments.add_argument("--prefix", default="")
    arguments.add_argument("--suffix", default="")
    arguments.add_argument("--html-file", type=Path, help="Offline fixture only; never marked destination-verified")
    args = arguments.parse_args()
    try:
        if args.html_file:
            if args.html_file.stat().st_size > MAX_BYTES:
                raise ValueError("Fixture exceeds the verification size limit.")
            html, url = args.html_file.read_text(encoding="utf-8"), args.url
        else:
            html, url = fetch_html(args.url)
        result = verify_html(html, url, args.quote, args.prefix, args.suffix, live=not args.html_file)
    except Exception as error:
        result = {"status":"not_verified", "verified":False, "source_url":args.url, "reason":str(error)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if "vdl" in result else 2


if __name__ == "__main__":
    sys.exit(main())
