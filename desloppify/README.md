# Desloppify — Technical Internals

## Philosophy

There are plenty of traditional tools that catch mechanical code issues — linters, formatters, dead code finders, complexity checkers. They're good at what they do and desloppify wraps many of them. But mechanical issues aren't usually what makes a codebase hard to work with.

The real problems are **subjective and structural**: poor abstractions, tangled dependencies, inconsistent patterns, modules that do too many things, naming that misleads. These are the things that slow you down, cause bugs, and make onboarding painful. Traditional static analysis can't see them because they require judgment — understanding intent, recognizing design drift, evaluating tradeoffs.

LLMs are now good enough to recognize these problems when given the right harness. Desloppify is that harness: it gives an LLM structured questions about architecture, convention consistency, error strategy, and design quality — then tracks the answers as scored findings alongside the mechanical detections. The result is a single health score that captures both what a linter can see and what only a thoughtful review can catch.

The tool is deliberately non-prescriptive about *what* to fix. It gives the agent a prioritized shortlist and trusts the human to either solve each issue or mindfully dismiss it with a reason. A narrative system recognizes momentum, stagnation, and regression, and adjusts its coaching accordingly. The goal isn't a perfect score — it's making technical debt visible, tractable, and progressively smaller.

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
│   ├── _scoring/
│   ├── _state/
│   └── _work_queue/
│
├── intelligence/       # Subjective/narrative/review intelligence layer
│   ├── narrative/
│   ├── integrity/
│   └── review/
│
├── languages/          # Layer 2 + 3: Language plugins (auto-discovered)
│   ├── __init__.py     # Registry: @register_lang, get_lang, auto-detect, structural validation
│   ├── _framework/     # Shared plugin framework
│   │   ├── generic.py          # generic_lang() factory for tool-based plugins
│   │   ├── base/               # Contracts, types, shared phase builders
│   │   ├── discovery.py        # Plugin auto-discovery
│   │   ├── resolution.py       # get_lang(), auto_detect_lang()
│   │   ├── runtime.py          # LangRun: per-invocation state wrapper
│   │   └── treesitter/         # Tree-sitter integration (optional)
│   │       ├── __init__.py     # TreeSitterLangSpec dataclass, cache API
│   │       ├── _specs.py       # Per-language tree-sitter query definitions
│   │       ├── _extractors.py  # Function/class extraction via AST
│   │       ├── _imports.py     # Import parsing + per-language resolvers
│   │       ├── _normalize.py   # Body normalization for duplicate detection
│   │       ├── _cache.py       # Scan-scoped parse tree cache
│   │       ├── _complexity.py  # AST complexity signals (nesting, CC, params, callbacks)
│   │       ├── _smells.py      # Cross-language AST smell detectors
│   │       ├── _cohesion.py    # Responsibility cohesion (call graph components)
│   │       └── _unused_imports.py  # Unused import detection
│   │       └── phases.py     # Tree-sitter phase factories for plugins
│   │
│   │── Generic plugins (single-file, tool-based):
│   ├── go/             # golangci-lint + go vet + tree-sitter
│   ├── rust/           # cargo clippy + cargo check + tree-sitter
│   ├── ruby/           # rubocop + tree-sitter
│   ├── java/           # checkstyle + tree-sitter
│   ├── kotlin/         # ktlint + detekt + tree-sitter
│   ├── swift/          # swiftlint + tree-sitter
│   ├── php/            # phpstan + tree-sitter
│   ├── scala/          # scalac + tree-sitter
│   ├── elixir/         # credo + tree-sitter
│   ├── haskell/        # hlint + tree-sitter
│   ├── lua/            # luacheck + tree-sitter
│   ├── perl/           # perlcritic + tree-sitter
│   ├── clojure/        # clj-kondo + tree-sitter
│   ├── zig/            # zig build + tree-sitter
│   ├── nim/            # nim check + tree-sitter
│   ├── bash/           # shellcheck + tree-sitter
│   ├── powershell/     # PSScriptAnalyzer + tree-sitter
│   ├── javascript/     # eslint + tree-sitter
│   ├── erlang/         # dialyzer + tree-sitter
│   ├── ocaml/          # ocaml compiler + tree-sitter
│   ├── fsharp/         # dotnet build + tree-sitter
│   └── ... (28 languages total)
│
│   │── Full plugins (multi-module, language-specific detectors):
│   ├── typescript/     # Everything TypeScript/React
│   │   ├── __init__.py # TypeScriptConfig assembly
│   │   ├── phases.py   # Phase runners + config constants (signals, rules)
│   │   ├── commands.py # detect-subcommand wrappers + command registry
│   │   ├── extractors.py  # extract_ts_functions, extract_ts_components
│   │   ├── move.py     # Move/import-rewrite helpers
│   │   ├── review.py   # Subjective-review language guidance
│   │   ├── test_coverage.py # Test mapping + quality heuristics
│   │   ├── detectors/  # TS-specific detector implementations
│   │   └── fixers/     # TS auto-fixers (unused imports, vars, logs, etc.)
│   │
│   ├── python/         # Everything Python
│   │   └── (same structure as typescript/)
│   │
│   ├── csharp/         # C#/.NET (partial — structural + coupling + security)
│   ├── dart/           # Dart/Flutter (partial)
│   └── gdscript/       # GDScript/Godot (partial)
│
```

## Three-Layer Architecture

```
Layer 1: engine/detectors/ Generic algorithms. Data-in, data-out. Zero language imports.
Layer 2: languages/_framework/base/ Shared contracts/helpers. Normalize raw results → tiered findings.
Layer 3: languages/<name>/ Language orchestration. Config + phase runners + extractors + CLI wrappers.
```

**Import direction**: `languages/` → `engine/detectors/`. Never the reverse. Enforced — no `desloppify/engine/detectors` file imports from `languages/`.
Detectors needing language-specific behavior use `hook_registry.get_lang_hook(...)` only.

## Language Plugin System

Plugins come in three tiers of depth, all auto-discovered at startup:

### Tier 1: Generic plugin (`generic_lang()`)

A single `__init__.py` that calls `generic_lang()` with tool specs. ~20 lines. No custom detectors.

```python
# languages/go/__init__.py
from desloppify.languages._framework.generic import generic_lang
from desloppify.languages._framework.treesitter._specs import GO_SPEC

