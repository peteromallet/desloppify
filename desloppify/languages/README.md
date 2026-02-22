# Languages

Desloppify supports 28 languages through a plugin system with two tiers: **full plugins** with hand-written detectors and subjective review, and **generic plugins** that wrap external linters and optionally use tree-sitter for AST analysis.

## Full Plugins

These have custom detectors, language-specific smell analysis, subjective review dimensions, auto-fixers, and deep scoring. They're multi-module packages with the full plugin contract.

| Language | Path | Key capabilities |
|----------|------|-----------------|
| **Python** | `python/` | AST smell detection, ruff/bandit adapters, import-linter, unused detection, security, auto-fix |
| **TypeScript** | `typescript/` | React-aware detectors, knip adapter, 7 auto-fixers, props/exports/concerns analysis |
| **C#/.NET** | `csharp/` | Structural + coupling + security, dotnet-based dep analysis |
| **Dart** | `dart/` | Flutter-aware, pubspec integration, test coverage mapping |
| **GDScript** | `gdscript/` | Godot scene-aware, tree-sitter phases, shared framework helpers |

Example: `python/` — see `python/__init__.py` for the full `@register_lang()` config with 15+ detector phases, custom extractors, security hooks, and review guidance.

## Generic Plugins

These are single-file plugins (~20-40 lines) that call `generic_lang()` with external tool specs. When `tree-sitter-language-pack` is installed, they also get AST-powered analysis for free.

| Language | Path | Tools | Tree-sitter |
|----------|------|-------|-------------|
| Go | `go/` | golangci-lint, go vet | functions, methods, imports, structs |
| Rust | `rust/` | cargo clippy, cargo check | functions, imports, structs |
| Ruby | `ruby/` | rubocop | functions, methods, classes, imports |
| Java | `java/` | checkstyle | functions, constructors, classes, imports |
| Kotlin | `kotlin/` | ktlint, detekt | functions, classes, imports |
| Swift | `swift/` | swiftlint | functions, classes |
| PHP | `php/` | phpstan | functions, methods, classes, imports |
| Scala | `scala/` | scalac | functions, classes, imports |
| Elixir | `elixir/` | credo | functions, imports |
| Haskell | `haskell/` | hlint | functions, imports |
| JavaScript | `javascript/` | eslint | functions, methods, classes, imports |
| C/C++ | `cxx/` | cppcheck | functions, classes, includes |
| Bash | `bash/` | shellcheck | functions, source imports |
| Lua | `lua/` | luacheck | functions, imports |
| Perl | `perl/` | perlcritic | subroutines, imports |
| Clojure | `clojure/` | clj-kondo | functions |
| Zig | `zig/` | zig build | functions, imports |
| Nim | `nim/` | nim check | functions |
| PowerShell | `powershell/` | PSScriptAnalyzer | functions |
| R | `r/` | — | functions, imports |
| Erlang | `erlang/` | dialyzer | functions, imports |
| OCaml | `ocaml/` | ocaml compiler | functions, modules, imports |
| F# | `fsharp/` | dotnet build | functions, imports |

Example: `go/__init__.py` — 40 lines, wraps golangci-lint + go vet, adds Go-specific zone rules and test coverage hooks.

## What Each Tier Gets

### Every plugin (generic or full)
- Security scanning (cross-language patterns)
- Subjective review (LLM-powered design review)
- Boilerplate + duplicate detection
- Zone classification (test/vendor/config/generated)
- Scoring integration (automatic detector → dimension mapping)

### Generic plugins with tree-sitter
All of the above, plus:
- Function/method extraction → duplicate detection
- Import parsing → dependency graph → coupling/orphan/cycle detection
- Test coverage analysis (import-based + naming convention mapping)
- AST complexity: nesting depth, cyclomatic complexity, long functions, parameter count, callback depth
- God class/struct detection (methods > 15, LOC > 500, attributes > 10)
- Responsibility cohesion (disconnected function clusters)
- Unused import detection
- Signature variance analysis
- AST smell detection (empty catch, unreachable code)

### Full plugins additionally get
- Custom per-line smell detectors (language-specific patterns)
- Language-aware auto-fixers
- Custom subjective review dimensions
- Hand-tuned coupling and dependency rules
- Framework-specific detectors (e.g., React hooks, Flutter widgets)

