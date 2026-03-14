# Next.js Framework Support (Scanners + Spec)

This document explains the Next.js framework support used by Desloppify's TypeScript and JavaScript plugins.

It covers:

- What the Next.js framework module does
- How framework detection and scanning flow works
- What each file in `desloppify/languages/_framework/node/frameworks/nextjs/` is responsible for
- Which shared files outside this folder affect behavior
- Current limits and safe extension points

If you are new to this code, start with the "Spec + scan flow" section, then read `scanners.py`.

## High-level purpose

The Next.js framework module adds framework-aware smells that generic code-quality detectors do not catch.

Current scope includes:

- App Router vs Pages Router migration and misuse signals
- Client/server boundary misuse (`"use client"`, `"use server"`, server-only imports/exports)
- Route handler and middleware context misuse
- Next.js API misuse in wrong router contexts
- Environment variable leakage in client modules
- `next lint` integration as a framework quality gate (`next_lint` detector)

This module is intentionally heuristic-heavy (regex/file-structure based) so scans remain fast and robust without requiring full compiler semantics.

## Module map

Files in this folder:

- `desloppify/languages/_framework/node/frameworks/nextjs/__init__.py`
- `desloppify/languages/_framework/node/frameworks/nextjs/info.py`
- `desloppify/languages/_framework/node/frameworks/nextjs/scanners.py`

Spec + orchestration lives outside this folder:

- `desloppify/languages/_framework/frameworks/specs/nextjs.py`
- `desloppify/languages/_framework/frameworks/phases.py`

### What each file does

`__init__.py`:

- Exposes the framework info contract and shared phase entrypoint for imports

`info.py`:

- Defines `NextjsFrameworkInfo`
- Converts ecosystem detection evidence into Next.js-specific router roots and flags

`scanners.py`:

- Implements all Next.js smell scanners
- Performs fast source-file discovery and content heuristics
- Returns normalized scanner entries for the framework spec adapter

## Shared surfaces outside this folder

These files are part of the same feature boundary and should be considered together:

- `desloppify/languages/_framework/frameworks/detection.py`
- `desloppify/languages/_framework/frameworks/phases.py`
- `desloppify/languages/_framework/frameworks/specs/nextjs.py`
- `desloppify/languages/typescript/__init__.py`
- `desloppify/languages/javascript/__init__.py`
- `desloppify/languages/_framework/generic_parts/parsers.py` (parser: `parse_next_lint`)
- `desloppify/languages/_framework/generic_parts/tool_factories.py` (tool phase: `make_tool_phase`)
- `desloppify/base/discovery/source.py`

### Responsibility split

- `frameworks/detection.py` decides whether Next.js is present for a scan path and where package roots are.
- `frameworks/specs/nextjs.py` defines the Next.js FrameworkSpec (detection config + scanners + tool integrations).
- `frameworks/phases.py` adapts specs into `DetectorPhase` objects.
- `nextjs/info.py` derives routing context (`app_roots`, `pages_roots`) from detection evidence.
- `nextjs/scanners.py` only finds smell candidates (fast, heuristic).

## Detectors

This module emits findings under:

- `nextjs`
- `next_lint`

Registry/scoring wiring lives outside this folder in:

- `desloppify/base/registry/catalog_entries.py`
- `desloppify/base/registry/catalog_models.py`
- `desloppify/engine/_scoring/policy/core.py`

## Scan flow in plain language

## Spec + scan flow in plain language

When TypeScript or JavaScript scans run for a Next.js project, flow is:

1. Ecosystem framework detection (Node) evaluates deterministic presence signals from `package.json`.
2. Next.js info derives App/Pages router roots from detection evidence (`marker_dir_hits`).
3. Next.js framework smells phase runs all scanner functions and maps entries into normalized `nextjs` issues.
4. `next lint` tool phase runs (slow) and maps ESLint JSON output into `next_lint` issues.
5. Potentials are returned for scoring and state merge.

## `next lint` behavior

The Next.js spec runs:

- `npx --no-install next lint --format json`

Behavior:

- If lint runs and returns JSON, file-level lint findings are emitted (one issue per file).
- If lint cannot run or output cannot be parsed, coverage is degraded for `next_lint` (shown as a scan coverage warning).

`next lint` runs as a slow phase (`DetectorPhase.slow=True`) so `--skip-slow` skips it automatically.

## Smell families covered

Current high-value families include:

- `"use client"` placement and missing directive checks
- `"use server"` placement checks (module-level misuse only)
- Server-only imports in client modules (`next/headers`, `next/server`, `next/cache`, `server-only`, Node built-ins)
- Server-only Next exports from client modules (`metadata`, `generateMetadata`, `revalidate`, `dynamic`, etc.)
- Pages Router APIs used under App Router (`getServerSideProps`, `getStaticProps`, etc.)
- `next/navigation` usage in Pages Router files
- App Router metadata/config exports in Pages Router files
- Pages API route files exporting App Router route-handler HTTP functions
- App Router route handler and middleware misuse
- `next/head` usage in App Router
- `next/document` imports outside valid `_document.*` pages context
- Browser global usage in App Router modules missing `"use client"`
- Client layout smell and async client component smell
- Mixed `app/` and `pages/` router project smell
- Env leakage in client modules via non-`NEXT_PUBLIC_*` `process.env` usage

## Extending this module safely

When adding a new smell:

1. Add scanner logic in `scanners.py`.
2. Return compact entries (`file`, `line`, and minimal structured detail).
3. Map entries to `make_issue(...)` in `phase.py` with clear `id`, `summary`, and `detail`.
4. Update/extend tests in:
   - `desloppify/languages/typescript/tests/test_ts_nextjs_framework.py`
   - `desloppify/languages/javascript/tests/test_js_nextjs_framework.py` (if JS parity applies)
5. Keep logic shared (do not duplicate TS vs JS framework smell rules).

## Limits and tradeoffs

- Scanners are heuristic, not compiler-accurate.
- Some patterns are intentionally conservative to avoid noisy false positives.
- Router/middleware checks rely on conventional Next.js file placement.
- `next lint` requires project dependencies to be present for full lint execution.

These tradeoffs are deliberate: fast scans with high-signal framework smells, while preserving a clear extension path when stronger analysis is needed.
