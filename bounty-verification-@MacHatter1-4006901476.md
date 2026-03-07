# Bounty Verification: S185 @MacHatter1 — Dual-Source Cluster Membership

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4006901476
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `PlanModel` stores membership in two places: `overrides[id].cluster` and `clusters[name].issue_ids`
**CONFIRMED.** `ItemOverride` declares `cluster: str | None` (schema.py:40) and `Cluster` declares `issue_ids: list[str]` (schema.py:48). Both are nested inside `PlanModel` (schema.py:145-163).

### 2. Mutators must manually synchronize both copies
**CONFIRMED.** `add_to_cluster()` in operations_cluster.py:44-66 explicitly writes to both stores: it appends to `cluster["issue_ids"]` AND sets `overrides[fid]["cluster"] = cluster_name`. Every mutation path must remember to update both.

### 3. Different readers trust different stores
**CONFIRMED.**
- `enrich_plan_metadata()` in plan_order.py:35-53 reads `override.get("cluster")` to badge queue items with cluster info.
- `filter_cluster_focus()` in plan_order.py:102-116 reads `cluster_data.get("issue_ids", [])` to filter items when `--cluster` is active.

These two functions consult different authorities. If the stores diverge, an item can appear badged as belonging to a cluster but be invisible when that cluster is focused (or vice versa).

### 4. `validate_plan()` does not check consistency
**CONFIRMED.** `validate_plan()` (schema.py:210-230) checks version type, queue_order type, queue/skip overlap, and skip entry kinds. It never cross-checks `overrides[x].cluster` against `clusters[name].issue_ids`.

### 5. `_repair_ghost_cluster_refs()` exists as evidence of known divergence
**CONFIRMED.** `_repair_ghost_cluster_refs()` in auto_cluster.py cleans up one class of orphaned override references, confirming the dual-store divergence is a known operational problem.

## Duplicate Check

S186 (same author) describes the same dual-store flaw but focuses on the auto-cluster shrink path as a concrete trigger. S186 is already tagged SKIP_DUPLICATE in bounty-filtered.json, confirming S185 is the primary submission. No other verified verdicts cover this structural issue.
