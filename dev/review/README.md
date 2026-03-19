# Review Pipeline

Three stages for processing open PRs and issues. Each item gets its own file. Stages 1 and 2 write separate files so they can't corrupt each other. Stage 3 reads both and adjudicates.

```
Stage 1: Assess              Stage 2: Challenge             Stage 3: Adjudicate + Execute
(parallel sub-agents)        (parallel sub-agents)          (sequential, one at a time)

 PR #486 ─→ agent            ACCEPT? ─→ challenger          reads pr-486.json + pr-486.stage2.json
 Issue #490 ─→ agent         REJECT? ─→ advocate            reads _cross-item.json for duplicates/ordering
 PR #484 ─→ agent            ...                            ─→ forms own opinion from the diff/issue
 ...                               ↓                        ─→ weighs stage1 vs stage2
       ↓                     orchestrator writes             ─→ decides + executes
 each writes                 _cross-item.json               ─→ test ─→ commit ─→ comment ─→ close
 pr-486.json                 (duplicates, ordering)
```

## Key design decisions

- **Separate files per stage.** Stage 1 writes `pr-486.json`. Stage 2 writes `pr-486.stage2.json`. Neither can corrupt the other. Stage 3 reads both.
- **Symmetric scrutiny.** Accepts get a devil's advocate (default NO). Rejects get an angel's advocate (default YES). Every item gets challenged from the opposite direction.
- **Cross-item metadata.** Duplicates, ordering, and interactions are recorded in `_cross-item.json` by the Stage 2 orchestrator (after reading sub-agent outputs) — the only agent that sees all items at once.
- **Stage 3 verifies, not rubber-stamps.** Duplicate groupings from `_cross-item.json` are suggestions — Stage 3 checks them. Missing `.stage2.json` files block execution (partial Stage 2 runs won't slip through).
- **No comments until Stage 3.** Contributors see one message: the final decision.
- **No bias toward action.** The goal is making the codebase better, not clearing a queue.

## Folder structure

```
review/
  README.md                        ← you are here
  schema.json                      ← JSON schema for all result files
  validate.py                      ← run after each stage to catch errors
  prompts/
    1-review-orchestrator.md       ← spawns parallel sub-agents for Stage 1
    1-review-agent.md              ← one agent per item: honest assessment
    2-challenge-orchestrator.md    ← spawns parallel sub-agents for Stage 2
    2-devils-advocate.md           ← challenges items Stage 1 accepted (default: NO)
    2-angels-advocate.md           ← advocates for items Stage 1 rejected (default: YES)
    3-decide-and-execute.md        ← reads both stages, adjudicates, implements, comments
  results/                         ← created at runtime, gitignored
    pr-486.json                    ← Stage 1 assessment (Stage 3 appends stage3 section)
    pr-486.stage2.json             ← Stage 2 challenge/advocacy (separate file, never modified)
    issue-490.json
    issue-490.stage2.json
    _cross-item.json               ← duplicate groups, ordering, interactions
    execution-log.json             ← Stage 3 record of what happened
```

## How to run

Prerequisites:
- On the release branch, not main (`git branch --show-current`)
- Clean working tree (`git status`)
- Tests green (`python -m pytest desloppify/tests/ -q`)
- `gh` authenticated (`gh auth status`)

Each stage is a separate conversation. Pass the orchestrator/adjudicate prompt to a `general-purpose` agent:

```
Stage 1:  "Read review/prompts/1-review-orchestrator.md and execute it."
Stage 2:  "Read review/prompts/2-challenge-orchestrator.md and execute it."
Stage 3:  "Read review/prompts/3-decide-and-execute.md and execute it."
```

Stages are idempotent — they skip items that already have result files. To re-run an item, delete its result file(s).

After Stage 3, review locally before pushing:
```bash
git log --oneline main..HEAD
python -m pytest desloppify/tests/ -q
```
