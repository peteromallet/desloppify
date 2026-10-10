"""A successful review import must respect the scan queue guard."""

from __future__ import annotations

import subprocess
import sys

from desloppify.app.commands.review.runner_process_impl.types import FollowupScanDeps
from desloppify.app.commands.runner.codex_batch import run_followup_scan
from desloppify.engine._plan.persistence import save_plan
from desloppify.engine._plan.schema import empty_plan
from desloppify.state import empty_state, save_state


def test_followup_scan_defers_when_imported_review_work_remains(
    set_project_root, capsys
) -> None:
    project_root = set_project_root
    review_id = "review::src/example.py::naming"
    state = empty_state()
    state["work_items"][review_id] = {
        "id": review_id,
        "detector": "review",
        "file": "src/example.py",
        "status": "open",
        "tier": 3,
        "confidence": "high",
        "summary": "Ambiguous helper name",
        "detail": {"dimension": "naming_quality"},
    }
    state_path = project_root / ".desloppify" / "state-python.json"
    save_state(state, state_path)
    plan = empty_plan()
    plan["queue_order"] = [review_id]
    plan["plan_start_scores"] = {"strict": 75.0}
    plan["refresh_state"] = {"lifecycle_phase": "execute"}
    plan_path = state_path.parent / "plan.json"
    save_plan(plan, plan_path)
    state_before = state_path.read_bytes()
    plan_before = plan_path.read_bytes()

    code = run_followup_scan(
        lang_name="python",
        scan_path=".",
        deps=FollowupScanDeps(
            project_root=project_root,
            timeout_seconds=10,
            python_executable=sys.executable,
            subprocess_run=subprocess.run,
            timeout_error=subprocess.TimeoutExpired,
            colorize_fn=lambda text, _tone: text,
        ),
    )

    assert code == 0
    assert "Follow-up scan deferred" in capsys.readouterr().out
    assert state_path.read_bytes() == state_before
    assert plan_path.read_bytes() == plan_before
