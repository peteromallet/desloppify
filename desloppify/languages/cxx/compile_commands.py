"""Compilation-database loading shared by C/C++ analysis."""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CompileCommand:
    """One command with paths resolved relative to its compilation database."""

    source: str
    directory: Path
    arguments: list[str]


def _parse_command_tokens(entry: dict[str, Any]) -> list[str]:
    arguments = entry.get("arguments")
    if not isinstance(arguments, list):
        command = entry.get("command")
        arguments = (
            shlex.split(command, posix=os.name != "nt")
            if isinstance(command, str) and command.strip()
            else []
        )
    if not all(isinstance(token, str) and "\0" not in token for token in arguments):
        raise ValueError("Compilation arguments must be strings without NUL bytes")
    return arguments


def load_compile_commands(path: Path) -> list[CompileCommand]:
    """Read root metadata once; ignore malformed entries without losing peers."""
    root = path.resolve()
    try:
        payload = json.loads((root / "compile_commands.json").read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []
    if not isinstance(payload, list):
        return []

    commands: list[CompileCommand] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        file_value = entry.get("file")
        if not isinstance(file_value, str) or not file_value.strip():
            continue
        try:
            directory_value = entry.get("directory")
            directory = (
                Path(directory_value)
                if isinstance(directory_value, str) and directory_value.strip()
                else root
            )
            if not directory.is_absolute():
                directory = root / directory
            directory = directory.resolve()
            source = Path(file_value)
            if not source.is_absolute():
                source = directory / source
            arguments = _parse_command_tokens(entry)
            commands.append(CompileCommand(str(source.resolve()), directory, arguments))
        except (ValueError, OSError):
            continue
    return commands
