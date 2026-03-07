# Bounty Verification: S157 @devnull37 — CLI Command Metadata Split

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4005528341
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. Handler imports + dispatch map in `registry.py` lines 12-51
**CONFIRMED.** `desloppify/app/commands/registry.py:12-51` contains `_build_handlers()` with 18 lazy imports and a dict mapping command names to handler functions.

### 2. Parser subcommand registration in `parser.py` lines 119-140
**CONFIRMED.** `desloppify/app/cli_support/parser.py:109-130` (approximately) calls 18 `_add_*_parser()` functions to register subcommands on the argparse subparser group. Line numbers are close but not exact.

### 3. User-facing command catalog/help in `parser.py` lines 30-67
**CONFIRMED.** `USAGE_EXAMPLES` string at `parser.py:30-65` is a hand-maintained help text listing all commands with descriptions and examples.

### 4. Raw lookup `get_command_handlers()[command]` at `cli.py` lines 136-137, called at 175-176
**CONFIRMED.** Exact line numbers verified:
- `_resolve_handler` at line 136-137 does `get_command_handlers()[command]`
- Called at line 175 inside `main()`

### 5. Drift can cause KeyError at runtime
**PARTIALLY CONFIRMED.** If a parser subcommand exists without a matching registry entry, argparse would accept the command but `_resolve_handler` would raise `KeyError`. However, the `help` command is handled before dispatch (line 166-167), so it's not vulnerable. Currently all 18 commands are in sync across all three locations.

## Duplicate Check

- **S041** (@renhe3983) covers CLI command structure inconsistency (files vs directories, naming conventions) — related but distinct concern. S157 specifically identifies the metadata-split / single-source-of-truth problem.
- No exact duplicate found.

## Assessment

The core observation is valid: command metadata is maintained in three independent locations with no enforcement mechanism. The claimed line references are accurate. This is a real maintenance-drift risk.

However, significant caveats:

1. **Standard pattern**: This is how virtually all Python argparse-based CLIs work. Unifying command registration is a nice-to-have, not an engineering failure.
2. **No actual drift**: All 18 commands are currently in sync across registry, parser, and help text.
3. **Low change frequency**: Commands are added rarely, reducing the practical risk.
4. **Misapplied architecture rule**: The submission cites the "dynamic imports only in `languages/__init__.py` and `engine/hook_registry.py`" rule, but this rule is about plugin discovery, not command registration. The registry uses lazy imports inside a function (standard Python pattern), not dynamic imports.
5. **No runtime bug**: No user has or would encounter a KeyError from this design in practice.
