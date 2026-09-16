"""Public contract tests for the frozen legislation vertical slice."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from policy_mcp.legislation import FrozenLegislationCatalog, register_legislation_tools
from policy_mcp.references import InMemoryReferenceStore

FIXTURE = Path(__file__).parent / "fixtures" / "legislation" / "catalog.json"


def result_data(result: Any) -> dict[str, Any]:
    assert result.is_error is not True
    assert result.structured_content is not None
    return result.structured_content


def build_server(
    *, now: list[datetime] | None = None, cursor_ttl: timedelta = timedelta(minutes=15)
) -> MCPServer[None]:
    clock = (lambda: now[0]) if now is not None else (lambda: datetime(2026, 9, 16, tzinfo=UTC))
    server: MCPServer[None] = MCPServer(name="policy-legislation")
    catalog = FrozenLegislationCatalog.from_json(FIXTURE)
    references = InMemoryReferenceStore(
        principal="local-test-principal",
        clock=clock,
        cursor_ttl=cursor_ttl,
    )
    register_legislation_tools(server, catalog, references)
    return server


async def test_contract_and_dip_search_to_bounded_passage() -> None:
    server = build_server()

    tools = await server.list_tools()
    assert [tool.name for tool in tools] == [
        "legislation_search",
        "legislation_procedure",
        "legislation_records",
        "legislation_read",
        "legislation_changes",
        "legislation_capabilities",
    ]
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.input_schema["additionalProperties"] is False
        assert tool.output_schema is not None

    search = result_data(
        await server.call_tool(
            "legislation_search",
            {"jurisdiction": "DE", "query": "digitale Verwaltung", "limit": 1},
        )
    )
    assert search["status"] == "ok"
    assert len(search["items"]) == 1
    card = search["items"][0]
    assert card["identifier"] == "20/1234"
    assert card["reference"].startswith("ref_")
    assert "dip.bundestag.de" not in card["reference"]
    assert card["official_url"] == "https://dip.bundestag.de/vorgang/101"
    assert card["source_language"] == "de"
    assert search["coverage"][0]["complete"] is False
    assert search["freshness"][0]["indexed_at"] == "2026-09-15T12:05:00Z"
    assert search["provenance"][0]["provider_id"] == "101"

    procedure = result_data(
        await server.call_tool("legislation_procedure", {"reference": card["reference"]})
    )
    assert procedure["status"] == "ok"
    assert procedure["procedure"]["status"] == "Abgeschlossen"
    assert procedure["procedure"]["events"][0]["date"] == "2026-06-01"
    document = procedure["procedure"]["documents"][0]
    assert document["reference"].startswith("ref_")

    passage = result_data(
        await server.call_tool(
            "legislation_read",
            {"reference": document["reference"], "query": "automatisierte Entscheidung"},
        )
    )
    assert passage["status"] == "ok"
    assert passage["passages"][0]["heading"] == "§ 1 Zweck"
    assert passage["passages"][0]["locator"] == {
        "kind": "paragraph",
        "start": "1",
        "end": "2",
    }
    assert "keinen Anspruch" in passage["passages"][0]["text"]
    assert "Ausnahmen" in passage["passages"][0]["text"]
    assert len(str(passage).encode()) < 16_384


async def test_snapshot_pagination_is_query_bound_without_skips() -> None:
    server = build_server()
    arguments = {"jurisdiction": "DE", "query": "Digitalisierung", "limit": 1}

    first = result_data(await server.call_tool("legislation_search", arguments))
    second = result_data(
        await server.call_tool(
            "legislation_search", {**arguments, "cursor": first["continuation"]["cursor"]}
        )
    )
    third = result_data(
        await server.call_tool(
            "legislation_search", {**arguments, "cursor": second["continuation"]["cursor"]}
        )
    )

    identifiers = [page["items"][0]["identifier"] for page in (first, second, third)]
    assert identifiers == ["20/1234", "20/2345", "20/3456"]
    assert len(set(identifiers)) == 3
    assert third["continuation"] is None

    modified_query = result_data(
        await server.call_tool(
            "legislation_search",
            {
                "jurisdiction": "DE",
                "query": "anderes Thema",
                "limit": 1,
                "cursor": first["continuation"]["cursor"],
            },
        )
    )
    assert modified_query["status"] == "error"
    assert modified_query["error"]["code"] == "forged_cursor"


async def test_cellar_identifier_reports_selected_language_and_translation_scope() -> None:
    server = build_server()

    response = result_data(
        await server.call_tool(
            "legislation_search",
            {
                "jurisdiction": "EU",
                "identifier": "CELEX:32024R1689",
                "kind": "legal_text",
                "language": "en",
            },
        )
    )

    assert response["status"] == "ok"
    assert response["items"][0]["source"] == "cellar"
    assert response["items"][0]["source_language"] == "en"
    assert response["items"][0]["requested_language"] == "en"
    assert response["items"][0]["translation_scope"] == "labels_only"


async def test_typed_source_reference_and_cursor_errors() -> None:
    now = [datetime(2026, 9, 16, tzinfo=UTC)]
    server = build_server(now=now, cursor_ttl=timedelta(seconds=1))

    not_configured = result_data(
        await server.call_tool("legislation_search", {"jurisdiction": "EU", "query": "agriculture"})
    )
    assert not_configured["error"]["code"] == "not_configured"

    unsupported = result_data(
        await server.call_tool("legislation_records", {"jurisdiction": "DE", "kind": "speech"})
    )
    assert unsupported["error"]["code"] == "unsupported"

    forged = result_data(
        await server.call_tool("legislation_procedure", {"reference": "ref_modified"})
    )
    assert forged["error"]["code"] == "forged_reference"

    first = result_data(
        await server.call_tool(
            "legislation_search",
            {"jurisdiction": "DE", "query": "Digitalisierung", "limit": 1},
        )
    )
    now[0] += timedelta(seconds=2)
    expired = result_data(
        await server.call_tool(
            "legislation_search",
            {
                "jurisdiction": "DE",
                "query": "Digitalisierung",
                "limit": 1,
                "cursor": first["continuation"]["cursor"],
            },
        )
    )
    assert expired["error"] == {
        "code": "expired_cursor",
        "message": "The continuation expired. Restart the search without a cursor.",
        "retryable": True,
    }


async def test_inputs_are_strict_and_require_exactly_one_search_term() -> None:
    server = build_server()

    with pytest.raises(ToolError):
        await server.call_tool(
            "legislation_search",
            {"jurisdiction": "DE", "query": "digital", "invented": True},
        )
    with pytest.raises(ToolError):
        await server.call_tool("legislation_search", {"jurisdiction": "DE"})
    with pytest.raises(ToolError):
        await server.call_tool(
            "legislation_search",
            {"jurisdiction": "DE", "query": "digital", "identifier": "20/1234"},
        )
