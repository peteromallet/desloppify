# SCSS Language Plugin for Desloppify

Provides SCSS/Sass analysis via [stylelint](https://stylelint.io/).

## Supported extensions

`.scss`, `.sass`

## Requirements

```bash
npm install -g stylelint stylelint-config-standard-scss
```

## Project detection

The plugin activates when desloppify finds a `_scss` directory or a `.stylelintrc` file in the project.

## Excluded paths

`node_modules`, `_output`, `.quarto`, `vendor`

## Usage

```bash
# Scan a project
desloppify scan --path <project>

# Auto-fix stylelint issues
desloppify autofix stylelint-issue --path <project>
```
