# C/C++ Language Module

This document explains what the C/C++ plugin needs for a full tool-backed scan.

## Native C and C++ AST analysis

Without build metadata, the `cxx` plugin uses the C Tree-sitter grammar for
`.c` files and the C++ grammar for C++ sources and headers. This matters even
when both grammars accept a file: for example, a C callback named `throw` is a function call,
whereas C++ interprets `throw(value)` as an exception statement.

When `compile_commands.json` is present at the scan root, AST smells and
cohesion use its source-file compilation language. Both `arguments` and `command`
entries are supported. Relative `directory` paths are resolved from the database
directory, and source paths from the command's `directory`. Missing or malformed
metadata falls back to file extensions.

Supported overrides include GCC/Clang `-x c`, `-x c++`, their joined forms,
header/preprocessed equivalents and `-x none`; the language in force at the
source argument is used. MSVC `/TC`, `/TP`, `/TcFILE` and `/TpFILE` (including
separate filenames and clang-cl's dash forms) are supported. Recognized C++
drivers (`c++`, `g++`, `clang++`, versioned/cross-prefixed variants, optionally
behind `ccache`, `sccache` or `distcc`) and Clang `--driver-mode` inform defaults.
`-std=` alone does not determine the input language.

Headers, including `.h`, retain C++ parsing because they may be shared with C++
translation units; compilation entries do not change that policy. Conflicting C
and C++ configurations for a source retain the plugin's previous C++ behavior,
with a warning. Findings for that file have low confidence and list both
`compilation_languages` in their details. This represents only the C++ context,
not both configurations; C-specific results may be incomplete.

This is not a compiler frontend: response files, forwarded frontend flags,
arbitrary compiler wrappers, shell expansion and cross-host command syntax are
not interpreted. Use
`arguments` to avoid platform-specific shell quoting limits. Metadata is read
once per AST phase, without a global cache. Dependency resolution and external
tools continue to use build metadata separately. Function extraction for
duplicate/signature analysis and structural complexity signals are separate
from these AST phases.

## What "full" means for C/C++

The C/C++ plugin can still scan a repository when external tooling is missing, but the deepest and most accurate analysis depends on build metadata and external analyzers.

For a full C/C++ check, Desloppify expects all of the following:

- `compile_commands.json`
- `clang-tidy` available on `PATH`
- `cppcheck` available on `PATH`
- the Python extras from `desloppify[full]` installed in the environment running Desloppify

Without those pieces, the scan degrades gracefully instead of failing outright, but the results are less complete.

## Required pieces

### 1. `compile_commands.json`

This is the primary analysis input for C/C++.

It improves:

- dependency and include resolution
- `clang-tidy` execution context
- tool-backed security findings
- general scan accuracy on real-world projects

Preferred location:

- place `compile_commands.json` at the repo root you pass to `desloppify scan --path ...`

Typical CMake generation:

```bash
cmake -S . -B build_compile_db -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cp build_compile_db/compile_commands.json ./compile_commands.json
```

On Windows with Visual Studio generators, CMake often does not emit `compile_commands.json` directly. In that case, use a Makefiles/Ninja-style configure in a separate build directory and copy the generated file to the repo root.

### 2. `clang-tidy`

`clang-tidy` provides the strongest C/C++-specific security and CERT-style findings.

Check availability:

```bash
clang-tidy --version
```

If `clang-tidy` is missing, Desloppify will still run, but C/C++ security falls back to weaker heuristics for files that are not covered by other tools.

### 3. `cppcheck`

`cppcheck` powers the `cppcheck_issue` phase and contributes additional tool-backed C/C++ findings.

Check availability:

```bash
cppcheck --version
```

If `cppcheck` is missing or times out, the scan still completes, but detector coverage for `cppcheck_issue` is reduced.

### 4. Python environment

Install Desloppify with the full extras in the environment that runs the scan:

```bash
pip install --upgrade "desloppify[full]"
```

This covers the Python-side runtime dependencies used by the full plugin system. It does **not** install system binaries like `clang-tidy` or `cppcheck`.

## Graceful degradation

The C/C++ plugin is designed to keep scanning when some requirements are missing.

### If `compile_commands.json` is missing

- dependency analysis falls back to best-effort local include scanning
- `clang-tidy`-backed coverage is usually weaker or unavailable
- overall result quality drops, especially on non-trivial projects

### If `clang-tidy` is missing

- scan continues
- C/C++ security falls back to other available sources
- if no stronger source is available, regex-based fallback is used with reduced coverage metadata

### If `cppcheck` is missing

- scan continues
- `cppcheck_issue` coverage is reduced
- other phases still run

### If all external C/C++ tools are missing

- scan still runs
- structural, coupling, signature, duplicate, and review-related phases may still produce useful output
- C/C++ tool-backed findings are reduced or absent
- results should be treated as partial coverage, not a full check

## Recommended verification sequence

Before relying on a C/C++ scan in a new repository, verify these in order:

```bash
clang-tidy --version
cppcheck --version
test -f compile_commands.json
desloppify --lang cxx scan --path .
```

On Windows, replace `test -f` with an equivalent shell command for your terminal.

## Practical interpretation

A scan that completes is not automatically a full C/C++ scan.

Treat the scan as fully tool-backed only when:

- `compile_commands.json` is present for the scanned project
- `clang-tidy` is available
- `cppcheck` is available
- the scan output does not report reduced coverage for the C/C++ tool phases
