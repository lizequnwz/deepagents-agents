from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import ssl

import httpx
import pytest
from pydantic import SecretStr

from general_agent.coding import documentation
from general_agent.coding.documentation import (
    BraveSearchConfig, DocumentationBroker, DocumentationError, DocumentationLimits, approved_domain,
)


class Peer:
    def __init__(self, address="8.8.8.8"):
        self.address = address

    def get_extra_info(self, name):
        return (self.address, 443) if name == "server_addr" else None


class Body(httpx.AsyncByteStream):
    def __init__(self, chunks, *, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.read = False
        self.closed = False

    async def __aiter__(self):
        self.read = True
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.fixture
async def network(monkeypatch):
    requests, transports, dns_calls, responses = [], [], [], []
    answers = {"docs.example.org": ["8.8.8.8"], "other.example.org": ["1.1.1.1"],
               "api.search.brave.com": ["8.8.4.4"]}

    async def resolve(host, port, **kwargs):
        dns_calls.append((host, port, kwargs))
        return [(socket.AF_INET6 if ":" in address else socket.AF_INET,
                 socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))
                for address in answers.get(host, ["8.8.8.8"])]

    class Transport(httpx.AsyncBaseTransport):
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            transports.append(self)

        async def handle_async_request(self, request):
            requests.append(request)
            if not responses:
                raise AssertionError("Unexpected outbound request")
            record = responses.pop(0)
            if isinstance(record, Exception):
                raise record
            record = dict(record)
            body = record.pop("stream", Body([record.pop("body", b"hello")]))
            extensions = record.pop("extensions", {"network_stream": Peer(request.url.host)})
            headers = {"content-type": "text/plain", **record.pop("headers", {})}
            return httpx.Response(record.pop("status", 200), headers=headers,
                                  stream=body, extensions=extensions, request=request, **record)

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(documentation.httpx, "AsyncHTTPTransport", Transport)
    return {"requests": requests, "transports": transports, "dns": dns_calls,
            "responses": responses, "answers": answers}


def broker(**kwargs):
    return DocumentationBroker(["docs.example.org", "other.example.org"], **kwargs)


@pytest.mark.parametrize("domain", ["localhost", "*.example.org", "https://docs.example.org", "docs.example.org/",
                                   "127.0.0.1", "[::1]", "docs.example.org.", "docs_example.org",
                                   "a..example.org", "-a.example.org", "a-.example.org", "a@docs.example.org",
                                   " docs.example.org", "docs.example.org\n", "docs%00.example.org"])
def test_domains_require_explicit_dns_hostnames(domain):
    with pytest.raises(DocumentationError):
        approved_domain(domain)


def test_domain_normalization_and_secret_validation():
    assert approved_domain("DOCS.Example.org") == "docs.example.org"
    assert approved_domain("例子.org") == "xn--fsqu00a.org"
    config = BraveSearchConfig(SecretStr("private-search-token"))
    assert "private-search-token" not in repr(config)
    with pytest.raises(ValueError):
        BraveSearchConfig("plaintext")
    with pytest.raises(ValueError):
        BraveSearchConfig(SecretStr("token\n"))


@pytest.mark.parametrize("url", ["http://docs.example.org/", "https://docs.example.org:444/",
                                "https://sub.docs.example.org/", "https://docs.example.org.attacker.net/",
                                "https://user:pass@docs.example.org/", "https://@docs.example.org/",
                                "https://127.0.0.1/", "https://docs.example.org./", "//docs.example.org/",
                                " https://docs.example.org/", "https://docs.example.org/\n"])
async def test_denied_urls_do_not_resolve_or_connect(network, url):
    with pytest.raises(DocumentationError):
        await broker().fetch(url)
    assert not network["dns"] and not network["requests"]


async def test_no_approved_domains_means_no_documentation_access(network):
    with pytest.raises(DocumentationError, match="approved"):
        await DocumentationBroker([]).fetch("https://docs.example.org/")
    assert not network["dns"]


