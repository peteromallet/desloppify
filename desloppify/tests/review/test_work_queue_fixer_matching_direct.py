"""Direct tests for matching autofix hints to issue subtypes."""

from __future__ import annotations

import desloppify.app.commands.next.render as render_mod
from desloppify.engine._work_queue.helpers import primary_command_for_issue
from desloppify.engine._work_queue.ranking import build_issue_items

_SUPPORTED_SMELL_FIXERS = {"dead-useeffect", "empty-if-chain"}


def test_smell_issue_only_suggests_its_matching_fixer() -> None:
    dead_effect = {
        "id": "smells::src/view.ts::dead_useeffect",
        "detector": "smells",
        "detail": {"smell_id": "dead_useeffect"},
    }
    hardcoded_url = {
        "id": "smells::src/assets.ts::hardcoded_url",
        "detector": "smells",
        "detail": {"smell_id": "hardcoded_url"},
    }

    assert primary_command_for_issue(
        dead_effect, supported_fixers=_SUPPORTED_SMELL_FIXERS
    ) == "desloppify autofix dead-useeffect --dry-run"
    assert primary_command_for_issue(
        hardcoded_url, supported_fixers=_SUPPORTED_SMELL_FIXERS
    ) == 'desloppify plan resolve "smells::src/assets.ts::hardcoded_url" --note "<what you did>" --confirm'
    assert not render_mod.fixer_matches_issue(
        {"detector": "unregistered_detector"}, "dead-useeffect"
    )


def test_queue_marks_unmatched_smell_manual_and_keeps_matching_fixer() -> None:
    issues = {
        "smells::src/assets.ts::hardcoded_url": {
            "id": "smells::src/assets.ts::hardcoded_url",
            "detector": "smells",
            "file": "src/assets.ts",
            "detail": {"smell_id": "hardcoded_url"},
            "status": "open",
            "confidence": "medium",
            "tier": 2,
            "lang": "typescript",
        },
        "smells::src/view.ts::dead_useeffect": {
            "id": "smells::src/view.ts::dead_useeffect",
            "detector": "smells",
            "file": "src/view.ts",
            "detail": {"smell_id": "dead_useeffect"},
            "status": "open",
            "confidence": "medium",
            "tier": 2,
            "lang": "typescript",
        },
    }
    items = build_issue_items(
        {
            "work_items": issues,
            "lang_capabilities": {
                "typescript": {"fixers": sorted(_SUPPORTED_SMELL_FIXERS)}
            },
        },
        scan_path=None,
        status_filter="open",
        scope=None,
        chronic=False,
    )

    by_id = {item["id"]: item for item in items}
    url_item = by_id["smells::src/assets.ts::hardcoded_url"]
    effect_item = by_id["smells::src/view.ts::dead_useeffect"]
    assert url_item["action_type"] == "manual_fix"
    assert "autofix" not in url_item["primary_command"]
    assert effect_item["action_type"] == "auto_fix"
    assert effect_item["primary_command"] == "desloppify autofix dead-useeffect --dry-run"


def test_batch_hint_counts_only_the_matched_smell_subtype(capsys) -> None:
    item = {
        "detector": "smells",
        "detail": {"smell_id": "dead_useeffect"},
        "action_type": "auto_fix",
        "primary_command": "desloppify autofix dead-useeffect --dry-run",
    }
    issues = {
        "smells::a::effect": {
            "detector": "smells",
            "detail": {"smell_id": "dead_useeffect"},
            "status": "open",
        },
        "smells::b::effect": {
            "detector": "smells",
            "detail": {"smell_id": "dead_useeffect"},
            "status": "open",
        },
        "smells::c::url": {
            "detector": "smells",
            "detail": {"smell_id": "hardcoded_url"},
            "status": "open",
        },
    }

    render_mod._render_auto_fix_batch_hint(item, issues)

    assert "Auto-fixable: 2 similar issues" in capsys.readouterr().out
