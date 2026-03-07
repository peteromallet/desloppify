# Bounty Verification: S005 — @agustif submission

## Status: YES_WITH_CAVEATS

## Claims vs Reality

### Claim 1: base/subjective_dimensions.py upward imports violate architecture contract

> `desloppify/base/subjective_dimensions.py` imports upward into `intelligence` and `languages` (`:10-17`), violating the documented architecture rule.

**TRUE.**

`base/subjective_dimensions.py:10-17` imports from:
- `desloppify.intelligence.review.dimensions.data` (lines 10-14)
- `desloppify.intelligence.review.dimensions.metadata` (line 16)
- `desloppify.languages` (line 17)

The architecture doc (`desloppify/README.md:95`) explicitly states:
> `base/` has zero upward imports — it never imports from `engine/`, `app/`, `intelligence/`, or `languages/`

This is a clear, documented violation. However, S307 already noted this same violation as a "known architectural shortcut" (S307 verdict line 8).

### Claim 2: metadata_legacy.py pulls DISPLAY_NAMES from scoring core

> `desloppify/intelligence/review/dimensions/metadata_legacy.py` pulls `DISPLAY_NAMES` from scoring core (`:5`).

**TRUE.**

`metadata_legacy.py:5`:
```python
from desloppify.engine._scoring.subjective.core import DISPLAY_NAMES
```

This creates a dependency from `intelligence/` layer into `engine/_scoring/` layer.

### Claim 3: Scoring core reaches back into metadata via cycle-break imports

> Scoring core reaches back into metadata via runtime imports explicitly marked as cycle breaks (`engine/_scoring/subjective/core.py:63-76`).

**TRUE.**

`engine/_scoring/subjective/core.py:63-76`:
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

Same pattern at lines 72-80 for `_dimension_weight`. Both are explicitly marked with `# cycle-break` comments, confirming the circular dependency is known and worked around.

S312 already covers this same `_dimension_weight` fallback as a "silent fallback" concern.

### Claim 4: Duplicated dimension defaults across files

> The same dimension defaults are duplicated across files (`base/subjective_dimensions.py:21-77`, `engine/_scoring/subjective/core.py:9-33`, `metadata_legacy.py:9-38`).

**TRUE.**

Three identical/equivalent copies exist:
1. `base/subjective_dimensions.py:21-45` — `DISPLAY_NAMES` dict (20 entries)
2. `engine/_scoring/subjective/core.py:9-33` — `DISPLAY_NAMES` dict (20 entries, identical)
3. `metadata_legacy.py:9-38` — `_LEGACY_SUBJECTIVE_WEIGHTS_BY_DISPLAY` and `LEGACY_RESET_ON_SCAN_DIMENSIONS` (equivalent defaults)

Additionally, `base/subjective_dimensions.py:49-78` duplicates the weight and reset-on-scan defaults from `metadata_legacy.py:9-38`.

## Duplicate Coverage Assessment

- **S307 (sungdark)**: Already noted the `base/subjective_dimensions.py` upward import as a layering violation. Dismissed it as a "known architectural shortcut, not a novel finding."
- **S312 (jujujuda)**: Already covered the `_dimension_weight` silent `1.0` fallback in scoring core. Noted the `# cycle-break` comment.

S005 adds value beyond S307/S312 by:
1. Mapping the **complete circular dependency chain**: `metadata_legacy.py` → `engine/_scoring/subjective/core.py` → (runtime) `intelligence/review/dimensions/metadata.py` → `metadata_legacy.py`
2. Identifying the **multi-home source of truth** problem: three files define the same dimension defaults
3. Connecting these as a systemic pattern rather than isolated observations

However, the individual components were already partially covered.

## Accuracy Assessment

- File paths: 100% accurate — all cited files and line ranges are correct
- Code examples: Accurate — imports, cycle-break comments, and duplication verified
- Architectural claim: Accurate — README.md:95 does document the violated contract

## Scores

- **Significance (Sig)**: 4 — Real architectural violation of a documented contract, but the codebase works correctly despite the cycle (runtime imports + fallbacks prevent actual breakage)
- **Originality (Orig)**: 3 — Individual components partially covered by S307 (upward imports) and S312 (weight fallback), but S005 connects them into a coherent circular-dependency narrative
- **Core Impact**: 2 — Affects dimension metadata pipeline, not the core scoring/gaming-resistance logic; the cycle-break fallbacks ensure scores are computed correctly
- **Overall**: 3 — Technically accurate and well-evidenced, but partially duplicative and the practical impact is low since the system handles the cycle gracefully

## One-line verdict
Accurate identification of a circular dependency chain and multi-home defaults in the subjective-dimension metadata pipeline, but partially covered by S307/S312 and mitigated by existing cycle-break patterns.
