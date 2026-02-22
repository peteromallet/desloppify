## Windsurf Overlay

Windsurf does not support spawning subagents from within a Cascade session.
Parallel reviews require the user to open multiple Cascade panes manually.

### Review workflow

1. Run `desloppify review --prepare` to generate `query.json`.
2. Ask the user to open additional Cascade panes for parallel review.
   Suggest splitting dimensions across 2-3 panes (e.g., naming + clarity
   in one, abstraction + error consistency in another).
3. Each pane should score its assigned dimensions independently, reading
   the codebase and `query.json`'s `dimension_prompts` for context.
4. Each pane writes its output to a separate file.
5. In the primary pane, merge assessments (average where dimensions overlap)
   and findings, then `desloppify review --import findings.json`.

If the user prefers a single-pane workflow, review all dimensions sequentially
in one session. This is slower but still works.

### Review integrity

1. Do not use prior chat context, score history, or target-threshold anchoring while scoring.
2. Score from evidence only; when evidence is mixed, score lower and explain uncertainty.
3. Return machine-readable JSON only for review imports:

```json
{
  "assessments": {
    "naming_quality": 0,
    "error_consistency": 0,
    "abstraction_fit": 0,
    "logic_clarity": 0,
    "ai_generated_debt": 0
  },
  "findings": []
}
```
