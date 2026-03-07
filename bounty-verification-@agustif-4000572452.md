# Bounty Verification: S005 @agustif

## Submission

The subjective-dimension metadata pipeline has a circular, multi-home source of truth that violates the repo's own architecture contract.

## Evidence Trace

### Claim 1: base/ must have zero upward imports (README:95)

**VERIFIED.** `desloppify/README.md` states under Rules:
> `base/` has zero upward imports -- it never imports from `engine/`, `app/`, `intelligence/`, or `languages/`

### Claim 2: base/subjective_dimensions.py imports upward into intelligence and languages (:10-17)

**VERIFIED.** At commit `6eb2065`, `desloppify/base/subjective_dimensions.py` lines 10-16:
```python
from desloppify.intelligence.review.dimensions.data import (
    load_dimensions as _load_dimensions,
)
from desloppify.intelligence.review.dimensions.data import (
    load_dimensions_for_lang as _load_dimensions_for_lang,
)
from desloppify.intelligence.review.dimensions.metadata import extract_prompt_meta
from desloppify.languages import available_langs as _available_langs
```
These are top-level imports from Layer 4 (`intelligence/`) and Layer 3 (`languages/`) into Layer 0 (`base/`), directly violating the documented contract.

### Claim 3: metadata_legacy.py pulls DISPLAY_NAMES from scoring core (:5)

**VERIFIED.** `desloppify/intelligence/review/dimensions/metadata_legacy.py` line 5:
```python
from desloppify.engine._scoring.subjective.core import DISPLAY_NAMES
```

### Claim 4: scoring core reaches back into metadata via runtime imports marked as cycle breaks (:63-76)

**VERIFIED.** `desloppify/engine/_scoring/subjective/core.py` lines 63-76:
```python
def _dimension_display_name(dim_name: str, *, lang_name: str | None) -> str:
    try:
        from desloppify.intelligence.review.dimensions.metadata import (
            dimension_display_name,  # cycle-break: subjective/core.py <-> metadata.py
        )
        return str(dimension_display_name(dim_name, lang_name=lang_name))
    except (AttributeError, RuntimeError, ValueError, TypeError):
        return DISPLAY_NAMES.get(dim_name, _display_fallback(dim_name))

def _dimension_weight(dim_name: str, *, lang_name: str | None) -> float:
    try:
        from desloppify.intelligence.review.dimensions.metadata import (
            dimension_weight,  # cycle-break: subjective/core.py <-> metadata.py
        )
        return float(dimension_weight(dim_name, lang_name=lang_name))
    except (AttributeError, RuntimeError, ValueError, TypeError):
        return 1.0
```

### Claim 5: Same dimension defaults duplicated across three files

**VERIFIED.** The `DISPLAY_NAMES` dict (20 entries) is duplicated verbatim between:
- `base/subjective_dimensions.py:21-50`
- `engine/_scoring/subjective/core.py:9-33`

Weight and reset-on-scan dicts are duplicated between:
- `base/subjective_dimensions.py:52-77`
- `intelligence/review/dimensions/metadata_legacy.py:9-38`

### Full circular dependency chain

```
base/subjective_dimensions.py
  -> intelligence/review/dimensions/metadata.py (extract_prompt_meta)
     -> intelligence/review/dimensions/metadata_legacy.py
        -> engine/_scoring/subjective/core.py (DISPLAY_NAMES)
           -> intelligence/review/dimensions/metadata.py (lazy cycle-break)
```

## Duplicate Check

S168 (lianqing1, March 5) identifies the same layer violation in `base/subjective_dimensions.py` but S005 (agustif, March 4) was submitted ~18 hours earlier with significantly more detail. S005 has priority.

## Verdict

All five claims are verified against commit `6eb2065`. The submission correctly identifies a real architecture violation with concrete file:line evidence and a clear explanation of why it matters (brittle cross-layer knot, masked breakage via silent fallbacks, maintenance cost of synchronized duplicates).
