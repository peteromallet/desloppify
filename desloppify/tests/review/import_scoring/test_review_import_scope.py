"""Regression coverage for scan scope surviving review imports."""

from __future__ import annotations

from argparse import Namespace

import pytest

from desloppify.base.runtime_state import runtime_scope
from desloppify.cli import _resolve_default_path
from desloppify.intelligence.review import import_holistic_issues, import_review_issues
from desloppify.state import MergeScanOptions, empty_state, merge_scan
from desloppify.state_io import load_state, save_state


@pytest.mark.parametrize(
    "import_review", [import_holistic_issues, import_review_issues]
)
@pytest.mark.parametrize("scan_path", [".", "packages/app", None])
@pytest.mark.parametrize("assessment_only", [False, True])
def test_review_import_preserves_scope_for_later_review(
    tmp_path, import_review, scan_path, assessment_only
):
    # A src directory makes scope loss fall back to a different scan target.
    (tmp_path / "src").mkdir()
    (tmp_path / "packages" / "app").mkdir(parents=True)
    state_file = tmp_path / "state-typescript.json"
    state = empty_state()
    payload = {
        "issues": []
        if assessment_only
        else [
            {
                "file": "packages/app/service.ts",
                "dimension": "naming_quality",
                "identifier": "vague_service_name",
                "summary": "Service name does not describe its responsibility",
                "related_files": ["packages/app/service.ts"],
                "evidence": [
                    "The service uses a generic name for a specific operation."
                ],
                "suggestion": "Name the service after the operation it performs.",
                "confidence": "high",
            }
        ],
        "assessments": {"naming_quality": 72},
    }

    with runtime_scope() as runtime:
        runtime.project_root = tmp_path
        merge_scan(
            state, [], options=MergeScanOptions(lang="typescript", scan_path=scan_path)
        )
        # A partial retry import must not erase the scope before import-run replay.
        for _ in range(2):
            import_review(payload, state, "typescript")
            save_state(state, state_file)
            state = load_state(state_file)
            assert state["scan_path"] == scan_path

        args = Namespace(
            command="review", path=None, state=str(state_file), lang="typescript"
        )
        _resolve_default_path(args)

    expected_path = tmp_path / (scan_path if scan_path is not None else "src")
    assert args.path == str(expected_path.resolve())
