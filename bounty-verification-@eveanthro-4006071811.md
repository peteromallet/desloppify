# Bounty Verification: S167 @eveanthro — Doc-vs-Implementation Drift

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4006071811
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. "Command entry files are thin orchestrators" — large files cited

The submission claims three files violate the "thin orchestrator" rule:

| File | Claimed lines | Actual lines | Match? |
|------|--------------|-------------|--------|
| `desloppify/app/commands/plan/override_handlers.py` | 856 | **632** | WRONG |
| `desloppify/app/commands/review/batch/execution.py` | 748 | **748** | Correct |
| `desloppify/app/commands/review/batch/core.py` | 720 | **720** | Correct |

**Verdict on claim 1:** PARTIALLY CONFIRMED. 2/3 line counts accurate. The 856-line claim for override_handlers.py is factually wrong (632 lines). Notably, the same incorrect 856-line figure appears in S165 (@ziyuxuan84829), which was also rejected. The two confirmed files are indeed large, though "large" does not automatically mean "not an orchestrator" — it depends on whether the logic should live elsewhere.

### 2. Dynamic imports outside designated extension points

All four cited files confirmed to use `importlib`:

- **`scan/artifacts.py:5,94-99`**: `importlib.import_module("desloppify.app.output.scorecard")` — lazy loads the scorecard module to avoid heavy import at startup.
- **`output/scorecard.py:5,45-47`**: `importlib.import_module("PIL.Image")`, `importlib.import_module("PIL.ImageDraw")` — deferred import of PIL, which is an **optional dependency**. Standard Python practice for optional deps.
- **`move/language.py:5,81,90`**: `importlib.import_module(module_name)` — loads language-specific move scaffolding. This is **within the language plugin system**, arguably an extension point itself.
- **`languages/typescript/commands.py:6,188`**: `importlib.import_module(module_path)` — loads language-specific submodule. **Inside** the `languages/` directory, which is the designated extension point.

**Verdict on claim 2:** CONFIRMED but overstated. All four files do use dynamic imports. However, the doc rule targets ad-hoc cross-boundary imports, not lazy loading of optional dependencies or language plugin internals. Three of four cases are within or adjacent to the designated extension point system (`languages/`). The PIL lazy import is standard Python practice for optional deps. These are not the kind of "ad-hoc" violations the philosophy doc warns against.

### 3. Persisted state bypassed by command modules

The doc says: *"Persisted state is owned by `state.py` and `engine/_state/` — command modules read and write through those APIs, they don't invent their own persisted fields."*

- **`review/external.py` (lines 357-358, 519, 547)**: Writes session payloads, templates, canonical imports, and session status updates. These are **session working files** for the external review workflow — not the persisted desloppify state (state.json/plan.json). Session files are ephemeral workflow artifacts.
- **`review/batch/orchestrator.py` (lines 115, 393)**: Writes blind packets and merged holistic issue JSON. Again, these are **pipeline build artifacts**, not persisted state.
- **`base/config.py` (lines 200, 362)**: Writes config.json and state data. This is **base infrastructure** — config.py is not a "command module." It's part of the state/config ownership layer the doc refers to.

**Verdict on claim 3:** NOT CONFIRMED as described. None of the cited examples bypass the state engine. external.py and orchestrator.py write session/batch working files, which are distinct from the persisted state the philosophy doc refers to. config.py is infrastructure, not a command module. The submission conflates "any JSON write to disk" with "inventing persisted fields."

## Duplicate Check

- S165 (@ziyuxuan84829) makes overlapping claims about large files and uses the same incorrect 856-line figure for override_handlers.py. S165 was rejected as generic/inaccurate.
- S034 (@xinlingfeiwu) covers app/ bypassing engine facades — related topic but focuses on private imports, not doc-vs-code drift.
- S023 (@jasonsutter87) covers god-orchestrator patterns — overlaps on large file concern but different framing.

No exact duplicate found. The doc-vs-code drift framing is somewhat original.

## Assessment

The core observation — that DEVELOPMENT_PHILOSOPHY.md's architectural rules don't perfectly match implementation — has some truth. But the submission overstates the severity and mischaracterizes the examples:

1. **One of three line counts is factually wrong** (632 vs claimed 856).
2. **Dynamic imports are legitimate** lazy loading for optional deps and language plugin internals, not the "ad-hoc" violations the doc warns against.
3. **"State bypass" examples write session/batch artifacts**, not persisted state. config.py is infrastructure, not a command module.
4. **No bugs or runtime issues result** from any of the cited drift.
5. This is fundamentally a **documentation accuracy observation**, not a code quality defect.
