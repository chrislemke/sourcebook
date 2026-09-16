"""Public contract tests for the GENESIS evidence adapter."""

from __future__ import annotations

import ipaddress
from decimal import Decimal

import httpx
import pytest
import respx

from policy_mcp.adapters.genesis import GenesisClient
from policy_mcp.evidence_models import (
    DatasetSelection,
    DatasetValidationError,
    ProviderResponseError,
    ResultTooLargeError,
)

BASE_URL = "https://genesis.destatis.de/genesisWS/rest/2020"
TOKEN = "private-genesis-token"


def public_resolver(_: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    return [ipaddress.ip_address("8.8.8.8")]


def metadata_response(
    *,
    measures: list[str] | None = None,
    time_members: list[str] | None = None,
) -> httpx.Response:
    """Build a frozen metadata response for query-validation tests."""
    selected_measures = measures or ["value"]
    selected_times = time_members or ["2023", "2024"]
    return httpx.Response(
        200,
        json={
            "Status": {"Code": 0},
            "Object": {
                "Code": "12411-0001",
                "Content": "Population by year",
                "SchemaVersion": "structure-7",
                "Unit": "people",
                "Measures": selected_measures,
                "Dimensions": [
                    {
                        "Code": "TIME",
                        "Content": "Year",
                        "Values": [
                            {"Code": member, "Content": member} for member in selected_times
                        ],
                    },
                    {
                        "Code": "REGION",
                        "Content": "Territory",
                        "Values": [{"Code": "DE", "Content": "Germany"}],
                    },
                ],
            },
        },
    )


@pytest.mark.asyncio
@respx.mock
async def test_search_posts_credentials_in_headers_and_returns_table_cards() -> None:
    route = respx.post(f"{BASE_URL}/find/find").mock(
        return_value=httpx.Response(
            200,
            json={
                "Status": {"Code": 0, "Content": "Success"},
                "List": [
                    {
                        "Code": "12411-0001",
                        "Content": "Population by year",
                        "Description": "Official population table",
                    }
                ],
            },
        )
    )

    async with httpx.AsyncClient() as http:
        page = await GenesisClient(http, token=TOKEN, resolver=public_resolver).search(
            "population", limit=3
        )

    request = route.calls[0].request
    assert request.headers["username"] == TOKEN
    assert "population" in request.content.decode()
    assert page.items[0].provider_id == "12411-0001"
    assert TOKEN not in page.model_dump_json()


@pytest.mark.asyncio
@respx.mock
async def test_nonzero_application_status_is_a_typed_failure_without_token_leakage() -> None:
    respx.post(f"{BASE_URL}/find/find").mock(
        return_value=httpx.Response(
            200,
            json={"Status": {"Code": 22, "Content": f"Invalid token {TOKEN}"}, "List": []},
        )
    )

    async with httpx.AsyncClient() as http:
        with pytest.raises(ProviderResponseError) as caught:
            await GenesisClient(http, token=TOKEN, resolver=public_resolver).search("population")

    assert TOKEN not in str(caught.value)


@pytest.mark.asyncio
@respx.mock
async def test_describe_returns_a_versioned_dimension_schema() -> None:
    route = respx.post(f"{BASE_URL}/metadata/table").mock(
        return_value=httpx.Response(
            200,
            json={
                "Status": {"Code": 0, "Content": "Success"},
                "Object": {
                    "Code": "12411-0001",
                    "Content": "Population by year",
                    "SchemaVersion": "structure-7",
                    "Unit": "people",
                    "Measures": ["value"],
                    "Dimensions": [
                        {
                            "Code": "TIME",
                            "Content": "Year",
                            "Values": [
                                {"Code": "2023", "Content": "2023"},
                                {"Code": "2024", "Content": "2024"},
                            ],
                        },
                        {
                            "Code": "REGION",
                            "Content": "Territory",
                            "Values": [{"Code": "DE", "Content": "Germany"}],
                        },
                    ],
                },
            },
        )
    )

    async with httpx.AsyncClient() as http:
        description = await GenesisClient(http, token=TOKEN, resolver=public_resolver).describe(
            "12411-0001"
        )

    assert route.calls[0].request.method == "POST"
    assert description.schema_version == "structure-7"
    assert description.dimensions[0].dimension_id == "TIME"
    assert description.dimensions[0].members[1].member_id == "2024"


@pytest.mark.asyncio
@respx.mock
async def test_query_validates_against_describe_and_preserves_numeric_source_text() -> None:
    respx.post(f"{BASE_URL}/metadata/table").mock(
        return_value=httpx.Response(
            200,
            json={
                "Status": {"Code": 0},
                "Object": {
                    "Code": "12411-0001",
                    "Content": "Population by year",
                    "SchemaVersion": "structure-7",
                    "Unit": "people",
                    "Measures": ["population", "protected", "unknown"],
                    "Dimensions": [
                        {
                            "Code": "TIME",
                            "Content": "Year",
                            "Values": [{"Code": "2024", "Content": "2024"}],
                        },
                        {
                            "Code": "REGION",
                            "Content": "Territory",
                            "Values": [{"Code": "DE", "Content": "Germany"}],
                        },
                    ],
                },
            },
        )
    )
    data_route = respx.post(f"{BASE_URL}/data/table").mock(
        return_value=httpx.Response(
            200,
            json={
                "Status": {"Code": 0},
                "Object": {
                    "Rows": [
                        {
                            "Dimensions": {"TIME": "2024", "REGION": "DE"},
                            "Values": ["1.234,5", "X", "."],
                        }
                    ]
                },
            },
        )
    )

    async with httpx.AsyncClient() as http:
        client = GenesisClient(http, token=TOKEN, resolver=public_resolver)
        await client.describe("12411-0001")
        result = await client.query(
            "12411-0001",
            schema_version="structure-7",
            selections=(
                DatasetSelection(dimension_id="TIME", member_ids=("2024",)),
                DatasetSelection(dimension_id="REGION", member_ids=("DE",)),
            ),
            measures=("population", "protected", "unknown"),
        )

    assert data_route.calls[0].request.method == "POST"
    assert result.rows[0].cells[0].value == Decimal("1234.5")
    assert result.rows[0].cells[0].source_text == "1.234,5"
    assert result.rows[0].cells[1].status == "suppressed"
    assert result.rows[0].cells[1].source_text == "X"
    assert result.rows[0].cells[2].status == "missing"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("schema_version", "selections"),
    [
        (
            "old-structure",
            (DatasetSelection(dimension_id="TIME", member_ids=("2024",)),),
        ),
        (
            "structure-7",
            (DatasetSelection(dimension_id="UNKNOWN", member_ids=("2024",)),),
        ),
        (
            "structure-7",
            (DatasetSelection(dimension_id="TIME", member_ids=("2099",)),),
        ),
        (
            "structure-7",
            (
                DatasetSelection(dimension_id="TIME", member_ids=("2024",)),
                DatasetSelection(dimension_id="TIME", member_ids=("2023",)),
            ),
        ),
        (
            "structure-7",
            (DatasetSelection(dimension_id="TIME", member_ids=("2024", "2024")),),
        ),
    ],
)
async def test_query_rejects_stale_or_invalid_typed_selections_before_request(
    schema_version: str,
    selections: tuple[DatasetSelection, ...],
) -> None:
    respx.post(f"{BASE_URL}/metadata/table").mock(return_value=metadata_response())
    data_route = respx.post(f"{BASE_URL}/data/table").mock(return_value=httpx.Response(500))

    async with httpx.AsyncClient() as http:
        client = GenesisClient(http, token=TOKEN, resolver=public_resolver)
        await client.describe("12411-0001")
        with pytest.raises(DatasetValidationError):
            await client.query(
                "12411-0001",
                schema_version=schema_version,
                selections=selections,
            )

    assert data_route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_query_rejects_row_and_cell_budgets_before_request() -> None:
    measures = [f"measure-{index}" for index in range(11)]
    time_members = [str(year) for year in range(2000, 2025)]
    respx.post(f"{BASE_URL}/metadata/table").mock(
        return_value=metadata_response(measures=measures, time_members=time_members)
    )
    data_route = respx.post(f"{BASE_URL}/data/table").mock(return_value=httpx.Response(500))

    async with httpx.AsyncClient() as http:
        client = GenesisClient(http, token=TOKEN, resolver=public_resolver)
        await client.describe("12411-0001")
        with pytest.raises(ResultTooLargeError, match="25 rows"):
            await client.query(
                "12411-0001",
                schema_version="structure-7",
                selections=(DatasetSelection(dimension_id="TIME", member_ids=("2000",)),),
                row_limit=26,
            )
        with pytest.raises(ResultTooLargeError, match="250-cell"):
            await client.query(
                "12411-0001",
                schema_version="structure-7",
                selections=(DatasetSelection(dimension_id="TIME", member_ids=tuple(time_members)),),
                measures=tuple(measures),
            )

    assert data_route.call_count == 0
