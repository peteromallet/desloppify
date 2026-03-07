# Bounty Verification: S016 @yuzebin — Hard Layer Violation in Core Work Queue

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4000906201
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `engine/_work_queue/synthetic.py` lines 93-96 import from `app` layer
**CONFIRMED.** At `synthetic.py:99` (line numbering differs slightly from submission's "93-96" due to counting), the function `build_triage_stage_items` contains:
```python
from desloppify.app.commands.plan.triage_playbook import (
    TRIAGE_STAGE_DEPENDENCIES,
    TRIAGE_STAGE_LABELS,
)
```
This is a direct engine→app import inside the `engine/_work_queue/` module.

### 2. Layer violation against documented architecture
**CONFIRMED.** The README states:
- "Import direction: Each layer imports only from lower-numbered layers" (line 54)
- `engine/` is Layer 1, `app/` is Layer 4 — so engine importing from app is a clear upward violation
- "Dynamic imports only in `languages/__init__.py` (discovery) and `engine/hook_registry.py` (hooks)" (line 92) — the deferred import in `synthetic.py` also violates this explicit allowlist

### 3. "Hard dependency" with no fallback
**CONFIRMED.** The import at line 99 has no `try/except ImportError` fallback. Compare with `engine/planning/dimension_rows.py:34-42` which wraps its engine→app import in `try/except ImportError` with a mechanical fallback. The `synthetic.py` import will raise `ImportError` if the app module is unavailable.

### 4. "16+ lazy imports in the engine layer"
**NOT VERIFIED IN DETAIL.** The submission mentions 16+ lazy imports in the engine layer but this claim is secondary. What matters is the confirmed violation.

### 5. Two engine→app violations
**CONFIRMED.** Both files identified by the submitter have engine→app imports:
- `engine/_work_queue/synthetic.py:99` — hard import (this submission)
- `engine/planning/dimension_rows.py:34` — soft import with try/except fallback

## What Is Being Imported

`TRIAGE_STAGE_LABELS` and `TRIAGE_STAGE_DEPENDENCIES` are simple constants (a tuple of tuples and a dict of sets) that define triage workflow metadata. They live in `app/commands/plan/triage_playbook.py` — a file that contains only constants and string templates. These constants have no app-layer dependencies themselves and could easily be relocated to `engine/` or `base/`.

## Duplicate Check
- No prior submission targets this specific file or import.
- S168 (@lianqing1) discusses layer violations in `base/subjective_dimensions.py` — different location.
- S221 (@g5n-dev) discusses circular dependencies broadly but does not specifically identify this import.
- S235 (@demithras) discusses private module boundary violations — different category.

## Assessment

The finding is **real and correctly identified**. The import violates two explicitly documented rules: the layer import direction rule and the dynamic import allowlist rule. The fix is straightforward — move the constants from `app/commands/plan/triage_playbook.py` to a shared location in `engine/` or `base/`.

However, caveats reduce the significance:
1. **Simple constants, not behavioral coupling**: The imported symbols are pure data constants with no dependencies. The violation is structural/organizational, not a deep architectural entanglement.
2. **Lazy import reduces practical impact**: The deferred import means the circular dependency only manifests at runtime when `build_triage_stage_items` is called, not at module load time.
3. **Trivial fix**: Moving two constant definitions is a ~10-line change. This is a misplacement of constants, not a fundamental design flaw.
4. **Not on critical hot path**: `build_triage_stage_items` is called during plan generation, not in tight loops or performance-sensitive code.
