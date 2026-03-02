# Desloppify - an agent harness to make your codebase 🤌

[![PyPI version](https://img.shields.io/pypi/v/desloppify)](https://pypi.org/project/desloppify/) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

Desloppify gives your AI coding agent the tools to identify, understand, and systematically improve codebase quality. It combines mechanical detection (dead code, duplication, complexity) with subjective LLM review (naming, abstractions, module boundaries), then works through a prioritized fix loop. State persists across scans so it chips away over multiple sessions, and the scoring is designed to resist gaming.

<img src="assets/explained.png" width="100%">

The score gives your agent a north-star, and the tooling helps it plan, execute, and resolve issues until it hits your target — with a lot of tricks to keep it on track. A score above 98 should correlate with a codebase a seasoned engineer would call beautiful.

That score generates a scorecard badge for your GitHub profile or README:

<img src="assets/scorecard.png" width="100%">

Currently supports 28 languages — full plugin depth for TypeScript, Python, C#, Dart, GDScript, and Go; generic linter + tree-sitter support for Rust, Ruby, Java, Kotlin, and 17 more.

## For your agent's consideration...

Paste this prompt into your agent:

```
I want you to improve the quality of this codebase. To do this, install and run desloppify.
Run ALL of the following (requires Python 3.11+):

pip install --upgrade "desloppify[full]"
desloppify update-skill claude    # installs the full workflow guide — pick yours: claude, cursor, codex, copilot, windsurf, gemini
desloppify scan --path .
desloppify next

--path is the directory to scan (use "." for the whole project, or "src/" etc).

Your goal is to get the strict score as high as possible. The scoring resists gaming — the
only way to improve it is to actually make the code better.

THE LOOP: run `next`. It tells you what to fix, which file, and the resolve command to run
when done. Fix it, resolve it, run `next` again. Over and over. This is your main job.

Don't be lazy. Large refactors and small detailed fixes — do both with equal energy. No task
is too big or too small. Fix things properly, not minimally.

Use `plan` to reorder priorities or cluster related issues. Rescan periodically. The scan
output includes agent instructions — follow them, don't substitute your own analysis.
```

## From Vibe Coding to Vibe Engineering

Vibe coding gets things built fast. But the codebases it produces tend to rot in ways that are hard to see and harder to fix — not just the mechanical stuff like dead imports, but the structural kind. Abstractions that made sense at first stop making sense. Naming drifts. Error handling is done three different ways. The codebase works, but working in it gets worse over time.

LLMs are actually good at spotting this now, if you ask them the right questions. That's the core bet here — that an agent with the right framework can hold a codebase to a real standard, the kind that used to require a senior engineer paying close attention over months.

So we're trying to define what "good" looks like as a score that's actually worth optimizing. Not a lint score you game to 100 by suppressing warnings. Something where improving the number means the codebase genuinely got better. That's hard, and we're not done, but the anti-gaming stuff matters to us a lot — it's the difference between a useful signal and a vanity metric.

The hope is that anyone can use this to build something a seasoned engineer would look at and respect. That's the bar we're aiming for.

If you'd like to join a community of vibe engineers who want to build beautiful things, [come hang out](https://discord.gg/aZdzbZrHaY).

<img src="assets/engineering.png" width="100%">

---

<details>
<summary><strong>Stuff you probably won't need to know</strong></summary>

#### Commands

| Command | Description |
|---------|-------------|
| `scan [--reset-subjective]` | Run all detectors, update state (optional: reset subjective baseline to 0 first) |
| `status` | Score + per-tier progress |
| `show <pattern>` | Findings by file, directory, detector, or ID |
| `next [--tier N] [--explain]` | Highest-priority open finding (--explain: with score context) |
| `resolve <status> <patterns>` | Mark open / fixed / wontfix / false_positive |
| `fix <fixer> [--dry-run]` | Auto-fix mechanical issues |
| `review --prepare` | Generate subjective review packet (`query.json`) |
| `review --run-batches --runner codex --parallel` | Run blind subjective batch assessments, merge/import, optionally `--scan-after-import` |
| `review --import <file> [--allow-partial]` | Import subjective review findings (fails closed on invalid findings by default) |
| `review --external-start --external-runner claude` | Start Claude cloud blind-review session (creates session/token/template) |
| `review --external-submit --session-id <id> --import <file>` | Submit Claude session output (from generated template); CLI injects canonical provenance |
| `next [--tier N] [--cluster <name>]` | Next priority item (respects plan, shows clusters) |
| `zone` | Show/set/clear zone classifications |
| `config` | Show/set/unset project configuration |
| `move <src> <dst>` | Move file/directory, update all imports |
| `detect <name>` | Run a single detector raw |
| `plan` | Prioritized markdown plan |
| `tree` | Annotated codebase tree |
| `viz` | Interactive HTML treemap |
| `dev scaffold-lang` | Generate a standardized language plugin scaffold |

#### Subjective Import Guardrails

- Findings must match `query.json` / packet `system_prompt` schema exactly:
  `dimension`, `identifier`, `summary`, `related_files`, `evidence`, `suggestion`, `confidence`.
- Score/feedback consistency is enforced:
  - scores below `100.0` require explicit same-dimension feedback (finding suggestion or `dimension_notes` evidence)
  - scores below `85.0` require at least one same-dimension finding
- `desloppify review --import` is fail-closed: if any finding is invalid/skipped, the import aborts and state is not saved.
- Use `--allow-partial` only when you explicitly want to accept skipped findings.

#### Review Batch Runtime Logs

- `review --run-batches` always writes a live run log while executing.
- Add `--retrospective` to include historical issue status/notes in the review packet so reviewers can distinguish root causes from symptom-level repeats.
- Default path: `.desloppify/subagents/runs/<run-stamp>/run.log`
- Per-batch live logs stream to `.desloppify/subagents/runs/<run-stamp>/logs/batch-<n>.log` while each batch is running.
- Override path with `--run-log-file <path>`.
- Launch output now includes a runtime upper-bound estimate and prints the active log path so agents can monitor long runs without being blind.

#### Detectors

**TypeScript/React**: logs, unused, exports, deprecated, large, complexity, gods, single_use, props, passthrough, concerns, deps, dupes, smells, coupling, patterns, naming, cycles, orphaned, react

**Python**: unused, large, complexity, gods, props, smells, dupes, deps, cycles, orphaned, single_use, naming

**C#/.NET**: deps, cycles, orphaned, dupes, large, complexity

#### Tiers & scoring

| Tier | Fix type | Examples |
|------|----------|----------|
| T1 | Auto-fixable | Unused imports, debug logs |
| T2 | Quick manual | Unused vars, dead exports |
| T3 | Needs judgment | Near-dupes, single_use abstractions |
| T4 | Major refactor | God components, mixed concerns |

Score is weighted (T4 = 4x T1). Strict score penalizes both open and wontfix.

#### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DESLOPPIFY_ROOT` | cwd | Project root |
| `DESLOPPIFY_SRC` | `src` | Source directory (TS alias resolution) |
| `--lang <name>` | auto-detected | Language selection (each has own state) |
| `--exclude <pattern>` | none | Path patterns to skip (repeatable: `--exclude migrations --exclude tests`) |
| `--no-badge` | false | Skip scorecard image generation |
| `--badge-path <path>` | `scorecard.png` | Output path for scorecard image |
| `DESLOPPIFY_NO_BADGE` | — | Set to `true` to disable badge via env |
| `DESLOPPIFY_BADGE_PATH` | `scorecard.png` | Badge output path via env |

Project config values (stored in `.desloppify/config.json`) are managed via:
- `desloppify config show`
- `desloppify config set target_strict_score 95` (default: `95`, valid range: `0-100`)
- `desloppify config set badge_path scorecard.png` (or nested path like `assets/health.png`)

#### Adding or augmenting a language

Use the scaffold workflow documented in `desloppify/languages/README.md`:

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
engine/detectors/            ← Generic algorithms (zero language knowledge)
hook_registry.py             ← Detector-safe access to optional language hooks
languages/_framework/runtime.py    ← LangRun (per-run mutable scan state)
languages/_framework/base/         ← Shared framework contracts + phase helpers
languages/_framework/generic.py    ← generic_lang() factory for tool-based plugins
languages/_framework/treesitter/   ← Tree-sitter integration (optional)
languages/<name>/            ← Language config + phases + extractors + detectors + fixers
```

Import direction: `languages/` → `engine/detectors/`. Never the reverse.
`LangConfig` stays static; runtime state lives on `LangRun`.

#### Command-Layer Boundaries

Command entry modules are intentionally thin orchestrators:

- `desloppify/app/commands/review/cmd.py` delegates to
  `desloppify/app/commands/review/prepare.py`, `desloppify/app/commands/review/batches.py`, `desloppify/app/commands/review/import_cmd.py`, and `desloppify/app/commands/review/runtime.py`
- `desloppify/app/commands/scan/scan_reporting_dimensions.py` delegates to
  `desloppify/app/commands/scan/scan_reporting_presentation.py` and `desloppify/app/commands/scan/scan_reporting_subjective.py`
- `desloppify/app/cli_support/parser.py` delegates subcommand construction to `desloppify/app/cli_support/parser_groups.py`

Public CLI behavior should be preserved when refactoring these orchestrators.

#### Allowed Dynamic Import Zones

Dynamic/optional loading is allowed only in explicit extension points:

- `desloppify/languages/__init__.py` for plugin discovery and registration
- `desloppify/hook_registry.py` for detector-safe optional hooks

Outside these zones, use static imports.

#### State Ownership

- `desloppify/state.py` and `desloppify/engine/_state/` own persisted schema and merge rules
- `desloppify/languages/_framework/runtime.py` (`LangRun`) owns per-run mutable execution state
- command modules may read/write state through state APIs, but should not define ad-hoc persisted fields

#### Optional Dependencies (Coverage)

- `pip install "desloppify[python-security]"` installs `bandit` for Python-specific security checks.
- `pip install "desloppify[treesitter]"` installs tree-sitter language-pack for deeper AST analysis in generic plugins.
- `pip install "desloppify[full]"` installs both.

If optional tools are missing, scan warns at start and end, and marks score confidence as reduced for affected detectors.

</details>
