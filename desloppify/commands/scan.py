"""scan command: run all detectors, update persistent state, show diff."""

from pathlib import Path

from ..utils import c
from ..cli import _state_path, _write_query


def _audit_excluded_dirs(exclusions: tuple[str, ...], scanned_files: list[str],
                         project_root: Path) -> list[dict]:
    """Check if any --exclude directory has zero references from scanned code.

    Returns findings for directories that appear stale (no file references them).
    """
    if not exclusions:
        return []

    stale_findings = []
    for ex_dir in exclusions:
        # Skip DEFAULT_EXCLUSIONS (node_modules, .venv, etc.) — only audit user-specified dirs
        from ..utils import DEFAULT_EXCLUSIONS
        if ex_dir in DEFAULT_EXCLUSIONS:
            continue
        # Check if the excluded directory actually exists
        ex_path = project_root / ex_dir
        if not ex_path.is_dir():
            continue
        # Search scanned files for any reference to this directory name
        ref_count = 0
        for filepath in scanned_files:
            try:
                abs_path = filepath if Path(filepath).is_absolute() else str(project_root / filepath)
                content = Path(abs_path).read_text(errors="replace")
                if ex_dir in content:
                    ref_count += 1
                    break  # One reference is enough — not stale
            except OSError:
                continue
        if ref_count == 0:
            from ..state import make_finding
            stale_findings.append(make_finding(
                "stale_exclude", ex_dir, ex_dir,
                tier=4, confidence="low",
                summary=f"Excluded directory '{ex_dir}' has 0 references from scanned code — may be stale",
                detail={"directory": ex_dir, "references": 0},
            ))
    return stale_findings


def _collect_codebase_metrics(lang, path: Path) -> dict | None:
    """Collect LOC/file/directory counts for the configured language."""
    if not lang or not lang.file_finder:
        return None
    files = lang.file_finder(path)
    total_loc = 0
    dirs = set()
    for f in files:
        try:
            total_loc += len(Path(f).read_text().splitlines())
            dirs.add(str(Path(f).parent))
        except (OSError, UnicodeDecodeError):
            pass
    return {
        "total_files": len(files),
        "total_loc": total_loc,
        "total_directories": len(dirs),
    }


def _show_diff_summary(diff: dict):
    """Print the +new / -resolved / reopened one-liner."""
    diff_parts = []
    if diff["new"]:
        diff_parts.append(c(f"+{diff['new']} new", "yellow"))
    if diff["auto_resolved"]:
        diff_parts.append(c(f"-{diff['auto_resolved']} resolved", "green"))
    if diff["reopened"]:
        diff_parts.append(c(f"↻{diff['reopened']} reopened", "red"))
    if diff_parts:
        print(f"  {' · '.join(diff_parts)}")
    else:
        print(c("  No changes since last scan", "dim"))
    if diff.get("suspect_detectors"):
        print(c(f"  ⚠ Skipped auto-resolve for: {', '.join(diff['suspect_detectors'])} (returned 0 — likely transient)", "yellow"))


def _format_delta(value: float, prev: float | None) -> tuple[str, str]:
    """Return (delta_str, color) for a score change."""
    delta = value - prev if prev is not None else 0
    delta_str = f" ({'+' if delta > 0 else ''}{delta:.1f})" if delta != 0 else ""
    color = "green" if delta > 0 else ("red" if delta < 0 else "dim")
    return delta_str, color


