# Desloppify - an agent harness to make your codebase 🤌

[![GitHub repo](https://img.shields.io/badge/github-cpjet64%2Fdesloppify-black)](https://github.com/cpjet64/desloppify) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

Desloppify gives your AI coding agent the tools to identify, understand, and systematically improve codebase quality. It combines mechanical detection (dead code, duplication, complexity) with subjective LLM review (naming, abstractions, module boundaries), then works through a prioritized fix loop. State persists across scans so it chips away over multiple sessions, and the scoring is designed to resist gaming.

<img src="assets/explained.png" width="100%">

The score gives your agent a north-star, and the tooling helps it plan, execute, and resolve issues until it hits your target — with a lot of tricks to keep it on track. A score above 98 should correlate with a codebase a seasoned engineer would call beautiful.

That score generates a scorecard badge for your GitHub profile or README:

<img src="assets/scorecard.png" width="100%">

Currently supports 29 languages — full plugin depth for TypeScript, Python, C#, C++, Dart, GDScript, Go, and Rust; generic linter + tree-sitter support for Ruby, Java, Kotlin, and 18 more. For C++ projects, `compile_commands.json` is the primary analysis path and `Makefile` repositories fall back to best-effort local include scanning.

## For your agent's consideration...

Use the prompt that matches your agent.

### Codex prompt

```text
I want you to improve the quality of this codebase. To do this, install and run desloppify.
Run ALL of the following (requires Python 3.11+):

pip install --upgrade "git+https://github.com/cpjet64/desloppify.git#egg=desloppify[full]"
desloppify update-skill codex

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

### Claude prompt

```text
I want you to improve the quality of this codebase. To do this, install and run desloppify.
Run ALL of the following (requires Python 3.11+):

pip install --upgrade "git+https://github.com/cpjet64/desloppify.git#egg=desloppify[full]"
desloppify update-skill claude

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

### Short bootstrap prompt

```text
I want you to improve the quality of this codebase. Install and run desloppify first.

pip install --upgrade "git+https://github.com/cpjet64/desloppify.git#egg=desloppify[full]"

If you are Codex, run:
desloppify update-skill codex

If you are Claude, run:
desloppify update-skill claude

Add .desloppify/ to .gitignore if it is not already ignored.
Before scanning, look for obvious exclude candidates such as vendor, build output, generated
code, and worktrees; exclude obvious ones with `desloppify exclude <path>`, but ask me before
excluding anything questionable.

Then run:
desloppify scan --path .
desloppify next

After that, stay in the `next` loop: fix the current item, resolve it, run `desloppify next`
again, and keep going. Use `desloppify backlog` only when you need wider context, and use
`plan` / `plan queue` to reorder or cluster work when needed. The goal is to raise the strict
score by actually improving the code, not by gaming the tool.
```

### Continuation prompt

```text
Continue the interrupted desloppify run from the current repo state. Do not restart from
scratch unless the current state is missing or unusable.

First, inspect the existing setup:
- check whether desloppify is already installed
- check whether .desloppify/ exists and keep it
- check whether a prior scan already populated backlog/plan state
- check whether there is already a current `next` item in progress
- check whether obvious exclude candidates still need to be added

If the skill is not installed yet, install from my fork and update the matching skill:

pip install --upgrade "git+https://github.com/cpjet64/desloppify.git#egg=desloppify[full]"

If you are Codex, run:
desloppify update-skill codex

If you are Claude, run:
desloppify update-skill claude

Then continue from the current state:
- if a scan has not been run yet, run `desloppify scan --path .`
- if scan state already exists, do not wipe it; continue with `desloppify next`
- if a task was partially completed, inspect the related files, finish it properly, and then run
  the resolve command the plan specifies
- keep looping on `desloppify next`

Use `desloppify backlog` only when you need broader context, and use `plan` / `plan queue`
only when reprioritization is actually needed. The goal is to resume momentum without losing
the living plan or redoing work unnecessarily.
```

## From Vibe Coding to Vibe Engineering

Vibe coding gets things built fast. But the codebases it produces tend to rot in ways that are hard to see and harder to fix — not just the mechanical stuff like dead imports, but the structural kind. Abstractions that made sense at first stop making sense. Naming drifts. Error handling is done three different ways. The codebase works, but working in it gets worse over time.

LLMs are actually good at spotting this now, if you ask them the right questions. That's the core bet here — that an agent with the right framework can hold a codebase to a real standard, the kind that used to require a senior engineer paying close attention over months.

So we're trying to define what "good" looks like as a score that's actually worth optimizing. Not a lint score you game to 100 by suppressing warnings. Something where improving the number means the codebase genuinely got better. That's hard, and we're not done, but the anti-gaming stuff matters to us a lot — it's the difference between a useful signal and a vanity metric.

The hope is that anyone can use this to build something a seasoned engineer would look at and respect. That's the bar we're aiming for.

If you'd like to join a community of vibe engineers who want to build beautiful things, [come hang out](https://discord.gg/aZdzbZrHaY).

<img src="assets/engineering.png" width="100%">

---

Issues, improvements, and PRs are hugely appreciated — [github.com/cpjet64/desloppify](https://github.com/cpjet64/desloppify).

MIT License
