# Rust Language Module

This document explains the Rust support in Desloppify in plain language.

It covers:

- What the Rust module does
- How scan phases work
- What each file in `desloppify/languages/rust/` is responsible for
- Which Rust-specific detectors exist today
- Where to add new logic safely
- Current limits and practical extension points

If you are new to this code, start with the `RustConfig` section and then read the "Scan flow" section.

## High-level purpose

The Rust module is a full plugin. It does more than wrap `cargo` tools.

Current scope includes:

- Structural analysis
- Coupling, cycles, and orphaned module detection
- Rust-specific API and Cargo policy detectors
- `cargo clippy`, `cargo check`, and `cargo rustdoc` integration
- Rust-specific code smell detection
- Duplicate detection
- Signature analysis
- Rust-aware test coverage mapping
- Subjective review guidance for Rust API and design quality
- A small set of Rust auto-fixers

This is not a compiler-accurate semantic model. The plugin intentionally combines:

- official toolchain signals from Cargo / Clippy / rustdoc
- best-effort Rust source parsing
- tree-sitter support when available
- hand-written Rust detectors for policy and idiom checks

## Module map

Files in this folder:

- `desloppify/languages/rust/__init__.py`
- `desloppify/languages/rust/commands.py`
- `desloppify/languages/rust/extractors.py`
- `desloppify/languages/rust/phases.py`
- `desloppify/languages/rust/phases_smells.py`
- `desloppify/languages/rust/support.py`
- `desloppify/languages/rust/tools.py`
- `desloppify/languages/rust/test_coverage.py`
- `desloppify/languages/rust/review.py`
- `desloppify/languages/rust/_fixers.py`
- `desloppify/languages/rust/detectors/`
- `desloppify/languages/rust/fixers/`
- `desloppify/languages/rust/tests/`

### What each file does

`__init__.py`:

- Defines `RustConfig`
- Registers the Rust plugin through `register_full_plugin(...)`
- Wires phase order, thresholds, zone rules, entry patterns, review hooks, and fixers

`commands.py`:

- Builds the Rust `detect` subcommand registry
- Exposes shared commands:
  - `deps`
  - `cycles`
  - `orphaned`
  - `dupes`
  - `large`
  - `complexity`
  - `smells`
- Exposes Rust-specific commands:
  - `clippy_warning`
  - `cargo_error`
  - `rustdoc_warning`
  - `rust_import_hygiene`
  - `rust_feature_hygiene`
  - `rust_doctest`
  - `rust_api_convention`
  - `rust_error_boundary`
  - `rust_future_proofing`
  - `rust_thread_safety`
  - `rust_async_locking`
  - `rust_drop_safety`
  - `rust_unsafe_api`

`extractors.py`:

- Finds Rust source files while skipping `target`, `vendor`, and other non-source folders
- Extracts functions for duplicate detection
- Uses tree-sitter when available and falls back to regex plus brace tracking otherwise

`phases.py`:

- Defines Rust structural complexity signals
- Runs structural analysis
- Runs coupling, cycles, and orphaned detection
- Runs Rust policy detectors
- Runs Rust signature analysis
- Builds the tool-backed phases for Clippy, Cargo check, and rustdoc

`phases_smells.py`:

- Runs Rust-specific smell detection
- Normalizes smell entries into standard issue objects

`support.py`:

- Shared Rust parsing and path helpers
- Comment stripping
- `use` / `mod` parsing helpers
- workspace / manifest resolution
- module and crate-name normalization helpers
- normalization helpers reused by extractors, deps, tests, and detectors

`tools.py`:

- Defines the Cargo command strings used by tool-backed phases
- Parses JSON diagnostics from `cargo check`, `cargo clippy`, and `cargo rustdoc`

`test_coverage.py`:

- Implements Rust-specific test coverage heuristics
- Maps integration tests, inline tests, imports, and barrel re-exports back to production files

`review.py`:

- Defines Rust subjective review dimensions
- Supplies Rust-specific review guidance and module-pattern markers
- Summarizes public API surface for review prompts

