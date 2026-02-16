# Adding a New Language

This repo uses one standard path: scaffold, then fill in language logic.

## 1) Scaffold (Canonical Start)

Run:

```bash
desloppify dev scaffold-lang <name> \
  --extension .ext \
  --marker <root-marker-file> \
  --default-src <src-dir>
```

Example:

```bash
desloppify dev scaffold-lang go --extension .go --marker go.mod --default-src .
```

What this does:

- creates `desloppify/lang/<name>/` with the full standardized file layout
- creates `tests/__init__.py` and `tests/test_init.py`
- updates `pyproject.toml` (`testpaths` + setuptools `exclude`) unless `--no-wire-pyproject`

## 2) Required Layout (Enforced)

Language registration fails if any of these are missing:

```text
desloppify/lang/<name>/
├── __init__.py
├── commands.py
├── extractors.py
├── phases.py
├── move.py
├── review.py
├── test_coverage.py
├── detectors/__init__.py
├── fixers/__init__.py
├── tests/__init__.py
└── tests/test_*.py (at least one)
```

## 3) LangConfig Contract (Validated at Runtime)

`get_lang("<name>")` validates:

- `name` matches the registered language name
- `extensions` non-empty
- `build_dep_graph`, `file_finder`, `extract_functions` callable
- `phases` non-empty and each phase has non-empty label + callable `run`
- `detect_commands` non-empty dict, callable values, snake_case lowercase keys
- `fixers` dict of `FixerConfig`
- `zone_rules` non-empty

## 4) Detector/Fixer Strategy

Use generic detectors when normalized data is enough:

- `large`, `complexity`, `gods`, `dupes`, `single_use`, `cycles`, `orphaned`, `naming`
- shared phases: `phase_security`, `phase_test_coverage`, `phase_subjective_review`

Use language-specific detectors when syntax/framework semantics are required:

- import graph parsing/resolution
- syntax-aware smell/security rules
- framework-specific conventions

Rule of thumb:

1. If generic input shape works, reuse generic detector.
2. If correctness depends on parser semantics, implement language-specific detector.

Fixer invariant:

- fixer `removed` IDs must match finding `name` exactly (`detector::file::name` identity)

## 5) Testing Standard

Add colocated tests under `desloppify/lang/<name>/tests/` following existing Python/TypeScript patterns.

Minimum:

1. config/init contract tests
2. command registry tests
3. extractor/dep-graph tests
4. move helper tests
5. any language-specific detector tests

Then run:

```bash
pytest -q
```

## 6) Definition of Done

1. `desloppify --lang <name> scan --path <src>` works
2. `desloppify --lang <name> detect <detector>` works
3. `desloppify --lang <name> move ...` works for language files
4. language tests pass
5. `pyproject.toml` includes language test path + package exclude
