"""Zero-configuration readers for official public actor sources."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import time
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urljoin, urlsplit
from xml.etree.ElementTree import Element

import httpx
from defusedxml import ElementTree
from pydantic import BaseModel, ConfigDict, Field

from policy_mcp.research_contracts import Jurisdiction
from policy_mcp.source_http import BoundedHttpClient, Resolver, SourceRequestError, resolve_host
from policy_mcp.storage import data_directory

ActorKind = Literal["person", "institution", "interest_representative"]
NonEmptyString = Annotated[str, Field(min_length=1)]

EP_API = "https://data.europarl.europa.eu/api/v2"
LOBBYREGISTER_SEARCH = "https://www.lobbyregister.bundestag.de/suche"
WHOISWHO_SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
TRANSPARENCY_XML = "https://transparency-register.europa.eu/odplastorganisationxml_en"
TRANSPARENCY_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
MAX_PROVIDER_CALLS = 6
LOGGER = logging.getLogger(__name__)


class ActorProviderError(RuntimeError):
    """A redacted live-source failure safe to expose to the actor catalog."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRole(_FrozenModel):
    predicate: str
    label: str
    organisation_id: str
    organisation_name: str
    valid_from: str | None = None
    valid_to: str | None = None
    evidence_provider_id: str


class SourceRelationship(_FrozenModel):
    predicate: str
    object_provider_id: str | None = None
    object_label: str
    basis: Literal["explicit_provider_link", "candidate_text_match"]
    valid_from: str | None = None
    valid_to: str | None = None
    evidence_provider_id: str


class SourceDisclosure(_FrozenModel):
    section_id: str
    heading: str
    wording: str
    spending_range: str | None = None
    clients: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    evidence_provider_id: str


class ActorSourceRecord(_FrozenModel):
    key: str
    kind: ActorKind
    scope: Jurisdiction
    source: str
    provider_id: str
    display_name: str
    alternative_names: tuple[str, ...] = ()
    description: str
    official_url: str
    source_modified_at: str
    observation_state: Literal["present"] = "present"
    historical_supported: bool
    roles: tuple[SourceRole, ...] = ()
    relationships: tuple[SourceRelationship, ...] = ()
    disclosures: tuple[SourceDisclosure, ...] = ()


class ActorSourceSearchResult(_FrozenModel):
    records: tuple[ActorSourceRecord, ...]
    successful_sources: tuple[str, ...]
    failures: dict[str, str]
    retrieved_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _terms_match(query: str, *values: str) -> bool:
    searchable = " ".join(values).casefold()
    return all(term in searchable for term in query.casefold().split())


def _xml_text(element: Element, name: str) -> str | None:
    child = element.find(f".//{{*}}{name}")
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _direct_xml_text(element: Element, name: str) -> str | None:
    child = element.find(f"./{{*}}{name}")
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _resource_tail(element: Element | None) -> str | None:
    if element is None:
        return None
    value = element.attrib.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource")
    if value is None:
        return None
    return value.rstrip("/").rsplit("/", 1)[-1]


