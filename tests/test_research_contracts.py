"""Shared response-envelope budget contracts."""

from policy_mcp.research_contracts import (
    MAX_RESULT_BYTES,
    CapabilitiesResponse,
    ResearchStatus,
    ResearchWarning,
    fit_response,
)


def test_mandatory_oversize_becomes_a_compact_typed_error() -> None:
    response = CapabilitiesResponse(
        status=ResearchStatus.OK,
        warnings=[ResearchWarning(code="provider", message="x" * (MAX_RESULT_BYTES + 4_000))],
    )

    fitted = fit_response(response, [])

    assert fitted.status == ResearchStatus.ERROR
    assert fitted.error is not None
    assert fitted.error.code == "oversized"
    assert len(fitted.model_dump_json().encode()) <= MAX_RESULT_BYTES
