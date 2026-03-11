---
name: desloppify
description: >
  Codebase health scanner and technical debt tracker. Use when the user asks
  about code quality, technical debt, dead code, large files, god classes,
  duplicate functions, code smells, naming issues, import cycles, or coupling
  problems. Also use when asked for a health score, what to fix next, or to
  create a cleanup plan. Supports 28 languages.
allowed-tools: Bash(desloppify *)
---

<!-- desloppify-begin -->
<!-- desloppify-skill-version: 5 -->

# Desloppify

## 1. Your Job

Maximise the **strict score** honestly. Your main cycle: **scan → plan → execute → rescan**. Follow the scan output's **INSTRUCTIONS FOR AGENTS** — don't substitute your own analysis.

**Don't be lazy.** Do large refactors and small detailed fixes with equal energy. If it takes touching 20 files, touch 20 files. If it's a one-line change, make it. No task is too big or too small — fix things properly, not minimally.

## 2. The Workflow

Three phases, repeated as a cycle.

### Phase 1: Scan and review — understand the codebase

```bash
desloppify scan --path .       # analyse the codebase
desloppify status              # check scores — are we at target?
```

The scan will tell you if subjective dimensions need review. Follow its instructions. To trigger a review manually:
```bash
desloppify review --prepare    # then follow your runner's review workflow
```

### Phase 2: Plan — decide what to work on

After reviews, triage stages and plan creation appear in the execution queue surfaced by `next`. Complete them in order:
```bash
desloppify next                                        # shows the next execution workflow step
desloppify plan triage --stage observe --report "themes and root causes..."
desloppify plan triage --stage reflect --report "comparison against completed work..."
desloppify plan triage --stage organize --report "summary of priorities..."
desloppify plan triage --complete --strategy "execution plan..."
```

### Automated triage (subagent runners)

For Codex: `desloppify plan triage --run-stages --runner codex`
For Claude: `desloppify plan triage --run-stages --runner claude` — then follow orchestrator instructions per stage

Options: `--only-stages observe,reflect` (subset), `--dry-run` (prompts only), `--stage-timeout-seconds N` (per-stage).

Then shape the queue. **The plan shapes everything `next` gives you** — `next` is the execution queue, not the full backlog. Don't skip this step.

```bash
desloppify plan                          # see the living plan details
desloppify plan queue                    # compact execution queue view
desloppify plan reorder <pat> top        # reorder — what unblocks the most?
desloppify plan cluster create <name>    # group related issues to batch-fix
desloppify plan focus <cluster>          # scope next to one cluster
desloppify plan skip <pat>              # defer — hide from next
```

More plan commands:
```bash
desloppify plan reorder <cluster> top    # move all cluster members at once
desloppify plan reorder <a> <b> top     # mix clusters + findings in one reorder
desloppify plan reorder <pat> before -t X  # position relative to another item/cluster
desloppify plan cluster reorder a,b top # reorder multiple clusters as one block
desloppify plan resolve <pat>           # mark complete
desloppify plan reopen <pat>             # reopen
```

### Phase 3: Execute — grind the queue to completion

Trust the plan and execute. Don't rescan mid-queue — finish the queue first.

**Branch first.** Create a dedicated branch for health work — never commit directly to main:
```bash
git checkout -b desloppify/code-health    # or desloppify/<focus-area>
```

**Set up commit tracking.** If you have a PR, link it for auto-updated descriptions:
```bash
desloppify config set commit_pr 42        # PR number for auto-updates
```

**The loop:**
```
1. desloppify next              ← what to fix next in the execution queue
2. Fix the issue in code
3. Resolve it (next shows you the exact command including required attestation)
4. When you have a logical batch, commit:
   git add <files> && git commit -m "desloppify: fix 3 deferred_import findings"
5. Record the commit:
   desloppify plan commit-log record      # moves findings uncommitted → committed, updates PR
6. Push periodically:
   git push -u origin desloppify/code-health
7. Repeat until the queue is empty
```

Score may temporarily drop after fixes — cascade effects are normal, keep going.
If `next` suggests an auto-fixer, run `desloppify autofix <fixer> --dry-run` to preview, then apply.

If you need to inspect broader open work that is not currently driving execution, use:
```bash
desloppify backlog                         # broader non-execution backlog
```

**When the queue is clear, go back to Phase 1.** New issues will surface, cascades will have resolved, priorities will have shifted. This is the cycle.

### Other useful commands

```bash
desloppify next --count 5                         # top 5 execution items
desloppify next --cluster <name>                  # drill into a cluster
desloppify backlog --count 5                      # top 5 backlog items outside execution
desloppify show <pattern>                         # filter by file/detector/ID
desloppify show --status open                     # all open findings
desloppify plan skip --permanent "<id>" --note "reason" --attest "..." # accept debt
desloppify exclude <path>                         # exclude a directory from scanning
desloppify config show                            # show all config including excludes
desloppify scan --path . --reset-subjective       # reset subjective baseline to 0
```

## 3. Reference

### How scoring works

Overall score = **25% mechanical** + **75% subjective**.

- **Mechanical (25%)**: auto-detected issues — duplication, dead code, smells, unused imports, security. Fixed by changing code and rescanning.
- **Subjective (75%)**: design quality review — naming, error handling, abstractions, clarity. Starts at **0%** until reviewed. The scan will prompt you when a review is needed.
- **Strict score** is the north star: wontfix items count as open. The gap between overall and strict is your wontfix debt.
- **Score types**: overall (lenient), strict (wontfix counts), objective (mechanical only), verified (confirmed fixes only).

### Subjective reviews in detail