generic_lang(
    name="go",
    extensions=[".go"],
    tools=[
        {"label": "golangci-lint", "cmd": "golangci-lint run --out-format=json",
         "fmt": "golangci", "id": "golangci_lint", "tier": 2,
         "fix_cmd": "golangci-lint run --fix"},
        {"label": "go vet", "cmd": "go vet ./...",
         "fmt": "gnu", "id": "vet_error", "tier": 3},
    ],
    exclude=["vendor", "testdata"],
    detect_markers=["go.mod"],
    treesitter_spec=GO_SPEC,   # enables AST-powered analysis
)
```

**What you get automatically:**
- External tool execution + output parsing (`gnu`, `json`, `golangci`, `cargo`, `rubocop`, `eslint` formats)
- Auto-fix via `fix_cmd` (if provided)
- Detector + scoring policy registration per tool
- Security scanning (cross-language patterns)
- Subjective review + boilerplate duplication + duplicate detection (shared tail phases)
- Zone classification (test/vendor/config/generated)

**What `treesitter_spec` adds (when `tree-sitter-language-pack` is installed):**
- Function extraction → duplicate detection
- Import parsing → dependency graph → coupling/orphan/cycle detection + test coverage
- AST complexity signals: nesting depth, cyclomatic complexity, long functions, parameter count, callback depth
- God class detection (methods > 15, LOC > 500, attributes > 10)
- Empty catch/except block detection
- Unreachable code detection
- Responsibility cohesion (disconnected function clusters)
- Unused import detection
- Signature variance (same function name, different signatures across files)

### Tier 2: Adding a new generic plugin

1. Create `languages/<name>/__init__.py`
2. Call `generic_lang()` with tool specs
3. Optionally add a `TreeSitterLangSpec` in `treesitter/_specs.py` (with import resolver in `_imports.py` if the language has local imports)
4. Done — auto-discovered, zero shared-core edits

To add a new tree-sitter spec:

```python
# In treesitter/_specs.py
MY_SPEC = TreeSitterLangSpec(
    grammar="mylang",              # tree-sitter grammar name
    function_query="""             # S-expression: capture @func, @name, @body
        (function_definition
            name: (identifier) @name
            body: (block) @body) @func
    """,
    comment_node_types=frozenset({"comment"}),
    import_query="""               # Optional: capture @import and @path
        (import_statement
            source: (string) @path) @import
    """,
    resolve_import=resolve_my_import,  # Optional: (text, source_file, scan_path) -> path | None
    class_query="""                # Optional: capture @class, @name, @body
        (class_definition
            name: (identifier) @name
            body: (class_body) @body) @class
    """,
)
```

To add an import resolver:

```python
# In treesitter/_imports.py
def resolve_my_import(import_text: str, source_file: str, scan_path: str) -> str | None:
    """Resolve import text to an absolute file path, or None for external/stdlib."""
    if is_stdlib(import_text):
        return None
    candidate = os.path.join(os.path.dirname(source_file), import_text + ".ext")
    return candidate if os.path.isfile(candidate) else None
