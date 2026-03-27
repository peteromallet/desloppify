# Desloppify -- Agent Instructions

Open Paws fork of [peteromallet/desloppify](https://github.com/peteromallet/desloppify). Multi-language codebase health scanner (29 languages) that combines mechanical detection with LLM-based subjective review. This fork adds advocacy-specific detectors for speciesist language, activist security antipatterns, and persona-based browser QA.

## Quick Start

```bash
# Requires Python 3.11+
pip install -e ".[full]"          # editable install with all extras
desloppify scan --path .          # run all mechanical detectors
desloppify status                 # view scores
desloppify next                   # get top-priority fix item
```

## Architecture

```
desloppify/                  # Python package root
  cli.py                     # CLI entry point (desloppify.cli:main)
  state.py                   # Persistent scan state (JSON)
  state_scoring.py           # Score computation
  app/
    commands/                # All CLI commands (scan, review, plan, next, persona_qa, ...)
    cli_support/             # Argument parsing
    output/                  # Terminal formatting
    skill_docs.py            # Agent skill file generation
  base/
    config/                  # Runtime config, project detection
    discovery/               # File discovery, zone mapping
    registry/                # Detector metadata catalog
    scoring_constants.py     # Dimension weights, tier thresholds
    subjective_dimensions.py # Subjective scoring framework
  engine/
    detectors/               # All mechanical detectors (see below)
    _scoring/                # Score aggregation
    _plan/                   # Plan/triage state machine
    _work_queue/             # Priority queue for fixes
    policy/                  # Scoring policy rules
  intelligence/
    review/                  # Subjective review orchestration
    narrative/               # Natural language summaries
  languages/                 # Per-language plugins (32 dirs)
    _framework/              # Shared language framework
    python/, typescript/, ...# Language-specific detectors + configs
  data/global/               # Shared markdown templates
  tests/                     # Pytest suite (mirrors source layout)

docs/                        # Agent overlay docs (CLAUDE.md, CURSOR.md, etc.)
dev/                         # Release and review scripts
website/                     # Landing page (static HTML/CSS/JS)
assets/                      # Images for README
.github/workflows/           # CI: ci.yml, integration.yml, python-publish.yml
```

## Key Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Package metadata, dependencies, pytest/ruff/mypy config |
| `Makefile` | CI targets: `make lint`, `make typecheck`, `make tests`, `make ci` |
| `desloppify/cli.py` | CLI entry point |
| `desloppify/state.py` | Persistent scan state (JSON serialization) |
| `desloppify/base/scoring_constants.py` | Dimension weights and tier thresholds |
| `desloppify/engine/detectors/` | All mechanical detectors |
| `desloppify/engine/detectors/advocacy_language.py` | Speciesist language detector (65 rules) |
| `desloppify/engine/detectors/advocacy_security.py` | Activist security antipattern detector |
| `desloppify/engine/detectors/advocacy_rules/` | YAML rule definitions |
| `desloppify/app/commands/persona_qa/` | Persona-based browser QA command |
| `desloppify/app/commands/scan/` | Scan command and reporting |
| `desloppify/app/commands/review/` | Subjective review orchestration |
| `desloppify/app/commands/plan/` | Plan/triage command |
| `docs/CLAUDE.md` | Claude subagent overlay (review + triage workflow) |
| `.pre-commit-config.yaml` | Pre-commit: no-animal-violence hook |
| `.semgrep.yml` | Semgrep config pointing to Open Paws rules |

## Development

```bash
# Install dev dependencies
make install-ci-tools         # minimal: pytest, mypy, ruff, import-linter
make install-full-tools       # full: adds tree-sitter, bandit, Pillow, PyYAML

# Lint
make lint                     # ruff (fatal errors only)
ruff check .                  # full ruff

# Type check
make typecheck                # mypy (subset of files configured in pyproject.toml)

# Tests
make tests                    # pytest (core tests)
make tests-full               # pytest with full extras installed

# Architecture contracts
make arch                     # import-linter layer boundary checks

# Full CI pipeline
make ci-fast                  # lint + typecheck + arch + contracts + tests
make ci                       # ci-fast + full tests + package smoke test

# Package smoke test
make package-smoke            # build wheel, install in venv, verify CLI works
```

Detectors are pure functions returning `(entries, metadata)`. They are registered in `base/registry/catalog_entries.py` (metadata) and wired into language-specific phase lists. No base class inheritance.

Overall score = 25% mechanical + 75% subjective. Subjective scores start at 0% until a review is run.

## Open Paws Additions

Beyond the upstream fork, this repo adds:

### Advocacy Language Detector (`engine/detectors/advocacy_language.py`)
65 YAML-defined rules detecting speciesist idioms, metaphors, insults, process language, and terminology in code, comments, and docs across all 29 languages plus `.md`/`.txt`/`.rst`. Context suppression for technical terms (POSIX `kill()`, git `master`), proper nouns, and quotations. Each finding includes a suggested replacement. Rules sourced from [project-compassionate-code](https://github.com/Open-Paws/project-compassionate-code).

### Advocacy Security Detector (`engine/detectors/advocacy_security.py`)
Heuristic detector for activist protection antipatterns against three adversary classes: state surveillance, industry infiltration, and AI model bias. Detects identity leakage, sensitive data to external APIs without zero-retention headers, investigation materials in public paths, unencrypted sensitive data writes, IP logging, and sensitive data in browser storage.

### Persona-Based Browser QA (`app/commands/persona_qa/`)
`desloppify persona-qa` command for browser-based testing with configurable persona profiles (YAML). Findings integrate into the standard work queue alongside mechanical and subjective issues.

### Three New Scoring Dimensions
Advocacy language, advocacy security, and persona QA -- each weight 1.0, integrated into the mechanical score.

### Windows Platform Fixes
`input()` blocking fix, `msvcrt.locking()` timeout fix, dataclass JSON serialization fix.

### Pre-commit and Semgrep Integration
`.pre-commit-config.yaml` hooks into Open Paws `no-animal-violence-pre-commit`. `.semgrep.yml` points to `semgrep-rules-no-animal-violence`.

### Upstream Tracking
Fork tracks `peteromallet/desloppify` as `upstream` remote. Fork-specific code lives in new files. Upstream merges should be clean: `git fetch upstream && git merge upstream/main`.