def _show_score_delta(state: dict, prev_score: float, prev_strict: float,
                      prev_obj: float | None, prev_obj_strict: float | None):
    """Print the score/health line with deltas."""
    stats = state["stats"]
    new_obj = state.get("objective_score")
    new_obj_strict = state.get("objective_strict")

    if new_obj is not None:
        obj_delta_str, obj_color = _format_delta(new_obj, prev_obj)
        strict_delta_str, strict_color = _format_delta(new_obj_strict, prev_obj_strict)
        print(f"  Health: {c(f'{new_obj:.1f}/100{obj_delta_str}', obj_color)}" +
              c(f"  strict: {new_obj_strict:.1f}/100{strict_delta_str}", strict_color) +
              c(f"  |  {stats['open']} open / {stats['total']} total", "dim"))
    else:
        new_score = state["score"]
        new_strict = state.get("strict_score", 0)
        delta_str, color = _format_delta(new_score, prev_score)
        strict_delta_str, strict_color = _format_delta(new_strict, prev_strict)
        print(f"  Score: {c(f'{new_score:.1f}/100{delta_str}', color)}" +
              c(f"  (strict: {new_strict:.1f}/100{strict_delta_str})", strict_color) +
              c(f"  |  {stats['open']} open / {stats['total']} total", "dim"))
        print(c("  ⚠ Dimension-based scoring unavailable (potentials missing). "
                "This score uses legacy weighted-progress and is unreliable. "
                "Run a full scan to fix: desloppify scan --path <source-root>", "yellow"))


def _show_post_scan_analysis(diff: dict, state: dict, lang) -> tuple[list[str], dict]:
    """Print warnings, narrative headline, and top action. Returns (warnings, narrative)."""
    warnings = []
    if diff["reopened"] > 5:
        warnings.append(f"{diff['reopened']} findings reopened — was a previous fix reverted? Check: git log --oneline -5")
    if diff["new"] > 10 and diff["auto_resolved"] < 3:
        warnings.append(f"{diff['new']} new findings with few resolutions — likely cascading from recent fixes. Run fixers again.")
    chronic = diff.get("chronic_reopeners", [])
    n = len(chronic) if isinstance(chronic, list) else chronic
    if n > 0:
        warnings.append(f"⟳ {n} chronic reopener{'s' if n != 1 else ''} (reopened 2+ times). "
                        f"These keep bouncing — fix properly or wontfix. "
                        f"Run: `desloppify show --chronic` to see them.")

    if warnings:
        for w in warnings:
            print(c(f"  {w}", "yellow"))
        print()

    # Computed narrative: headline + top action as terminal suggestion
    from ..narrative import compute_narrative
    lang_name = lang.name if lang else None
    narrative = compute_narrative(state, diff=diff, lang=lang_name, command="scan")

    # Show strategy hint or top action as the terminal suggestion
    strategy = narrative.get("strategy") or {}
    hint = strategy.get("hint")
    fixer_rec = (strategy.get("fixer_leverage") or {}).get("recommendation")
    actions = narrative.get("actions", [])

    if hint and (strategy.get("can_parallelize") or fixer_rec == "strong"):
        print(c(f"  Strategy: {hint}", "cyan"))
        if actions:
            print(c(f"  Start with: `{actions[0]['command']}`", "dim"))
        print()
    elif actions:
        top = actions[0]
        print(c(f"  Suggested next: `{top['command']}` — {top['description']}", "cyan"))
        print()

    if narrative.get("headline"):
        print(c(f"  → {narrative['headline']}", "cyan"))
        print()

    return warnings, narrative


