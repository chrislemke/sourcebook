"""Security and reliability contracts for upstream HTTP retrieval."""

from __future__ import annotations

import gzip
import ipaddress
from pathlib import Path

import httpx
import pytest

from policy_mcp.source_http import BoundedHttpClient, SourceRequestError


def public_resolver(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    addresses = {
        "search.example.eu": [ipaddress.ip_address("8.8.8.8")],
        "files.example.eu": [ipaddress.ip_address("1.1.1.1")],
        "localhost": [ipaddress.ip_address("127.0.0.1")],
    }
    return addresses[host]


async def test_rejects_hosts_and_private_redirects_before_following_them() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://localhost/private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = BoundedHttpClient(
            transport,
            allowed_hosts={"search.example.eu", "localhost"},
            resolver=public_resolver,
        )
        with pytest.raises(SourceRequestError, match="HTTPS"):
            await client.get("https://search.example.eu/record")

        with pytest.raises(SourceRequestError, match="allowlisted"):
            await client.get("https://unlisted.example/record")

    assert calls == ["https://search.example.eu/record"]


async def test_rejects_private_allowlisted_address() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200))
    ) as http:
        client = BoundedHttpClient(http, allowed_hosts={"localhost"}, resolver=public_resolver)
        with pytest.raises(SourceRequestError, match="private or reserved"):
            await client.get("https://localhost/record")


async def test_retries_transient_failures_and_honors_response_limit() -> None:
    attempts = 0
    delays: list[float] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, headers={"retry-after": "0"})
        return httpx.Response(200, content=b"bounded")

    async def record_delay(seconds: float) -> None:
        delays.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = BoundedHttpClient(
            transport,
            allowed_hosts={"search.example.eu"},
            resolver=public_resolver,
            sleep=record_delay,
        )
        response = await client.get("https://search.example.eu/data")

    assert response.content == b"bounded"
    assert attempts == 3
    assert delays == [0.0, 0.0]

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"123456"))
    ) as transport:
        client = BoundedHttpClient(
            transport,
            allowed_hosts={"files.example.eu"},
            resolver=public_resolver,
            max_response_bytes=5,
        )
        with pytest.raises(SourceRequestError, match="response limit"):
            await client.get("https://files.example.eu/file")


async def test_decoded_response_does_not_reapply_content_encoding() -> None:
    compressed = gzip.compress(b"decoded content")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=compressed,
                headers={"content-encoding": "gzip"},
            )
        )
    ) as transport:
        client = BoundedHttpClient(
            transport,
            allowed_hosts={"files.example.eu"},
            resolver=public_resolver,
        )
        response = await client.get("https://files.example.eu/file")

    assert response.content == b"decoded content"
    assert "content-encoding" not in response.headers


async def test_streaming_download_replaces_cache_only_after_complete_response(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "snapshot.xml"
    destination.write_bytes(b"old")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"complete"))
    ) as transport:
        client = BoundedHttpClient(
            transport,
            allowed_hosts={"files.example.eu"},
            resolver=public_resolver,
            max_response_bytes=10,
        )
        response = await client.download("https://files.example.eu/file", destination)

    assert response.status_code == 200
    assert destination.read_bytes() == b"complete"

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"too-large"))
    ) as transport:
        client = BoundedHttpClient(
            transport,
            allowed_hosts={"files.example.eu"},
            resolver=public_resolver,
            max_response_bytes=5,
        )
        with pytest.raises(SourceRequestError, match="response limit"):
            await client.download("https://files.example.eu/file", destination)

    assert destination.read_bytes() == b"complete"
