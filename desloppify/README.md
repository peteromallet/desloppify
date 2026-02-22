# Desloppify — Technical Internals

Traditional tools catch mechanical issues — linters, formatters, dead code finders. Desloppify wraps those but the point is **subjective analysis**: structured LLM prompts about architecture, design quality, and convention consistency, tracked as scored findings. The score weights subjective findings heavily because that's what actually moves the needle. See the top-level README for philosophy and usage.

## Directory Layout

```
desloppify/
├── cli.py              # Argparse, main()
├── state.py            # Persistent-state facade
├── utils.py            # File discovery, path helpers
├── hook_registry.py    # Detector-safe language hook registry
├── app/                # CLI layer (commands, parser, output)
├── engine/             # Scan/scoring/state internals
│   ├── detectors/      # Generic algorithms (zero language knowledge)
│   ├── planning/       # Prioritization and plan generation
│   ├── policy/         # Zones, scoring policy
│   ├── _scoring/
│   ├── _state/
│   └── _work_queue/
├── intelligence/       # Subjective/narrative/review layer
│   ├── narrative/
│   ├── integrity/
│   └── review/
└── languages/          # Language plugins (auto-discovered, see languages/README.md)
    ├── _framework/     # Shared plugin framework, generic_lang(), tree-sitter
    ├── python/         # Full plugins (custom detectors, fixers, review dims)
    ├── typescript/
    ├── csharp/, dart/, gdscript/
    └── go/, rust/, ruby/, java/, ... (23 generic plugins)
```

## Architecture

```
Layer 1: engine/detectors/       Generic algorithms. Data-in, data-out. Zero language imports.
Layer 2: languages/_framework/   Shared contracts/helpers. Normalize raw results → tiered findings.
Layer 3: languages/<name>/       Language config + phases + extractors + detectors + fixers.
```

**Import direction**: `languages/` → `engine/detectors/`. Never the reverse. Detectors needing language-specific behavior use `hook_registry.get_lang_hook(...)`.

## Data Flow

```
scan:    LangConfig → LangRun(phases) → generate_findings() → merge_scan() → state-{lang}.json
fix:     LangConfig.fixers → fixer.fix() → resolve in state
detect:  LangConfig.detect_commands[name](args) → display
```

## Contracts

**Detector**: `detect_*(data, config) → list[dict]` — generic algorithm, no language assumptions.

**Phase runner**: `_phase_*(path, lang) → (list[Finding], dict[str, int])` — thin orchestrator calling extractors → generic algorithms → normalization.

**LangConfig**: Static language contract. Owns phases, detectors, thresholds, hooks.

**LangRun**: Per-invocation runtime wrapper (`_framework/runtime.py`) carrying mutable state (zone_map, dep_graph, complexity_map). Phases execute against LangRun, not LangConfig.

## Rules

- Entry command modules stay thin — behavioral logic in delegated modules
- Dynamic imports only in `languages/__init__.py` (discovery) and `hook_registry.py` (hooks)
- Persistent schema owned by `state.py` + `engine/_state/`. Command modules don't introduce ad-hoc persisted fields
- `LangRun` owns per-run mutable state, not `LangConfig`

## Non-Obvious Behavior

- **State scoping**: `merge_scan` only auto-resolves findings matching the scan's `lang` and `scan_path`. A Python scan never touches TS state.
- **Suspect guard**: If a detector drops from >=5 findings to 0, disappearances are held (bypass: `--force-resolve`).
- **Scoring**: Weighted by tier (T4=4x, T1=1x). Strict score penalizes both open and wontfix.
- **Cascade effects**: Fixing one category (e.g. unused imports) can surface work for the next (unused vars). Score can temporarily drop.
- **Tree-sitter optional**: All tree-sitter features degrade gracefully. Without `tree-sitter-language-pack`, generic plugins fall back to tool-only mode.
