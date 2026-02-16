# C# Language Module

This document explains the C# support in Desloppify in plain language.

It covers:

- What the C# module does
- How scan phases work
- What each file in `desloppify/lang/csharp/` is responsible for
- Which shared files outside this folder affect C# behavior
- Current limits and safe extension points

If you are new to this code, start with the `CSharpConfig` section and then read the "Scan flow" section.

## High-level purpose

The C# module lets Desloppify scan `.cs` codebases and report maintainability issues.

The current scope is an MVP. It focuses on:

- Structural signals
- Coupling signals
- Duplicate logic
- Security patterns
- Subjective review coverage

It does not include C# auto-fixers yet.

## Module map

Files in this folder:

- `desloppify/lang/csharp/__init__.py`
- `desloppify/lang/csharp/commands.py`
- `desloppify/lang/csharp/extractors.py`
- `desloppify/lang/csharp/phases.py`
- `desloppify/lang/csharp/detectors/deps.py`
- `desloppify/lang/csharp/detectors/security.py`
- `desloppify/lang/csharp/detectors/__init__.py`
- `desloppify/lang/csharp/fixers/__init__.py`

### What each file does

`__init__.py`:

- Registers the language as `"csharp"` with `@register_lang("csharp")`
- Defines the `LangConfig` instance (`CSharpConfig`)
- Wires C# phases, thresholds, file finder, dep graph builder, and detect commands
- Defines C# zone rules and entry patterns

`commands.py`:

- Implements language specific `detect` subcommands for C#
- Exposes command registry for:
  - `deps`
  - `cycles`
  - `orphaned`
  - `dupes`
  - `large`
  - `complexity`

`extractors.py`:

- Finds C# files while skipping build artifacts
- Extracts methods for duplicate detection
- Extracts class information for structural analysis
- Normalizes method bodies before hashing for duplicate checks

`phases.py`:

- Defines C# complexity signals and god-class rules
- Implements the C# structural phase runner
- Implements the C# coupling phase runner

`detectors/deps.py`:

- Builds a C# dependency graph from `namespace`, `using`, and `.csproj` references
- Provides C# `detect deps` and `detect cycles` output handlers

`detectors/security.py`:

- Adds C# specific security checks on top of shared security checks
- Currently checks SQL string building, weak RNG usage in security contexts, disabled TLS validation, and unsafe formatters

`fixers/__init__.py`:

- Exists to satisfy plugin structure validation
- No C# fixers are implemented yet

## CSharpConfig

Main config class: `desloppify/lang/csharp/__init__.py`.

Important settings:

- `name`: `"csharp"`
- `extensions`: `[".cs"]`
- `default_src`: `"."`
- `typecheck_cmd`: `"dotnet build"`
- `large_threshold`: `500`
- `complexity_threshold`: `20`

Entry patterns used for orphan detection:

- `/Program.cs`
- `/Startup.cs`
- `/Main.cs`
- `/MauiProgram.cs`
- `/MainActivity.cs`
- `/AppDelegate.cs`
- `/SceneDelegate.cs`
- `/WinUIApplication.cs`
- `/App.xaml.cs`
- `/Properties/`
- `/Migrations/`
- `.g.cs`
- `.designer.cs`

Zone rules:

- Generated:
  - `.g.cs`
  - `.designer.cs`
  - `/obj/`
  - `/bin/`
- Test:
  - `.Tests.cs`
  - `Tests.cs`
  - `Test.cs`
  - `/Tests/`
  - `/test/`
- Config:
  - `/Program.cs`
  - `/Startup.cs`
  - `/AssemblyInfo.cs`

Phases in order:

1. Structural analysis
2. Coupling + cycles + orphaned
3. Security
4. Subjective review
5. Duplicates (slow phase)

Default C# scan profile is `objective`, which skips subjective review unless you opt in with `--profile full`.

## Scan flow in plain language

When you run:

```bash
desloppify --lang csharp scan --path <repo>
```

the flow is:

1. Resolve C# language config from registry
2. Discover `.cs` files
3. Build zone map (production, test, generated, etc)
4. Run each configured phase in order
5. Convert raw detector output into normalized findings
6. Merge findings into state and scoring

