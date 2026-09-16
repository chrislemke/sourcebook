"""Frozen legislation catalog and MCP tool registration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from policy_mcp.contracts import tool_description
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

    @classmethod
    def from_json(cls, path: Path) -> FrozenLegislationCatalog:
        """Load one frozen catalog fixture."""
        return cls(_Fixture.model_validate_json(path.read_text()))

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
            if wanted is not None and record.identifier.casefold() != wanted:
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
        "The local fixture is not a complete historical backfill."
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


def register_legislation_tools(
    server: MCPServer[Any],
    catalog: FrozenLegislationCatalog,
    reference_store: ReferenceStore,
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
    def legislation_search(
        jurisdiction: Jurisdiction,
        query: Annotated[str | None, Field(min_length=1, max_length=300)] = None,
        identifier: Annotated[str | None, Field(min_length=1, max_length=100)] = None,
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
        if expected_source not in catalog.ready_sources:
            return _source_error(
                "not_configured",
                f"Source {expected_source} has not passed its ingestion gate.",
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
    def legislation_procedure(
        reference: Annotated[str, Field(min_length=12, max_length=200)],
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
        provenance = _provenance(catalog, record)
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
            coverage=[_coverage(record.source, record.jurisdiction)],
            freshness=[_freshness(catalog, record.source, record.source_modified_at)],
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
        capabilities = [
            SourceCapability(
                source="dip",
                jurisdiction=Jurisdiction.DE,
                state="ready" if "dip" in catalog.ready_sources else "not_configured",
                operations=(
                    ["search", "procedure", "read"] if "dip" in catalog.ready_sources else []
                ),
                limitations=["The local index is not a complete historical backfill."],
            ),
            SourceCapability(
                source="cellar",
                jurisdiction=Jurisdiction.EU,
                state="ready" if "cellar" in catalog.ready_sources else "not_configured",
                operations=(
                    ["identifier_lookup", "read"] if "cellar" in catalog.ready_sources else []
                ),
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
