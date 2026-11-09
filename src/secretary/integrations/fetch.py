"""Safe page fetcher for research jobs (plan §14.2).

Rules: HTTP(S) only; blocks private/loopback/link-local IPs after DNS
resolution, on every redirect (defends against DNS rebinding); 1 MB cap;
10 s timeout; text/html and text/plain only; custom user agent; max 3
redirects. Extracts the main text with trafilatura and truncates to about
1,500 tokens per source.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
import trafilatura

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_CONTENT_TYPES = {"text/html", "text/plain"}
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 10.0
MAX_BYTES = 1_048_576  # 1 MB
TOKEN_CAP_CHARS = 6000  # ~1,500 tokens at ~4 chars/token
USER_AGENT = "Secretary/0.1.0 (research fetcher; +https://example.local/secretary)"


class FetchError(Exception):
    """Raised when a URL cannot be safely fetched or extracted."""


def _host_is_allowed(hostname: str | None) -> bool:
    """True if every resolved address is public and non-link-local."""
    if not hostname:
        return False
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
        ):
            return False
    return True


def fetch_url(url: str) -> dict:
    """Fetch *url* safely and return {"url", "text"} with the extracted main text."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.hostname:
        raise FetchError("only http/https URLs with a host are allowed")
    if not _host_is_allowed(parsed.hostname):
        raise FetchError(f"host {parsed.hostname} is not allowed")

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html, text/plain"}
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True, max_redirects=MAX_REDIRECTS) as client, \
             client.stream("GET", url, headers=headers) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise FetchError(f"fetch failed: {exc}") from exc
                # Check every redirect target for rebinding to a private address.
                for response_or_history in [response, *response.history]:
                    hurl = urlparse(str(response_or_history.url))
                    if not _host_is_allowed(hurl.hostname):
                        raise FetchError(f"redirect to {hurl.hostname} is not allowed")
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if content_type not in ALLOWED_CONTENT_TYPES:
                    raise FetchError(f"content type {content_type!r} is not allowed")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise FetchError("response exceeds the 1 MB cap")
                    chunks.append(chunk)
                body = b"".join(chunks)
    except httpx.HTTPError as exc:
        raise FetchError(f"fetch failed: {exc}") from exc

    html = body.decode("utf-8", errors="replace")
    text = trafilatura.extract(html, include_links=False, include_formatting=False) or ""
    text = " ".join(text.split())
    if len(text) > TOKEN_CAP_CHARS:
        text = text[:TOKEN_CAP_CHARS] + "…"
    return {"url": str(response.url), "text": text}
