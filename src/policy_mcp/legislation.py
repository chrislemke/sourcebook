"""Frozen legislation catalog and MCP tool registration."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from policy_mcp.adapters.dip import DipAuthenticationError, DipClient, DipProviderError
from policy_mcp.contracts import tool_description
from policy_mcp.diagnostics import load_credential
from policy_mcp.ingestion import dip_record_payload
from policy_mcp.references import (
    MAX_SNAPSHOT_ITEMS,
    ExpiredCursorError,
    ForgedCursorError,
    ForgedReferenceError,
    ReferenceStore,
)
from policy_mcp.research_contracts import (
    CapabilitiesInput,
    CapabilitiesResponse,
    ChangesInput,
    ChangesResponse,
    Continuation,
    Coverage,
    DocumentCard,
    Freshness,
    Jurisdiction,
    Locator,
    OutlineEntry,
    Passage,
    ProcedureDetail,
    ProcedureEvent,
    ProcedureInput,
    ProcedureResponse,
    Provenance,
    ReadInput,
    ReadResponse,
    RecordsInput,
    RecordsResponse,
    ResearchError,
    ResearchStatus,
    SearchCard,
    SearchInput,
    SearchResponse,
    SourceCapability,
    StrictModel,
    fit_response,
)
from policy_mcp.storage import open_database


class _Event(StrictModel):
    date: str
    label: str


class _Section(StrictModel):
    heading: str
    locator: Locator
    text: str


class _Document(StrictModel):
    key: str
    source: str
    provider_id: str
    title: str
    source_language: str
    official_url: str
    source_modified_at: str
    sections: list[_Section]


class _Record(StrictModel):
    key: str
    kind: Literal["procedure", "legal_text"]
    jurisdiction: Jurisdiction
    source: str
    provider_id: str
    identifier: str
    title: str
    abstract: str
    subjects: list[str]
    status: str
    source_language: str
    available_languages: list[str] = Field(default_factory=list)
    official_url: str
    source_modified_at: str
    events: list[_Event]
    document_keys: list[str]


class _Fixture(StrictModel):
    retrieved_at: str
    indexed_at: str
    records: list[_Record]
    documents: list[_Document]


class FrozenLegislationCatalog:
    """Read-only catalog built from checked-in provider-shaped fixtures."""

    def __init__(self, fixture: _Fixture) -> None:
        self.retrieved_at = fixture.retrieved_at
        self.indexed_at = fixture.indexed_at
        self._records = {record.key: record for record in fixture.records}
        self._documents = {document.key: document for document in fixture.documents}

    @classmethod
    def empty(cls) -> FrozenLegislationCatalog:
        """Create an unconfigured production catalog without sample records."""
        return cls(_Fixture(retrieved_at="", indexed_at="", records=[], documents=[]))

    @property
    def ready_sources(self) -> set[str]:
        """Return sources that have passed ingestion into this catalog."""
        return {
            *[record.source for record in self._records.values()],
            *[document.source for document in self._documents.values()],
        }

    @property
    def searchable_sources(self) -> set[str]:
        """Return sources with at least one validated searchable record."""
        return {record.source for record in self._records.values()}

    def available_operations(self, source: str) -> list[str]:
        """Derive only operations supported by validated local entities."""
        records = [record for record in self._records.values() if record.source == source]
        has_documents = any(document.source == source for document in self._documents.values())
        if source == "dip":
            operations = ["search", "procedure"] if records else []
        elif source == "cellar":
            operations = ["identifier_lookup"] if records else []
        else:
            operations = []
        if has_documents:
            operations.append("read")
        return operations

    @classmethod
    def from_json(cls, path: Path) -> FrozenLegislationCatalog:
        """Load one frozen catalog fixture."""
        return cls(_Fixture.model_validate_json(path.read_text()))

    @classmethod
    def from_database(cls) -> FrozenLegislationCatalog:
        """Load the latest validated legislation versions from healthy local sources."""
        with open_database() as connection:
            return cls._from_connection(connection)

    @classmethod
    def _from_connection(cls, connection: sqlite3.Connection) -> FrozenLegislationCatalog:
        rows = connection.execute(
            """
            WITH latest_versions AS (
                SELECT
                    records.source_id,
                    records.entity_kind,
                    record_versions.payload_json,
                    record_versions.retrieved_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY records.id
                        ORDER BY
                            record_versions.source_timestamp DESC,
                            record_versions.id DESC
                    ) AS version_rank
                FROM records
                JOIN sources ON sources.source_id = records.source_id
                JOIN record_versions ON record_versions.record_id = records.id
                WHERE sources.status = 'healthy'
                  AND records.entity_kind IN ('procedure', 'legal_text', 'document')
            )
            SELECT source_id, entity_kind, payload_json, retrieved_at
            FROM latest_versions
            WHERE version_rank = 1
            ORDER BY source_id, entity_kind
            """
        ).fetchall()
        records: list[_Record] = []
        documents: list[_Document] = []
        retrieved_at = ""
        for source_id, entity_kind, payload_json, row_retrieved_at in rows:
            try:
                payload = json.loads(payload_json)
                if not isinstance(payload, dict) or payload.get("source") != source_id:
                    continue
                if entity_kind == "document":
                    documents.append(_Document.model_validate(payload))
                else:
                    record = _Record.model_validate(payload)
                    if record.kind != entity_kind:
                        continue
                    records.append(record)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            # SQLite CURRENT_TIMESTAMP is UTC without a zone marker.
            retrieved_at = max(retrieved_at, str(row_retrieved_at).replace(" ", "T") + "Z")
        return cls(
            _Fixture(
                retrieved_at=retrieved_at,
                indexed_at=retrieved_at,
                records=records,
                documents=documents,
            )
        )

    def search(self, request: SearchInput) -> list[_Record]:
        """Search only capabilities supported by the frozen local index."""
        terms = request.query.casefold().split() if request.query else []
        wanted = request.identifier.casefold() if request.identifier is not None else None
        matches: list[_Record] = []
        for record in self._records.values():
            if record.jurisdiction != request.jurisdiction or record.kind != request.kind:
                continue
            if request.source is not None and record.source != request.source:
                continue
            if wanted is not None and wanted not in {
                record.identifier.casefold(),
                record.provider_id.casefold(),
            }:
                continue
            searchable = " ".join([record.title, record.abstract, *record.subjects]).casefold()
            if wanted is None and not all(term in searchable for term in terms):
                continue
            matches.append(record)
            if len(matches) > MAX_SNAPSHOT_ITEMS:
                break
        return matches

    def record(self, key: str) -> _Record | None:
        return self._records.get(key)

    def document(self, key: str) -> _Document | None:
        return self._documents.get(key)


class DipLiveUnavailableError(RuntimeError):
    """DIP could not answer a live request; the message is safe to show."""


class DipKeyRejectedError(DipLiveUnavailableError):
    """DIP rejected the configured API key."""


class LiveDipLegislation:
    """Query German federal procedures from DIP on demand when an API key is configured."""

    def __init__(
        self,
        *,
        api_key: Callable[[], str | None] = lambda: load_credential("DIP_API_KEY"),
        timeout_seconds: float = 30.0,
        client: Callable[[httpx.AsyncClient, str, bool], DipClient] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))
        self._client = client or (
            lambda http, key, positions: DipClient(http, api_key=key, include_positions=positions)
        )
        self._transport = transport

    @property
    def configured(self) -> bool:
        return self._api_key() is not None

    async def search(self, request: SearchInput) -> list[_Record]:
        """Search DIP titles, DIP ids, or GESTA numbers and return procedures without steps."""
        if request.identifier is not None:
            identifier = request.identifier.strip()
            if identifier.isascii() and identifier.isdigit():
                return await self._records(ids=(identifier,), positions=False)
            return await self._records(gesta=identifier, positions=False)
        assert request.query is not None
        words = request.query.split()
        records = await self._records(titles=(request.query,), positions=False)
        if records or len(words) < 2:
            return records
        # DIP searches several words as one phrase. Retry with the longest, usually most
        # selective word and keep titles that contain every word.
        candidates = await self._records(titles=(max(words, key=len),), positions=False)
        wanted = [word.casefold() for word in words]
        return [
            record
            for record in candidates
            if all(word in record.title.casefold() for word in wanted)
        ]

    async def procedure(self, provider_id: str) -> _Record | None:
        """Fetch one procedure with its dated steps."""
        records = await self._records(ids=(provider_id,), positions=True)
        return records[0] if records else None

    async def records(self, provider_ids: list[str]) -> list[_Record]:
        """Fetch procedures for stored search keys without their steps."""
        if not provider_ids:
            return []
        return await self._records(ids=tuple(provider_ids), positions=False)

    async def _records(
        self,
        *,
        titles: tuple[str, ...] = (),
        ids: tuple[str, ...] = (),
        gesta: str | None = None,
        positions: bool,
    ) -> list[_Record]:
        key = self._api_key()
        if key is None:
            raise DipLiveUnavailableError("DIP_API_KEY is not configured.")
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as http:
                client = self._client(http, key, positions)
                page = await client.search_procedures(titles=titles, ids=ids, gesta=gesta)
        except DipAuthenticationError:
            raise DipKeyRejectedError(
                "DIP rejected the configured API key. Check or replace DIP_API_KEY."
            ) from None
        except DipProviderError as error:
            raise DipLiveUnavailableError(str(error)) from None
        return [_Record.model_validate(dip_record_payload(item)) for item in page.items]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _query_hash(request: SearchInput) -> str:
    value = request.model_dump(mode="json", exclude={"cursor", "limit"})
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _provenance(catalog: FrozenLegislationCatalog, record: _Record | _Document) -> Provenance:
    return Provenance(
        source=record.source,
        provider_id=record.provider_id,
        official_url=record.official_url,
        retrieved_at=catalog.retrieved_at,
        source_modified_at=record.source_modified_at,
    )


def _coverage(source: str, jurisdiction: Jurisdiction) -> Coverage:
    limitation = (
        "The local index is not a complete historical backfill."
        if source == "dip"
        else "CELLAR identifier retrieval is not full-text EUR-Lex search."
    )
    return Coverage(
        source=source,
        jurisdiction=jurisdiction,
        complete=False,
        limitations=[limitation],
    )


def _freshness(
    catalog: FrozenLegislationCatalog,
    source: str,
    source_modified_at: str | None = None,
) -> Freshness:
    return Freshness(
        source=source,
        retrieved_at=catalog.retrieved_at,
        indexed_at=catalog.indexed_at,
        source_modified_at=source_modified_at,
    )


def _card(
    catalog: FrozenLegislationCatalog,
    references: ReferenceStore,
    record: _Record,
    language: str,
) -> SearchCard:
    provenance = _provenance(catalog, record)
    return SearchCard(
        reference=references.reference_for(
            principal=references.principal,
            kind=record.kind,
            key=record.key,
        ),
        kind=record.kind,
        jurisdiction=record.jurisdiction,
        source=record.source,
        identifier=record.identifier,
        title=record.title,
        abstract=record.abstract,
        status=record.status,
        official_url=record.official_url,
        source_language=record.source_language,
        requested_language=language,
        provenance=provenance,
    )


def _error(code: Any, message: str, *, retryable: bool = False) -> ResearchError:
    return ResearchError(code=code, message=message, retryable=retryable)


def _trim_whole_items(response: Any, field_name: str) -> Any:
    """Fit a result by removing whole optional items, retaining warnings and provenance."""
    return fit_response(response, getattr(response, field_name))


def _source_error(code: Any, message: str) -> SearchResponse:
    return SearchResponse(status=ResearchStatus.ERROR, error=_error(code, message))


def _strict_tool_inputs(server: MCPServer[Any], names: list[str]) -> None:
    """Make SDK-generated argument models reject undeclared top-level fields."""
    manager = server._tool_manager
    for name in names:
        tool = manager.get_tool(name)
        if tool is None:  # pragma: no cover - registration invariant
            raise RuntimeError(f"Tool registration failed: {name}")
        tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
        tool.fn_metadata.arg_model.model_rebuild(force=True)
        tool.parameters = tool.fn_metadata.arg_model.model_json_schema(by_alias=True)


DIP_KEY_PREFIX = "dip:vorgang:"
LIVE_DIP_COVERAGE = Coverage(
    source="dip",
    jurisdiction=Jurisdiction.DE,
    complete=False,
    limitations=[
        "Live DIP search matches words in procedure titles, not abstracts or document text."
    ],
)
DIP_SETUP_MESSAGE = (
    "German legislation search needs a DIP API key. Claude Desktop: open Settings > "
    "Extensions > Sourcebook Legislation and enter it. Claude Code: reinstall the plugin with "
    "--config dip_api_key=... or run `policy-mcp configure --credential DIP_API_KEY`. The "
    "Bundestag publishes a free public key at https://dip.bundestag.de/über-dip/hilfe/api."
)


def _live_catalog(records: list[_Record]) -> FrozenLegislationCatalog:
    retrieved_at = _now()
    return FrozenLegislationCatalog(
        _Fixture(retrieved_at=retrieved_at, indexed_at=retrieved_at, records=records, documents=[])
    )


async def _live_dip_search(
    live_dip: LiveDipLegislation,
    reference_store: ReferenceStore,
    request: SearchInput,
) -> SearchResponse:
    digest = _query_hash(request)
    try:
        if request.cursor is None:
            matches = await live_dip.search(request)
            page = reference_store.first_page(
                [record.key for record in matches],
                principal=reference_store.principal,
                query_hash=digest,
                limit=request.limit,
            )
            by_key = {record.key: record for record in matches}
            records = [by_key[key] for key in page.keys if key in by_key]
        else:
            page = reference_store.next_page(
                request.cursor,
                principal=reference_store.principal,
                query_hash=digest,
                limit=request.limit,
            )
            fetched = await live_dip.records(
                [key.removeprefix(DIP_KEY_PREFIX) for key in page.keys]
            )
            by_key = {record.key: record for record in fetched}
            records = [by_key[key] for key in page.keys if key in by_key]
    except ForgedCursorError:
        return _source_error("forged_cursor", "The continuation does not belong to this query.")
    except ExpiredCursorError:
        response = _source_error("expired_cursor", "The continuation expired.")
        response.error = _error(
            "expired_cursor",
            "The continuation expired. Restart the search without a cursor.",
            retryable=True,
        )
        return response
    except DipKeyRejectedError as error:
        return _source_error("not_configured", f"{error} {DIP_SETUP_MESSAGE}")
    except DipLiveUnavailableError as error:
        response = _source_error("temporarily_unavailable", "DIP could not be reached.")
        response.error = _error(
            "temporarily_unavailable", f"DIP could not be reached. {error}", retryable=True
        )
        return response
    except ValueError:
        return _source_error("oversized", "The search matched too many bounded results.")
    live_catalog = _live_catalog(records)
    cards = [_card(live_catalog, reference_store, record, request.language) for record in records]
    response = SearchResponse(
        status=ResearchStatus.OK,
        items=cards,
        continuation=(
            Continuation(cursor=page.cursor, expires_at=page.expires_at.isoformat())
            if page.cursor is not None and page.expires_at is not None
            else None
        ),
        coverage=[LIVE_DIP_COVERAGE],
        freshness=[_freshness(live_catalog, "dip")],
        provenance=[card.provenance for card in cards],
    )
    return _trim_whole_items(response, "items")


def register_legislation_tools(
    server: MCPServer[Any],
    catalog: FrozenLegislationCatalog,
    reference_store: ReferenceStore,
    *,
    live_dip: LiveDipLegislation | None = None,
) -> None:
    """Register the six stable read-only legislation tools."""
    annotations = ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )

    @server.tool(
        name="legislation_search",
        description=tool_description("legislation_search"),
        annotations=annotations,
        structured_output=True,
    )
    async def legislation_search(
        jurisdiction: Annotated[
            Jurisdiction,
            Field(description="DE for German federal procedures; EU is not connected yet."),
        ],
        query: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=300,
                description="German topic words matched against titles, abstracts, and subjects.",
            ),
        ] = None,
        identifier: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=100,
                description=(
                    "Exact DIP procedure id, or a GESTA number such as G006. GESTA numbers "
                    "repeat across electoral terms."
                ),
            ),
        ] = None,
        kind: Literal["procedure", "legal_text"] = "procedure",
        source: Literal["dip", "ep", "cellar", "eurlex"] | None = None,
        language: Literal["de", "en"] = "de",
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
        cursor: Annotated[str | None, Field(min_length=12, max_length=200)] = None,
    ) -> SearchResponse:
        request = SearchInput(
            jurisdiction=jurisdiction,
            query=query,
            identifier=identifier,
            kind=kind,
            source=source,
            language=language,
            limit=limit,
            cursor=cursor,
        )
        expected_source = request.source or (
            "dip" if request.jurisdiction == Jurisdiction.DE else "cellar"
        )
        use_live_dip = (
            expected_source == "dip"
            and request.jurisdiction == Jurisdiction.DE
            and request.kind == "procedure"
            and live_dip is not None
            and live_dip.configured
        )
        if use_live_dip:
            assert live_dip is not None
            return await _live_dip_search(live_dip, reference_store, request)
        if expected_source not in catalog.searchable_sources:
            return _source_error(
                "not_configured",
                DIP_SETUP_MESSAGE
                if expected_source == "dip"
                else f"Source {expected_source} has not passed its ingestion gate.",
            )
        if request.jurisdiction == Jurisdiction.EU and request.query is not None:
            return _source_error(
                "not_configured",
                "EU topic search requires a configured EP or EUR-Lex index.",
            )
        if request.jurisdiction == Jurisdiction.DE and request.kind != "procedure":
            return _source_error("unsupported", "DIP legal-text search is not supported.")
        if request.jurisdiction == Jurisdiction.EU and request.source not in (None, "cellar"):
            return _source_error("not_configured", f"Source {request.source} is not configured.")

        digest = _query_hash(request)
        try:
            if request.cursor is None:
                matches = catalog.search(request)
                page = reference_store.first_page(
                    [record.key for record in matches],
                    principal=reference_store.principal,
                    query_hash=digest,
                    limit=request.limit,
                )
            else:
                page = reference_store.next_page(
                    request.cursor,
                    principal=reference_store.principal,
                    query_hash=digest,
                    limit=request.limit,
                )
        except ForgedCursorError:
            return _source_error("forged_cursor", "The continuation does not belong to this query.")
        except ExpiredCursorError:
            response = _source_error(
                "expired_cursor",
                "The continuation expired. Restart the search without a cursor.",
            )
            response.error = _error(
                "expired_cursor",
                "The continuation expired. Restart the search without a cursor.",
                retryable=True,
            )
            return response
        except ValueError:
            return _source_error("oversized", "The search matched too many bounded results.")

        records = [record for key in page.keys if (record := catalog.record(key)) is not None]
        cards = [_card(catalog, reference_store, record, request.language) for record in records]
        sources = sorted({record.source for record in records})
        jurisdiction_value = request.jurisdiction
        provenances = [card.provenance for card in cards]
        response = SearchResponse(
            status=ResearchStatus.OK,
            items=cards,
            continuation=(
                Continuation(cursor=page.cursor, expires_at=page.expires_at.isoformat())
                if page.cursor is not None and page.expires_at is not None
                else None
            ),
            coverage=[_coverage(item, jurisdiction_value) for item in sources],
            freshness=[_freshness(catalog, item) for item in sources],
            provenance=provenances,
        )
        return _trim_whole_items(response, "items")

    @server.tool(
        name="legislation_procedure",
        description=tool_description("legislation_procedure"),
        annotations=annotations,
        structured_output=True,
    )
    async def legislation_procedure(
        reference: Annotated[
            str,
            Field(min_length=12, max_length=200, description="Reference from legislation_search."),
        ],
        language: Literal["de", "en"] = "de",
    ) -> ProcedureResponse:
        request = ProcedureInput(reference=reference, language=language)
        try:
            key = reference_store.resolve(
                request.reference,
                principal=reference_store.principal,
                expected_kinds=("procedure",),
            )
        except ForgedReferenceError:
            return ProcedureResponse(
                status=ResearchStatus.ERROR,
                error=_error("forged_reference", "The procedure reference is invalid."),
            )
        record = catalog.record(key)
        catalog_for_record = catalog
        if live_dip is not None and live_dip.configured and key.startswith(DIP_KEY_PREFIX):
            try:
                live_record = await live_dip.procedure(key.removeprefix(DIP_KEY_PREFIX))
            except DipLiveUnavailableError as error:
                if record is None:
                    rejected = isinstance(error, DipKeyRejectedError)
                    return ProcedureResponse(
                        status=ResearchStatus.ERROR,
                        error=_error(
                            "not_configured" if rejected else "temporarily_unavailable",
                            f"{error} {DIP_SETUP_MESSAGE}"
                            if rejected
                            else f"DIP could not be reached. {error}",
                            retryable=not rejected,
                        ),
                    )
            else:
                if live_record is not None:
                    record = live_record
                    catalog_for_record = _live_catalog([live_record])
        if record is None:
            return ProcedureResponse(
                status=ResearchStatus.ERROR,
                error=_error("not_found", "The procedure is no longer available."),
            )
        documents: list[DocumentCard] = []
        for document_key in record.document_keys:
            document = catalog.document(document_key)
            if document is None:
                continue
            provenance = _provenance(catalog, document)
            documents.append(
                DocumentCard(
                    reference=reference_store.reference_for(
                        principal=reference_store.principal,
                        kind="document",
                        key=document.key,
                    ),
                    title=document.title,
                    official_url=document.official_url,
                    source_language=document.source_language,
                    provenance=provenance,
                )
            )
        provenance = _provenance(catalog_for_record, record)
        response = ProcedureResponse(
            status=ResearchStatus.OK,
            procedure=ProcedureDetail(
                reference=request.reference,
                identifier=record.identifier,
                title=record.title,
                status=record.status,
                source_language=record.source_language,
                events=[
                    ProcedureEvent(date=event.date, label=event.label) for event in record.events
                ],
                documents=documents,
            ),
            coverage=[
                LIVE_DIP_COVERAGE
                if catalog_for_record is not catalog
                else _coverage(record.source, record.jurisdiction)
            ],
            freshness=[_freshness(catalog_for_record, record.source, record.source_modified_at)],
            provenance=[provenance, *[item.provenance for item in documents]],
        )
        return fit_response(response, documents)

    @server.tool(
        name="legislation_records",
        description=tool_description("legislation_records"),
        annotations=annotations,
        structured_output=True,
    )
    def legislation_records(
        jurisdiction: Jurisdiction,
        kind: Literal["speech", "question", "committee_document", "adopted_text"],
        query: Annotated[str | None, Field(min_length=1, max_length=300)] = None,
        language: Literal["de", "en"] = "de",
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
        cursor: Annotated[str | None, Field(min_length=12, max_length=200)] = None,
    ) -> RecordsResponse:
        RecordsInput(
            jurisdiction=jurisdiction,
            kind=kind,
            query=query,
            language=language,
            limit=limit,
            cursor=cursor,
        )
        return RecordsResponse(
            status=ResearchStatus.ERROR,
            error=_error("unsupported", "This parliamentary record route is not enabled."),
        )

    @server.tool(
        name="legislation_read",
        description=tool_description("legislation_read"),
        annotations=annotations,
        structured_output=True,
    )
    def legislation_read(
        reference: Annotated[str, Field(min_length=12, max_length=200)],
        query: Annotated[str | None, Field(min_length=1, max_length=300)] = None,
        section: Annotated[str | None, Field(min_length=1, max_length=200)] = None,
        language: Literal["de", "en"] = "de",
        max_chars: Annotated[int, Field(ge=128, le=4000)] = 4000,
    ) -> ReadResponse:
        request = ReadInput(
            reference=reference,
            query=query,
            section=section,
            language=language,
            max_chars=max_chars,
        )
        try:
            key = reference_store.resolve(
                request.reference,
                principal=reference_store.principal,
                expected_kinds=("document",),
            )
        except ForgedReferenceError:
            return ReadResponse(
                status=ResearchStatus.ERROR,
                error=_error("forged_reference", "The document reference is invalid."),
            )
        document = catalog.document(key)
        if document is None:
            return ReadResponse(
                status=ResearchStatus.ERROR,
                error=_error("not_found", "The document is no longer available."),
            )
        provenance = _provenance(catalog, document)
        if request.query is None and request.section is None:
            response = ReadResponse(
                status=ResearchStatus.OK,
                outline=[
                    OutlineEntry(heading=item.heading, locator=item.locator)
                    for item in document.sections
                ],
                coverage=[_coverage(document.source, Jurisdiction.DE)],
                freshness=[_freshness(catalog, document.source, document.source_modified_at)],
                provenance=[provenance],
            )
            return fit_response(response, response.outline)
        if request.query is not None:
            terms = request.query.casefold().split()
            selected = [
                item
                for item in document.sections
                if all(term in f"{item.heading} {item.text}".casefold() for term in terms)
            ]
        else:
            selected = [item for item in document.sections if item.heading == request.section]
        if not selected:
            return ReadResponse(
                status=ResearchStatus.ERROR,
                error=_error("not_found", "No matching passage was found."),
                provenance=[provenance],
            )
        passages: list[Passage] = []
        used = 0
        for item in selected:
            if used + len(item.text) > request.max_chars:
                if not passages:
                    return ReadResponse(
                        status=ResearchStatus.ERROR,
                        error=_error(
                            "oversized",
                            "The smallest whole passage exceeds the requested budget.",
                        ),
                        provenance=[provenance],
                    )
                break
            passages.append(
                Passage(
                    heading=item.heading,
                    locator=item.locator,
                    text=item.text,
                    source_language=document.source_language,
                    provenance=provenance,
                )
            )
            used += len(item.text)
        response = ReadResponse(
            status=ResearchStatus.OK,
            passages=passages,
            coverage=[_coverage(document.source, Jurisdiction.DE)],
            freshness=[_freshness(catalog, document.source, document.source_modified_at)],
            provenance=[provenance],
        )
        return _trim_whole_items(response, "passages")

    @server.tool(
        name="legislation_changes",
        description=tool_description("legislation_changes"),
        annotations=annotations,
        structured_output=True,
    )
    def legislation_changes(
        jurisdiction: Jurisdiction,
        since: str,
        source: Literal["dip", "ep", "cellar", "eurlex"] | None = None,
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
        cursor: Annotated[str | None, Field(min_length=12, max_length=200)] = None,
    ) -> ChangesResponse:
        ChangesInput(
            jurisdiction=jurisdiction,
            since=since,
            source=source,
            limit=limit,
            cursor=cursor,
        )
        return ChangesResponse(
            status=ResearchStatus.ERROR,
            error=_error("unsupported", "Observed change listing is not enabled."),
        )

    @server.tool(
        name="legislation_capabilities",
        description=tool_description("legislation_capabilities"),
        annotations=annotations,
        structured_output=True,
    )
    def legislation_capabilities(
        jurisdiction: Jurisdiction | None = None,
        source: Literal["dip", "ep", "cellar", "eurlex"] | None = None,
    ) -> CapabilitiesResponse:
        request = CapabilitiesInput(jurisdiction=jurisdiction, source=source)
        dip_live = live_dip is not None and live_dip.configured
        dip_operations = (
            ["search", "procedure"] if dip_live else catalog.available_operations("dip")
        )
        cellar_operations = catalog.available_operations("cellar")
        capabilities = [
            SourceCapability(
                source="dip",
                jurisdiction=Jurisdiction.DE,
                state="ready" if dip_operations else "not_configured",
                operations=dip_operations,
                limitations=(
                    [
                        "Live DIP search matches words in procedure titles, DIP ids, and GESTA "
                        "numbers."
                    ]
                    if dip_live
                    else ["The local index is not a complete historical backfill."]
                    if dip_operations
                    else [DIP_SETUP_MESSAGE]
                ),
            ),
            SourceCapability(
                source="cellar",
                jurisdiction=Jurisdiction.EU,
                state="ready" if cellar_operations else "not_configured",
                operations=cellar_operations,
                limitations=["Identifier retrieval is not full-text EUR-Lex search."],
            ),
            SourceCapability(
                source="ep",
                jurisdiction=Jurisdiction.EU,
                state="not_configured",
                operations=[],
            ),
            SourceCapability(
                source="eurlex",
                jurisdiction=Jurisdiction.EU,
                state="not_configured",
                operations=[],
            ),
        ]
        filtered = [
            item
            for item in capabilities
            if (request.jurisdiction is None or item.jurisdiction == request.jurisdiction)
            and (request.source is None or item.source == request.source)
        ]
        response = CapabilitiesResponse(status=ResearchStatus.OK, sources=filtered)
        return fit_response(response, response.sources)

    names = [
        "legislation_search",
        "legislation_procedure",
        "legislation_records",
        "legislation_read",
        "legislation_changes",
        "legislation_capabilities",
    ]
    _strict_tool_inputs(server, names)
