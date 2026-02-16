# Desloppify - agent tools to make your codebase 🤌

Detects subjective and mechanical code-base issues - everything from poor quality abstractions and inconsistent naming, to file complexity and duplication. Once identified, it tracks issues, and helps you work with your agents to relentlessly solve them. Currently supports Typescript & Python.

Every scan generates a scorecard badge you can add to your README — here's the one for this repo - the strict score includes the ones you've ignored that haven't been solved:

<img src="scorecard.png" width="100%">

## For your agent's consideration...

Copy-paste into any AI coding agent (Cursor, Codex, Copilot, etc.):

```
Install or update desloppify, then scan this codebase for code quality issues (dead code,
duplication, complexity, smells). It tracks findings and reports a health score.

pip install --upgrade git+https://github.com/peteromallet/desloppify.git
desloppify scan --path .
desloppify status
desloppify next

--path is the directory to scan (use "." for the whole project, or "src/" etc).
Language is auto-detected. To override: desloppify --lang python scan --path .
(note: --lang goes BEFORE the subcommand)

Fix what it finds, then "desloppify resolve fixed <id>" and rescan. For false positives:
"desloppify resolve wontfix <id> --note 'reason'" (note is required — don't skip work).
Keep going until all issues are resolved. If you notice anything wrong or confusing about
desloppify itself, tell me and ask if I want you to log an issue. If you need to understand
how desloppify works or debug an issue: git clone https://github.com/peteromallet/desloppify.git /tmp/desloppify

If you're Claude Code, also run:
mkdir -p .claude/skills/desloppify && { curl -fsSL https://raw.githubusercontent.com/peteromallet/desloppify/main/SKILL.md; printf '\n\n'; curl -fsSL https://raw.githubusercontent.com/peteromallet/desloppify/main/skills/CLAUDE.md; } > .claude/skills/desloppify/SKILL.md

If you're Codex, also run:
mkdir -p .agents/skills/desloppify && { curl -fsSL https://raw.githubusercontent.com/peteromallet/desloppify/main/SKILL.md; printf '\n\n'; curl -fsSL https://raw.githubusercontent.com/peteromallet/desloppify/main/skills/CODEX.md; } > .agents/skills/desloppify/SKILL.md

If your Codex build reads $CODEX_HOME/skills, also run:
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills/desloppify" && cp .agents/skills/desloppify/SKILL.md "${CODEX_HOME:-$HOME/.codex}/skills/desloppify/SKILL.md"
```

### Agent-specific skill install (core + overlay)

Run exactly one of the following.

#### Claude Code

```bash
mkdir -p .claude/skills/desloppify && {
  curl -fsSL https://raw.githubusercontent.com/peteromallet/desloppify/main/SKILL.md
  printf '\n\n'
  curl -fsSL https://raw.githubusercontent.com/peteromallet/desloppify/main/skills/CLAUDE.md
} > .claude/skills/desloppify/SKILL.md
```

#### Codex (documented path: `.agents/skills`)

```bash
mkdir -p .agents/skills/desloppify && {
  curl -fsSL https://raw.githubusercontent.com/peteromallet/desloppify/main/SKILL.md
  printf '\n\n'
  curl -fsSL https://raw.githubusercontent.com/peteromallet/desloppify/main/skills/CODEX.md
} > .agents/skills/desloppify/SKILL.md
```

Optional compatibility copy for Codex builds that still read `$CODEX_HOME/skills`:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills/desloppify" \
  && cp .agents/skills/desloppify/SKILL.md "${CODEX_HOME:-$HOME/.codex}/skills/desloppify/SKILL.md"
```

### Deploy isolated reviewers

#### Claude Code (first-class subagents)

```bash
mkdir -p .claude/agents && cat > .claude/agents/desloppify-reviewer.md <<'EOF'
---
name: desloppify-reviewer
description: Blind subjective reviewer for desloppify packets.
---
You are an isolated reviewer for subjective desloppify scans.

Only use .desloppify/review_packet_blind.json and referenced source files.
Do not use prior chat context, score history, or narrative summaries.
Return JSON only:
{"assessments":{"naming_quality":0,"error_consistency":0,"abstraction_fit":0,"logic_clarity":0,"ai_generated_debt":0},"findings":[]}
EOF
```

Use `/agents` in Claude Code and delegate subjective review tasks to `desloppify-reviewer`.

#### Codex (equivalent isolation pattern)

Codex currently uses isolated tasks/worktrees rather than named subagents.

```bash
REVIEW_DIR="../$(basename "$PWD")-review-$(date +%Y%m%d%H%M%S)"
git worktree add --detach "$REVIEW_DIR"
mkdir -p "$REVIEW_DIR/.desloppify"
cp .desloppify/review_packet_blind.json "$REVIEW_DIR/.desloppify/review_packet_blind.json"
```

Then run a new Codex thread (or cloud task) from `"$REVIEW_DIR"` for the subjective review.

### Isolated subjective reviews (recommended)

When you want a clean review that is not biased by score history:

1. Prepare review data:

```bash
desloppify review --prepare --path .
```

2. Create a blind packet:

```bash
jq 'del(.narrative, .objective_score, .objective_strict, .dimension_scores, .stats, .scan_count, .last_scan)' \
  .desloppify/query.json > .desloppify/review_packet_blind.json