Important point:

The C# module mostly delegates to shared detector logic. Language files provide C# parsing and C# specific rules.

## File discovery

`find_csharp_files()` in `extractors.py` uses shared `find_source_files(...)` with C# specific exclusions:

- `bin`
- `obj`
- `.vs`
- `.idea`
- `packages`

This keeps generated output and IDE folders out of analysis.

## Method extraction

`extract_csharp_functions(filepath)` supports:

- Block-bodied methods: `public int Add(...) { ... }`
- Expression-bodied methods: `public int Double(int x) => x * 2;`

What it records:

- Method name
- Start and end line
- LOC
- Raw body
- Normalized body
- `md5` hash of normalized body
- Parameter names

Normalization removes:

- Block comments
- Line comments
- Blank lines
- Obvious logging lines like `Console.WriteLine(...)` and `logger.X(...)`

This helps duplicate detection focus on logic, not noise.

### Method extraction limits

This is regex plus brace tracking, not Roslyn.

It is designed for practical static signal quality, not compiler-level semantic accuracy.

## Class extraction

`extract_csharp_classes(path)` finds class-like types and collects:

- Type name (`class`, `record`, `struct`)
- Method list
- Attribute/property-like members
- Base class and interface names
- Class LOC

This output feeds shared "god structure" detection in `phases.py`.

## Dependency graph builder

Main function: `build_dep_graph(path)` in `detectors/deps.py`.

It combines:

- `namespace` declarations
- `using` statements (normal, alias, static)
- `.csproj` `ProjectReference` relationships
- `obj/project.assets.json` project references (when restore metadata exists)
- Optional `RootNamespace` from `.csproj`
- Optional Roslyn JSON graph input via `DESLOPPIFY_CSHARP_ROSLYN_CMD`

How it works at a high level:

1. Find C# source files and `.csproj` files
2. Parse project references and root namespaces
3. Merge additional project references from `obj/project.assets.json` when available
4. Map each source file to its nearest project file
5. Build namespace to file index
6. For each file, map `using` namespaces to possible target files
7. Restrict cross-project edges using project reference relationships
8. Mark detected bootstrap/entrypoint files as graph roots (so they are not treated as orphaned)
9. Return graph in shared detector format

Bootstrap heuristics include path/name/content signals, for example:

- platform entry files such as `MauiProgram.cs`, `MainActivity.cs`, `AppDelegate.cs`
- platform folders under `Platforms/*` only count when delegate/bootstrap signatures are present
- common bootstrap signatures such as `Main(...)`, `CreateMauiApp(...)`, and delegate inheritance

Roslyn mode:

- You can pass a one-off command with `--lang-opt roslyn_cmd=...` on `scan` or `detect`.
- If no runtime option is provided, `DESLOPPIFY_CSHARP_ROSLYN_CMD` is used.
- The command can include `{path}` placeholder and must print JSON to stdout.
- The command is executed without shell interpolation (`shell=False`) for safer invocation.
- Guardrails:
  - `DESLOPPIFY_CSHARP_ROSLYN_TIMEOUT_SECONDS` (default `20`)
  - `DESLOPPIFY_CSHARP_ROSLYN_MAX_OUTPUT_BYTES` (default `5242880`)
  - `DESLOPPIFY_CSHARP_ROSLYN_MAX_EDGES` (default `200000`)
- Supported JSON shapes:
  - `{"files":[{"file":"<abs-or-rel>", "imports":["<abs-or-rel>", ...]}]}`
  - `{"edges":[{"source":"<abs-or-rel>", "target":"<abs-or-rel>"}]}`
- If command execution fails or JSON is invalid, Desloppify falls back to heuristic namespace/project graph building.

Example:

```bash
desloppify --lang csharp detect deps --path . \
  --lang-opt "roslyn_cmd=dotnet run --project contrib/csharp/RoslynGraphEmitter/RoslynGraphEmitter.csproj -- {path}"
```

Sample emitter:

- `contrib/csharp/RoslynGraphEmitter/` (adapt to your repo/build setup)

Graph node shape (same shape expected by shared graph detectors):

- `imports` set
- `importers` set
- `import_count`
- `importer_count`

This is enough for:

- Cycles
- Orphan detection
- Single-use abstraction signals
- Coupling summaries

### Dependency graph limits

This is namespace and reference based approximation.

It does not resolve:

- Full symbol binding
- Partial class symbol merges at semantic level
- Advanced compiler features and generated symbols

For MVP this tradeoff is intentional. Optional Roslyn input improves precision when available.

## C# structural phase

Implemented in `_phase_structural(...)` in `phases.py`.

It merges signals from:

- Large files
- Complexity signals
- God class rules
- Flat directories

Complexity signals include:

- High `using` count
- TODO/FIXME/HACK markers
- Many class declarations in one file
- Deep brace nesting
- High method count
- Long methods

God class rules include:

- High method count
- High attribute count
- Many base class or interface links
- Multiple long methods

The phase merges many small clues into one structural finding per file when needed.

## C# coupling phase

Implemented in `_phase_coupling(...)` in `phases.py`.

It runs shared detectors against the C# graph:

- `single_use`
- `cycles`
- `orphaned`

It then applies zone filtering and converts entries into normalized findings.

Actionability gating for `single_use` and `orphaned`:

- C# now downgrades confidence unless there is corroboration from multiple signals.
- Corroboration signals currently include:
  - large file size (LOC over threshold)
  - complexity score over threshold
  - high fan-out (`import_count >= languages.csharp.high_fanout_threshold`, default `5`)
- Confidence policy:
  - `medium` when corroboration count is at least `languages.csharp.corroboration_min_signals` (default `2`)
  - `low` otherwise

This reduces eager cleanup recommendations for weakly-supported coupling findings.

## C# security phase

C# security runs through shared `phase_security(...)` in `lang/base.py`.

That shared phase does:

1. Shared cross-language security checks
2. Optional language specific checks via `lang.detect_lang_security(...)`

For C#, `detect_lang_security(...)` points to `detectors/security.py`.

Current C# specific checks:

- Dynamic SQL command construction from interpolation or concatenation
- `new Random()` in security-sensitive contexts
- TLS cert validation callback forced to `true`
- `BinaryFormatter` or `SoapFormatter` usage

## Duplicates phase

C# duplicate detection is shared and language-agnostic once methods are extracted.

Flow:

1. `CSharpConfig.extract_functions` gathers C# methods from all files
2. Shared `phase_dupes(...)` filters out excluded zones
3. Shared duplicate detector clusters exact and near-duplicate methods

The C# extractor is what makes this possible.

## Detect command support

C# detect commands live in `commands.py`.

Supported commands:

- `deps`
- `cycles`
- `orphaned`
- `dupes`
- `large`
- `complexity`

Examples:

```bash
desloppify --lang csharp detect deps --path .
desloppify --lang csharp detect cycles --path .
desloppify --lang csharp detect orphaned --path .
desloppify --lang csharp detect dupes --path .
desloppify --lang csharp detect large --path .
desloppify --lang csharp detect complexity --path .
```

All support the same output style used by other languages, including JSON mode where implemented.

## Shared modules related to C#

This section is important because C# support is not isolated to `lang/csharp/`.

### Registry and auto-detection

`desloppify/lang/__init__.py`:

- Registers available language plugins
- Auto-detects C# using:
  - `global.json`
  - `*.sln`
  - `*.csproj`
- Uses source file counts to pick dominant language in mixed repos

### Shared phase helpers and contracts

`desloppify/lang/base.py`:

- Defines `LangConfig` contract C# must satisfy
- Runs shared phase logic for:
  - `phase_security`
  - `phase_subjective_review`
  - `phase_dupes`
- Extends external test file discovery to include C# test files

### CLI language surface

`desloppify/cli.py`:

- Exposes `--lang csharp` in language help text
- Notes that C# fixers are not available yet

`desloppify/commands/detect.py` and `desloppify/commands/_helpers.py`:

- Use dynamic language lists so C# appears in validation and error messaging

### Move command

`desloppify/commands/move.py`:

- Recognizes `.cs` as C# for move operations
- Supports moving C# files and folders
- Current C# replacement strategy is no-op for import rewrite
- Suggests `dotnet build` after C# move to verify project state

### Visualization

`desloppify/visualize.py`:

