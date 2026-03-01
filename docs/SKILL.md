<!-- desloppify-begin -->
<!-- desloppify-skill-version: 2 -->
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

# Desloppify

## 1. Your Job

Improve code quality by maximising the **strict score** honestly.

**The main thing you do is run `desloppify next`** — it tells you exactly what to fix and how. Fix it, resolve it, run `next` again. Keep going.

Follow the scan output's **INSTRUCTIONS FOR AGENTS** — don't substitute your own analysis.

## 2. The Workflow

Two loops. The **outer loop** rescans periodically to measure progress.
The **inner loop** is where you spend most of your time: fixing issues one by one.

### Outer loop — scan and check

```bash
desloppify scan --path .       # analyse the codebase
desloppify status              # check scores — are we at target?
```
If not at target, work the inner loop. Rescan periodically — especially after clearing a cluster or batch of related fixes. Issues cascade-resolve and new ones may surface.

### Inner loop — fix issues

Repeat until the queue is clear:

```
1. desloppify next              ← tells you exactly what to fix next
2. Fix the issue in code
3. Resolve it (next shows you the exact command including required attestation)
```

Score may temporarily drop after fixes — cascade effects are normal, keep going.
If `next` suggests an auto-fixer, run `desloppify fix <fixer> --dry-run` to preview, then apply.

**To be strategic**, use `plan` to shape what `next` gives you:
```bash
desloppify plan                        # see the full ordered queue
desloppify plan move <pat> top         # reorder — what unblocks the most?
desloppify plan cluster create <name>  # group related issues to batch-fix
desloppify plan focus <cluster>        # scope next to one cluster
desloppify plan skip <pat>             # skip / hide from next
desloppify plan done <pat>             # mark complete
desloppify plan reopen <pat>           # reopen
```

### Subjective reviews

The scan will prompt you when a subjective review is needed — just follow its instructions.
If you need to trigger one manually:
```bash
desloppify review --run-batches --runner codex --parallel --scan-after-import
```

### Other useful commands

```bash
desloppify next --count 5                         # top 5 priorities
desloppify next --cluster <name>                  # drill into a cluster
desloppify show <pattern>                         # filter by file/detector/ID
desloppify show --status open                     # all open findings
desloppify plan skip --permanent "<id>" --note "reason" # accept debt (lowers strict score)
desloppify scan --path . --reset-subjective       # reset subjective baseline to 0
```

## 3. Reference

### How scoring works

Overall score = **40% mechanical** + **60% subjective**.

- **Mechanical (40%)**: auto-detected issues — duplication, dead code, smells, unused imports, security. Fixed by changing code and rescanning.
- **Subjective (60%)**: design quality review — naming, error handling, abstractions, clarity. Starts at **0%** until reviewed. The scan will prompt you when a review is needed.
- **Strict score** is the north star: wontfix items count as open. The gap between overall and strict is your wontfix debt.
- **Score types**: overall (lenient), strict (wontfix counts), objective (mechanical only), verified (confirmed fixes only).

### Subjective reviews in detail

- **Preferred**: `desloppify review --run-batches --runner codex --parallel --scan-after-import` — does everything in one command.
- **Manual path**: `desloppify review --prepare` → review per dimension → `desloppify review --import file.json`.
- Import first, fix after — import creates tracked state entries for correlation.
- Integrity: reviewers score from evidence only. Scores hitting exact targets trigger auto-reset.
- Even moderate scores (60-80) dramatically improve overall health.
- Stale dimensions auto-surface in `next` — just follow the queue.

### Key concepts

- **Tiers**: T1 auto-fix → T2 quick manual → T3 judgment call → T4 major refactor.
- **Auto-clusters**: related findings are auto-grouped in `next`. Drill in with `next --cluster <name>`.
- **Zones**: production/script (scored), test/config/generated/vendor (not scored). Fix with `zone set`.
- **Wontfix cost**: widens the lenient↔strict gap. Challenge past decisions when the gap grows.
- Score can temporarily drop after fixes (cascade effects are normal).

## 4. Escalate Tool Issues Upstream

When desloppify itself appears wrong or inconsistent:

1. Capture a minimal repro (`command`, `path`, `expected`, `actual`).
2. Open a GitHub issue in `peteromallet/desloppify`.
3. If you can fix it safely, open a PR linked to that issue.
4. If unsure whether it is tool bug vs user workflow, issue first, PR second.

## Prerequisite

`command -v desloppify >/dev/null 2>&1 && echo "desloppify: installed" || echo "NOT INSTALLED — run: pip install --upgrade git+https://github.com/peteromallet/desloppify.git"`

<!-- desloppify-end -->
