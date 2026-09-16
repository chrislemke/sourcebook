"""Strict, bounded contracts for selected European public sources."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

type Language = Literal[
    "bg",
    "cs",
    "da",
    "de",
    "el",
    "en",
    "es",
    "et",
    "fi",
    "fr",
    "ga",
    "hr",
    "hu",
    "it",
    "lt",
    "lv",
    "mt",
    "nl",
    "pl",
    "pt",
    "ro",
    "sk",
    "sl",
    "sv",
]
type ComitologyFamily = Literal[
    "committee",
    "agenda",
    "draft_measure",
    "voting_sheet",
    "summary_record",
    "document",
]
NonEmptyString = Annotated[str, Field(min_length=1)]
IsoDate = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
IsoTimestamp = Annotated[
    str,
    Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"),
]

CELEX_PATTERN = re.compile(r"[0-9E][0-9]{4}[A-Z]{1,2}[0-9]{4}(?:\([0-9]{2}\))?")
EP_HOSTS = frozenset({"data.europarl.europa.eu", "www.europarl.europa.eu"})
COMITOLOGY_HOSTS = frozenset({"ec.europa.eu", "data.europa.eu"})
TEXT_ATTACHMENT_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "application/xml",
        "text/html",
        "text/plain",
        "text/xml",
    }
)


class FrozenModel(BaseModel):
    """Strict immutable base for normalized source contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _official_https_url(value: str, hosts: frozenset[str]) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("URL must use an allowlisted official HTTPS host")
    return value


class CompiledCellarQuery(FrozenModel):
    """A server-authored CELLAR query for one validated CELEX identifier."""

    identifier: NonEmptyString
    language: Literal["de", "en"]
    query: NonEmptyString


def compile_cellar_celex_query(identifier: str, language: str) -> CompiledCellarQuery:
    """Compile a CELEX lookup through one fixed SELECT template."""
    if CELEX_PATTERN.fullmatch(identifier) is None:
        raise ValueError("Invalid CELEX identifier")
    if language == "de":
        language_uri = "DEU"
    elif language == "en":
        language_uri = "ENG"
    else:
        raise ValueError("Unsupported CELLAR language; expected de or en")
    query = f"""SELECT ?work ?expression ?manifestation ?file
WHERE {{
  ?work <http://publications.europa.eu/ontology/cdm#resource_legal_id_celex> "{identifier}" .
  ?expression
    <http://publications.europa.eu/ontology/cdm#expression_belongs_to_work> ?work ;
    <http://publications.europa.eu/ontology/cdm#expression_uses_language>
    <http://publications.europa.eu/resource/authority/language/{language_uri}> .
  OPTIONAL {{
    ?manifestation
      <http://publications.europa.eu/ontology/cdm#manifestation_manifests_expression>
      ?expression .
    OPTIONAL {{
      ?file
        <http://publications.europa.eu/ontology/cdm#file_belongs_to_manifestation>
        ?manifestation .
    }}
  }}
}}
ORDER BY ?expression ?manifestation ?file
LIMIT 25"""
    return CompiledCellarQuery(identifier=identifier, language=language, query=query)


class _OfficialEpUrl(FrozenModel):
    source_url: NonEmptyString

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        return _official_https_url(value, EP_HOSTS)


class _EPProcedurePayload(_OfficialEpUrl):
    identifier: NonEmptyString
    title: NonEmptyString
    status: NonEmptyString
    language: Language


class _EPEventPayload(_OfficialEpUrl):
    identifier: NonEmptyString
    procedure_identifier: NonEmptyString
    event_date: IsoDate
    event_type: NonEmptyString
    title: NonEmptyString
    language: Language


class _EPDocumentPayload(_OfficialEpUrl):
    identifier: NonEmptyString
    procedure_identifier: NonEmptyString
    document_type: NonEmptyString
    title: NonEmptyString
    language: Language


class _EPSpeechPayload(_OfficialEpUrl):
    identifier: NonEmptyString
    speaker_identifier: NonEmptyString
    sitting_date: IsoDate
    title: NonEmptyString
    text: NonEmptyString
    language: Language


class EPProcedureRecord(FrozenModel):
    """Normalized procedure without conflating events or documents."""

    kind: Literal["procedure"] = "procedure"
    identifier: NonEmptyString
    title: NonEmptyString
    status: NonEmptyString
    source_language: Language
    source_url: NonEmptyString
    source_text_is_inert: Literal[True] = True


