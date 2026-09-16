"""Contract tests for the profile-specific MCP servers."""

from pathlib import Path

import pytest
from mcp.types import CallToolResult

from policy_mcp.server import create_server
from policy_mcp.storage import SyncRecord, open_database, persist_sync_window


def _persist_legislation_record() -> None:
    persist_sync_window(
        "dip",
        window_start="2026-09-15T00:00:00Z",
        window_end="2026-09-16T00:00:00Z",
        records=[
            SyncRecord(
                provider_id="334562",
                provider_version="2026-09-15T12:00:00Z",
                entity_kind="procedure",
                content_hash="a" * 64,
                source_timestamp="2026-09-15T12:00:00Z",
                payload={
                    "key": "dip:vorgang:334562",
                    "kind": "procedure",
                    "jurisdiction": "DE",
                    "source": "dip",
                    "provider_id": "334562",
                    "identifier": "334562",
                    "title": "Gesetz zur digitalen Verwaltung",
                    "abstract": "Ein Verfahren zur digitalen Verwaltung.",
                    "subjects": ["Digitalisierung", "Verwaltung"],
                    "status": "Beratung",
                    "source_language": "de",
                    "official_url": "https://dip.bundestag.de/vorgang/334562",
                    "source_modified_at": "2026-09-15T12:00:00Z",
                    "events": [],
                    "document_keys": [],
                },
            )
        ],
    )


async def test_legislation_profile_exposes_stable_research_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    server = create_server("legislation", principal="local-test")

    assert server.name == "policy-legislation"
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
        assert tool.input_schema["additionalProperties"] is False
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True

    result = await server.call_tool("legislation_capabilities", {})
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    assert result.structured_content["status"] == "ok"
    assert {item["state"] for item in result.structured_content["sources"]} == {"not_configured"}


async def test_legislation_profile_serves_latest_validated_database_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    _persist_legislation_record()

    server = create_server("legislation", principal="local-test")
    capabilities = await server.call_tool("legislation_capabilities", {"source": "dip"})
    search = await server.call_tool(
        "legislation_search",
        {"jurisdiction": "DE", "query": "digitale Verwaltung", "source": "dip"},
    )

    assert isinstance(capabilities, CallToolResult)
    assert isinstance(search, CallToolResult)
    assert capabilities.structured_content is not None
    assert capabilities.structured_content["sources"][0]["state"] == "ready"
    assert capabilities.structured_content["sources"][0]["operations"] == [
        "search",
        "procedure",
    ]
    assert search.structured_content is not None
    assert search.structured_content["status"] == "ok"
    assert search.structured_content["items"][0]["identifier"] == "334562"


async def test_older_backfill_does_not_replace_the_current_procedure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    _persist_legislation_record()
    persist_sync_window(
        "dip",
        window_start="2026-01-01T00:00:00Z",
        window_end="2026-01-02T00:00:00Z",
        records=[
            SyncRecord(
                provider_id="334562",
                provider_version="2026-01-01T12:00:00Z",
                entity_kind="procedure",
                content_hash="c" * 64,
                source_timestamp="2026-01-01T12:00:00Z",
                payload={
                    "key": "dip:vorgang:334562",
                    "kind": "procedure",
                    "jurisdiction": "DE",
                    "source": "dip",
                    "provider_id": "334562",
                    "identifier": "334562",
                    "title": "OLD procedure title",
                    "abstract": "Older digital administration record.",
                    "subjects": ["Digitalisierung"],
                    "status": "Older status",
                    "source_language": "de",
                    "official_url": "https://dip.bundestag.de/vorgang/334562",
                    "source_modified_at": "2026-01-01T12:00:00Z",
                    "events": [],
                    "document_keys": [],
                },
            )
        ],
    )

    server = create_server("legislation", principal="local-test")
    search = await server.call_tool(
        "legislation_search",
        {"jurisdiction": "DE", "query": "digitale Verwaltung", "source": "dip"},
    )

    assert isinstance(search, CallToolResult)
    assert search.structured_content is not None
    assert search.structured_content["items"][0]["title"] == ("Gesetz zur digitalen Verwaltung")
    with open_database() as connection:
        indexed_title = connection.execute(
            "SELECT title FROM record_search WHERE record_id = "
            "(SELECT id FROM records WHERE source_id = 'dip' AND provider_id = '334562')"
        ).fetchone()[0]
        watermark = connection.execute(
            "SELECT completed_watermark FROM sync_state WHERE source_id = 'dip'"
        ).fetchone()[0]
    assert indexed_title == "Gesetz zur digitalen Verwaltung"
    assert watermark == "2026-09-16T00:00:00Z"


async def test_legislation_profile_ignores_invalid_database_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    persist_sync_window(
        "dip",
        window_start="2026-09-15T00:00:00Z",
        window_end="2026-09-16T00:00:00Z",
        records=[
            SyncRecord(
                provider_id="broken",
                provider_version="1",
                entity_kind="procedure",
                content_hash="b" * 64,
                source_timestamp=None,
                payload={"source": "dip", "title": "Incomplete"},
            )
        ],
    )

    server = create_server("legislation", principal="local-test")
    capabilities = await server.call_tool("legislation_capabilities", {"source": "dip"})

    assert isinstance(capabilities, CallToolResult)
    assert capabilities.structured_content is not None
    assert capabilities.structured_content["sources"][0]["state"] == "not_configured"


async def test_actor_profile_exposes_stable_research_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    server = create_server("actors", principal="local-test")

    tools = await server.list_tools()
    assert [tool.name for tool in tools] == [
        "actor_search",
        "actor_get",
        "actor_interests",
        "actor_capabilities",
    ]
    for tool in tools:
        assert tool.input_schema["additionalProperties"] is False
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.idempotent_hint is True

    result = await server.call_tool("actor_capabilities", {})
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    assert result.structured_content["status"] == "ok"
    assert {item["source"] for item in result.structured_content["sources"]} == {
        "ep",
        "eu_transparency",
        "eu_whoiswho",
        "lobbyregister",
    }
    assert {item["state"] for item in result.structured_content["sources"]} == {"ready"}


async def test_evidence_profile_exposes_stable_research_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))
    server = create_server("evidence", principal="local-test")

    tools = await server.list_tools()
    assert [tool.name for tool in tools] == [
        "evidence_search",
        "evidence_describe",
        "evidence_query",
        "evidence_get",
        "evidence_capabilities",
    ]
    for tool in tools:
        assert tool.input_schema["additionalProperties"] is False
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.idempotent_hint is True

    result = await server.call_tool("evidence_capabilities", {})
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    assert result.structured_content["status"] == "ok"
    assert {item["state"] for item in result.structured_content["sources"]} == {
        "ready",
        "not_configured",
        "unsupported",
    }
    by_route = {item["route"]: item for item in result.structured_content["sources"]}
    assert by_route["govdata.catalogue"]["operations"] == ["search", "get"]
