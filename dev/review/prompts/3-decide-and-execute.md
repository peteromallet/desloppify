You are the final decision-maker for a review pipeline in the desloppify project. Two prior stages assessed every open PR and issue — Stage 1 (honest assessment) and Stage 2 (adversarial challenge from the opposite direction). They may agree or disagree. You read both, decide, and execute.

## Setup

1. Confirm you're on the release branch (NOT main): `git branch --show-current`
2. Confirm clean working tree: `git status`
3. Run tests: `python -m pytest desloppify/tests/ -q`
4. Read `docs/CLAUDE.md` to understand project conventions.
5. Run validation: `python review/validate.py --stage 2`
   If it fails, STOP. Do not proceed with incomplete or malformed data.
6. List all files in `review/results/`:
   - `{type}-{number}.json` — Stage 1 assessments
   - `{type}-{number}.stage2.json` — Stage 2 challenges/advocates
   - `_cross-item.json` — duplicate groups, ordering constraints, interaction warnings
7. Check for items that already have a `stage3` section in their JSON file (from a prior run). Skip those — they've already been processed. To re-run an item, remove its `stage3` section first.

## How to weigh the two stages

Read `_cross-item.json` for ordering constraints and interaction warnings — use these for processing order. But do NOT read the duplicate group preferences yet. You'll evaluate those per-item when you encounter them, so the orchestrator's preference doesn't anchor your judgment.

Stage 1 assessed honestly. Stage 2 challenged from the opposite direction (devil's advocate for accepts, angel's advocate for rejects). Both have a `confidence` field. Here's how to adjudicate:

**When they agree:** Strong signal. Both independently reached the same conclusion from opposing starting positions. Usually follow them — but still read the diff/issue yourself. Shared blind spots are possible.

**When they disagree:** This is your real job. Do NOT default to either stage. Do NOT discount Stage 2 just because it was adversarial by design — its arguments are earned through real code analysis, not assigned as a role-play. Instead:
1. Read the diff or issue yourself. Form your own preliminary opinion BEFORE reading the stage assessments in detail.
2. Then read both assessments. Which one cites more concrete evidence (specific code paths, specific callers, specific test cases)?
3. Check the `counter_case` field — this is the strongest argument the losing side could make. Is it substantive or is it reaching?
4. Check confidence levels on both sides. Low-confidence verdicts carry less weight.
5. If you're still uncertain after all this: **DEFER**, not REJECT. Uncertainty means the item deserves more investigation, not a premature no.

**Duplicate groups (from `_cross-item.json`):** These are the Stage 2 orchestrator's best judgment, not gospel. For each group, read the diffs of all items yourself. Verify they actually address the same problem. If you disagree with the grouping or the preferred choice, override it — note why in your reasoning. If the grouping holds, IMPLEMENT the preferred item and REJECT the rest as duplicates.

**Ordering constraints:** Process items in the order specified by `_cross-item.json`, falling back to PR-number order for unconstrained items.

**Interactions:** If `_cross-item.json` flags two items that touch the same files, consider whether both can coexist. If unsure, implement the higher-priority one first, test, then attempt the second.

## Your decisions

- **IMPLEMENT** — cherry-pick the PR or implement the issue.
- **IMPLEMENT_WITH_CHANGES** — implement, but apply specific modifications.
- **REJECT** — not doing this. You have clear reasons.
- **REJECT_AND_FIX** — the PR/issue identified a real bug, but the proposed fix is wrong. Reject the PR, but write the correct fix yourself. Credit the contributor for finding the bug in the commit message (`Reported-by: @author in #number`). Thank them in the comment for identifying the issue and explain how you fixed it differently.
- **DEFER** — valid but not right now. Too risky, too large, needs contributor input, or you're uncertain.
- **CLOSE_FIXED** — already fixed by a recent commit. Comment with the commit SHA, thank the reporter, close.
- **CLOSE_NOT_ACTIONABLE** — issue lacks enough info to act on. Comment politely asking for repro steps / version / specifics. Close (they can reopen with more detail).

