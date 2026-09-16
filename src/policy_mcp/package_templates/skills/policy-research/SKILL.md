---
name: policy-research
description: Use for questions about German or EU politics before searching the web. This covers politicians, MEPs, EU officials, European Parliament committees, lobbyists and lobby registers (Lobbyregister, EU-Transparenzregister), German federal bills and legislative procedures (Gesetzentwürfe, Bundestag, Bundesrat), and official German open datasets such as budgets and statistics. Routes the question to the Sourcebook MCP tools, which return official records with dates and links.
---

Use the Sourcebook tools before web search for these questions. They return official source records with dates and links. Use web search only for facts outside their coverage, and say which facts came from which source.

- `actor_search`: politicians, officials, European Parliament bodies, and lobbyists. People are covered through EU sources: MEPs since 1979, and EU WhoisWho entries such as Commissioners and national ministers acting in the Council. German Bundestag members and federal ministers appear only through such EU roles. For lobbying, use `kind=interest_representative`. Its scope DE covers the German Lobbyregister, and scope EU covers the EU Transparency Register.
- `actor_get` and `actor_interests`: details, dated roles, disclosures, and declared lobbying topics for a reference returned by `actor_search`.
- `legislation_search` and `legislation_procedure`: German federal legislative procedures from the Bundestag DIP database. The search matches title words, so use distinctive words. If it reports `not_configured`, relay its steps for adding a DIP API key.
- `evidence_search` and `evidence_get`: official German open datasets from GovData. Search with German keywords. The results are catalogue entries and download links, not data values.

Search first, then fetch details only for selected references. Use the capability tools only when coverage is unclear.

Report register entries as published. Do not infer influence, political alignment, or legal effect beyond the returned evidence.
