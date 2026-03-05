# Architecture Guardrails

This repository enforces architecture regressions in CI through two gates:

1. `import-linter` contracts (`.github/importlinter.ini`)
2. Scoped SCC cycle checker (`.github/scripts/check_import_cycles.py`)

## Boundary Rule

`desloppify.base` must not import:

- `desloppify.app`
- `desloppify.engine`
- `desloppify.intelligence`
- `desloppify.languages`

Current legacy exceptions are explicitly listed in the `ignore_imports` section of
`[importlinter:contract:base_no_upward_imports]`.

## Cycle Rule

CI checks for new import cycles intersecting:

- `desloppify.app.commands.review`
- `desloppify.engine._plan`
- `desloppify.engine._state`
- `desloppify.engine._scoring`

Allowed SCCs are tracked in:

- `.github/architecture/cycle_allowlist.txt`

Any new SCC in these paths fails `make arch`.

## Local Run

```bash
make arch
```