`_fixers.py`:

- Implements the current Rust auto-fixers
- Fixes same-crate imports
- Adds missing Cargo features
- Adds README doctest harnesses to `src/lib.rs`

`fixers/__init__.py`:

- Thin package wrapper that exposes the fixer registry

## Detector layout

Rust detectors are split by responsibility.

`detectors/api.py`:

- import hygiene
- public API naming conventions
- public error boundary rules
- future-proofing rules for public API shapes
- thread-safety contract checks

`detectors/cargo_policy.py`:

- Cargo feature hygiene
- README / inline doctest policy

`detectors/safety.py`:

- async locking checks
- drop safety checks
- unsafe API usage checks

`detectors/smells.py`:

- Rust-specific smell orchestration
- custom smell logic for cases that need context-aware suppression

`detectors/smells_catalog.py`:

- smell IDs
- labels
- severities
- regex-backed smell definitions for simple rules

`detectors/deps.py`:

- Rust dependency graph construction from `mod` and `use` relationships

`detectors/_shared.py`:

- shared detector helpers reused across API, Cargo policy, safety, and smell detectors

`detectors/custom.py`:

- compatibility shim for older imports
- re-exports the split detector API without owning new logic

## RustConfig

Main config class: `desloppify/languages/rust/__init__.py`.

Important settings:

- `name`: `"rust"`
- `extensions`: `[".rs"]`
- `default_src`: `"src"`
- `typecheck_cmd`: `"cargo check"`
- `large_threshold`: `500`
- `complexity_threshold`: `15`
- `default_scan_profile`: `"full"`
- `detect_markers`: `["Cargo.toml"]`

Entry patterns used for orphan detection:

- `src/lib.rs`
- `src/main.rs`
- `src/bin/`
- `tests/`
- `examples/`
- `benches/`
- `fuzz/`
- `build.rs`

Zone rules:

- Production:
  - `/src/bin/`
- Test:
  - `/tests/`
- Script:
  - `/examples/`
  - `/benches/`
  - `/fuzz/`
  - `build.rs`
- Config:
  - `Cargo.toml`
  - `Cargo.lock`
  - `/.cargo/`

Phases in order:

1. Structural analysis
2. Coupling + cycles + orphaned
3. Rust API + cargo policy
4. `cargo clippy`
5. `cargo check`
6. `cargo rustdoc`
7. Shared tree-sitter phases
8. Signature analysis
9. Test coverage
10. Code smells
11. Security
12. Shared subjective review + duplicates tail

## Scan flow in plain language

When you run:

```bash
desloppify --lang rust scan --path <repo>
```

the flow is:

1. Resolve Rust language config from registry
2. Discover `.rs` files under the target root
3. Build the zone map
4. Run structural and graph-based detectors
5. Run Rust-specific policy detectors
6. Run tool-backed Cargo phases
7. Run shared tree-sitter phases when available
8. Run Rust signature, coverage, smell, and security phases
9. Normalize all detector output into standard issues
10. Merge issues into scan state and scoring

Important point:

The Rust plugin is hybrid. Some findings come from source inspection, some from Cargo tool output, and some from shared framework phases.

## Dependency graph builder

Main function: `build_dep_graph(path)` in `detectors/deps.py`.

It builds a Rust module graph from:

- `mod` declarations
- `#[path = ...]` module overrides
- `use` statements
- workspace/package indexing from nearby Cargo manifests

At a high level:

1. Find Rust files
2. Index files into a graph shell
3. Resolve local `mod` declarations to target files
4. Resolve `use` specs to local modules when possible
5. Finalize graph edges for coupling, cycle, and orphaned analysis

This is intentionally best-effort. It does not use `cargo metadata`, rust-analyzer, or compiler internals.

## Tool-backed phases

Rust has three official-tool phases in `tools.py` and `phases.py`:

- `cargo clippy`
- `cargo check`
- `cargo rustdoc`

Current command policy:

