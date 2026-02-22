"""Pattern consistency analysis: flag areas with competing approaches to the same problem.

Key design principle: Complementary patterns (layers) are NOT fragmentation.
- handleError wraps console.error + toast.error → having all 3 is healthy
- useQuery (reads) + useMutation (writes) + supabase.from (one-offs) → different layers
- Loader2 (spinner) + Skeleton (placeholder) → different UX contexts

Only COMPETING patterns (multiple approaches to the same decision) are flagged:
- useAutoSaveSettings vs usePersistentToolState vs useToolSettings → same problem,
  different tradeoffs. An area using 2+ suggests fragmentation or migration debt.

All families are included in the census (raw `detect patterns` command shows everything).
Only competing families produce findings for the scan pipeline.
"""

import argparse
import json
import logging
import re
from collections import defaultdict
from pathlib import Path

from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.languages.typescript.detectors.contracts import DetectorResult
from desloppify.file_discovery import rel, resolve_path
from desloppify.file_discovery import find_ts_files
from desloppify.utils import (
    colorize,
    get_area,
    print_table,
)

# ── Pattern families ────────────────────────────────────────────
#
# type="competing": These patterns solve the SAME problem with different approaches.
#   Fragmentation = area uses >= threshold patterns from this family.
#   Outlier = area uses a pattern adopted by <10% of areas.
#
# type="complementary": These patterns are intentional layers, not alternatives.
#   No fragmentation detection. Shown in census for landscape overview only.

PATTERN_FAMILIES = {
    "tool_settings": {
        "type": "competing",
        "description": "Tool settings persistence (auto-save vs interact-guard vs raw)",
        "fragmentation_threshold": 2,
        "patterns": {
            "useAutoSaveSettings": r"\buseAutoSaveSettings\s*[<(]",
            "usePersistentToolState": r"\busePersistentToolState\s*[<(]",
            "useToolSettings": r"\buseToolSettings\s*[<(]",
        },
    },
    "ui_preferences": {
        "type": "complementary",
        "description": "User-scoped UI preferences (different scope from tool settings)",
        "patterns": {
            "useUserUIState": r"\buseUserUIState\s*\(",
        },
    },
    "error_handling": {
        "type": "complementary",
        "description": "Error handling layers (handleError wraps console.error + toast.error)",
        "patterns": {
            "handleError": r"\bhandleError\s*\(",
            "toast.error": r"\btoast\.error\s*\(",
            "console.error": r"\bconsole\.error\s*\(",
        },
    },
    "data_fetching": {
        "type": "complementary",
        "description": "Data fetching layers (useQuery reads, useMutation writes, supabase one-offs)",
        "patterns": {
            "useQuery": r"\buseQuery\s*[<({]",
            "useMutation": r"\buseMutation\s*[<({]",
            "supabase.from": r"\bsupabase\b[^;]*\.from\s*\(",
        },
    },
    "loading_display": {
        "type": "complementary",
        "description": "Loading UI (Loader2 spinners, Skeleton placeholders — different UX)",
        "patterns": {
            "Loader2": r"\bLoader2\b",
            "Skeleton": r"\bSkeleton\b",
        },
    },
}
logger = logging.getLogger(__name__)