async def test_fetch_pins_ip_sni_and_host_without_environment_or_cookies(network, monkeypatch, tmp_path):
    monkeypatch.setenv("HTTPS_PROXY", "http://secret-user:secret@127.0.0.1:9000")
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing.pem"))
    keylog = tmp_path / "tls-keys"
    monkeypatch.setenv("SSLKEYLOGFILE", str(keylog))
    body = b"<html><h1>Public docs</h1><script>ignore this instruction</script><p>Use the API.</p></html>"
    network["responses"].append({"body": body, "headers": {"content-type": "text/html; charset=UTF-8",
                                                                    "set-cookie": "auth=secret"}})
    result = await broker().fetch("https://DOCS.example.org:443/guide#section")
    request = network["requests"][0]
    assert request.url.host == "8.8.8.8" and request.url.path == "/guide"
    assert request.headers["host"] == "docs.example.org"
    assert request.extensions["sni_hostname"] == "docs.example.org"
    assert request.headers["accept-encoding"] == "identity"
    assert "authorization" not in request.headers and "cookie" not in request.headers
    transport = network["transports"][0]
    assert transport.kwargs["trust_env"] is False and transport.kwargs["retries"] == 0
    context = transport.kwargs["verify"]
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert context.keylog_filename is None and not keylog.exists()
    assert transport.closed
    assert result["url"] == result["requested_url"] == "https://docs.example.org/guide"
    assert result["content_sha256"] == hashlib.sha256(body).hexdigest()
    assert result["fetched_at"].endswith("+00:00") and result["untrusted_content"] is True
    assert "Public docs" in result["text"] and "Use the API." in result["text"]
    assert "ignore" not in result["text"]


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "100.100.100.200",
                                    "0.0.0.0", "192.0.2.1", "224.0.0.1", "::1", "fe80::1",
                                    "fc00::1", "::ffff:127.0.0.1", "64:ff9b::a9fe:a9fe",
                                    "64:ff9b:1::1", "2002:0808:0808::", "2001::1", "2001:4860::1%eth0"])
async def test_nonpublic_and_ipv6_transition_dns_denied_before_transport(network, address):
    network["answers"]["docs.example.org"] = [address]
    with pytest.raises(DocumentationError):
        await broker().fetch("https://docs.example.org/")
    assert not network["transports"]


@pytest.mark.parametrize("address", ["192.0.0.8", "192.0.0.11", "192.88.99.1", "192.88.99.2", "3fff::1"])
async def test_special_protocol_relay_documentation_blocks_denied_across_python_versions(network, address):
    network["answers"]["docs.example.org"] = [address]
    with pytest.raises(DocumentationError):
        await broker().fetch("https://docs.example.org/")
    assert not network["transports"]


async def test_mixed_public_private_dns_answers_fail_closed(network):
    network["answers"]["docs.example.org"] = ["8.8.8.8", "127.0.0.1"]
    with pytest.raises(DocumentationError):
        await broker().fetch("https://docs.example.org/")
    assert not network["requests"]


async def test_global_ipv6_and_public_mapped_addresses_pin_canonical_peer(network):
    network["answers"]["docs.example.org"] = ["2001:4860:4860::8888"]
    network["responses"].append({})
    assert (await broker().fetch("https://docs.example.org/"))["text"] == "hello"
    assert network["requests"][0].url.host == "2001:4860:4860::8888"
    network["answers"]["docs.example.org"] = ["::ffff:8.8.8.8"]
    network["responses"].append({"extensions": {"network_stream": Peer("::ffff:8.8.8.8")}})
    await broker().fetch("https://docs.example.org/")
    assert network["requests"][1].url.host == "8.8.8.8"


@pytest.mark.parametrize("extensions", [{}, {"network_stream": Peer("1.1.1.1")},
                                         {"network_stream": Peer("127.0.0.1")}])
async def test_connected_peer_is_verified_before_reading_body(network, extensions):
    body = Body([b"must not be consumed"])
    network["responses"].append({"stream": body, "extensions": extensions})
    with pytest.raises(DocumentationError):
        await broker().fetch("https://docs.example.org/")
    assert not body.read and body.closed


async def test_approved_redirect_revalidates_dns_and_never_reuses_cookies(network):
    network["responses"].extend([
        {"status": 302, "headers": {"location": "https://other.example.org/new", "set-cookie": "session=private"}},
        {"body": b"redirected"},
    ])
    result = await broker().fetch("https://docs.example.org/old")
    assert result["url"] == "https://other.example.org/new"
    assert len(network["transports"]) == 2 and all(t.closed for t in network["transports"])
    assert [request.url.host for request in network["requests"]] == ["8.8.8.8", "1.1.1.1"]
    assert all("cookie" not in request.headers for request in network["requests"])


