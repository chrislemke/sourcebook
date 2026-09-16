"""Frozen provider-contract tests for the official DIP API boundary."""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from policy_mcp.adapters.dip import (
    DipAuthenticationError,
    DipClient,
    DipProviderError,
)

API_KEY = "test-secret-dip-key"
BASE_URL = "https://search.dip.bundestag.de/api/v1"


def public_resolver(_: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    return [ipaddress.ip_address("8.8.8.8")]


def procedure_payload(*, identifier: str = "334562") -> dict[str, object]:
    return {
        "id": identifier,
        "typ": "Vorgang",
        "beratungsstand": "Überwiesen",
        "vorgangstyp": "Gesetzgebung",
        "wahlperiode": 21,
        "initiative": ["Bundesregierung"],
        "datum": "2026-07-08",
        "aktualisiert": "2026-09-16T12:30:00+02:00",
        "titel": "Gesetz zur Stärkung digitaler Ermittlungsbefugnisse",
        "abstract": "Änderung des geltenden Rechts",
        "sachgebiet": ["Innere Sicherheit"],
        "deskriptor": [
            {"name": "Polizeiliches Informationssystem", "typ": "Sachbegriffe", "fundstelle": True}
        ],
        "gesta": "B045",
        "zustimmungsbeduerftigkeit": ["Ja, laut Gesetzentwurf"],
        "vorgang_verlinkung": [
            {
                "id": "334563",
                "verweisung": "Bundesratsverfahren",
                "titel": "Beratung im Bundesrat",
                "wahlperiode": 21,
                "gesta": "B045",
            }
        ],
    }


def position_payload(
    *,
    identifier: str,
    institution: str,
    number: str,
    document_id: str,
    label: str,
) -> dict[str, object]:
    return {
        "id": identifier,
        "vorgangsposition": label,
        "zuordnung": institution,
        "gang": True,
        "fortsetzung": False,
        "nachtrag": False,
        "vorgangstyp": "Gesetzgebung",
        "typ": "Vorgangsposition",
        "titel": "Gesetz zur Stärkung digitaler Ermittlungsbefugnisse",
        "dokumentart": "Drucksache",
        "vorgang_id": "334562",
        "datum": "2026-05-26",
        "aktualisiert": "2026-09-16T12:30:00+02:00",
        "fundstelle": {
            "id": document_id,
            "dokumentnummer": number,
            "datum": "2026-05-26",
            "dokumentart": "Drucksache",
            "herausgeber": institution,
            "urheber": ["Bundesregierung"],
            "pdf_url": f"https://dserver.bundestag.de/btd/21/061/{number.replace('/', '')}.pdf",
            "drucksachetyp": "Gesetzentwurf",
        },
        "aktivitaet_anzahl": 0,
    }


def response(request: httpx.Request, payload: object, *, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        request=request,
        json=payload,
        headers={"content-type": "application/json"},
    )


@pytest.mark.asyncio
async def test_fetch_procedure_preserves_status_labels_dates_positions_and_documents() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == f"ApiKey {API_KEY}"
        assert "apikey" not in request.url.params
        assert not any(key in request.url.params for key in ("q", "f.titel", "query"))
        if request.url.path.endswith("/vorgang"):
            assert request.url.params.get("f.id") == "334562"
            return response(
                request,
                {"numFound": 1, "cursor": "procedure-next", "documents": [procedure_payload()]},
            )
        assert request.url.path.endswith("/vorgangsposition")
        assert request.url.params.get("f.vorgang") == "334562"
        if request.url.params.get("cursor") is None:
            documents = [
                position_payload(
                    identifier="1001",
                    institution="BT",
                    number="21/6131",
                    document_id="2001",
                    label="1. Beratung",
                ),
                position_payload(
                    identifier="1002",
                    institution="BR",
                    number="259/26",
                    document_id="2002",
                    label="1. Durchgang",
                ),
            ]
            return response(
                request,
                {"numFound": 2, "cursor": "positions-end", "documents": documents},
            )
        return response(
            request,
            {"numFound": 2, "cursor": "positions-end", "documents": []},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        page = await DipClient(http, api_key=API_KEY, resolver=public_resolver).fetch_procedures(
            "334562"
        )

    assert page.total_found == 1
    assert page.next_cursor == "procedure-next"
    assert len(page.items) == 1
    procedure = page.items[0]
    assert procedure.provider_id == "334562"
    assert procedure.provider_status == "Überwiesen"
    assert procedure.provider_labels == (
        "Innere Sicherheit",
        "Polizeiliches Informationssystem",
    )
    assert procedure.document_date == "2026-07-08"
    assert procedure.source_modified_at == "2026-09-16T12:30:00+02:00"
    assert [(event.provider_id, event.institution, event.label) for event in procedure.events] == [
        ("1001", "BT", "1. Beratung"),
        ("1002", "BR", "1. Durchgang"),
    ]
    assert [(document.provider_id, document.publisher) for document in procedure.documents] == [
        ("2001", "BT"),
        ("2002", "BR"),
    ]
    assert procedure.related_procedures[0].relation == "Bundesratsverfahren"
    assert procedure.related_procedures[0].provider_id == "334563"
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_provider_cursor_is_exposed_until_the_provider_repeats_it() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        if request.url.params.get("cursor") is None:
            return response(
                request,
                {"numFound": 1, "cursor": "next", "documents": [procedure_payload()]},
            )
        return response(request, {"numFound": 1, "cursor": "next", "documents": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = DipClient(http, api_key=API_KEY, include_positions=False, resolver=public_resolver)
        first = await client.fetch_procedures("334562")
        exhausted = await client.fetch_procedures("334562", cursor=first.next_cursor)

    assert first.next_cursor == "next"
    assert exhausted.next_cursor is None
    assert seen == [{"f.id": "334562"}, {"f.id": "334562", "cursor": "next"}]


@pytest.mark.asyncio
async def test_modification_fetch_applies_an_explicit_overlap_window() -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return response(request, {"numFound": 0, "cursor": "empty", "documents": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        page = await DipClient(
            http, api_key=API_KEY, include_positions=False, resolver=public_resolver
        ).fetch_modifications(
            datetime(2026, 9, 16, 12, 0, tzinfo=UTC),
            overlap=timedelta(minutes=15),
        )

    assert page.items == ()
    assert page.window_start == "2026-09-16T11:45:00+00:00"
    assert captured is not None
    assert dict(captured.url.params) == {"f.aktualisiert.start": "2026-09-16T11:45:00+00:00"}


@pytest.mark.asyncio
async def test_401_and_provider_body_never_expose_the_api_key() -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return response(
            request,
            {"code": 401, "message": f"Rejected {API_KEY}"},
            status=401,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(DipAuthenticationError) as error:
            await DipClient(http, api_key=API_KEY, resolver=public_resolver).fetch_procedures(
                "334562"
            )

    assert API_KEY not in str(error.value)
    assert error.value.__cause__ is None
    assert captured is not None
    assert captured.headers["Authorization"] == f"ApiKey {API_KEY}"
    assert API_KEY not in str(captured.url)


@pytest.mark.asyncio
async def test_schema_drift_fails_closed_without_echoing_the_response() -> None:
    hostile_value = f"new field containing {API_KEY}"

    def handler(request: httpx.Request) -> httpx.Response:
        return response(
            request,
            {
                "numFound": 1,
                "cursor": "next",
                "documents": [procedure_payload()],
                "unexpected": hostile_value,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(DipProviderError, match="schema") as error:
            await DipClient(http, api_key=API_KEY, resolver=public_resolver).fetch_procedures(
                "334562"
            )

    assert API_KEY not in str(error.value)
    assert hostile_value not in str(error.value)


@pytest.mark.asyncio
async def test_arbitrary_linked_document_url_is_rejected() -> None:
    position = position_payload(
        identifier="1001",
        institution="BT",
        number="21/6131",
        document_id="2001",
        label="1. Beratung",
    )
    assert isinstance(position["fundstelle"], dict)
    position["fundstelle"]["pdf_url"] = "https://attacker.example/secret.pdf"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/vorgang"):
            return response(
                request,
                {"numFound": 1, "cursor": "next", "documents": [procedure_payload()]},
            )
        return response(
            request,
            {"numFound": 1, "cursor": "positions-end", "documents": [position]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(DipProviderError, match="schema"):
            await DipClient(
                http, api_key=API_KEY, max_pages=1, resolver=public_resolver
            ).fetch_procedures("334562")


@pytest.mark.asyncio
@pytest.mark.parametrize("limit_kind", ["response", "records", "pages"])
async def test_response_record_and_page_caps_fail_closed(limit_kind: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if limit_kind == "response":
            return response(
                request,
                {"numFound": 0, "cursor": "x" * 1_000, "documents": []},
            )
        if request.url.path.endswith("/vorgang"):
            documents = [procedure_payload(), procedure_payload(identifier="334563")]
            return response(request, {"numFound": 2, "cursor": "next", "documents": documents})
        position = position_payload(
            identifier="1001",
            institution="BT",
            number="21/6131",
            document_id="2001",
            label="1. Beratung",
        )
        cursor = request.url.params.get("cursor")
        next_cursor = "position-2" if cursor is None else "position-3"
        return response(
            request,
            {"numFound": 2, "cursor": next_cursor, "documents": [position]},
        )

    options: dict[str, Any] = {"include_positions": limit_kind == "pages"}
    if limit_kind == "response":
        options["max_response_bytes"] = 100
    elif limit_kind == "records":
        options["max_records"] = 1
    else:
        options["max_pages"] = 1
        options["max_records"] = 10

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(DipProviderError, match="limit"):
            await DipClient(
                http, api_key=API_KEY, resolver=public_resolver, **options
            ).fetch_procedures("334562")


@pytest.mark.asyncio
async def test_client_rejects_an_unofficial_base_url() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: response(request, {}))
    ) as async_client:
        with pytest.raises(ValueError, match="official HTTPS"):
            DipClient(async_client, api_key=API_KEY, base_url="https://attacker.example/api/v1")
