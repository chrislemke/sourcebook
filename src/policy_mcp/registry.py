"""Strict, route-isolated loading for the versioned source registry."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

NonEmptyString = Annotated[str, Field(min_length=1)]
NonEmptyStrings = Annotated[tuple[NonEmptyString, ...], Field(min_length=1)]


class RouteState(StrEnum):
    """Operator-visible state for one independently gated source route."""

    HEALTHY = "healthy"
    DISABLED = "disabled"
    WARMING = "warming"
    NOT_CONFIGURED = "not_configured"
    SCHEMA_CHANGED = "schema_changed"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"


class RegistryPolicy(BaseModel):
    """Global limits applied before a source is selected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    no_fee_sources_only: Literal[True]
    public_read_only: Literal[True]
    default_search_limit: Annotated[int, Field(ge=1, le=10)]
    interactive_max_provider_requests: Annotated[int, Field(ge=1)]


class LicenceMetadata(BaseModel):
    """Licence declaration for records returned by a source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmptyString
    url: NonEmptyString


class PaginationMetadata(BaseModel):
    """The source-specific pagination strategy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: NonEmptyString
    stable: bool


class RefreshPolicy(BaseModel):
    """Refresh cadence and threshold used by source health checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cadence: NonEmptyString
    freshness_threshold: NonEmptyString


class RouteDefinition(BaseModel):
    """One model-facing path whose health is independent of sibling routes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: RouteState
    allowed_operations: NonEmptyStrings
    enable_after: tuple[NonEmptyString, ...]


class SourceDefinition(BaseModel):
    """Required operational metadata for one upstream source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter: NonEmptyString
    transport: NonEmptyString
    allowed_hosts: NonEmptyStrings
    credential_transport: Literal[
        "none",
        "os_keyring",
        "environment",
        "os_keyring_or_environment",
    ]
    fixture_hashes: dict[NonEmptyString, NonEmptyString]
    licence: LicenceMetadata
    attribution: NonEmptyString
    date_bases: NonEmptyStrings
    pagination: PaginationMetadata
    refresh_policy: RefreshPolicy
    supported_languages: NonEmptyStrings
    language_fallback: NonEmptyString
    coverage_limits: NonEmptyString
    parser_version: NonEmptyString
    routes: dict[NonEmptyString, RouteDefinition]


class RegistryIssue(BaseModel):
    """A validation failure scoped to one source or route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: NonEmptyString
    route_id: str | None
    code: Literal["invalid_source", "invalid_route"]
    detail: NonEmptyString


class RouteRegistration(BaseModel):
    """A route lookup result, including failed-closed registrations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: NonEmptyString
    route_id: NonEmptyString
    state: RouteState
    definition: RouteDefinition | None


class SourceRegistry(BaseModel):
    """A validated registry with independently addressable route states."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_version: Literal[1]
    policy: RegistryPolicy
    sources: dict[NonEmptyString, SourceDefinition]
    issues: tuple[RegistryIssue, ...]
    registrations: dict[str, RouteRegistration]

    def route(self, source_id: str, route_id: str) -> RouteRegistration:
        """Return one route registration by source and local route identifier."""
        return self.registrations[f"{source_id}:{route_id}"]


def _mapping(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be a mapping with string keys")
    return value


def _validation_detail(error: ValidationError) -> str:
    problem = error.errors(include_url=False)[0]
    location = ".".join(str(part) for part in problem["loc"])
    return f"{location}: {problem['msg']}"


def load_registry(path: Path) -> SourceRegistry:
    """Load a strict v1 registry while failing invalid routes closed in isolation."""
    raw = _mapping(yaml.safe_load(path.read_text()), name="registry")
    if raw.get("registry_version") != 1:
        raise ValueError("registry_version must be 1")
    if set(raw) != {"registry_version", "policy", "sources"}:
        raise ValueError("registry contains unsupported or missing top-level fields")

    policy = RegistryPolicy.model_validate(raw["policy"])
    raw_sources = _mapping(raw["sources"], name="sources")
    sources: dict[str, SourceDefinition] = {}
    registrations: dict[str, RouteRegistration] = {}
    issues: list[RegistryIssue] = []

    for source_id, source_value in raw_sources.items():
        source_raw = _mapping(source_value, name=f"source {source_id}")
        raw_routes = _mapping(source_raw.get("routes"), name=f"source {source_id} routes")
        metadata = {**source_raw, "routes": {}}
        try:
            source = SourceDefinition.model_validate(metadata)
        except ValidationError as error:
            issues.append(
                RegistryIssue(
                    source_id=source_id,
                    route_id=None,
                    code="invalid_source",
                    detail=_validation_detail(error),
                )
            )
            continue

        routes: dict[str, RouteDefinition] = {}
        for route_id, route_value in raw_routes.items():
            key = f"{source_id}:{route_id}"
            try:
                route = RouteDefinition.model_validate(route_value)
            except ValidationError as error:
                issues.append(
                    RegistryIssue(
                        source_id=source_id,
                        route_id=route_id,
                        code="invalid_route",
                        detail=_validation_detail(error),
                    )
                )
                registrations[key] = RouteRegistration(
                    source_id=source_id,
                    route_id=route_id,
                    state=RouteState.SCHEMA_CHANGED,
                    definition=None,
                )
                continue
            routes[route_id] = route
            registrations[key] = RouteRegistration(
                source_id=source_id,
                route_id=route_id,
                state=route.state,
                definition=route,
            )
        sources[source_id] = source.model_copy(update={"routes": routes})

    return SourceRegistry(
        registry_version=1,
        policy=policy,
        sources=sources,
        issues=tuple(issues),
        registrations=registrations,
    )
