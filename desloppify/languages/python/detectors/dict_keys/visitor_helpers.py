"""Helper routines used by DictKeyVisitor."""

from __future__ import annotations

import ast

from desloppify.languages.python.detectors.dict_keys import (
    _BULK_READ_METHODS,
    _CONFIG_NAMES,
    TrackedDict,
    _get_name,
    _get_str_key,
    _is_singular_plural,
    _levenshtein,
)


def mark_returned_or_passed(visitor, node: ast.expr) -> None:
    """Mark a tracked dict expression as escaped via return/call boundary."""
    if isinstance(node, ast.Tuple):
        for elt in node.elts:
            mark_returned_or_passed(visitor, elt)
        return
    if isinstance(node, ast.List | ast.Set):
        for elt in node.elts:
            mark_returned_or_passed(visitor, elt)
        return
    if isinstance(node, ast.Dict):
        for key in node.keys:
            if key is not None:
                mark_returned_or_passed(visitor, key)
        for value in node.values:
            mark_returned_or_passed(visitor, value)
        return
    name = _get_name(node)
    if not name:
        return
    tracked = visitor._get_tracked(name)
    if tracked:
        tracked.returned_or_passed = True


def mark_assignment_escape(visitor, targets: list[ast.expr], value: ast.expr) -> None:
    """Mark tracked dict as escaped when assigned into container/attribute slots."""
    name = _get_name(value)
    if not name:
        return
    tracked = visitor._get_tracked(name)
    if tracked is None:
        return
    for target in targets:
        if isinstance(target, ast.Subscript | ast.Attribute):
            tracked.returned_or_passed = True
            return


def dict_source_provenance(
    visitor,
    value: ast.expr,
) -> tuple[list[str], bool] | None:
    """Return known keys and whether a dict expression may contain other keys."""

    source_name = _get_name(value)
    if source_name:
        tracked = visitor._get_tracked(source_name)
        if tracked is None:
            return None
        return list(tracked.writes), tracked.keyset_is_open

    if isinstance(value, ast.Dict):
        known_keys: list[str] = []
        keyset_is_open = False
        for key_node, value_node in zip(value.keys, value.values, strict=True):
            if key_node is None:
                provenance = dict_source_provenance(visitor, value_node)
                if provenance is None:
                    keyset_is_open = True
                else:
                    source_keys, source_is_open = provenance
                    known_keys.extend(source_keys)
                    keyset_is_open |= source_is_open
                continue
            key = _get_str_key(key_node)
            if key is None:
                keyset_is_open = True
            else:
                known_keys.append(key)
        return known_keys, keyset_is_open

    if not isinstance(value, ast.Call):
        return None

    if isinstance(value.func, ast.Name) and value.func.id == "dict":
        known_keys = []
        keyset_is_open = False
        for argument in value.args:
            provenance = dict_source_provenance(visitor, argument)
            if provenance is None:
                keyset_is_open = True
            else:
                source_keys, source_is_open = provenance
                known_keys.extend(source_keys)
                keyset_is_open |= source_is_open
        for keyword in value.keywords:
            if keyword.arg is not None:
                known_keys.append(keyword.arg)
                continue
            provenance = dict_source_provenance(visitor, keyword.value)
            if provenance is None:
                keyset_is_open = True
            else:
                source_keys, source_is_open = provenance
                known_keys.extend(source_keys)
                keyset_is_open |= source_is_open
        return known_keys, keyset_is_open

    if (
        isinstance(value.func, ast.Attribute)
        and value.func.attr == "copy"
        and not value.args
        and not value.keywords
    ):
        source_name = _get_name(value.func.value)
        if source_name:
            tracked = visitor._get_tracked(source_name)
            if tracked is not None:
                return list(tracked.writes), tracked.keyset_is_open
    return None


def record_call_interactions(visitor, node: ast.Call) -> None:
    """Update tracked dict read/write metadata from a call expression."""
    if isinstance(node.func, ast.Attribute):
        name = _get_name(node.func.value)
        method = node.func.attr
        if name:
            tracked = visitor._get_tracked(name)
            if tracked:
                if method in ("get", "pop", "__getitem__", "__contains__"):
                    if node.args:
                        key = _get_str_key(node.args[0])
                        if key:
                            tracked.reads[key].append(node.lineno)
                        else:
                            tracked.has_dynamic_key = True
                elif method == "setdefault":
                    if node.args:
                        key = _get_str_key(node.args[0])
                        if key:
                            tracked.reads[key].append(node.lineno)
                            tracked.writes[key].append(node.lineno)
                        else:
                            tracked.has_dynamic_key = True
                            tracked.keyset_is_open = True
                elif method == "update":
                    if node.args:
                        provenance = dict_source_provenance(visitor, node.args[0])
                        if provenance is None:
                            tracked.keyset_is_open = True
                        else:
                            source_keys, source_is_open = provenance
                            for key in source_keys:
                                tracked.writes[key].append(node.lineno)
                            tracked.keyset_is_open |= source_is_open
                    for kw in node.keywords:
                        if kw.arg:
                            tracked.writes[kw.arg].append(node.lineno)
                        else:
                            provenance = dict_source_provenance(visitor, kw.value)
                            if provenance is None:
                                tracked.keyset_is_open = True
                            else:
                                source_keys, source_is_open = provenance
                                for key in source_keys:
                                    tracked.writes[key].append(node.lineno)
                                tracked.keyset_is_open |= source_is_open
                elif method in _BULK_READ_METHODS:
                    tracked.bulk_read = True

    for arg in node.args:
        mark_returned_or_passed(visitor, arg)
    for kw in node.keywords:
        if kw.arg is None:
            name = _get_name(kw.value)
            if name:
                tracked = visitor._get_tracked(name)
                if tracked:
                    tracked.has_star_unpack = True
        else:
            mark_returned_or_passed(visitor, kw.value)


