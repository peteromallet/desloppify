# Desloppify

Codebase health scanner. Detects cruft (dead code, duplication, complexity, smells), tracks findings across scans, auto-fixes mechanical issues, reports a weighted score. TypeScript/React and Python out of the box — [add your own language](#adding-a-language) with one directory.

## Install

```bash
pip install git+https://github.com/peteromallet/desloppify.git
```

## Use with AI Agents

Copy-paste into any AI coding agent (Cursor, Windsurf, Copilot, etc.):

```
Install desloppify: pip install git+https://github.com/peteromallet/desloppify.git

Scan my codebase: desloppify scan --path src/. Then: desloppify status for the score,
desloppify next for the top finding to fix. After fixing: desloppify resolve fixed "<id>".
For auto-fixable stuff: desloppify fix unused-imports --dry-run. Rescan after each batch.
Work tier by tier: T1 (auto-fix) → T2 (quick) → T3 (judgment) → T4 (refactor).
desloppify show <detector> to dig in, desloppify plan for a prioritized plan.
Use --lang python for Python projects.

As you work, note any false positives, missing detectors, or improvements and suggest
them to me so I can report them at https://github.com/peteromallet/desloppify/issues.
```

**Claude Code** — copy-paste this instead to also install the skill (auto-discovery + workflow guidance):

```
pip install git+https://github.com/peteromallet/desloppify.git
mkdir -p .claude/skills/desloppify && curl -sL https://raw.githubusercontent.com/peteromallet/desloppify/main/SKILL.md -o .claude/skills/desloppify/SKILL.md
```

## Quick Start

```bash
desloppify scan --path src/              # detect findings, update state
desloppify status                         # health score + tier breakdown
desloppify next --count 5                 # next 5 highest-priority items
desloppify fix unused-imports --dry-run   # preview auto-fix
desloppify resolve fixed "unused::..."    # mark finding resolved
desloppify scan --path src/              # rescan after fixes
```

## Commands

| Command | Description |
|---------|-------------|
| `scan` | Run all detectors, update state |
| `status` | Score + per-tier progress |
| `show <pattern>` | Findings by file, directory, detector, or ID |
| `next [--tier N]` | Highest-priority open finding |
| `resolve <status> <patterns>` | Mark fixed / wontfix / false_positive |
| `fix <fixer> [--dry-run]` | Auto-fix mechanical issues |
| `detect <name>` | Run a single detector raw |
| `plan` | Prioritized markdown plan |
| `tree` | Annotated codebase tree |
| `viz` | Interactive HTML treemap |

## Detectors

**TypeScript/React**: logs, unused, exports, deprecated, large, complexity, gods, single-use, props, passthrough, concerns, deps, dupes, smells, coupling, patterns, naming, cycles, orphaned, react

**Python**: unused, large, complexity, gods, passthrough, smells, dupes, deps, cycles, orphaned, single-use, naming

## Tiers & Scoring

| Tier | Fix type | Examples |
|------|----------|----------|
| T1 | Auto-fixable | Unused imports, debug logs |
| T2 | Quick manual | Unused vars, dead exports |
| T3 | Needs judgment | Near-dupes, single-use abstractions |
| T4 | Major refactor | God components, mixed concerns |

Score is weighted (T4 = 4x T1). Strict score excludes wontfix.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DESLOPPIFY_ROOT` | cwd | Project root |
| `DESLOPPIFY_SRC` | `src` | Source directory (TS alias resolution) |
| `--lang <name>` | auto-detected | Language selection (each has own state) |

## Adding a Language

Create `desloppify/lang/<name>/` with `__init__.py`, `commands.py`, `extractors.py`, `detectors/`, `fixers/`. Validated at registration. Zero shared code changes. See `lang/python/` for example.

## Architecture

```
detectors/              ← Generic algorithms (zero language knowledge)
lang/base.py            ← Shared finding helpers
lang/<name>/            ← Language config + phase runners + extractors + detectors + fixers
```

Import direction: `lang/` → `detectors/`. Never the reverse.