class EuropeanParliamentActors:
    """Read MEP identities and dated memberships from the public EP API."""

    source = "ep"

    def __init__(self, client: httpx.AsyncClient, *, resolver: Resolver = resolve_host) -> None:
        self._http = BoundedHttpClient(
            client,
            allowed_hosts={"data.europarl.europa.eu"},
            resolver=resolver,
            max_response_bytes=3_000_000,
        )

    async def search(
        self,
        query: str,
        *,
        kind: ActorKind,
        language: Literal["de", "en"],
        limit: int,
    ) -> tuple[ActorSourceRecord, ...]:
        del language
        if kind not in {"person", "institution"}:
            return ()
        endpoint = "meps" if kind == "person" else "corporate-bodies"
        element_name = "Person" if kind == "person" else "Organization"
        matches: list[tuple[str, str]] = []
        calls = 0
        page_size = 5_000
        for offset in range(0, 10_000, page_size):
            if calls >= MAX_PROVIDER_CALLS or len(matches) >= limit:
                break
            response = await self._http.get(
                f"{EP_API}/{endpoint}",
                params={"offset": offset, "limit": page_size},
                headers={"Accept": "application/rdf+xml"},
            )
            calls += 1
            if response.status_code != 200:
                raise ActorProviderError("European Parliament search failed")
            page = self._listing(response.content, element_name=element_name)
            for provider_id, label in page:
                if _terms_match(query, label):
                    matches.append((provider_id, label))
                    if len(matches) >= limit:
                        break
            if matches or len(page) < page_size:
                break

        records: list[ActorSourceRecord] = []
        for provider_id, label in matches[:limit]:
            if calls < MAX_PROVIDER_CALLS:
                detail = await self._http.get(
                    f"{EP_API}/{endpoint}/{provider_id}",
                    headers={"Accept": "application/rdf+xml"},
                )
                calls += 1
                if detail.status_code == 200:
                    records.append(self._detail_record(detail.content, kind=kind))
                    continue
            records.append(self._summary_record(provider_id, label, kind=kind))
        return tuple(records)

    @staticmethod
    def _listing(content: bytes, *, element_name: str) -> list[tuple[str, str]]:
        if content.lstrip().startswith(b"{"):
            try:
                payload = json.loads(content)
            except ValueError as error:
                raise ActorProviderError("European Parliament returned invalid JSON-LD") from error
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                raise ActorProviderError("European Parliament listing omitted its data")
            expected_type = element_name.casefold()
            return [
                (str(item["identifier"]), str(item["label"]))
                for item in data
                if isinstance(item, dict)
                and str(item.get("type", "")).casefold() == expected_type
                and isinstance(item.get("identifier"), str | int)
                and isinstance(item.get("label"), str)
            ]
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as error:
            raise ActorProviderError("European Parliament returned invalid XML") from error
        page: list[tuple[str, str]] = []
        for item in root.findall(f".//{{*}}{element_name}"):
            provider_id = _xml_text(item, "identifier")
            label = _xml_text(item, "label")
            if provider_id is not None and label is not None:
                page.append((provider_id, label))
        return page

    def _summary_record(
        self, provider_id: str, label: str, *, kind: Literal["person", "institution"]
    ) -> ActorSourceRecord:
        path = "person" if kind == "person" else "org"
        return ActorSourceRecord(
            key=f"ep:{kind}:{provider_id}",
            kind=kind,
            scope=Jurisdiction.EU,
            source=self.source,
            provider_id=provider_id,
            display_name=label,
            description=(
                "Published European Parliament member identity."
                if kind == "person"
                else "Published European Parliament body."
            ),
            official_url=f"https://data.europarl.europa.eu/{path}/{provider_id}",
            source_modified_at=_now(),
            historical_supported=True,
        )

    def _detail_record(
        self, content: bytes, *, kind: Literal["person", "institution"]
    ) -> ActorSourceRecord:
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as error:
            raise ActorProviderError("European Parliament returned invalid detail XML") from error
        item_name = "Person" if kind == "person" else "Organization"
        item = root.find(f".//{{*}}{item_name}")
        if item is None:
            raise ActorProviderError("European Parliament detail omitted its actor")
        provider_id = _direct_xml_text(item, "identifier")
        label = _direct_xml_text(item, "label")
        if provider_id is None or label is None:
            raise ActorProviderError("European Parliament detail omitted its identity")
        roles: list[SourceRole] = []
        for membership in item.findall(".//{*}Membership"):
            membership_id = (
                membership.attrib.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about", "")
                .rstrip("/")
                .rsplit("/", 1)[-1]
            )
            organisation_id = _resource_tail(membership.find("./{*}organization"))
            role_id = _resource_tail(membership.find("./{*}role"))
            if not membership_id or organisation_id is None or role_id is None:
                continue
            roles.append(
                SourceRole(
                    predicate="member_of",
                    label=role_id.replace("_", " ").title(),
                    organisation_id=organisation_id,
                    organisation_name=(
                        "European Parliament, parliamentary term "
                        + organisation_id.removeprefix("ep-")
                        if organisation_id.startswith("ep-")
                        else f"European Parliament organisation {organisation_id}"
                    ),
                    valid_from=_xml_text(membership, "startDate"),
                    valid_to=_xml_text(membership, "endDate"),
                    evidence_provider_id=membership_id,
                )
            )
        summary = self._summary_record(provider_id, label, kind=kind)
        return summary.model_copy(update={"roles": tuple(roles)})