## The Difference

A generic Go plugin runs golangci-lint and gets tree-sitter analysis — that covers most of what you need. A full Python plugin has 15+ hand-written detector phases that understand Python-specific patterns like mutable class variables, `lru_cache` on methods with mutable args, subprocess calls without timeouts, naive regex backtracking, and dozens more. It has auto-fixers that can rewrite imports. It has subjective review dimensions tuned for Python conventions.

The generic system is the right starting point for any language. Only invest in a full plugin when you need detectors that understand language idioms beyond what AST pattern matching and external linters can catch.

## Adding a New Generic Plugin

Create `languages/<name>/__init__.py`:

```python
from desloppify.languages._framework.generic import generic_lang
from desloppify.languages._framework.treesitter._specs import MY_SPEC  # if available

generic_lang(
    name="mylang",
    extensions=[".ml"],
    tools=[
        {"label": "mylinter", "cmd": "mylinter --json .",
         "fmt": "json", "id": "mylinter_issue", "tier": 2,
         "fix_cmd": "mylinter --fix ."},
    ],
    exclude=["vendor"],
    detect_markers=["myproject.toml"],
    treesitter_spec=MY_SPEC,
)
```

That's it. Auto-discovered at startup, zero shared-code edits.

## Upgrading Generic → Full

Only needed when you want things generic plugins can't provide: custom per-line smell detectors, language-specific coupling rules, custom fixers with AST rewriting, or full control over phase ordering.

The path is incremental:

1. **Start generic** — `generic_lang()` with tool specs + tree-sitter
2. **Extend in-place** — add zone rules, test coverage hooks, security hooks (stays generic)
3. **Go full** — when you need custom detectors or fixers, switch to `@register_lang()` with a package directory

Bootstrap: `desloppify dev scaffold-lang <name> --extension .ext --marker <root-marker>`

Required package structure (validated at registration): `__init__.py`, `commands.py`, `extractors.py`, `phases.py`, `move.py`, `review.py`, `test_coverage.py`, plus `detectors/`, `fixers/`, and `tests/` directories.

A full plugin can still reuse generic building blocks — `_run_tool()` for external tools, tree-sitter extractors, shared phase builders (`detector_phase_security()`, `detector_phase_test_coverage()`, `shared_subjective_duplicates_tail()`).

## Shared Framework (`_framework/`)

```
_framework/
├── generic.py           # generic_lang() factory for tool-based plugins
├── base/                # LangConfig, DetectorPhase, FixerConfig contracts
│   ├── types.py         # Core dataclasses
│   ├── shared_phases.py # Shared detector phase runners
│   ├── phase_builders.py # Phase builder helpers
│   └── structural.py   # Structural analysis utilities
├── treesitter/          # Tree-sitter integration (optional)
│   ├── _specs.py        # Per-language tree-sitter query definitions
│   ├── _extractors.py   # Function/class extraction via AST
│   ├── _imports.py      # Import parsing + per-language resolvers
│   ├── _complexity.py   # AST complexity signals
│   ├── _smells.py       # Cross-language AST smell detectors
│   ├── _cohesion.py     # Responsibility cohesion
│   └── _unused_imports.py
├── runtime.py           # LangRun (per-run mutable execution state)
├── resolution.py        # get_lang/available_langs/auto_detect_lang
├── discovery.py         # Plugin auto-discovery
├── commands_base.py     # Shared detect-command factories
└── review_data/         # Shared review dimension JSON payloads
```

## Design Rules

- Import direction: `languages/<name>/` → `engine/detectors/` and `languages/_framework/*`. Never the reverse.
- Keep language plugin code in its language folder
- Keep reusable cross-language framework code in `_framework/`
- Generic plugins should NOT mirror the full plugin directory structure — they are intentionally minimal

## Testing

```bash
# Run all language tests
pytest -q desloppify/tests/lang/common/ desloppify/languages/*/tests/

# Run one language's tests
pytest -q desloppify/languages/go/tests/

# Validate plugin contracts
pytest -q desloppify/tests/lang/common/test_lang_standardization.py
```
