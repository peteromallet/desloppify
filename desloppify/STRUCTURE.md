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
├── state.py            # Public persistent-state facade
├── utils.py            # File discovery, path helpers, formatting
├── hook_registry.py    # Detector-safe registry for language hook modules
├── app/                # CLI app layer (commands, parser wiring, output)
│   ├── cli_support/
│   ├── commands/
│   └── output/
│
├── engine/             # Scan/scoring/state engine internals
│   ├── detectors/      # Layer 1: Generic algorithms (zero language knowledge)
│   ├── planning/       # Prioritization and plan generation
│   ├── policy/         # Shared policy datasets (zones, scoring policy)
│   ├── scoring_internal/
│   ├── state_internal/
│   └── work_queue_internal/
│
├── intelligence/       # Subjective/narrative/review intelligence layer
│   ├── narrative/
│   ├── integrity/
│   └── review/
│
├── languages/          # Layer 2 + 3: Language plugins (auto-discovered)
│   ├── __init__.py     # Registry: @register_lang, get_lang, auto-detect, structural validation
│   ├── framework/      # Shared plugin framework internals (contracts/discovery/runtime/factories)
│   ├── _shared/        # Shared prompts/templates/assets across plugins
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
│   │
│   ├── csharp/         # Everything C#/.NET
│   │   ├── __init__.py # CSharpConfig + phase runners + config data
│   │   ├── commands.py # detect-subcommand wrappers + command registry
│   │   ├── extractors.py  # extract_csharp_functions, extract_csharp_classes
│   │   ├── phases.py   # C# phase orchestration
│   │   ├── detectors/  # C#-specific detector implementations
│   │   │   ├── deps.py     # C# dependency graph builder (using + project refs)
│   │   │   └── security.py # C# security checks
│   │   └── fixers/     # C# auto-fixers (none yet — structural placeholder)
│   ├── dart/           # Everything Dart/Flutter
│   │   ├── __init__.py # DartConfig + phase runners
│   │   ├── phases.py   # Dart phase orchestration
│   │   ├── detectors/  # Dart-specific detectors
│   │   └── fixers/     # Dart auto-fixers (none yet)
│   └── gdscript/       # Everything GDScript (Godot)
│       ├── __init__.py # GDScriptConfig + phase runners
│       ├── phases.py   # GDScript phase orchestration
│       ├── detectors/  # GDScript-specific detectors
│       └── fixers/     # GDScript auto-fixers (none yet)
│
```

## Three-Layer Architecture

```
Layer 1: engine/detectors/ Generic algorithms. Data-in, data-out. Zero language imports.
Layer 2: languages/framework/base/ Shared contracts/helpers. Normalize raw results → tiered findings.
Layer 3: languages/<name>/ Language orchestration. Config + phase runners + extractors + CLI wrappers.
```

**Import direction**: `languages/` → `engine/detectors/`. Never the reverse. Enforced — no `desloppify/engine/detectors` file imports from `languages/`.
Detectors needing language-specific behavior use `hook_registry.get_lang_hook(...)` only.

## Data Flow

```
scan:    LangConfig → LangRun(phases + runtime state) → generate_findings() → merge_scan(lang=, scan_path=) → state-{lang}.json
fix:     LangConfig.fixers → fixer.fix() → resolve in state
detect:  LangConfig.detect_commands[name](args) → display
```

## Contracts

**Detector**: `detect_*(data, config) → list[dict]` — generic algorithm. All params required (no defaults that assume a language).

**Extractor**: `extract_*(filepath) → list[FunctionInfo|ClassInfo]` — language-specific parsing that produces shared data types.

**Phase runner**: `_phase_*(path, lang) → list[dict]` — thin orchestrators: extractors → generic algorithms → shared normalization helpers. Config data (signals, rules, thresholds) lives as module-level constants in `phases.py`.

**Cmd wrapper**: `cmd_<name>(args) → None` — CLI display function in `languages/<name>/commands.py`. Each language owns all its cmd wrappers — no generic cmd_* in `detectors/`.

**LangConfig**: Static language contract dataclass in `languages/<name>/__init__.py`. It owns declarative config (phases, detectors, thresholds, hooks) only.

**LangRun**: Per-invocation runtime wrapper (`languages/framework/runtime.py`) carrying mutable scan state (`zone_map`, `dep_graph`, `complexity_map`, review cache, runtime settings/options). Commands and `generate_findings` always execute phases against `LangRun`.

Key `LangConfig` fields: `phases`, `build_dep_graph`, `detect_commands`, `file_finder`, `extract_functions`, `detect_markers`, `entry_patterns`, `barrel_names`. Auto-discovered — adding a language requires zero shared-core edits. Validated at registration: each plugin must have `commands.py`, `extractors.py`, `phases.py`, `move.py`, `review.py`, `test_coverage.py`, plus `detectors/`, `fixers/`, and `tests/` (each dir with `__init__.py`), and at least one `tests/test_*.py`. `detect_commands` keys are standardized to lowercase snake_case.

Bootstrap command: `desloppify dev scaffold-lang <name> --extension .ext --marker <root-marker>`.

## Command Layer Contracts

- Entry modules should stay thin and focused on argument flow + composition:
  - `app/commands/review/cmd.py`
  - `app/commands/scan/scan_reporting_dimensions.py`
  - `app/cli_support/parser.py`
- Behavioral logic belongs in delegated modules:
  - review flow: `app/commands/review/prepare.py`, `app/commands/review/batches.py`, `app/commands/review/import_cmd.py`, `app/commands/review/runtime.py`
  - scan reporting flow: `app/commands/scan/scan_reporting_progress.py`, `app/commands/scan/scan_reporting_breakdown.py`, `app/commands/scan/scan_reporting_subjective_common.py`, `app/commands/scan/scan_reporting_subjective_integrity.py`, `app/commands/scan/scan_reporting_subjective_output.py`
  - subjective reporting internals: `app/commands/scan/scan_reporting_subjective_common.py`, `app/commands/scan/scan_reporting_subjective_integrity.py`, `app/commands/scan/scan_reporting_subjective_output.py`
  - parser group construction: `app/cli_support/parser_groups.py`
- Compatibility wrappers are not allowed; use canonical helper modules and update tests/patch points to match.

## Allowed Dynamic Import Zones

Dynamic loading is restricted to explicit extension points:

- `languages/__init__.py` for plugin discovery and registration
- `hook_registry.py` for optional detector-safe hook resolution

All other module relationships should use static imports.

## State Ownership Rules

- Persistent schema and merge semantics are owned by `state.py` and `engine/state_internal/`.
- Per-run mutable execution state is owned by `languages/framework/runtime.py` (`LangRun`), not by `LangConfig`.
- Command modules may orchestrate load/save/merge, but should not introduce ad-hoc persisted fields.
- Review packet artifacts under `.desloppify/` are runtime artifacts, not persisted source-of-truth state.

## Non-Obvious Behavior

- **State scoping**: `merge_scan` only auto-resolves findings matching the scan's `lang` and `scan_path`. A Python scan never touches TS state.
- **Suspect guard**: If a detector drops from >=5 findings to 0, its disappearances are held (bypass: `--force-resolve`).
- **Scoring**: Weighted by tier (T4=4x, T1=1x). Strict score penalizes both open and wontfix findings.
- **Finding ID format**: `detector::file::name` — if a detector changes naming, findings lose state continuity.
- **Cascade effects**: Fixing one category (e.g. dead exports) can create work for the next (unused vars). Score can temporarily drop.
