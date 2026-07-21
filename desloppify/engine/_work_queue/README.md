# Work Queue

How items flow from scan results into the execution queue that `desloppify next` returns.

## Core concepts

- **`queue_order`** is the durable ordering source (persisted in plan JSON).
- **Phase gate** controls visibility — re-resolved from live items every build, not from persisted phase.
- **`auto_queue` detectors** (`unused`, `logs`) auto-inject into `queue_order` without triage.
- See `policy.py` for the readable queue model summary.
- See `docs/QUEUE_LIFECYCLE.md` for phase lifecycle rules.

## Lifecycle phases

Phase is determined by `_phase_for_snapshot()` from the persisted lifecycle mode plus
live item partitions. Legacy fine-grained phase names are migrated once by
`current_lifecycle_phase()` before snapshot resolution.

1. **LIFECYCLE_PHASE_REVIEW_INITIAL** — fresh boundary, no scores yet. Shows subjective review items.
   Objective items are NOT visible until initial review completes, unless the user explicitly
   promotes live execution work into the active queue. Explicit promotion overrides the normal
   planning gates until the promoted work drains.

2. **LIFECYCLE_PHASE_EXECUTE** — the main work phase. Shows objective (mechanical defect) items.
   Only issues in `queue_order` are executable (post-triage). Pre-triage: all objectives visible.

3. **LIFECYCLE_PHASE_SCAN** / **LIFECYCLE_PHASE_*_POSTFLIGHT** — workflow items (rescan, communicate score,
   assessment, triage). These gate the execution phase.

## Auto-queue vs triage-promoted

Detectors with `auto_queue=True` in the registry (currently: `unused`, `logs`) get
`execution_status=active` and `execution_policy=ephemeral_autopromote` at cluster creation.
Their issues auto-inject into `queue_order`.

All other detectors require triage to promote their clusters to active. The precedence
for determining execution policy is: **explicit persisted field → registry `auto_queue` → string-sniffing fallback**.

## Module map

```
snapshot.py          build_queue_snapshot() — canonical entry point
  → ranking.py       build_issue_items() — creates WorkQueueItem dicts from state
  → selection.py     items_for_visibility() — filters by execution/backlog view
  → finalize.py      finalize_queue() — enriches with impact, stamps plan position, sorts
  → plan_order.py    stamp_plan_sort_keys(), collapse_clusters()
  → synthetic.py     build_subjective_items(), build_triage_stage_items()
  → synthetic_workflow.py  workflow items (scan, review, communicate-score, deferred)
policy.py            should_auto_queue(), explain_queue() — readable rules + explainability
models.py            QueueBuildOptions, QueueSnapshot, WorkQueueResult
```

## Sort order (`item_sort_key` in ranking.py)

```
Tier 0: _TIER_PLANNED   — items with explicit plan position (by plan_pos)
Tier 1: _TIER_EXISTING  — known items without plan position (by natural sort)
Tier 2: _TIER_NEW       — newly discovered items (by natural sort)

Natural sort (within each tier):
  _RANK_CLUSTER=0 → clusters first, by action_type (auto_fix=0, refactor=1, manual_fix=2)
  _RANK_ISSUE=1   → individual issues, by -impact, confidence, -count, id
```

## Key types

- `WorkQueueItem` (types.py) — TypedDict with id, kind, detector, file, etc.
- `QueueSnapshot` (snapshot.py) — the full snapshot: execution_items, backlog_items, phase, counts
- `_Partitions` (snapshot.py) — intermediate grouping before phase resolution
