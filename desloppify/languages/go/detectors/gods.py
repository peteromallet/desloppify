"""Go god struct detection — structs with too many fields/methods/LOC."""

from __future__ import annotations

import re
from pathlib import Path

from desloppify.engine.detectors.base import ClassInfo, FunctionInfo, GodRule
from desloppify.languages.go.extractors import find_go_files

# ── Receiver regex: func (r *StructName) MethodName(...)
_RECEIVER_RE = re.compile(
    r"^func\s+\(\s*\w+\s+\*?(\w+)(?:\[[\w,\s]+\])?\s*\)\s+(\w+)"
)

# ── Struct declaration regex
_STRUCT_DECL_RE = re.compile(
    r"^type\s+(\w+)\s+struct\s*\{"
)

GO_GOD_RULES: list[GodRule] = [
    GodRule(
        name="method_count",
        description="methods",
        extract=lambda cls: len(cls.methods),
        threshold=10,
    ),
    GodRule(
        name="field_count",
        description="fields",
        extract=lambda cls: len(cls.attributes),
        threshold=15,
    ),
    GodRule(
        name="loc",
        description="LOC",
        extract=lambda cls: cls.loc,
        threshold=300,
    ),
]


def extract_go_structs(path: Path) -> list[ClassInfo]:
    """Extract Go struct definitions with their fields and associated methods."""
    files = find_go_files(path)
    # First pass: collect all methods by receiver type across all files
    methods_by_struct: dict[str, list] = {}

    for filepath in files:
        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError:
            continue
        for line in content.splitlines():
            m = _RECEIVER_RE.match(line)
            if m:
                struct_name = m.group(1)
                method_name = m.group(2)
                methods_by_struct.setdefault(struct_name, []).append(
                    (method_name, filepath)
                )

    # Second pass: extract struct definitions with fields
    structs: list[ClassInfo] = []
    for filepath in files:
        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError:
            continue
        lines = content.splitlines()

        i = 0
        while i < len(lines):
            m = _STRUCT_DECL_RE.match(lines[i].strip())
            if not m:
                i += 1
                continue

            struct_name = m.group(1)
            start_line = i + 1  # 1-indexed

            # Find closing brace by tracking depth
            depth = 1
            fields: list[str] = []
            j = i + 1
            while j < len(lines) and depth > 0:
                stripped = lines[j].strip()
                depth += stripped.count('{') - stripped.count('}')
                if depth > 0 and stripped and not stripped.startswith("//") and not stripped.startswith("/*"):
                    # This is a field line
                    # Skip embedded structs (lines that are just a type name)
                    parts = stripped.split()
                    if len(parts) >= 2 and not stripped.startswith("}"):
                        fields.append(parts[0])
                j += 1

            end_line = j  # 1-indexed
            loc = end_line - start_line + 1

            # Get methods for this struct
            methods = methods_by_struct.get(struct_name, [])

            total_loc = loc

            # Create FunctionInfo stubs for methods
            method_infos = [
                FunctionInfo(
                    name=mname, file=mfile, line=0, end_line=0,
                    loc=0, body="",
                )
                for mname, mfile in methods
            ]

            structs.append(ClassInfo(
                name=struct_name,
                file=filepath,
                line=start_line,
                loc=total_loc,
                methods=method_infos,
                attributes=fields,
                metrics={
                    "method_count": len(methods),
                    "field_count": len(fields),
                    "name": struct_name,
                },
            ))

            i = j

    return structs
