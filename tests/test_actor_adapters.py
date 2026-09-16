"""Zero-configuration contracts for the live actor sources."""

from __future__ import annotations

import ipaddress
from pathlib import Path

import httpx
import respx

from policy_mcp.adapters.actors import (
    EuropeanParliamentActors,
    EuTransparencyActors,
    EuWhoisWhoActors,
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
