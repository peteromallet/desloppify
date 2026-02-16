# Adding a New Language

Use one path only: scaffold, then implement.

## 1) Canonical Start (Do This)

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

This generates the standardized plugin layout and (unless `--no-wire-pyproject`) updates `pyproject.toml` for test discovery/package excludes.

Do not manually copy Python/TypeScript as your primary bootstrap strategy.

## 2) Required Plugin Layout (Enforced)

`desloppify/lang/<name>/` must contain:

- `__init__.py` (required for module discovery)
- `commands.py`
- `extractors.py`
- `phases.py`
- `move.py`
- `review.py`
- `test_coverage.py`
- `detectors/__init__.py`
- `fixers/__init__.py`
- `tests/__init__.py`
- at least one `tests/test_*.py`

Registration/validation fails if this contract is incomplete.

## 3) LangConfig Runtime Contract (Enforced)

`get_lang("<name>")` validates:

- `cfg` is `LangConfig` and `cfg.name == "<name>"`
- non-empty `extensions`
- callable `build_dep_graph`, `file_finder`, `extract_functions`
- non-empty `phases`, each with non-empty label and callable `run`
- non-empty `detect_commands` with lowercase snake_case keys and callable values
- `fixers` is a dict of `FixerConfig` values (can be empty)
- non-empty `zone_rules`

## 4) Detector/Fixer Rules of Thumb

Prefer shared/generic first:

- shared phases in `desloppify/lang/base.py`:
  - `phase_security`
  - `phase_test_coverage`
  - `phase_subjective_review`
  - `phase_dupes`
  - `phase_private_imports` (if applicable)
- generic detectors in `desloppify/detectors/` when normalized inputs are enough.

Write language-specific detectors when correctness depends on parser/framework semantics (imports, AST-aware smells, framework conventions).

Fixers:

- fixers are language-local (`desloppify/lang/<name>/fixers/`)
- there is no global generic fixer layer
- emitted `removed` identities must match finding IDs (`detector::file::name`) for correct state resolution

## 5) Tests (Minimum)

Add tests in `desloppify/lang/<name>/tests/` and run:

```bash
pytest -q \
  tests/test_lang_init.py \
  tests/test_lang_standardization.py \
  desloppify/lang/<name>/tests
```

Also run full suite before merge:

```bash
pytest -q
```

## 6) Done Checklist

1. `desloppify --lang <name> scan --path <src>` works.
2. `desloppify --lang <name> detect <detector>` works.
3. `desloppify --lang <name> move ...` works for language files.
4. Contract tests pass (`test_lang_init` + `test_lang_standardization` + language tests).
5. `pyproject.toml` includes language test path/package exclude (or intentionally skipped via `--no-wire-pyproject`).
