"""Bounded client for the documented GovData CKAN actions."""

from __future__ import annotations

from typing import Any

import httpx

from policy_mcp.evidence_models import (
    CatalogueDistribution,
    CatalogueRecord,
    CatalogueSearchPage,
    ProviderResponseError,
)
from policy_mcp.source_http import BoundedHttpClient, Resolver, SourceRequestError, resolve_host

BASE_URL = "https://www.govdata.de/ckan/api/3/action"


class GovDataClient:
    """Read package metadata through an injected HTTP client."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_response_bytes: int = 2_000_000,
        resolver: Resolver = resolve_host,
    ) -> None:
        self._http = BoundedHttpClient(
            client,
            allowed_hosts={"www.govdata.de"},
            resolver=resolver,
            max_response_bytes=max_response_bytes,
        )

    async def search(self, query: str, *, limit: int = 5, start: int = 0) -> CatalogueSearchPage:
        """Search the public catalogue without treating distributions as queryable."""
        if not query.strip():
            raise ValueError("GovData search requires a non-empty query")
        if not 1 <= limit <= 10:
            raise ValueError("GovData search limit must be between 1 and 10")
        if start < 0:
            raise ValueError("GovData search start must not be negative")
        result = await self._request(
            "package_search", params={"q": query, "rows": limit, "start": start}
        )
        if not isinstance(result, dict):
            raise ProviderResponseError("GovData returned an invalid package search result")
        count = result.get("count")
        packages = result.get("results")
        if not isinstance(count, int) or not isinstance(packages, list):
            raise ProviderResponseError("GovData returned an invalid package search result")
        items = tuple(self._project_package(package) for package in packages)
        next_start = start + len(items) if start + len(items) < count else None
        return CatalogueSearchPage(items=items, total=count, next_start=next_start)

    async def get(self, provider_id: str) -> CatalogueRecord:
        """Retrieve one selected package."""
        if not provider_id.strip():
            raise ValueError("GovData package identifier must not be empty")
        result = await self._request("package_show", params={"id": provider_id})
        return self._project_package(result)

    async def _request(self, action: str, *, params: dict[str, str | int]) -> Any:
        try:
            response = await self._http.get(f"{BASE_URL}/{action}", params=params)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, SourceRequestError, ValueError) as error:
            raise ProviderResponseError("GovData request failed") from error
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ProviderResponseError("GovData reported an application-level failure")
        if "result" not in payload:
            raise ProviderResponseError("GovData response omitted its result")
        return payload["result"]

    @staticmethod
    def _project_package(value: Any) -> CatalogueRecord:
        if not isinstance(value, dict):
            raise ProviderResponseError("GovData returned invalid package metadata")
        provider_id = value.get("name")
        title = value.get("title")
        if not isinstance(provider_id, str) or not isinstance(title, str):
            raise ProviderResponseError("GovData package metadata omitted its identity")
        organization = value.get("organization")
        publisher = organization.get("title") if isinstance(organization, dict) else None
        raw_extras = value.get("extras")
        extras = {
            item["key"]: item["value"]
            for item in (raw_extras if isinstance(raw_extras, list) else [])
            if isinstance(item, dict)
            and isinstance(item.get("key"), str)
            and isinstance(item.get("value"), str)
        }
        if not isinstance(publisher, str) or not publisher:
            publisher = extras.get("publisher_name")
        resources = value.get("resources", [])
        if not isinstance(resources, list):
            raise ProviderResponseError("GovData package resources are invalid")
        distributions: list[CatalogueDistribution] = []
        # DCAT-AP.de publishes licences per distribution, so the package field is often empty.
        distribution_licences: list[str] = []
        for resource in resources:
            if not isinstance(resource, dict):
                raise ProviderResponseError("GovData returned an invalid distribution")
            resource_id = resource.get("id")
            url = resource.get("url")
            if not isinstance(resource_id, str) or not isinstance(url, str):
                raise ProviderResponseError("GovData distribution omitted its identity")
            if isinstance(resource.get("license"), str) and resource["license"]:
                distribution_licences.append(resource["license"])
            distributions.append(
                CatalogueDistribution(
                    provider_id=resource_id,
                    title=resource.get("name") if isinstance(resource.get("name"), str) else None,
                    url=url,
                    format=(
                        resource.get("format") if isinstance(resource.get("format"), str) else None
                    ),
                )
            )
        return CatalogueRecord(
            provider_id=provider_id,
            title=title,
            description=value.get("notes") if isinstance(value.get("notes"), str) else None,
            publisher=publisher if isinstance(publisher, str) else None,
            modified_at=(
                value.get("metadata_modified")
                if isinstance(value.get("metadata_modified"), str)
                else None
            ),
            licence=(
                value["license_id"]
                if isinstance(value.get("license_id"), str) and value["license_id"]
                else "; ".join(dict.fromkeys(distribution_licences)) or None
            ),
            distributions=tuple(distributions),
        )


class LiveGovDataService:
    """Open a short-lived bounded client for each interactive GovData request."""

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("GovData timeout must be positive")
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 5.0))

    async def search(self, query: str, *, limit: int = 5, start: int = 0) -> CatalogueSearchPage:
        """Search GovData without keeping a network client alive between MCP calls."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await GovDataClient(client).search(query, limit=limit, start=start)

    async def get(self, provider_id: str) -> CatalogueRecord:
        """Read one selected GovData package."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await GovDataClient(client).get(provider_id)