class EPEventRecord(FrozenModel):
    """Normalized dated procedure event."""

    kind: Literal["event"] = "event"
    identifier: NonEmptyString
    procedure_identifier: NonEmptyString
    event_date: IsoDate
    event_type: NonEmptyString
    title: NonEmptyString
    source_language: Language
    source_url: NonEmptyString
    source_text_is_inert: Literal[True] = True


class EPDocumentRecord(FrozenModel):
    """Normalized parliamentary document kept separate from its procedure."""

    kind: Literal["document"] = "document"
    identifier: NonEmptyString
    procedure_identifier: NonEmptyString
    document_type: NonEmptyString
    title: NonEmptyString
    source_language: Language
    source_url: NonEmptyString
    source_text_is_inert: Literal[True] = True


class EPSpeechRecord(FrozenModel):
    """Normalized speech with its source wording retained as inert text."""

    kind: Literal["speech"] = "speech"
    identifier: NonEmptyString
    speaker_identifier: NonEmptyString
    sitting_date: IsoDate
    title: NonEmptyString
    text: NonEmptyString
    source_language: Language
    source_url: NonEmptyString
    source_text_is_inert: Literal[True] = True


type EPRecord = EPProcedureRecord | EPEventRecord | EPDocumentRecord | EPSpeechRecord


def normalize_ep_collection(collection: str, payload: Mapping[str, object]) -> EPRecord:
    """Validate one collection-specific EP payload and preserve its entity kind."""
    if collection == "procedure":
        source = _EPProcedurePayload.model_validate(payload)
        return EPProcedureRecord(
            identifier=source.identifier,
            title=source.title,
            status=source.status,
            source_language=source.language,
            source_url=source.source_url,
        )
    if collection == "event":
        source = _EPEventPayload.model_validate(payload)
        return EPEventRecord(
            identifier=source.identifier,
            procedure_identifier=source.procedure_identifier,
            event_date=source.event_date,
            event_type=source.event_type,
            title=source.title,
            source_language=source.language,
            source_url=source.source_url,
        )
    if collection == "document":
        source = _EPDocumentPayload.model_validate(payload)
        return EPDocumentRecord(
            identifier=source.identifier,
            procedure_identifier=source.procedure_identifier,
            document_type=source.document_type,
            title=source.title,
            source_language=source.language,
            source_url=source.source_url,
        )
    if collection == "speech":
        source = _EPSpeechPayload.model_validate(payload)
        return EPSpeechRecord(
            identifier=source.identifier,
            speaker_identifier=source.speaker_identifier,
            sitting_date=source.sitting_date,
            title=source.title,
            text=source.text,
            source_language=source.language,
            source_url=source.source_url,
        )
    raise ValueError(f"Unsupported European Parliament collection: {collection}")


class _ComitologyManifest(FrozenModel):
    snapshot_id: NonEmptyString
    family: ComitologyFamily
    published_at: IsoTimestamp
    requested_language: Language
    source_language: Language
    distribution_url: NonEmptyString
    record_count: Annotated[int, Field(ge=0)]

    @field_validator("distribution_url")
    @classmethod
    def validate_distribution_url(cls, value: str) -> str:
        return _official_https_url(value, COMITOLOGY_HOSTS)


class _ComitologyRecordBase(FrozenModel):
    identifier: NonEmptyString
    title: NonEmptyString
    language: Language
    source_url: NonEmptyString

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        return _official_https_url(value, COMITOLOGY_HOSTS)


class _CommitteePayload(_ComitologyRecordBase):
    pass


class _AgendaPayload(_ComitologyRecordBase):
    committee_identifier: NonEmptyString
    meeting_date: IsoDate


class _DraftMeasurePayload(_ComitologyRecordBase):
    committee_identifier: NonEmptyString


class _VotingSheetPayload(_ComitologyRecordBase):
    draft_measure_identifier: NonEmptyString


class _SummaryRecordPayload(_ComitologyRecordBase):
    committee_identifier: NonEmptyString
    meeting_identifier: NonEmptyString


class _AttachmentPayload(FrozenModel):
    url: NonEmptyString
    media_type: NonEmptyString

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _official_https_url(value, COMITOLOGY_HOSTS)


class _DocumentPayload(_ComitologyRecordBase):
    parent_identifier: NonEmptyString
    document_type: NonEmptyString
    attachment: _AttachmentPayload | None = None


