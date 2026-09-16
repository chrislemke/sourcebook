"""Versioned deterministic routing evaluation contracts and runner."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

NonEmptyString = Annotated[str, Field(min_length=1)]


class RoutingCase(BaseModel):
    """One frozen prompt and its expected public routing behavior."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: NonEmptyString
    language: Literal["de", "en"]
    profile: Literal["legislation", "actors", "evidence", "unsupported"]
    prompt: NonEmptyString
    ambiguous: bool = False
    expected_first_tool: str | None
    expected_route: str | None
    documented_operations: tuple[NonEmptyString, ...]
    required_warnings: tuple[NonEmptyString, ...]
    evidence_references_required: bool


class RoutingCorpus(BaseModel):
    """A complete, immutable routing evaluation data set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_version: Literal[1]
    documented_operations: frozenset[NonEmptyString]
    cases: tuple[RoutingCase, ...]


class RoutingDecision(BaseModel):
    """The observable decision emitted by a deterministic router."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    first_tool: str | None
    route: str | None
    operations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence_reference_count: Annotated[int, Field(ge=0)] = 0


class EvaluationReport(BaseModel):
    """Separate routing-quality and provider-contract measurements."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_cases: int
    scored_cases: int
    correct_first_tool: int
    first_tool_accuracy: float
    correct_route: int
    route_accuracy: float
    undocumented_operation_count: int
    undocumented_operations: tuple[str, ...]
    missing_warning_count: int
    missing_warning_cases: tuple[str, ...]
    missing_evidence_reference_count: int
    missing_evidence_reference_cases: tuple[str, ...]
    release_gate_passed: bool


def load_corpus(path: Path) -> RoutingCorpus:
    """Load and validate the versioned JSON evaluation corpus."""
    corpus = RoutingCorpus.model_validate_json(path.read_text())
    case_ids = [case.id for case in corpus.cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("evaluation case ids must be unique")
    if len(corpus.cases) != 60:
        raise ValueError("routing corpus v1 must contain exactly 60 cases")
    expected_profiles = {
        "legislation": 20,
        "actors": 15,
        "evidence": 15,
        "unsupported": 10,
    }
    if Counter(case.profile for case in corpus.cases) != expected_profiles:
        raise ValueError(f"routing corpus v1 must use profile split {expected_profiles}")
    if Counter(case.language for case in corpus.cases) != {"de": 30, "en": 30}:
        raise ValueError("routing corpus v1 must contain 30 German and 30 English prompts")
    for case in corpus.cases:
        if not case.ambiguous and (not case.expected_first_tool or not case.expected_route):
            raise ValueError(f"unambiguous case {case.id} requires a tool and route")
        if case.ambiguous and (
            case.expected_first_tool is not None or case.expected_route is not None
        ):
            raise ValueError(f"ambiguous case {case.id} cannot require a tool or route")
        unknown = set(case.documented_operations) - corpus.documented_operations
        if unknown:
            raise ValueError(f"case {case.id} declares undocumented operations: {sorted(unknown)}")
    return corpus


def run_evaluation(
    corpus: RoutingCorpus,
    decisions: Mapping[str, RoutingDecision],
) -> EvaluationReport:
    """Measure routing, warnings, evidence, and provider-operation release gates."""
    expected_ids = {case.id for case in corpus.cases}
    if set(decisions) != expected_ids:
        missing = sorted(expected_ids - set(decisions))
        unexpected = sorted(set(decisions) - expected_ids)
        raise ValueError(
            f"decisions must cover the corpus; missing={missing}, unexpected={unexpected}"
        )

    scored = [case for case in corpus.cases if not case.ambiguous]
    correct = sum(decisions[case.id].first_tool == case.expected_first_tool for case in scored)
    correct_route = sum(decisions[case.id].route == case.expected_route for case in scored)
    undocumented_occurrences = [
        operation
        for decision in decisions.values()
        for operation in decision.operations
        if operation not in corpus.documented_operations
    ]
    undocumented = sorted(set(undocumented_occurrences))
    missing_warning_cases = tuple(
        case.id
        for case in corpus.cases
        if set(case.required_warnings) - set(decisions[case.id].warnings)
    )
    missing_warning_count = sum(
        len(set(case.required_warnings) - set(decisions[case.id].warnings)) for case in corpus.cases
    )
    missing_evidence_cases = tuple(
        case.id
        for case in corpus.cases
        if case.evidence_references_required and decisions[case.id].evidence_reference_count == 0
    )
    first_tool_accuracy = correct / len(scored) if scored else 0.0
    route_accuracy = correct_route / len(scored) if scored else 0.0
    return EvaluationReport(
        total_cases=len(corpus.cases),
        scored_cases=len(scored),
        correct_first_tool=correct,
        first_tool_accuracy=first_tool_accuracy,
        correct_route=correct_route,
        route_accuracy=route_accuracy,
        undocumented_operation_count=len(undocumented_occurrences),
        undocumented_operations=tuple(undocumented),
        missing_warning_count=missing_warning_count,
        missing_warning_cases=missing_warning_cases,
        missing_evidence_reference_count=len(missing_evidence_cases),
        missing_evidence_reference_cases=missing_evidence_cases,
        release_gate_passed=(
            first_tool_accuracy >= 0.95
            and route_accuracy >= 0.95
            and not undocumented_occurrences
            and not missing_warning_cases
            and not missing_evidence_cases
        ),
    )
