"""Shared MCP contract metadata used by runtime and package manifests."""

from typing import Final

from policy_mcp.profiles import Profile

TOOL_DESCRIPTIONS: Final[dict[str, str]] = {
    "legislation_search": (
        "Search German federal legislative procedures (Gesetzgebungsverfahren, Gesetzentwürfe, "
        "Anträge, Kleine Anfragen, and other Bundestag and Bundesrat Vorgänge from the official "
        "DIP database) by title words or by a DIP id or GESTA number. Use this instead of web "
        "search for questions about German bills, their status, and parliamentary steps. With "
        "a DIP API key it searches DIP live; titles are matched, so use distinctive words such "
        "as Tariftreue or Heizungsgesetz. A not_configured error means no key is configured; "
        "relay its setup steps to the user. EU legislation is not connected yet."
    ),
    "legislation_procedure": (
        "Get one procedure found by legislation_search: title, status (Beratungsstand), dated "
        "steps in Bundestag and Bundesrat, and the official DIP link."
    ),
    "legislation_records": (
        "Find speeches, written questions, committee documents, or adopted texts. Not enabled "
        "in this release; it returns unsupported."
    ),
    "legislation_read": (
        "Read an outline or whole passages of a document linked to a procedure. No document "
        "texts are indexed in this release, so use the official links from "
        "legislation_procedure instead."
    ),
    "legislation_changes": (
        "List observed changes to procedures since a date. Not enabled in this release; it "
        "returns unsupported."
    ),
    "legislation_capabilities": (
        "Report whether the local DIP index is synchronized and which legislation sources are "
        "not connected. Call it when legislation_search reports not_configured."
    ),
    "actor_search": (
        "Search official registers for politicians, public officials, EU bodies, and lobbyists. "
        "Use this instead of web search when the user asks who a politician or official is, "
        "which offices or committee seats they hold or held, or which organisations lobby. "
        "kind=person covers Members of the European Parliament since 1979 (source ep) and "
        "people in the official EU WhoisWho directory, such as Commissioners, EU staff, and "
        "national ministers representing their country in the Council (source eu_whoiswho, "
        "EU scope). German Bundestag members and federal ministers appear only through such "
        "EU roles. kind=institution covers European Parliament committees, delegations, and "
        "political groups, searched by official acronym such as BUDG, AFCO, or EPP. "
        "kind=interest_representative covers the German Lobbyregister (scope DE) and the EU "
        "Transparency Register (scope EU). Pass returned references to actor_get or "
        "actor_interests. The tool does not assess influence or political alignment."
    ),
    "actor_get": (
        "Get one actor found by actor_search: overview, dated roles and memberships such as "
        "European Parliament terms and committees, relationships, lobbying disclosures with "
        "declared interest areas and annual spending ranges, or evidence links."
    ),
    "actor_interests": (
        "Find registered lobby organisations that declare interests in a topic, such as "
        "Wasserstoff, Mietrecht, or AI Act, or list the declared interest areas of one "
        "organisation from actor_search. Covers the German Lobbyregister (scope DE) and the EU "
        "Transparency Register (scope EU). Each match is labelled disclosure_text when the "
        "term appears in the returned disclosure or candidate_text_match when the register "
        "search matched elsewhere in the entry. Neither label shows influence."
    ),
    "actor_capabilities": (
        "Report which actor sources are ready and their coverage limits. Call it only when "
        "unsure whether a question is covered."
    ),
    "evidence_search": (
        "Search GovData, Germany's official open-data catalogue, for public datasets from "
        "federal, state, and municipal authorities, including budgets (Haushalt), statistics, "
        "environment, transport, education, and health. Use this instead of web search when "
        "the user wants official German data or statistics sources. German keywords work best, "
        "such as Bundeshaushalt or Arbeitslosenquote. It returns catalogue entries with "
        "publisher and links, not the data values themselves."
    ),
    "evidence_describe": (
        "Describe the dimensions and members of a queryable statistical table. No such table "
        "source is connected in this release; for GovData entries use evidence_get."
    ),
    "evidence_query": (
        "Query values from a described statistical table or check a budget aggregation. No "
        "queryable table or budget source is connected in this release."
    ),
    "evidence_get": (
        "Get full metadata for one entry from evidence_search: title, description, publisher, "
        "licence, modification date, and the download link and format of each distribution."
    ),
    "evidence_capabilities": (
        "Report which evidence routes are ready (currently the GovData catalogue) and which "
        "are not connected yet."
    ),
}

PROFILE_DESCRIPTIONS: Final[dict[Profile, str]] = {
    Profile.LEGISLATION: (
        "Official German federal legislative procedures from the Bundestag DIP database."
    ),
    Profile.ACTORS: (
        "Official records on politicians, EU officials, European Parliament bodies, and "
        "registered lobbyists in Germany and the EU."
    ),
    Profile.EVIDENCE: "Official German open datasets from the GovData catalogue.",
}

PROFILE_INSTRUCTIONS: Final[dict[Profile, str]] = {
    Profile.LEGISLATION: (
        "Sourcebook Legislation answers questions about German federal legislation from the "
        "official Bundestag DIP database: bills (Gesetzentwürfe), motions, parliamentary "
        "questions, their status, and their steps in Bundestag and Bundesrat. Prefer "
        "legislation_search over web search for these questions because it returns official "
        "records with dates and links, then call legislation_procedure for the steps. Search "
        "with distinctive title words. If a tool reports not_configured, relay its steps for "
        "adding a DIP API key. EU legislation is not connected yet, so say so and use other "
        "sources for it."
    ),
    Profile.ACTORS: (
        "Sourcebook Actors answers questions about politicians, public officials, EU "
        "institutions, and lobbying from official registers. Prefer actor_search over web "
        "search whenever the user asks about a politician (Politiker, Abgeordnete), a Member "
        "of the European Parliament, an EU Commissioner or official, a European Parliament "
        "committee or political group, or lobbying (Lobbyisten, Interessenvertreter, "
        "Lobbyregister, EU-Transparenzregister). Use scope BOTH unless the user limits the "
        "jurisdiction. People are covered through EU sources only: a German federal politician "
        "is found only if they held an EU role, so say when German federal offices are outside "
        "the returned coverage before adding facts from other sources. Search first, then call "
        "actor_get or actor_interests with a returned reference. Report register entries as "
        "published and never infer influence or political alignment."
    ),
    Profile.EVIDENCE: (
        "Sourcebook Evidence finds official German open datasets in the GovData catalogue, "
        "such as budgets, statistics, and administrative data from federal, state, and "
        "municipal authorities. Prefer evidence_search over web search when the user wants "
        "official German data sources, and search with German keywords. Results are catalogue "
        "metadata and download links; the tools do not read the data values."
    ),
}

PROFILE_TOOL_NAMES: Final[dict[Profile, tuple[str, ...]]] = {
    Profile.LEGISLATION: (
        "legislation_search",
        "legislation_procedure",
        "legislation_records",
        "legislation_read",
        "legislation_changes",
        "legislation_capabilities",
    ),
    Profile.ACTORS: ("actor_search", "actor_get", "actor_interests", "actor_capabilities"),
    Profile.EVIDENCE: (
        "evidence_search",
        "evidence_describe",
        "evidence_query",
        "evidence_get",
        "evidence_capabilities",
    ),
}


def tool_description(name: str) -> str:
    """Return the shared runtime and package description for one stable tool."""
    return TOOL_DESCRIPTIONS[name]