```

To add a new output parser format:

```python
# In framework/generic.py — add to _PARSERS dict
def parse_myformat(output: str, scan_path: Path) -> list[dict]:
    """Parse tool output into [{file, line, message}]."""
    ...
```

### Tier 3: Full plugin (`@register_lang()`)

Package directory with hand-coded phases, language-specific detectors, and full control. Used by Python, TypeScript, C#, Dart, GDScript.

```python
# languages/mylang/__init__.py
from desloppify.languages import register_lang

@register_lang("mylang")
class MyLangConfig(LangConfig):
    def __init__(self):
        super().__init__(
            name="mylang", extensions=[".ml"], phases=[...],
            build_dep_graph=my_dep_builder, extract_functions=my_extractor, ...
        )

    def detect_lang_security(self, files, zone_map):
        """Hook: called by shared phase_security() for lang-specific checks."""
        return my_security_checks(files, zone_map)
```

**Required package structure** (validated at registration):
`commands.py`, `extractors.py`, `phases.py`, `move.py`, `review.py`, `test_coverage.py`, plus `detectors/`, `fixers/`, and `tests/` directories.

Bootstrap command: `desloppify dev scaffold-lang <name> --extension .ext --marker <root-marker>`.

### Extending existing plugins

Generic plugins are designed to be improved incrementally. Here are the common tasks:

#### Add a linter tool to an existing language

Edit `languages/<name>/__init__.py` — append to the `tools` list:

```python
generic_lang(
    name="go",
    tools=[
        # ... existing tools ...
        {"label": "staticcheck", "cmd": "staticcheck ./...",
         "fmt": "gnu", "id": "staticcheck_warning", "tier": 2},
    ],
    ...
)
```

Each tool entry needs: `label` (display name), `cmd` (shell command), `fmt` (parser format), `id` (unique detector name), `tier` (1-4). Add `fix_cmd` for auto-fix support.

#### Add or improve a tree-sitter spec

Edit `treesitter/_specs.py`. Common improvements:

- **Add `class_query`** → enables god class detection
- **Add `import_query` + `resolve_import`** → enables coupling, orphan, cycle, test coverage, unused import analysis
- **Improve `function_query`** → better duplicate detection (capture more function forms: methods, lambdas, arrow functions)

Use `tree-sitter-language-pack`'s playground or `tree-sitter parse` to test queries against real code. Queries must capture `@func`/`@name`/`@body` (functions), `@class`/`@name`/`@body` (classes), or `@import`/`@path` (imports).

#### Improve an import resolver

Edit `treesitter/_imports.py`. Common fixes:

- Handle additional source roots (e.g., `src/`, `lib/`, `app/`)
- Support more file extensions (e.g., `.jsx` alongside `.js`)
- Skip additional stdlib/framework modules to reduce false positive edges
- Handle aliased imports or re-exports

#### Add language-specific security checks

For a generic plugin — attach to the returned config:

```python
cfg = generic_lang("go", ...)

def _detect_go_security(files, zone_map):
    findings, potentials = [], {}
    # ... check for unsafe pointer usage, unvalidated http.Get, etc.
    return findings, potentials

cfg.detect_lang_security = _detect_go_security
```

The shared `phase_security()` runner checks for `detect_lang_security` via `hasattr()` and calls it automatically alongside the cross-language security checks.

#### Add a cross-language AST detector

New detectors that work across all tree-sitter-enabled languages go in `treesitter/`:

1. Create `treesitter/_my_detector.py` with a function like `detect_X(file_list, spec) -> list[dict]`
2. Wire it into `generic.py` via a new `_make_X_phase()` factory function
3. Add the phase to the `generic_lang()` phase list (guarded by `if has_treesitter`)

#### Add a new complexity signal

Edit `treesitter/_complexity.py`:

```python
def make_my_signal_compute(spec):
    def compute(content, lines, *, _filepath=""):
        # Parse file, analyze AST, return (count, label) or None
        ...
    return compute
```

Then add it to `_make_structural_phase()` in `generic.py`:

```python
signals.append(ComplexitySignal("my_signal", None, weight=2, threshold=10,
    compute=make_my_signal_compute(treesitter_spec)))
