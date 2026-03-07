# Bounty Verification: S120 @optimus-fulcria — Unsandboxed Plugin Auto-Loading

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4003923979
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. `discovery.py:95-113` auto-loads plugins from scan target
**CONFIRMED.** At snapshot commit `6eb2065`, `desloppify/languages/_framework/discovery.py` lines 95-113 contain:
```python
user_plugin_dir = get_project_root() / ".desloppify" / "plugins"
if user_plugin_dir.is_dir():
    for f in sorted(user_plugin_dir.glob("*.py")):
        spec = importlib.util.spec_from_file_location(
            f"desloppify_user_plugin_{f.stem}", f
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
```
This executes arbitrary Python files from the scanned project's `.desloppify/plugins/` directory.

### 2. `get_project_root()` resolves to the scan target
**CONFIRMED.** `desloppify/base/discovery/paths.py:13-18` returns `current_runtime_context().project_root` or falls back to `DESLOPPIFY_ROOT` env var / `Path.cwd()`. When `desloppify scan --path /some/repo` is run, `project_root` is set to the target directory.

### 3. No user consent, warning, or sandboxing
**CONFIRMED.** There is no CLI flag, prompt, log warning, hash verification, allowlist, or capability restriction before `exec_module()` runs. The only safety is a broad `try/except` that catches load errors — but that does not prevent execution, only catches failures after the fact.

### 4. Supply chain exposure pattern
**CONFIRMED.** A repository containing `.desloppify/plugins/malicious.py` would execute that file when scanned. This matches the CVE-2024-3566 pattern (arbitrary code execution via repo-embedded config).

## Duplicate Check

| Submission | Author | Timestamp | Same Issue? |
|-----------|--------|-----------|-------------|
| **S120** | optimus-fulcria | 2026-03-05T10:10:19Z | **Original** |
| S126 | TSECP | 2026-03-05T12:53:34Z | Yes — near-identical wording |
| S146 | tianshanclaw | 2026-03-05T13:33:52Z | Yes — near-identical wording |
| S225 | g5n-dev | 2026-03-06T08:11:05Z | Yes — same finding, different write-up |

S120 has clear timestamp priority.

## Assessment

The submission identifies a genuine design flaw: a code analysis tool that executes arbitrary code from its scan target without consent. The analysis is well-structured, references are accurate, and the trust-boundary inversion is clearly articulated.

**Strengths:**
- All code references verified against snapshot
- Clear articulation of the inverted trust model
- Practical attack scenario (git clone + scan)
- Comparison with industry practice (pylint, ruff, semgrep avoid executing analyzed code)

**Caveats:**
- Plugin auto-loading is an intentional feature for extensibility — the flaw is the absence of a consent gate, not the feature itself
- In practice, users typically scan their own projects (not untrusted repos), reducing real-world risk
- The feature could be fixed with a `--trust-plugins` flag or explicit opt-in rather than removal
