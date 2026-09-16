"""Fail-closed parsers for German parliamentary records and statutes."""

from __future__ import annotations

import csv
import io
from typing import Literal

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pydantic import BaseModel, ConfigDict

VoteChoice = Literal["yes", "no", "abstain", "absent", "not_recorded"]
VoteKind = Literal["amendment", "final", "other"]


class RecordFormatError(ValueError):
    """A published record does not match a supported, pinned format."""


class SpeechParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locator: str
    text: str


class Speech(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speech_id: str
    speaker_id: str | None
    speaker_name: str
    speaker_resolved: bool
    agenda_id: str
    agenda_title: str
    paragraphs: list[SpeechParagraph]


class Transcript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parser_version: Literal["transcript-v1", "transcript-v2"]
    speeches: list[Speech]


class RecordedVote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: str
    member_name: str
    choice: VoteChoice
    source_value: str
    correction: str | None


class RollCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motion_id: str
    vote_kind: VoteKind
    votes: list[RecordedVote]


class Provision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str
    heading: str
    text: str
    amendment_note: str | None


class ConsolidatedStatute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str
    title: str
    consolidated_as_of: str
    authoritative: Literal[False] = False
    source_url: str
    promulgation_url: str | None
    provisions: list[Provision]


def _xml_root(content: bytes):
    try:
        return ElementTree.fromstring(content)
    except (DefusedXmlException, ElementTree.ParseError) as error:
        raise RecordFormatError("Unsafe or malformed XML record") from error


def _text(node, path: str) -> str:
    selected = node.find(path)
    if selected is None:
        return ""
    return " ".join("".join(selected.itertext()).split())


def parse_transcript_xml(content: bytes) -> Transcript:
    """Parse either supported plenary transcript generation."""
    root = _xml_root(content)
    speeches: list[Speech] = []
    if root.tag == "proceedings" and root.attrib.get("version") == "1":
        parser_version: Literal["transcript-v1", "transcript-v2"] = "transcript-v1"
        for agenda in root.findall("./agenda"):
            for speech in agenda.findall("./speech"):
                speaker_id = speech.attrib.get("speaker-id")
                speeches.append(
                    Speech(
                        speech_id=speech.attrib["id"],
                        speaker_id=speaker_id,
                        speaker_name=speech.attrib.get("speaker", "Unbekannt"),
                        speaker_resolved=speaker_id is not None,
                        agenda_id=agenda.attrib["id"],
                        agenda_title=agenda.attrib.get("title", ""),
                        paragraphs=[
                            SpeechParagraph(
                                locator=paragraph.attrib["id"],
                                text=" ".join("".join(paragraph.itertext()).split()),
                            )
                            for paragraph in speech.findall("./p")
                        ],
                    )
                )
    elif root.tag == "dbtplenarprotokoll" and root.attrib.get("version") == "2":
        parser_version = "transcript-v2"
        for agenda in root.findall("./sitzungsverlauf/tagesordnungspunkt"):
            for speech in agenda.findall("./rede"):
                speaker = speech.find("./redner")
                if speaker is None:
                    speaker_id = None
                    speaker_name = "Unbekannt"
                else:
                    speaker_id = speaker.attrib.get("id")
                    speaker_name = _text(speaker, "./name") or "Unbekannt"
                speeches.append(
                    Speech(
                        speech_id=speech.attrib["id"],
                        speaker_id=speaker_id,
                        speaker_name=speaker_name,
                        speaker_resolved=speaker_id is not None,
                        agenda_id=agenda.attrib["id"],
                        agenda_title=agenda.attrib.get("titel", ""),
                        paragraphs=[
                            SpeechParagraph(
                                locator=paragraph.attrib["id"],
                                text=" ".join("".join(paragraph.itertext()).split()),
                            )
                            for paragraph in speech.findall("./p")
                        ],
                    )
                )
    else:
        raise RecordFormatError("Unsupported transcript XML generation")
    return Transcript(parser_version=parser_version, speeches=speeches)


ROLL_CALL_HEADERS = {
    "member_id",
    "member_name",
    "choice",
    "correction",
    "motion_id",
    "vote_kind",
}
VOTE_CHOICES: dict[str, VoteChoice] = {
    "YES": "yes",
    "NO": "no",
    "ABSTAIN": "abstain",
    "ABSENT": "absent",
    "NOT_RECORDED": "not_recorded",
}


def parse_roll_call_csv(content: bytes) -> RollCall:
    """Parse a roll call by named column meaning, never column position."""
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    except UnicodeDecodeError as error:
        raise RecordFormatError("Roll-call file is not UTF-8") from error
    if set(reader.fieldnames or ()) != ROLL_CALL_HEADERS:
        raise RecordFormatError("Roll-call headers do not match the pinned schema")
    votes: list[RecordedVote] = []
    motion_id: str | None = None
    vote_kind: VoteKind | None = None
    for row in reader:
        if any(value.lstrip().startswith(("=", "+", "-", "@")) for value in row.values()):
            raise RecordFormatError("Spreadsheet formula values are forbidden")
        source_value = row["choice"].strip().upper()
        normalized = VOTE_CHOICES.get(source_value)
        if normalized is None:
            raise RecordFormatError(f"Unsupported recorded vote value: {source_value}")
        row_motion = row["motion_id"].strip()
        source_kind = row["vote_kind"].strip().lower()
        if source_kind == "amendment":
            row_kind: VoteKind = "amendment"
        elif source_kind == "final":
            row_kind = "final"
        elif source_kind == "other":
            row_kind = "other"
        else:
            raise RecordFormatError(f"Unsupported vote kind: {source_kind}")
        if motion_id is not None and motion_id != row_motion:
            raise RecordFormatError("One roll-call file contains multiple motions")
        if vote_kind is not None and vote_kind != row_kind:
            raise RecordFormatError("One roll-call file contains multiple vote kinds")
        motion_id = row_motion
        vote_kind = row_kind
        votes.append(
            RecordedVote(
                member_id=row["member_id"].strip(),
                member_name=row["member_name"].strip(),
                choice=normalized,
                source_value=source_value,
                correction=row["correction"].strip() or None,
            )
        )
    if motion_id is None or vote_kind is None:
        raise RecordFormatError("Roll-call file contains no votes")
    return RollCall(motion_id=motion_id, vote_kind=vote_kind, votes=votes)


def parse_statute_xml(content: bytes) -> ConsolidatedStatute:
    """Parse consolidated statute XML without claiming gazette authority."""
    root = _xml_root(content)
    if root.tag != "statute":
        raise RecordFormatError("Unsupported statute XML generation")
    source = root.find("./source")
    if source is None or not source.attrib.get("href", "").startswith("https://"):
        raise RecordFormatError("Statute source URL is missing or invalid")
    promulgation = root.find("./promulgation")
    return ConsolidatedStatute(
        identifier=root.attrib["id"],
        title=root.attrib["title"],
        consolidated_as_of=root.attrib["consolidated"],
        source_url=source.attrib["href"],
        promulgation_url=(promulgation.attrib.get("href") if promulgation is not None else None),
        provisions=[
            Provision(
                identifier=provision.attrib["id"],
                heading=provision.attrib.get("heading", ""),
                text=_text(provision, "./text"),
                amendment_note=_text(provision, "./amendment") or None,
            )
            for provision in root.findall("./provision")
        ],
    )
