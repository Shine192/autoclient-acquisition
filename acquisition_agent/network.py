"""Bounded HTTP requests. Research fetches have no credentials and reject local URLs."""
import ipaddress
import json
import socket
from html.parser import HTMLParser
from urllib import error, parse, request


def public_url(url):
    p = parse.urlsplit(url)
    if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password or p.port not in (None, 80, 443):
        raise ValueError("Only public HTTP(S) research pages are supported")
    addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Local/private research destinations are blocked")
    return url


class CheckedRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("API redirect rejected")


def fetch_text(url):
    public_url(url)
    req = request.Request(url, headers={"User-Agent": "ShineAcquisitionResearch/0.1 (+manual-review)", "Accept": "text/html,application/rss+xml,application/xml,text/plain"})
    try:
        with request.build_opener(CheckedRedirect()).open(req, timeout=25) as response:
            media = response.headers.get_content_type()
            if media not in ("text/html", "text/plain", "application/rss+xml", "application/xml", "text/xml", "application/atom+xml"):
                raise ValueError("Unsupported research document type")
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError("Research page exceeds 2 MB")
            return body.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except error.HTTPError as exc:
        raise ValueError("Research HTTP " + str(exc.code)) from None


def api_json(url, method="POST", payload=None, headers=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = request.Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})}, method=method)
    try:
        with request.build_opener(NoRedirect()).open(req, timeout=60) as response:
            raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                raise ValueError("API response too large")
            return json.loads(raw)
    except error.HTTPError as exc:
        # Never print provider responses that could echo keys or full personal payloads.
        raise ValueError("API request failed with HTTP " + str(exc.code)) from None
    except error.URLError:
        raise ValueError("API request failed; check connection") from None


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def plain_text(html):
    parser = VisibleText()
    parser.feed(html)
    return "\n".join(parser.parts)[:30000]
