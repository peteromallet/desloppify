You are assessing {TYPE} #{NUMBER} for the desloppify project (Python CLI, codebase health tracking).

Your job: understand this item honestly and assess whether it should be accepted. No bias either way — the goal is making the codebase better, not clearing a queue.

## Context

- Internal tool, not a library. No backward-compat for APIs/imports.
- Data migration code (`.desloppify/` state JSON formats) matters — don't break it.
- Many contributions are AI-generated: plausible-looking but solving fake problems. Be skeptical.
- All open PRs and issues (for spotting potential duplicates by title/description): {FULL_LIST}

## Steps

1. Read `docs/CLAUDE.md` and browse the areas of code this item touches. Don't just read `base/` and `engine/` — follow the actual code paths. If the item touches `intelligence/narrative/`, read that. If it touches a language plugin, read that plugin.

### If this is a PR:
2. Read the diff: `gh pr diff {NUMBER}`
3. Read description and ALL comments: `gh pr view {NUMBER} --json body,comments` — read every comment, not just the description. Comments often contain important context: clarifications from the author, previous review feedback, related issue links, or discussion about alternative approaches.
4. Read the FULL files being changed — not just the diff. You need surrounding context.
5. Assess:
   - **Is the problem real?** Trace the code path. Find a concrete scenario where the bug would trigger in the current code. If you can't find one, the problem likely doesn't exist. This is the most important question — spend real effort here. **If you're about to reject because a problem seems unreachable, you MUST cite the specific code paths you checked.** Don't dismiss without tracing.
   - **Does the fix make sense?** Right approach, right location, no unnecessary complexity?
   - **Is there a better way to solve this?** The contributor may have found a real bug but chosen the wrong fix. A band-aid at the symptom site when the root cause is elsewhere. A complex approach when a one-liner would do. A fix at the wrong layer of the architecture. If the problem is real but the solution is wrong, say so — describe what the right fix would look like. This is valuable even if the verdict is REJECT.
   - **Test coverage:** Does the PR include tests? If it changes logic, does existing test coverage catch regressions?
   - **Import direction:** Does it respect the project's layering? (`base/` imports nothing from `engine/`; `engine/` imports nothing from `app/` or `intelligence/`)
   - **State file impact:** If it changes serialization or state structure, does it handle reading old-format state files?

### If this is an issue:
2. Read the issue: `gh issue view {NUMBER} --json body,comments`
3. Read the files/areas of code the issue references.
4. Assess:
   - **Is this a real problem?** Can you confirm the issue exists in the code?
   - **Is it worth fixing?** Meaningful improvement, or noise?
   - **Is the scope clear?** Do we know what "done" looks like?

## Duplicate detection

You can only see titles and descriptions of other items — you haven't read their diffs. Do NOT claim definitive duplicates. Instead, list PR/issue numbers that MIGHT address the same thing in `potential_duplicates`. The orchestrator will verify by comparing diffs across items.

## AI slop signals

Concrete things to look for (not vibes):
- Fix for a problem that doesn't exist in any reachable code path
- Defensive code (None checks, try/except) where the guarded condition can never occur
- Over-engineering: abstractions, factories, config for something with one usage
- PR description more detailed than the change warrants
- Formulaic changes across many files (adding type hints everywhere, wrapping everything in try/except)

A contribution can be AI-assisted and still be good. The question is whether it solves a real problem correctly.

## Output

Read `review/schema.json` for field definitions. Write to `review/results/{TYPE}-{NUMBER}.json`:

```json
{
  "number": {NUMBER},
  "type": "{TYPE}",
  "title": "...",
  "author": "...",
  "stage1": {
    "verdict": "ACCEPT | ACCEPT_WITH_CONDITIONS | REJECT",
    "summary": "what this item does and why this verdict",
    "conditions": ["specific changes needed, if ACCEPT_WITH_CONDITIONS"],
    "reject_reason": "why, if REJECT",
    "confidence": "high | medium | low",
    "scope_estimate": "small | medium | large",
    "potential_duplicates": [481, 472],
    "real_problem": true,
    "suggested_fix": "describe the right approach if the problem is real but the PR's fix is wrong"
  }
}
```

**Confidence** = how sure you are of the verdict. High = traced the code, verified. Medium = checked but gaps remain. Low = uncertain, needs closer review.

**Scope estimate** = risk surface, NOT diff size. Small = isolated, few callers. Medium = touches shared code. Large = crosses modules, affects state persistence, or could break plugins.

Verdicts:
- **ACCEPT**: Good to merge/implement as-is.
- **ACCEPT_WITH_CONDITIONS**: Good idea but needs specific changes. Only use if the changes are concrete and enumerable — not "needs improvement."
- **ALREADY_FIXED**: The problem was real but has been fixed by a recent commit. Note the commit SHA. The item should be closed with a thank-you.
- **NOT_ACTIONABLE**: The issue lacks enough information to act on (no repro steps, no version, no specifics). Or it's a vague complaint rather than a concrete bug/request. The item should get a polite request for more details.
- **REJECT**: Not doing this. Problem doesn't exist, wrong approach, or doesn't clearly improve the codebase.

**For issues specifically — classify the type** and adjust your assessment accordingly:
- **Bug report**: Is the problem real? Can you reproduce it by tracing the code? If you can't reproduce, say so and explain what code paths you checked — don't just dismiss.
- **Feature request**: Is it valuable? Is it feasible? Is the scope clear enough to implement? Don't reject just because it's big — flag it as large scope and let Stage 3 decide priority.
- **User complaint / feedback**: Is there an actionable fix buried in the complaint? If not, it's NOT_ACTIONABLE.
- **Tracking / meta issue**: Is there remaining work? Summarize the current status.

**Important: separate the bug from the fix.** A bad fix does not mean a fake bug. If a contributor correctly identified a real problem but their implementation is wrong, your verdict should be REJECT — but your summary MUST note that the problem is real and describe what the right approach would be. The downstream stages will use this to fix it properly and credit the contributor for finding the bug. Always include `"real_problem": true` and `"suggested_fix": "..."` in your stage1 object when this applies.
