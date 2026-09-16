"""Typed, bounded client for the GENESIS REST service."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from math import prod
from typing import Any

import httpx

from policy_mcp.evidence_models import (
    DatasetCard,
    DatasetDescription,
    DatasetDimension,
    DatasetResult,
    DatasetRow,
    DatasetSearchPage,
    DatasetSelection,
    DatasetValidationError,
    DimensionMember,
    NumericCell,
    ProviderResponseError,
    ResultTooLargeError,
)
from policy_mcp.source_http import BoundedHttpClient, Resolver, SourceRequestError, resolve_host

BASE_URL = "https://genesis.destatis.de/genesisWS/rest/2020"


class GenesisClient:
    """Read GENESIS tables with a token kept outside public values."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        token: str,
        max_response_bytes: int = 2_000_000,
        resolver: Resolver = resolve_host,
    ) -> None:
        if not token:
            raise ValueError("GENESIS token must not be empty")
        self._http = BoundedHttpClient(
            client,
            allowed_hosts={"genesis.destatis.de"},
            resolver=resolver,
            max_response_bytes=max_response_bytes,
        )
        self._token = token
        self._descriptions: dict[str, DatasetDescription] = {}

    async def search(self, query: str, *, limit: int = 5) -> DatasetSearchPage:
        """Search table metadata using the documented POST operation."""
        if not query.strip():
            raise ValueError("GENESIS search requires a non-empty query")
        if not 1 <= limit <= 10:
            raise ValueError("GENESIS search limit must be between 1 and 10")
        payload = await self._post(
            "find/find",
            data={"term": query, "category": "tables", "pagelength": str(limit)},
        )
        values = payload.get("List")
        if not isinstance(values, list):
            raise ProviderResponseError("GENESIS returned an invalid search result")
        cards: list[DatasetCard] = []
        for value in values:
            if not isinstance(value, dict):
                raise ProviderResponseError("GENESIS returned an invalid table card")
            code = value.get("Code")
            title = value.get("Content")
            if not isinstance(code, str) or not isinstance(title, str):
                raise ProviderResponseError("GENESIS table card omitted its identity")
            description = value.get("Description")
            cards.append(
                DatasetCard(
                    provider_id=code,
                    title=title,
                    description=description if isinstance(description, str) else None,
                )
            )
        return DatasetSearchPage(items=tuple(cards))

    async def describe(self, provider_id: str) -> DatasetDescription:
        """Return and retain the structure that later slice queries must match."""
        if not provider_id.strip():
            raise ValueError("GENESIS table identifier must not be empty")
        payload = await self._post("metadata/table", data={"name": provider_id})
        value = payload.get("Object")
        if not isinstance(value, dict):
            raise ProviderResponseError("GENESIS returned invalid table metadata")
        code = value.get("Code")
        title = value.get("Content")
        dimensions_value = value.get("Dimensions")
        if (
            not isinstance(code, str)
            or not isinstance(title, str)
            or not isinstance(dimensions_value, list)
        ):
            raise ProviderResponseError("GENESIS table metadata omitted required fields")
        dimensions: list[DatasetDimension] = []
        for dimension_value in dimensions_value:
            dimensions.append(self._parse_dimension(dimension_value))
        measures_value = value.get("Measures", ["value"])
        if not isinstance(measures_value, list) or not all(
            isinstance(measure, str) for measure in measures_value
        ):
            raise ProviderResponseError("GENESIS table measures are invalid")
        schema_version = value.get("SchemaVersion")
        if not isinstance(schema_version, str):
            canonical = json.dumps(dimensions_value, ensure_ascii=False, sort_keys=True)
            schema_version = hashlib.sha256(canonical.encode()).hexdigest()
        description = DatasetDescription(
            provider_id=code,
            title=title,
            schema_version=schema_version,
            dimensions=tuple(dimensions),
            measures=tuple(measures_value),
            unit=value.get("Unit") if isinstance(value.get("Unit"), str) else None,
        )
        self._descriptions[code] = description
        return description

    async def query(
        self,
        provider_id: str,
        *,
        schema_version: str,
        selections: tuple[DatasetSelection, ...],
        measures: tuple[str, ...] = ("value",),
        row_limit: int = 25,
    ) -> DatasetResult:
        """Retrieve a slice after validating it against a described structure."""
        description = self._descriptions.get(provider_id)
        if description is None:
            raise DatasetValidationError("Describe the GENESIS table before querying it")
        if schema_version != description.schema_version:
            raise DatasetValidationError("GENESIS dataset schema version is stale")
        if not 1 <= row_limit <= 25:
            raise ResultTooLargeError("GENESIS queries allow at most 25 rows")
        if not selections:
            raise DatasetValidationError("GENESIS query requires typed dimension selections")
        if not measures:
            raise DatasetValidationError("GENESIS query requires at least one measure")

        dimensions = {dimension.dimension_id: dimension for dimension in description.dimensions}
        seen_dimensions: set[str] = set()
        for selection in selections:
            if selection.dimension_id in seen_dimensions:
                raise DatasetValidationError("GENESIS query repeats a dimension selection")
            seen_dimensions.add(selection.dimension_id)
            dimension = dimensions.get(selection.dimension_id)
            if dimension is None:
                raise DatasetValidationError("GENESIS query contains an unknown dimension")
            if len(selection.member_ids) != len(set(selection.member_ids)):
                raise DatasetValidationError("GENESIS query repeats a dimension member")
            known_members = {member.member_id for member in dimension.members}
            if any(member not in known_members for member in selection.member_ids):
                raise DatasetValidationError("GENESIS query contains an unknown dimension member")

        if len(measures) != len(set(measures)):
            raise DatasetValidationError("GENESIS query repeats a measure")
        if any(measure not in description.measures for measure in measures):
            raise DatasetValidationError("GENESIS query contains an unknown measure")
        requested_rows = prod(len(selection.member_ids) for selection in selections)
        if requested_rows > row_limit:
            raise ResultTooLargeError("GENESIS selection exceeds the requested row limit")
        if requested_rows * len(measures) > 250:
            raise ResultTooLargeError("GENESIS selection exceeds the 250-cell limit")

        payload = await self._post(
            "data/table",
            data={
                "name": provider_id,
                "selection": json.dumps(
                    [selection.model_dump(mode="json") for selection in selections],
                    separators=(",", ":"),
                ),
                "measures": ",".join(measures),
                "rowlimit": str(row_limit),
            },
        )
        value = payload.get("Object")
        rows_value = value.get("Rows") if isinstance(value, dict) else None
        if not isinstance(rows_value, list):
            raise ProviderResponseError("GENESIS returned invalid table rows")
        if len(rows_value) > row_limit or len(rows_value) * len(measures) > 250:
            raise ProviderResponseError("GENESIS returned a result above the requested budget")
        rows = tuple(self._parse_row(row, len(measures)) for row in rows_value)
        return DatasetResult(
            provider_id=provider_id,
            schema_version=schema_version,
            measures=measures,
            rows=rows,
        )

    @staticmethod
    def _parse_dimension(value: Any) -> DatasetDimension:
        if not isinstance(value, dict):
            raise ProviderResponseError("GENESIS returned an invalid dimension")
        code = value.get("Code")
        label = value.get("Content")
        members_value = value.get("Values")
        if (
            not isinstance(code, str)
            or not isinstance(label, str)
            or not isinstance(members_value, list)
        ):
            raise ProviderResponseError("GENESIS dimension omitted required fields")
        members: list[DimensionMember] = []
        for member_value in members_value:
            if not isinstance(member_value, dict):
                raise ProviderResponseError("GENESIS returned an invalid dimension member")
            member_code = member_value.get("Code")
            member_label = member_value.get("Content")
            if not isinstance(member_code, str) or not isinstance(member_label, str):
                raise ProviderResponseError("GENESIS dimension member omitted required fields")
            members.append(DimensionMember(member_id=member_code, label=member_label))
        return DatasetDimension(dimension_id=code, label=label, members=tuple(members))

    @classmethod
    def _parse_row(cls, value: Any, measure_count: int) -> DatasetRow:
        if not isinstance(value, dict):
            raise ProviderResponseError("GENESIS returned an invalid result row")
        dimensions = value.get("Dimensions")
        cells = value.get("Values")
        if (
            not isinstance(dimensions, dict)
            or not all(
                isinstance(key, str) and isinstance(item, str) for key, item in dimensions.items()
            )
            or not isinstance(cells, list)
            or not all(isinstance(cell, str) for cell in cells)
            or len(cells) != measure_count
        ):
            raise ProviderResponseError("GENESIS result row omitted required values")
        return DatasetRow(
            dimensions=dimensions,
            cells=tuple(cls._parse_numeric_cell(cell) for cell in cells),
        )

    @staticmethod
    def _parse_numeric_cell(source_text: str) -> NumericCell:
        stripped = source_text.strip()
        if stripped in {"X", "x"}:
            return NumericCell(source_text=source_text, value=None, status="suppressed")
        if stripped in {"", "-", ".", "..", "...", "/"}:
            return NumericCell(source_text=source_text, value=None, status="missing")
        normalized = stripped.replace("\u00a0", "").replace(" ", "").replace(".", "")
        normalized = normalized.replace(",", ".")
        try:
            value = Decimal(normalized)
        except InvalidOperation as error:
            raise ProviderResponseError("GENESIS returned an invalid numeric value") from error
        return NumericCell(source_text=source_text, value=value, status="value")

    async def _post(self, operation: str, *, data: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self._http.post(
                f"{BASE_URL}/{operation}",
                headers={"username": self._token},
                data=data,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, SourceRequestError, ValueError) as error:
            raise ProviderResponseError("GENESIS request failed") from error
        if not isinstance(payload, dict):
            raise ProviderResponseError("GENESIS returned an invalid response")
        status = payload.get("Status")
        if not isinstance(status, dict) or str(status.get("Code")) != "0":
            raise ProviderResponseError("GENESIS reported an application-level failure")
        return payload