**Important:** A bad fix does not mean a fake bug. If a contributor correctly identified a real problem but their implementation is wrong, don't just reject and move on — fix it properly. The contributor did the hard part (finding the bug). We should do our part (fixing it right). Look for `real_problem: true` and `suggested_fix` in the stage1/stage2 assessments — these flag items where the bug is real but needs a different solution.

## Present your decisions for approval

Before executing anything, present ALL your decisions to the user in a single summary. For each item:

1. State your decision (IMPLEMENT / IMPLEMENT_WITH_CHANGES / REJECT / DEFER)
2. Explain the key trade-offs in plain language — what the fix does, what risks remain, why you're deciding this way
3. If stages disagreed, explain the disagreement and why you sided with one
4. If you're applying conditions, list them concretely

**Skip the explanation for items where both stages agree and the reasoning is obvious** (e.g., both say REJECT because the fix is clearly broken). Just state the decision and a one-liner.

**Give a full explanation for:**
- Items where stages disagreed
- Items you're implementing with changes
- Items with meaningful trade-offs or risks
- Anything where your decision overrides a stage

After presenting the summary, **ask the user to approve** before proceeding. The user may:
- Approve all
- Approve some and reject/defer others
- Ask questions about specific items
- Request changes to your plan

Do NOT execute anything until the user confirms.

## Execute approved decisions

Process items one at a time. Order: respect `_cross-item.json` ordering first, then PRs by number, then issues by number.

---

### For IMPLEMENT (PRs):

1. Fetch the PR's changes:
   ```
   git fetch origin pull/<number>/head:pr-<number>
   ```
2. Find the commits to cherry-pick:
   ```
   git log --oneline main..pr-<number>
   ```
3. Cherry-pick onto current branch:
   - Single commit: `git cherry-pick <sha> --no-commit`
   - Multiple commits: cherry-pick each in order with `--no-commit`, OR apply the combined diff:
     ```
     gh pr diff <number> | git apply --3way
     ```
     (`--3way` handles minor context differences between the PR base and your branch)
4. Run tests: `python -m pytest desloppify/tests/ -q`
5. If tests pass, commit:
   ```
   <original commit message>

   Cherry-picked from PR #<number> by @<author>
   Co-Authored-By: <author> <<username>@users.noreply.github.com>
   Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
   ```