@pytest.mark.parametrize("location", ["https://evil.example.net/", "http://docs.example.org/",
                                     "https://docs.example.org:444/", "https://@docs.example.org/",
                                     "//@docs.example.org/", "//user@docs.example.org/", "https://127.0.0.1/"])
async def test_redirect_authority_denied_before_second_connection(network, location):
    network["responses"].append({"status": 302, "headers": {"location": location}})
    with pytest.raises(DocumentationError):
        await broker().fetch("https://docs.example.org/")
    assert len(network["requests"]) == len(network["dns"]) == 1


async def test_relative_redirect_and_redirect_loop_are_bounded(network):
    network["responses"].extend([{"status": 302, "headers": {"location": "../next"}}, {}])
    await broker().fetch("https://docs.example.org/path/start")
    assert network["requests"][1].url.path == "/next"
    network["responses"].extend([{"status": 302, "headers": {"location": "/loop"}}] * 2)
    with pytest.raises(DocumentationError, match="redirect limit"):
        await broker(limits=DocumentationLimits(max_redirects=1)).fetch("https://docs.example.org/")


async def test_redirect_dns_rebinding_to_private_fails_before_new_transport(network):
    network["responses"].append({"status": 302, "headers": {"location": "https://other.example.org/"}})
    network["answers"]["other.example.org"] = ["169.254.169.254"]
    with pytest.raises(DocumentationError):
        await broker().fetch("https://docs.example.org/")
    assert len(network["requests"]) == 1


@pytest.mark.parametrize("headers", [{"content-type": "application/pdf"}, {"content-type": "application/json"},
                                   {"content-type": "image/svg+xml"}, {"content-encoding": "gzip"},
                                   {"content-length": "10000"}, {"content-length": "-5"}])
async def test_unsupported_compressed_or_oversize_content_denied_without_body(network, headers):
    body = Body([b"danger"])
    network["responses"].append({"headers": headers, "stream": body})
    with pytest.raises(DocumentationError):
        await broker(limits=DocumentationLimits(max_response_bytes=10)).fetch("https://docs.example.org/")
    assert not body.read


async def test_streamed_bytes_truncation_and_binary_content(network):
    network["responses"].append({"body": b"123456789"})
    result = await broker(limits=DocumentationLimits(max_text_chars=5)).fetch("https://docs.example.org/")
    assert result["text"] == "12345" and result["truncated"]
    network["responses"].append({"stream": Body([b"123456", b"789012"]), "headers": {}})
    with pytest.raises(DocumentationError, match="response byte"):
        await broker(limits=DocumentationLimits(max_response_bytes=10)).fetch("https://docs.example.org/")
    network["responses"].append({"body": b"binary\0payload"})
    with pytest.raises(DocumentationError, match="Binary"):
        await broker().fetch("https://docs.example.org/")


async def test_html_entity_external_content_is_not_followed(network):
    network["responses"].append({"body": b'<!DOCTYPE html SYSTEM "http://127.0.0.1/private"><html><p>safe</p><iframe src="https://evil.example/"></iframe></html>',
                                "headers": {"content-type": "application/xhtml+xml"}})
    result = await broker().fetch("https://docs.example.org/")
    assert result["text"] == "safe" and len(network["requests"]) == 1


async def test_global_counts_admit_concurrently_and_share_bytes(network):
    item = broker(limits=DocumentationLimits(max_pages=1))
    network["responses"].append({})
    results = await asyncio.gather(item.fetch("https://docs.example.org/a"),
                                   item.fetch("https://docs.example.org/b"), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, DocumentationError) for result in results) == 1
    assert len(network["requests"]) == 1 and item.usage()["pages"] == 1
    item = broker(limits=DocumentationLimits(max_total_bytes=8))
    network["responses"].extend([{}, {}])
    await item.fetch("https://docs.example.org/a")
    with pytest.raises(DocumentationError, match="total byte"):
        await item.fetch("https://docs.example.org/b")
    count = len(network["requests"])
    with pytest.raises(DocumentationError, match="total byte"):
        await item.fetch("https://docs.example.org/c")
    assert len(network["requests"]) == count and item.usage()["bytes"] == 10


