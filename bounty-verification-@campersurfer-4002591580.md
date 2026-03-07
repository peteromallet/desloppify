# Bounty Verification: S117 @campersurfer — Review Issue Identity Structurally Unstable

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4002591580
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `sha256(summary)[:8]` baked into per-file issue IDs
**CONFIRMED.** `per_file.py:113` computes `content_hash = hashlib.sha256(issue["summary"].encode()).hexdigest()[:8]`, then at line 120 uses it in `name=f"{dimension}::{issue['identifier']}::{content_hash}"`. The `make_issue` function at `filtering.py:160` builds `issue_id = f"{detector}::{rfile}::{name}"`, so the summary hash is embedded in the issue identity.

### 2. `sha256(summary)[:8]` baked into holistic issue IDs
**CONFIRMED.** `holistic_issue_flow.py:107` computes the same `content_hash = hashlib.sha256(summary_text.encode()).hexdigest()[:8]`, used at line 119 in `name=f"{prefix}::{dimension}::{issue['identifier']}::{content_hash}"`.

### 3. Auto-resolve creates phantom churn when summary wording changes
**CONFIRMED.** `resolution.py:18-30` (`auto_resolve_review_issues`) iterates all open issues and auto-resolves any whose `issue_id` is NOT in `new_ids`. When the LLM produces a different summary for the same logical finding, the hash changes, producing a new ID. The old ID is absent from `new_ids` and gets auto-resolved. The same finding simultaneously appears as "auto_resolved" (old ID) and "new" (new ID).

### 4. History loss on re-review
**CONFIRMED.** `filtering.py:162-176` (`make_issue`) assigns fresh `first_seen`, `reopen_count: 0`, `note: None`, `status: "open"` to every newly created issue. When a finding gets a new ID due to summary rewording, all prior history (manual notes, suppression state, reopen count, first-seen timestamp) is lost.

### 5. `identifier` field was intended as the stable semantic key
**CONFIRMED.** The `identifier` field is passed through by the LLM and included in the name, but the content hash appended after it defeats its purpose as a stable dedup key. Removing the hash and using `identifier` alone (as the submission suggests) would provide stable identity across re-reviews.

## Duplicate Check
No other submission in the bounty inbox raises this specific issue. Searched for "content_hash", "sha256(summary)", "content hash", "summary hash" — only S117 matches.

## Assessment
This is a well-analyzed, original finding with precise code references that all check out. The submission correctly identifies a structural design flaw: coupling issue identity to LLM-generated text creates non-deterministic IDs that undermine the tool's own tracking guarantees (history, suppression, progress measurement).

The fix is straightforward: remove `content_hash` from the `name` parameter and store the summary as mutable metadata. This would make issue identity depend on `(detector, file, dimension, identifier)` — the semantic coordinates of the finding — rather than on how the LLM chose to describe it.

This is not merely a theoretical concern: LLMs are inherently non-deterministic, and even deterministic temperature=0 outputs can change across model versions or API updates. Every such change silently resets tracking state for affected findings.
