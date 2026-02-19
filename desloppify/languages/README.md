# Languages Architecture

This directory contains two things:

1. Language plugins (`python/`, `typescript/`, `csharp/`, `dart/`, `gdscript/`)
2. Shared plugin framework internals (`framework/` and `_shared/`)

## Layout

```
languages/
├── __init__.py
├── README.md
├── framework/                # Shared plugin framework internals
│   ├── base/                 # LangConfig, DetectorPhase, FixerConfig contracts
│   │   ├── types.py          # LangConfig, FixerConfig, FixResult dataclasses
│   │   ├── shared_phases.py  # shared detector phase runners
│   │   ├── phase_builders.py # phase builder helpers
│   │   └── structural.py     # structural analysis utilities
│   ├── runtime.py            # LangRun (per-run mutable execution state)
│   ├── resolution.py         # get_lang/available_langs/auto_detect_lang
│   ├── discovery.py          # plugin discovery + load errors
│   ├── commands_base.py      # shared detect-command factories
│   ├── finding_factories.py  # shared finding normalization factories
│   ├── facade_common.py      # shared facade detector helpers
│   ├── contract_validation.py
│   ├── structure_validation.py
│   ├── policy.py
│   └── registry_state.py
├── _shared/                  # Shared static assets/templates for language plugins
└── <language>/               # One folder per language plugin
```

## Adding A New Language

Use the scaffold command:

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

The scaffold creates `desloppify/languages/<name>/...` and can wire test discovery into `pyproject.toml`.

## Plugin Contract (Required Files)

`desloppify/languages/<name>/` must contain:

- `__init__.py`
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

Registration/validation fails when the contract is incomplete.

## Design Rules

- Import direction: `languages/<name>/` -> `engine/detectors/` and `languages/framework/*`
- Do not import language-specific modules from `engine/detectors/*`
- Keep language plugin code in its language folder
- Keep reusable cross-language framework code in `languages/framework/`
- Keep shared static prompts/templates in `languages/_shared/`

## Test Command

```bash
pytest -q \
  desloppify/tests/lang/common/test_lang_standardization.py \
  desloppify/tests/lang/common/test_lang_test_layout.py \
  desloppify/languages/<name>/tests
```

## Adding Subjective Dimensions (One Place)

Subjective dimensions are metadata-driven. Add the dimension prompt once, and
scoring/display/reset wiring is automatic.

Where to add:

- Global per-file dimension: `desloppify/languages/_shared/review_data/per_file_dimensions.json`
- Global holistic dimension: `desloppify/languages/_shared/review_data/holistic_dimensions.json`
- Language-specific dimension override:
  `desloppify/languages/<lang>/review_data/per_file_dimensions.override.json`
  or `desloppify/languages/<lang>/review_data/holistic_dimensions.override.json`

In each `dimension_prompts.<dimension_key>` entry, optional `meta` fields:

- `enabled_by_default` (bool): auto-register in default review dimensions
- `weight` (number): subjective score weighting
- `display_name` (string): scorecard/output label
- `reset_on_scan` (bool): include/exclude from `scan --reset-subjective`

### How Language-Specific Dimensions Behave

Language overrides support both modes:

- Override an existing dimension:
  Add the same key under `dimension_prompts` in the language override file.
  The language entry overrides prompt text + metadata (`weight`,
  `display_name`, etc.) for that language's runs.
- Add a new dimension alongside existing ones:
  Add a new `dimension_prompts.<new_key>` entry with
  `meta.enabled_by_default: true`.
  It is auto-registered for that language without editing central scoring maps.

Advanced (replace full set):

- You can provide a full language payload file
  (`review_data/per_file_dimensions.json` or
  `review_data/holistic_dimensions.json`) to replace shared defaults, then still
  layer `*.override.json` on top.

### Weighting Guidance

System-level math:

- Overall score = `40% mechanical + 60% subjective`
- Within subjective, each dimension's impact share is:
  `weight / sum(active subjective weights)`

Practical guidance:

- `1-3`: niche/secondary signal
- `3-6`: meaningful language-specific signal
- `6-10`: core language-specific quality axis
- `>10`: only when you intentionally want strong dominance

Example:

```json
{
  "dimension_prompts": {
    "folder_structure_quality": {
      "description": "Directory layout and navigability quality",
      "look_for": ["mixed concerns in large flat folders"],
      "skip": ["small repos where flat layout is fine"],
      "meta": {
        "enabled_by_default": true,
        "weight": 4.0,
        "display_name": "Folder Structure",
        "reset_on_scan": true
      }
    }
  }
}
```

For language overrides, this prompt-only entry is enough; no
`*_dimensions_append` is required when `enabled_by_default` is true.