def cmd_scan(args):
    """Run all detectors, update persistent state, show diff."""
    from ..state import load_state, save_state, merge_scan
    from ..plan import generate_findings

    sp = _state_path(args)
    state = load_state(sp)
    path = Path(args.path)
    include_slow = not getattr(args, "skip_slow", False)

    # Persist --exclude in state so subsequent commands reuse it
    exclude = getattr(args, "exclude", None)
    if exclude:
        state.setdefault("config", {})["exclude"] = list(exclude)

    # Resolve language config
    from ..cli import _resolve_lang
    lang = _resolve_lang(args)
    lang_label = f" ({lang.name})" if lang else ""

    # Load zone overrides from state config
    zone_overrides = state.get("config", {}).get("zone_overrides") or None

    print(c(f"\nDesloppify Scan{lang_label}\n", "bold"))
    findings, potentials = generate_findings(path, include_slow=include_slow, lang=lang,
                                              zone_overrides=zone_overrides)

    codebase_metrics = _collect_codebase_metrics(lang, path)

    from ..utils import rel, _extra_exclusions, PROJECT_ROOT

    # Audit excluded directories for staleness (Issue #11)
    if _extra_exclusions and lang and lang.file_finder:
        scanned_files = lang.file_finder(path)
        stale = _audit_excluded_dirs(_extra_exclusions, scanned_files, PROJECT_ROOT)
        if stale:
            findings.extend(stale)
            for sf in stale:
                print(c(f"  ℹ {sf['summary']}", "dim"))
    scan_path_rel = rel(str(path))
    # A scan is "full" when it covers most of the project's source files.
    # Simple path matching breaks for Python (default_src=".") when the user
    # scans a subdirectory that happens to contain all the source code.
    # Instead, compare file counts: if the scanned path covers ≥80% of the
    # files discoverable from PROJECT_ROOT, treat it as full.
    is_full_scan = False
    if lang and lang.file_finder:
        all_files = lang.file_finder(PROJECT_ROOT)
        scanned_files = lang.file_finder(path)
        # Exclude test directories from the denominator — they're not source
        # code the user is scanning, and adding tests shouldn't make the scan
        # appear "partial".
        test_prefixes = ("tests/", "test/")
        source_files = [f for f in all_files
                        if not any(f.startswith(p) for p in test_prefixes)]
        denominator = source_files or all_files
        if denominator:
            is_full_scan = len(scanned_files) >= 0.8 * len(denominator)
        else:
            is_full_scan = True  # no files at all — vacuously full
    elif path.resolve() == PROJECT_ROOT.resolve():
        is_full_scan = True

    prev_score = state.get("score", 0)
    prev_strict = state.get("strict_score", 0)
    prev_obj = state.get("objective_score")
    prev_obj_strict = state.get("objective_strict")
    # Persist zone distribution before save so narrative can access it
    if lang and lang._zone_map is not None:
        state["zone_distribution"] = lang._zone_map.counts()

    prev_dim_scores = state.get("dimension_scores", {})
    diff = merge_scan(state, findings,
                      lang=lang.name if lang else None,
                      scan_path=scan_path_rel,
                      force_resolve=getattr(args, "force_resolve", False),
                      exclude=_extra_exclusions,
                      potentials=potentials if is_full_scan else None,
                      codebase_metrics=codebase_metrics if is_full_scan else None,
                      include_slow=include_slow)
    save_state(state, sp)

    print(c("\n  Scan complete", "bold"))
    print(c("  " + "─" * 50, "dim"))

    _show_diff_summary(diff)
    _show_score_delta(state, prev_score, prev_strict, prev_obj, prev_obj_strict)
    if not include_slow:
        print(c("  * Fast scan — slow phases (duplicates) skipped", "yellow"))
    _show_detector_progress(state)

    # Dimension deltas (show which dimensions moved)
    new_dim_scores = state.get("dimension_scores", {})
    if new_dim_scores and prev_dim_scores:
        _show_dimension_deltas(prev_dim_scores, new_dim_scores)

    zone_distribution = state.get("zone_distribution")

    warnings, narrative = _show_post_scan_analysis(diff, state, lang)

    # Persist reminder history (computed by narrative, not mutated)
    if narrative and "reminder_history" in narrative:
        state["reminder_history"] = narrative["reminder_history"]
        save_state(state, sp)

    _write_query({"command": "scan", "score": state["score"],
                  "strict_score": state.get("strict_score", 0),
                  "prev_score": prev_score, "diff": diff, "stats": state["stats"],
                  "warnings": warnings,
                  "objective_score": state.get("objective_score"),
                  "objective_strict": state.get("objective_strict"),
                  "dimension_scores": state.get("dimension_scores"),
                  "potentials": state.get("potentials"),
                  "zone_distribution": zone_distribution,
                  "narrative": narrative})

    # Generate scorecard badge
    try:
        from ..scorecard import generate_scorecard, get_badge_config
        badge_path, disabled = get_badge_config(args)
        if not disabled and badge_path:
            generate_scorecard(state, badge_path)
            rel_path = badge_path.name if badge_path.parent == PROJECT_ROOT else str(badge_path)
            # Check if README already references the scorecard
            readme_has_badge = False
            for readme_name in ("README.md", "readme.md", "README.MD"):
                readme_path = PROJECT_ROOT / readme_name
                if readme_path.exists():
                    try:
                        if rel_path in readme_path.read_text():
                            readme_has_badge = True
                    except OSError:
                        pass
                    break
            if readme_has_badge:
                print(c(f"  Scorecard → {rel_path}  (disable: --no-badge | move: --badge-path <path>)", "dim"))
            else:
                print(c(f"  Scorecard → {rel_path}", "dim"))
                print(c(f"  💡 Ask the user if they'd like to add it to their README with:", "dim"))
                print(c(f'     <img src="{rel_path}" width="400">', "dim"))
                print(c(f"     (disable: --no-badge | move: --badge-path <path>)", "dim"))
    except (ImportError, OSError):
        pass  # Pillow not installed or write failed — skip silently