async def test_global_deadline_includes_dns_streaming_and_later_operations(network, monkeypatch):
    item = broker(limits=DocumentationLimits(deadline_seconds=0.02))
    network["responses"].append({"stream": Body([b"late"], delay=0.05)})
    with pytest.raises(DocumentationError, match="deadline"):
        await item.fetch("https://docs.example.org/")
    with pytest.raises(DocumentationError, match="deadline"):
        await item.fetch("https://docs.example.org/again")
    assert len(network["requests"]) == 1

    async def slow_dns(*args, **kwargs):
        await asyncio.sleep(0.05)
        raise AssertionError("DNS should have been cancelled")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", slow_dns)
    with pytest.raises(DocumentationError, match="deadline"):
        await broker(limits=DocumentationLimits(deadline_seconds=0.02)).fetch("https://docs.example.org/")


async def test_request_budget_counts_redirects_and_failures(network):
    item = broker(limits=DocumentationLimits(max_requests=1))
    network["responses"].append({"status": 302, "headers": {"location": "/next"}})
    with pytest.raises(DocumentationError, match="requests limit"):
        await item.fetch("https://docs.example.org/")
    assert len(network["requests"]) == 1
    network["responses"].append(httpx.ConnectError("sensitive proxy detail"))
    with pytest.raises(DocumentationError, match="Public documentation request failed") as error:
        await broker().fetch("https://docs.example.org/")
    assert "sensitive" not in str(error.value)


async def test_search_uses_documented_fixed_api_and_filters_to_selected_domain(network):
    key = "server-only-search-key"
    item = broker(search=BraveSearchConfig(SecretStr(key)))
    body = json.dumps({"web": {"results": [
        {"url": "https://evil.example/", "title": "bad", "description": "bad"},
        {"url": "https://sub.docs.example.org/", "title": "subdomain", "description": "bad"},
        {"url": "https://docs.example.org/a", "title": "<b>Good</b>", "description": "API <strong>help</strong>"},
        {"url": "http://docs.example.org/b", "title": "insecure", "description": "bad"},
        {"url": "https://@docs.example.org/b", "title": "userinfo", "description": "bad"},
        {"url": "https://other.example.org/b", "title": "other approved", "description": "bad"},
    ]}}).encode()
    network["responses"].append({"body": body, "headers": {"content-type": "application/json"}})
    result = await item.search("async client", domain="docs.example.org", count=3)
    request = network["requests"][0]
    assert request.url.host == "8.8.4.4" and request.url.path == "/res/v1/web/search"
    assert request.headers["host"] == request.extensions["sni_hostname"] == "api.search.brave.com"
    assert request.headers["x-subscription-token"] == key
    assert request.url.params["q"] == "site:docs.example.org async client"
    assert request.url.params["result_filter"] == "web"
    assert request.url.params["text_decorations"] == "false"
    assert result["results"] == [{"url": "https://docs.example.org/a", "title": "Good", "snippet": "API\nhelp"}]
    assert result["content_sha256"] == hashlib.sha256(body).hexdigest()
    assert key not in json.dumps(result) and key not in repr(item._search)
    assert [entry[0] for entry in network["dns"]] == ["api.search.brave.com"]


async def test_search_secret_not_sent_on_redirect_or_later_document_fetch(network):
    item = broker(search=BraveSearchConfig(SecretStr("secret-key")))
    network["responses"].append({"status": 302, "headers": {"location": "https://docs.example.org/"}})
    with pytest.raises(DocumentationError, match="search redirects"):
        await item.search("docs", domain="docs.example.org")
    assert len(network["requests"]) == 1
    network["responses"].append({})
    await item.fetch("https://docs.example.org/")
    assert "x-subscription-token" not in network["requests"][1].headers
    assert item.usage()["queries"] == item.usage()["pages"] == 1


@pytest.mark.parametrize("query,domain,count", [("", "docs.example.org", 5), ("q\n", "docs.example.org", 5),
                                             ("a" * 600, "docs.example.org", 5), ("q " * 75, "docs.example.org", 5),
                                             ("q", "evil.example", 5), ("q", "docs.example.org", 0),
                                             ("q", "docs.example.org", True), ("q", "docs.example.org", 11)])
async def test_search_invalid_or_unapproved_arguments_never_connect(network, query, domain, count):
    with pytest.raises(DocumentationError):
        await broker(search=BraveSearchConfig(SecretStr("key"))).search(query, domain=domain, count=count)
    assert not network["dns"]


