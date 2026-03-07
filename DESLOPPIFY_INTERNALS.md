# Desloppify Internals — Agent Reference

## What It Does
Desloppify scans codebases for engineering quality issues, scores them, and generates a prioritized work queue. It combines mechanical detection (automated pattern matching) with subjective LLM review (holistic assessment).

## Architecture

```
scan --path .
  -> Language plugins extract functions, classes, imports
  -> Mechanical detectors run on extracted data
  -> LLM subjective review runs on sampled files
  -> Issues written to state (.desloppify/)
  -> Scoring computes strict_score + verified_strict_score
  -> Work queue ranks issues by impact for `next` command
```

## Mechanical Detectors (engine/detectors/)

| Detector | What it catches |
|---|---|
| `complexity.py` | High cyclomatic complexity, deep nesting |
| `coupling.py` | Tight coupling, circular dependencies, private import violations |
| `dupes.py` | Duplicate/near-duplicate functions (body hash + normalized comparison) |
| `gods.py` | God classes/functions (too many methods, attributes, LOC) |
| `large.py` | Oversized files |
| `orphaned.py` | Dead code — unused exports, unreferenced files |
| `single_use.py` | Single-use abstractions (wrapper functions called once) |
| `naming.py` | Naming inconsistencies |
| `passthrough.py` | Passthrough functions that just forward calls |
| `graph.py` | Dependency graph analysis |
| `flat_dirs.py` | Flat directory structures lacking organization |
| `signature.py` | Function signature issues (too many params, etc.) |
| `concerns.py` | Mixed concerns / responsibility violations |
| `coverage/` | Test coverage gaps |
| `security/` | Security vulnerabilities (patterns + Bandit adapter) |

## Subjective Dimensions (LLM-assessed)

Subjective reviews are **informed by mechanical detection results**. The LLM sees the scan output (detected issues, counts, confidence levels) before scoring subjective dimensions. This means subjective scores reflect both what the LLM observes directly in the code AND patterns already surfaced by detectors.

**Example:** If the `coupling.py` detector flags 12 circular dependencies, the subjective `dependency_health` dimension will see those flags and factor them into its 0-100 score — but it can also catch subtler coupling patterns (like implicit coupling through shared global state) that the mechanical detector missed.

### Holistic Dimensions (cross-module)

| Dimension | What it assesses |
|---|---|
| `cross_module_architecture` | Module boundaries, layering violations, dependency direction |
| `initialization_coupling` | Boot/init sequences that create hidden dependencies |
| `convention_outlier` | Code that breaks established patterns in the codebase |
| `error_consistency` | Whether error handling follows a single consistent strategy |
| `abstraction_fitness` | Are abstractions at the right level? Over/under-abstracted? |
| `dependency_health` | External + internal dependency hygiene |
| `test_strategy` | Test quality, coverage strategy, test architecture |
| `api_surface_coherence` | Public API consistency, naming, parameter conventions |
| `authorization_consistency` | Auth checks applied uniformly across entry points |
| `ai_generated_debt` | Signs of AI-generated code left unreviewed |
| `incomplete_migration` | Half-finished refactors, old + new patterns coexisting |
| `package_organization` | File/folder structure, logical grouping |
| `high_level_elegance` | Architecture-level clarity and simplicity |
| `mid_level_elegance` | Module/class-level design quality |
| `low_level_elegance` | Function/expression-level readability |

### Per-file Review Dimensions

| Dimension | What it assesses |
|---|---|
| `naming_quality` | Variable, function, class names — clear and consistent? |
| `logic_clarity` | Is the control flow easy to follow? |
| `type_safety` | Proper typing, no `Any` abuse, no implicit coercions |
| `contract_coherence` | Do function signatures match their behavior? |
| `design_coherence` | Does the file have a single clear purpose? |

## Scoring (engine/_scoring/)

- Each detector has a **potential** (max issues it could find) and **actual** (confirmed issues)
- Issues weighted by `confidence` (high/medium/low) via `CONFIDENCE_WEIGHTS`
- File-count caps prevent a single file from dominating scores
- `strict_score` = weighted pass rate across all detectors
- `verified_strict_score` = after human/agent resolution of issues
- Subjective dimensions scored 0-100 by LLM, factored into overall score
- Anti-gaming: scoring resists suppression, status laundering, and trivial fixes

## State (engine/_state/)

- `schema.py` — `StateModel` with issues, stats, scores, subjective assessments
- `merge.py` — `merge_scan()` updates issues from new scan, recomputes scores
- `resolution.py` — `resolve_issues()` writes manual decisions (status/note) into same records
- State is mutable — scan results, scores, and resolutions all live in one document

## Work Queue (engine/_work_queue/)

- `ranking.py` — `_natural_sort_key()` ranks by impact, confidence, review weight
- Items: issues, subjective dimensions, workflow stages, clusters
- `item_sort_key()` combines plan position + natural ranking

## Detection Coverage by Layer

Desloppify has two detection layers. Mechanical detectors catch structural patterns automatically. Subjective LLM review can catch deeper issues — but only in files it samples and reviews.

### Mechanical detectors reliably catch:
- Dead code, duplicates, god classes, high complexity, large files
- Naming inconsistencies, coupling, flat directories, passthrough functions
- Security patterns, test coverage gaps

### Subjective review CAN catch (but may miss depending on sampling):
- Cross-function logic bugs, type confusion, race conditions
- Silent failure paths, data model coupling issues
- Sort/comparison correctness, API contract drift, state mutation side effects
- Architectural problems that span multiple files

### Where gaps typically occur:
- **Mechanical detectors** don't do semantic/runtime analysis — they catch patterns, not logic
- **Subjective review** depends on file sampling — it may not review the specific file where the issue lives
- **Cross-file interactions** are harder for both layers — issues that only emerge when two modules interact
- Issues in **rarely-changed utility code** may not be sampled for subjective review

When assessing "why did desloppify miss this?", consider: was the issue in a file that was likely sampled? Could the subjective review have caught it if it looked? Or is this genuinely outside both layers' reach?
