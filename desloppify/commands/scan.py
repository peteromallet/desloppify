"""scan command: run all detectors, update persistent state, show diff."""

from pathlib import Path

from ..utils import colorize
from ._helpers import state_path, _write_query


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


def _warn_explicit_lang_with_no_files(args, lang, path: Path, metrics: dict | None) -> None:
    """Warn when user explicitly selected a language but scan found zero files."""
    explicit_lang = getattr(args, "lang", None)
    if not explicit_lang or not lang or not metrics:
        return
    if metrics.get("total_files", 0) > 0:
        return

    suggestion = " Omit `--lang` to auto-detect."
    try:
        from ..lang import auto_detect_lang

        root = path if path.is_dir() else path.parent
        detected = auto_detect_lang(root)
        if detected and detected != lang.name:
            suggestion = (
                f" Detected `{detected}` for this path — use `--lang {detected}` "
                "or omit `--lang`."
            )
    except Exception:
        pass

    print(
        colorize(
            f"  ⚠ No {lang.name} source files found under `{path}`.{suggestion}",
            "yellow",
        )
    )


def _show_diff_summary(diff: dict):
    """Print the +new / -resolved / reopened one-liner."""
    diff_parts = []
    if diff["new"]:
        diff_parts.append(colorize(f"+{diff['new']} new", "yellow"))
    if diff["auto_resolved"]:
        diff_parts.append(colorize(f"-{diff['auto_resolved']} resolved", "green"))
    if diff["reopened"]:
        diff_parts.append(colorize(f"↻{diff['reopened']} reopened", "red"))
    if diff_parts:
        print(f"  {' · '.join(diff_parts)}")
    else:
        print(colorize("  No changes since last scan", "dim"))
    if diff.get("suspect_detectors"):
        print(colorize(f"  ⚠ Skipped auto-resolve for: {', '.join(diff['suspect_detectors'])} (returned 0 — likely transient)", "yellow"))


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

    wontfix = stats.get("wontfix", 0)
    wontfix_str = f" · {wontfix} wontfix" if wontfix else ""

    if new_obj is not None:
        obj_delta_str, obj_color = _format_delta(new_obj, prev_obj)
        strict_delta_str, strict_color = _format_delta(new_obj_strict, prev_obj_strict)
        print(f"  Health: {colorize(f'{new_obj:.1f}/100{obj_delta_str}', obj_color)}" +
              colorize(f"  strict: {new_obj_strict:.1f}/100{strict_delta_str}", strict_color) +
              colorize(f"  |  {stats['open']} open{wontfix_str} / {stats['total']} total", "dim"))
        # Surface wontfix debt gap prominently when significant
        gap = (new_obj or 0) - (new_obj_strict or 0)
        if gap >= 5 and wontfix >= 10:
            print(colorize(f"  ⚠ {gap:.1f}-point gap between health and strict — "
                           f"{wontfix} wontfix items represent hidden debt", "yellow"))
    else:
        new_score = state["score"]
        new_strict = state.get("strict_score", 0)
        delta_str, color = _format_delta(new_score, prev_score)
        strict_delta_str, strict_color = _format_delta(new_strict, prev_strict)
        print(f"  Score: {colorize(f'{new_score:.1f}/100{delta_str}', color)}" +
              colorize(f"  (strict: {new_strict:.1f}/100{strict_delta_str})", strict_color) +
              colorize(f"  |  {stats['open']} open{wontfix_str} / {stats['total']} total", "dim"))
        print(colorize("  ⚠ Dimension-based scoring unavailable (potentials missing). "
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
            print(colorize(f"  {w}", "yellow"))
        print()

    # Computed narrative: headline + top action as terminal suggestion
    print(colorize("\n  INSTRUCTIONS FOR AGENTS: follow the strategy and recommendations below.", "yellow"))
    from ..narrative import compute_narrative
    lang_name = lang.name if lang else None
    narrative = compute_narrative(state, diff=diff, lang=lang_name, command="scan")

    # Show strategy hint or top action as the terminal suggestion
    strategy = narrative.get("strategy") or {}
    hint = strategy.get("hint")
    fixer_rec = (strategy.get("fixer_leverage") or {}).get("recommendation")
    actions = narrative.get("actions", [])

    if hint and (strategy.get("can_parallelize") or fixer_rec == "strong"):
        print(colorize(f"  Strategy: {hint}", "cyan"))
        if actions:
            print(colorize(f"  Start with: `{actions[0]['command']}`", "dim"))
        print()
    elif actions:
        top = actions[0]
        print(colorize(f"  Suggested next: `{top['command']}` — {top['description']}", "cyan"))
        print()

    if narrative.get("headline"):
        print(colorize(f"  → {narrative['headline']}", "cyan"))
        print()

    # Review findings nudge
    from ..state import path_scoped_findings
    open_review = [f for f in path_scoped_findings(
        state.get("findings", {}), state.get("scan_path")).values()
                   if f["status"] == "open" and f.get("detector") == "review"]
    if open_review:
        s = "s" if len(open_review) != 1 else ""
        print(colorize(f"  Review: {len(open_review)} finding{s} pending \u2014 `desloppify issues`", "cyan"))
        print()

    # Auto-queue: nudge subjective review for high-complexity unreviewed files
    review_cache = state.get("review_cache", {}).get("files", {})
    scoped = path_scoped_findings(state.get("findings", {}), state.get("scan_path"))
    complex_unreviewed = set()
    for f in scoped.values():
        if (f.get("detector") in ("structural", "smells")
                and f.get("status") == "wontfix"
                and f.get("file") not in review_cache):
            complex_unreviewed.add(f.get("file"))
    if len(complex_unreviewed) >= 3:
        print(colorize(f"  {len(complex_unreviewed)} complex files have never been reviewed — "
                        f"`desloppify review --prepare` would provide actionable refactoring guidance", "dim"))
        print()

    return warnings, narrative


def cmd_scan(args) -> None:
    """Run all detectors, update persistent state, show diff."""
    from ..state import load_state, save_state, merge_scan
    from ..plan import generate_findings

    sp = state_path(args)
    state = load_state(sp)
    path = Path(args.path)
    include_slow = not getattr(args, "skip_slow", False)

    # Persist --exclude in config so subsequent commands reuse it
    from ..config import save_config
    config = args._config
    exclude = getattr(args, "exclude", None)
    if exclude:
        config["exclude"] = list(exclude)
        save_config(config)

    # Resolve language config
    from ._helpers import resolve_lang
    lang = resolve_lang(args)
    lang_label = f" ({lang.name})" if lang else ""

    # Load zone overrides from config
    zone_overrides = config.get("zone_overrides") or None

    # Populate review cache and max age for review_coverage detector
    if lang:
        lang._review_cache = state.get("review_cache", {}).get("files", {})
        lang._review_max_age_days = config.get("review_max_age_days", 30)
        state.setdefault("lang_capabilities", {})[lang.name] = {
            "fixers": sorted(lang.fixers.keys()),
            "typecheck_cmd": lang.typecheck_cmd,
        }
        # Apply config-level threshold overrides
        override_threshold = config.get("large_files_threshold", 0)
        if override_threshold > 0:
            lang.large_threshold = override_threshold
        props_threshold = config.get("props_threshold", 0)
        if props_threshold > 0:
            lang._props_threshold = props_threshold

    print(colorize(f"\nDesloppify Scan{lang_label}\n", "bold"))
    from ..utils import enable_file_cache, disable_file_cache
    enable_file_cache()
    try:
        findings, potentials = generate_findings(path, include_slow=include_slow, lang=lang,
                                                  zone_overrides=zone_overrides)
    finally:
        disable_file_cache()

    codebase_metrics = _collect_codebase_metrics(lang, path)
    _warn_explicit_lang_with_no_files(args, lang, path, codebase_metrics)

    from ..utils import rel, get_exclusions, PROJECT_ROOT

    # Audit excluded directories for staleness (Issue #11)
    extra_ex = get_exclusions()
    if extra_ex and lang and lang.file_finder:
        scanned_files = lang.file_finder(path)
        stale = _audit_excluded_dirs(extra_ex, scanned_files, PROJECT_ROOT)
        if stale:
            findings.extend(stale)
            for sf in stale:
                print(colorize(f"  ℹ {sf['summary']}", "dim"))
    scan_path_rel = rel(str(path))

    prev_scan_path = state.get("scan_path")
    path_changed = prev_scan_path is not None and prev_scan_path != scan_path_rel
    prev_score = state.get("score", 0) if not path_changed else 0
    prev_strict = state.get("strict_score", 0) if not path_changed else 0
    prev_obj = state.get("objective_score") if not path_changed else None
    prev_obj_strict = state.get("objective_strict") if not path_changed else None
    # Persist zone distribution before save so narrative can access it
    if lang and lang._zone_map is not None:
        state["zone_distribution"] = lang._zone_map.counts()

    prev_dim_scores = state.get("dimension_scores", {}) if not path_changed else {}
    diff = merge_scan(state, findings,
                      lang=lang.name if lang else None,
                      scan_path=scan_path_rel,
                      force_resolve=getattr(args, "force_resolve", False),
                      exclude=get_exclusions(),
                      potentials=potentials,
                      codebase_metrics=codebase_metrics,
                      include_slow=include_slow,
                      ignore=config.get("ignore", []))

    # Expire stale holistic review findings
    from ..issues import expire_stale_holistic
    holistic_max_age = config.get("holistic_max_age_days", 30)
    expire_stale_holistic(state, holistic_max_age)

    save_state(state, sp)

    print(colorize("\n  AGENT: PLEASE READ the strategy and recommendations below the score.", "yellow"))
    print(colorize("  They are CUSTOM COACHING tailored to this codebase. Follow them.", "yellow"))
    print(colorize("  Scan complete", "bold"))
    print(colorize("  " + "─" * 50, "dim"))

    _show_diff_summary(diff)
    _show_score_delta(state, prev_score, prev_strict, prev_obj, prev_obj_strict)
    if not include_slow:
        print(colorize("  * Fast scan — slow phases (duplicates) skipped", "yellow"))
    _show_detector_progress(state)

    # Dimension deltas and low-dimension hints
    new_dim_scores = state.get("dimension_scores", {})
    if new_dim_scores and prev_dim_scores:
        _show_dimension_deltas(prev_dim_scores, new_dim_scores)
    if new_dim_scores:
        _show_low_dimension_hints(new_dim_scores)

    _show_score_integrity(state, diff)

    zone_distribution = state.get("zone_distribution")

    warnings, narrative = _show_post_scan_analysis(diff, state, lang)

    # Persist reminder history (computed by narrative, not mutated)
    if narrative and "reminder_history" in narrative:
        state["reminder_history"] = narrative["reminder_history"]
        save_state(state, sp)

    from ..config import config_for_query
    _write_query({"command": "scan", "score": state["score"],
                  "strict_score": state.get("strict_score", 0),
                  "prev_score": prev_score, "diff": diff, "stats": state["stats"],
                  "warnings": warnings,
                  "objective_score": state.get("objective_score"),
                  "objective_strict": state.get("objective_strict"),
                  "dimension_scores": state.get("dimension_scores"),
                  "potentials": state.get("potentials"),
                  "zone_distribution": zone_distribution,
                  "narrative": narrative,
                  "config": config_for_query(config)})

    # Generate scorecard badge
    badge_path = None
    try:
        from ..output.scorecard import generate_scorecard, get_badge_config
        badge_path, disabled = get_badge_config(args, config)
        if not disabled and badge_path:
            generate_scorecard(state, badge_path)
            rel_path = badge_path.name if badge_path.parent == PROJECT_ROOT else str(badge_path)
            # Check if README already references the scorecard
            readme_has_badge = False
            for readme_name in ("README.md", "readme.md", "README.MD"):
                readme_path = PROJECT_ROOT / readme_name
                if readme_path.exists():
                    try:
                        if rel_path in readme_path.read_text(
                            encoding="utf-8", errors="replace"
                        ):
                            readme_has_badge = True
                    except OSError:
                        pass
                    break
            if readme_has_badge:
                print(colorize(f"  Scorecard → {rel_path}  (disable: --no-badge | move: --badge-path <path>)", "dim"))
            else:
                print(colorize(f"  Scorecard → {rel_path}", "dim"))
                print(colorize(f"  💡 Ask the user if they'd like to add it to their README with:", "dim"))
                print(colorize(f'     <img src="{rel_path}" width="100%">', "dim"))
                print(colorize(f"     (disable: --no-badge | move: --badge-path <path>)", "dim"))
        else:
            badge_path = None
    except (ImportError, OSError):
        badge_path = None  # Pillow not installed or write failed — skip silently

    _print_llm_summary(state, badge_path, narrative, diff)


def _show_score_integrity(state: dict, diff: dict):
    """Show Score Integrity section — surfaces wontfix debt and ignored findings."""
    stats = state.get("stats", {})
    wontfix = stats.get("wontfix", 0)
    ignored = diff.get("ignored", 0)
    ignore_patterns = diff.get("ignore_patterns", 0)

    if wontfix <= 5 and ignored <= 0 and ignore_patterns <= 0:
        return

    obj = state.get("objective_score")
    obj_strict = state.get("objective_strict")
    strict_gap = round(obj - obj_strict, 1) if obj is not None and obj_strict is not None else 0

    # Wontfix % of actionable findings (open + wontfix + fixed + auto_resolved + false_positive)
    actionable = stats.get("open", 0) + wontfix + stats.get("fixed", 0) + stats.get("auto_resolved", 0) + stats.get("false_positive", 0)
    wontfix_pct = round(wontfix / actionable * 100) if actionable else 0

    print(colorize("  " + "\u2504" * 2 + " Score Integrity " + "\u2504" * 37, "dim"))

    if wontfix > 5:
        if wontfix_pct > 50:
            style = "red"
            msg = f"  \u274c {wontfix} wontfix ({wontfix_pct}%) \u2014 over half of findings swept under rug. Strict gap: {strict_gap} pts"
        elif wontfix_pct > 25:
            style = "yellow"
            msg = f"  \u26a0 {wontfix} wontfix ({wontfix_pct}%) \u2014 review whether past wontfix decisions still hold"
        elif wontfix_pct > 10:
            style = "yellow"
            msg = f"  \u26a0 {wontfix} wontfix findings ({wontfix_pct}%) \u2014 strict {strict_gap} pts below lenient"
        else:
            style = "dim"
            msg = f"  {wontfix} wontfix \u2014 strict gap: {strict_gap} pts"
        print(colorize(msg, style))

        # Show top 2 dimensions with biggest strict gap
        dim_scores = state.get("dimension_scores", {})
        if dim_scores:
            gaps = []
            for name, data in dim_scores.items():
                score = data.get("score", 100)
                strict = data.get("strict", score)
                gap = round(score - strict, 1)
                if gap > 0:
                    gaps.append((name, gap))
            gaps.sort(key=lambda x: -x[1])
            if gaps:
                top = gaps[:2]
                gap_str = ", ".join(f"{n} (\u2212{g} pts)" for n, g in top)
                print(colorize(f"    Biggest gaps: {gap_str}", "dim"))

    if ignored > 0:
        if ignore_patterns > 5 or ignored > 100:
            style = "red"
        else:
            style = "yellow"
        print(colorize(f"  \u26a0 {ignore_patterns} ignore pattern{'s' if ignore_patterns != 1 else ''} "
                        f"suppressed {ignored} finding{'s' if ignored != 1 else ''} this scan", style))
        print(colorize(f"    Ignored findings are invisible to scoring", "dim"))
    elif ignore_patterns > 0:
        print(colorize(
            f"  {ignore_patterns} ignore pattern{'s' if ignore_patterns != 1 else ''} active "
            f"(0 findings suppressed this scan)",
            "dim",
        ))

    print(colorize("  " + "\u2504" * 55, "dim"))
    print()


def _print_llm_summary(state: dict, badge_path: Path | None,
                        narrative: dict | None = None,
                        diff: dict | None = None):
    """Print a structured summary for LLM consumption.

    The LLM reads terminal output after running scans. This gives it
    clear instructions on how to present the results to the end user.
    Only shown when running inside an agent (CLAUDE_CODE or DESLOPPIFY_AGENT env).
    """
    import os
    if not (os.environ.get("CLAUDE_CODE") or os.environ.get("DESLOPPIFY_AGENT")):
        return

    dim_scores = state.get("dimension_scores", {})
    obj_score = state.get("objective_score")
    obj_strict = state.get("objective_strict")
    if obj_score is None and not dim_scores:
        return

    print("─" * 60)
    print("INSTRUCTIONS FOR LLM")
    print("IMPORTANT: ALWAYS present ALL scores to the user after a scan.")
    print("Show overall health (lenient + strict), ALL dimension scores,")
    print("AND all subjective dimension scores in a markdown table.")
    print("The goal is to maximize strict scores. Never skip the scores.\n")

    print(f"Overall health: {obj_score:.1f}/100")
    if obj_strict is not None:
        print(f"Strict health:  {obj_strict:.1f}/100")
    print()

    # Build dimension table — separate mechanical from subjective
    from ..scoring import DIMENSIONS
    static_names = {d.name for d in DIMENSIONS}
    mechanical = [(name, data) for name, data in dim_scores.items()
                  if name in static_names and data.get("checks", 0) > 0]
    subjective = [(name, data) for name, data in dim_scores.items()
                  if name not in static_names and data.get("checks", 0) > 0]

    if mechanical or subjective:
        from ..registry import dimension_action_type
        print("| Dimension | Health | Strict | Issues | Tier | Action |")
        print("|-----------|--------|--------|--------|------|--------|")
        for name, data in sorted(mechanical, key=lambda x: x[0]):
            score = data.get("score", 100)
            strict = data.get("strict", score)
            issues = data.get("issues", 0)
            tier = data.get("tier", "")
            action = dimension_action_type(name)
            print(f"| {name} | {score:.1f}% | {strict:.1f}% | {issues} | T{tier} | {action} |")
        if subjective:
            print("| **Subjective Dimensions** | | | | | |")
            for name, data in sorted(subjective, key=lambda x: x[0]):
                score = data.get("score", 100)
                strict = data.get("strict", score)
                issues = data.get("issues", 0)
                tier = data.get("tier", "")
                print(f"| {name} | {score:.1f}% | {strict:.1f}% | {issues} | T{tier} | review |")
        print()

    stats = state.get("stats", {})
    if stats:
        wontfix = stats.get("wontfix", 0)
        ignored = diff.get("ignored", 0) if diff else 0
        ignore_pats = diff.get("ignore_patterns", 0) if diff else 0
        strict_gap = round((obj_score or 0) - (obj_strict or 0), 1) if obj_score and obj_strict else 0
        print(f"Total findings: {stats.get('total', 0)} | "
              f"Open: {stats.get('open', 0)} | "
              f"Fixed: {stats.get('fixed', 0)} | "
              f"Wontfix: {wontfix}")
        if wontfix or ignored or ignore_pats:
            print(f"Ignored: {ignored} (by {ignore_pats} patterns) | Strict gap: {strict_gap} pts")
            print("Focus on strict score \u2014 wontfix and ignore inflate the lenient score.")
        print()

    # Workflow guide — teach agents the full cycle
    print("## Workflow Guide\n")
    print("1. **Review findings first** (if any): `desloppify issues` — high-value subjective findings")
    print("2. **Run auto-fixers** (if available): `desloppify fix <fixer> --dry-run` to preview, then apply")
    print("3. **Manual fixes**: `desloppify next` — highest-priority item. Fix it, then:")
    print('   `desloppify resolve fixed "<id>" --note "<what you did>"`')
    print("4. **Rescan**: `desloppify scan --path <path>` — verify improvements, catch cascading effects")
    print("5. **Check progress**: `desloppify status` — dimension scores dashboard\n")
    print("### Decision Guide")
    print("- **Tackle**: T1/T2 (high impact), auto-fixable, security findings")
    print("- **Consider skipping**: T4 low-confidence, test/config zone findings (lower impact)")
    print("- **Wontfix**: Intentional patterns, false positives →")
    print('  `desloppify resolve wontfix "<id>" --note "<why>"`')
    print("- **Batch wontfix**: Multiple intentional patterns →")
    print('  `desloppify resolve wontfix "<detector>::*::<category>" --note "<why>"`\n')
    print("### Understanding Dimensions")
    print("- **Mechanical** (File health, Code quality, etc.): Fix code → rescan")
    print("- **Subjective** (Naming Quality, Logic Clarity, etc.): Address review findings → re-review")
    print("- **Health vs Strict**: Health ignores wontfix; Strict penalizes it. Focus on Strict.\n")

    # Current narrative status
    if narrative:
        headline = narrative.get("headline", "")
        strategy = narrative.get("strategy") or {}
        actions = narrative.get("actions", [])
        if headline:
            print(f"Current status: {headline}")
        hint = strategy.get("hint", "")
        if hint:
            print(f"Strategy: {hint}")
        if actions:
            top = actions[0]
            print(f"Top action: `{top['command']}` — {top['description']}")
        print()

    if badge_path and badge_path.exists():
        from ..utils import PROJECT_ROOT
        rel_path = badge_path.name if badge_path.parent == PROJECT_ROOT else str(badge_path)
        print(f"A scorecard image was saved to `{rel_path}`.")
        print("Let the user know they can view it, and suggest adding it")
        print(f'to their README: `<img src="{rel_path}" width="100%">`')
    print("─" * 60)


def _show_detector_progress(state: dict):
    """Show per-detector progress bars — the heartbeat of a scan."""
    from ..state import path_scoped_findings
    findings = path_scoped_findings(state["findings"], state.get("scan_path"))
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

    from ..registry import display_order, DETECTORS
    DET_ORDER = [DETECTORS[d].display for d in display_order() if d in DETECTORS]
    order_map = {d: i for i, d in enumerate(DET_ORDER)}
    sorted_dets = sorted(by_det.items(), key=lambda x: order_map.get(x[0], 99))

    print(colorize("  " + "─" * 50, "dim"))
    bar_len = 15
    for det, ds in sorted_dets:
        total = ds["total"]
        open_count = ds["open"]
        addressed = total - open_count
        pct = round(addressed / total * 100) if total else 100

        filled = round(pct / 100 * bar_len)
        if pct == 100:
            bar = colorize("█" * bar_len, "green")
        elif open_count <= 2:
            bar = colorize("█" * filled, "green") + colorize("░" * (bar_len - filled), "dim")
        else:
            bar = colorize("█" * filled, "yellow") + colorize("░" * (bar_len - filled), "dim")

        det_label = det.replace("_", " ").ljust(18)
        if open_count > 0:
            open_str = colorize(f"{open_count:3d} open", "yellow")
        else:
            open_str = colorize("  ✓", "green")

        print(f"  {det_label} {bar} {pct:3d}%  {open_str}  {colorize(f'/ {total}', 'dim')}")

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

    print(colorize("  Moved:", "dim"))
    for name, old, new, delta, old_s, new_s, s_delta in sorted(moved, key=lambda x: x[3]):
        sign = "+" if delta > 0 else ""
        color = "green" if delta > 0 else "red"
        strict_str = ""
        if abs(s_delta) >= 0.1:
            s_sign = "+" if s_delta > 0 else ""
            strict_str = colorize(f"  strict: {old_s:.1f}→{new_s:.1f}% ({s_sign}{s_delta:.1f}%)", "dim")
        print(colorize(f"    {name:<22} {old:.1f}% → {new:.1f}%  ({sign}{delta:.1f}%)", color) + strict_str)
    print()


def _show_low_dimension_hints(dim_scores: dict):
    """Show actionable hints for dimensions below 50%."""
    from ..scoring import DIMENSIONS
    static_names = {d.name for d in DIMENSIONS}

    _MECHANICAL_HINTS = {
        "File health": "run `desloppify show structural` — split large files",
        "Code quality": "run `desloppify show smells` — fix code smells",
        "Duplication": "run `desloppify show dupes` — deduplicate functions",
        "Test health": "add tests for uncovered files: `desloppify show test_coverage`",
        "Security": "run `desloppify show security` — fix security issues",
    }

    low = []
    for name, data in dim_scores.items():
        strict = data.get("strict", data.get("score", 100))
        if strict < 50:
            if name in static_names:
                hint = _MECHANICAL_HINTS.get(name, "run `desloppify show` for details")
            else:
                hint = "run `desloppify review --prepare` to assess"
            low.append((name, strict, hint))

    if not low:
        return

    low.sort(key=lambda x: x[1])
    print(colorize("  Needs attention:", "yellow"))
    for name, score, hint in low:
        print(colorize(f"    {name} ({score:.0f}%) — {hint}", "yellow"))
    print()
