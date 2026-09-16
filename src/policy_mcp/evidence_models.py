"""Strict public models and typed failures for evidence adapters."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base for evidence values crossing an adapter boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)


class EvidenceAdapterError(RuntimeError):
    """Base error for a provider failure safe to expose to callers."""


class ProviderResponseError(EvidenceAdapterError):
    """The provider returned an HTTP or application-level failure."""


class DatasetValidationError(EvidenceAdapterError):
    """A dataset query does not match its described structure."""


class ResultTooLargeError(DatasetValidationError):
    """A dataset query exceeds the interactive result budget."""


class CatalogueDistribution(StrictModel):
    """One GovData distribution, conservatively disabled for querying."""

    provider_id: str
    title: str | None = None
    url: str
    format: str | None = None
    queryable: Literal[False] = False


class CatalogueRecord(StrictModel):
    """Compact metadata for one GovData package."""

    provider_id: str
    title: str
    description: str | None = None
    publisher: str | None = None
    modified_at: str | None = None
    licence: str | None = None
    distributions: tuple[CatalogueDistribution, ...] = ()


class CatalogueSearchPage(StrictModel):
    """One bounded page of GovData records."""

    items: tuple[CatalogueRecord, ...]
    total: int = Field(ge=0)
    next_start: int | None = Field(default=None, ge=0)


class DatasetCard(StrictModel):
    """Small GENESIS table search result."""

    provider_id: str
    title: str
    description: str | None = None


class DatasetSearchPage(StrictModel):
    """One bounded page of GENESIS table results."""

    items: tuple[DatasetCard, ...]


class DimensionMember(StrictModel):
    """One allowed member of a dataset dimension."""

    member_id: str
    label: str


class DatasetDimension(StrictModel):
    """One selectable GENESIS dimension."""

    dimension_id: str
    label: str
    members: tuple[DimensionMember, ...]


class DatasetDescription(StrictModel):
    """Stored GENESIS structure used to validate later slices."""

    provider_id: str
    title: str
    schema_version: str
    dimensions: tuple[DatasetDimension, ...]
    measures: tuple[str, ...] = ("value",)
    unit: str | None = None


class DatasetSelection(StrictModel):
    """Typed dimension selection accepted by GENESIS queries."""

    dimension_id: str
    member_ids: tuple[str, ...] = Field(min_length=1)


class NumericCell(StrictModel):
    """Parsed value that always retains the provider's original text."""

    source_text: str
    value: Decimal | None
    status: Literal["value", "missing", "suppressed"]


class DatasetRow(StrictModel):
    """One normalized GENESIS result row."""

    dimensions: dict[str, str]
    cells: tuple[NumericCell, ...]


class DatasetResult(StrictModel):
    """A bounded normalized GENESIS slice."""

    provider_id: str
    schema_version: str
    measures: tuple[str, ...]
    rows: tuple[DatasetRow, ...]
