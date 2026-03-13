# Next.js Framework Module

This document explains the Next.js framework support used by Desloppify's TypeScript and JavaScript plugins.

It covers:

- What the Next.js framework module does
- How framework detection and scanning flow works
- What each file in `desloppify/languages/typescript/frameworks/nextjs/` is responsible for
- Which shared files outside this folder affect behavior
- Current limits and safe extension points

If you are new to this code, start with the `detect_nextjs_framework_smells` section and then read the "Scan flow" section.

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

- `desloppify/languages/typescript/frameworks/nextjs/__init__.py`
- `desloppify/languages/typescript/frameworks/nextjs/info.py`
- `desloppify/languages/typescript/frameworks/nextjs/phase.py`
- `desloppify/languages/typescript/frameworks/nextjs/scanners.py`

### What each file does

`__init__.py`:

- Exposes the framework info contract and shared phase entrypoint for imports

`info.py`:

- Defines `NextjsFrameworkInfo`
- Converts generic framework detection output into Next.js-specific router roots and flags

`phase.py`:

- Orchestrates all Next.js scanners
- Converts scanner entries into normalized issues (`nextjs` detector)
- Runs `next lint` integration and emits normalized lint issues (`next_lint` detector)

`scanners.py`:

- Implements all Next.js smell scanners
- Performs fast source-file discovery and content heuristics
- Returns normalized scanner entries for the phase orchestrator

## Shared surfaces outside this folder

These files are part of the same feature boundary and should be considered together:

- `desloppify/languages/typescript/frameworks/detect.py`
- `desloppify/languages/typescript/frameworks/catalog.py`
- `desloppify/languages/typescript/frameworks/types.py`
- `desloppify/languages/typescript/phases_smells.py`
- `desloppify/languages/javascript/phases_nextjs.py`
- `desloppify/languages/_framework/node/next_lint.py`
- `desloppify/base/discovery/source.py`

### Responsibility split

- `frameworks/detect.py` decides whether Next.js is the primary framework and where package roots are.
- `nextjs/info.py` exposes Next.js routing context (`app_roots`, `pages_roots`) used by scanners.
- `nextjs/scanners.py` only finds smell candidates.
- `nextjs/phase.py` maps candidates to detector issues and handles scoring potentials.
- `next_lint.py` provides lint execution/parsing, independent of smell mapping.

## Detectors

This module emits findings under:

- `nextjs`
- `next_lint`

Registry/scoring wiring lives outside this folder in:

- `desloppify/base/registry/catalog_entries.py`
- `desloppify/base/registry/catalog_models.py`
- `desloppify/engine/_scoring/policy/core.py`

## Scan flow in plain language

When TypeScript or JavaScript code smells run for a Next.js project, flow is:

1. Framework detection picks primary framework from package markers and scripts.
2. Next.js info derives App/Pages router roots from detection evidence.
3. Shared Next.js phase runs all scanner functions.
4. Scanner entries are mapped into normalized `nextjs` issues.
5. `next lint` is executed and mapped into `next_lint` issues.
6. Potentials are returned for scoring and state merge.

## `next lint` behavior

`run_next_lint(...)` executes:

- `npx --no-install next lint --format json`

Behavior:

- If lint runs and returns JSON, file-level lint findings are emitted.
- If lint cannot run or output cannot be parsed, a `next_lint::unavailable` issue is emitted.

This keeps lint participation explicit in Next.js scans instead of silently skipping.

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
