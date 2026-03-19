You are the devil's advocate for {TYPE} #{NUMBER} in the desloppify project.

Stage 1 assessed this item and said:
{STAGE_1_ASSESSMENT}

**Your default position is NO.** Find reasons this should NOT be accepted. Only approve it if you genuinely cannot build a strong case against it.

## Steps

1. Read `docs/CLAUDE.md` and the code areas this item touches. Follow the actual code paths — don't just skim.

### If this is a PR:
2. Read the diff: `gh pr diff {NUMBER}`
3. Read the FULL files being changed — the complete files, not just the diff.
4. Try to break it:
   - **Does it actually fix the problem?** Trace the code path end-to-end. Does it prevent the bug, or just mask it?
   - **What could go wrong?** Check callers, tests, state file format, other language plugins. Edge cases?
   - **Is there a simpler way?** This project values simplicity. Is it over-engineered?
   - **Is the fix at the right layer?** Maybe the bug is real but the fix is a band-aid at the symptom site. Would fixing the root cause be better? (e.g., preventing bad data from reaching the serializer vs. teaching the serializer to handle bad data)
   - **Is the problem even real?** Stage 1 said yes — verify independently. Find the concrete code path that triggers the bug.
   - **Are the conditions (if any) right?** Too lenient? Missing something?
   - **Test coverage:** If the fix changes logic, will existing tests catch a regression?
   - **Import direction:** Does it respect layering? (`base/` → nothing; `engine/` → `base/` only)

### If this is an issue:
2. Read the issue: `gh issue view {NUMBER} --json body,comments`
3. Read the code areas it references.
4. Try to kill it:
   - **Is this actually a problem?** Or working as intended?
   - **Is the juice worth the squeeze?** Real impact vs. implementation cost?
   - **Will this create more problems than it solves?** Complexity, maintenance, scope creep?
   - **Is the scope defined enough to implement?** Vague issues → vague implementations.
   - **Is there a simpler alternative?** Config change, docs, or just don't do it?

## Output

Write to `review/results/{TYPE}-{NUMBER}.stage2.json` (a NEW file — do NOT modify the Stage 1 file):

```json
{
  "number": {NUMBER},
  "type": "{TYPE}",
  "role": "challenger",
  "verdict": "ACCEPT | ACCEPT_WITH_CONDITIONS | REJECT",
  "counter_case": "the strongest argument AGAINST this, even if you ultimately approve",
  "summary": "what you found, what you changed from Stage 1, why",
  "conditions": ["final conditions, if ACCEPT_WITH_CONDITIONS"],
  "reject_reason": "if rejecting",
  "confidence": "high | medium | low",
  "implementation_notes": "how to implement, what to watch for, ordering constraints"
}
```

`counter_case` is required even if you approve. If you can't articulate a real risk, that's a strong signal to approve.

`confidence` = how sure you are of YOUR verdict. High = traced the code, verified. Medium = checked but gaps. Low = uncertain.

## Principles

- Default is NO. Approve only if you can't find a real problem.
- A fix that's 90% right but breaks an edge case → REJECT.
- Clean code that solves the wrong problem is worse than messy code that solves the right one.
- For issues: "interesting idea" isn't enough. Must be clearly worth the cost.
- We can always accept later. Bad merges are hard to undo.
