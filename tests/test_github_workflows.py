"""Static checks for the public GitHub validation and release workflows."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PINNED_ACTION = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def _load(name: str) -> dict[str, Any]:
    payload = yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)
    assert isinstance(payload, dict)
    return payload


def _action_references(value: Any) -> list[str]:
    if isinstance(value, dict):
        references = []
        for key, child in value.items():
            if key == "uses" and isinstance(child, str):
                references.append(child)
            references.extend(_action_references(child))
        return references
    if isinstance(value, list):
        return [reference for child in value for reference in _action_references(child)]
    return []


def test_all_actions_are_pinned_to_immutable_commits() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        workflow = _load(path.name)
        for reference in _action_references(workflow):
            assert PINNED_ACTION.fullmatch(reference), f"Unpinned action in {path}: {reference}"


def test_package_validation_covers_both_release_targets() -> None:
    workflow = _load("package-proof.yml")
    targets = {
        entry["target"] for entry in workflow["jobs"]["package"]["strategy"]["matrix"]["include"]
    }

    assert workflow["permissions"] == {"contents": "read"}
    assert targets == {"darwin-arm64", "windows-x64"}


def test_release_runs_on_main_and_has_one_narrow_write_permission() -> None:
    workflow = _load("release.yml")
    release_job = workflow["jobs"]["release"]

    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}
    assert release_job["permissions"] == {"contents": "write"}
    assert set(release_job["needs"]) == {"package", "python-distribution"}


def test_release_validates_packages_before_publishing() -> None:
    workflow_text = (WORKFLOWS / "release.yml").read_text()

    assert "tests/test_release_artifacts.py" in workflow_text
    assert "gh release create" in workflow_text
    assert "SHA256SUMS" in workflow_text
