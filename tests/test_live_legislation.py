"""MCP contract tests for live DIP legislation search with a configured API key."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver import MCPServer

from policy_mcp.adapters.dip import DipClient
from policy_mcp.diagnostics import load_credential
from policy_mcp.legislation import (
    FrozenLegislationCatalog,
    LiveDipLegislation,
    register_legislation_tools,
)
from policy_mcp.references import InMemoryReferenceStore

API_KEY = "test-secret-dip-key"


def public_resolver(_: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    return [ipaddress.ip_address("8.8.8.8")]


def procedure(identifier: str, title: str, gesta: str | None = None) -> dict[str, object]:
    return {
        "id": identifier,
        "typ": "Vorgang",
        "beratungsstand": "Verkündet",
        "vorgangstyp": "Gesetzgebung",
        "wahlperiode": 21,
        "aktualisiert": "2026-09-16T12:30:00+02:00",
        "titel": title,
        **({"gesta": gesta} if gesta else {}),
    }


def position(label: str, date: str) -> dict[str, object]:
    return {
        "id": "9001",
        "vorgangsposition": label,
        "zuordnung": "BT",
        "gang": True,
        "fortsetzung": False,
        "nachtrag": False,
        "vorgangstyp": "Gesetzgebung",
        "typ": "Vorgangsposition",
        "titel": "Tariftreuegesetz",
        "dokumentart": "Plenarprotokoll",
        "vorgang_id": "325840",
        "datum": date,
        "aktualisiert": "2026-09-16T12:30:00+02:00",
        "fundstelle": {
            "id": "7001",
            "dokumentnummer": "21/58",
            "datum": date,
            "dokumentart": "Plenarprotokoll",
            "herausgeber": "BT",
            "urheber": [],
            "anfangsquadrant": "",
        },
        "aktivitaet_anzahl": 0,
    }


class _Dip:
    def __init__(self, *, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, request=request, json={"code": self.status})
        params = request.url.params
        if request.url.path.endswith("/vorgangsposition"):
            documents = [position("2. Beratung", "2026-02-26")]
        elif params.get_list("f.titel") == ["Tariftreue Vergabe"]:
            documents = []
        else:
            documents = [
                procedure("325840", "Gesetz zur Sicherung von Tariftreue bei der Vergabe", "G006"),
                procedure("331662", "Entschließungsantrag zur Tariftreue"),
            ]
        return httpx.Response(
            200,
            request=request,
            json={"numFound": len(documents), "cursor": "c", "documents": documents},
            headers={"content-type": "application/json"},
        )


def build_server(dip: _Dip, *, api_key: str | None = API_KEY) -> MCPServer[None]:
    server: MCPServer[None] = MCPServer(name="policy-legislation")
    live = LiveDipLegislation(
        api_key=lambda: api_key,
        transport=httpx.MockTransport(dip),
        client=lambda http, key, positions: DipClient(
            http,
            api_key=key,
            include_positions=positions,
            resolver=public_resolver,
            min_request_interval=0,
        ),
    )
    register_legislation_tools(
        server,
        FrozenLegislationCatalog.empty(),
        InMemoryReferenceStore(principal="live-legislation-test"),
        live_dip=live,
    )
    return server


def data(result: Any) -> dict[str, Any]:
    assert result.is_error is not True
    assert result.structured_content is not None
    return result.structured_content


async def test_without_a_key_search_explains_how_to_add_one() -> None:
    dip = _Dip()
    server = build_server(dip, api_key=None)

    response = data(
        await server.call_tool("legislation_search", {"jurisdiction": "DE", "query": "Tariftreue"})
    )

    assert response["error"]["code"] == "not_configured"
    assert "Settings > Extensions" in response["error"]["message"]
    assert "dip.bundestag.de" in response["error"]["message"]
    assert dip.requests == []


async def test_live_search_and_procedure_use_the_configured_key() -> None:
    dip = _Dip()
    server = build_server(dip)

    capabilities = data(await server.call_tool("legislation_capabilities", {"source": "dip"}))
    search = data(
        await server.call_tool("legislation_search", {"jurisdiction": "DE", "query": "Tariftreue"})
    )
    detail = data(
        await server.call_tool(
            "legislation_procedure", {"reference": search["items"][0]["reference"]}
        )
    )

    assert capabilities["sources"][0]["state"] == "ready"
    assert [item["identifier"] for item in search["items"]] == ["G006", "331662"]
    assert search["items"][0]["official_url"] == "https://dip.bundestag.de/vorgang/325840"
    assert detail["procedure"]["events"] == [{"date": "2026-02-26", "label": "2. Beratung"}]
    assert all(request.headers["Authorization"] == f"ApiKey {API_KEY}" for request in dip.requests)


async def test_multiword_search_retries_the_longest_word_and_keeps_titles_with_every_word() -> None:
    dip = _Dip()
    server = build_server(dip)

    search = data(
        await server.call_tool(
            "legislation_search", {"jurisdiction": "DE", "query": "Tariftreue Vergabe"}
        )
    )

    assert [request.url.params.get_list("f.titel") for request in dip.requests] == [
        ["Tariftreue Vergabe"],
        ["Tariftreue"],
    ]
    assert [item["identifier"] for item in search["items"]] == ["G006"]


async def test_rejected_key_is_reported_without_exposing_it() -> None:
    server = build_server(_Dip(status=401))

    response = data(
        await server.call_tool("legislation_search", {"jurisdiction": "DE", "identifier": "G006"})
    )

    assert response["error"]["code"] == "not_configured"
    assert response["error"]["retryable"] is False
    assert "rejected the configured API key" in response["error"]["message"]
    assert API_KEY not in str(response)


def test_unresolved_installer_placeholder_counts_as_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DIP_API_KEY", "${user_config.dip_api_key}")
    monkeypatch.setattr("policy_mcp.diagnostics.keyring.get_password", lambda *_: None)

    assert load_credential("DIP_API_KEY") is None