- **Local runner (Codex)**: `desloppify review --run-batches --runner codex --parallel --scan-after-import` — automated end-to-end.
- **Local runner (Claude)**: `desloppify review --prepare` → launch parallel subagents → `desloppify review --import merged.json` — see skill doc overlay for details.
- **Cloud/external**: `desloppify review --external-start --external-runner claude` → follow session template → `--external-submit`.
- **Manual path**: `desloppify review --prepare` → review per dimension → `desloppify review --import file.json`.
- Import first, fix after — import creates tracked state entries for correlation.
- Target-matching scores trigger auto-reset to prevent gaming.
- Even moderate scores (60-80) dramatically improve overall health.
- Stale dimensions auto-surface in `next` — just follow the queue.

### Review output format

Return machine-readable JSON for review imports. For `--external-submit`, include `session` from the generated template:

```json
{
  "session": {
    "id": "<session_id_from_template>",
    "token": "<session_token_from_template>"
  },
  "assessments": {
    "<dimension_from_query>": 0
  },
  "findings": [
    {
      "dimension": "<dimension_from_query>",
      "identifier": "short_id",
      "summary": "one-line defect summary",
      "related_files": ["relative/path/to/file.py"],
      "evidence": ["specific code observation"],
      "suggestion": "concrete fix recommendation",
      "confidence": "high|medium|low"
    }
  ]
}
```

**Import rules:**
- `findings` MUST match `query.system_prompt` exactly (including `related_files`, `evidence`, and `suggestion`). Use `"findings": []` when no defects found.
- Import is fail-closed: invalid findings abort unless `--allow-partial` is passed.
- Assessment scores are auto-applied from trusted internal or cloud session imports. Legacy `--attested-external` remains supported.

**Import paths:**
- Robust session flow (recommended): `desloppify review --external-start --external-runner claude` → use generated prompt/template → run printed `--external-submit` command.
- Durable scored import (legacy): `desloppify review --import findings.json --attested-external --attest "I validated this review was completed without awareness of overall score and is unbiased."`
- Findings-only fallback: `desloppify review --import findings.json`

### Review integrity

1. Do not use prior chat context, score history, or target-threshold anchoring.
2. Score from evidence only; when mixed, score lower and explain uncertainty.
3. Assess every requested dimension; never drop one. If evidence is weak, score lower.

### Reviewer agent prompt

Runners that support agent definitions (Cursor, Copilot, Gemini) can create a dedicated reviewer agent. Use this system prompt:

```
You are a code quality reviewer. You will be given a codebase path, a set of
dimensions to score, and what each dimension means. Read the code, score each
dimension 0-100 from evidence only, and return JSON in the required format.
Do not anchor to target thresholds. When evidence is mixed, score lower and
explain uncertainty.
```

See your editor's overlay section below for the agent config format.

### Commit tracking & branch workflow

Work on a dedicated branch named `desloppify/<description>` (e.g., `desloppify/code-health`, `desloppify/fix-smells`). Never push health work directly to main.

```bash
desloppify config set commit_pr 42              # link to your PR
desloppify plan commit-log                      # see uncommitted + committed status
desloppify plan commit-log record               # record HEAD commit, update PR description
desloppify plan commit-log record --note "why"  # with rationale
desloppify plan commit-log record --only "smells::*"  # record specific findings only
desloppify plan commit-log history              # show commit records
desloppify plan commit-log pr                   # preview PR body markdown
desloppify config set commit_tracking_enabled false  # disable guidance
```

After resolving findings as `fixed`, the tool shows uncommitted work, committed history, and a suggested commit message. After committing externally, run `record` to move findings from uncommitted to committed and auto-update the linked PR description.

### Key concepts

- **Tiers**: T1 auto-fix → T2 quick manual → T3 judgment call → T4 major refactor.
- **Auto-clusters**: related findings are auto-grouped in `next`. Drill in with `next --cluster <name>`.
- **Zones**: production/script (scored), test/config/generated/vendor (not scored). Fix with `zone set`.
- **Wontfix cost**: widens the lenient↔strict gap. Challenge past decisions when the gap grows.
- Score can temporarily drop after fixes (cascade effects are normal).

## 4. Fix Tool Issues Upstream

When desloppify itself appears wrong or inconsistent — a bug, a bad detection, a crash, confusing output — **fix it and open a PR**. If you can't confidently fix it, file an issue instead.

### Fix and PR (preferred)

Clone the tool repo to a temp directory, make the fix there, and verify it works against the project you're scanning before pushing.

```bash
git clone https://github.com/peteromallet/desloppify.git /tmp/desloppify-fix
cd /tmp/desloppify-fix
git checkout -b fix/<short-description>
```

Make your changes, then run the test suite and verify the fix against the original project:

```bash
python -m pytest desloppify/tests/ -q
python -m desloppify scan --path <project-root>   # the project you were scanning
```

Once it looks good, push and open a PR:

```bash
git add <files> && git commit -m "fix: <what and why>"
git push -u origin fix/<short-description>
gh pr create --title "fix: <short description>" --body "$(cat <<'EOF'
## Problem
<what went wrong — include the command and output>

## Fix
<what you changed and why>
EOF
)"
```

Clean up after: `rm -rf /tmp/desloppify-fix`

### File an issue (fallback)

If the fix is unclear or the change needs discussion, open an issue at `https://github.com/peteromallet/desloppify/issues` with a minimal repro: command, path, expected output, actual output.

## Prerequisite

`command -v desloppify >/dev/null 2>&1 && echo "desloppify: installed" || echo "NOT INSTALLED — run: pip install --upgrade git+https://github.com/peteromallet/desloppify.git"`

<!-- desloppify-end -->
