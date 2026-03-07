# Bounty Verification: S183 @MacHatter1 — review import split-brain parser

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4006883883
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `cmd.py` routes through `helpers.load_import_issues_data()`
**CONFIRMED.** `cmd.py:360-368` calls `import_helpers_mod.load_import_issues_data()`, where `import_helpers_mod` is `from . import helpers as import_helpers_mod` (line 43).

### 2. `helpers.py` rejects `{"findings": []}` payloads
**CONFIRMED.** `helpers._parse_and_validate_import` (lines 141-165) checks `if "issues" not in issues_data` and returns error `"issues object must contain a 'issues' key"`. It does NOT call `normalize_legacy_findings_alias`. Zero occurrences of "findings" or "normalize_legacy" in helpers.py at snapshot.

### 3. `parse.py` normalizes `findings -> issues` via shared payload logic
**CONFIRMED.** `parse._normalize_import_root_payload` (lines 288-299) calls `normalize_legacy_findings_alias(payload, ...)` from `payload.py`. The `payload.py:normalize_legacy_findings_alias` function (lines 26-40) renames `findings` to `issues` when `ALLOW_LEGACY_FINDINGS_ALIAS` is True.

### 4. Tests exercise the newer parse path
**CONFIRMED.** `test_direct_coverage_priority_modules.py:118-121` calls `review_import_parse_mod._normalize_import_root_payload({"findings": []})` and asserts success — exercising the `parse.py` path, not the `helpers.py` path used by the CLI.

## Duplicate Check
- **S166** (@usernametooshort) identifies related duplication in the same `parse.py`/`helpers.py` files, but focuses on the duplicate `ImportPayloadLoadError` exception class — a different symptom of the same underlying split. S183 identifies the behavioral parser divergence specifically around `findings` normalization.
- No other submission covers this exact behavioral divergence.

## Assessment
The core observation is valid: two parallel `load_import_issues_data()` / `_parse_and_validate_import()` implementations exist, and the one used by the CLI (`helpers`) lacks the `findings -> issues` normalization present in the one used by tests (`parse`). A compatibility fix landing in `parse.py` goes green in tests but never affects the CLI.

Caveats:
1. **Limited practical scope**: The `findings` alias is a legacy compatibility feature (`ALLOW_LEGACY_FINDINGS_ALIAS` with sunset date 2026-12-31). Only legacy payloads using the old `findings` key are affected.
2. **Related duplication already identified**: S166 flagged the broader `parse.py`/`helpers.py` duplication problem, though from a different angle (exception class identity).
3. **Single concrete divergence demonstrated**: The submission demonstrates one specific behavioral difference (`findings` normalization). The "split-brain" framing is accurate but the demonstrated impact is narrow.

The finding is structurally sound and well-referenced. The behavioral divergence at the import trust boundary is a real engineering concern.
