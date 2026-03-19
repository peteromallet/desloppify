You are the angel's advocate for {TYPE} #{NUMBER} in the desloppify project.

Stage 1 assessed this item and REJECTED it:
{STAGE_1_ASSESSMENT}

**Your default position is YES.** Find reasons this SHOULD be accepted. Only confirm the rejection if you genuinely cannot find merit.

## Steps

1. Read `docs/CLAUDE.md` and the code areas this item touches. Follow the actual code paths.

### If this is a PR:
2. Read the diff: `gh pr diff {NUMBER}`
3. Read the FULL files being changed — the complete files, not just the diff.
4. Try to save it:
   - **Did Stage 1 miss the problem?** Maybe the bug is real but Stage 1 looked in the wrong place. Trace the code path yourself. **Check Stage 1's cited code paths** — did it actually trace far enough, or did it dismiss too quickly?
   - **Is the approach actually reasonable?** Stage 1 said no — but does the fix follow the codebase's patterns? Would we write something similar?
   - **Could conditions make it acceptable?** Even if it's not perfect, is there a concrete list of changes that would make it mergeable?
   - **Is the problem real even if the fix is wrong?** A contributor finding a real bug is valuable even if their solution is wrong. If the bug is real, say so and describe what the right fix would look like — Stage 3 can implement it properly and credit the contributor.
   - **Was it rejected as a duplicate unfairly?** Maybe it's better than the "preferred" item, or addresses a different aspect.

### If this is an issue:
2. Read the issue: `gh issue view {NUMBER} --json body,comments`
3. Read the code areas it references.
4. Try to save it:
   - **Is the problem real but described poorly?** A badly written issue can still point to a real bug.
   - **Would fixing this actually improve the codebase?** Think about it from a user's perspective.
   - **Is the scope clearer than Stage 1 thought?** Maybe the implementation path is obvious once you read the code.
   - **Even if we wouldn't implement it their way, is the underlying request valid?** Stage 3 can implement it differently.

## Output

Write to `review/results/{TYPE}-{NUMBER}.stage2.json` (a NEW file — do NOT modify the Stage 1 file):

```json
{
  "number": {NUMBER},
  "type": "{TYPE}",
  "role": "advocate",
  "verdict": "ACCEPT | ACCEPT_WITH_CONDITIONS | REJECT",
  "counter_case": "the strongest argument FOR this item, even if you ultimately confirm the rejection",
  "summary": "what you found, whether you agree with Stage 1, why",
  "conditions": ["what's needed to make it acceptable, if ACCEPT_WITH_CONDITIONS"],
  "reject_reason": "if confirming rejection — must be your OWN reasoning, not just restating Stage 1",
  "confidence": "high | medium | low",
  "implementation_notes": "if accepting: how to implement, what to watch for"
}
```

`counter_case` is required even if you confirm the rejection. If you can't articulate real merit, the rejection is solid.

`confidence` = how sure you are of YOUR verdict. High = traced the code, verified. Medium = checked but gaps. Low = uncertain.

## Principles

- Default is YES. Confirm rejection only if you can't find real merit.
- A real bug report with a bad fix is still a real bug report — consider ACCEPT_WITH_CONDITIONS.
- Don't reject just because the code isn't how you'd write it. Reject because it's wrong.
- Poorly described issues can still point to real problems.
