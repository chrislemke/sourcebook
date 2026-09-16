"""MCP contract tests for the frozen actor vertical slice."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from policy_mcp.actors import FrozenActorCatalog, register_actor_tools
from policy_mcp.references import InMemoryReferenceStore

FIXTURE = Path(__file__).parent / "fixtures" / "actors" / "catalog.json"


def result_data(result: Any) -> dict[str, Any]:
    assert result.is_error is not True
    assert result.structured_content is not None
    return result.structured_content


def build_server() -> MCPServer[None]:
    server: MCPServer[None] = MCPServer(name="policy-actors")
    catalog = FrozenActorCatalog.from_json(FIXTURE)
    references = InMemoryReferenceStore(
        principal="actor-test-principal",
        clock=lambda: datetime(2026, 9, 16, tzinfo=UTC),
    )
    register_actor_tools(server, catalog, references)
    return server


async def test_actor_search_contract_keeps_duplicate_names_as_distinct_identities() -> None:
    server = build_server()

    tools = await server.list_tools()
    assert [tool.name for tool in tools] == [
        "actor_search",
        "actor_get",
        "actor_interests",
        "actor_capabilities",
    ]
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.input_schema["additionalProperties"] is False
        assert tool.output_schema is not None

    response = result_data(
        await server.call_tool(
            "actor_search",
            {"query": "Maria Müller", "scope": "EU", "kind": "person", "limit": 10},
        )
    )

    assert response["status"] == "ok"
    assert [item["provider_id"] for item in response["items"]] == ["1001", "P-77"]
    assert len({item["reference"] for item in response["items"]}) == 2
    assert all(item["reference"].startswith("ref_") for item in response["items"])
    assert response["coverage"]
    assert response["freshness"]
    assert len(str(response).encode()) < 16_384


async def test_search_pagination_is_bounded_and_query_bound() -> None:
    server = build_server()
    arguments = {
        "query": "frozen public disclosure",
        "scope": "BOTH",
        "kind": "interest_representative",
        "limit": 1,
    }

    first = result_data(await server.call_tool("actor_search", arguments))
    second = result_data(
        await server.call_tool(
            "actor_search",
            {**arguments, "cursor": first["continuation"]["cursor"]},
        )
    )

    assert [first["items"][0]["provider_id"], second["items"][0]["provider_id"]] == [
        "R-100",
        "R-200",
    ]
    assert second["continuation"] is None

    forged = result_data(
        await server.call_tool(
            "actor_search",
            {
                **arguments,
                "query": "different",
                "cursor": first["continuation"]["cursor"],
            },
        )
    )
    assert forged["error"]["code"] == "forged_cursor"


async def test_requested_actor_views_retain_dated_predicates_and_disclosure_wording() -> None:
    server = build_server()
    people = result_data(
        await server.call_tool(
            "actor_search",
            {"query": "Maria Müller", "scope": "EU", "kind": "person"},
        )
    )
    person_ref = people["items"][0]["reference"]

    roles = result_data(
        await server.call_tool("actor_get", {"reference": person_ref, "view": "roles"})
    )
    assert roles["actor"]["roles"][0] == {
        "predicate": "member_of",
        "label": "Member",
        "organisation_id": "EP",
        "organisation_name": "European Parliament",
        "valid_from": "2024-07-16",
        "valid_to": None,
        "provenance": roles["actor"]["roles"][0]["provenance"],
    }
    assert roles["actor"]["description"] is None
    assert roles["actor"]["disclosures"] == []

    representatives = result_data(
        await server.call_tool(
            "actor_search",
            {
                "query": "Forum Klimawende",
                "scope": "DE",
                "kind": "interest_representative",
            },
        )
    )
    representative_ref = representatives["items"][0]["reference"]
    relationships = result_data(
        await server.call_tool(
            "actor_get",
            {"reference": representative_ref, "view": "relationships", "limit": 10},
        )
    )
    assert [item["basis"] for item in relationships["actor"]["relationships"]] == [
        "explicit_provider_link",
        "candidate_text_match",
    ]
    assert relationships["actor"]["relationships"][0]["predicate"] == (
        "declared_regulatory_project"
    )

    disclosures = result_data(
        await server.call_tool(
            "actor_get",
            {"reference": representative_ref, "view": "disclosures"},
        )
    )
    disclosure = disclosures["actor"]["disclosures"][0]
    assert disclosure["wording"] == (
        "Erneuerbare Energien, Klimaanpassung und digitale Energienetze"
    )
    assert disclosure["spending_range"] == "100.001 bis 110.000 Euro"
    assert disclosure["clients"] == ["Stiftung Zukunft"]


async def test_actor_get_relationship_view_has_stable_continuation() -> None:
    server = build_server()
    search = result_data(
        await server.call_tool(
            "actor_search",
            {
                "query": "Forum Klimawende",
                "scope": "DE",
                "kind": "interest_representative",
            },
        )
    )
    reference = search["items"][0]["reference"]

    first = result_data(
        await server.call_tool(
            "actor_get",
            {"reference": reference, "view": "relationships", "limit": 1},
        )
    )
    second = result_data(
        await server.call_tool(
            "actor_get",
            {
                "reference": reference,
                "view": "relationships",
                "limit": 1,
                "cursor": first["continuation"]["cursor"],
            },
        )
    )

    assert first["actor"]["relationships"][0]["basis"] == "explicit_provider_link"
    assert second["actor"]["relationships"][0]["basis"] == "candidate_text_match"
    assert second["continuation"] is None


async def test_historical_request_returns_typed_coverage_error() -> None:
    server = build_server()
    search = result_data(
        await server.call_tool(
            "actor_search",
            {"query": "DG ENER", "scope": "EU", "kind": "institution"},
        )
    )

    response = result_data(
        await server.call_tool(
            "actor_get",
            {
                "reference": search["items"][0]["reference"],
                "view": "overview",
                "as_of": "2020-01-01",
            },
        )
    )

    assert response["status"] == "error"
    assert response["error"]["code"] == "unsupported"
    assert "historical" in response["coverage"][0]["limitations"][1]


async def test_interests_preserve_observation_limits_without_judgment_or_contacts() -> None:
    server = build_server()

    response = result_data(
        await server.call_tool(
            "actor_interests",
            {"scope": "DE", "query": "Energienetze", "limit": 10},
        )
    )

    assert response["status"] == "ok"
    assert {item["basis"] for item in response["matches"]} == {
        "disclosure_text",
        "candidate_text_match",
    }
    assert response["warnings"][0]["code"] == "observed_absent"
    serialized = str(response).casefold()
    for forbidden in (
        "influence_score",
        "alignment_score",
        "causation_score",
        "contact_email",
        "phone",
        "postal_address",
    ):
        assert forbidden not in serialized


async def test_capabilities_distinguish_frozen_acceptance_from_blocked_routes() -> None:
    server = build_server()

    response = result_data(await server.call_tool("actor_capabilities", {}))
    states = {item["source"]: item["state"] for item in response["sources"]}

    assert states["ep_acceptance"] == "ready"
    assert states["whoiswho_acceptance"] == "ready"
    assert states["register_acceptance"] == "ready"
    assert states["lobbyregister"] == "not_configured"
    assert states["eu_transparency"] == "not_configured"
    assert response["freshness"]
    assert response["coverage"]


async def test_references_are_principal_bound_and_inputs_are_strict() -> None:
    first = build_server()
    second = build_server()
    search = result_data(
        await first.call_tool(
            "actor_search",
            {"query": "DG ENER", "scope": "EU", "kind": "institution"},
        )
    )

    forged = result_data(
        await second.call_tool(
            "actor_get",
            {"reference": search["items"][0]["reference"], "view": "overview"},
        )
    )
    assert forged["error"]["code"] == "forged_reference"

    with pytest.raises(ToolError):
        await first.call_tool(
            "actor_search",
            {
                "query": "DG ENER",
                "scope": "EU",
                "kind": "institution",
                "invented": True,
            },
        )
    with pytest.raises(ToolError):
        await first.call_tool("actor_interests", {"scope": "EU"})
