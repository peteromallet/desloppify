# Bounty Verification: @optimus-fulcria submission #4003923979

**Scoreboard ID:** S328
**Verdict:** NO
**Date:** 2026-03-06

## Submission Summary

The submission claims that `get_project_root()` resolves to the scan target path, and that `discovery.py:95-113` auto-loads `.py` files from that path's `.desloppify/plugins/` directory via `exec_module` without user consent — constituting poor engineering.

## Code References Examined

- `desloppify/base/discovery/paths.py:13-18` — `get_project_root()` function
- `desloppify/languages/_framework/discovery.py:95-113` — user plugin loading block

## Independent Code Description

**`paths.py:13-18`** — `get_project_root()`:
```python
def get_project_root() -> Path:
    """Return the active project root, checking RuntimeContext first."""
    override = current_runtime_context().project_root
    if override is not None:
        return Path(override).resolve()
    return _DEFAULT_PROJECT_ROOT
```
Where `_DEFAULT_PROJECT_ROOT = Path(os.environ.get("DESLOPPIFY_ROOT", Path.cwd())).resolve()`.

This returns the **project root** — the CWD (or `DESLOPPIFY_ROOT` env var, or runtime context override). It is NOT the scan target path; the scan target is `get_project_root() / "src"` (see `get_default_path()`, `get_src_path()`).

**`discovery.py:95-113`** — user plugin loading:
```python
# Discover user plugins from <active-project-root>/.desloppify/plugins/*.py
try:
    user_plugin_dir = get_project_root() / ".desloppify" / "plugins"
    if user_plugin_dir.is_dir():
        for f in sorted(user_plugin_dir.glob("*.py")):
            spec = importlib.util.spec_from_file_location(...)
            if spec and spec.loader:
                try:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                except _PLUGIN_IMPORT_ERRORS as ex:
                    logger.debug(...)
```

During `load_all()`, every `.py` file in `<project_root>/.desloppify/plugins/` is executed in-process via `exec_module`. No warning, no opt-in, no user consent. Errors are caught silently at DEBUG level.

## Claim Analysis

### Claim 1: `get_project_root()` resolves to the scan target path

**Status: INACCURATE**

`get_project_root()` returns the project root (CWD or env var), not the scan target. The scan target is `project_root/src`. The project root IS the root of the project being analyzed, so plugins are indeed loaded from within the analyzed project — but the framing is imprecise.

### Claim 2: Plugin files are executed without user consent

**Status: ACCURATE**

The code does execute arbitrary `.py` files from `<project_root>/.desloppify/plugins/` via `exec_module()` with no warning, prompt, or opt-in. Execution is in the same Python process with full privileges. This is technically accurate.

### Claim 3: This constitutes poor engineering

**Status: NOT CONFIRMED**

The loading block is explicitly commented as an intentional plugin system. This pattern is standard in developer tools:
- **pytest**: auto-executes `conftest.py` at project root and subdirs
- **ESLint**: loads `.eslintrc.js` from project root
- **pre-commit**: loads hook scripts from project repository
- **black / ruff / mypy**: load config from `pyproject.toml`

Python provides no meaningful process sandboxing regardless of approach. The primary risk (analyzing an untrusted repo with malicious `.desloppify/plugins/*.py`) is a use-case concern — not a code quality defect. Users who run desloppify against foreign repos assume standard dev tool risks.

There is no scoring or gaming impact.

## Verdict: NO

The code refs are accurate and the mechanism is correctly described. However:

1. The "scan target path" framing is imprecise — `get_project_root()` is the project root, not the scan target
2. The plugin loading is **intentional** (explicitly commented, follows standard dev tool patterns)
3. No poor engineering — deliberate extension point, not an oversight
4. No scoring impact

## Scores

| Dimension | Score |
|-----------|-------|
| Signal (significance) | 3/10 |
| Originality | 4/10 |
| Core Impact | 0/10 |
| Overall | 2/10 |
