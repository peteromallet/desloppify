# Desloppify - an agent harness to make your codebase 🤌

[![PyPI version](https://img.shields.io/pypi/v/desloppify)](https://pypi.org/project/desloppify/) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

Desloppify gives your AI coding agent the tools to identify, understand, and systematically improve codebase quality. It combines mechanical detection (dead code, duplication, complexity) with subjective LLM review (naming, abstractions, module boundaries), then works through a prioritized fix loop. State persists across scans so it chips away over multiple sessions, and the scoring is designed to resist gaming.

## What it is / What it isn't

**desloppify IS:**
- A **codebase health scanner** — finds structural debt, dead code, coupling problems, and design issues across 32 languages
- A **scoring system** — gives you an honest health score (25% mechanical detectors, 75% AI design review) that resists gaming
- A **prioritized action queue** — `desloppify next` always gives you the single most important thing to fix next
- An **agent harness** — designed to be driven by AI coding agents (Claude, Codex, Cursor, etc.) that do the actual fixing guided by the queue
- A **continuous improvement loop** — scan → score → plan → execute → rescan, tracked across sessions and PRs

**desloppify IS NOT:**
- An auto-formatter (use Prettier, Black, or gofmt for that)
- A linter (it wraps your existing linters and adds structural analysis on top)
- A tool that auto-fixes everything — mechanical auto-fix covers only the safest patterns (unused imports, style violations via existing tools). The vast majority of findings require a human or AI agent to implement
- A one-time audit tool — it's designed to run continuously as a feedback loop
- A replacement for code review — it finds structural and design debt, not logic bugs

**The framing to nail:** *desloppify tells you and your AI agent exactly what slop exists, where it is, and what to fix next. The fixing is done by you or your agent — guided by the queue.*

---

## Supported Languages

**Full plugins** — language-specific detectors, richer scoring, deeper analysis:

| Language | Extensions | External tool |
|----------|-----------|---------------|
| Python | `.py` | `ruff` (required), `bandit` (optional) |
| TypeScript | `.ts`, `.tsx` | `node`, `npx` |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` | `node`, `npx` |
| Rust | `.rs` | `cargo`, `clippy` |
| Go | `.go` | `golangci-lint` |
| C# | `.cs` | optional: Roslyn JSON |
| C/C++ | `.c`, `.cpp`, `.h`, `.hpp` | optional: `clang-tidy`, `cppcheck` |
| Dart | `.dart` | — |
| GDScript | `.gd` | — |

**Generic plugins (23+)** — structural analysis, coupling, duplication, orphaned code, tree-sitter AST, and any linter you have installed:

Ruby, Java, Kotlin, Swift, PHP, Scala, Elixir, Haskell, Bash, Lua, Perl, Clojure, Zig, Nim, PowerShell, R, Erlang, OCaml, F#, Julia, SCSS, Quarto, and more.

Both tiers support the full agent-driven workflow. Full plugins have language-specific smell detectors and deeper scoring; generic plugins do structural/coupling/duplication/orphaned analysis and wrap any language linter you have installed.

---

## Quick start

```bash
# Install
pip install "desloppify[full]"

# Scan your project (produces a health score + list of issues)
cd /your/project
desloppify scan

# Get your next action item (the single most important thing to fix)
desloppify next
```

Before scanning, exclude directories that shouldn't be analysed (vendor folders, build output, generated code):

```bash
desloppify exclude vendor/
desloppify exclude build/
```

Add `.desloppify/` to your `.gitignore` — it contains local state that shouldn't be committed.

---

<img src="assets/explained.png" width="100%">

The score gives your agent a north-star, and the tooling helps it plan, execute, and resolve issues until it hits your target — with a lot of tricks to keep it on track. A score above 98 should correlate with a codebase a seasoned engineer would call beautiful.

That score generates a scorecard badge for your GitHub profile or README:

<img src="assets/scorecard.png" width="100%">

## For your agent's consideration...

Paste this prompt into your agent:

```
I want you to improve the quality of this codebase. To do this, install and run desloppify.
Run ALL of the following (requires Python 3.11+):

pip install --upgrade "desloppify[full]"
desloppify update-skill claude    # installs the full workflow guide — pick yours: claude, cursor, codex, copilot, droid, windsurf, gemini

Add .desloppify/ to your .gitignore — it contains local state that shouldn't be committed.

Before scanning, check for directories that should be excluded (vendor, build output,
generated code, worktrees, etc.) and exclude obvious ones with `desloppify exclude <path>`.
Share any questionable candidates with me before excluding.

desloppify scan --path .
desloppify next

--path is the directory to scan (use "." for the whole project, or "src/" etc).

Your goal is to get the strict score as high as possible. The scoring resists gaming — the
only way to improve it is to actually make the code better.

THE LOOP: run `next`. It is the execution queue from the living plan, not the whole backlog.
It tells you what to fix now, which file, and the resolve command to run when done.
Fix it, resolve it, run `next` again. Over and over. This is your main job.

Use `desloppify backlog` only when you need to inspect broader open work that is not currently
driving execution.

Don't be lazy. Large refactors and small detailed fixes — do both with equal energy. No task
is too big or too small. Fix things properly, not minimally.

Use `plan` / `plan queue` to reorder priorities or cluster related issues. Rescan periodically.
The scan output includes agent instructions — follow them, don't substitute your own analysis.
```

## How it works

```
scan ──→ score ──→ review ──→ triage ──→ execute ──→ rescan
  │         │         │          │          │           │
  │     dimensions    │     prioritize    fix it     verify
  │     scored      LLM reviews  & cluster  & resolve  improvements
  │                 subjective   the queue
  │                 quality
  detectors find
  mechanical issues
  (dead code, smells,
  test gaps, etc.)
```

**Scan** runs mechanical detectors across your codebase — dead code, duplication, complexity, test coverage gaps, naming issues, and more. Each issue is scored by dimension (File health, Code quality, Test health, etc.).

**Review** uses an LLM to assess subjective quality dimensions — naming, abstractions, error handling patterns, module boundaries. These score alongside the mechanical dimensions.

**Triage** is where prioritization happens. The agent (or you) observes the findings, reflects on patterns, organizes issues into clusters, and enriches them with implementation detail. This produces an ordered execution queue — only items explicitly queued appear in `next`. Before triage, all mechanical issues are visible in the queue sorted by impact, which can be noisy.

**Execute** is the fix loop: `next` → fix → `resolve` → `next`. Items come from the triaged queue. Autofix handles what it can; the rest needs manual or agent work.

**Rescan** verifies improvements, catches cascading effects, and feeds the next cycle.

State persists in `.desloppify/` so progress carries across sessions. The scoring resists gaming — wontfix items widen the gap between lenient and strict scores, and re-reviewing dimensions can lower scores if the reviewer finds new issues.

## Key concepts

- **Overall score** — your headline number; ignores issues you've accepted as known debt
- **Strict score** — your north star; counts everything including accepted debt (harder to game)
- **Triage** — the process of reviewing raw findings and promoting them into a prioritized action queue
- **Subjective review** — AI analysis of architecture and design quality; accounts for 75% of your score

## From Vibe Coding to Vibe Engineering

Vibe coding gets things built fast. But the codebases it produces tend to rot in ways that are hard to see and harder to fix — not just the mechanical stuff like dead imports, but the structural kind. Abstractions that made sense at first stop making sense. Naming drifts. Error handling is done three different ways. The codebase works, but working in it gets worse over time.

LLMs are actually good at spotting this now, if you ask them the right questions. That's the core bet here — that an agent with the right framework can hold a codebase to a real standard, the kind that used to require a senior engineer paying close attention over months.

So we're trying to define what "good" looks like as a score that's actually worth optimizing. Not a lint score you game to 100 by suppressing warnings. Something where improving the number means the codebase genuinely got better. That's hard, and we're not done, but the anti-gaming stuff matters to us a lot — it's the difference between a useful signal and a vanity metric.

The hope is that anyone can use this to build something a seasoned engineer would look at and respect. That's the bar we're aiming for.

If you'd like to join a community of vibe engineers who want to build beautiful things, [come hang out](https://discord.gg/aZdzbZrHaY).

<img src="assets/engineering.png" width="100%">

---

Issues, improvements, and PRs are hugely appreciated — [github.com/peteromallet/desloppify](https://github.com/peteromallet/desloppify).

MIT License
