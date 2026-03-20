# TypeScript Language Plugin for Desloppify

Provides in-depth static analysis for TypeScript and React/TSX codebases.

## Supported extensions

`.ts`, `.tsx`

## Requirements

- Node.js with `npm`/`npx` available on `PATH`
- TypeScript installed in the project: `npm install --save-dev typescript`

Optional tools (enable additional phases):

```bash
npm install --save-dev knip   # dead exports and unused files
```

## Project detection

Activates on projects containing a `package.json` file.

## Usage

```bash
# Scan for issues
desloppify scan --path <project>

# Auto-fix safe issues (unused imports, log cleanup, etc.)
desloppify autofix --path <project>
```

## What gets analysed

| Phase | What it finds |
|-------|--------------|
| Unused (tsc) | Type errors, unused locals, implicit any |
| Dead exports | Exported symbols never imported outside their module |
| Deprecated | Uses of deprecated APIs |
| Logs | Console statements left in production code |
| Structural analysis | God components, large files, complexity hotspots |
| Coupling + cycles + patterns + naming | Import cycles, tight coupling, single-use abstractions, naming issues |
| Tree-sitter cohesion | Modules/classes that do too many unrelated things (when tree-sitter available) |
| Signature analysis | Overly broad function signatures |
| Test coverage | Functions/components with no corresponding tests |
| Code smells | `any` types, empty catch blocks, `@ts-ignore`, non-null assertions, async/await misuse, and more |
| React patterns | Hook bloat, context misuse, state sync issues, prop drilling |
| Framework patterns | Next.js-specific issues when applicable |
| Security | Common TypeScript/Node security patterns |
| Subjective review | LLM analysis of architecture, abstractions, and design quality |
| Duplicates | Near-duplicate functions across the codebase |

## Exclusions

The following are excluded from analysis by default:

- `node_modules`
- `*.d.ts` declaration files
- `dist`, `build`, `.next`, `coverage`

## Auto-fixers

TypeScript has a set of targeted auto-fixers applied via `desloppify autofix`:

- Unused import removal
- Console log cleanup
- `useEffect` dependency array fixes
- Variable and parameter cleanup
- Syntax normalization

---

## TypeScript Plugin Maintainer Notes

### Phase layout

- `phases_basic.py` — logs, unused (tsc), dead exports, deprecated
- `phases_structural.py` — structural analysis (god objects, large files, complexity)
- `phases_coupling.py` — coupling, cycles, orphaned, single-use, naming patterns
- `phases_smells.py` — code smell detection
- `phases_config.py` — shared thresholds and god-class rules

### Detector layout

- `detectors/smells/` — TypeScript-specific smell catalog and detection logic
- `detectors/react/` — React/hooks-specific detectors
- `detectors/security/` — Security pattern detectors
- `detectors/patterns/` — Naming and structural pattern analysis
- `detectors/deps/` — Dependency graph construction
- `detectors/exports.py` — Dead export detection
- `detectors/concerns.py` — Responsibility cohesion analysis
- `detectors/contracts.py` — Interface/type contract checks
- `detectors/deprecated.py` — Deprecated API usage
- `detectors/knip_adapter.py` — Knip integration for dead code detection

### Adding a new smell detector

1. Add smell metadata to `detectors/smells/catalog.py` — `id`, `label`, `pattern`, `severity`
2. For pattern-based smells, the catalog entry is sufficient
3. For context-aware smells, implement detection logic in the appropriate `detector_*.py` module
4. Run checks: `pytest -q desloppify/languages/typescript/tests/`

### Testing

```bash
# Run all TypeScript plugin tests
pytest -q desloppify/languages/typescript/tests/

# Run focused smell tests
pytest -q desloppify/languages/typescript/tests/test_ts_smells.py

# Run React detector tests
pytest -q desloppify/languages/typescript/tests/test_ts_react.py
```
