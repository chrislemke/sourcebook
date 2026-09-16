"""Bounded provider contract for German Bundestag DIP procedures."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from policy_mcp.source_http import (
    BoundedHttpClient,
    Resolver,
    SourceChallengeError,
    SourceRequestError,
    resolve_host,
)

DEFAULT_BASE_URL = "https://search.dip.bundestag.de/api/v1"
# DIP publishes no rate limit, but its bot protection challenges fast sequential clients.
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 1.0
OFFICIAL_API_HOST = "search.dip.bundestag.de"
OFFICIAL_DOCUMENT_HOSTS = frozenset(
    {
        "dserver.bundestag.de",
        "dip.bundestag.de",
        "www.bgbl.de",
    }
)
Identifier = Annotated[str, Field(pattern=r"^[0-9]+$")]
NonEmptyString = Annotated[str, Field(min_length=1)]
DipQuery = Mapping[str, str] | list[tuple[str, str | float | None]]
IsoDate = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
IsoDateTime = Annotated[
    str,
    Field(
        pattern=(
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(?:Z|[+-][0-9]{2}:[0-9]{2})$"
        )
    ),
]


class DipProviderError(RuntimeError):
    """A redacted DIP failure safe to return through an operator boundary."""


class DipAuthenticationError(DipProviderError):
    """DIP rejected the configured API key."""


class DipChallengeError(DipProviderError):
    """DIP bot protection challenged this client instead of returning data."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _RawModel(_FrozenModel):
    """A provider payload whose optional fields DIP sometimes sends as empty strings."""

    @model_validator(mode="before")
    @classmethod
    def empty_optional_strings_are_absent(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {
            key: (
                None
                if item == ""
                and key in cls.model_fields
                and not cls.model_fields[key].is_required()
                else item
            )
            for key, item in value.items()
        }


class _RawDescriptor(_FrozenModel):
    name: NonEmptyString
    typ: NonEmptyString
    fundstelle: bool


class _RawProcedureLink(_RawModel):
    id: Identifier
    verweisung: NonEmptyString
    titel: NonEmptyString
    wahlperiode: int
    gesta: str | None = None


class _RawProcedure(_RawModel):
    id: Identifier
    typ: Literal["Vorgang"]
    beratungsstand: str | None = None
    vorgangstyp: NonEmptyString
    wahlperiode: int
    initiative: list[str] | None = None
    datum: IsoDate | None = None
    aktualisiert: IsoDateTime
    titel: NonEmptyString
    abstract: str | None = None
    sachgebiet: list[str] | None = None
    deskriptor: list[_RawDescriptor] | None = None
    gesta: str | None = None
    zustimmungsbeduerftigkeit: list[str] | None = None
    kom: str | None = None
    ratsdok: str | None = None
    verkuendung: list[dict[str, object]] | None = None
    inkrafttreten: list[dict[str, object]] | None = None
    archiv: str | None = None
    mitteilung: str | None = None
    vorgang_verlinkung: list[_RawProcedureLink] | None = None
    sek: str | None = None


class _RawFinding(_RawModel):
    id: Identifier
    dokumentnummer: NonEmptyString
    datum: IsoDate
    dokumentart: Literal["Drucksache", "Plenarprotokoll"]
    herausgeber: Literal["BT", "BR", "BV", "EK"]
    urheber: list[str]
    pdf_url: str | None = None
    xml_url: str | None = None
    drucksachetyp: str | None = None
    verteildatum: IsoDate | None = None
    seite: str | None = None
    anfangsseite: int | None = None
    endseite: int | None = None
    anfangsquadrant: Literal["A", "B", "C", "D"] | None = None
    endquadrant: Literal["A", "B", "C", "D"] | None = None
    frage_nummer: str | None = None
    anlagen: str | None = None
    top: int | None = None
    top_zusatz: str | None = None

    @field_validator("pdf_url", "xml_url")
    @classmethod
    def validate_document_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in OFFICIAL_DOCUMENT_HOSTS
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("DIP document URL is not on an official HTTPS host")
        return value


class _RawPosition(_RawModel):
    id: Identifier
    vorgangsposition: NonEmptyString
    zuordnung: Literal["BT", "BR", "BV", "EK"]
    gang: bool
    fortsetzung: bool
    nachtrag: bool
    vorgangstyp: NonEmptyString
    typ: Literal["Vorgangsposition"]
    titel: NonEmptyString
    dokumentart: Literal["Drucksache", "Plenarprotokoll"]
    vorgang_id: Identifier
    datum: IsoDate
    aktualisiert: IsoDateTime
    fundstelle: _RawFinding
    urheber: list[dict[str, object]] | None = None
    ueberweisung: list[dict[str, object]] | None = None
    aktivitaet_anzeige: list[dict[str, object]] | None = None
    aktivitaet_anzahl: int
    ressort: list[dict[str, object]] | None = None
    beschlussfassung: list[dict[str, object]] | None = None
    ratsdok: str | None = None
    kom: str | None = None
    sek: str | None = None
    mitberaten: list[dict[str, object]] | None = None
    abstract: str | None = None


class _RawProcedurePage(_FrozenModel):
    numFound: Annotated[int, Field(ge=0)]
    cursor: NonEmptyString
    documents: list[_RawProcedure]


class _RawPositionPage(_FrozenModel):
    numFound: Annotated[int, Field(ge=0)]
    cursor: NonEmptyString
    documents: list[_RawPosition]


class DipProcedureEvent(_FrozenModel):
    """One DIP procedure position, separate from its linked document."""

    provider_id: Identifier
    label: NonEmptyString
    institution: Literal["BT", "BR", "BV", "EK"]
    procedure_type: NonEmptyString
    date: IsoDate
    source_modified_at: IsoDateTime
    key_progress: bool
    continuation: bool
    supplement: bool
    linked_document_id: Identifier


class DipLinkedDocument(_FrozenModel):
    """Document metadata linked from a procedure position."""

    provider_id: Identifier
    kind: Literal["Drucksache", "Plenarprotokoll"]
    number: NonEmptyString
    date: IsoDate
    publisher: Literal["BT", "BR", "BV", "EK"]
    authors: tuple[str, ...]
    document_type: str | None
    pdf_url: str | None
    xml_url: str | None


class DipRelatedProcedure(_FrozenModel):
    """An explicit provider link to another procedure."""

    provider_id: Identifier
    relation: NonEmptyString
    title: NonEmptyString
    parliamentary_term: int
    gesta: str | None


class DipProcedure(_FrozenModel):
    """Normalized DIP procedure retaining provider wording and dates."""

    provider_id: Identifier
    provider_type: Literal["Vorgang"] = "Vorgang"
    procedure_type: NonEmptyString
    provider_status: str | None
    title: NonEmptyString
    parliamentary_term: int
    initiatives: tuple[str, ...]
    document_date: IsoDate | None
    source_modified_at: IsoDateTime
    abstract: str | None
    provider_labels: tuple[str, ...]
    gesta: str | None
    consent_labels: tuple[str, ...]
    events: tuple[DipProcedureEvent, ...]
    documents: tuple[DipLinkedDocument, ...]
    related_procedures: tuple[DipRelatedProcedure, ...]


class DipProcedurePage(_FrozenModel):
    """One bounded provider page and its opaque continuation cursor."""

    items: tuple[DipProcedure, ...]
    total_found: int
    next_cursor: str | None
    window_start: IsoDateTime | None = None


class DipClient:
    """Fetch exact or recently modified DIP procedures without topic search."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        max_pages: int = 5,
        max_records: int = 100,
        max_response_bytes: int = 2_000_000,
        include_positions: bool = True,
        resolver: Resolver = resolve_host,
        min_request_interval: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("DIP API key must not be empty")
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != OFFICIAL_API_HOST
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != "/api/v1"
        ):
            raise ValueError("DIP base URL must be the official HTTPS API host")
        if max_pages < 1 or max_records < 1 or max_response_bytes < 1:
            raise ValueError("DIP limits must be positive")
        self._http = BoundedHttpClient(
            client,
            allowed_hosts={OFFICIAL_API_HOST},
            resolver=resolver,
            max_response_bytes=max_response_bytes,
            challenge_paths=("/.enodia/",),
        )
        self._min_request_interval = max(min_request_interval, 0.0)
        self._clock = clock
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_pages = max_pages
        self._max_records = max_records
        self._include_positions = include_positions

    async def fetch_procedures(
        self,
        provider_id: str,
        *,
        cursor: str | None = None,
    ) -> DipProcedurePage:
        """Fetch one provider page filtered only by an explicit DIP identifier."""
        if not provider_id.isascii() or not provider_id.isdigit():
            raise ValueError("DIP procedure identifier must contain only digits")
        parameters = {"f.id": provider_id}
        if cursor is not None:
            parameters["cursor"] = self._validate_cursor(cursor)
        page = await self._procedure_page(parameters)
        return await self._normalize_page(page, requested_cursor=cursor, window_start=None)

    async def search_procedures(
        self,
        *,
        titles: tuple[str, ...] = (),
        ids: tuple[str, ...] = (),
        gesta: str | None = None,
        cursor: str | None = None,
    ) -> DipProcedurePage:
        """Fetch one page of procedures by title words, DIP ids, or a GESTA number."""
        if not titles and not ids and gesta is None:
            raise ValueError("DIP search needs titles, ids, or a GESTA number")
        if any(not item.isascii() or not item.isdigit() for item in ids):
            raise ValueError("DIP procedure identifier must contain only digits")
        parameters: list[tuple[str, str | float | None]] = [
            *(("f.titel", title) for title in titles),
            *(("f.id", identifier) for identifier in ids),
            *((("f.gesta", gesta),) if gesta is not None else ()),
        ]
        if cursor is not None:
            parameters.append(("cursor", self._validate_cursor(cursor)))
        page = await self._procedure_page(parameters)
        return await self._normalize_page(page, requested_cursor=cursor, window_start=None)

    async def fetch_modifications(
        self,
        since: datetime,
        *,
        until: datetime | None = None,
        overlap: timedelta,
        cursor: str | None = None,
    ) -> DipProcedurePage:
        """Fetch changed procedures from an explicitly overlapping modification window."""
        if since.tzinfo is None or since.utcoffset() is None:
            raise ValueError("DIP modification timestamps must include a timezone")
        if overlap < timedelta(0) or overlap > timedelta(days=7):
            raise ValueError("DIP overlap must be between zero and seven days")
        window_start = (since - overlap).isoformat(timespec="seconds")
        parameters = {"f.aktualisiert.start": window_start}
        if until is not None:
            if until.tzinfo is None or until.utcoffset() is None:
                raise ValueError("DIP modification timestamps must include a timezone")
            if until < since:
                raise ValueError("DIP modification end must not be before its start")
            parameters["f.aktualisiert.end"] = until.isoformat(timespec="seconds")
        if cursor is not None:
            parameters["cursor"] = self._validate_cursor(cursor)
        page = await self._procedure_page(parameters)
        return await self._normalize_page(
            page,
            requested_cursor=cursor,
            window_start=window_start,
        )

    @staticmethod
    def _validate_cursor(cursor: str) -> str:
        if not cursor or len(cursor) > 4_096 or any(char.isspace() for char in cursor):
            raise ValueError("Invalid DIP provider cursor")
        return cursor

    async def _procedure_page(self, parameters: DipQuery) -> _RawProcedurePage:
        payload = await self._get("vorgang", parameters)
        try:
            page = _RawProcedurePage.model_validate(payload)
        except ValidationError:
            raise DipProviderError("DIP procedure response failed schema validation") from None
        if len(page.documents) > self._max_records:
            raise DipProviderError("DIP procedure response exceeded the record limit")
        return page

    async def _normalize_page(
        self,
        page: _RawProcedurePage,
        *,
        requested_cursor: str | None,
        window_start: str | None,
    ) -> DipProcedurePage:
        items: list[DipProcedure] = []
        for procedure in page.documents:
            positions = await self._fetch_positions(procedure.id) if self._include_positions else ()
            items.append(self._normalize_procedure(procedure, positions))
        next_cursor = None if page.cursor == requested_cursor else page.cursor
        return DipProcedurePage(
            items=tuple(items),
            total_found=page.numFound,
            next_cursor=next_cursor,
            window_start=window_start,
        )

    async def _fetch_positions(self, procedure_id: str) -> tuple[_RawPosition, ...]:
        positions: list[_RawPosition] = []
        cursor: str | None = None
        for page_number in range(1, self._max_pages + 1):
            parameters = {"f.vorgang": procedure_id}
            if cursor is not None:
                parameters["cursor"] = cursor
            payload = await self._get("vorgangsposition", parameters)
            try:
                page = _RawPositionPage.model_validate(payload)
            except ValidationError:
                raise DipProviderError("DIP position response failed schema validation") from None
            if cursor is not None and page.cursor == cursor:
                break
            if len(positions) + len(page.documents) > self._max_records:
                raise DipProviderError("DIP position response exceeded the record limit")
            positions.extend(page.documents)
            cursor = page.cursor
            if page_number == self._max_pages:
                raise DipProviderError("DIP position pagination exceeded the page limit")
        return tuple(positions)

    @staticmethod
    def _normalize_procedure(
        source: _RawProcedure,
        positions: tuple[_RawPosition, ...],
    ) -> DipProcedure:
        events = tuple(
            DipProcedureEvent(
                provider_id=position.id,
                label=position.vorgangsposition,
                institution=position.zuordnung,
                procedure_type=position.vorgangstyp,
                date=position.datum,
                source_modified_at=position.aktualisiert,
                key_progress=position.gang,
                continuation=position.fortsetzung,
                supplement=position.nachtrag,
                linked_document_id=position.fundstelle.id,
            )
            for position in positions
        )
        documents_by_id: dict[str, DipLinkedDocument] = {}
        for position in positions:
            finding = position.fundstelle
            documents_by_id.setdefault(
                finding.id,
                DipLinkedDocument(
                    provider_id=finding.id,
                    kind=finding.dokumentart,
                    number=finding.dokumentnummer,
                    date=finding.datum,
                    publisher=finding.herausgeber,
                    authors=tuple(finding.urheber),
                    document_type=finding.drucksachetyp,
                    pdf_url=finding.pdf_url,
                    xml_url=finding.xml_url,
                ),
            )
        labels = tuple(
            dict.fromkeys(
                [*(source.sachgebiet or []), *(item.name for item in source.deskriptor or [])]
            )
        )
        relations = tuple(
            DipRelatedProcedure(
                provider_id=link.id,
                relation=link.verweisung,
                title=link.titel,
                parliamentary_term=link.wahlperiode,
                gesta=link.gesta,
            )
            for link in source.vorgang_verlinkung or []
        )
        return DipProcedure(
            provider_id=source.id,
            procedure_type=source.vorgangstyp,
            provider_status=source.beratungsstand,
            title=source.titel,
            parliamentary_term=source.wahlperiode,
            initiatives=tuple(source.initiative or []),
            document_date=source.datum,
            source_modified_at=source.aktualisiert,
            abstract=source.abstract,
            provider_labels=labels,
            gesta=source.gesta,
            consent_labels=tuple(source.zustimmungsbeduerftigkeit or []),
            events=events,
            documents=tuple(documents_by_id.values()),
            related_procedures=relations,
        )

    async def count_modifications(
        self,
        since: datetime,
        *,
        until: datetime,
        overlap: timedelta,
    ) -> int:
        """Return how many procedures changed in a window without fetching their positions."""
        parameters = {
            "f.aktualisiert.start": (since - overlap).isoformat(timespec="seconds"),
            "f.aktualisiert.end": until.isoformat(timespec="seconds"),
        }
        return (await self._procedure_page(parameters)).numFound

    async def _pace(self) -> None:
        if self._last_request_at is not None:
            remaining = self._min_request_interval - (self._clock() - self._last_request_at)
            if remaining > 0:
                await self._sleep(remaining)
        self._last_request_at = self._clock()

    async def _get(self, operation: str, parameters: DipQuery) -> object:
        await self._pace()
        try:
            response = await self._http.get(
                f"{self._base_url}/{operation}",
                headers={"Authorization": f"ApiKey {self._api_key}"},
                params=parameters,
            )
        except SourceChallengeError:
            raise DipChallengeError(
                "DIP bot protection challenged the request. Wait several minutes, then sync again."
            ) from None
        except SourceRequestError as error:
            if "response limit" in str(error):
                raise DipProviderError("DIP response exceeded the response limit") from None
            raise DipProviderError("DIP request failed") from None
        except httpx.HTTPError:
            raise DipProviderError("DIP request failed") from None
        if response.status_code == 401:
            raise DipAuthenticationError("DIP authentication was rejected") from None
        if response.status_code >= 400:
            raise DipProviderError(f"DIP returned HTTP {response.status_code}") from None
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise DipProviderError("DIP returned an unsupported content type")
        try:
            return response.json()
        except ValueError:
            raise DipProviderError("DIP returned invalid JSON") from None
