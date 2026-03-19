You are orchestrating Stage 1 (assessment) of a review pipeline for the desloppify project.

## Prerequisites

- You must be on the release branch (not main). Check: `git branch --show-current`
- Working tree must be clean: `git status`
- Tests must pass: `python -m pytest desloppify/tests/ -q`

## Steps

1. Get the list of open PRs and issues:
   ```
   gh pr list --state open --json number,title,author,headRefName,body
   gh issue list --state open --json number,title,author,body,labels
   ```

2. Create `review/results/` directory if it doesn't exist.

3. Check for existing result files. If `review/results/{type}-{number}.json` already exists for an item, **skip it** — it was assessed in a prior run. To re-assess, delete the file first.

4. Read `review/prompts/1-review-agent.md` — this is the template for each sub-agent.

5. Read `review/schema.json` — this defines the output format and field definitions.

6. For each open PR and issue that doesn't already have a result file, launch a sub-agent using the **Agent tool** with `subagent_type: "general-purpose"`. Launch them all in parallel (multiple Agent tool calls in one message). For each sub-agent:
   - Fill `{TYPE}` with "pr" or "issue"
   - Fill `{NUMBER}` with the item number
   - Fill `{FULL_LIST}` with the complete list from step 1 (titles and descriptions only — for spotting potential duplicates)
   - Include the full text of the sub-agent prompt with these substitutions

7. After all sub-agents complete, verify that a `review/results/{type}-{number}.json` file exists for each item. If any are missing, check the agent output and retry.

8. Run validation: `python review/validate.py --stage 1`
   Fix any errors before proceeding to Stage 2.

9. Do NOT post comments on PRs/issues — Stage 3 handles all GitHub communication.

## Note on parallel execution

All sub-agents hit the GitHub API simultaneously. If you have many items (20+), consider batching into groups of 10 to avoid rate limiting. Watch for agents that return empty/partial diffs — that's a sign of throttling.

## Batching strategy

- **PRs**: one sub-agent per PR (each needs to read a full diff + surrounding code — heavy context).
- **Issues**: can batch multiple issues per sub-agent (no diffs, lighter context). 3-6 issues per agent is fine if they're in different areas of the codebase. Don't batch issues that might be duplicates of each other — they need independent assessment.
- **Already-fixed items**: if you know recent commits on the branch already address an issue, you can skip the sub-agent and write the result file yourself with verdict `ALREADY_FIXED`.
