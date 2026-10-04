"""Bounded public documentation access through an application-owned broker.

HTTPcore's documented ``sni_hostname`` extension allows an IP-address request
with the approved hostname retained for TLS verification and the Host header.
Each hop uses a fresh transport: DNS is resolved once, every answer is checked,
and the connected peer is checked before a response body is consumed.

Transport contract: https://www.encode.io/httpcore/extensions/
Search contract: https://api-dashboard.search.brave.com/api-reference/web/search/get
"""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import ipaddress
import json
import math
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from lxml import etree, html
from pydantic import SecretStr

from general_agent.coding.http import tls_context


class DocumentationError(ValueError):
    """A denied, exhausted or unsuccessful public documentation operation."""


@dataclass(frozen=True)
class DocumentationLimits:
    deadline_seconds: float = 30.0
    max_pages: int = 6
    max_queries: int = 2
    max_requests: int = 12
    max_redirects: int = 3
    max_response_bytes: int = 512 * 1024
    max_total_bytes: int = 2 * 1024 * 1024
    max_text_chars: int = 50_000

    def __post_init__(self):
        if (isinstance(self.deadline_seconds, bool)
                or not isinstance(self.deadline_seconds, (int, float))
                or not math.isfinite(self.deadline_seconds) or self.deadline_seconds <= 0):
            raise ValueError("Documentation deadline must be finite and positive.")
        for name in ("max_pages", "max_queries", "max_requests", "max_response_bytes",
                     "max_total_bytes", "max_text_chars"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer.")
        if type(self.max_redirects) is not int or self.max_redirects < 0:
            raise ValueError("max_redirects must be a nonnegative integer.")


@dataclass(frozen=True)
class BraveSearchConfig:
    api_key: SecretStr

    def __post_init__(self):
        if not isinstance(self.api_key, SecretStr):
            raise ValueError("Search credentials must use SecretStr.")
        key = self.api_key.get_secret_value()
        if not key or len(key) > 1024 or not key.isascii() or _controls(key):
            raise ValueError("Invalid search credential.")


_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
# Reject special-purpose protocol/relay blocks regardless of Python's changing
# is_global classification. These are not public documentation destinations.
_SPECIAL_V4 = (ipaddress.ip_network("192.0.0.0/24"), ipaddress.ip_network("192.88.99.0/24"))
_DOCUMENTATION_V6 = ipaddress.ip_network("3fff::/20")
_REDIRECTS = {301, 302, 303, 307, 308}


def _controls(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def approved_domain(value: str) -> str:
    """Normalize one explicit DNS hostname; wildcards, URLs and IPs are denied."""
    if not isinstance(value, str) or not value or value != value.strip() or _controls(value):
        raise DocumentationError("An approved domain must be a DNS hostname.")
    if any(char in value for char in "/\\:@?#[]%") or value.endswith("."):
        raise DocumentationError("An approved domain must be a DNS hostname.")
    try:
        domain = httpx.URL(f"https://{value}/").raw_host.decode("ascii").lower()
    except (ValueError, UnicodeError, httpx.InvalidURL) as exc:
        raise DocumentationError("Invalid approved domain.") from exc
    labels = domain.split(".")
    if len(domain) > 253 or len(labels) < 2 or any(not _LABEL.fullmatch(label) for label in labels):
        raise DocumentationError("Invalid approved domain.")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        return domain
    raise DocumentationError("IP-address domains are not allowed.")


def _public_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise DocumentationError("DNS returned an invalid address.") from exc
    if isinstance(address, ipaddress.IPv6Address):
        if address.scope_id or address.sixtofour or address.teredo or any(address in net for net in _NAT64):
            raise DocumentationError("IPv6 transition and scoped addresses are not allowed.")
        if address.ipv4_mapped:
            return _public_ip(str(address.ipv4_mapped))
        if address.is_site_local:
            raise DocumentationError("Nonpublic addresses are not allowed.")
        if address in _DOCUMENTATION_V6:
            raise DocumentationError("Documentation-only addresses are not allowed.")
    elif any(address in net for net in _SPECIAL_V4):
        raise DocumentationError("Special-purpose addresses are not allowed.")
    if (not address.is_global or address.is_private or address.is_loopback
            or address.is_link_local or address.is_reserved or address.is_multicast
            or address.is_unspecified):
        raise DocumentationError("Nonpublic addresses are not allowed.")
    return str(address)


def _url(value: str, domains: frozenset[str]) -> httpx.URL:
    if (not isinstance(value, str) or not value or len(value) > 8192
            or value != value.strip() or _controls(value)):
        raise DocumentationError("Invalid documentation URL.")
    try:
        parts = urlsplit(value)
        parsed = httpx.URL(value)
        host = approved_domain(parsed.raw_host.decode("ascii"))
        if "@" in parts.netloc or parsed.userinfo:
            raise DocumentationError("URL credentials are not allowed.")
        if parsed.scheme != "https" or parsed.port not in (None, 443):
            raise DocumentationError("Only HTTPS on port 443 is allowed.")
        if host not in domains:
            raise DocumentationError("Documentation domain has not been approved.")
        return parsed.copy_with(host=host, fragment=None)
    except (ValueError, UnicodeError, httpx.InvalidURL) as exc:
        if isinstance(exc, DocumentationError):
            raise
        raise DocumentationError("Invalid documentation URL.") from exc


def _text(body: bytes, content_type: str, *, max_chars: int) -> tuple[str, bool]:
    charset = re.search(r"(?:^|;)\s*charset\s*=\s*[\"']?([^;\"'\s]+)", content_type, re.I)
    encoding = charset.group(1) if charset else "utf-8"
    try:
        codecs.lookup(encoding)
        text = body.decode(encoding, errors="replace")
    except (LookupError, ValueError) as exc:
        raise DocumentationError("Unsupported documentation text encoding.") from exc
    if "\x00" in text:
        raise DocumentationError("Binary documentation content is not allowed.")
    if not text.strip():
        return "", False
    mime = content_type.partition(";")[0].strip().lower()
    if mime in {"text/html", "application/xhtml+xml"}:
        try:
            document = html.fromstring(text, parser=html.HTMLParser(no_network=True))
        except (etree.ParserError, ValueError) as exc:
            raise DocumentationError("Documentation HTML could not be parsed.") from exc
        for element in document.xpath("//script|//style|//noscript|//template|//iframe|//object|//embed"):
            element.drop_tree()
        text = "\n".join(document.itertext())
    text = "".join(char for char in text if ord(char) >= 160 or 32 <= ord(char) < 127 or char in "\n\r\t")
    text = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").splitlines()).strip()
    return text[:max_chars], len(text) > max_chars


class DocumentationBroker:
    """One attempt's shared, bounded public fetch/search capability.

    Reuse this instance across root and delegated tools. Never accept domains,
    credentials, transports or limits from model-generated tool arguments.
    Returned text is untrusted source content, not an instruction channel.
    Seed usage from the attempt when resuming. Counts remain cumulative while
    each active broker window gets a deadline that excludes the human wait.
    """

    def __init__(self, approved_domains, *, search: BraveSearchConfig | None = None,
                 limits: DocumentationLimits | None = None, usage: dict | None = None):
        if isinstance(approved_domains, (str, bytes)):
            raise ValueError("Approved domains must be a collection of hostnames.")
        self.domains = frozenset(approved_domain(value) for value in approved_domains)
        if search is not None and not isinstance(search, BraveSearchConfig):
            raise ValueError("Invalid public search configuration.")
        if limits is not None and not isinstance(limits, DocumentationLimits):
            raise ValueError("Invalid public documentation limits.")
        self._search = search
        self.limits = limits or DocumentationLimits()
        self._lock = asyncio.Lock()
        self._deadline: float | None = None
        self._counts = {"pages": 0, "queries": 0, "requests": 0, "bytes": 0}
        if usage is not None:
            if (not isinstance(usage, dict) or not usage.keys() <= self._counts.keys()
                    or any(type(value) is not int or value < 0 for value in usage.values())):
                raise ValueError("Invalid saved documentation usage.")
            self._counts.update(usage)
        self._exhausted: str | None = (
            "Documentation total byte limit exhausted."
            if self._counts["bytes"] >= self.limits.max_total_bytes else None
        )

    def usage(self) -> dict:
        return dict(self._counts)

    async def _admit(self, kind: str) -> float:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            if self._deadline is None:
                self._deadline = now + self.limits.deadline_seconds
            if self._exhausted:
                raise DocumentationError(self._exhausted)
            if now >= self._deadline:
                raise DocumentationError("Documentation deadline exhausted.")
            if self._counts["requests"] >= self.limits.max_requests:
                raise DocumentationError("Documentation requests limit exhausted.")
            if self._counts[kind] >= getattr(self.limits, f"max_{kind}"):
                raise DocumentationError(f"Documentation {kind} limit exhausted.")
            self._counts[kind] += 1
            return self._deadline

    async def _charge(self, size: int):
        async with self._lock:
            self._counts["bytes"] += size
            if self._counts["bytes"] >= self.limits.max_total_bytes:
                self._exhausted = "Documentation total byte limit exhausted."
            if self._counts["bytes"] > self.limits.max_total_bytes:
                raise DocumentationError(self._exhausted)

    async def _resolve(self, host: str) -> str:
        answers = await asyncio.get_running_loop().getaddrinfo(
            host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP,
        )
        if not answers or len(answers) > 32:
            raise DocumentationError("Documentation DNS response is empty or too large.")
        addresses = sorted({_public_ip(answer[4][0]) for answer in answers})
        return addresses[0]

    async def _response(self, url: httpx.URL, *, json_response: bool = False,
                        token: SecretStr | None = None) -> dict:
        await self._admit("requests")
        host = url.raw_host.decode("ascii")
        address = await self._resolve(host)
        pinned_url = url.copy_with(host=address)
        headers = {"Host": host, "Accept-Encoding": "identity",
                   "Accept": "application/json" if json_response else "text/*, application/xhtml+xml",
                   "User-Agent": "GeneralAgent-Documentation/1"}
        if token is not None:
            headers["X-Subscription-Token"] = token.get_secret_value()
        transport = httpx.AsyncHTTPTransport(
            verify=tls_context(), trust_env=False, retries=0, http2=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        )
        async with httpx.AsyncClient(transport=transport, trust_env=False,
                                    follow_redirects=False, timeout=self.limits.deadline_seconds) as client:
            async with client.stream("GET", pinned_url, headers=headers,
                                     extensions={"sni_hostname": host}) as response:
                stream = response.extensions.get("network_stream")
                peer = stream.get_extra_info("server_addr") if stream is not None else None
                if not isinstance(peer, tuple) or not peer or _public_ip(peer[0]) != address:
                    raise DocumentationError("Connected peer did not match the pinned public address.")
                if response.status_code in _REDIRECTS:
                    location = response.headers.get("location", "")
                    if not location or len(location) > 8192 or _controls(location):
                        raise DocumentationError("Invalid documentation redirect.")
                    return {"redirect": location}
                if response.status_code != 200:
                    raise DocumentationError(f"Documentation server returned HTTP {response.status_code}.")
                if response.headers.get("content-encoding", "identity").lower() not in {"identity", ""}:
                    raise DocumentationError("Compressed documentation responses are not allowed.")
                content_type = response.headers.get("content-type", "")
                if len(content_type) > 512:
                    raise DocumentationError("Invalid documentation content type.")
                mime = content_type.partition(";")[0].strip().lower()
                if json_response:
                    allowed = mime == "application/json"
                else:
                    allowed = mime.startswith("text/") or mime == "application/xhtml+xml"
                if not allowed:
                    raise DocumentationError("Documentation response must contain supported text.")
                declared = response.headers.get("content-length")
                if declared is not None:
                    if not declared.isdecimal() or len(declared) > 20:
                        raise DocumentationError("Invalid documentation content length.")
                    if int(declared) > self.limits.max_response_bytes:
                        raise DocumentationError("Documentation response byte limit exhausted.")
                body = bytearray()
                async for chunk in response.aiter_raw(chunk_size=8192):
                    await self._charge(len(chunk))
                    if len(body) + len(chunk) > self.limits.max_response_bytes:
                        raise DocumentationError("Documentation response byte limit exhausted.")
                    body.extend(chunk)
                return {"body": bytes(body), "content_type": content_type}

    async def fetch(self, url: str) -> dict:
        current = _url(url, self.domains)
        requested = str(current)
        deadline = await self._admit("pages")
        redirects = []
        try:
            async with asyncio.timeout_at(deadline):
                for hop in range(self.limits.max_redirects + 1):
                    response = await self._response(current)
                    if "redirect" not in response:
                        text, truncated = _text(response["body"], response["content_type"],
                                                max_chars=self.limits.max_text_chars)
                        return {"requested_url": requested, "url": str(current), "redirects": redirects,
                                "fetched_at": datetime.now(timezone.utc).isoformat(),
                                "content_sha256": hashlib.sha256(response["body"]).hexdigest(),
                                "content_type": response["content_type"], "text": text,
                                "truncated": truncated, "untrusted_content": True}
                    if hop == self.limits.max_redirects:
                        raise DocumentationError("Documentation redirect limit exhausted.")
                    location = response["redirect"]
                    if "@" in urlsplit(location).netloc:
                        raise DocumentationError("URL credentials are not allowed.")
                    if "://" in location:
                        _url(location, self.domains)
                    current = _url(str(current.join(location)), self.domains)
                    redirects.append(str(current))
        except TimeoutError as exc:
            raise DocumentationError("Documentation deadline exhausted.") from exc
        except (httpx.HTTPError, OSError) as exc:
            raise DocumentationError("Public documentation request failed.") from exc
        raise DocumentationError("Documentation request did not complete.")

    async def search(self, query: str, *, domain: str, count: int = 5) -> dict:
        if self._search is None:
            raise DocumentationError("Public documentation search has not been configured.")
        selected = approved_domain(domain)
        if selected not in self.domains:
            raise DocumentationError("Documentation domain has not been approved.")
        if not isinstance(query, str) or not query.strip() or _controls(query):
            raise DocumentationError("Invalid documentation search query.")
        full_query = f"site:{selected} {query.strip()}"
        if len(full_query) > 600 or len(full_query.split()) > 75:
            raise DocumentationError("Documentation search query is too long.")
        if type(count) is not int or not 1 <= count <= 10:
            raise DocumentationError("Documentation search count must be between 1 and 10.")
        url = _url(_BRAVE_URL, frozenset({"api.search.brave.com"})).copy_add_param("q", full_query)
        for key, value in {"count": str(count), "result_filter": "web", "text_decorations": "false"}.items():
            url = url.copy_add_param(key, value)
        deadline = await self._admit("queries")
        try:
            async with asyncio.timeout_at(deadline):
                response = await self._response(url, json_response=True, token=self._search.api_key)
                if "redirect" in response:
                    raise DocumentationError("Public search redirects are not allowed.")
                try:
                    payload = json.loads(response["body"])
                    records = payload.get("web", {}).get("results", [])
                except (ValueError, AttributeError, TypeError, RecursionError) as exc:
                    raise DocumentationError("Invalid public search response.") from exc
                if not isinstance(records, list) or len(records) > 100:
                    raise DocumentationError("Invalid public search results.")
                results = []
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    try:
                        result_url = _url(record.get("url"), frozenset({selected}))
                    except DocumentationError:
                        continue
                    title = record.get("title", "")
                    snippet = record.get("description", "")
                    if not isinstance(title, str) or not isinstance(snippet, str):
                        continue
                    title_text, _ = _text(title.encode(errors="replace"), "text/html", max_chars=500) if title else ("", False)
                    snippet_text, _ = _text(snippet.encode(errors="replace"), "text/html", max_chars=2000) if snippet else ("", False)
                    results.append({"url": str(result_url), "title": title_text, "snippet": snippet_text})
                    if len(results) >= count:
                        break
                return {"provider": "brave", "query": query.strip(), "domain": selected,
                        "url": str(url), "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "content_sha256": hashlib.sha256(response["body"]).hexdigest(),
                        "results": results, "untrusted_content": True}
        except TimeoutError as exc:
            raise DocumentationError("Documentation deadline exhausted.") from exc
        except (httpx.HTTPError, OSError) as exc:
            raise DocumentationError("Public documentation search request failed.") from exc