def _bounded_text(value: object, *, max_chars: int = 4_000) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _euro_range(value: object, *, language: str) -> str | None:
    if not isinstance(value, dict):
        return None
    lower = value.get("from") if "from" in value else value.get("min")
    upper = value.get("to") if "to" in value else value.get("max")
    if not isinstance(lower, int | float) and not isinstance(upper, int | float):
        return None
    formatter = (
        (lambda item: f"{item:,.0f}")
        if language == "en"
        else (lambda item: f"{item:,.0f}".replace(",", "."))
    )
    if isinstance(lower, int | float) and isinstance(upper, int | float):
        connector = " to " if language == "en" else " bis "
        return f"{formatter(lower)}{connector}{formatter(upper)} Euro"
    selected = lower if isinstance(lower, int | float) else upper
    assert isinstance(selected, int | float)
    return f"{formatter(selected)} Euro"


class _LobbySearchParser(HTMLParser):
    """Extract public result cards without collecting contact details."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._text: list[str] = []
        self._title: list[str] = []
        self._in_title_link = False

    def _finish(self) -> None:
        if self._current is None:
            return
        self._current["name"] = " ".join(self._title).strip()
        self._current["text"] = " ".join(" ".join(self._text).split())
        self.entries.append(self._current)
        self._current = None
        self._text = []
        self._title = []
        self._in_title_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "h4" and (identifier := values.get("id")):
            prefix = "common-search-result-list-item-"
            if identifier.startswith(prefix):
                self._finish()
                self._current = {"provider_id": identifier.removeprefix(prefix)}
                return
        if self._current is not None and tag == "a" and "url" not in self._current:
            href = values.get("href")
            if href and href.startswith("/suche/"):
                self._current["url"] = urljoin(LOBBYREGISTER_SEARCH, href)
                self._in_title_link = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title_link:
            self._in_title_link = False

    def handle_data(self, data: str) -> None:
        if self._current is None or not data.strip():
            return
        self._text.append(data.strip())
        if self._in_title_link:
            self._title.append(data.strip())

    def close(self) -> None:
        super().close()
        self._finish()


def _between(text: str, start: str, ends: tuple[str, ...]) -> str | None:
    marker = text.find(start)
    if marker < 0:
        return None
    value = text[marker + len(start) :]
    positions = [position for end in ends if (position := value.find(end)) >= 0]
    if positions:
        value = value[: min(positions)]
    value = value.strip(" :;\n\t")
    return value or None


class LobbyregisterActors:
    """Search the Bundestag Lobbyregister without user credentials."""

    source = "lobbyregister"

    def __init__(self, client: httpx.AsyncClient, *, resolver: Resolver = resolve_host) -> None:
        self._http = BoundedHttpClient(
            client,
            allowed_hosts={"www.lobbyregister.bundestag.de"},
            resolver=resolver,
            max_response_bytes=12_000_000,
        )

    async def search(
        self,
        query: str,
        *,
        kind: ActorKind,
        language: Literal["de", "en"],
        limit: int,
    ) -> tuple[ActorSourceRecord, ...]:
        if kind != "interest_representative":
            return ()
        return await self._search_public_page(query, language=language, limit=limit)

    async def _search_public_page(
        self, query: str, *, language: Literal["de", "en"], limit: int
    ) -> tuple[ActorSourceRecord, ...]:
        response = await self._http.get(
            LOBBYREGISTER_SEARCH,
            params={"q": query, "pageSize": min(limit, 10)},
            headers={"Accept": "text/html"},
        )
        if response.status_code != 200:
            raise ActorProviderError("Lobbyregister public search failed")
        parser = _LobbySearchParser()
        parser.feed(response.text)
        parser.close()
        records: list[ActorSourceRecord] = []
        for entry in parser.entries[:limit]:
            record = self._public_record(entry, language=language)
            if record is not None:
                records.append(record)
        return tuple(records)

    def _public_record(
        self, entry: dict[str, str], *, language: Literal["de", "en"]
    ) -> ActorSourceRecord | None:
        provider_id = entry.get("provider_id", "")
        name = entry.get("name", "")
        text = entry.get("text", "")
        official_url = entry.get("url", "")
        if not re.fullmatch(r"R\d{6}", provider_id) or not name or not official_url:
            return None
        category = _between(
            text,
            "Tätigkeitskategorie:",
            ("Interessen- und Vorhabenbereiche", "Jährliche finanzielle Aufwendungen"),
        )
        interests = _between(
            text,
            "):",
            ("Jährliche finanzielle Aufwendungen",),
        )
        spending_match = re.search(
            r"Jährliche finanzielle Aufwendungen im Bereich der Interessenvertretung:.*?"
            r"((?:\d{1,3}(?:\.\d{3})*|0) bis \d{1,3}(?:\.\d{3})* Euro|0 Euro)",
            text,
        )
        modified_match = re.search(r"Letzte Änderung:\s*(\d{2}\.\d{2}\.\d{4})", text)
        modified = _now()
        if modified_match:
            with suppress(ValueError):
                modified = (
                    datetime.strptime(modified_match.group(1), "%d.%m.%Y")
                    .replace(tzinfo=UTC)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
        disclosure = SourceDisclosure(
            section_id="activities-and-interests",
            heading=(
                "Activities and interests" if language == "en" else "Tätigkeiten und Interessen"
            ),
            wording=_bounded_text(interests or category or name),
            spending_range=spending_match.group(1) if spending_match else None,
            evidence_provider_id=f"{provider_id}-search-result",
        )
        return ActorSourceRecord(
            key=f"lobbyregister:interest_representative:{provider_id}",
            kind="interest_representative",
            scope=Jurisdiction.DE,
            source=self.source,
            provider_id=provider_id,
            display_name=name,
            description=category or "Published Lobbyregister entry.",
            official_url=official_url,
            source_modified_at=modified,
            historical_supported=True,
            disclosures=(disclosure,),
        )


class EuWhoisWhoActors:
    """Search public EU WhoisWho identities through its SPARQL endpoint."""

    source = "eu_whoiswho"

    def __init__(self, client: httpx.AsyncClient, *, resolver: Resolver = resolve_host) -> None:
        self._http = BoundedHttpClient(
            client,
            allowed_hosts={"publications.europa.eu"},
            resolver=resolver,
            max_response_bytes=2_000_000,
        )

    async def search(
        self,
        query: str,
        *,
        kind: ActorKind,
        language: Literal["de", "en"],
        limit: int,
    ) -> tuple[ActorSourceRecord, ...]:
        del language
        if kind != "person":
            return ()
        literal = json.dumps(query.casefold(), ensure_ascii=False)
        sparql = f"""PREFIX foaf:<http://xmlns.com/foaf/0.1/>