- Includes `.cs` in fallback file collection when language is not explicitly resolved

### Test coverage heuristics

`desloppify/detectors/test_coverage.py`:

- Loads C# test-coverage behavior via language plugin hook modules
- Treats C# declaration-only patterns as lower-value test targets where appropriate

`desloppify/detectors/test_coverage_mapping.py`:

- Adds C# naming conventions for mapping tests to source files
- Adds C# assertion and mocking pattern detection
- Supports xUnit/NUnit/MSTest style test attributes in quality analysis

### Review context and prompts

`desloppify/review/context.py`:

- Uses C# plugin review hooks for module patterns and migration signal pairing

`desloppify/review/context_holistic.py`:

- Uses C# plugin API-surface hooks for mixed sync/async public API checks

`desloppify/review/dimensions.py`:

- Adds C# specific review guidance for naming, patterns, and auth concerns

## Test coverage for this module

C# module tests are in:

- `tests/test_csharp_init.py`
- `tests/test_csharp_commands.py`
- `tests/test_csharp_extractors.py`
- `tests/test_csharp_deps.py`
- `tests/test_csharp_scan.py`
- `tests/test_test_coverage_csharp.py`

Fixtures are in:

- `tests/fixtures/csharp/simple_app/`
- `tests/fixtures/csharp/multi_project/`
- `tests/fixtures/csharp/cyclic/`
- `tests/fixtures/csharp/signal_rich/`

Fixture intent:

- `simple_app`: baseline single project behavior
- `multi_project`: project reference edge building
- `cyclic`: cycle detection path
- `signal_rich`: intentional detector signals for meaningful scan assertions (security, structural, orphaned, single-use candidate behavior)

## Current limitations

This list is intentional and expected for MVP:

- No C# auto-fixers yet
- No built-in Roslyn resolver binary ships with Desloppify
- Dependency graph defaults to namespace/project heuristics, with optional Roslyn JSON command integration
- Some advanced C# syntax cases may not be parsed perfectly by regex-based extractors

## Safe extension points

If you want to grow C# support, these are the safest places:

1. Add new C# security checks in `detectors/security.py`.
2. Improve graph precision in `detectors/deps.py`.
3. Expand complexity signals and god rules in `phases.py`.
4. Add C# move rewrite support by implementing C# replacement helpers and wiring `_compute_replacements(...)`.
5. Add C# fixers by creating real entries in `fixers/` and registering them in `CSharpConfig.fixers`.

When adding behavior, always add tests in `tests/test_csharp_*.py` and, if needed, a focused fixture under `tests/fixtures/csharp/`.

## Troubleshooting notes

If C# findings seem empty:

- Verify the scan path actually contains `.cs` files
- Check that files are not all classified into excluded zones
- Run `detect deps` first to confirm graph building works
- Run `detect large` and `detect complexity` to verify structural baseline

If dependency edges look wrong:

- Check `namespace` declarations are consistent with folder/project layout
- Check `.csproj` `ProjectReference` links
- Check whether the files are under excluded directories such as `obj` or `bin`

## Quick reference

Common commands:

```bash
desloppify --lang csharp scan --path .
desloppify --lang csharp scan --profile full --path .
desloppify --lang csharp scan --path . --lang-opt "roslyn_cmd=dotnet run --project contrib/csharp/RoslynGraphEmitter/RoslynGraphEmitter.csproj -- {path}"
desloppify --lang csharp status
desloppify --lang csharp next
desloppify --lang csharp show .
desloppify --lang csharp detect deps --path .
desloppify --lang csharp detect deps --path . --lang-opt "roslyn_cmd=dotnet run --project contrib/csharp/RoslynGraphEmitter/RoslynGraphEmitter.csproj -- {path}"
desloppify --lang csharp detect cycles --path .
desloppify --lang csharp detect orphaned --path .
desloppify --lang csharp detect dupes --path .
```

## Summary

The C# module follows the same architecture as other Desloppify languages:

- Language module provides parsing and language-specific rules
- Shared detectors provide most of the heavy logic
- Findings are normalized through shared state and scoring systems

This keeps C# support consistent with the rest of the tool while still allowing C# specific behavior where it matters.
