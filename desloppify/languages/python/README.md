# Python Language Plugin for Desloppify

Provides in-depth static analysis for Python codebases — no external linter required for most checks.

## Supported extensions

`.py`

## Requirements

- Python 3.11+
- [`ruff`](https://docs.astral.sh/ruff/) on `PATH` — required for the **Unused** phase (unused imports, variables)
- [`bandit`](https://bandit.readthedocs.io/) on `PATH` — optional; enables the **Security** phase

Install optional tools:

```bash
pip install ruff bandit
```

## Project detection

Activates on projects containing any of: `pyproject.toml`, `setup.py`, `setup.cfg`.

## Usage

```bash
# Scan for issues
desloppify scan --path <project>

# Full scan with all phases
desloppify scan --path <project> --profile full
```

Autofix is **not** supported for Python — all findings are reported only.

## What gets analysed

| Phase | What it finds |
|-------|--------------|
| Unused (ruff) | Unused imports and variables |
| Structural analysis | God classes, large files, complexity hotspots |
| Responsibility cohesion | Modules/classes that do too many unrelated things |
| Coupling + cycles + orphaned | Import cycles, tight coupling, unreachable modules |
| Uncalled functions | Dead code — functions never called within the project |
| Test coverage | Functions/classes with no corresponding tests |
| Signature | Overly broad signatures (`*args`, `**kwargs` misuse) |
| Code smells | Swallowed exceptions, mutable defaults, bare excepts, and more |
| Mutable state | Mutable class-level defaults and module-level shared state |
| Security | Common security issues via bandit (requires bandit) |
| Private imports | Cross-module access to private (`_`-prefixed) internals |
| Layer violations | Higher-level modules importing from lower-level domains |
| Dict key flow | Inconsistent dictionary schemas across call sites |
| Unused enums | Enum members defined but never referenced |

## Exclusions

The following are excluded from analysis by default:

- `__pycache__`
- `.venv`
- `node_modules`
- `.eggs`
- `*.egg-info`

---

## Python Plugin Maintainer Notes

### AST smell detector layout

`desloppify.languages.python.detectors.smells_ast` is split by role:

- `_dispatch.py`: registry-driven orchestration for AST smell scanning
- `_types.py`: typed match/count models and deterministic merge helpers
- `_node_detectors.py`: function/class node-level detectors
- `_source_detectors.py`: source/import-resolution detectors
- `_tree_safety_detectors.py`: security/safety oriented tree detectors
- `_tree_quality_detectors.py`: maintainability/quality tree detectors
- `_tree_context_callbacks.py`: callback-parameter context detectors
- `_tree_context_paths.py`: path-separator context detectors

Public package exports are intentionally narrow in
`smells_ast/__init__.py`.

### Adding a new AST smell detector

1. Decide category:
- node-level: function/class-specific logic
- tree-level: whole-module AST logic
- source-level: import resolution or source-text + AST combo

2. Implement detector in the appropriate module.
- Keep detector focused to one smell ID.
- Prefer returning normalized entries (`file`, `line`, `content`) via
  dispatch adapters.

3. Register detector in `_dispatch.py`.
- Add a `NODE_DETECTORS` or `TREE_DETECTORS` spec entry.
- Ensure smell ID is unique.

4. Wire smell metadata in `/Users/peteromalley/Documents/desloppify/desloppify/languages/python/detectors/smells.py`.
- Add ID, label, severity to `SMELL_CHECKS`.

5. Add tests.
- Unit test for detector behavior.
- Direct test for dispatch/registry behavior when relevant.

6. Run checks.
- `ruff check`
- `pytest -q`