SELECT DISTINCT ?person ?given ?family WHERE {{
  ?person foaf:familyName ?family .
  OPTIONAL {{ ?person foaf:givenName ?given }}
  FILTER(STRSTARTS(STR(?person),
    "http://publications.europa.eu/resource/directory/person/"))
  FILTER(CONTAINS(LCASE(CONCAT(COALESCE(STR(?given), ""), " ", STR(?family))), {literal}))
}} LIMIT {min(limit, 10)}"""
        response = await self._http.get(
            WHOISWHO_SPARQL, params={"query": sparql, "format": "text/csv"}
        )
        if response.status_code != 200:
            raise ActorProviderError("EU WhoisWho search failed")
        rows = csv.DictReader(io.StringIO(response.text))
        records: list[ActorSourceRecord] = []
        observed_at = _now()
        for row in rows:
            uri = row.get("person", "").strip()
            family = row.get("family", "").strip()
            given = row.get("given", "").strip()
            if not uri or not family:
                continue
            parsed = urlsplit(uri)
            if parsed.scheme != "http" or parsed.hostname != "publications.europa.eu":
                continue
            provider_id = uri.rstrip("/").rsplit("/", 1)[-1]
            records.append(
                ActorSourceRecord(
                    key=f"eu_whoiswho:person:{provider_id}",
                    kind="person",
                    scope=Jurisdiction.EU,
                    source=self.source,
                    provider_id=provider_id,
                    display_name=" ".join(item for item in (given, family) if item),
                    description="Published identity in the official EU directory.",
                    official_url=uri,
                    source_modified_at=observed_at,
                    historical_supported=False,
                )
            )
        return tuple(records)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: Element, path: str) -> str | None:
    current: Element | None = element
    for name in path.split("/"):
        if current is None:
            return None
        current = next((child for child in current if _local_name(child.tag) == name), None)
    if current is None or current.text is None:
        return None
    text = current.text.strip()
    return text or None


def _descendant_texts(element: Element, name: str) -> tuple[str, ...]:
    return tuple(
        child.text.strip()
        for child in element.iter()
        if _local_name(child.tag) == name and child.text and child.text.strip()
    )


class EuTransparencyActors:
    """Search the daily public EU Transparency Register XML snapshot."""

    source = "eu_transparency"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        cache_path: Path | None = None,
        resolver: Resolver = resolve_host,
    ) -> None:
        self._http = BoundedHttpClient(
            client,
            allowed_hosts={"transparency-register.europa.eu"},
            resolver=resolver,
            max_response_bytes=200_000_000,
        )
        self._cache_path = cache_path or data_directory() / "snapshots" / "eu-transparency.xml"

    async def _snapshot(self) -> Path:
        if (
            self._cache_path.is_file()
            and time.time() - self._cache_path.stat().st_mtime < TRANSPARENCY_CACHE_MAX_AGE_SECONDS
        ):
            return self._cache_path
        self._cache_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            await self._http.download(TRANSPARENCY_XML, self._cache_path)
        except (SourceRequestError, httpx.HTTPError) as error:
            if not self._cache_path.is_file():
                raise ActorProviderError("EU Transparency Register download failed") from error
        return self._cache_path

    async def search(
        self,
        query: str,
        *,
        kind: ActorKind,
        language: Literal["de", "en"],
        limit: int,
    ) -> tuple[ActorSourceRecord, ...]:
        if kind != "interest_representative":
            return ()
        path = await self._snapshot()
        return await asyncio.to_thread(self._search_snapshot, path, query, language, limit)

    def _search_snapshot(
        self, path: Path, query: str, language: Literal["de", "en"], limit: int
    ) -> tuple[ActorSourceRecord, ...]:
        export_date = _now()
        records: list[ActorSourceRecord] = []
        try:
            iterator = ElementTree.iterparse(path, events=("end",))
            for _, element in iterator:
                name = _local_name(element.tag)
                if name == "metaData":
                    export_date = _child_text(element, "exportDate") or export_date
                    element.clear()
                    continue
                if name != "interestRepresentative":
                    continue
                record = self._record(
                    element,
                    query=query,
                    language=language,
                    export_date=export_date,
                )
                element.clear()
                if record is not None:
                    records.append(record)
                    if len(records) >= limit:
                        break
        except (ElementTree.ParseError, OSError) as error:
            raise ActorProviderError("EU Transparency Register snapshot is invalid") from error
        return tuple(records)

    def _record(
        self,
        element: Element,
        *,
        query: str,
        language: Literal["de", "en"],
        export_date: str,
    ) -> ActorSourceRecord | None:
        provider_id = _child_text(element, "identificationCode")
        display_name = _child_text(element, "name/originalName")
        if provider_id is None or display_name is None:
            return None
        acronym = _child_text(element, "acronym")
        goals = _child_text(element, "goals") or ""
        proposals = _child_text(element, "EULegislativeProposals") or ""
        activities = _child_text(element, "communicationActivities") or ""
        interests = _descendant_texts(element, "name")
        if not _terms_match(
            query, display_name, acronym or "", goals, proposals, activities, *interests
        ):
            return None
        category = _child_text(element, "registrationCategory")
        lower_text = _child_text(element, "financialData/closedYear/costs/range/min")
        upper_text = _child_text(element, "financialData/closedYear/costs/range/max")
        expense_range: dict[str, int] = {}
        if lower_text and lower_text.isdigit():
            expense_range["min"] = int(lower_text)
        if upper_text and upper_text.isdigit():
            expense_range["max"] = int(upper_text)
        wording = "; ".join(
            item for item in (*interests, _bounded_text(goals), _bounded_text(activities)) if item
        )
        disclosure = SourceDisclosure(
            section_id="declared-activities",
            heading=("Declared activities" if language == "en" else "Erklärte Tätigkeiten"),
            wording=wording or display_name,
            spending_range=_euro_range(expense_range, language=language),
            projects=(proposals,) if proposals else (),
            evidence_provider_id=f"{provider_id}-declaration",
        )
        modified = _child_text(element, "lastUpdateDate") or export_date
        return ActorSourceRecord(
            key=f"eu_transparency:interest_representative:{provider_id}",
            kind="interest_representative",
            scope=Jurisdiction.EU,
            source=self.source,
            provider_id=provider_id,
            display_name=display_name,
            alternative_names=(acronym,) if acronym else (),
            description=category or "Published EU Transparency Register entry.",
            official_url=(
                "https://transparency-register.europa.eu/"
                f"searchregister-or-update/organisation-detail_en?id={provider_id}"
            ),
            source_modified_at=modified,
            historical_supported=False,
            disclosures=(disclosure,),
        )


class LiveActorSources:
    """Fan out one actor search to relevant public sources without user setup."""

    ready_sources = frozenset({"ep", "eu_whoiswho", "lobbyregister", "eu_transparency"})

    def __init__(
        self,
        *,
        resolver: Resolver = resolve_host,
        timeout_seconds: float = 120.0,
        transparency_cache: Path | None = None,
    ) -> None:
        self._resolver = resolver
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))
        self._transparency_cache = transparency_cache

    async def search(
        self,
        query: str,
        *,
        scope: Literal["DE", "EU", "BOTH"],
        kind: ActorKind,
        source: str | None,
        language: Literal["de", "en"],
        limit: int,
    ) -> ActorSourceSearchResult:
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            providers: Sequence[tuple[str, object]] = (
                ("ep", EuropeanParliamentActors(http, resolver=self._resolver)),
                ("eu_whoiswho", EuWhoisWhoActors(http, resolver=self._resolver)),
                ("lobbyregister", LobbyregisterActors(http, resolver=self._resolver)),
                (
                    "eu_transparency",
                    EuTransparencyActors(
                        http,
                        cache_path=self._transparency_cache,
                        resolver=self._resolver,
                    ),
                ),
            )
            selected = [
                (name, provider)
                for name, provider in providers
                if (source is None or source == name)
                and (
                    scope == "BOTH"
                    or (scope == "DE" and name == "lobbyregister")
                    or (scope == "EU" and name != "lobbyregister")
                )
                and (
                    (kind == "person" and name in {"ep", "eu_whoiswho"})
                    or (kind == "institution" and name == "ep")
                    or (
                        kind == "interest_representative"
                        and name in {"lobbyregister", "eu_transparency"}
                    )
                )
            ]
            tasks = [
                provider.search(query, kind=kind, language=language, limit=limit)  # type: ignore[attr-defined]
                for _, provider in selected
            ]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        records: list[ActorSourceRecord] = []
        successful: list[str] = []
        failures: dict[str, str] = {}
        for (name, _), outcome in zip(selected, outcomes, strict=True):
            if isinstance(outcome, asyncio.CancelledError):
                raise outcome
            if isinstance(outcome, BaseException):
                causes: list[str] = []
                current: BaseException | None = outcome
                while current is not None and len(causes) < 3:
                    causes.append(type(current).__name__)
                    current = current.__cause__
                LOGGER.warning("Actor source %s unavailable (%s)", name, " <- ".join(causes))
                failures[name] = "Official source request failed"
                continue
            successful.append(name)
            records.extend(outcome)
        return ActorSourceSearchResult(
            records=tuple(records[:1_000]),
            successful_sources=tuple(successful),
            failures=failures,
            retrieved_at=_now(),
        )
