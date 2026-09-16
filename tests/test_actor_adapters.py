"""Zero-configuration contracts for the live actor sources."""

from __future__ import annotations

import ipaddress
from pathlib import Path

import httpx
import pytest
import respx

from policy_mcp.adapters.actors import (
    ActorSearchUnsupportedError,
    EuropeanParliamentActors,
    EuTransparencyActors,
    EuWhoisWhoActors,
    LiveActorSources,
    LobbyregisterActors,
)


def public_resolver(_: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    return [ipaddress.ip_address("8.8.8.8")]


EP_LIST = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:foaf="http://xmlns.com/foaf/0.1/"
 xmlns:dcterms="http://purl.org/dc/terms/">
  <foaf:Person rdf:about="https://data.europarl.europa.eu/person/1077">
    <rdfs:label>Friedrich MERZ</rdfs:label>
    <dcterms:identifier>1077</dcterms:identifier>
    <foaf:givenName>Friedrich</foaf:givenName>
    <foaf:familyName>Merz</foaf:familyName>
  </foaf:Person>
</rdf:RDF>
"""

EP_DETAIL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:foaf="http://xmlns.com/foaf/0.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcat="http://www.w3.org/ns/dcat#"
 xmlns:org="http://www.w3.org/ns/org#">
  <foaf:Person rdf:about="https://data.europarl.europa.eu/person/1077">
    <rdfs:label>Friedrich MERZ</rdfs:label>
    <foaf:givenName>Friedrich</foaf:givenName>
    <foaf:familyName>Merz</foaf:familyName>
    <org:hasMembership>
      <org:Membership rdf:about="https://data.europarl.europa.eu/membership/1077-m-8596">
        <dcterms:identifier>1077-f-107416</dcterms:identifier>
        <org:memberDuring>
          <dcterms:PeriodOfTime>
            <dcat:startDate>1989-07-25</dcat:startDate>
            <dcat:endDate>1994-07-18</dcat:endDate>
          </dcterms:PeriodOfTime>
        </org:memberDuring>
        <org:role rdf:resource="https://data.europarl.europa.eu/def/ep-roles/MEMBER_PARLIAMENT"/>
        <org:organization rdf:resource="https://data.europarl.europa.eu/org/ep-3"/>
      </org:Membership>
    </org:hasMembership>
    <dcterms:identifier>1077</dcterms:identifier>
  </foaf:Person>
</rdf:RDF>
"""


@respx.mock
async def test_ep_search_returns_historical_member_without_configuration() -> None:
    respx.get("https://data.europarl.europa.eu/api/v2/meps").mock(
        return_value=httpx.Response(
            200, text=EP_LIST, headers={"content-type": "application/rdf+xml"}
        )
    )
    respx.get("https://data.europarl.europa.eu/api/v2/meps/1077").mock(
        return_value=httpx.Response(
            200, text=EP_DETAIL, headers={"content-type": "application/rdf+xml"}
        )
    )

    async with httpx.AsyncClient() as http:
        records = await EuropeanParliamentActors(http, resolver=public_resolver).search(
            "Friedrich Merz", kind="person", language="de", limit=5
        )

    assert records[0].provider_id == "1077"
    assert records[0].display_name == "Friedrich MERZ"
    assert records[0].roles[0].valid_from == "1989-07-25"
    assert records[0].roles[0].valid_to == "1994-07-18"


@respx.mock
async def test_lobbyregister_uses_public_search_without_a_key() -> None:
    search = respx.get("https://www.lobbyregister.bundestag.de/suche").mock(
        return_value=httpx.Response(
            200,
            text="""
<ul class="results-parent-list">
  <li><div class="mod-common-search-result-list-item-register-entry">
    <h4 id="common-search-result-list-item-R001542">
      <a href="/suche/R001542/69471"><span>BdKom</span></a>
    </h4>
    <strong>Registernummer:</strong><span>R001542</span>
    <strong>Letzte Änderung:</strong><span>07.07.2026</span>
    <strong>Tätigkeitskategorie:</strong><span>Berufsverband</span>
    <strong>Interessen- und Vorhabenbereiche (2):</strong>
    <span>Digitalisierung; Internetpolitik</span>
    <strong>Jährliche finanzielle Aufwendungen im Bereich der Interessenvertretung:</strong>
    <div>Geschäftsjahr: 01/25 bis 12/25 <span>1 bis 10.000 Euro</span></div>
  </div></li>
</ul>
""",
        )
    )

    async with httpx.AsyncClient() as http:
        records = await LobbyregisterActors(http, resolver=public_resolver).search(
            "Friedrich Merz", kind="interest_representative", language="de", limit=5
        )

    assert search.calls[0].request.url.params["q"] == "Friedrich Merz"
    assert records[0].provider_id == "R001542"
    assert records[0].display_name == "BdKom"
    assert records[0].description == "Berufsverband"
    assert records[0].disclosures[0].wording == "Digitalisierung; Internetpolitik"
    assert records[0].disclosures[0].spending_range == "1 bis 10.000 Euro"


@respx.mock
async def test_whoiswho_search_uses_public_sparql_endpoint() -> None:
    route = respx.get("https://publications.europa.eu/webapi/rdf/sparql").mock(
        return_value=httpx.Response(
            200,
            text=(
                '"person","given","family"\n'
                '"http://publications.europa.eu/resource/directory/person/EURCOU_NRE537797",'
                '"Friedrich","MERZ"\n'
            ),
            headers={"content-type": "text/csv"},
        )
    )

    async with httpx.AsyncClient() as http:
        records = await EuWhoisWhoActors(http, resolver=public_resolver).search(
            "Friedrich Merz", kind="person", language="de", limit=5
        )

    assert "merz" in str(route.calls[0].request.url).casefold()
    assert records[0].display_name == "Friedrich MERZ"
    assert records[0].provider_id == "EURCOU_NRE537797"


async def test_transparency_register_searches_cached_public_snapshot(tmp_path: Path) -> None:
    snapshot = tmp_path / "eu-transparency.xml"
    snapshot.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<ListOfIRPublicDetail>
  <metaData><exportDate>2026-09-15T20:00:00+00:00</exportDate></metaData>
  <resultList>
    <interestRepresentative>
      <identificationCode>123456789-10</identificationCode>
      <lastUpdateDate>2026-09-10T10:00:00+00:00</lastUpdateDate>
      <name><originalName>Digital Public Services Alliance</originalName></name>
      <acronym>DPSA</acronym>
      <registrationCategory>Trade association</registrationCategory>
      <goals>Interoperable public registers</goals>
      <EULegislativeProposals>Interoperable Europe</EULegislativeProposals>
      <interests><interest><name>Digital economy and society</name></interest></interests>
      <financialData><closedYear><costs><range><min>50000</min><max>99999</max></range></costs></closedYear></financialData>
    </interestRepresentative>
  </resultList>
</ListOfIRPublicDetail>
"""
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ) as http:
        records = await EuTransparencyActors(
            http,
            cache_path=snapshot,
            resolver=public_resolver,
        ).search("public registers", kind="interest_representative", language="en", limit=5)

    assert records[0].provider_id == "123456789-10"
    assert records[0].display_name == "Digital Public Services Alliance"
    assert records[0].disclosures[0].spending_range == "50,000 to 99,999 Euro"


TRANSPARENCY_XML_11 = """<?xml version='1.1' encoding='UTF-8'?>
<ListOfIRPublicDetail xmlns="http://intragate.ec.europa.eu/transparencyregister/odp">
  <metaData xmlns=""><exportDate>2026-09-15T20:00:00.070+00:00</exportDate></metaData>
  <resultList xmlns="">
    <interestRepresentative>
      <identificationCode>111-01</identificationCode>
      <name><originalName>Hydrogen Mobility Club</originalName></name>
      <goals>Works with BASF&#x2;suppliers on fuel cells</goals>
      <interests><interest><name>Energy</name></interest></interests>
      <financialData><closedYear><contributions><contributor>
        <name>Contributor that must not appear</name>
      </contributor></contributions></closedYear></financialData>
    </interestRepresentative>
    <interestRepresentative>
      <identificationCode>222-02</identificationCode>
      <lastUpdateDate>2026-09-10T11:41:14.144+00:00</lastUpdateDate>
      <name><originalName>BASF SE</originalName></name>
      <goals>Chemistry</goals>
    </interestRepresentative>
  </resultList>
</ListOfIRPublicDetail>
"""


async def test_transparency_snapshot_accepts_xml_11_references_and_ranks_names_first(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "eu-transparency.xml"
    snapshot.write_text(TRANSPARENCY_XML_11)

    async with httpx.AsyncClient() as http:
        records = await EuTransparencyActors(
            http, cache_path=snapshot, resolver=public_resolver
        ).search("BASF", kind="interest_representative", language="en", limit=5)

    assert [record.display_name for record in records] == ["BASF SE", "Hydrogen Mobility Club"]
    assert "Contributor" not in records[1].disclosures[0].wording
    assert records[0].source_modified_at == "2026-09-10T11:41:14.144+00:00"
    assert records[1].source_modified_at == "2026-09-15T20:00:00.070+00:00"


@respx.mock
async def test_transparency_snapshot_download_follows_the_official_redirect(
    tmp_path: Path,
) -> None:
    respx.get("https://transparency-register.europa.eu/odplastorganisationxml_en").mock(
        return_value=httpx.Response(
            301,
            headers={
                "location": (
                    "https://ec.europa.eu/transparencyregister/public/files/ODP/download/XML/latest"
                )
            },
        )
    )
    respx.get(
        "https://ec.europa.eu/transparencyregister/public/files/ODP/download/XML/latest"
    ).mock(return_value=httpx.Response(200, text=TRANSPARENCY_XML_11))
    snapshot = tmp_path / "snapshots" / "eu-transparency.xml"

    async with httpx.AsyncClient() as http:
        records = await EuTransparencyActors(
            http, cache_path=snapshot, resolver=public_resolver
        ).search("BASF SE", kind="interest_representative", language="de", limit=5)

    assert [record.provider_id for record in records] == ["222-02"]
    assert snapshot.is_file()


@respx.mock
async def test_ep_institution_detail_reads_json_ld_names_and_validity() -> None:
    respx.get("https://data.europarl.europa.eu/api/v2/corporate-bodies").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"identifier": "1041", "type": "Organization", "label": "BUDG"}]},
        )
    )
    respx.get("https://data.europarl.europa.eu/api/v2/corporate-bodies/1041").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "identifier": "1041",
                        "label": "BUDG",
                        "prefLabel": {"de": "Haushaltsausschuss", "en": "Committee on Budgets"},
                        "altLabel": {"de": "Haushalt", "en": "Budgets"},
                        "classification": "def/ep-entities/COMMITTEE_PARLIAMENTARY_STANDING",
                        "temporal": {"startDate": "2024-07-16"},
                    }
                ]
            },
        )
    )

    async with httpx.AsyncClient() as http:
        records = await EuropeanParliamentActors(http, resolver=public_resolver).search(
            "BUDG", kind="institution", language="de", limit=5
        )

    assert records[0].display_name == "Haushaltsausschuss"
    assert records[0].alternative_names == ("BUDG", "Haushalt", "Budgets")
    assert "valid from 2024-07-16" in records[0].description
    assert records[0].source_modified_at is None


@respx.mock
async def test_live_sources_interleave_answering_sources(tmp_path: Path) -> None:
    respx.get("https://www.lobbyregister.bundestag.de/suche").mock(
        return_value=httpx.Response(
            200,
            text="".join(
                f'<h4 id="common-search-result-list-item-R00000{index}">'
                f'<a href="/suche/R00000{index}/1?backUrl=%2Fsuche">BASF {index}</a></h4>'
                for index in (1, 2)
            ),
        )
    )
    snapshot = tmp_path / "eu-transparency.xml"
    snapshot.write_text(TRANSPARENCY_XML_11)

    result = await LiveActorSources(resolver=public_resolver, transparency_cache=snapshot).search(
        "BASF",
        scope="BOTH",
        kind="interest_representative",
        source=None,
        language="de",
        limit=5,
    )

    assert [record.source for record in result.records] == [
        "lobbyregister",
        "eu_transparency",
        "lobbyregister",
        "eu_transparency",
    ]
    assert (
        result.records[0].official_url == "https://www.lobbyregister.bundestag.de/suche/R000001/1"
    )
    assert result.records[0].source_modified_at is None


async def test_live_sources_reject_combinations_without_a_connected_source() -> None:
    with pytest.raises(ActorSearchUnsupportedError, match="European Parliament"):
        await LiveActorSources(resolver=public_resolver).search(
            "Friedrich Merz",
            scope="DE",
            kind="person",
            source=None,
            language="de",
            limit=5,
        )


@respx.mock
async def test_ep_roles_name_bodies_by_official_acronym(monkeypatch: pytest.MonkeyPatch) -> None:
    import policy_mcp.adapters.actors as actors_module

    monkeypatch.setattr(actors_module, "_EP_BODY_NAMES", {})
    monkeypatch.setattr(actors_module, "_EP_BODY_NAMES_LOADED_AT", None)
    respx.get("https://data.europarl.europa.eu/api/v2/meps").mock(
        return_value=httpx.Response(200, text=EP_LIST)
    )
    respx.get("https://data.europarl.europa.eu/api/v2/meps/1077").mock(
        return_value=httpx.Response(
            200,
            text=EP_DETAIL.replace("org/ep-3", "org/605").replace(
                "ep-roles/MEMBER_PARLIAMENT", "ep-roles/MEMBER"
            ),
        )
    )
    respx.get("https://data.europarl.europa.eu/api/v2/corporate-bodies").mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:dcterms="http://purl.org/dc/terms/" xmlns:org="http://www.w3.org/ns/org#">
  <org:Organization rdf:about="https://data.europarl.europa.eu/org/605">
    <rdfs:label>ECON</rdfs:label>
    <org:classification
      rdf:resource="https://data.europarl.europa.eu/def/ep-entities/COMMITTEE_PARLIAMENTARY_STANDING"/>
    <dcterms:identifier>605</dcterms:identifier>
  </org:Organization>
</rdf:RDF>
""",
        )
    )

    async with httpx.AsyncClient() as http:
        records = await EuropeanParliamentActors(http, resolver=public_resolver).search(
            "Friedrich Merz", kind="person", language="de", limit=5
        )

    assert records[0].roles[0].organisation_name == (
        "European Parliament committee parliamentary standing ECON"
    )
