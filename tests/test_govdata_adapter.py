"""Public contract tests for the GovData CKAN adapter."""

from __future__ import annotations

import ipaddress

import httpx
import pytest
import respx

from policy_mcp.adapters.govdata import GovDataClient
from policy_mcp.evidence_models import ProviderResponseError


def public_resolver(_: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    return [ipaddress.ip_address("8.8.8.8")]


@pytest.mark.asyncio
@respx.mock
async def test_search_projects_compact_non_queryable_catalogue_records() -> None:
    route = respx.get("https://www.govdata.de/ckan/api/3/action/package_search").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "count": 2,
                    "results": [
                        {
                            "name": "energy-data",
                            "title": "Energy data",
                            "notes": "Official annual figures.",
                            "metadata_modified": "2026-09-15T10:30:00+00:00",
                            "license_id": "dl-de/by-2-0",
                            "organization": {"title": "Example authority"},
                            "resources": [
                                {
                                    "id": "csv-1",
                                    "name": "Annual CSV",
                                    "url": "https://example.gov/data.csv",
                                    "format": "CSV",
                                }
                            ],
                        }
                    ],
                },
            },
        )
    )

    async with httpx.AsyncClient() as http:
        page = await GovDataClient(http, resolver=public_resolver).search("energy", limit=1)

    assert dict(route.calls[0].request.url.params) == {
        "q": "energy",
        "rows": "1",
        "start": "0",
    }
    assert page.total == 2
    assert page.next_start == 1
    assert page.items[0].provider_id == "energy-data"
    assert page.items[0].publisher == "Example authority"
    assert page.items[0].distributions[0].queryable is False


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"error": "unavailable"}),
        httpx.Response(200, json={"success": False, "error": {"message": "bad query"}}),
    ],
)
async def test_search_rejects_http_and_ckan_application_failures(
    response: httpx.Response,
) -> None:
    respx.get("https://www.govdata.de/ckan/api/3/action/package_search").mock(return_value=response)

    async with httpx.AsyncClient() as http:
        with pytest.raises(ProviderResponseError, match="GovData"):
            await GovDataClient(http, resolver=public_resolver).search("energy")


@pytest.mark.asyncio
@respx.mock
async def test_get_retrieves_one_selected_package() -> None:
    route = respx.get("https://www.govdata.de/ckan/api/3/action/package_show").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "name": "budget-data",
                    "title": "Budget data",
                    "notes": None,
                    "metadata_modified": None,
                    "license_id": None,
                    "organization": None,
                    "resources": [],
                },
            },
        )
    )

    async with httpx.AsyncClient() as http:
        record = await GovDataClient(http, resolver=public_resolver).get("budget-data")

    assert dict(route.calls[0].request.url.params) == {"id": "budget-data"}
    assert record.provider_id == "budget-data"
    assert record.distributions == ()


@pytest.mark.asyncio
@respx.mock
async def test_dcat_distribution_licences_and_publisher_extras_fill_empty_package_fields() -> None:
    respx.get("https://www.govdata.de/ckan/api/3/action/package_show").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "name": "bundeshaushalt-2011",
                    "title": "Bundeshaushalt 2011",
                    "license_id": "",
                    "organization": None,
                    "extras": [{"key": "publisher_name", "value": "Bundesministerium"}],
                    "resources": [
                        {
                            "id": "zip-1",
                            "url": "https://example.gov/plan.zip",
                            "license": "http://dcat-ap.de/def/licenses/dl-by-de/2.0",
                        },
                        {
                            "id": "zip-2",
                            "url": "https://example.gov/plan-2.zip",
                            "license": "http://dcat-ap.de/def/licenses/dl-by-de/2.0",
                        },
                    ],
                },
            },
        )
    )

    async with httpx.AsyncClient() as http:
        record = await GovDataClient(http, resolver=public_resolver).get("bundeshaushalt-2011")

    assert record.licence == "http://dcat-ap.de/def/licenses/dl-by-de/2.0"
    assert record.publisher == "Bundesministerium"
