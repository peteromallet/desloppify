You are orchestrating Stage 2 (challenge) of a review pipeline for the desloppify project.

Stage 1 has assessed every open PR and issue. Each item has a file at `review/results/{type}-{number}.json` with a `stage1` section. Your job: make sure every verdict gets challenged from the opposite direction.

## Steps

1. List all files in `review/results/` matching `pr-*.json` and `issue-*.json` (exclude `.stage2.json` files).

2. Read each file. Separate into:
   - **Stage 1 ACCEPT or ACCEPT_WITH_CONDITIONS** → gets a **challenger** (devil's advocate, default NO)
   - **Stage 1 REJECT** → gets an **advocate** (angel's advocate, default YES)
   - **Stage 1 ALREADY_FIXED or NOT_ACTIONABLE** → skip, no sub-agent needed. Write a minimal `.stage2.json` confirming the verdict so Stage 3's completeness check passes.

3. Read the sub-agent prompts:
   - `review/prompts/2-devils-advocate.md` — for challengers
   - `review/prompts/2-angels-advocate.md` — for advocates

4. Read `review/schema.json` for the output format.

5. Check for existing `.stage2.json` files. Skip items that already have one (prior run). To re-run, delete the `.stage2.json` file first.

6. Launch ALL sub-agents in parallel using the **Agent tool** with `subagent_type: "general-purpose"`:
   - For ACCEPT/ACCEPT_WITH_CONDITIONS items: use the challenger prompt
   - For REJECT items: use the advocate prompt
   - Fill `{TYPE}`, `{NUMBER}`, and `{STAGE_1_ASSESSMENT}` (the full stage1 object)
   - Each agent writes to `review/results/{type}-{number}.stage2.json`

7. After all sub-agents complete, verify `.stage2.json` files exist for every item.

## Cross-item analysis (you do this yourself, after sub-agents finish)

Sub-agents each see one item. You see all of them. Now handle the things they can't:

8. **Read all `.stage2.json` files.** Sub-agents may have discovered new overlaps, interactions, or duplicate signals not flagged by Stage 1. Note any new findings before proceeding.

9. **Duplicate resolution.** Read all Stage 1 files — check `potential_duplicates` flags — AND check Stage 2 sub-agent summaries for newly discovered overlaps. For each cluster of items that might address the same thing:
   - Read the diffs of all items in the cluster: `gh pr diff <number>` / `gh issue view <number>`
   - Decide: are they actually duplicates? If yes, which one is best? (Criteria: correctness > completeness > code quality)

10. **Interaction check.** Identify items that touch the same files. If two accepted items both modify the same file, note whether they can coexist or conflict.

11. **Ordering.** If item A depends on item B (e.g., A's diff assumes B's changes), note the ordering constraint.

12. Write `review/results/_cross-item.json`:
    ```json
    {
      "duplicate_groups": [
        {
          "items": ["pr-486", "pr-481", "pr-472"],
          "preferred": "pr-486",
          "reasoning": "most complete fix, handles edge cases others miss"
        }
      ],
      "ordering": [
        { "item": "pr-486", "must_come_after": "pr-484", "reason": "486's diff assumes 484's refactor" }
      ],
      "interactions": [
        { "items": ["pr-483", "pr-475"], "concern": "both modify engine/plan.py — may conflict" }
      ]
    }
    ```
    If there are no duplicates, ordering constraints, or interactions, write `{"duplicate_groups": [], "ordering": [], "interactions": []}`.

13. Run validation: `python review/validate.py --stage 2`
    Fix any errors before proceeding to Stage 3.

14. Do NOT post comments — Stage 3 handles all GitHub communication.

## Note on parallel execution

Same rate-limiting concern as Stage 1 — all sub-agents hit `gh pr diff` / `gh issue view` simultaneously. Batch into groups of 10 if needed.