```

3. Run the review in an isolated agent context:

- Claude Code: use `/agents` with `desloppify-reviewer`, or a skill with `context: fork`.
- Codex app/CLI: run a new thread on a dedicated worktree.
- Codex web: delegate a separate cloud task (each task has its own environment).

### If desloppify looks inconsistent

When an agent sees likely tool bugs, confusing behavior, or documentation mismatch:

1. Open an issue in `peteromallet/desloppify` with repro steps and expected vs actual behavior.
2. If you have a concrete fix, open a PR linked to that issue.
3. If unclear whether it is usage error vs tool bug, open the issue first, then follow with a PR if needed.

## From Vibe Coding to Vibe Engineering

Vibe coding gets things built fast. But the codebase accumulates debt - dead code, duplication, tangled dependencies - and eventually progress slows, bugs get harder to fix, and new features become a pain.

Thankfully, both subjective and objective engineering best practices exist - and, with a little help from agents, they can be tracked. Desloppify is for people who want to keep the speed of agent-driven development while pushing themselves to a standard that rivals traditional engineering teams.

It handles the mechanical layer automatically: scan, detect, auto-fix what it can. For the rest - architectural fitness, convention drift, things that need taste - it gives your agent a prioritized shortlist. You decide what to fix and what to mindfully ignore. The goal is to capture all of this in a single score that combines both objective and subjective metrics - a real measure of the health of your codebase.

If you'd like to join a community of vibe engineers who want to build beautiful things, [come hang out](https://discord.gg/aZdzbZrHaY).

<img src="desloppify/engineering.png" width="100%">

---

<details>
<summary><strong>Stuff you probably won't need to know</strong></summary>

#### Commands

| Command | Description |
|---------|-------------|
| `scan` | Run all detectors, update state |
| `status` | Score + per-tier progress |
| `show <pattern>` | Findings by file, directory, detector, or ID |
| `next [--tier N]` | Highest-priority open finding |
| `resolve <status> <patterns>` | Mark fixed / wontfix / false_positive |
| `ignore <pattern>` | Suppress findings matching a pattern |
| `fix <fixer> [--dry-run]` | Auto-fix mechanical issues |
| `move <src> <dst>` | Move file/directory, update all imports |
| `detect <name>` | Run a single detector raw |
| `plan` | Prioritized markdown plan |
| `tree` | Annotated codebase tree |
| `viz` | Interactive HTML treemap |
| `dev scaffold-lang` | Generate a standardized language plugin scaffold |

#### Detectors

**TypeScript/React**: logs, unused, exports, deprecated, large, complexity, gods, single_use, props, passthrough, concerns, deps, dupes, smells, coupling, patterns, naming, cycles, orphaned, react

**Python**: unused, large, complexity, gods, props, smells, dupes, deps, cycles, orphaned, single_use, naming

#### Tiers & scoring

| Tier | Fix type | Examples |
|------|----------|----------|
| T1 | Auto-fixable | Unused imports, debug logs |
| T2 | Quick manual | Unused vars, dead exports |
| T3 | Needs judgment | Near-dupes, single_use abstractions |
| T4 | Major refactor | God components, mixed concerns |

Score is weighted (T4 = 4x T1). Strict score excludes wontfix.

#### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DESLOPPIFY_ROOT` | cwd | Project root |
| `DESLOPPIFY_SRC` | `src` | Source directory (TS alias resolution) |
| `--lang <name>` | auto-detected | Language selection (each has own state) |
| `--exclude <dirs>` | none | Directories to skip (e.g. `--exclude migrations tests`) |
| `--no-badge` | false | Skip scorecard image generation |
| `--badge-path <path>` | `scorecard.png` | Output path for scorecard image |
| `DESLOPPIFY_NO_BADGE` | — | Set to `true` to disable badge via env |
| `DESLOPPIFY_BADGE_PATH` | `scorecard.png` | Badge output path via env |

#### Adding a language

Use the scaffold workflow documented in `ADDING_NEW_LANGUAGE.md`:

```bash
desloppify dev scaffold-lang <name> --extension .ext --marker <root-marker>
```

Detect command keys are standardized to snake_case. CLI compatibility aliases
like `single-use` and legacy `passthrough` are still accepted.
Standard plugin shape: `__init__.py`, `commands.py`, `extractors.py`, `phases.py`,
`move.py`, `review.py`, `test_coverage.py`, plus `detectors/`, `fixers/`, and `tests/`.
Validated at registration. Zero shared code changes.

#### Architecture

```
detectors/              ← Generic algorithms (zero language knowledge)
lang/base.py            ← Shared finding helpers
lang/<name>/            ← Language config + phases + extractors + detectors + fixers
```

Import direction: `lang/` → `detectors/`. Never the reverse.

</details>