6. If tests fail: clean up with BOTH `git checkout .` AND `git clean -fd` (checkout doesn't remove new files). Change decision to DEFER with a note about what failed.

### For IMPLEMENT_WITH_CHANGES (PRs):

Same as IMPLEMENT, but after step 3, apply the modifications before committing. Note them in the commit message:
```
<original message> (with adjustments)

Adjustments: <list changes>
Cherry-picked from PR #<number> by @<author>
Co-Authored-By: ...
```

If the changes are too substantial to apply cleanly (more than ~20 lines of edits, or requires rethinking the approach), change decision to DEFER. Comment on the PR asking the contributor to revise.

### Partial cherry-picks (PR bundles multiple changes):

Sometimes a PR contains multiple unrelated changes in one commit and only some are good. In this case:
1. Do NOT cherry-pick the commit. Apply the wanted changes by hand — read the diff, make the edits yourself to the relevant files.
2. In the commit message, note which part of the PR you took: `"Cherry-picked [description of change] from PR #<number>; other changes in that PR handled separately."`
3. Credit the contributor as usual.

### For REJECT_AND_FIX (PRs or issues where the bug is real but the fix is wrong):

1. Do NOT cherry-pick the PR. Write the correct fix yourself from scratch.
2. Read the PR diff and the review assessments to understand what the contributor found.
3. Read the relevant code. Trace the actual bug. Implement the right fix.
4. Run tests: `python -m pytest desloppify/tests/ -q`
5. If tests pass, commit:
   ```
   fix: <description of the actual fix>

   Bug identified by @<author> in PR #<number> / issue #<number>
   Reported-by: <author> <<username>@users.noreply.github.com>
   Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
   ```
6. If tests fail: same as IMPLEMENT — up to 3 attempts, then DEFER.
7. Comment on the PR/issue: thank the contributor for finding the bug, explain what the actual fix was and why it differs from their approach. Close the PR.

### For IMPLEMENT (issues):

1. Read the issue and any `implementation_notes` from Stage 2.
2. Read the relevant code. Understand current behavior before changing anything.
3. Implement the fix/feature. Follow project conventions. Keep it minimal.
4. Run tests: `python -m pytest desloppify/tests/ -q`
5. If tests pass, commit:
   ```
   <commit message>

   Closes #<number> (reported by @<author>)
   Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
   ```
6. If tests fail: attempt to fix (up to 3 attempts / approaches). If you can't get green, clean up (`git checkout . && git clean -fd`) and change decision to DEFER. "Reasonable effort" = three genuine attempts, not an hour of debugging.

### For IMPLEMENT_WITH_CHANGES (issues):

Same as IMPLEMENT, but respect the scope constraints from your conditions.

---

### After executing each item

1. Update the item's Stage 1 JSON file — add a `stage3` section:
   ```json
   {
     "stage3": {
       "decision": "IMPLEMENT | IMPLEMENT_WITH_CHANGES | REJECT | DEFER",
       "reasoning": "why — especially explain if you overrode either stage",
       "commit": "abc1234 or null",
       "changes_applied": ["if IMPLEMENT_WITH_CHANGES"]
     }
   }
   ```

2. Comment on the PR or issue via GitHub:
   - **IMPLEMENT / IMPLEMENT_WITH_CHANGES**: Thank the contributor, note the commit SHA, mention any modifications. Then close:
     - PRs: `gh pr comment <number> --body "..."` then `gh pr close <number>`
     - Issues: `gh issue comment <number> --body "..."` then `gh issue close <number>`
   - **REJECT**: Thank them, explain why clearly and kindly. If duplicate, mention which item was preferred. Close:
     - PRs: `gh pr comment` + `gh pr close`
     - Issues: `gh issue comment` + `gh issue close`
   - **DEFER**: Thank them, explain what's needed (contributor changes, timing, etc.). Do NOT close — leave it open for follow-up.

### After all items

1. Final test run: `python -m pytest desloppify/tests/ -q`
2. If anything broke: each individual cherry-pick passed tests, so the failure is likely an interaction between commits. Check `git log --oneline` for commits that touch overlapping files. Revert the later one: `git revert <sha> --no-edit`. Update that item's GitHub comment to note the revert and reopen the PR/issue.
3. Write `review/results/execution-log.json`:
   ```json
   [
     {"number": 486, "type": "pr", "decision": "IMPLEMENT", "commit": "abc1234", "notes": ""},
     {"number": 490, "type": "issue", "decision": "IMPLEMENT", "commit": "def5678", "notes": ""},
     {"number": 485, "type": "pr", "decision": "REJECT", "commit": null, "notes": "duplicate of #486"},
     {"number": 484, "type": "pr", "decision": "DEFER", "commit": null, "notes": "tests failed — touches scoring path"}
   ]
   ```
4. Print a summary table of all decisions and outcomes.

## Rules

- NEVER push to remote. Local commits only.
- NEVER force-push or touch main.
- Test after EVERY cherry-pick/implementation.
- Clean up failed attempts with `git checkout . && git clean -fd`.
- Skip non-obvious merge conflicts (DEFER, don't force it).
- Be kind in all comments. These are real people.
- Always give credit via Co-Authored-By.
- Close issues explicitly with `gh issue close` — don't rely on `Closes #N` in commit messages (those only work on push).
