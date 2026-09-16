"""Versioned parser contracts for German parliamentary records and laws."""

from __future__ import annotations

import pytest

from policy_mcp.german_records import (
    RecordFormatError,
    parse_roll_call_csv,
    parse_statute_xml,
    parse_transcript_xml,
)


def test_two_transcript_generations_preserve_speaker_agenda_and_paragraph_locators() -> None:
    old = b"""<?xml version='1.0' encoding='utf-8'?>
    <proceedings version="1">
      <agenda id="TOP-1" title="Energiegesetz">
        <speech id="S-1" speaker-id="1101" speaker="Ada Beispiel">
          <p id="P-1">Das gilt nicht ohne Ausnahme.</p>
          <p id="P-2">Die Ausnahme bleibt eng begrenzt.</p>
        </speech>
      </agenda>
    </proceedings>"""
    new = b"""<?xml version='1.0' encoding='utf-8'?>
    <dbtplenarprotokoll version="2">
      <sitzungsverlauf><tagesordnungspunkt id="TOP-2" titel="Haushalt">
        <rede id="S-2"><redner id="1102"><name>Ben Beispiel</name></redner>
          <p klasse="J" id="P-3">Der Ansatz betraegt 10 Millionen Euro.</p>
        </rede>
      </tagesordnungspunkt></sitzungsverlauf>
    </dbtplenarprotokoll>"""

    old_result = parse_transcript_xml(old)
    new_result = parse_transcript_xml(new)

    assert old_result.parser_version == "transcript-v1"
    assert old_result.speeches[0].model_dump() == {
        "speech_id": "S-1",
        "speaker_id": "1101",
        "speaker_name": "Ada Beispiel",
        "speaker_resolved": True,
        "agenda_id": "TOP-1",
        "agenda_title": "Energiegesetz",
        "paragraphs": [
            {"locator": "P-1", "text": "Das gilt nicht ohne Ausnahme."},
            {"locator": "P-2", "text": "Die Ausnahme bleibt eng begrenzt."},
        ],
    }
    assert new_result.parser_version == "transcript-v2"
    assert new_result.speeches[0].speaker_name == "Ben Beispiel"
    assert new_result.speeches[0].paragraphs[0].locator == "P-3"


def test_transcript_reports_unresolved_speaker_instead_of_guessing() -> None:
    document = b"""<proceedings version="1"><agenda id="A" title="Debatte">
      <speech id="S" speaker="Alex Beispiel"><p id="P">Text</p></speech>
    </agenda></proceedings>"""

    speech = parse_transcript_xml(document).speeches[0]

    assert speech.speaker_name == "Alex Beispiel"
    assert speech.speaker_id is None
    assert speech.speaker_resolved is False


def test_roll_call_maps_headers_by_meaning_and_preserves_non_votes() -> None:
    content = b"""choice,member_id,member_name,correction,motion_id,vote_kind
YES,1101,Ada Beispiel,,M-1,amendment
NOT_RECORDED,1102,Ben Beispiel,late correction,M-1,amendment
"""

    result = parse_roll_call_csv(content)

    assert result.motion_id == "M-1"
    assert result.vote_kind == "amendment"
    assert result.votes[0].choice == "yes"
    assert result.votes[1].choice == "not_recorded"
    assert result.votes[1].correction == "late correction"


def test_roll_call_rejects_changed_headers_and_formulas() -> None:
    with pytest.raises(RecordFormatError, match="headers"):
        parse_roll_call_csv(b"name,result\nAda,YES\n")
    with pytest.raises(RecordFormatError, match="formula"):
        parse_roll_call_csv(
            b"member_id,member_name,choice,correction,motion_id,vote_kind\n"
            b"1101,Ada,=1+1,,M-1,final\n"
        )


def test_statute_preserves_consolidated_status_and_amendment_note() -> None:
    content = b"""<?xml version='1.0' encoding='utf-8'?>
    <statute id="BGB" title="Buergerliches Gesetzbuch" consolidated="2026-01-01">
      <source href="https://www.gesetze-im-internet.de/bgb/">Consolidated service</source>
      <promulgation href="https://www.recht.bund.de/">Bundesgesetzblatt</promulgation>
      <provision id="p-1" heading="Paragraph 1">
        <text>Die Rechtsfaehigkeit beginnt mit der Vollendung der Geburt.</text>
        <amendment>Zuletzt geaendert am 1. Januar 2026.</amendment>
      </provision>
    </statute>"""

    statute = parse_statute_xml(content)

    assert statute.identifier == "BGB"
    assert statute.consolidated_as_of == "2026-01-01"
    assert statute.authoritative is False
    assert statute.promulgation_url == "https://www.recht.bund.de/"
    assert statute.provisions[0].amendment_note == "Zuletzt geaendert am 1. Januar 2026."


def test_hostile_xml_fails_closed() -> None:
    hostile = b'<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><x>&secret;</x>'

    with pytest.raises(RecordFormatError, match="XML"):
        parse_transcript_xml(hostile)
