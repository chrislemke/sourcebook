"""Security and reliability contracts for upstream HTTP retrieval."""

from __future__ import annotations

import ipaddress

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