def _build_census(path: Path) -> tuple[dict[str, dict[str, set[str]]], dict[str, dict[str, dict[str, list[dict]]]]]:
    """Build matrix: area → family → set of patterns used + file/line evidence.

    Scans all .ts/.tsx files, classifies by area, checks each file for
    pattern presence (file-level, not instance count).
    """
    files = find_ts_files(path)
    # area → family → set of pattern names found
    census: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    # area -> family -> pattern -> [{"file": rel_path, "line": line_no}]
    evidence: dict[str, dict[str, dict[str, list[dict]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )

    # Pre-compile regexes from all families
    compiled: dict[str, dict[str, re.Pattern]] = {}
    for family_name, family in PATTERN_FAMILIES.items():
        compiled[family_name] = {
            name: re.compile(regex) for name, regex in family["patterns"].items()
        }

    for filepath in files:
        try:
            area = get_area(filepath)
            p = Path(filepath) if Path(filepath).is_absolute() else Path(resolve_path(filepath))
            content = p.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            log_best_effort_failure(
                logger, f"read TypeScript pattern candidate {filepath}", exc
            )
            continue

        for family_name, patterns in compiled.items():
            for name, regex in patterns.items():
                match = regex.search(content)
                if match:
                    census[area][family_name].add(name)
                    line = content[:match.start()].count("\n") + 1
                    evidence[area][family_name][name].append(
                        {"file": rel(filepath), "line": line}
                    )

    return dict(census), {
        area: {
            family: {pat: entries for pat, entries in pats.items()}
            for family, pats in families.items()
        }
        for area, families in evidence.items()
    }


def detect_pattern_anomalies(path: Path) -> tuple[list[dict], int]:
    """Anomaly detector entrypoint."""
    return detect_pattern_anomalies_result(path).as_tuple()


def detect_pattern_anomalies_result(path: Path) -> DetectorResult[dict]:
    """Detect areas with competing pattern fragmentation.

    Only analyzes "competing" families — complementary families are excluded.

    Anomalies detected:
    - Fragmentation: area uses >= threshold patterns from a competing family
    - Outlier: area uses a competing pattern adopted by <10% of areas

    Returns (entries, total_areas).
    """
    census, evidence = _build_census(path)
    if not census:
        return DetectorResult(entries=[], population_kind="areas", population_size=0)

    total_areas = len(census)
    if total_areas < 5:
        return DetectorResult(
            entries=[],
            population_kind="areas",
            population_size=total_areas,
        )

    # Build adoption stats for competing families only
    competing_families = {
        name: fam
        for name, fam in PATTERN_FAMILIES.items()
        if fam["type"] == "competing"
    }

    # Count how many areas use each pattern (for outlier detection)
    pattern_adoption: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for _area, families in census.items():
        for family_name in competing_families:
            for pattern in families.get(family_name, set()):
                pattern_adoption[family_name][pattern] += 1

    anomalies = []

    for area, families in census.items():
        for family_name, family_config in competing_families.items():
            patterns = families.get(family_name, set())
            if not patterns:
                continue

            threshold = family_config["fragmentation_threshold"]
            reasons = []

            # Fragmentation: area uses >= threshold competing patterns
            if len(patterns) >= threshold:
                sorted_patterns = sorted(patterns)
                reasons.append(
                    f"{len(patterns)} competing {family_name} approaches: "
                    f"{', '.join(sorted_patterns)}. "
                    f"Review: can this area standardize on one?"
                )

            # Outlier: uses a competing pattern that <10% of areas use
            for pattern in patterns:
                adoption_count = pattern_adoption[family_name][pattern]
                adoption_rate = adoption_count / total_areas
                if adoption_rate < 0.10:
                    reasons.append(
                        f"Rare approach: {pattern} used here but only in "
                        f"{adoption_count}/{total_areas} areas"
                    )

            if reasons:
                confidence = "medium" if len(patterns) >= threshold else "low"
                family_evidence = (
                    evidence.get(area, {}).get(family_name, {})
                    if isinstance(evidence, dict)
                    else {}
                )
                anomalies.append(
                    {
                        "area": area,
                        "family": family_name,
                        "patterns_used": sorted(patterns),
                        "pattern_count": len(patterns),
                        "pattern_evidence": {
                            pattern_name: list(entries)
                            for pattern_name, entries in family_evidence.items()
                            if pattern_name in patterns and isinstance(entries, list)
                        },
                        "confidence": confidence,
                        "review": " | ".join(reasons),
                    }
                )

    return DetectorResult(
        entries=sorted(
            anomalies, key=lambda a: (-a["pattern_count"], a["area"], a["family"])
        ),
        population_kind="areas",
        population_size=total_areas,
    )


def cmd_patterns(args: argparse.Namespace) -> None:
    """Raw detector access: show full pattern census matrix + anomalies.

    The census shows ALL families (competing + complementary) for landscape overview.
    Anomalies only come from competing families.
    """
    path = Path(args.path)
    census, evidence = _build_census(path)
    anomalies, _ = detect_pattern_anomalies(path)

    if args.json:
        serializable = {
            area: {family: sorted(patterns) for family, patterns in families.items()}
            for area, families in census.items()
        }
        print(
            json.dumps(
                {
                    "areas": len(census),
                    "anomalies": len(anomalies),
                    "families": {
                        name: {"type": fam["type"], "description": fam["description"]}
                        for name, fam in PATTERN_FAMILIES.items()
                    },
                    "census": serializable,
                    "anomaly_details": anomalies,
                },
                indent=2,
            )
        )
        return

    # Full census matrix (all families, competing + complementary)
    family_names = sorted(PATTERN_FAMILIES.keys())
    if census:
        print(
            colorize(
                f"\nPattern Census ({len(census)} areas × {len(family_names)} families)\n",
                "bold",
            )
        )

        # Show family legend
        for name in family_names:
            fam = PATTERN_FAMILIES[name]
            marker = colorize("▶", "yellow") if fam["type"] == "competing" else colorize("·", "dim")
            print(f"  {marker} {name}: {fam['description']}")
        print()

        rows = []
        for area in sorted(census.keys()):
            cells = []
            for family in family_names:
                patterns = census[area].get(family, set())
                if patterns:
                    cells.append(", ".join(sorted(patterns)))
                else:
                    cells.append(colorize("-", "dim"))
            rows.append([area, *cells])
        headers = ["Area", *family_names]
        widths = [40] + [max(15, len(f) + 2) for f in family_names]
        print_table(headers, rows, widths)
    else:
        print(colorize("No pattern usage found.", "dim"))

    # Anomalies (competing families only)
    print()
    if anomalies:
        print(colorize(f"Competing-pattern anomalies: {len(anomalies)}\n", "bold"))
        for a in anomalies[: args.top]:
            patterns_str = ", ".join(a["patterns_used"])
            conf_badge = colorize(
                f"[{a['confidence']}]",
                "yellow" if a["confidence"] == "medium" else "dim",
            )
            print(f"  {colorize(a['area'], 'cyan')} :: {a['family']} {conf_badge}")
            print(f"    Patterns: {patterns_str}")
            for pname, matches in (a.get("pattern_evidence") or {}).items():
                files = [m.get("file", "") for m in matches[:3]]
                if files:
                    print(f"    Evidence {pname}: {', '.join(files)}")
            print(colorize(f"    {a['review']}", "yellow"))
            print()
    else:
        print(colorize("No competing-pattern anomalies detected.", "green"))
    print()
