"""TypeScript smells phase runner."""

from __future__ import annotations

from pathlib import Path

from desloppify.base.output.terminal import log
from desloppify.engine._state.filtering import make_issue
from desloppify.engine.policy.zones import adjust_potential
from desloppify.languages._framework.base.smell_contracts import (
    normalize_smell_entries,
)
from desloppify.languages._framework.base.types import LangRuntimeContract
from desloppify.languages._framework.issue_factories import make_smell_issues
import desloppify.languages.typescript.detectors.react.context as react_context_mod
import desloppify.languages.typescript.detectors.react.hook_bloat as react_hook_bloat_mod
import desloppify.languages.typescript.detectors.react.state_sync as react_state_sync_mod
import desloppify.languages.typescript.detectors.smells as smells_detector_mod
from desloppify.languages.typescript.frameworks import detect_primary_ts_framework
from desloppify.languages.typescript.frameworks.nextjs import nextjs_info_from_detection
from desloppify.languages.typescript.frameworks.nextjs.phase import detect_nextjs_framework_smells
from desloppify.state_io import Issue


def phase_smells(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
    smell_entries, total_smell_files = smells_detector_mod.detect_smells(path)
    normalized_smells = normalize_smell_entries(smell_entries)
    results = make_smell_issues(
        [entry.to_mapping() for entry in normalized_smells],
        log,
    )

    react_entries, total_effects = react_state_sync_mod.detect_state_sync(path)
    for entry in react_entries:
        setter_str = ", ".join(entry["setters"])
        results.append(
            make_issue(
                "react",
                entry["file"],
                setter_str,
                tier=3,
                confidence="medium",
                summary=f"State sync anti-pattern: useEffect only calls {setter_str}",
                detail={"line": entry["line"], "setters": entry["setters"]},
            )
        )
    if react_entries:
        log(f"         react: {len(react_entries)} state sync anti-patterns")

    nesting_entries, _ = react_context_mod.detect_context_nesting(path)
    for entry in nesting_entries:
        providers_str = " → ".join(entry["providers"][:5])
        results.append(
            make_issue(
                "react",
                entry["file"],
                f"nesting::{entry['depth']}",
                tier=3,
                confidence="medium",
                summary=f"Deep provider nesting ({entry['depth']} levels): {providers_str}",
                detail={"depth": entry["depth"], "providers": entry["providers"]},
            )
        )
    if nesting_entries:
        log(f"         react: {len(nesting_entries)} deep provider nesting")

    hook_entries, _ = react_hook_bloat_mod.detect_hook_return_bloat(path)
    for entry in hook_entries:
        results.append(
            make_issue(
                "react",
                entry["file"],
                f"hook_bloat::{entry['hook']}",
                tier=3,
                confidence="medium",
                summary=f"Hook return bloat: {entry['hook']} returns {entry['field_count']} fields",
                detail={
                    "hook": entry["hook"],
                    "field_count": entry["field_count"],
                    "line": entry["line"],
                },
            )
        )
    if hook_entries:
        log(f"         react: {len(hook_entries)} bloated hook returns")

    bool_entries, _ = react_hook_bloat_mod.detect_boolean_state_explosion(path)
    for entry in bool_entries:
        states_str = ", ".join(entry["states"][:5])
        results.append(
            make_issue(
                "react",
                entry["file"],
                f"bool_state::{entry['prefix']}",
                tier=3,
                confidence="low",
                summary=(
                    f"Boolean state explosion: {entry['count']} boolean useState hooks "
                    f"({states_str})"
                ),
                detail={
                    "count": entry["count"],
                    "setters": entry["setters"],
                    "states": entry["states"],
                    "line": entry["line"],
                },
            )
        )
    if bool_entries:
        log(f"         react: {len(bool_entries)} boolean state explosions")

    framework = detect_primary_ts_framework(path, lang)
    nextjs_info = nextjs_info_from_detection(framework)
    nextjs_scanned = 0
    next_lint_potential = 0
    if nextjs_info.is_primary:
        scan_root = nextjs_info.package_root
        nextjs_issues, nextjs_potentials = detect_nextjs_framework_smells(
            scan_root, nextjs_info, log
        )
        results.extend(nextjs_issues)
        nextjs_scanned = nextjs_potentials.get("nextjs", 0)
        next_lint_potential = nextjs_potentials.get("next_lint", 0)

    potentials: dict[str, int] = {
        "smells": adjust_potential(lang.zone_map, total_smell_files),
        "react": total_effects,
    }
    if nextjs_scanned > 0:
        potentials["nextjs"] = nextjs_scanned
    if next_lint_potential > 0:
        potentials["next_lint"] = next_lint_potential

    return results, potentials


__all__ = ["phase_smells"]
