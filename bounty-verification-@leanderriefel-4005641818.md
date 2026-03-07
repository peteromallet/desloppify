# Bounty Verification: S160 @leanderriefel

**Submission:** `queue_order` is a stringly-typed mixed domain model (data + workflow control plane in one list)

**Verdict:** YES_WITH_CAVEATS

## Claim-by-Claim Verification

All claims verified against commit `6eb2065`.

### 1. `queue_order` is `list[str]` storing mixed entity types
**CONFIRMED** — `schema.py:149` defines `queue_order: list[str]`. `stale_dimensions.py:24-40` defines the prefixes: `subjective::`, `triage::`, `workflow::`, and the centralized `SYNTHETIC_PREFIXES` tuple.

### 2. Plan resolver treats synthetic IDs as valid (`_resolve.py:36-53`)
**CONFIRMED** — `resolve_ids_from_patterns()` checks `plan_ids` (which includes queue_order contents) and accepts literal synthetic IDs like `subjective::*` even when they have no state entry.

### 3. Reconcile excludes synthetic prefixes (`reconcile.py:166-172`)
**CONFIRMED** — Reconcile filters out IDs matching `SYNTHETIC_PREFIXES` before checking if issues are alive. Uses the centralized constant correctly.

### 4. Override handlers duplicate synthetic detection (`override_handlers.py:443-445`)
**CONFIRMED** — `_is_synthetic_id()` hardcodes the 3 prefix checks (`triage::`, `workflow::`, `subjective::`) instead of importing `SYNTHETIC_PREFIXES` from stale_dimensions.

### 5. Queue mutation special-cases triage IDs (`operations_queue.py:104-108`)
**CONFIRMED** — `move_items()` imports `TRIAGE_IDS` and filters them out before processing, preventing manual reordering of workflow-managed items.

### 6. Triage UI filters by prefix (`display.py:448-450`)
**CONFIRMED** — Display filters `triage::` and `workflow::` prefixes but notably omits `subjective::`, which is a slightly different filter than `SYNTHETIC_PREFIXES`.

### 7. Schema migration imports runtime constants (`schema_migrations.py:124-128`)
**CONFIRMED** — `migrate_v5_to_v6()` imports `TRIAGE_STAGE_IDS` and `WORKFLOW_CREATE_PLAN_ID` from stale_dimensions with an explicit `# cycle-break` comment.

### 8. Architectural inversion claim
**PARTIALLY CONFIRMED** — The cycle-break note exists and documents a real import relationship concern. However, the comment is actually good engineering practice (documenting the constraint), not poor engineering.

## Mitigating Factors

- `SYNTHETIC_PREFIXES` tuple already exists as a centralized constant — the pattern is partially organized
- Only `override_handlers.py` truly duplicates the prefix check; other modules import from the central location or use specific subsets intentionally
- `display.py` omitting `subjective::` may be intentional (subjective items arguably belong in queue display)
- This is a common Python pattern (tagged strings as ad-hoc tagged unions) — works correctly with no bugs
- The cycle-break comment in schema_migrations.py is defensive documentation, not a flaw

## Duplicate Check

No prior submissions cover `queue_order` typing specifically. S012/S013 cover `Issue.detail` god field (different field, different subsystem). S005 covers circular deps in subjective dimensions (related module but different concern). **S160 is original.**
