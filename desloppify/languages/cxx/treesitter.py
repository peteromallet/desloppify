"""Compilation-aware Tree-sitter phases for the existing C/C++ plugin."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from pathlib import Path

from desloppify.base.discovery.file_paths import resolve_path
from desloppify.languages._framework import treesitter
from desloppify.languages._framework.base.types import (
    DetectorPhase,
    LangRuntimeContract,
)
from desloppify.languages._framework.treesitter import (
    C_SPEC,
    CPP_SPEC,
    TreeSitterLangSpec,
)
from desloppify.languages._framework.treesitter.phases import (
    make_ast_smells_phase,
    make_cohesion_phase,
)
from desloppify.languages.cxx.compile_commands import (
    CompileCommand,
    load_compile_commands,
)
from desloppify.languages.cxx.extractors import CXX_SOURCE_EXTENSIONS
from desloppify.state_io import Issue

logger = logging.getLogger(__name__)

_CPP_DRIVER = re.compile(r"(?:^|-)(?:g\+\+|c\+\+|clang\+\+)(?:-\d+(?:\.\d+)*)?$")
_WRAPPERS = {"ccache", "sccache", "distcc"}
_LANGUAGES = {
    "c": "c",
    "c-header": "c",
    "cpp-output": "c",
    "c++": "cpp",
    "c++-header": "cpp",
    "c++-cpp-output": "cpp",
}
_OPTION_VALUES = {
    "-o",
    "-I",
    "-isystem",
    "-iquote",
    "-include",
    "-imacros",
    "-isysroot",
    "--sysroot",
    "-MF",
    "-MT",
    "-MQ",
    "-Xclang",
    "-target",
    "--target",
    "-arch",
    "-D",
    "-U",
}


def _command_path(value: str, directory: Path) -> str:
    path = Path(value.strip('"'))
    return os.path.normcase(str((directory / path).resolve()))


def _command_language(command: CompileCommand) -> str:
    """Interpret input language, not the language-standard warning option."""
    tokens = command.arguments
    drivers = iter(tokens)
    driver = Path(next(drivers, "").strip('"')).name.lower().removesuffix(".exe")
    while driver in _WRAPPERS:
        driver = Path(next(drivers, "").strip('"')).name.lower().removesuffix(".exe")
    default = (
        "cpp"
        if Path(command.source).suffix != ".c" or _CPP_DRIVER.search(driver)
        else "c"
    )
    language = "none"
    input_language: str | None = None
    msvc_global: str | None = None
    msvc_input: str | None = None
    source = os.path.normcase(command.source)
    args = iter(tokens[1:])
    for token in args:
        if token == "--":
            if any(_command_path(arg, command.directory) == source for arg in args):
                input_language = language
            break
        if token == "-x":
            language = next(args, "none")
        elif token.startswith("-x"):
            language = token[2:]
        elif token in {"/TC", "-TC", "/TP", "-TP"}:
            msvc_global = "c" if token.endswith("C") else "cpp"
        elif token.startswith(("/Tc", "-Tc", "/Tp", "-Tp")):
            target = token[3:] or next(args, "")
            if target and _command_path(target, command.directory) == source:
                msvc_input = "c" if token[2] == "c" else "cpp"
        elif token in _OPTION_VALUES:
            next(args, None)
        elif token.startswith("--driver-mode="):
            mode = token.partition("=")[2]
            if mode == "g++":
                default = "cpp"
            elif mode in {"gcc", "cl", "cpp"}:
                default = "c" if Path(command.source).suffix == ".c" else "cpp"
        elif not token.startswith(("-", "/")) or Path(token).is_absolute():
            if _command_path(token, command.directory) == source:
                input_language = language
    return (
        msvc_input
        or msvc_global
        or _LANGUAGES.get(
            input_language if input_language is not None else language, default
        )
    )


def _compilation_specs(path: Path) -> tuple[dict[str, TreeSitterLangSpec], set[str]]:
    languages: dict[str, set[str]] = {}
    for command in load_compile_commands(path):
        # Header language is intentionally unchanged, even for explicit entries.
        if Path(command.source).suffix not in CXX_SOURCE_EXTENSIONS:
            continue
        languages.setdefault(os.path.normcase(command.source), set()).add(
            _command_language(command)
        )
    conflicts = {file for file, modes in languages.items() if len(modes) > 1}
    specs = {
        file: CPP_SPEC if "cpp" in modes else C_SPEC
        for file, modes in languages.items()
    }
    return specs, conflicts


def _compilation_aware_phase(factory: Callable[..., DetectorPhase]) -> DetectorPhase:
    base = factory(CPP_SPEC)

    def run(
        path: Path, lang: LangRuntimeContract
    ) -> tuple[list[Issue], dict[str, int]]:
        # Prepare per invocation: no per-file DB reads or configuration shared
        # between scans, even when one CxxConfig is used for different roots.
        specs, conflicts = _compilation_specs(path)

        def select(filepath: str) -> TreeSitterLangSpec:
            file = os.path.normcase(resolve_path(filepath))
            if file in conflicts:
                logger.warning(
                    "Conflicting C/C++ compile languages for %s; retaining C++ parsing. "
                    "%s findings represent only that context and have low confidence.",
                    file,
                    base.label,
                )
            fallback = C_SPEC if Path(filepath).suffix == ".c" else CPP_SPEC
            return specs.get(file, fallback)

        issues, potentials = factory(CPP_SPEC, spec_for_file=select).run(path, lang)
        for issue in issues:
            if os.path.normcase(resolve_path(issue["file"])) in conflicts:
                issue["confidence"] = "low"
                issue["detail"]["compilation_languages"] = ["c", "cpp"]
        return issues, potentials

    return DetectorPhase(base.label, run, slow=base.slow)


def make_cxx_treesitter_phases() -> list[DetectorPhase]:
    """Reuse shared AST phases with scan-local compilation context."""
    if not treesitter.is_available():
        return []
    return [
        _compilation_aware_phase(factory)
        for factory in (make_ast_smells_phase, make_cohesion_phase)
    ]
