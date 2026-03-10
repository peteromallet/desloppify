"""Direct coverage for defer-policy and scan-scope helpers."""

from __future__ import annotations

import desloppify.engine._plan.sync.defer_policy as defer_policy_mod
import desloppify.engine._state.scope as scope_mod


def test_defer_policy_updates_counts_and_escalates_by_scan_or_time() -> None:
    state = {"scan_count": 4, "last_scan": "2026-03-10T12:00:00+00:00"}

    created = defer_policy_mod.update_defer_state(
        None,
        state=state,
        deferred_ids={" review::b ", "review::a", ""},
    )
    assert created["deferred_ids"] == ["review::a", "review::b"]
    assert created["defer_count"] == 1
    assert created["first_deferred_scan"] == 4

    repeated = defer_policy_mod.update_defer_state(
        created,
        state={"scan_count": 5, "last_scan": "2026-03-11T12:00:00+00:00"},
        deferred_ids={"review::a", "review::b"},
    )
    assert repeated["defer_count"] == 2
    assert repeated["first_deferred_scan"] == 4

    assert defer_policy_mod.should_escalate_defer_state(
        {
            "deferred_ids": ["review::a"],
            "defer_count": 3,
            "first_deferred_scan": 2,
            "first_deferred_at": "2026-03-01T00:00:00+00:00",
        },
        state={"scan_count": 4, "last_scan": "2026-03-10T00:00:00+00:00"},
    )
    assert defer_policy_mod.should_escalate_defer_state(
        {
            "deferred_ids": ["review::a"],
            "defer_count": 1,
            "first_deferred_scan": 2,
            "first_deferred_at": "2026-03-01T00:00:00+00:00",
        },
        state={"scan_count": 4, "last_scan": "2026-03-10T00:00:00+00:00"},
    )
    assert not defer_policy_mod.should_escalate_defer_state(
        {
            "deferred_ids": ["review::a"],
            "defer_count": 1,
            "first_deferred_scan": 4,
            "first_deferred_at": "2026-03-10T00:00:00+00:00",
        },
        state={"scan_count": 4, "last_scan": "2026-03-10T12:00:00+00:00"},
        options=defer_policy_mod.DeferEscalationOptions(min_scans=5, min_days=10),
    )


def test_scope_helpers_filter_and_break_down_open_issues() -> None:
    issues = {
        "in": {"file": "src/app.py", "status": "open", "detector": "unused"},
        "exact": {"file": "src", "status": "open", "detector": "unused"},
        "holistic": {"file": ".", "status": "open", "detector": "unused"},
        "out": {"file": "tests/test_app.py", "status": "open", "detector": "unused"},
        "closed": {"file": "src/closed.py", "status": "fixed", "detector": "unused"},
        "suppressed": {
            "file": "src/suppressed.py",
            "status": "open",
            "detector": "unused",
            "suppressed": True,
        },
    }

    assert scope_mod.issue_in_scan_scope("src/app.py", "src")
    assert scope_mod.issue_in_scan_scope(".", "src")
    assert not scope_mod.issue_in_scan_scope("tests/test_app.py", "src")

    scoped = scope_mod.path_scoped_issues(issues, "src")
    assert set(scoped) == {"in", "exact", "holistic", "closed", "suppressed"}

    breakdown = scope_mod.open_scope_breakdown(issues, "src", detector="unused")
    assert breakdown == {"in_scope": 3, "out_of_scope": 1, "global": 4}