- Clippy runs workspace-wide, all targets, all features, JSON output
- Cargo check runs workspace-wide, all targets, all features, JSON output
- Rustdoc runs once per workspace library package with `cargo rustdoc -p <package> --lib`, all features, JSON output

Current rustdoc warnings enabled:

- `broken_intra_doc_links`
- `private_intra_doc_links`
- `missing_crate_level_docs`

If these tools are unavailable or fail, the plugin records reduced coverage rather than inventing findings.

## Rust smell detection

Rust smells are split into two kinds:

- declarative smells in `smells_catalog.py`
- context-aware smells implemented in `smells.py`

Use the catalog when a smell is safe to express as a raw regex.

Use `smells.py` when a smell needs suppression logic, local rationale checks, or source-aware handling.

Current custom smells:

- `undocumented_unsafe`
- `allow_attr`

Current catalog-backed smells include:

- `static_mut`
- `result_unit_err`
- `string_error`
- `pub_use_glob`
- `todo_macro`
- `unimplemented_macro`
- `mem_forget`
- `box_leak`
- `process_exit`
- `dbg_macro`
- `thread_sleep`

Important implementation detail:

Regex-based smells rely on Rust comment stripping from `support.py`. That stripper intentionally preserves line counts while removing doc comments and regular comments so smell line numbers stay stable.

## Test coverage behavior

Rust test coverage in `test_coverage.py` uses heuristics rather than compiler instrumentation.

It understands:

- inline unit tests via `#[cfg(test)]` and `#[test]`
- integration tests under `tests/`
- runtime entrypoints like `src/main.rs`, `src/bin/*`, and `build.rs`
- `use`-based mapping from tests to production modules
- barrel re-exports via `lib.rs`

This gives Rust better coverage mapping than generic import-only heuristics.

## Auto-fixers

Current Rust auto-fixers are intentionally narrow:

- same-crate import rewrites to `crate::...`
- missing Cargo feature declarations
- README doctest harness insertion into `src/lib.rs`

Rust does not currently have broad AST rewrite fixers.

## Subjective review

Rust review guidance focuses on:

- cross-module architecture
- error consistency
- abstraction fitness
- test strategy
- API surface coherence
- design coherence

The review layer also highlights Rust-specific patterns such as:

- prelude-style re-exports
- boundary drift between `thiserror` and `anyhow`
- panic paths in public code
- public trait and public type surface complexity

## Safe extension points

If you want to add new Rust behavior, use this order of preference.

1. Add a regex-backed smell in `detectors/smells_catalog.py`
- only when it has low false-positive risk

2. Add a context-aware smell in `detectors/smells.py`
- use this when the rule needs local suppression or rationale handling

3. Add a policy detector in the appropriate split module
- `api.py`
- `cargo_policy.py`
- `safety.py`

4. Add shared parsing helpers to `detectors/_shared.py` or `support.py`
- prefer `_shared.py` for detector-only helpers
- prefer `support.py` for reusable Rust parsing/path logic across the plugin

5. Add or extend auto-fixers in `_fixers.py`
- only when the rewrite is deterministic and safe

## Current limits

- The dependency graph is source-based, not compiler-backed
- Regex fallback extraction is best-effort when tree-sitter is unavailable
- Tool-backed phases depend on local Cargo tooling and workspace health
- Rustdoc phase currently runs with `--lib`, so binary-only docs are not covered there
- Auto-fix coverage is intentionally narrow

## Testing

```bash
# Run Rust plugin tests
pytest -q desloppify/languages/rust/tests

# Run focused smell tests
pytest -q desloppify/languages/rust/tests/test_smells.py

# Run focused support tests
pytest -q desloppify/languages/rust/tests/test_support.py
```

## Verification

This README was written against the current Rust plugin layout and phase wiring in:

- `__init__.py`
- `commands.py`
- `phases.py`
- `phases_smells.py`
- `extractors.py`
- `support.py`
- `tools.py`
- `test_coverage.py`
- `review.py`
- `_fixers.py`
- `detectors/`

If you change phase order, detector ownership, or command names, update this file at the same time.