def analyze_scope_issues(
    visitor,
    scope: dict[str, TrackedDict],
    func_name: str,
    *,
    is_class: bool = False,
) -> list[dict]:
    """Analyze a completed scope and return dict-key issues."""
    issues: list[dict] = []
    seen_tracked: set[int] = set()
    for tracked in scope.values():
        tracked_identity = id(tracked)
        if tracked_identity in seen_tracked:
            continue
        seen_tracked.add(tracked_identity)
        if not tracked.locally_created:
            continue

        suppress_dead = (
            tracked.returned_or_passed
            or tracked.has_dynamic_key
            or tracked.has_star_unpack
            or tracked.bulk_read
            or any(
                tracked.name.lower().endswith(name) or tracked.name.lower() == name
                for name in _CONFIG_NAMES
            )
            or (not is_class and func_name in ("__init__", "setUp", "setup"))
            or sum(len(lines) for lines in tracked.writes.values()) < 3
        )

        written_keys = set(tracked.writes.keys())
        read_keys = set(tracked.reads.keys())

        dead_keys = written_keys - read_keys
        if not suppress_dead:
            for key in sorted(dead_keys):
                line = tracked.writes[key][0]
                issues.append(
                    {
                        "file": visitor.filepath,
                        "kind": "dead_write",
                        "variable": tracked.name,
                        "key": key,
                        "line": line,
                        "func": func_name,
                        "tier": 3,
                        "confidence": "medium",
                        "summary": (
                            f'Dict key "{key}" written to `{tracked.name}` '
                            f"at line {line} but never read"
                        ),
                        "detail": f"in {func_name}()",
                    }
                )

        phantom_keys = set() if tracked.keyset_is_open else read_keys - written_keys
        for key in sorted(phantom_keys):
            line = tracked.reads[key][0]
            issues.append(
                {
                    "file": visitor.filepath,
                    "kind": "phantom_read",
                    "variable": tracked.name,
                    "key": key,
                    "line": line,
                    "func": func_name,
                    "tier": 2,
                    "confidence": "high",
                    "summary": (
                        f'Dict key "{key}" read at line {line} '
                        f"but never written to `{tracked.name}`"
                    ),
                    "detail": (
                        f"Created at line {tracked.created_line} in "
                        f"{func_name}() — will raise KeyError or "
                        f"return None via .get()"
                    ),
                }
            )

        for dead_key in sorted(dead_keys):
            for phantom_key in sorted(phantom_keys):
                distance = _levenshtein(dead_key, phantom_key)
                is_plural_miss = _is_singular_plural(dead_key, phantom_key)
                if distance <= 2 or is_plural_miss:
                    write_line = tracked.writes[dead_key][0]
                    read_line = tracked.reads[phantom_key][0]
                    issues.append(
                        {
                            "file": visitor.filepath,
                            "kind": "near_miss",
                            "variable": tracked.name,
                            "key": f"{dead_key}~{phantom_key}",
                            "line": write_line,
                            "func": func_name,
                            "tier": 2,
                            "confidence": "high",
                            "summary": (
                                f'Possible key typo: "{dead_key}" vs "{phantom_key}" '
                                f"on dict `{tracked.name}` in {func_name}()"
                            ),
                            "detail": (
                                f'Written: "{dead_key}" at line {write_line}, '
                                f'Read: "{phantom_key}" at line {read_line} '
                                f"— edit distance {distance}"
                            ),
                        }
                    )

        for key, write_lines in tracked.writes.items():
            if len(write_lines) < 2:
                continue
            read_lines = tracked.reads.get(key, [])
            for idx in range(len(write_lines) - 1):
                first, second = write_lines[idx], write_lines[idx + 1]
                has_read_between = any(first < read <= second for read in read_lines)
                if not has_read_between:
                    issues.append(
                        {
                            "file": visitor.filepath,
                            "kind": "overwritten_key",
                            "variable": tracked.name,
                            "key": key,
                            "line": second,
                            "func": func_name,
                            "tier": 3,
                            "confidence": "medium",
                            "summary": (
                                f'Dict key "{key}" overwritten on `{tracked.name}` '
                                f"at line {second} (previously set at line {first}, "
                                "never read between)"
                            ),
                            "detail": f"in {func_name}()",
                        }
                    )
    return issues
