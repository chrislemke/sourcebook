"""Public contract tests for the deterministic routing evaluation runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from policy_mcp.evaluation import RoutingDecision, load_corpus, run_evaluation


def test_repository_corpus_is_versioned_bilingual_and_balanced() -> None:
    corpus = load_corpus(Path("evals/routing-v1.json"))

    assert corpus.corpus_version == 1
    assert len(corpus.cases) == 60
    assert {
        language: sum(case.language == language for case in corpus.cases)
        for language in ("de", "en")
    } == {"de": 30, "en": 30}
    assert {
        profile: sum(case.profile == profile for case in corpus.cases)
        for profile in (
            "legislation",
            "actors",
            "evidence",
            "unsupported",
        )
    } == {"legislation": 20, "actors": 15, "evidence": 15, "unsupported": 10}
    assert len({case.id for case in corpus.cases}) == 60
    assert all(case.expected_route for case in corpus.cases if not case.ambiguous)
    assert all(case.expected_first_tool for case in corpus.cases if not case.ambiguous)


def test_runner_reports_first_tool_accuracy_and_undocumented_operations_separately() -> None:
    corpus = load_corpus(Path("evals/routing-v1.json"))
    decisions: dict[str, RoutingDecision] = {}
    for case in corpus.cases:
        decisions[case.id] = RoutingDecision(
            first_tool=case.expected_first_tool,
            route=case.expected_route,
            operations=case.documented_operations,
            warnings=case.required_warnings,
            evidence_reference_count=1 if case.evidence_references_required else 0,
        )

    first_scored = next(case for case in corpus.cases if not case.ambiguous)
    decisions[first_scored.id] = RoutingDecision(
        first_tool="policy_diagnostic",
        route=first_scored.expected_route,
        operations=(*first_scored.documented_operations, "private.search"),
        warnings=first_scored.required_warnings,
        evidence_reference_count=1 if first_scored.evidence_references_required else 0,
    )

    report = run_evaluation(corpus, decisions)

    assert report.scored_cases == sum(not case.ambiguous for case in corpus.cases)
    assert report.correct_first_tool == report.scored_cases - 1
    assert report.first_tool_accuracy == pytest.approx(
        (report.scored_cases - 1) / report.scored_cases
    )
    assert report.undocumented_operation_count == 1
    assert report.undocumented_operations == ("private.search",)
    assert report.route_accuracy == 1.0
    assert report.release_gate_passed is False


def test_ambiguous_cases_do_not_reduce_first_tool_accuracy() -> None:
    corpus = load_corpus(Path("evals/routing-v1.json"))
    decisions = {
        case.id: RoutingDecision(
            first_tool=case.expected_first_tool if not case.ambiguous else None,
            route=case.expected_route if not case.ambiguous else None,
            operations=case.documented_operations,
            warnings=case.required_warnings,
            evidence_reference_count=1 if case.evidence_references_required else 0,
        )
        for case in corpus.cases
    }

    report = run_evaluation(corpus, decisions)

    assert report.first_tool_accuracy == 1.0
    assert report.undocumented_operation_count == 0
    assert report.missing_warning_count == 0
    assert report.missing_evidence_reference_count == 0
    assert report.release_gate_passed is True


def test_runner_reports_route_warning_and_reference_failures() -> None:
    corpus = load_corpus(Path("evals/routing-v1.json"))
    decisions = {
        case.id: RoutingDecision(
            first_tool=case.expected_first_tool if not case.ambiguous else None,
            route="wrong.route" if not case.ambiguous else None,
            operations=case.documented_operations,
        )
        for case in corpus.cases
    }

    report = run_evaluation(corpus, decisions)

    assert report.route_accuracy == 0.0
    assert report.missing_warning_count > 0
    assert report.missing_evidence_reference_count > 0
    assert report.release_gate_passed is False
