"""Typed contracts shared by legislation research tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_RESULT_BYTES = 16_384


class StrictModel(BaseModel):
    """A wire model that rejects fields outside its published contract."""

    model_config = ConfigDict(extra="forbid")


class Jurisdiction(StrEnum):
    DE = "DE"
    EU = "EU"


class ResearchStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    ERROR = "error"


class ResearchError(StrictModel):
    code: Literal[
        "not_configured",
        "unsupported",
        "forged_reference",
        "forged_cursor",
        "expired_cursor",
        "not_found",
        "oversized",
        "temporarily_unavailable",
    ]
    message: str
    retryable: bool = False


class ResearchWarning(StrictModel):
    code: str
    message: str


class Coverage(StrictModel):
    source: str
    jurisdiction: Jurisdiction
    complete: bool
    limitations: list[str] = Field(default_factory=list)


class Freshness(StrictModel):
    source: str
    retrieved_at: str
    indexed_at: str
    source_modified_at: str | None = None


class Provenance(StrictModel):
    source: str
    provider_id: str
    official_url: str
    retrieved_at: str
    source_modified_at: str | None = None


class Continuation(StrictModel):
    cursor: str
    expires_at: str


class Locator(StrictModel):
    kind: Literal["paragraph", "page", "section", "article"]
    start: str
    end: str


class SearchInput(StrictModel):
    jurisdiction: Jurisdiction
    query: str | None = Field(default=None, min_length=1, max_length=300)
    identifier: str | None = Field(default=None, min_length=1, max_length=100)
    kind: Literal["procedure", "legal_text"] = "procedure"
    source: Literal["dip", "ep", "cellar", "eurlex"] | None = None
    language: Literal["de", "en"] = "de"
    limit: int = Field(default=5, ge=1, le=10)
    cursor: str | None = Field(default=None, min_length=12, max_length=200)

    @model_validator(mode="after")
    def require_one_search_term(self) -> SearchInput:
        if (self.query is None) == (self.identifier is None):
            raise ValueError("Provide exactly one of query or identifier")
        return self


class ProcedureInput(StrictModel):
    reference: str = Field(min_length=12, max_length=200)
    language: Literal["de", "en"] = "de"


class RecordsInput(StrictModel):
    jurisdiction: Jurisdiction
    kind: Literal["speech", "question", "committee_document", "adopted_text"]
    query: str | None = Field(default=None, min_length=1, max_length=300)
    language: Literal["de", "en"] = "de"
    limit: int = Field(default=5, ge=1, le=10)
    cursor: str | None = Field(default=None, min_length=12, max_length=200)


class ReadInput(StrictModel):
    reference: str = Field(min_length=12, max_length=200)
    query: str | None = Field(default=None, min_length=1, max_length=300)
    section: str | None = Field(default=None, min_length=1, max_length=200)
    language: Literal["de", "en"] = "de"
    max_chars: int = Field(default=4000, ge=128, le=4000)

    @model_validator(mode="after")
    def choose_one_passage_selector(self) -> ReadInput:
        if self.query is not None and self.section is not None:
            raise ValueError("Provide at most one of query or section")
        return self


class ChangesInput(StrictModel):
    jurisdiction: Jurisdiction
    source: Literal["dip", "ep", "cellar", "eurlex"] | None = None
    since: str
    limit: int = Field(default=5, ge=1, le=10)
    cursor: str | None = Field(default=None, min_length=12, max_length=200)


class CapabilitiesInput(StrictModel):
    jurisdiction: Jurisdiction | None = None
    source: Literal["dip", "ep", "cellar", "eurlex"] | None = None


class SearchCard(StrictModel):
    reference: str
    kind: Literal["procedure", "legal_text"]
    jurisdiction: Jurisdiction
    source: str
    identifier: str
    title: str
    abstract: str
    status: str
    official_url: str
    source_language: str
    requested_language: str
    translation_scope: Literal["labels_only"] = "labels_only"
    provenance: Provenance


class ProcedureEvent(StrictModel):
    date: str
    label: str


class DocumentCard(StrictModel):
    reference: str
    title: str
    official_url: str
    source_language: str
    provenance: Provenance


class ProcedureDetail(StrictModel):
    reference: str
    identifier: str
    title: str
    status: str
    source_language: str
    events: list[ProcedureEvent]
    documents: list[DocumentCard]


class Passage(StrictModel):
    heading: str
    locator: Locator
    text: str
    source_language: str
    provenance: Provenance


class OutlineEntry(StrictModel):
    heading: str
    locator: Locator


class SourceCapability(StrictModel):
    source: str
    jurisdiction: Jurisdiction
    state: Literal["ready", "not_configured", "unsupported"]
    operations: list[str]
    limitations: list[str] = Field(default_factory=list)


class ResponseBase(StrictModel):
    status: ResearchStatus
    warnings: list[ResearchWarning] = Field(default_factory=list)
    coverage: list[Coverage] = Field(default_factory=list)
    freshness: list[Freshness] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)
    error: ResearchError | None = None


def fit_response(
    response: Any,
    optional_items: list[Any],
    *,
    oversized_error: Any | None = None,
) -> Any:
    """Enforce the wire budget by dropping only whole optional items."""
    if len(response.model_dump_json().encode()) <= MAX_RESULT_BYTES:
        return response
    response.warnings.append(
        ResearchWarning(
            code="response_trimmed",
            message="Whole optional items were removed to fit the response budget.",
        )
    )
    while optional_items and len(response.model_dump_json().encode()) > MAX_RESULT_BYTES:
        optional_items.pop()
    if len(response.model_dump_json().encode()) > MAX_RESULT_BYTES:
        error = oversized_error or ResearchError(
            code="oversized",
            message="Mandatory warnings and provenance exceed the response budget.",
        )
        compact = type(response)(status=ResearchStatus.ERROR, error=error)
        if len(compact.model_dump_json().encode()) > MAX_RESULT_BYTES:
            raise RuntimeError("Typed oversized response exceeds the wire budget")
        return compact
    return response


class SearchResponse(ResponseBase):
    items: list[SearchCard] = Field(default_factory=list)
    continuation: Continuation | None = None


class ProcedureResponse(ResponseBase):
    procedure: ProcedureDetail | None = None


class RecordsResponse(ResponseBase):
    records: list[SearchCard] = Field(default_factory=list)
    continuation: Continuation | None = None


class ReadResponse(ResponseBase):
    outline: list[OutlineEntry] = Field(default_factory=list)
    passages: list[Passage] = Field(default_factory=list)


class ChangesResponse(ResponseBase):
    changes: list[SearchCard] = Field(default_factory=list)
    continuation: Continuation | None = None


class CapabilitiesResponse(ResponseBase):
    sources: list[SourceCapability] = Field(default_factory=list)
