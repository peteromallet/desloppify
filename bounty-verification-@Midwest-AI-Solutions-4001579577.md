# Bounty S032 Verification: @Midwest-AI-Solutions — Naive str.replace corrupts cluster descriptions

**Issue:** https://github.com/peteromallet/desloppify/issues/204
**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4001579577
**Author:** @Midwest-AI-Solutions
**Snapshot commit:** `6eb2065`

## Claim

`_build_cluster_meta` in `plan_order.py:159-162` uses global `str.replace` to update a count embedded in a natural-language description. This replaces every occurrence of the digit substring, not just the intended count — silently corrupting other numbers in the description.

## Evidence

### Code at snapshot (confirmed match)

```python
# desloppify/engine/_work_queue/plan_order.py:159-162 at 6eb2065
stored_desc = cluster_data.get("description") or ""
total_in_cluster = len(cluster_data.get("issue_ids", []))
if stored_desc and total_in_cluster != len(members):
    summary = stored_desc.replace(str(total_in_cluster), str(len(members)))
```

The code matches exactly. `str.replace` with no `count` argument performs global substitution.

### How descriptions are actually generated

`cluster_strategy.py:generate_description` (lines 71-101 at `6eb2065`) produces descriptions from simple templates:
- `f"Address {count} {dimension} review issues"`
- `f"Fix {count} {label} issues"`
- `f"Remove {count} {display} issues"`
- `f"Review {count} large files"`

These templates embed **only the count number** — no other digits. The submission's hypothetical examples ("Fix 12 naming violations across 112 files") do not match actual generated descriptions.

### Triggering conditions

The bug requires:
1. `total_in_cluster != len(members)` — filtering changed visible count
2. The digit string of the old count appears elsewhere in the description

Condition 1 can occur (status/scope filtering). Condition 2 is unlikely with current templates but could occur with manually edited plan descriptions or future template changes.

### Fix status

The code is **still unfixed** as of HEAD — identical to the snapshot.

## Verdict

| Question | Answer | Reasoning |
|----------|--------|-----------|
| **Is this poor engineering?** | YES | `str.replace` for count substitution in natural language is a known anti-pattern |
| **Is this at least somewhat significant?** | MARGINAL | Current description templates contain only one number, so collisions are unlikely in practice |

**Final verdict:** YES_WITH_CAVEATS

The bug mechanism is correctly identified and well-explained. The submission earns credit for spotting a genuine anti-pattern. However, the severity is overstated — the dramatic examples ("112 files" → "88 files") don't reflect actual generated descriptions, which typically contain only the count number. The practical corruption risk is low with current code, though it represents a latent fragility.

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 4/10 |
| Originality | 7/10 |
| Core Impact | 3/10 |
| Overall | 4/10 |

- **Significance 4/10:** Technically real but low practical impact with current templates.
- **Originality 7/10:** No duplicate submissions about this specific issue. Good eye for a subtle anti-pattern.
- **Core Impact 3/10:** Cluster descriptions are informational, not functional. Corruption would mislead but not break workflows.
- **Overall 4/10:** Valid finding, well-presented, but practical risk significantly overstated.
