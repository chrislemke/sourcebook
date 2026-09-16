"""Frozen actor catalog and MCP tool registration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field, model_validator

from policy_mcp.adapters.actors import ActorProviderError, LiveActorSources
from policy_mcp.contracts import tool_description
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
    ResearchError,
    ResearchStatus,
    ResearchWarning,
    ResponseBase,
    StrictModel,
    fit_response,
)


class ActorScope(StrEnum):
    DE = "DE"
    EU = "EU"
    BOTH = "BOTH"


ActorKind = Literal["person", "institution", "interest_representative"]
ActorView = Literal["overview", "roles", "relationships", "disclosures", "evidence"]
ObservationState = Literal["present", "observed_absent", "reappeared"]
RelationBasis = Literal["explicit_provider_link", "candidate_text_match"]


class _Role(StrictModel):
    predicate: str
    label: str
    organisation_id: str
    organisation_name: str
    valid_from: str | None = None
    valid_to: str | None = None
    evidence_provider_id: str


class _Relationship(StrictModel):
    predicate: str
    object_provider_id: str | None = None
    object_label: str
    basis: RelationBasis
    valid_from: str | None = None
    valid_to: str | None = None
    evidence_provider_id: str


class _Disclosure(StrictModel):
    section_id: str
    heading: str
    wording: str
    spending_range: str | None = None
    clients: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    evidence_provider_id: str


class _Actor(StrictModel):
    key: str
    kind: ActorKind
    scope: Jurisdiction
    source: str
    provider_id: str
    display_name: str
    alternative_names: list[str] = Field(default_factory=list)
    description: str
    official_url: str
    source_modified_at: str
    observation_state: ObservationState
    historical_supported: bool
    roles: list[_Role] = Field(default_factory=list)
    relationships: list[_Relationship] = Field(default_factory=list)
    disclosures: list[_Disclosure] = Field(default_factory=list)


class _Fixture(StrictModel):
    retrieved_at: str
    indexed_at: str
    actors: list[_Actor]


class ActorSearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=300)
    scope: ActorScope
    kind: ActorKind
    as_of: str | None = Field(default=None, max_length=40)
    updated_since: str | None = Field(default=None, max_length=40)
    source: str | None = Field(default=None, min_length=1, max_length=50)
    language: Literal["de", "en"] = "de"
    limit: int = Field(default=5, ge=1, le=10)
    cursor: str | None = Field(default=None, min_length=12, max_length=200)


class ActorGetInput(StrictModel):
    reference: str = Field(min_length=12, max_length=200)
    view: ActorView = "overview"
    as_of: str | None = Field(default=None, max_length=40)
    section_id: str | None = Field(default=None, min_length=1, max_length=100)
    query: str | None = Field(default=None, min_length=1, max_length=300)
    limit: int = Field(default=5, ge=1, le=10)
    cursor: str | None = Field(default=None, min_length=12, max_length=200)


class ActorInterestsInput(StrictModel):
    scope: ActorScope
    query: str | None = Field(default=None, min_length=1, max_length=300)
    procedure_reference: str | None = Field(default=None, min_length=12, max_length=200)
    actor_reference: str | None = Field(default=None, min_length=12, max_length=200)
    updated_since: str | None = Field(default=None, max_length=40)
    limit: int = Field(default=5, ge=1, le=10)
    cursor: str | None = Field(default=None, min_length=12, max_length=200)

    @model_validator(mode="after")
    def require_selector(self) -> ActorInterestsInput:
        if not any((self.query, self.procedure_reference, self.actor_reference)):
            raise ValueError("Provide a topic query, procedure reference, or actor reference")
        return self


class ActorCapabilitiesInput(StrictModel):
    scope: ActorScope | None = None
    source: str | None = Field(default=None, min_length=1, max_length=50)


class ActorCard(StrictModel):
    reference: str
    kind: ActorKind
    scope: Jurisdiction
    source: str
    provider_id: str
    display_name: str
    alternative_names: list[str]
    description: str
    official_url: str
    observation_state: ObservationState
    provenance: Provenance


class PublishedRole(StrictModel):
    predicate: str
    label: str
    organisation_id: str
    organisation_name: str
    valid_from: str | None = None
    valid_to: str | None = None
    provenance: Provenance


class PublishedRelationship(StrictModel):
    predicate: str
    object_provider_id: str | None = None
    object_label: str
    basis: RelationBasis
    valid_from: str | None = None
    valid_to: str | None = None
    provenance: Provenance


class PublishedDisclosure(StrictModel):
    section_id: str
    heading: str
    wording: str
    spending_range: str | None = None
    clients: list[str]
    projects: list[str]
    provenance: Provenance


class ActorDetail(StrictModel):
    reference: str
    view: ActorView
    kind: ActorKind
    scope: Jurisdiction
    source: str
    provider_id: str
    display_name: str
    alternative_names: list[str] = Field(default_factory=list)
    description: str | None = None
    official_url: str
    observation_state: ObservationState
    roles: list[PublishedRole] = Field(default_factory=list)
    relationships: list[PublishedRelationship] = Field(default_factory=list)
    disclosures: list[PublishedDisclosure] = Field(default_factory=list)
    evidence: list[Provenance] = Field(default_factory=list)


class InterestMatch(StrictModel):
    actor_reference: str
    actor_provider_id: str
    actor_name: str
    scope: Jurisdiction
    source: str
    predicate: str
    basis: Literal["disclosure_text", "explicit_provider_link", "candidate_text_match"]
    wording: str
    spending_range: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    provenance: Provenance


class ActorSourceCapability(StrictModel):
    source: str
    scope: Jurisdiction
    state: Literal["ready", "not_configured"]
    operations: list[str]
    limitations: list[str] = Field(default_factory=list)


class ActorSearchResponse(ResponseBase):
    items: list[ActorCard] = Field(default_factory=list)
    continuation: Continuation | None = None


class ActorGetResponse(ResponseBase):
    actor: ActorDetail | None = None
    continuation: Continuation | None = None


class ActorInterestsResponse(ResponseBase):
    matches: list[InterestMatch] = Field(default_factory=list)
    continuation: Continuation | None = None


class ActorCapabilitiesResponse(ResponseBase):
    sources: list[ActorSourceCapability] = Field(default_factory=list)


class FrozenActorCatalog:
    """Read-only actor catalog built from checked-in acceptance fixtures."""

    def __init__(self, fixture: _Fixture) -> None:
        self.retrieved_at = fixture.retrieved_at
        self.indexed_at = fixture.indexed_at
        self._actors = {actor.key: actor for actor in fixture.actors}

    @classmethod
    def empty(cls) -> FrozenActorCatalog:
        """Create an unconfigured production catalog without sample actors."""
        return cls(_Fixture(retrieved_at="", indexed_at="", actors=[]))

    @classmethod
    def from_json(cls, path: Path) -> FrozenActorCatalog:
        return cls(_Fixture.model_validate_json(path.read_text()))

    def actor(self, key: str) -> _Actor | None:
        return self._actors.get(key)

    def search(self, request: ActorSearchInput) -> list[_Actor]:
        terms = request.query.casefold().split()
        matches = []
        for actor in self._actors.values():
            if request.kind != actor.kind:
                continue
            if request.scope != ActorScope.BOTH and actor.scope.value != request.scope.value:
                continue
            if request.source is not None and actor.source != request.source:
                continue
            if (
                request.updated_since is not None
                and actor.source_modified_at < request.updated_since
            ):
                continue
            searchable = " ".join(
                [actor.display_name, *actor.alternative_names, actor.description]
            ).casefold()
            if all(term in searchable for term in terms):
                matches.append(actor)
                if len(matches) > MAX_SNAPSHOT_ITEMS:
                    break
        return matches

    def actors(self) -> Iterable[_Actor]:
        return self._actors.values()

    async def prepare_search(self, request: ActorSearchInput) -> list[ResearchWarning]:
        """Frozen catalogs already contain every actor they can search."""
        del request
        return []

    async def prepare_interests(self, request: ActorInterestsInput) -> list[ResearchWarning]:
        """Frozen catalogs already contain every disclosure they can search."""
        del request
        return []

    @property
    def ready_sources(self) -> set[str]:
        return {actor.source for actor in self._actors.values()}

    @property
    def open_world(self) -> bool:
        return False

    def coverage_limitations(self, actor: _Actor) -> list[str]:
        del actor
        return ["The frozen acceptance catalog is not a complete register."]

    def capabilities(self) -> list[ActorSourceCapability]:
        return [
            ActorSourceCapability(
                source="ep_acceptance",
                scope=Jurisdiction.EU,
                state=("ready" if "ep_acceptance" in self.ready_sources else "not_configured"),
                operations=(
                    ["search", "get_roles"] if "ep_acceptance" in self.ready_sources else []
                ),
                limitations=["Frozen acceptance data only."],
            ),
            ActorSourceCapability(
                source="whoiswho_acceptance",
                scope=Jurisdiction.EU,
                state=(
                    "ready" if "whoiswho_acceptance" in self.ready_sources else "not_configured"
                ),
                operations=(
                    ["search", "get_roles", "get_relationships"]
                    if "whoiswho_acceptance" in self.ready_sources
                    else []
                ),
                limitations=["Frozen acceptance data only."],
            ),
            ActorSourceCapability(
                source="register_acceptance",
                scope=Jurisdiction.DE,
                state=(
                    "ready" if "register_acceptance" in self.ready_sources else "not_configured"
                ),
                operations=(
                    ["search", "get_disclosures", "interests"]
                    if "register_acceptance" in self.ready_sources
                    else []
                ),
                limitations=["Frozen acceptance data only."],
            ),
            ActorSourceCapability(
                source="lobbyregister",
                scope=Jurisdiction.DE,
                state="not_configured",
                operations=[],
                limitations=["The official v2 schema contract gate has not passed."],
            ),
            ActorSourceCapability(
                source="eu_transparency",
                scope=Jurisdiction.EU,
                state="not_configured",
                operations=[],
                limitations=["No validated current distribution is configured."],
            ),
        ]


class LiveActorCatalog(FrozenActorCatalog):
    """In-memory catalog populated on demand from public official sources."""

    def __init__(self, sources: LiveActorSources | None = None) -> None:
        super().__init__(_Fixture(retrieved_at="", indexed_at="", actors=[]))
        self._sources = sources or LiveActorSources()
        self._prepared_keys: list[str] = []

    @property
    def ready_sources(self) -> set[str]:
        return set(self._sources.ready_sources)

    @property
    def open_world(self) -> bool:
        return True

    def coverage_limitations(self, actor: _Actor) -> list[str]:
        limitations = {
            "ep": ["European Parliament member and body data only."],
            "eu_whoiswho": ["Current published EU directory identities only."],
            "lobbyregister": ["Published German federal lobbying disclosures only."],
            "eu_transparency": ["Self-reported EU Transparency Register snapshot data."],
        }
        return limitations.get(actor.source, ["Coverage follows the official source."])

    async def prepare_search(self, request: ActorSearchInput) -> list[ResearchWarning]:
        result = await self._sources.search(
            request.query,
            scope=request.scope.value,
            kind=request.kind,
            source=request.source,
            language=request.language,
            limit=request.limit,
        )
        if not result.successful_sources:
            raise ActorProviderError("No selected official actor source was reachable")
        self._prepared_keys = []
        for record in result.records:
            actor = _Actor.model_validate(record.model_dump(mode="python"))
            self._actors[actor.key] = actor
            self._prepared_keys.append(actor.key)
        self.retrieved_at = result.retrieved_at
        self.indexed_at = result.retrieved_at
        return [
            ResearchWarning(
                code="source_unavailable",
                message=f"{source} was unavailable; other configured sources were still searched.",
            )
            for source in sorted(result.failures)
        ]

    def search(self, request: ActorSearchInput) -> list[_Actor]:
        """Return the bounded matches selected by the live providers."""
        return [
            actor
            for key in self._prepared_keys
            if (actor := self._actors.get(key)) is not None
            and (request.updated_since is None or actor.source_modified_at >= request.updated_since)
        ]

    async def prepare_interests(self, request: ActorInterestsInput) -> list[ResearchWarning]:
        if request.query is None:
            return []
        return await self.prepare_search(
            ActorSearchInput(
                query=request.query,
                scope=request.scope,
                kind="interest_representative",
                updated_since=request.updated_since,
                limit=request.limit,
            )
        )

    def capabilities(self) -> list[ActorSourceCapability]:
        return [
            ActorSourceCapability(
                source="ep",
                scope=Jurisdiction.EU,
                state="ready",
                operations=["search", "get_roles"],
                limitations=["Official European Parliament member and body data."],
            ),
            ActorSourceCapability(
                source="eu_whoiswho",
                scope=Jurisdiction.EU,
                state="ready",
                operations=["search"],
                limitations=["Current official EU directory identities."],
            ),
            ActorSourceCapability(
                source="lobbyregister",
                scope=Jurisdiction.DE,
                state="ready",
                operations=["search", "get_disclosures", "interests"],
                limitations=["Uses the public Bundestag search and, when available, its API."],
            ),
            ActorSourceCapability(
                source="eu_transparency",
                scope=Jurisdiction.EU,
                state="ready",
                operations=["search", "get_disclosures", "interests"],
                limitations=["The daily public snapshot is cached locally for 24 hours."],
            ),
        ]


def _query_hash(value: StrictModel) -> str:
    payload = value.model_dump(mode="json", exclude={"cursor", "limit"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _provenance(catalog: FrozenActorCatalog, actor: _Actor, provider_id: str) -> Provenance:
    return Provenance(
        source=actor.source,
        provider_id=provider_id,
        official_url=actor.official_url,
        retrieved_at=catalog.retrieved_at,
        source_modified_at=actor.source_modified_at,
    )


def _coverage(catalog: FrozenActorCatalog, actor: _Actor, *, historical: bool = False) -> Coverage:
    limitations = catalog.coverage_limitations(actor)
    if historical:
        limitations.append("This source does not support the requested historical state.")
    return Coverage(
        source=actor.source,
        jurisdiction=actor.scope,
        complete=False,
        limitations=limitations,
    )


def _freshness(catalog: FrozenActorCatalog, actor: _Actor) -> Freshness:
    return Freshness(
        source=actor.source,
        retrieved_at=catalog.retrieved_at,
        indexed_at=catalog.indexed_at,
        source_modified_at=actor.source_modified_at,
    )


def _error(code: Any, message: str, *, retryable: bool = False) -> ResearchError:
    return ResearchError(code=code, message=message, retryable=retryable)


def _warning_for(actor: _Actor) -> list[ResearchWarning]:
    if actor.observation_state == "observed_absent":
        return [
            ResearchWarning(
                code="observed_absent",
                message=(
                    "The entry disappeared from an observed snapshot. This does not establish "
                    "deregistration."
                ),
            )
        ]
    if actor.observation_state == "reappeared":
        return [
            ResearchWarning(
                code="observed_reappearance",
                message="The entry reappeared in a later observed snapshot.",
            )
        ]
    return []


def _card(
    catalog: FrozenActorCatalog,
    references: ReferenceStore,
    actor: _Actor,
) -> ActorCard:
    provenance = _provenance(catalog, actor, actor.provider_id)
    return ActorCard(
        reference=references.reference_for(
            principal=references.principal,
            kind=actor.kind,
            key=actor.key,
        ),
        kind=actor.kind,
        scope=actor.scope,
        source=actor.source,
        provider_id=actor.provider_id,
        display_name=actor.display_name,
        alternative_names=actor.alternative_names,
        description=actor.description,
        official_url=actor.official_url,
        observation_state=actor.observation_state,
        provenance=provenance,
    )


def _continuation(page: Any) -> Continuation | None:
    if page.cursor is None or page.expires_at is None:
        return None
    return Continuation(cursor=page.cursor, expires_at=page.expires_at.isoformat())


def _strict_tool_inputs(server: MCPServer[Any], names: list[str]) -> None:
    manager = server._tool_manager
    for name in names:
        tool = manager.get_tool(name)
        if tool is None:  # pragma: no cover
            raise RuntimeError(f"Tool registration failed: {name}")
        tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
        tool.fn_metadata.arg_model.model_rebuild(force=True)
        tool.parameters = tool.fn_metadata.arg_model.model_json_schema(by_alias=True)


def register_actor_tools(
    server: MCPServer[Any],
    catalog: FrozenActorCatalog,
    reference_store: ReferenceStore,
) -> None:
    """Register the four stable actor tools."""
    annotations = ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=catalog.open_world,
    )

    @server.tool(
        name="actor_search",
        description=tool_description("actor_search"),
        annotations=annotations,
        structured_output=True,
    )
    async def actor_search(
        query: Annotated[str, Field(min_length=1, max_length=300)],
        scope: ActorScope,
        kind: ActorKind,
        as_of: Annotated[str | None, Field(max_length=40)] = None,
        updated_since: Annotated[str | None, Field(max_length=40)] = None,
        source: Annotated[str | None, Field(min_length=1, max_length=50)] = None,
        language: Literal["de", "en"] = "de",
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
        cursor: Annotated[str | None, Field(min_length=12, max_length=200)] = None,
    ) -> ActorSearchResponse:
        request = ActorSearchInput(
            query=query,
            scope=scope,
            kind=kind,
            as_of=as_of,
            updated_since=updated_since,
            source=source,
            language=language,
            limit=limit,
            cursor=cursor,
        )
        if not catalog.ready_sources or (
            request.source is not None and request.source not in catalog.ready_sources
        ):
            return ActorSearchResponse(
                status=ResearchStatus.ERROR,
                error=_error("not_configured", "No matching actor source has passed its gate."),
            )
        if request.as_of is not None:
            return ActorSearchResponse(
                status=ResearchStatus.ERROR,
                error=_error(
                    "unsupported",
                    "The frozen actor sources do not support historical as-of search.",
                ),
            )
        try:
            source_warnings = await catalog.prepare_search(request)
        except ActorProviderError:
            return ActorSearchResponse(
                status=ResearchStatus.ERROR,
                error=_error(
                    "temporarily_unavailable",
                    "The selected official actor sources could not be reached.",
                    retryable=True,
                ),
            )
        digest = _query_hash(request)
        try:
            if request.cursor is None:
                matches = catalog.search(request)
                page = reference_store.first_page(
                    [actor.key for actor in matches],
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
            return ActorSearchResponse(
                status=ResearchStatus.ERROR,
                error=_error("forged_cursor", "The continuation does not belong to this query."),
            )
        except ExpiredCursorError:
            return ActorSearchResponse(
                status=ResearchStatus.ERROR,
                error=_error(
                    "expired_cursor",
                    "The continuation expired. Restart the search without a cursor.",
                    retryable=True,
                ),
            )
        except ValueError:
            return ActorSearchResponse(
                status=ResearchStatus.ERROR,
                error=_error("oversized", "The search matched too many bounded results."),
            )
        actors = [actor for key in page.keys if (actor := catalog.actor(key)) is not None]
        cards = [_card(catalog, reference_store, actor) for actor in actors]
        response = ActorSearchResponse(
            status=ResearchStatus.PARTIAL if source_warnings else ResearchStatus.OK,
            items=cards,
            continuation=_continuation(page),
            warnings=[
                *source_warnings,
                *(warning for actor in actors for warning in _warning_for(actor)),
            ],
            coverage=[_coverage(catalog, actor) for actor in actors],
            freshness=[_freshness(catalog, actor) for actor in actors],
            provenance=[card.provenance for card in cards],
        )
        return fit_response(response, response.items)

    @server.tool(
        name="actor_get",
        description=tool_description("actor_get"),
        annotations=annotations,
        structured_output=True,
    )
    def actor_get(
        reference: Annotated[str, Field(min_length=12, max_length=200)],
        view: ActorView = "overview",
        as_of: Annotated[str | None, Field(max_length=40)] = None,
        section_id: Annotated[str | None, Field(min_length=1, max_length=100)] = None,
        query: Annotated[str | None, Field(min_length=1, max_length=300)] = None,
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
        cursor: Annotated[str | None, Field(min_length=12, max_length=200)] = None,
    ) -> ActorGetResponse:
        request = ActorGetInput(
            reference=reference,
            view=view,
            as_of=as_of,
            section_id=section_id,
            query=query,
            limit=limit,
            cursor=cursor,
        )
        try:
            key = reference_store.resolve(
                request.reference,
                principal=reference_store.principal,
                expected_kinds=("person", "institution", "interest_representative"),
            )
        except ForgedReferenceError:
            return ActorGetResponse(
                status=ResearchStatus.ERROR,
                error=_error("forged_reference", "The actor reference is invalid."),
            )
        actor = catalog.actor(key)
        if actor is None:
            return ActorGetResponse(
                status=ResearchStatus.ERROR,
                error=_error("not_found", "The actor is no longer available."),
            )
        if request.as_of is not None and not actor.historical_supported:
            return ActorGetResponse(
                status=ResearchStatus.ERROR,
                error=_error(
                    "unsupported",
                    "This source cannot answer the requested historical as-of date.",
                ),
                coverage=[_coverage(catalog, actor, historical=True)],
                freshness=[_freshness(catalog, actor)],
            )
        view_items = _view_items(actor, request)
        page = None
        selected_indices: tuple[int, ...] | None = None
        if request.view != "overview":
            digest = _query_hash(request)
            try:
                page = (
                    reference_store.first_page(
                        [str(index) for index in range(len(view_items))],
                        principal=reference_store.principal,
                        query_hash=digest,
                        limit=request.limit,
                    )
                    if request.cursor is None
                    else reference_store.next_page(
                        request.cursor,
                        principal=reference_store.principal,
                        query_hash=digest,
                        limit=request.limit,
                    )
                )
            except ForgedCursorError:
                return ActorGetResponse(
                    status=ResearchStatus.ERROR,
                    error=_error(
                        "forged_cursor", "The continuation does not belong to this actor view."
                    ),
                )
            except ExpiredCursorError:
                return ActorGetResponse(
                    status=ResearchStatus.ERROR,
                    error=_error(
                        "expired_cursor",
                        "The continuation expired. Restart the actor view without a cursor.",
                        retryable=True,
                    ),
                )
            except ValueError:
                return ActorGetResponse(
                    status=ResearchStatus.ERROR,
                    error=_error("oversized", "The actor view has too many bounded items."),
                )
            selected_indices = tuple(int(key) for key in page.keys)
        detail = _detail_for_view(
            catalog,
            actor,
            request,
            reference_store,
            view_items=view_items,
            selected_indices=selected_indices,
        )
        response = ActorGetResponse(
            status=ResearchStatus.OK,
            actor=detail,
            continuation=_continuation(page) if page is not None else None,
            warnings=_warning_for(actor),
            coverage=[_coverage(catalog, actor)],
            freshness=[_freshness(catalog, actor)],
            provenance=detail.evidence or [_provenance(catalog, actor, actor.provider_id)],
        )
        optional_items = {
            "roles": detail.roles,
            "relationships": detail.relationships,
            "disclosures": detail.disclosures,
            "evidence": detail.evidence,
        }.get(request.view, [])
        return fit_response(response, optional_items)

    @server.tool(
        name="actor_interests",
        description=tool_description("actor_interests"),
        annotations=annotations,
        structured_output=True,
    )
    async def actor_interests(
        scope: ActorScope,
        query: Annotated[str | None, Field(min_length=1, max_length=300)] = None,
        procedure_reference: Annotated[str | None, Field(min_length=12, max_length=200)] = None,
        actor_reference: Annotated[str | None, Field(min_length=12, max_length=200)] = None,
        updated_since: Annotated[str | None, Field(max_length=40)] = None,
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
        cursor: Annotated[str | None, Field(min_length=12, max_length=200)] = None,
    ) -> ActorInterestsResponse:
        request = ActorInterestsInput(
            scope=scope,
            query=query,
            procedure_reference=procedure_reference,
            actor_reference=actor_reference,
            updated_since=updated_since,
            limit=limit,
            cursor=cursor,
        )
        try:
            source_warnings = await catalog.prepare_interests(request)
        except ActorProviderError:
            return ActorInterestsResponse(
                status=ResearchStatus.ERROR,
                error=_error(
                    "temporarily_unavailable",
                    "The selected official actor sources could not be reached.",
                    retryable=True,
                ),
            )
        try:
            actor_key = (
                reference_store.resolve(
                    request.actor_reference,
                    principal=reference_store.principal,
                    expected_kinds=("person", "institution", "interest_representative"),
                )
                if request.actor_reference is not None
                else None
            )
            procedure_key = (
                reference_store.resolve(
                    request.procedure_reference,
                    principal=reference_store.principal,
                    expected_kinds=("procedure",),
                )
                if request.procedure_reference is not None
                else None
            )
        except ForgedReferenceError:
            return ActorInterestsResponse(
                status=ResearchStatus.ERROR,
                error=_error("forged_reference", "The supplied reference is invalid."),
            )
        matches = _interest_matches(catalog, reference_store, request, actor_key, procedure_key)
        digest = _query_hash(request)
        match_keys = [f"{index}" for index in range(len(matches))]
        try:
            page = (
                reference_store.first_page(
                    match_keys,
                    principal=reference_store.principal,
                    query_hash=digest,
                    limit=request.limit,
                )
                if request.cursor is None
                else reference_store.next_page(
                    request.cursor,
                    principal=reference_store.principal,
                    query_hash=digest,
                    limit=request.limit,
                )
            )
        except ForgedCursorError:
            return ActorInterestsResponse(
                status=ResearchStatus.ERROR,
                error=_error("forged_cursor", "The continuation does not belong to this query."),
            )
        except ExpiredCursorError:
            return ActorInterestsResponse(
                status=ResearchStatus.ERROR,
                error=_error(
                    "expired_cursor",
                    "The continuation expired. Restart the search without a cursor.",
                    retryable=True,
                ),
            )
        except ValueError:
            return ActorInterestsResponse(
                status=ResearchStatus.ERROR,
                error=_error("oversized", "The interest search matched too many results."),
            )
        selected = [matches[int(key)] for key in page.keys]
        selected_actors = [
            actor
            for item in selected
            if (actor := _actor_by_provider(catalog, item.source, item.actor_provider_id))
            is not None
        ]
        response = ActorInterestsResponse(
            status=ResearchStatus.PARTIAL if source_warnings else ResearchStatus.OK,
            matches=selected,
            continuation=_continuation(page),
            warnings=[
                *source_warnings,
                *(warning for actor in selected_actors for warning in _warning_for(actor)),
            ],
            coverage=[_coverage(catalog, actor) for actor in selected_actors],
            freshness=[_freshness(catalog, actor) for actor in selected_actors],
            provenance=[item.provenance for item in selected],
        )
        return fit_response(response, response.matches)

    @server.tool(
        name="actor_capabilities",
        description=tool_description("actor_capabilities"),
        annotations=annotations,
        structured_output=True,
    )
    def actor_capabilities(
        scope: ActorScope | None = None,
        source: Annotated[str | None, Field(min_length=1, max_length=50)] = None,
    ) -> ActorCapabilitiesResponse:
        request = ActorCapabilitiesInput(scope=scope, source=source)
        sources = catalog.capabilities()
        filtered = [
            item
            for item in sources
            if (
                request.scope is None
                or request.scope == ActorScope.BOTH
                or item.scope.value == request.scope.value
            )
            and (request.source is None or item.source == request.source)
        ]
        ready_sources = {item.source for item in filtered if item.state == "ready"}
        fixture_actors = [actor for actor in catalog.actors() if actor.source in ready_sources]
        response = ActorCapabilitiesResponse(
            status=ResearchStatus.OK,
            sources=filtered,
            coverage=[_coverage(catalog, actor) for actor in fixture_actors],
            freshness=[_freshness(catalog, actor) for actor in fixture_actors],
        )
        return fit_response(response, response.sources)

    names = ["actor_search", "actor_get", "actor_interests", "actor_capabilities"]
    _strict_tool_inputs(server, names)


def _detail_for_view(
    catalog: FrozenActorCatalog,
    actor: _Actor,
    request: ActorGetInput,
    references: ReferenceStore,
    *,
    view_items: list[Any],
    selected_indices: tuple[int, ...] | None,
) -> ActorDetail:
    actor_reference = references.reference_for(
        principal=references.principal,
        kind=actor.kind,
        key=actor.key,
    )
    roles: list[PublishedRole] = []
    relationships: list[PublishedRelationship] = []
    disclosures: list[PublishedDisclosure] = []
    evidence: list[Provenance] = []
    if request.view == "roles":
        selected_roles = [view_items[index] for index in selected_indices or ()]
        roles = [
            PublishedRole(
                predicate=role.predicate,
                label=role.label,
                organisation_id=role.organisation_id,
                organisation_name=role.organisation_name,
                valid_from=role.valid_from,
                valid_to=role.valid_to,
                provenance=_provenance(catalog, actor, role.evidence_provider_id),
            )
            for role in selected_roles
        ]
        evidence = [item.provenance for item in roles]
    elif request.view == "relationships":
        selected_relationships = [view_items[index] for index in selected_indices or ()]
        relationships = [
            PublishedRelationship(
                predicate=relation.predicate,
                object_provider_id=relation.object_provider_id,
                object_label=relation.object_label,
                basis=relation.basis,
                valid_from=relation.valid_from,
                valid_to=relation.valid_to,
                provenance=_provenance(catalog, actor, relation.evidence_provider_id),
            )
            for relation in selected_relationships
        ]
        evidence = [item.provenance for item in relationships]
    elif request.view == "disclosures":
        values = [view_items[index] for index in selected_indices or ()]
        disclosures = [
            PublishedDisclosure(
                section_id=item.section_id,
                heading=item.heading,
                wording=item.wording,
                spending_range=item.spending_range,
                clients=item.clients,
                projects=item.projects,
                provenance=_provenance(catalog, actor, item.evidence_provider_id),
            )
            for item in values
        ]
        evidence = [item.provenance for item in disclosures]
    elif request.view == "evidence":
        evidence = [
            _provenance(catalog, actor, provider_id)
            for provider_id in [view_items[index] for index in selected_indices or ()]
        ]
    return ActorDetail(
        reference=actor_reference,
        view=request.view,
        kind=actor.kind,
        scope=actor.scope,
        source=actor.source,
        provider_id=actor.provider_id,
        display_name=actor.display_name,
        alternative_names=actor.alternative_names if request.view == "overview" else [],
        description=actor.description if request.view == "overview" else None,
        official_url=actor.official_url,
        observation_state=actor.observation_state,
        roles=roles,
        relationships=relationships,
        disclosures=disclosures,
        evidence=evidence,
    )


def _view_items(actor: _Actor, request: ActorGetInput) -> list[Any]:
    if request.view == "roles":
        return list(actor.roles)
    if request.view == "relationships":
        return list(actor.relationships)
    if request.view == "disclosures":
        values = actor.disclosures
        if request.section_id is not None:
            values = [item for item in values if item.section_id == request.section_id]
        if request.query is not None:
            terms = request.query.casefold().split()
            values = [
                item
                for item in values
                if all(
                    term
                    in " ".join(
                        [item.heading, item.wording, *item.clients, *item.projects]
                    ).casefold()
                    for term in terms
                )
            ]
        return list(values)
    if request.view == "evidence":
        return [
            actor.provider_id,
            *[item.evidence_provider_id for item in actor.roles],
            *[item.evidence_provider_id for item in actor.relationships],
            *[item.evidence_provider_id for item in actor.disclosures],
        ]
    return []


def _interest_matches(
    catalog: FrozenActorCatalog,
    references: ReferenceStore,
    request: ActorInterestsInput,
    actor_key: str | None,
    procedure_key: str | None,
) -> list[InterestMatch]:
    terms = request.query.casefold().split() if request.query is not None else []
    matches: list[InterestMatch] = []
    for actor in catalog.actors():
        if actor.kind != "interest_representative":
            continue
        if request.scope != ActorScope.BOTH and actor.scope.value != request.scope.value:
            continue
        if actor_key is not None and actor.key != actor_key:
            continue
        if request.updated_since is not None and actor.source_modified_at < request.updated_since:
            continue
        actor_reference = references.reference_for(
            principal=references.principal,
            kind=actor.kind,
            key=actor.key,
        )
        for disclosure in actor.disclosures:
            searchable = " ".join(
                [disclosure.heading, disclosure.wording, *disclosure.clients, *disclosure.projects]
            ).casefold()
            if terms and not all(term in searchable for term in terms):
                continue
            if procedure_key is not None:
                continue
            matches.append(
                InterestMatch(
                    actor_reference=actor_reference,
                    actor_provider_id=actor.provider_id,
                    actor_name=actor.display_name,
                    scope=actor.scope,
                    source=actor.source,
                    predicate="declared_interest",
                    basis="disclosure_text",
                    wording=disclosure.wording,
                    spending_range=disclosure.spending_range,
                    provenance=_provenance(catalog, actor, disclosure.evidence_provider_id),
                )
            )
            if len(matches) > MAX_SNAPSHOT_ITEMS:
                return matches
        for relation in actor.relationships:
            searchable = f"{relation.predicate} {relation.object_label}".casefold()
            if terms and not all(term in searchable for term in terms):
                continue
            if procedure_key is not None and relation.object_provider_id != procedure_key:
                continue
            matches.append(
                InterestMatch(
                    actor_reference=actor_reference,
                    actor_provider_id=actor.provider_id,
                    actor_name=actor.display_name,
                    scope=actor.scope,
                    source=actor.source,
                    predicate=relation.predicate,
                    basis=relation.basis,
                    wording=relation.object_label,
                    valid_from=relation.valid_from,
                    valid_to=relation.valid_to,
                    provenance=_provenance(catalog, actor, relation.evidence_provider_id),
                )
            )
            if len(matches) > MAX_SNAPSHOT_ITEMS:
                return matches
    return matches


def _actor_by_provider(
    catalog: FrozenActorCatalog,
    source: str,
    provider_id: str,
) -> _Actor | None:
    return next(
        (
            actor
            for actor in catalog.actors()
            if actor.source == source and actor.provider_id == provider_id
        ),
        None,
    )
