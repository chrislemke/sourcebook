"""Public contract tests for the versioned source registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from policy_mcp.registry import RouteState, load_registry


def test_repository_registry_has_required_metadata_and_route_states() -> None:
    registry = load_registry(Path("config/sources.yaml"))

    assert registry.registry_version == 1
    assert registry.issues == ()
    assert set(registry.sources) == {
        "bundestag_open_data",
        "cellar",
        "comitology",
        "de_budget",
        "dip",
        "ep",
        "eu_transparency",
        "eu_whoiswho",
        "eurlex",
        "funding_tenders",
        "genesis",
        "gesetze_im_internet",
        "govdata",
        "lobbyregister",
        "ted",
    }
    for source in registry.sources.values():
        assert source.allowed_hosts
        assert source.credential_transport in {
            "none",
            "os_keyring",
            "environment",
            "os_keyring_or_environment",
        }
        assert source.fixture_hashes is not None
        assert source.licence.name
        assert source.attribution
        assert source.date_bases
        assert source.pagination.kind
        assert source.refresh_policy.cadence
        assert source.supported_languages
        assert source.coverage_limits
        assert source.parser_version
        assert source.routes
        for route in source.routes.values():
            assert route.allowed_operations
            assert isinstance(route.state, RouteState)


def test_invalid_route_fails_closed_without_disabling_its_sibling(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sources.yaml"
    path.write_text(
        """
registry_version: 1
policy:
  no_fee_sources_only: true
  public_read_only: true
  default_search_limit: 5
  interactive_max_provider_requests: 6
sources:
  example:
    adapter: ExampleAdapter
    transport: rest
    allowed_hosts: [example.test]
    credential_transport: none
    fixture_hashes: {}
    licence: {name: public, url: "https://example.test/licence"}
    attribution: Example publisher
    date_bases: [published_at]
    pagination: {kind: cursor, stable: true}
    refresh_policy: {cadence: hourly, freshness_threshold: PT2H}
    supported_languages: [en]
    language_fallback: explicit_only
    coverage_limits: Test fixture only.
    parser_version: "1"
    routes:
      working:
        state: warming
        allowed_operations: [search]
        enable_after: [schema_pin]
      broken:
        state: healthy
        allowed_operations: [search]
        enable_after: [schema_pin]
        undocumented_field: rejected
""".strip()
        + "\n"
    )

    registry = load_registry(path)

    assert registry.route("example", "working").state is RouteState.WARMING
    assert registry.route("example", "broken").state is RouteState.SCHEMA_CHANGED
    assert registry.route("example", "broken").definition is None
    assert len(registry.issues) == 1
    assert registry.issues[0].source_id == "example"
    assert registry.issues[0].route_id == "broken"


def test_registry_rejects_an_unsupported_registry_version(tmp_path: Path) -> None:
    path = tmp_path / "sources.yaml"
    path.write_text("registry_version: 2\npolicy: {}\nsources: {}\n")

    with pytest.raises(ValueError, match="registry_version"):
        load_registry(path)