async def test_search_opt_in_and_query_budget(network):
    with pytest.raises(DocumentationError, match="configured"):
        await broker().search("help", domain="docs.example.org")
    item = broker(search=BraveSearchConfig(SecretStr("key")), limits=DocumentationLimits(max_queries=1))
    network["responses"].append({"body": b'{"web":{"results":[]}}', "headers": {"content-type": "application/json"}})
    assert (await item.search("help", domain="docs.example.org"))["results"] == []
    with pytest.raises(DocumentationError, match="queries limit"):
        await item.search("again", domain="docs.example.org")


@pytest.mark.parametrize("body", [b"broken json", b"[]", b'{"web":[]}', b'{"web":{"results":"bad"}}'])
async def test_search_malformed_provider_responses_fail_safely(network, body):
    network["responses"].append({"body": body, "headers": {"content-type": "application/json"}})
    with pytest.raises(DocumentationError, match="Invalid public search"):
        await broker(search=BraveSearchConfig(SecretStr("key"))).search("help", domain="docs.example.org")


@pytest.mark.parametrize("kwargs", [{"deadline_seconds": float("nan")}, {"deadline_seconds": float("inf")},
                                    {"deadline_seconds": False}, {"max_pages": 0}, {"max_queries": True},
                                    {"max_total_bytes": -1}, {"max_redirects": -1}])
def test_limits_are_finite_and_validated(kwargs):
    with pytest.raises(ValueError):
        DocumentationLimits(**kwargs)


@pytest.mark.parametrize("usage", [{"unknown": 1}, {"pages": True}, {"bytes": -1}, {"queries": 1.5}, []])
def test_seeded_usage_must_contain_only_nonnegative_known_integer_counters(usage):
    with pytest.raises(ValueError, match="saved documentation usage"):
        broker(usage=usage)


async def test_seeded_usage_survives_resume_and_cannot_be_mutated_by_caller(network):
    previous = {"pages": 5, "queries": 1, "requests": 10, "bytes": 1234}
    item = broker(usage=previous)
    previous["pages"] = 0
    network["responses"].append({})
    await item.fetch("https://docs.example.org/")
    assert item.usage() == {"pages": 6, "queries": 1, "requests": 11, "bytes": 1239}
    exported = item.usage()
    exported["pages"] = 0
    resumed = broker(usage=item.usage())
    with pytest.raises(DocumentationError, match="pages limit"):
        await resumed.fetch("https://docs.example.org/")
    assert len(network["requests"]) == 1


@pytest.mark.parametrize("usage,reason", [({"requests": 12}, "requests limit"),
                                        ({"bytes": 2 * 1024 * 1024}, "total byte"),
                                        ({"bytes": 2 * 1024 * 1024 + 1}, "total byte")])
async def test_exhausted_seeded_global_counters_deny_before_dns(network, usage, reason):
    with pytest.raises(DocumentationError, match=reason):
        await broker(usage=usage).fetch("https://docs.example.org/")
    assert not network["dns"] and not network["requests"]


async def test_real_httpx_httpcore_transport_connects_only_literal_ip_and_verifies_hostname(monkeypatch):
    """Exercise the real HTTP stack without opening a socket or external network."""
    connections, handshakes, writes = [], [], []

    class Wire:
        closed = False
        response = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 4\r\n\r\ndocs"

        async def read(self, max_bytes, timeout=None):
            response, self.response = self.response, b""
            return response

        async def write(self, buffer, timeout=None):
            writes.append(buffer)

        async def aclose(self):
            self.closed = True

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            handshakes.append((ssl_context, server_hostname))
            return self

        def get_extra_info(self, name):
            return ("8.8.8.8", 443) if name == "server_addr" else None

    wire = Wire()

    class Network:
        async def connect_tcp(self, host, port, **kwargs):
            connections.append((host, port))
            return wire

    async def resolve(host, port, **kwargs):
        assert host == "docs.example.org"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", port))]

    original = httpx.AsyncHTTPTransport

    def transport(**kwargs):
        instance = original(**kwargs)
        instance._pool._network_backend = Network()
        return instance

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(documentation.httpx, "AsyncHTTPTransport", transport)
    result = await broker().fetch("https://docs.example.org/guide")
    assert result["text"] == "docs" and wire.closed
    assert connections == [("8.8.8.8", 443)]
    assert handshakes[0][1] == "docs.example.org"
    assert handshakes[0][0].check_hostname and handshakes[0][0].verify_mode == ssl.CERT_REQUIRED
    assert b"Host: docs.example.org\r\n" in b"".join(writes)