class LinkedIdentifier(FrozenModel):
    """An explicit identifier relation supplied by Comitology."""

    relation: Literal["committee", "meeting", "draft_measure", "parent"]
    identifier: NonEmptyString


class AttachmentDisposition(FrozenModel):
    """Validated attachment metadata and whether text handling is supported."""

    url: NonEmptyString
    media_type: NonEmptyString
    metadata_only: bool
    text_available: bool


class ComitologyRecord(FrozenModel):
    """One Comitology entity with identifiers and links kept separate."""

    family: ComitologyFamily
    identifier: NonEmptyString
    title: NonEmptyString
    source_language: Language
    source_url: NonEmptyString
    linked_identifiers: tuple[LinkedIdentifier, ...]
    attachment: AttachmentDisposition | None
    source_text_is_inert: Literal[True] = True


class ComitologySnapshot(FrozenModel):
    """One validated distribution snapshot and its normalized records."""

    snapshot_id: NonEmptyString
    family: ComitologyFamily
    published_at: IsoTimestamp
    requested_language: Language
    source_language: Language
    distribution_url: NonEmptyString
    language_fallback: bool
    records: tuple[ComitologyRecord, ...]


type ComitologyPayload = (
    _CommitteePayload
    | _AgendaPayload
    | _DraftMeasurePayload
    | _VotingSheetPayload
    | _SummaryRecordPayload
    | _DocumentPayload
)


def _parse_comitology_record(
    family: ComitologyFamily,
    value: Mapping[str, object],
) -> ComitologyPayload:
    models: dict[ComitologyFamily, type[ComitologyPayload]] = {
        "committee": _CommitteePayload,
        "agenda": _AgendaPayload,
        "draft_measure": _DraftMeasurePayload,
        "voting_sheet": _VotingSheetPayload,
        "summary_record": _SummaryRecordPayload,
        "document": _DocumentPayload,
    }
    return models[family].model_validate(value)


def _linked_identifiers(source: ComitologyPayload) -> tuple[LinkedIdentifier, ...]:
    links: list[LinkedIdentifier] = []
    if isinstance(source, (_AgendaPayload, _DraftMeasurePayload, _SummaryRecordPayload)):
        links.append(LinkedIdentifier(relation="committee", identifier=source.committee_identifier))
    if isinstance(source, _VotingSheetPayload):
        links.append(
            LinkedIdentifier(
                relation="draft_measure",
                identifier=source.draft_measure_identifier,
            )
        )
    if isinstance(source, _SummaryRecordPayload):
        links.append(LinkedIdentifier(relation="meeting", identifier=source.meeting_identifier))
    if isinstance(source, _DocumentPayload):
        links.append(LinkedIdentifier(relation="parent", identifier=source.parent_identifier))
    return tuple(links)


def _attachment(source: ComitologyPayload) -> AttachmentDisposition | None:
    if not isinstance(source, _DocumentPayload) or source.attachment is None:
        return None
    text_available = source.attachment.media_type in TEXT_ATTACHMENT_MEDIA_TYPES
    return AttachmentDisposition(
        url=source.attachment.url,
        media_type=source.attachment.media_type,
        metadata_only=not text_available,
        text_available=text_available,
    )


def parse_comitology_snapshot(
    manifest: Mapping[str, object],
    records: Sequence[Mapping[str, object]],
) -> ComitologySnapshot:
    """Validate and normalize exactly one of the six published dataset families."""
    source_manifest = _ComitologyManifest.model_validate(manifest)
    if source_manifest.record_count != len(records):
        raise ValueError("Comitology manifest record_count does not match records")
    normalized: list[ComitologyRecord] = []
    for value in records:
        source = _parse_comitology_record(source_manifest.family, value)
        if source.language != source_manifest.source_language:
            raise ValueError("Comitology record language differs from manifest source_language")
        normalized.append(
            ComitologyRecord(
                family=source_manifest.family,
                identifier=source.identifier,
                title=source.title,
                source_language=source.language,
                source_url=source.source_url,
                linked_identifiers=_linked_identifiers(source),
                attachment=_attachment(source),
            )
        )
    return ComitologySnapshot(
        snapshot_id=source_manifest.snapshot_id,
        family=source_manifest.family,
        published_at=source_manifest.published_at,
        requested_language=source_manifest.requested_language,
        source_language=source_manifest.source_language,
        distribution_url=source_manifest.distribution_url,
        language_fallback=(source_manifest.requested_language != source_manifest.source_language),
        records=tuple(normalized),
    )
