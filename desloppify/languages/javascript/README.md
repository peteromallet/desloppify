# JavaScript Language Plugin for Desloppify

Provides JavaScript/JSX analysis via ESLint.

## Supported extensions

`.js`, `.jsx`, `.mjs`, `.cjs`

## Requirements

- Node.js with npm/npx available on `PATH`
- ESLint installed in the project: `npm install --save-dev eslint`

## Project detection

Activates on projects containing a `package.json` file.

## Usage

```bash
# Scan for issues
desloppify scan --path <project>

# Scan and auto-fix
desloppify scan --path <project> --fix
```

Autofix is supported — ESLint's `--fix` flag is used to apply safe automatic corrections.

## Exclusions

The following directories are excluded from analysis:

- `node_modules`
- `dist`
- `build`
- `.next`
- `coverage`