```

### Upgrading generic → full

Only needed when you want things generic plugins can't provide: custom per-line smell detectors, language-specific coupling rules, custom fixers with AST rewriting, or full control over phase ordering.

The path is incremental:

1. **Start generic** — `generic_lang()` with tool specs + tree-sitter
2. **Extend in-place** — add security hooks, improve specs/resolvers (stays generic)
3. **Go full package** — when you need custom smell detectors, coupling rules, or fixers, switch to `@register_lang()` with a package directory. Bootstrap: `desloppify dev scaffold-lang <name> --extension .ext --marker <root-marker>`

Generic plugins should NOT mirror the full plugin directory structure. They are intentionally minimal — a single `__init__.py` that calls `generic_lang()`. The full package structure (`commands.py`, `extractors.py`, `phases.py`, `move.py`, `review.py`, `test_coverage.py`, `detectors/`, `fixers/`, `tests/`) is only required for `@register_lang()` plugins and is validated at registration.

A full plugin can still reuse generic building blocks:
- `_run_tool()` for external tool execution
- Tree-sitter extractors (`ts_extract_functions`, `ts_extract_classes`, `ts_build_dep_graph`)
- Shared phase builders (`detector_phase_security()`, `detector_phase_test_coverage()`, `shared_subjective_duplicates_tail()`)
- Import resolvers from `_imports.py`

## Data Flow

```
scan:    LangConfig → LangRun(phases + runtime state) → generate_findings() → merge_scan(lang=, scan_path=) → state-{lang}.json
fix:     LangConfig.fixers → fixer.fix() → resolve in state
detect:  LangConfig.detect_commands[name](args) → display
```

## Contracts

**Detector**: `detect_*(data, config) → list[dict]` — generic algorithm. All params required (no defaults that assume a language).

**Extractor**: `extract_*(filepath) → list[FunctionInfo|ClassInfo]` — language-specific parsing that produces shared data types.

**Phase runner**: `_phase_*(path, lang) → (list[Finding], dict[str, int])` — thin orchestrators: extractors → generic algorithms → shared normalization helpers. Config data (signals, rules, thresholds) lives as module-level constants in `phases.py`.

**Cmd wrapper**: `cmd_<name>(args) → None` — CLI display function in `languages/<name>/commands.py`. Each language owns all its cmd wrappers — no generic cmd_* in `detectors/`.

**LangConfig**: Static language contract dataclass in `languages/<name>/__init__.py`. It owns declarative config (phases, detectors, thresholds, hooks) only.

**LangRun**: Per-invocation runtime wrapper (`languages/_framework/runtime.py`) carrying mutable scan state (`zone_map`, `dep_graph`, `complexity_map`, review cache, runtime settings/options). Commands and `generate_findings` always execute phases against `LangRun`.

## Command Layer Contracts

- Entry modules should stay thin and focused on argument flow + composition:
  - `app/commands/review/cmd.py`
  - `app/commands/scan/scan_reporting_dimensions.py`
  - `app/cli_support/parser.py`
- Behavioral logic belongs in delegated modules:
  - review flow: `app/commands/review/prepare.py`, `app/commands/review/batches.py`, `app/commands/review/import_cmd.py`, `app/commands/review/runtime.py`
  - scan reporting flow: `app/commands/scan/scan_reporting_presentation.py`, `app/commands/scan/scan_reporting_subjective.py`
  - subjective reporting internals: `app/commands/scan/scan_reporting_subjective.py`
  - parser group construction: `app/cli_support/parser_groups.py`
- Compatibility wrappers are not allowed; use canonical helper modules and update tests/patch points to match.

## Allowed Dynamic Import Zones

Dynamic loading is restricted to explicit extension points:

- `languages/__init__.py` for plugin discovery and registration
- `hook_registry.py` for optional detector-safe hook resolution

All other module relationships should use static imports.

## State Ownership Rules

- Persistent schema and merge semantics are owned by `state.py` and `engine/_state/`.
- Per-run mutable execution state is owned by `languages/_framework/runtime.py` (`LangRun`), not by `LangConfig`.
- Command modules may orchestrate load/save/merge, but should not introduce ad-hoc persisted fields.
- Review packet artifacts under `.desloppify/` are runtime artifacts, not persisted source-of-truth state.

## Non-Obvious Behavior

- **State scoping**: `merge_scan` only auto-resolves findings matching the scan's `lang` and `scan_path`. A Python scan never touches TS state.
- **Suspect guard**: If a detector drops from >=5 findings to 0, its disappearances are held (bypass: `--force-resolve`).
- **Scoring**: Weighted by tier (T4=4x, T1=1x). Strict score penalizes both open and wontfix findings.
- **Finding ID format**: `detector::file::name` — if a detector changes naming, findings lose state continuity.
- **Cascade effects**: Fixing one category (e.g. unused imports) can create work for the next (unused vars). Score can temporarily drop.
- **Tree-sitter optional**: All tree-sitter features degrade gracefully. If `tree-sitter-language-pack` is not installed, generic plugins fall back to tool-only mode (no function extraction, no import analysis, no AST complexity).
