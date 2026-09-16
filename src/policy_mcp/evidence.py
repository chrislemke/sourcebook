"""Frozen quantitative and financial evidence MCP tools."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from functools import reduce
from operator import mul
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field, model_validator

from policy_mcp.contracts import tool_description
from policy_mcp.evidence_models import (
    CatalogueDistribution,
    DatasetDescription,
    DatasetDimension,
    DimensionMember,
    NumericCell,
)
from policy_mcp.references import (
    MAX_SNAPSHOT_ITEMS,
    ExpiredCursorError,
    ForgedCursorError,
    ForgedReferenceError,
    ReferenceStore,
)
from policy_mcp.research_contracts import (
    Continuation,
    Coverage,
    Freshness,
    Jurisdiction,
    Provenance,
    ResearchStatus,
    ResearchWarning,
    StrictModel,
    fit_response,
)

EvidenceKind = Literal[
    "dataset",
    "budget",
    "notice",
    "procurement_procedure",
    "lot",
    "award",
    "funding_call",
    "funded_project",
    "catalogue",
]
EvidenceSource = Literal["genesis", "federal_budget", "ted", "funding_tenders", "govdata"]


class EvidenceError(StrictModel):
    code: Literal[
        "not_configured",
        "unsupported",
        "forged_reference",
        "forged_cursor",
        "expired_cursor",
        "not_found",
        "stale_schema",
        "unknown_dimension",
        "missing_dimension",
        "unknown_member",
        "duplicate_selection",
        "duplicate_member",
        "unknown_measure",
        "oversized",
        "double_counting",
        "incompatible_records",
    ]
    message: str
    retryable: bool = False
    detail: dict[str, int | str] = Field(default_factory=dict)


class EvidenceResponse(StrictModel):
    status: ResearchStatus
    warnings: list[ResearchWarning] = Field(default_factory=list)
    coverage: list[Coverage] = Field(default_factory=list)
    freshness: list[Freshness] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)
    error: EvidenceError | None = None


class EvidenceCard(StrictModel):
    reference: str
    source: EvidenceSource
    kind: EvidenceKind
    provider_id: str
    title: str
    description: str
    official_url: str
    provenance: Provenance


class EvidenceSearchResponse(EvidenceResponse):
    items: list[EvidenceCard] = Field(default_factory=list)
    continuation: Continuation | None = None


class EvidenceDatasetDescription(DatasetDescription):
    scale: int
    population: str


class EvidenceDescribeResponse(EvidenceResponse):
    dataset: EvidenceDatasetDescription | None = None
    continuation: Continuation | None = None


class SelectionInput(StrictModel):
    dimension_id: str = Field(min_length=1, max_length=50)
    member_ids: list[str] = Field(min_length=1, max_length=100)


class EvidenceValue(NumericCell):
    measure: str
    symbol: str | None = None


class EvidenceRow(StrictModel):
    dimensions: dict[str, str]
    values: list[EvidenceValue]
    unit: str
    scale: int
    period: str
    population: str
    territory: str
    footnotes: list[str]


class BudgetAggregate(StrictModel):
    amount: Decimal
    currency: str
    source_unit: str
    stage: str
    flow: str
    record_count: int


class EvidenceQueryResponse(EvidenceResponse):
    provider_id: str | None = None
    schema_version: str | None = None
    measures: list[str] = Field(default_factory=list)
    rows: list[EvidenceRow] = Field(default_factory=list)
    aggregate: BudgetAggregate | None = None
    continuation: Continuation | None = None


class DetailBase(StrictModel):
    reference: str
    source: EvidenceSource
    provider_id: str
    title: str
    description: str
    official_url: str
    provenance: Provenance


class BudgetDetail(DetailBase):
    kind: Literal["budget"] = "budget"
    fiscal_year: int
    stage: Literal["draft", "enacted", "supplementary", "actual"]
    flow: Literal["revenue", "expenditure"]
    amount: Decimal
    currency: str
    source_unit: str
    classification_version: str
    hierarchy_path: list[str]
    parent_reference: str | None = None
    child_references: list[str] = Field(default_factory=list)
    may_sum_with_children: Literal[False] = False


class TedDetail(DetailBase):
    kind: Literal["notice", "procurement_procedure", "lot", "award"]
    linked_references: list[str] = Field(default_factory=list)
    country: str | None = None
    buyer: str | None = None
    classification: str | None = None


class FundingCallDetail(DetailBase):
    kind: Literal["funding_call"] = "funding_call"
    programme: str
    state: str
    deadline: str


class FundedProjectDetail(DetailBase):
    kind: Literal["funded_project"] = "funded_project"
    programme: str
    state: str
    grant_amount: Decimal
    currency: str


class CatalogueDetail(DetailBase):
    kind: Literal["catalogue"] = "catalogue"
    publisher: str
    licence: str
    distributions: list[CatalogueDistribution]


EvidenceDetail = (
    BudgetDetail | TedDetail | FundingCallDetail | FundedProjectDetail | CatalogueDetail
)


class _DetailCommon(TypedDict):
    reference: str
    source: EvidenceSource
    provider_id: str
    title: str
    description: str
    official_url: str
    provenance: Provenance


class EvidenceGetResponse(EvidenceResponse):
    record: EvidenceDetail | None = None


class EvidenceCapability(StrictModel):
    route: str
    state: Literal["ready", "not_configured", "unsupported"]
    operations: list[str]
    limitations: list[str] = Field(default_factory=list)


class EvidenceCapabilitiesResponse(EvidenceResponse):
    sources: list[EvidenceCapability] = Field(default_factory=list)


class SearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=300)
    source: EvidenceSource | None = None
    kind: EvidenceKind | None = None
    year: int | None = Field(default=None, ge=1900, le=2200)
    stage: Literal["draft", "enacted", "supplementary", "actual"] | None = None
    flow: Literal["revenue", "expenditure"] | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    limit: int = Field(default=5, ge=1, le=10)
    cursor: str | None = Field(default=None, min_length=12, max_length=200)


class DescribeInput(StrictModel):
    reference: str = Field(min_length=12, max_length=200)
    member_limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=12, max_length=200)


class QueryInput(StrictModel):
    reference: str | None = Field(default=None, min_length=12, max_length=200)
    references: list[str] | None = Field(default=None, min_length=1, max_length=25)
    schema_version: str | None = Field(default=None, min_length=1, max_length=200)
    selections: list[SelectionInput] | None = None
    measures: list[str] | None = Field(default=None, min_length=1, max_length=25)

    @model_validator(mode="after")
    def choose_query_mode(self) -> QueryInput:
        if (self.reference is None) == (self.references is None):
            raise ValueError("Provide one dataset reference or a list of budget references")
        return self


class GetInput(StrictModel):
    reference: str = Field(min_length=12, max_length=200)


class CapabilityInput(StrictModel):
    route: str | None = Field(default=None, min_length=1, max_length=100)


class _Record(StrictModel):
    key: str
    source: EvidenceSource
    kind: EvidenceKind
    provider_id: str
    title: str
    description: str
    official_url: str
    modified_at: str
    subjects: list[str]
    details: dict[str, Any]


class _Fixture(StrictModel):
    retrieved_at: str
    indexed_at: str
    records: list[_Record]


class FrozenEvidenceCatalog:
    """Read-only local metadata and value catalog built from a frozen fixture."""

    def __init__(self, fixture: _Fixture) -> None:
        self.retrieved_at = fixture.retrieved_at
        self.indexed_at = fixture.indexed_at
        self._records = {record.key: record for record in fixture.records}

    @classmethod
    def empty(cls) -> FrozenEvidenceCatalog:
        """Create an unconfigured production catalog without sample evidence."""
        return cls(_Fixture(retrieved_at="", indexed_at="", records=[]))

    @classmethod
    def from_json(cls, path: Path) -> FrozenEvidenceCatalog:
        return cls(_Fixture.model_validate_json(path.read_text()))

    def record(self, key: str) -> _Record | None:
        return self._records.get(key)

    @property
    def ready_sources(self) -> set[EvidenceSource]:
        return {record.source for record in self._records.values()}

    def search(self, request: SearchInput) -> list[_Record]:
        terms = request.query.casefold().split()
        records: list[_Record] = []
        for record in self._records.values():
            searchable = " ".join([record.title, record.description, *record.subjects]).casefold()
            if not all(term in searchable for term in terms):
                continue
            if request.source is not None and record.source != request.source:
                continue
            if request.kind is not None and record.kind != request.kind:
                continue
            if request.year is not None and record.details.get("fiscal_year") != request.year:
                continue
            if request.stage is not None and record.details.get("stage") != request.stage:
                continue
            if request.flow is not None and record.details.get("flow") != request.flow:
                continue
            if request.country is not None and record.details.get("country") != request.country:
                continue
            records.append(record)
            if len(records) > MAX_SNAPSHOT_ITEMS:
                break
        return records


def _jurisdiction(source: EvidenceSource) -> Jurisdiction:
    return Jurisdiction.EU if source in ("ted", "funding_tenders") else Jurisdiction.DE


def _provenance(catalog: FrozenEvidenceCatalog, record: _Record) -> Provenance:
    return Provenance(
        source=record.source,
        provider_id=record.provider_id,
        official_url=record.official_url,
        retrieved_at=catalog.retrieved_at,
        source_modified_at=record.modified_at,
    )


def _coverage(record: _Record) -> Coverage:
    return Coverage(
        source=record.source,
        jurisdiction=_jurisdiction(record.source),
        complete=False,
        limitations=["This frozen local catalog does not claim complete source coverage."],
    )


def _freshness(catalog: FrozenEvidenceCatalog, record: _Record) -> Freshness:
    return Freshness(
        source=record.source,
        retrieved_at=catalog.retrieved_at,
        indexed_at=catalog.indexed_at,
        source_modified_at=record.modified_at,
    )


def _error(
    code: Any,
    message: str,
    *,
    retryable: bool = False,
    detail: dict[str, int | str] | None = None,
) -> EvidenceError:
    return EvidenceError(
        code=code,
        message=message,
        retryable=retryable,
        detail=detail or {},
    )


def _hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _card(
    catalog: FrozenEvidenceCatalog,
    references: ReferenceStore,
    record: _Record,
) -> EvidenceCard:
    provenance = _provenance(catalog, record)
    return EvidenceCard(
        reference=references.reference_for(
            principal=references.principal,
            kind=record.kind,
            key=record.key,
        ),
        source=record.source,
        kind=record.kind,
        provider_id=record.provider_id,
        title=record.title,
        description=record.description,
        official_url=record.official_url,
        provenance=provenance,
    )


def _continuation(cursor: str | None, expires_at: Any) -> Continuation | None:
    if cursor is None or expires_at is None:
        return None
    return Continuation(cursor=cursor, expires_at=expires_at.isoformat())


def _fit(response: Any, field_name: str) -> Any:
    return fit_response(
        response,
        getattr(response, field_name),
        oversized_error=_error(
            "oversized", "Mandatory warnings and provenance exceed the response budget."
        ),
    )


def _strict_tool_inputs(server: MCPServer[Any], names: list[str]) -> None:
    manager = server._tool_manager
    for name in names:
        tool = manager.get_tool(name)
        if tool is None:  # pragma: no cover
            raise RuntimeError(f"Tool registration failed: {name}")
        tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
        tool.fn_metadata.arg_model.model_rebuild(force=True)
        tool.parameters = tool.fn_metadata.arg_model.model_json_schema(by_alias=True)


def _dataset_details(record: _Record) -> tuple[EvidenceDatasetDescription, dict[str, Any]]:
    details = record.details
    dimensions = tuple(
        DatasetDimension(
            dimension_id=item["dimension_id"],
            label=item["label"],
            members=tuple(
                DimensionMember(member_id=member["member_id"], label=member["label"])
                for member in item["members"]
            ),
        )
        for item in details["dimensions"]
    )
    description = EvidenceDatasetDescription(
        provider_id=record.provider_id,
        title=record.title,
        schema_version=details["schema_version"],
        dimensions=dimensions,
        measures=tuple(details["measures"]),
        unit=details["unit"],
        scale=details["scale"],
        population=details["population"],
    )
    return description, details


def register_evidence_tools(
    server: MCPServer[Any],
    catalog: FrozenEvidenceCatalog,
    reference_store: ReferenceStore,
) -> None:
    """Register the five stable evidence tools."""
    annotations = ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )

    @server.tool(
        name="evidence_search",
        description=tool_description("evidence_search"),
        annotations=annotations,
        structured_output=True,
    )
    def evidence_search(
        query: Annotated[str, Field(min_length=1, max_length=300)],
        source: EvidenceSource | None = None,
        kind: EvidenceKind | None = None,
        year: Annotated[int | None, Field(ge=1900, le=2200)] = None,
        stage: Literal["draft", "enacted", "supplementary", "actual"] | None = None,
        flow: Literal["revenue", "expenditure"] | None = None,
        country: Annotated[str | None, Field(min_length=2, max_length=2)] = None,
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
        cursor: Annotated[str | None, Field(min_length=12, max_length=200)] = None,
    ) -> EvidenceSearchResponse:
        request = SearchInput(
            query=query,
            source=source,
            kind=kind,
            year=year,
            stage=stage,
            flow=flow,
            country=country,
            limit=limit,
            cursor=cursor,
        )
        if not catalog.ready_sources or (
            request.source is not None and request.source not in catalog.ready_sources
        ):
            return EvidenceSearchResponse(
                status=ResearchStatus.ERROR,
                error=_error("not_configured", "No matching evidence route has passed its gate."),
            )
        digest = _hash(request.model_dump(mode="json", exclude={"limit", "cursor"}))
        try:
            if request.cursor is None:
                records = catalog.search(request)
                page = reference_store.first_page(
                    [record.key for record in records],
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
            return EvidenceSearchResponse(
                status=ResearchStatus.ERROR,
                error=_error("forged_cursor", "The cursor does not belong to this search."),
            )
        except ExpiredCursorError:
            return EvidenceSearchResponse(
                status=ResearchStatus.ERROR,
                error=_error(
                    "expired_cursor",
                    "The cursor expired. Restart the search.",
                    retryable=True,
                ),
            )
        except ValueError:
            return EvidenceSearchResponse(
                status=ResearchStatus.ERROR,
                error=_error("oversized", "The search matched too many bounded results."),
            )
        records = [record for key in page.keys if (record := catalog.record(key)) is not None]
        cards = [_card(catalog, reference_store, record) for record in records]
        response = EvidenceSearchResponse(
            status=ResearchStatus.OK,
            items=cards,
            continuation=_continuation(page.cursor, page.expires_at),
            coverage=[_coverage(record) for record in records],
            freshness=[_freshness(catalog, record) for record in records],
            provenance=[card.provenance for card in cards],
        )
        return _fit(response, "items")

    @server.tool(
        name="evidence_describe",
        description=tool_description("evidence_describe"),
        annotations=annotations,
        structured_output=True,
    )
    def evidence_describe(
        reference: Annotated[str, Field(min_length=12, max_length=200)],
        member_limit: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Field(min_length=12, max_length=200)] = None,
    ) -> EvidenceDescribeResponse:
        request = DescribeInput(
            reference=reference,
            member_limit=member_limit,
            cursor=cursor,
        )
        try:
            key = reference_store.resolve(
                request.reference,
                principal=reference_store.principal,
                expected_kinds=("dataset",),
            )
        except ForgedReferenceError:
            return EvidenceDescribeResponse(
                status=ResearchStatus.ERROR,
                error=_error("forged_reference", "The dataset reference is invalid."),
            )
        record = catalog.record(key)
        if record is None:
            return EvidenceDescribeResponse(
                status=ResearchStatus.ERROR,
                error=_error("not_found", "The dataset is no longer available."),
            )
        description, _ = _dataset_details(record)
        member_keys: list[str] = []
        for dimension in description.dimensions:
            for member in dimension.members:
                member_keys.append(f"{dimension.dimension_id}\0{member.member_id}")
                if len(member_keys) > MAX_SNAPSHOT_ITEMS:
                    break
            if len(member_keys) > MAX_SNAPSHOT_ITEMS:
                break
        digest = _hash({"reference": request.reference})
        try:
            if request.cursor is None:
                page = reference_store.first_page(
                    member_keys,
                    principal=reference_store.principal,
                    query_hash=digest,
                    limit=request.member_limit,
                )
            else:
                page = reference_store.next_page(
                    request.cursor,
                    principal=reference_store.principal,
                    query_hash=digest,
                    limit=request.member_limit,
                )
        except (ForgedCursorError, ExpiredCursorError) as error:
            code = "expired_cursor" if isinstance(error, ExpiredCursorError) else "forged_cursor"
            return EvidenceDescribeResponse(
                status=ResearchStatus.ERROR,
                error=_error(code, "The member continuation is invalid or expired."),
            )
        except ValueError:
            return EvidenceDescribeResponse(
                status=ResearchStatus.ERROR,
                error=_error("oversized", "The dataset has too many bounded members."),
            )
        allowed = set(page.keys)
        paged_dimensions = tuple(
            DatasetDimension(
                dimension_id=dimension.dimension_id,
                label=dimension.label,
                members=tuple(
                    member
                    for member in dimension.members
                    if f"{dimension.dimension_id}\0{member.member_id}" in allowed
                ),
            )
            for dimension in description.dimensions
            if any(
                f"{dimension.dimension_id}\0{member.member_id}" in allowed
                for member in dimension.members
            )
        )
        description = description.model_copy(update={"dimensions": paged_dimensions})
        provenance = _provenance(catalog, record)
        return EvidenceDescribeResponse(
            status=ResearchStatus.OK,
            dataset=description,
            continuation=_continuation(page.cursor, page.expires_at),
            coverage=[_coverage(record)],
            freshness=[_freshness(catalog, record)],
            provenance=[provenance],
        )

    @server.tool(
        name="evidence_query",
        description=tool_description("evidence_query"),
        annotations=annotations,
        structured_output=True,
    )
    def evidence_query(
        reference: Annotated[str | None, Field(min_length=12, max_length=200)] = None,
        references: Annotated[list[str] | None, Field(min_length=1, max_length=25)] = None,
        schema_version: Annotated[str | None, Field(min_length=1, max_length=200)] = None,
        selections: list[SelectionInput] | None = None,
        measures: Annotated[list[str] | None, Field(min_length=1, max_length=25)] = None,
    ) -> EvidenceQueryResponse:
        request = QueryInput(
            reference=reference,
            references=references,
            schema_version=schema_version,
            selections=selections,
            measures=measures,
        )
        if request.references is not None:
            return _query_budgets(catalog, reference_store, request.references)
        assert request.reference is not None
        try:
            key = reference_store.resolve(
                request.reference,
                principal=reference_store.principal,
                expected_kinds=("dataset",),
            )
        except ForgedReferenceError:
            return EvidenceQueryResponse(
                status=ResearchStatus.ERROR,
                error=_error("forged_reference", "The dataset reference is invalid."),
            )
        record = catalog.record(key)
        if record is None:
            return EvidenceQueryResponse(
                status=ResearchStatus.ERROR,
                error=_error("not_found", "The dataset is no longer available."),
            )
        description, details = _dataset_details(record)
        if request.schema_version != description.schema_version:
            return EvidenceQueryResponse(
                status=ResearchStatus.ERROR,
                error=_error(
                    "stale_schema",
                    "The stored dataset structure changed. Describe it again before querying.",
                ),
            )
        selections_value = request.selections or []
        selected_ids = [item.dimension_id for item in selections_value]
        if len(selected_ids) != len(set(selected_ids)):
            return EvidenceQueryResponse(
                status=ResearchStatus.ERROR,
                error=_error("duplicate_selection", "A dimension was selected more than once."),
            )
        known = {dimension.dimension_id: dimension for dimension in description.dimensions}
        for selection in selections_value:
            if selection.dimension_id not in known:
                return EvidenceQueryResponse(
                    status=ResearchStatus.ERROR,
                    error=_error(
                        "unknown_dimension", f"Unknown dimension: {selection.dimension_id}"
                    ),
                )
            if len(selection.member_ids) != len(set(selection.member_ids)):
                return EvidenceQueryResponse(
                    status=ResearchStatus.ERROR,
                    error=_error(
                        "duplicate_member",
                        f"Dimension {selection.dimension_id} repeats a member.",
                    ),
                )
            member_ids = {member.member_id for member in known[selection.dimension_id].members}
            unknown = [item for item in selection.member_ids if item not in member_ids]
            if unknown:
                return EvidenceQueryResponse(
                    status=ResearchStatus.ERROR,
                    error=_error("unknown_member", f"Unknown member: {unknown[0]}"),
                )
        missing = [item for item in known if item not in selected_ids]
        if missing:
            return EvidenceQueryResponse(
                status=ResearchStatus.ERROR,
                error=_error("missing_dimension", f"Missing dimension: {missing[0]}"),
            )
        selected_measures = request.measures or ["value"]
        unknown_measures = [item for item in selected_measures if item not in description.measures]
        if unknown_measures:
            return EvidenceQueryResponse(
                status=ResearchStatus.ERROR,
                error=_error("unknown_measure", f"Unknown measure: {unknown_measures[0]}"),
            )
        row_count = reduce(mul, (len(item.member_ids) for item in selections_value), 1)
        cell_count = row_count * len(selected_measures)
        if row_count > 25 or cell_count > 250:
            return EvidenceQueryResponse(
                status=ResearchStatus.ERROR,
                error=_error(
                    "oversized",
                    "The requested dataset slice exceeds the interactive limit.",
                    detail={"rows": row_count, "cells": cell_count},
                ),
            )
        selection_map = {item.dimension_id: set(item.member_ids) for item in selections_value}
        rows: list[EvidenceRow] = []
        for row in details["rows"]:
            if not all(
                row["dimensions"].get(dimension) in members
                for dimension, members in selection_map.items()
            ):
                continue
            values = []
            for measure in selected_measures:
                cell = row["values"].get(measure)
                if cell is None:
                    continue
                values.append(
                    EvidenceValue(
                        measure=measure,
                        source_text=cell["source_text"],
                        value=Decimal(cell["value"]) if cell["value"] is not None else None,
                        status=cell["status"],
                        symbol=cell["symbol"],
                    )
                )
            rows.append(
                EvidenceRow(
                    dimensions=row["dimensions"],
                    values=values,
                    unit=description.unit or "",
                    scale=description.scale,
                    period=row["period"],
                    population=description.population,
                    territory=row["territory"],
                    footnotes=row["footnotes"],
                )
            )
        provenance = _provenance(catalog, record)
        response = EvidenceQueryResponse(
            status=ResearchStatus.OK,
            provider_id=record.provider_id,
            schema_version=description.schema_version,
            measures=selected_measures,
            rows=rows,
            coverage=[_coverage(record)],
            freshness=[_freshness(catalog, record)],
            provenance=[provenance],
        )
        return _fit(response, "rows")

    @server.tool(
        name="evidence_get",
        description=tool_description("evidence_get"),
        annotations=annotations,
        structured_output=True,
    )
    def evidence_get(
        reference: Annotated[str, Field(min_length=12, max_length=200)],
    ) -> EvidenceGetResponse:
        request = GetInput(reference=reference)
        try:
            key = reference_store.resolve(
                request.reference,
                principal=reference_store.principal,
                expected_kinds=(
                    "budget",
                    "notice",
                    "procurement_procedure",
                    "lot",
                    "award",
                    "funding_call",
                    "funded_project",
                    "catalogue",
                ),
            )
        except ForgedReferenceError:
            return EvidenceGetResponse(
                status=ResearchStatus.ERROR,
                error=_error("forged_reference", "The evidence reference is invalid."),
            )
        record = catalog.record(key)
        if record is None:
            return EvidenceGetResponse(
                status=ResearchStatus.ERROR,
                error=_error("not_found", "The evidence record is no longer available."),
            )
        detail = _detail(catalog, reference_store, request.reference, record)
        provenance = _provenance(catalog, record)
        response = EvidenceGetResponse(
            status=ResearchStatus.OK,
            record=detail,
            coverage=[_coverage(record)],
            freshness=[_freshness(catalog, record)],
            provenance=[provenance],
        )
        return fit_response(
            response,
            [],
            oversized_error=_error("oversized", "The selected evidence record is too large."),
        )

    @server.tool(
        name="evidence_capabilities",
        description=tool_description("evidence_capabilities"),
        annotations=annotations,
        structured_output=True,
    )
    def evidence_capabilities(route: str | None = None) -> EvidenceCapabilitiesResponse:
        request = CapabilityInput(route=route)
        capabilities = [
            EvidenceCapability(
                route="genesis.query",
                state="ready" if "genesis" in catalog.ready_sources else "not_configured",
                operations=(
                    ["search", "describe", "query"] if "genesis" in catalog.ready_sources else []
                ),
            ),
            EvidenceCapability(
                route="federal_budget.enacted",
                state=("ready" if "federal_budget" in catalog.ready_sources else "not_configured"),
                operations=(["search", "get"] if "federal_budget" in catalog.ready_sources else []),
            ),
            EvidenceCapability(
                route="federal_budget.actuals", state="not_configured", operations=[]
            ),
            EvidenceCapability(
                route="ted.notice",
                state="ready" if "ted" in catalog.ready_sources else "not_configured",
                operations=["search", "get"] if "ted" in catalog.ready_sources else [],
            ),
            EvidenceCapability(
                route="funding_tenders.calls",
                state=("ready" if "funding_tenders" in catalog.ready_sources else "not_configured"),
                operations=(
                    ["search", "get"] if "funding_tenders" in catalog.ready_sources else []
                ),
            ),
            EvidenceCapability(
                route="funding_tenders.projects",
                state=("ready" if "funding_tenders" in catalog.ready_sources else "not_configured"),
                operations=(
                    ["search", "get"] if "funding_tenders" in catalog.ready_sources else []
                ),
            ),
            EvidenceCapability(
                route="govdata.catalogue",
                state="ready" if "govdata" in catalog.ready_sources else "not_configured",
                operations=["search", "get"] if "govdata" in catalog.ready_sources else [],
            ),
            EvidenceCapability(
                route="govdata.distribution_query",
                state="unsupported",
                operations=[],
                limitations=[
                    "Catalogue distributions are non-queryable until an adapter is allowlisted."
                ],
            ),
        ]
        if request.route is not None:
            capabilities = [item for item in capabilities if item.route == request.route]
        response = EvidenceCapabilitiesResponse(status=ResearchStatus.OK, sources=capabilities)
        return fit_response(
            response,
            response.sources,
            oversized_error=_error("oversized", "Capability metadata exceeds the response budget."),
        )

    _strict_tool_inputs(
        server,
        [
            "evidence_search",
            "evidence_describe",
            "evidence_query",
            "evidence_get",
            "evidence_capabilities",
        ],
    )


def _query_budgets(
    catalog: FrozenEvidenceCatalog,
    references: ReferenceStore,
    tokens: list[str],
) -> EvidenceQueryResponse:
    records: list[_Record] = []
    try:
        for token in tokens:
            key = references.resolve(
                token,
                principal=references.principal,
                expected_kinds=("budget",),
            )
            record = catalog.record(key)
            if record is None:
                return EvidenceQueryResponse(
                    status=ResearchStatus.ERROR,
                    error=_error("not_found", "A budget record is no longer available."),
                )
            records.append(record)
    except ForgedReferenceError:
        return EvidenceQueryResponse(
            status=ResearchStatus.ERROR,
            error=_error("forged_reference", "A budget reference is invalid."),
        )
    keys = {record.key for record in records}
    if any(
        record.details.get("parent_key") in keys
        or bool(keys.intersection(record.details.get("child_keys", [])))
        for record in records
    ):
        return EvidenceQueryResponse(
            status=ResearchStatus.ERROR,
            error=_error(
                "double_counting",
                "A parent budget total cannot be added to one of its child records.",
            ),
        )
    signatures = {
        (
            record.details["currency"],
            record.details["source_unit"],
            record.details["stage"],
            record.details["flow"],
        )
        for record in records
    }
    if len(signatures) != 1:
        return EvidenceQueryResponse(
            status=ResearchStatus.ERROR,
            error=_error(
                "incompatible_records",
                "Budget records with different units, stages, or flows cannot be summed.",
            ),
        )
    currency, source_unit, stage, flow = signatures.pop()
    return EvidenceQueryResponse(
        status=ResearchStatus.OK,
        aggregate=BudgetAggregate(
            amount=sum((Decimal(record.details["amount"]) for record in records), Decimal()),
            currency=currency,
            source_unit=source_unit,
            stage=stage,
            flow=flow,
            record_count=len(records),
        ),
        coverage=[_coverage(record) for record in records],
        freshness=[_freshness(catalog, record) for record in records],
        provenance=[_provenance(catalog, record) for record in records],
    )


def _detail(
    catalog: FrozenEvidenceCatalog,
    references: ReferenceStore,
    token: str,
    record: _Record,
) -> EvidenceDetail:
    common: _DetailCommon = {
        "reference": token,
        "source": record.source,
        "provider_id": record.provider_id,
        "title": record.title,
        "description": record.description,
        "official_url": record.official_url,
        "provenance": _provenance(catalog, record),
    }
    details = record.details
    if record.kind == "budget":
        parent_key = details.get("parent_key")
        return BudgetDetail(
            **common,
            fiscal_year=details["fiscal_year"],
            stage=details["stage"],
            flow=details["flow"],
            amount=Decimal(details["amount"]),
            currency=details["currency"],
            source_unit=details["source_unit"],
            classification_version=details["classification_version"],
            hierarchy_path=details["hierarchy_path"],
            parent_reference=(
                references.reference_for(
                    principal=references.principal,
                    kind="budget",
                    key=parent_key,
                )
                if parent_key
                else None
            ),
            child_references=[
                references.reference_for(
                    principal=references.principal,
                    kind="budget",
                    key=key,
                )
                for key in details["child_keys"]
            ],
        )
    linked_references: list[str] = []
    for key in details.get("linked_keys", []):
        linked = catalog.record(key)
        linked_references.append(
            references.reference_for(
                principal=references.principal,
                kind=linked.kind if linked is not None else "unknown",
                key=key,
            )
        )
    if record.kind in ("notice", "procurement_procedure", "lot", "award"):
        return TedDetail(
            **common,
            kind=record.kind,
            linked_references=linked_references,
            country=details.get("country"),
            buyer=details.get("buyer"),
            classification=details.get("classification"),
        )
    if record.kind == "funding_call":
        return FundingCallDetail(
            **common,
            programme=details["programme"],
            state=details["status"],
            deadline=details["deadline"],
        )
    if record.kind == "funded_project":
        return FundedProjectDetail(
            **common,
            programme=details["programme"],
            state=details["status"],
            grant_amount=Decimal(details["grant_amount"]),
            currency=details["currency"],
        )
    if record.kind == "catalogue":
        return CatalogueDetail(
            **common,
            publisher=details["publisher"],
            licence=details["licence"],
            distributions=[CatalogueDistribution(**item) for item in details["distributions"]],
        )
    raise ValueError(f"Unsupported selected record kind: {record.kind}")
