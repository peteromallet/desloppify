# S328 Verification: Unsandboxed plugin auto-loading from scan target directory

**Author:** @optimus-fulcria
**Claim:** desloppify auto-loads Python plugins from the scan target's `.desloppify/plugins/` directory without sandboxing, enabling arbitrary code execution when scanning untrusted codebases.

## Code References

### discovery.py:95-113 — ACCURATE
Lines 95-113 load `.py` files from `get_project_root() / ".desloppify" / "plugins"` using `importlib.util.spec_from_file_location` + `spec.loader.exec_module(mod)`. This executes arbitrary Python code with full interpreter privileges. Error handling catches `_PLUGIN_IMPORT_ERRORS` but does not prevent code execution — only catches failures after execution has occurred.

### paths.py:13-18 — ACCURATE
`get_project_root()` returns either a `RuntimeContext` override or `_DEFAULT_PROJECT_ROOT`, which defaults to `Path(os.environ.get("DESLOPPIFY_ROOT", Path.cwd())).resolve()`. The project root IS the scan target directory, confirming that plugins are loaded from the directory being analyzed.

## Assessment

The code references are accurate and the mechanism works as described. However, the characterization as "poorly engineered" is weak for the following reasons:

1. **Intentional feature, not a bug.** The user-plugin system is deliberately designed with directory conventions, naming, and error handling. It is an opt-in extension point (user must create `.desloppify/plugins/` and place `.py` files in it).

2. **Standard dev-tool pattern.** Python dev tools routinely execute code from the project directory:
   - pytest loads `conftest.py` from the project
   - ESLint loads `.eslintrc.js`
   - pre-commit runs hooks from config
   - setuptools executes `setup.py`
   - Many linters/formatters load plugin code from project configs

3. **No practical Python sandboxing.** Python has no production-grade sandboxing mechanism. Even `importlib` with restrictions can be bypassed. The standard mitigation is "don't run dev tools on untrusted code," which applies equally to pytest, pip install, and every other Python tool.

4. **Scan target trust model.** Users run desloppify on their own codebases. Running any Python tool on an untrusted codebase already implies code execution risk (e.g., `__init__.py` imports during analysis, tree-sitter native extensions, etc.).

## Verdict: PARTIALLY VERIFIED

The mechanism exists and works as described — code references are accurate. But characterizing an intentional plugin system that follows standard Python dev-tool conventions as "poorly engineered" is a stretch. The "unsandboxed" qualifier is technically true but applies to essentially all Python dev tools.

| Sig | Orig | Core | Overall |
|-----|------|------|---------|
| 3   | 4    | 0    | 2       |

- **Sig 3:** Valid security observation but describes normal Python dev-tool behavior
- **Orig 4:** Accurate code references, real mechanism identified
- **Core 0:** No impact on scoring engine whatsoever
- **Overall 2:** Points at an intentional feature and calls it a deficiency; follows universal Python dev-tool conventions
