"""MCP contract tests for actor tools backed by live official sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pytest
from mcp.server.mcpserver import MCPServer

from policy_mcp.actors import LiveActorCatalog, register_actor_tools
from policy_mcp.adapters.actors import (
    ActorSourceRecord,
    ActorSourceSearchResult,
    LiveActorSources,
    SourceDisclosure,
)
from policy_mcp.references import SQLiteReferenceStore
from policy_mcp.research_contracts import Jurisdiction


def lobby_entry(provider_id: str, name: str, wording: str) -> ActorSourceRecord:
    return ActorSourceRecord(
        key=f"lobbyregister:interest_representative:{provider_id}",
        kind="interest_representative",
        scope=Jurisdiction.DE,
        source="lobbyregister",
        provider_id=provider_id,
        display_name=name,
        description="Unternehmen",
        official_url=f"https://www.lobbyregister.bundestag.de/suche/{provider_id}/1",
        source_modified_at="2026-09-01T00:00:00Z",
        historical_supported=True,
        disclosures=(
            SourceDisclosure(
                section_id="activities-and-interests",
                heading="Tätigkeiten und Interessen",
                wording=wording,
                evidence_provider_id=f"{provider_id}-search-result",
            ),
        ),
    )


class _Sources:
    ready_sources = LiveActorSources.ready_sources

    def __init__(self, records: dict[str, tuple[ActorSourceRecord, ...]]) -> None:
        self.records = records
        self.failures: dict[str, str] = {}

    async def search(
        self,
        query: str,
        *,
        scope: Literal["DE", "EU", "BOTH"],
        kind: str,
        source: str | None,
        language: str,
        limit: int,
    ) -> ActorSourceSearchResult:
        del scope, kind, source, language, limit
        return ActorSourceSearchResult(
            records=self.records.get(query, ()),
            successful_sources=() if self.failures else ("lobbyregister",),
            failures=self.failures,
            retrieved_at="2026-09-16T12:00:00Z",
        )


def build_server(sources: Any) -> MCPServer[None]:
    server: MCPServer[None] = MCPServer(name="policy-actors")
    register_actor_tools(
        server,
        LiveActorCatalog(sources),
        SQLiteReferenceStore(principal="live-actor-test"),
    )
    return server


def data(result: Any) -> dict[str, Any]:
    assert result.is_error is not True
    assert result.structured_content is not None
    return result.structured_content


@pytest.fixture(autouse=True)
def data_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLICY_MCP_DATA_DIR", str(tmp_path))


async def test_uncovered_scope_is_unsupported_instead_of_unavailable() -> None:
    server = build_server(LiveActorSources())

    response = data(
        await server.call_tool(
            "actor_search", {"query": "Friedrich Merz", "scope": "DE", "kind": "person"}
        )
    )

    assert response["error"]["code"] == "unsupported"
    assert response["error"]["retryable"] is False
    assert "European Parliament (EU)" in response["error"]["message"]


async def test_scope_both_warns_when_one_jurisdiction_has_no_source() -> None:
    server = build_server(_Sources({}))

    response = data(
        await server.call_tool(
            "actor_search", {"query": "Friedrich Merz", "scope": "BOTH", "kind": "person"}
        )
    )

    assert response["status"] == "partial"
    assert response["warnings"][0]["code"] == "scope_not_covered"


async def test_unreachable_sources_explain_the_reason() -> None:
    sources = _Sources({})
    sources.failures = {"eu_transparency": "The snapshot is still downloading."}
    server = build_server(sources)

    response = data(
        await server.call_tool(
            "actor_search",
            {"query": "BASF", "scope": "EU", "kind": "interest_representative"},
        )
    )

    assert response["error"]["code"] == "temporarily_unavailable"
    assert "still downloading" in response["error"]["message"]


async def test_selected_actor_survives_a_server_restart() -> None:
    siemens = lobby_entry("R001875", "Siemens AG", "Energienetze; Digitalisierung")
    first = build_server(_Sources({"Siemens": (siemens,)}))
    search = data(
        await first.call_tool(
            "actor_search",
            {"query": "Siemens", "scope": "DE", "kind": "interest_representative"},
        )
    )
    reference = search["items"][0]["reference"]

    restarted = build_server(_Sources({}))
    detail = data(
        await restarted.call_tool("actor_get", {"reference": reference, "view": "disclosures"})
    )

    assert detail["status"] == "ok"
    assert detail["actor"]["display_name"] == "Siemens AG"
    assert detail["provenance"][0]["retrieved_at"] == "2026-09-16T12:00:00Z"


async def test_interests_only_consider_actors_from_the_current_topic_search() -> None:
    siemens = lobby_entry("R001875", "Siemens AG", "Energienetze; Digitalisierung")
    hydrogen = lobby_entry("R000999", "Wasserstoff-Verband", "Erneuerbare Energien")
    server = build_server(_Sources({"Siemens": (siemens,), "Wasserstoff": (hydrogen,)}))
    await server.call_tool(
        "actor_search",
        {"query": "Siemens", "scope": "DE", "kind": "interest_representative"},
    )

    response = data(
        await server.call_tool("actor_interests", {"scope": "DE", "query": "Wasserstoff"})
    )

    assert [match["actor_name"] for match in response["matches"]] == ["Wasserstoff-Verband"]
    assert response["matches"][0]["basis"] == "candidate_text_match"
