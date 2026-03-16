# Ruby Language Plugin for Desloppify

Static analysis for Ruby codebases via RuboCop, plus structural, coupling, and
duplication analysis powered by tree-sitter — no additional tools required for
most checks.

## Supported extensions

`.rb`

## Requirements

- [`rubocop`](https://rubocop.org/) on `PATH` — required for the **RuboCop** phase

Install:

```bash
gem install rubocop
```

## Project detection

Activates on projects containing any of: `Gemfile`, `Rakefile`, `.ruby-version`,
or any `*.gemspec` file.

## Usage

```bash
# Scan for issues
desloppify scan --path <project>

# Full scan with all phases
desloppify scan --path <project> --profile full

# Auto-correct RuboCop offenses
desloppify fix --path <project>
```

## What gets analysed

| Phase | What it finds |
|-------|--------------|
| RuboCop | Style violations, layout issues, lint warnings |
| Structural analysis | God classes, large files, complexity hotspots |
| Coupling + cycles + orphaned | Import cycles, tight coupling, unreachable files |
| Duplicates | Copy-pasted methods across the codebase |
| Signature | Methods with overly broad or inconsistent signatures |
| Code smells | Empty rescue blocks, unreachable code, and more |
| Security | Common security anti-patterns |
| Subjective review | LLM-powered design and responsibility review |

## Autofix

RuboCop's `--auto-correct` is wired to `desloppify fix`. Only offenses that
RuboCop marks as safe to auto-correct will be changed.

## Exclusions

The following are excluded from analysis by default:

- `vendor/`
- `.bundle/`
- `coverage/`
- `tmp/`
- `log/`
- `bin/`