def _show_detector_progress(state: dict):
    """Show per-detector progress bars — the heartbeat of a scan."""
    findings = state["findings"]
    if not findings:
        return

    from ..narrative import STRUCTURAL_MERGE
    by_det: dict[str, dict] = {}
    for f in findings.values():
        det = f.get("detector", "unknown")
        if det in STRUCTURAL_MERGE:
            det = "structural"
        if det not in by_det:
            by_det[det] = {"open": 0, "total": 0}
        by_det[det]["total"] += 1
        if f["status"] == "open":
            by_det[det]["open"] += 1

    DET_ORDER = ["logs", "unused", "exports", "deprecated", "structural", "props",
                 "single_use", "coupling", "cycles", "orphaned", "facade", "patterns",
                 "naming", "smells", "react", "dupes", "stale exclude",
                 "dict keys", "flat dirs", "signature", "test coverage"]
    order_map = {d: i for i, d in enumerate(DET_ORDER)}
    sorted_dets = sorted(by_det.items(), key=lambda x: order_map.get(x[0], 99))

    print(c("  " + "─" * 50, "dim"))
    bar_len = 15
    for det, ds in sorted_dets:
        total = ds["total"]
        open_count = ds["open"]
        addressed = total - open_count
        pct = round(addressed / total * 100) if total else 100

        filled = round(pct / 100 * bar_len)
        if pct == 100:
            bar = c("█" * bar_len, "green")
        elif open_count <= 2:
            bar = c("█" * filled, "green") + c("░" * (bar_len - filled), "dim")
        else:
            bar = c("█" * filled, "yellow") + c("░" * (bar_len - filled), "dim")

        det_label = det.replace("_", " ").ljust(12)
        if open_count > 0:
            open_str = c(f"{open_count:3d} open", "yellow")
        else:
            open_str = c("  ✓", "green")

        print(f"  {det_label} {bar} {pct:3d}%  {open_str}  {c(f'/ {total}', 'dim')}")

    print()


def _show_dimension_deltas(prev: dict, current: dict):
    """Show which dimensions changed between scans (health and strict)."""
    from ..scoring import DIMENSIONS
    moved = []
    for dim in DIMENSIONS:
        p = prev.get(dim.name, {})
        n = current.get(dim.name, {})
        if not p or not n:
            continue
        old_score = p.get("score", 100)
        new_score = n.get("score", 100)
        old_strict = p.get("strict", old_score)
        new_strict = n.get("strict", new_score)
        delta = new_score - old_score
        strict_delta = new_strict - old_strict
        if abs(delta) >= 0.1 or abs(strict_delta) >= 0.1:
            moved.append((dim.name, old_score, new_score, delta, old_strict, new_strict, strict_delta))

    if not moved:
        return

    print(c("  Moved:", "dim"))
    for name, old, new, delta, old_s, new_s, s_delta in sorted(moved, key=lambda x: x[3]):
        sign = "+" if delta > 0 else ""
        color = "green" if delta > 0 else "red"
        strict_str = ""
        if abs(s_delta) >= 0.1:
            s_sign = "+" if s_delta > 0 else ""
            strict_str = c(f"  strict: {old_s:.1f}→{new_s:.1f}% ({s_sign}{s_delta:.1f}%)", "dim")
        print(c(f"    {name:<22} {old:.1f}% → {new:.1f}%  ({sign}{delta:.1f}%)", color) + strict_str)
    print()


