"""Public MCP contract tests for the frozen evidence vertical slice."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from policy_mcp.evidence import FrozenEvidenceCatalog, register_evidence_tools
from policy_mcp.references import InMemoryReferenceStore

FIXTURE = Path(__file__).parent / "fixtures" / "evidence" / "catalog.json"


def build_server() -> MCPServer[None]:
    server: MCPServer[None] = MCPServer(name="policy-evidence")
    register_evidence_tools(
        server,
        FrozenEvidenceCatalog.from_json(FIXTURE),
        InMemoryReferenceStore(principal="evidence-test-principal"),
    )
    return server


def data(result: Any) -> dict[str, Any]:
    assert result.is_error is not True
    assert result.structured_content is not None
    assert len(str(result.structured_content).encode()) < 16_384
    return result.structured_content


async def test_contract_and_genesis_search_describe_query_path() -> None:
    server = build_server()
    tools = await server.list_tools()

    assert [tool.name for tool in tools] == [
        "evidence_search",
        "evidence_describe",
        "evidence_query",
        "evidence_get",
        "evidence_capabilities",
    ]
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.input_schema["additionalProperties"] is False
        assert tool.output_schema is not None

    search = data(
        await server.call_tool(
            "evidence_search",
            {"query": "Erwerbstätige", "source": "genesis", "kind": "dataset"},
        )
    )
    assert search["status"] == "ok"
    assert search["items"][0]["kind"] == "dataset"
    assert "values" not in search["items"][0]
    reference = search["items"][0]["reference"]

    description = data(await server.call_tool("evidence_describe", {"reference": reference}))
    assert description["dataset"]["schema_version"] == "sha256:genesis-v1"
    assert description["dataset"]["unit"] == "Tausend Personen"
    assert description["dataset"]["dimensions"][0]["dimension_id"] == "GEO"
    assert description["dataset"]["dimensions"][0]["members"][0] == {
        "member_id": "DE",
        "label": "Deutschland",
    }

    result = data(
        await server.call_tool(
            "evidence_query",
            {
                "reference": reference,
                "schema_version": "sha256:genesis-v1",
                "selections": [
                    {"dimension_id": "GEO", "member_ids": ["DE", "BE"]},
                    {"dimension_id": "TIME", "member_ids": ["2024", "2025"]},
                    {"dimension_id": "SEX", "member_ids": ["TOTAL"]},
                ],
                "measures": ["value"],
            },
        )
    )
    assert result["status"] == "ok"
    assert len(result["rows"]) == 4
    assert result["rows"][0]["unit"] == "Tausend Personen"
    assert result["rows"][0]["scale"] == 1000
    assert result["rows"][0]["period"] == "2024"
    assert result["rows"][0]["territory"] == "Deutschland"
    assert result["rows"][0]["footnotes"] == ["Vorläufiges Ergebnis"]
    statuses = {row["values"][0]["status"] for row in result["rows"]}
    symbols = {row["values"][0]["symbol"] for row in result["rows"]}
    assert statuses == {"value", "missing", "suppressed"}
    assert {"-", "x"}.issubset(symbols)
    assert result["provenance"][0]["source"] == "genesis"
    assert result["coverage"][0]["complete"] is False


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"schema_version": "stale"}, "stale_schema"),
        (
            {"selections": [{"dimension_id": "UNKNOWN", "member_ids": ["x"]}]},
            "unknown_dimension",
        ),
        (
            {
                "selections": [
                    {"dimension_id": "GEO", "member_ids": ["DE"]},
                    {"dimension_id": "GEO", "member_ids": ["BE"]},
                ]
            },
            "duplicate_selection",
        ),
        (
            {"selections": [{"dimension_id": "GEO", "member_ids": ["UNKNOWN"]}]},
            "unknown_member",
        ),
        (
            {"selections": [{"dimension_id": "GEO", "member_ids": ["DE", "DE"]}]},
            "duplicate_member",
        ),
    ],
)
async def test_dataset_query_rejects_stale_or_unknown_contract_values(
    changes: dict[str, Any], code: str
) -> None:
    server = build_server()
    search = data(
        await server.call_tool("evidence_search", {"query": "Erwerbstätige", "source": "genesis"})
    )
    arguments: dict[str, Any] = {
        "reference": search["items"][0]["reference"],
        "schema_version": "sha256:genesis-v1",
        "selections": [
            {"dimension_id": "GEO", "member_ids": ["DE"]},
            {"dimension_id": "TIME", "member_ids": ["2024"]},
            {"dimension_id": "SEX", "member_ids": ["TOTAL"]},
        ],
        "measures": ["value"],
    }
    arguments.update(changes)

    response = data(await server.call_tool("evidence_query", arguments))

    assert response["status"] == "error"
    assert response["error"]["code"] == code


async def test_query_preflight_rejects_more_than_25_rows_or_250_cells() -> None:
    server = build_server()
    search = data(await server.call_tool("evidence_search", {"query": "Erwerbstätige"}))
    reference = search["items"][0]["reference"]
    common = {"reference": reference, "schema_version": "sha256:genesis-v1"}

    too_many_rows = data(
        await server.call_tool(
            "evidence_query",
            {
                **common,
                "selections": [
                    {"dimension_id": "GEO", "member_ids": ["DE", "BE", "BY", "HH", "NW"]},
                    {
                        "dimension_id": "TIME",
                        "member_ids": ["2020", "2021", "2022", "2023", "2024", "2025"],
                    },
                    {"dimension_id": "SEX", "member_ids": ["TOTAL"]},
                ],
                "measures": ["value"],
            },
        )
    )
    assert too_many_rows["error"]["code"] == "oversized"
    assert too_many_rows["error"]["detail"]["rows"] == 30

    too_many_cells = data(
        await server.call_tool(
            "evidence_query",
            {
                **common,
                "selections": [
                    {"dimension_id": "GEO", "member_ids": ["DE", "BE", "BY", "HH", "NW"]},
                    {
                        "dimension_id": "TIME",
                        "member_ids": ["2020", "2021", "2022", "2023", "2024"],
                    },
                    {"dimension_id": "SEX", "member_ids": ["TOTAL"]},
                ],
                "measures": [
                    "value",
                    "male",
                    "female",
                    "employees",
                    "self_employed",
                    "full_time",
                    "part_time",
                    "domestic",
                    "national",
                    "seasonally_adjusted",
                    "unadjusted",
                ],
            },
        )
    )
    assert too_many_cells["error"]["code"] == "oversized"
    assert too_many_cells["error"]["detail"]["cells"] == 275


async def test_raw_query_language_and_extra_fields_are_rejected_by_schema() -> None:
    server = build_server()

    with pytest.raises(ToolError):
        await server.call_tool(
            "evidence_search", {"query": "digital", "raw_query": "SELECT * FROM data"}
        )


async def test_budget_stage_flow_unit_and_hierarchy_are_preserved() -> None:
    server = build_server()
    search = data(
        await server.call_tool(
            "evidence_search",
            {
                "query": "Digitalisierung",
                "source": "federal_budget",
                "kind": "budget",
                "stage": "enacted",
                "flow": "expenditure",
            },
        )
    )
    assert len(search["items"]) == 2
    parent, child = search["items"]

    detail = data(await server.call_tool("evidence_get", {"reference": parent["reference"]}))
    assert detail["record"]["kind"] == "budget"
    assert detail["record"]["stage"] == "enacted"
    assert detail["record"]["flow"] == "expenditure"
    assert detail["record"]["source_unit"] == "thousand_eur"
    assert detail["record"]["may_sum_with_children"] is False

    aggregate = data(
        await server.call_tool(
            "evidence_query",
            {"references": [parent["reference"], child["reference"]]},
        )
    )
    assert aggregate["status"] == "error"
    assert aggregate["error"]["code"] == "double_counting"


async def test_notice_funding_and_catalogue_entities_remain_distinct() -> None:
    server = build_server()

    async def selected(source: str, kind: str, query: str = "Digitalisierung") -> dict[str, Any]:
        result = data(
            await server.call_tool(
                "evidence_search", {"query": query, "source": source, "kind": kind}
            )
        )
        return data(
            await server.call_tool("evidence_get", {"reference": result["items"][0]["reference"]})
        )["record"]

    notice = await selected("ted", "notice")
    procedure = await selected("ted", "procurement_procedure")
    lot = await selected("ted", "lot")
    award = await selected("ted", "award")
    assert {notice["kind"], procedure["kind"], lot["kind"], award["kind"]} == {
        "notice",
        "procurement_procedure",
        "lot",
        "award",
    }
    assert (
        len(
            {
                notice["provider_id"],
                procedure["provider_id"],
                lot["provider_id"],
                award["provider_id"],
            }
        )
        == 4
    )

    call = await selected("funding_tenders", "funding_call")
    project = await selected("funding_tenders", "funded_project")
    assert call["kind"] == "funding_call"
    assert "deadline" in call
    assert project["kind"] == "funded_project"
    assert "grant_amount" in project

    catalogue = await selected("govdata", "catalogue", "Digitalisierungsindex")
    assert catalogue["kind"] == "catalogue"
    assert catalogue["distributions"][0]["queryable"] is False


async def test_search_pagination_and_capabilities_report_disabled_routes() -> None:
    server = build_server()
    first = data(
        await server.call_tool("evidence_search", {"query": "Digitalisierung", "limit": 2})
    )
    second = data(
        await server.call_tool(
            "evidence_search",
            {
                "query": "Digitalisierung",
                "limit": 2,
                "cursor": first["continuation"]["cursor"],
            },
        )
    )
    first_ids = {item["provider_id"] for item in first["items"]}
    second_ids = {item["provider_id"] for item in second["items"]}
    assert first_ids.isdisjoint(second_ids)

    capabilities = data(await server.call_tool("evidence_capabilities", {}))
    by_route = {item["route"]: item["state"] for item in capabilities["sources"]}
    assert by_route["genesis.query"] == "ready"
    assert by_route["govdata.distribution_query"] == "unsupported"
    assert by_route["federal_budget.actuals"] == "not_configured"
