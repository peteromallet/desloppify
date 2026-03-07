# Bounty Verification: S195 @AlexChen31337

**Submission:** STATE_DIR, STATE_FILE, and PLAN_FILE are baked in at import time, silently breaking the RuntimeContext.project_root override

## Code Trace (at commit 6eb2065)

### 1. The intended dynamic mechanism

`runtime_state.py` provides `RuntimeContext.project_root` and `runtime_scope()` for overriding the project root at runtime. `paths.py:get_project_root()` correctly consults `current_runtime_context()` on every call:

```python
# paths.py:13-16
def get_project_root() -> Path:
    override = current_runtime_context().project_root
    if override is not None:
        return Path(override).resolve()
    return _DEFAULT_PROJECT_ROOT
```

`config.py` follows this correctly — `_default_config_file()` is a **function** that calls `get_project_root()` each time:

```python
# base/config.py:25-27
def _default_config_file() -> Path:
    return get_project_root() / ".desloppify" / "config.json"
```

### 2. The frozen constants (the bug)

**schema.py:312-313** — evaluated once at import time:
```python
STATE_DIR = get_project_root() / ".desloppify"
STATE_FILE = STATE_DIR / "state.json"
```

**persistence.py:24** — derived from already-frozen STATE_DIR:
```python
PLAN_FILE = STATE_DIR / "plan.json"
```

**paths.py:21-23** — also frozen at import:
```python
PROJECT_ROOT = get_project_root()
DEFAULT_PATH = PROJECT_ROOT / "src"
SRC_PATH = PROJECT_ROOT / os.environ.get("DESLOPPIFY_SRC", "src")
```

### 3. Consequences confirmed

- `load_state()` and `save_state()` in `engine/_state/persistence.py` default to `STATE_FILE` (line 53, 179) — the frozen path.
- `load_plan()` and `save_plan()` default to `PLAN_FILE` — also frozen.
- `conftest.py:14-19` uses `runtime_scope(RuntimeContext(project_root=tmp_path))` expecting persistence to redirect, but STATE_FILE/PLAN_FILE are already frozen.
- `test_queue_order_guard.py:86,180` must monkeypatch `PLAN_FILE` directly as a workaround, confirming the bug is known to test authors.

### 4. No duplicates found

No prior submission identifies this specific import-time freezing bug in STATE_DIR/STATE_FILE/PLAN_FILE and the mismatch with the runtime_scope mechanism.

## Verdict

| Question | Answer | Reasoning |
|----------|--------|-----------|
| **Is this poor engineering?** | YES | Module-level constants silently defeat the project's own RuntimeContext override mechanism |
| **Is this at least somewhat significant?** | YES | Affects all default-path state/plan operations, causes test isolation issues, and running from a different directory silently persists state in the wrong location |

**Final verdict:** YES

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 7/10 |
| Originality | 7/10 |
| Core Impact | 6/10 |
| Overall | 7/10 |

## Why Desloppify Missed This

- **What should catch:** A rule detecting module-level calls to dynamic-resolution functions whose results are stored as constants
- **Why not caught:** Static analysis doesn't track the semantic intent of `get_project_root()` being designed for repeated evaluation vs. one-shot use
- **What could catch:** A "frozen-dynamic" pattern detector that flags module-level assignments calling functions that consult mutable runtime state
