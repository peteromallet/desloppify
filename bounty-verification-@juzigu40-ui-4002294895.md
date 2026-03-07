# Bounty Verification: S089 — Anti-gaming attestation syntactic-only

**Submission:** [S089](https://github.com/peteromallet/desloppify/issues/204#issuecomment-4002294895)
**Author:** @juzigu40-ui
**Snapshot:** `6eb2065`

## Claims & Verification

### Claim 1: Attestation validator checks only two substrings
**File:** `desloppify/app/commands/helpers/attestation.py:9-27`
**Verdict:** CONFIRMED

```python
_REQUIRED_ATTESTATION_PHRASES = ("i have actually", "not gaming")

def _missing_attestation_keywords(attestation: str | None) -> list[str]:
    normalized = " ".join((attestation or "").strip().lower().split())
    return [phrase for phrase in _REQUIRED_ATTESTATION_PHRASES if phrase not in normalized]

def validate_attestation(attestation: str | None) -> bool:
    return not _missing_attestation_keywords(attestation)
```

Any string containing both "i have actually" and "not gaming" passes. No semantic validation.

### Claim 2: `--confirm` auto-builds a passing attestation
**File:** `desloppify/app/commands/plan/override_handlers.py:492-499`
**Verdict:** CONFIRMED

```python
if getattr(args, "confirm", False):
    if not note:
        print(colorize("  --confirm requires --note to describe what you did.", "red"))
        return
    attestation = f"I have actually {note} and I am not gaming the score."
```

The template `"I have actually {note} and I am not gaming the score."` trivially passes `validate_attestation()` regardless of note content.

### Claim 3: Resolve mutates issue status and persists
**File:** `desloppify/engine/_state/resolution.py:130-171`
**Verdict:** CONFIRMED

`resolve_issues()` sets `status`, `resolved_at`, `note`, and `resolution_attestation` on matching issues, then calls `_recompute_stats()`. The attestation is stored as:
```python
"resolution_attestation": {
    "kind": "manual",
    "text": attestation,
    "attested_at": now,
    "scan_verified": False,  # ← key mitigation
}
```

### Claim 4: Score guide treats verified as scan-verified only
**File:** `desloppify/app/commands/scan/reporting/summary.py:116-120`
**Verdict:** CONFIRMED

```
strict   = like overall, but wontfix counts against you  <-- your north star
verified = strict, but only credits scan-verified fixes
```

## Mitigating Factors

1. **`scan_verified: False`** — Manual resolutions are explicitly marked as not scan-verified. The "verified" score mode (which the guide recommends as north star) does NOT credit manual resolutions. The submission overstates this as "state/score mutations are accepted as evidence" — they're accepted for `strict` but not `verified`.

2. **`--confirm` still requires `--note` (≥50 chars)** — Users must describe what they did. The note is persisted in the resolution attestation for audit.

3. **Intentional UX design** — The attestation is a speed bump / self-accountability prompt, not a security boundary. The four-tier score system (overall → objective → strict → verified) provides graduated trust levels by design.

4. **`--confirm` is a convenience flag** — Without it, users must manually provide `--attest` text containing the required phrases. The auto-generation just removes friction for the common case.

## Duplicate Check

- **S147** (same author) covers attestation weakness in the context of suppression integrity — related but distinct focus (suppression vs resolution).
- **S249** (@Tib-Gridello) covers anti-gaming check timing — different topic.
- No prior submission specifically identifies the `--confirm` auto-generation bypass. **Original finding.**

## Verdict: YES_WITH_CAVEATS

The observation is technically correct: the attestation is trivially bypassable via substring matching, and `--confirm` auto-generates a passing attestation. However:
- The `verified` score mode already mitigates this by requiring scan-verified evidence
- Manual resolutions are explicitly marked `scan_verified: False`
- The attestation is an intentional UX speed bump, not a security control
- "Structural trust-boundary failure" overstates the impact

| Criterion | Score | Reasoning |
|-----------|-------|-----------|
| Significance | 4/10 | Real but intentionally low-friction by design; mitigated by verified score |
| Originality | 6/10 | First to identify `--confirm` auto-generation; no prior duplicates |
| Core Impact | 3/10 | Affects strict score only; verified score unaffected; UX choice not a bug |
| Overall | 4/10 | Valid observation, overstated significance |
