"""Bounded HTTP retrieval for allowlisted official sources."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str], list[IPAddress]]
Sleeper = Callable[[float], Awaitable[None]]


class SourceRequestError(RuntimeError):
    """A safe upstream error that contains no credentials or response body."""


def resolve_host(host: str) -> list[IPAddress]:
    """Resolve a host into validated address objects."""
    return list(
        {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        }
    )


@dataclass
class BoundedHttpClient:
    """HTTP client with host, redirect, retry, and response-size limits."""

    client: httpx.AsyncClient
    allowed_hosts: set[str]
    resolver: Resolver = resolve_host
    sleep: Sleeper = asyncio.sleep
    max_response_bytes: int = 5_000_000
    max_redirects: int = 3
    transient_retries: int = 2

    def _validate_url(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "https":
            raise SourceRequestError("Official source URLs must use HTTPS")
        if parsed.username or parsed.password:
            raise SourceRequestError("Credentials are forbidden in source URLs")
        host = parsed.hostname
        if host is None or host not in self.allowed_hosts:
            raise SourceRequestError("Source host is not allowlisted")
        try:
            addresses = self.resolver(host)
        except (OSError, KeyError, ValueError) as error:
            raise SourceRequestError("Source host could not be resolved") from error
        if not addresses:
            raise SourceRequestError("Source host could not be resolved")
        if any(not address.is_global for address in addresses):
            raise SourceRequestError("Source host resolves to a private or reserved address")

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str | int] | None = None,
        data: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """Send one bounded request, following only validated redirects."""
        current = url
        current_method = method
        current_data = data
        redirects = 0
        attempts = 0
        while True:
            self._validate_url(current)
            try:
                async with self.client.stream(
                    current_method,
                    current,
                    headers=headers,
                    params=params,
                    data=current_data,
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if location is None:
                            raise SourceRequestError("Source redirect omitted its destination")
                        redirects += 1
                        if redirects > self.max_redirects:
                            raise SourceRequestError("Source exceeded the redirect limit")
                        current = urljoin(current, location)
                        params = None
                        if response.status_code in {301, 302, 303}:
                            current_method = "GET"
                            current_data = None
                        continue

                    if (
                        response.status_code in {429, 502, 503, 504}
                        and attempts < self.transient_retries
                    ):
                        attempts += 1
                        retry_after = response.headers.get("retry-after", "0")
                        try:
                            delay = min(max(float(retry_after), 0), 5)
                        except ValueError:
                            delay = 0
                        await self.sleep(delay)
                        continue

                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > self.max_response_bytes:
                            raise SourceRequestError(
                                "Official source response exceeded the response limit"
                            )
                    return httpx.Response(
                        status_code=response.status_code,
                        headers=response.headers,
                        content=bytes(content),
                        request=response.request,
                        extensions=response.extensions,
                    )
            except httpx.HTTPError as error:
                if attempts >= self.transient_retries:
                    raise SourceRequestError("Official source request failed") from error
                attempts += 1
                await self.sleep(0)
                continue

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str | int] | None = None,
    ) -> httpx.Response:
        """Retrieve one bounded response."""
        return await self.request("GET", url, headers=headers, params=params)

    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """Submit one bounded form request."""
        return await self.request("POST", url, headers=headers, data=data)
