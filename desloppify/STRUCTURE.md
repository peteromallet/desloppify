# Desloppify — Technical Internals

## Philosophy

Desloppify gives AI coding agents a structured process for bringing codebases to a very high standard — with the human always in the loop. It works with any language via a plugin system.

Code quality breaks into two layers. **Mechanical** issues — dead code, duplication, complexity, smells — can be detected deterministically and often fixed automatically. **Subjective** issues — architecture fitness, convention drift, error strategy consistency — require judgment that only a human can provide.

Desloppify handles the mechanical layer aggressively: scan, track, coach the agent through cleanup. Findings persist across scans. A narrative system recognizes momentum, stagnation, and regression, and adjusts its guidance accordingly. Prioritization is opinionated — security and structural health outweigh style nits.

But the tool is deliberately non-prescriptive about *what* to fix. It gives the agent a shortlist and trusts the human to either solve each issue or mindfully dismiss it with a reason. The goal isn't a perfect score — it's making technical debt visible, tractable, and progressively smaller.

See README.md for usage.

## Directory Layout

```
desloppify/
├── cli.py              # Argparse, main(), shared helpers
├── plan.py             # Detector orchestration + finding normalization
├── state.py            # Persistent state: load/save, merge_scan, scoring
├── utils.py            # File discovery, path helpers, formatting
├── visualize.py        # tree + viz commands
│
├── detectors/          # Layer 1: Generic algorithms (zero language knowledge)
│   ├── base.py         # Shared data types: FunctionInfo, ClassInfo, ComplexitySignal, GodRule
│   ├── dupes.py        # detect_duplicates(functions, threshold) → pairs
│   ├── gods.py         # detect_gods(classes, rules) → god entries
│   ├── complexity.py   # detect_complexity(path, signals, file_finder) → scored files
│   ├── large.py        # detect_large_files(path, file_finder, threshold) → large files
│   ├── graph.py        # detect_cycles(graph), get_coupling_score(file, graph)
│   ├── orphaned.py     # detect_orphaned_files(path, graph, extensions, ...)
│   ├── single_use.py   # detect_single_use_abstractions(path, graph, barrel_names)
│   ├── coupling.py     # detect_coupling_violations(graph, shared_prefix, tools_prefix)
│   ├── naming.py       # detect_naming_inconsistencies(path, file_finder, skip_names)
│   └── passthrough.py  # classify_params(params, body, pattern_fn) — shared core
│
├── lang/               # Layer 2 + 3: Language plugins (auto-discovered)
│   ├── __init__.py     # Registry: @register_lang, get_lang, auto-detect, structural validation
│   ├── base.py         # LangConfig + shared finding helpers (make_*_findings)
│   │
│   ├── typescript/     # Everything TypeScript/React
│   │   ├── __init__.py # TypeScriptConfig assembly
│   │   ├── phases.py   # Phase runners + config constants (signals, rules)
│   │   ├── commands.py # detect-subcommand wrappers + command registry
│   │   ├── extractors.py  # extract_ts_functions, extract_ts_components, detect_passthrough_components
│   │   ├── move.py     # Move/import-rewrite helpers for `desloppify move`
│   │   ├── review.py   # Subjective-review language guidance
│   │   ├── test_coverage.py # Test mapping + quality heuristics
│   │   ├── detectors/  # TS-specific detector implementations
│   │   │   ├── smells.py   # TS smell rules + brace-tracked multi-line helpers
│   │   │   ├── deps.py     # TS import graph builder + dynamic import detection
│   │   │   ├── unused.py   # tsc-based unused detection
│   │   │   └── ...         # logs, exports, deprecated, react, concerns, patterns, props
│   │   └── fixers/     # TS auto-fixers (unused imports, dead exports, etc.)
│   │
│   └── python/         # Everything Python
│       ├── __init__.py # PythonConfig assembly
│       ├── phases.py   # Phase runners + config constants (signals, rules)
│       ├── commands.py # detect-subcommand wrappers + command registry
│       ├── extractors.py  # extract_py_functions, extract_py_classes, detect_passthrough_functions
│       ├── move.py     # Move/import-rewrite helpers for `desloppify move`
│       ├── review.py   # Subjective-review language guidance
│       ├── test_coverage.py # Test mapping + quality heuristics
│       ├── detectors/  # PY-specific detector implementations
│       │   ├── smells.py   # PY smell rules + indentation-tracked multi-line helpers
│       │   ├── deps.py     # Python import graph builder
│       │   └── unused.py   # ruff-based unused detection
│       └── fixers/     # PY auto-fixers (none yet — structural placeholder)
│
├── commands/           # One file per CLI subcommand
```

## Three-Layer Architecture

```
Layer 1: detectors/       Generic algorithms. Data-in, data-out. Zero language knowledge.
Layer 2: lang/base.py     Shared finding helpers. Normalize raw results → tiered findings.
Layer 3: lang/<name>/     Language orchestration. Config + phase runners + extractors + CLI wrappers.
```

**Import direction**: `lang/` → `detectors/`. Never the reverse. Enforced — no `detectors/` file imports from `lang/`.

## Data Flow

```
scan:    LangConfig.phases → generate_findings() → merge_scan(lang=, scan_path=) → state-{lang}.json
fix:     LangConfig.fixers → fixer.fix() → resolve in state
detect:  LangConfig.detect_commands[name](args) → display
```

## Contracts

**Detector**: `detect_*(data, config) → list[dict]` — generic algorithm. All params required (no defaults that assume a language).

**Extractor**: `extract_*(filepath) → list[FunctionInfo|ClassInfo]` — language-specific parsing that produces shared data types.

**Phase runner**: `_phase_*(path, lang) → list[dict]` — thin orchestrators: extractors → generic algorithms → shared normalization helpers. Config data (signals, rules, thresholds) lives as module-level constants in `phases.py`.

**Cmd wrapper**: `cmd_<name>(args) → None` — CLI display function in `lang/<name>/commands.py`. Each language owns all its cmd wrappers — no generic cmd_* in `detectors/`.

**LangConfig**: Dataclass in `lang/<name>/__init__.py`. Key fields: `phases`, `build_dep_graph`, `detect_commands`, `file_finder`, `extract_functions`, `detect_markers`, `entry_patterns`, `barrel_names`. Auto-discovered — adding a language requires zero shared-core edits. Validated at registration: each plugin must have `commands.py`, `extractors.py`, `phases.py`, `move.py`, `review.py`, `test_coverage.py`, plus `detectors/`, `fixers/`, and `tests/` (each dir with `__init__.py`), and at least one `tests/test_*.py`. `detect_commands` keys are standardized to lowercase snake_case.

Bootstrap command: `desloppify dev scaffold-lang <name> --extension .ext --marker <root-marker>`.

## Non-Obvious Behavior

- **State scoping**: `merge_scan` only auto-resolves findings matching the scan's `lang` and `scan_path`. A Python scan never touches TS state.
- **Suspect guard**: If a detector drops from >=5 findings to 0, its disappearances are held (bypass: `--force-resolve`).
- **Scoring**: Weighted by tier (T4=4x, T1=1x). Strict score excludes wontfix from both numerator and denominator.
- **Finding ID format**: `detector::file::name` — if a detector changes naming, findings lose state continuity.
- **Cascade effects**: Fixing one category (e.g. dead exports) can create work for the next (unused vars). Score can temporarily drop.
