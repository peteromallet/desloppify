# Bounty Verification: S005 — @agustif

**Comment ID:** 4000572452
**Verdict:** YES_WITH_CAVEATS

## Claims Verified

### Claim 1: base/subjective_dimensions.py upward imports violate architecture contract

**CONFIRMED.** `base/subjective_dimensions.py:10-17` imports from:
- `desloppify.intelligence.review.dimensions.data` (lines 10-14)
- `desloppify.intelligence.review.dimensions.metadata` (line 16)
- `desloppify.languages` (line 17)

`README.md:95` explicitly states: "base/ has zero upward imports — it never imports from engine/, app/, intelligence/, or languages/". This is a documented contract violation. Partially overlaps with S307 (sungdark), which noted this same violation as a "known architectural shortcut."

### Claim 2: metadata_legacy.py pulls DISPLAY_NAMES from scoring core

**CONFIRMED.** `intelligence/review/dimensions/metadata_legacy.py:5`:
```python
from desloppify.engine._scoring.subjective.core import DISPLAY_NAMES
```
Creates an `intelligence/` → `engine/_scoring/` cross-layer dependency.

### Claim 3: Scoring core reaches back into metadata via cycle-break imports

**CONFIRMED.** `engine/_scoring/subjective/core.py:61-69` and `72-80`:
```python
def _dimension_display_name(dim_name: str, *, lang_name: str | None) -> str:
    try:
        from desloppify.intelligence.review.dimensions.metadata import (
            dimension_display_name,  # cycle-break: subjective/core.py <-> metadata.py
        )
        return str(dimension_display_name(dim_name, lang_name=lang_name))
    except (AttributeError, RuntimeError, ValueError, TypeError):
        return DISPLAY_NAMES.get(dim_name, _display_fallback(dim_name))
```
Same pattern for `_dimension_weight` at lines 72-80. Both explicitly marked with `# cycle-break` comments. S312 (jujujuda) already covered the `_dimension_weight` silent `1.0` fallback.

### Claim 4: Duplicated dimension defaults across files

**CONFIRMED.** `DISPLAY_NAMES` dict (20 identical entries) exists in:
1. `base/subjective_dimensions.py:21-45`
2. `engine/_scoring/subjective/core.py:9-33`

Additionally, `metadata_legacy.py:9-38` has `_LEGACY_SUBJECTIVE_WEIGHTS_BY_DISPLAY` and `LEGACY_RESET_ON_SCAN_DIMENSIONS` which are equivalent to `base/subjective_dimensions.py:49-78`.

## Duplicate Coverage Assessment

- **S307 (sungdark):** Noted base/subjective_dimensions.py upward imports. S307 was NOT VERIFIED overall (fabricated code examples elsewhere), but this specific observation was correct.
- **S312 (jujujuda):** Covered `_dimension_weight` silent `1.0` fallback and noted the cycle-break pattern.

S005 adds value by:
1. Mapping the **complete circular chain**: `metadata_legacy.py` → `engine/_scoring/subjective/core.py` → (runtime) `intelligence/review/dimensions/metadata.py`
2. Identifying the **multi-home source of truth**: identical `DISPLAY_NAMES` in 2 files, equivalent defaults in a 3rd
3. Framing these as a systemic pattern rather than isolated issues

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 4/10 |
| Originality | 3/10 |
| Core Impact | 2/10 |
| Overall | 3/10 |

## One-line Verdict

Accurate identification of a circular dependency chain and multi-home defaults in the subjective-dimension metadata pipeline, but partially covered by S307/S312 and mitigated by existing cycle-break patterns.
