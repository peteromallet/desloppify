"""DictKeyVisitor — AST visitor tracking dict key writes/reads per scope."""

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


def _mark_returned_or_passed(visitor: DictKeyVisitor, node: ast.expr) -> None:
    """Mark a tracked dict expression as escaped via return/call boundary."""
    if isinstance(node, ast.Tuple):
        for elt in node.elts:
            _mark_returned_or_passed(visitor, elt)
        return
    name = _get_name(node)
    if not name:
        return
    tracked = visitor._get_tracked(name)
    if tracked:
        tracked.returned_or_passed = True


def _record_call_interactions(visitor: DictKeyVisitor, node: ast.Call) -> None:
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
                elif method == "update":
                    if node.args and isinstance(node.args[0], ast.Dict):
                        for key_node in node.args[0].keys:
                            key = _get_str_key(key_node) if key_node else None
                            if key:
                                tracked.writes[key].append(node.lineno)
                            elif key_node is None:
                                tracked.has_dynamic_key = True
                    for kw in node.keywords:
                        if kw.arg:
                            tracked.writes[kw.arg].append(node.lineno)
                        else:
                            tracked.has_dynamic_key = True
                elif method in _BULK_READ_METHODS:
                    tracked.bulk_read = True

    for arg in node.args:
        _mark_returned_or_passed(visitor, arg)
    for kw in node.keywords:
        if kw.arg is None:
            name = _get_name(kw.value)
            if name:
                tracked = visitor._get_tracked(name)
                if tracked:
                    tracked.has_star_unpack = True
        else:
            _mark_returned_or_passed(visitor, kw.value)


def _analyze_scope_findings(
    visitor: DictKeyVisitor,
    scope: dict[str, TrackedDict],
    func_name: str,
    *,
    is_class: bool = False,
) -> list[dict]:
    """Analyze a completed scope and return dict-key findings."""
    findings: list[dict] = []
    for tracked in scope.values():
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
                findings.append(
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

        phantom_keys = read_keys - written_keys
        for key in sorted(phantom_keys):
            line = tracked.reads[key][0]
            findings.append(
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
                    findings.append(
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
                    findings.append(
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
    return findings


class DictKeyVisitor(ast.NodeVisitor):
    """Walk a module AST, tracking dict key writes/reads per function scope."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._scopes: list[dict[str, TrackedDict]] = []
        self._class_dicts: dict[str, TrackedDict] = {}  # self.x dicts
        self._in_init_or_setup = False
        self._findings: list[dict] = []
        self._dict_literals: list[dict] = []  # for schema drift

    def _current_scope(self) -> dict[str, TrackedDict]:
        return self._scopes[-1] if self._scopes else {}

    def _track(
        self,
        name: str,
        line: int,
        *,
        locally_created: bool,
        initial_keys: list[str] | None = None,
    ) -> TrackedDict:
        scope = self._current_scope()
        td = TrackedDict(name=name, created_line=line, locally_created=locally_created)
        if initial_keys:
            for k in initial_keys:
                td.writes[k].append(line)
        scope[name] = td
        return td

    def _get_tracked(self, name: str) -> TrackedDict | None:
        # Check current scope first, then class scope for self.x
        for scope in reversed(self._scopes):
            if name in scope:
                return scope[name]
        if name.startswith("self.") and name in self._class_dicts:
            return self._class_dicts[name]
        return None

    # -- Scope management --

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        prev_init = self._in_init_or_setup
        self._in_init_or_setup = node.name in ("__init__", "setUp", "setup")
        self._scopes.append({})
        self.generic_visit(node)
        scope = self._scopes.pop()
        self._findings.extend(_analyze_scope_findings(self, scope, node.name))
        self._in_init_or_setup = prev_init

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        prev_class_dicts = self._class_dicts
        self._class_dicts = {}
        self.generic_visit(node)
        self._findings.extend(
            _analyze_scope_findings(
                self,
                self._class_dicts,
                f"class {node.name}",
                is_class=True,
            )
        )
        self._class_dicts = prev_class_dicts

    # -- Dict creation --

    def visit_Assign(self, node: ast.Assign) -> None:
        if len(node.targets) == 1:
            target = node.targets[0]
            name = _get_name(target)
            if name:
                self._check_dict_creation(name, node.value, node.lineno)
        # Also check for subscript writes: d["key"] = val
        for target in node.targets:
            self._check_subscript_write(target, node.lineno)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        # AugAssign (d["k"] += v) is both a read AND a write
        if isinstance(node.target, ast.Subscript):
            name = _get_name(node.target.value)
            if name:
                td = self._get_tracked(name)
                if td:
                    key = _get_str_key(node.target.slice)
                    if key:
                        td.reads[key].append(node.lineno)
                    else:
                        td.has_dynamic_key = True
        self._check_subscript_write(node.target, node.lineno)
        self.generic_visit(node)

    def _check_dict_creation(self, name: str, value: ast.expr, line: int):
        """Detect d = {}, d = dict(), d = {"k": v, ...}."""
        initial_keys: list[str] = []
        is_creation = False

        if isinstance(value, ast.Dict):
            is_creation = True
            for k in value.keys:
                sk = _get_str_key(k) if k else None
                if sk:
                    initial_keys.append(sk)
            # Collect dict literal for schema drift
            if (
                all(
                    isinstance(k, ast.Constant) and isinstance(k.value, str)
                    for k in value.keys
                    if k is not None
                )
                and len(value.keys) >= 3
            ):
                keys = [k.value for k in value.keys if isinstance(k, ast.Constant)]
                self._dict_literals.append(
                    {
                        "file": self.filepath,
                        "line": line,
                        "keys": frozenset(keys),
                    }
                )
        elif (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "dict"
        ):
            is_creation = True
            for kw in value.keywords:
                if kw.arg:
                    initial_keys.append(kw.arg)

        if is_creation:
            td = self._track(
                name, line, locally_created=True, initial_keys=initial_keys
            )
            # Store as class dict if it's self.x
            if name.startswith("self.") and self._in_init_or_setup:
                self._class_dicts[name] = td

    def _check_subscript_write(self, target: ast.expr, line: int):
        """Handle d["key"] = val or d["key"] += val."""
        if not isinstance(target, ast.Subscript):
            return
        name = _get_name(target.value)
        if not name:
            return
        key = _get_str_key(target.slice)
        td = self._get_tracked(name)
        if td is None:
            return
        if key:
            td.writes[key].append(line)
        else:
            td.has_dynamic_key = True

    # -- Dict reads --

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.ctx, ast.Load):
            name = _get_name(node.value)
            if name:
                td = self._get_tracked(name)
                if td:
                    key = _get_str_key(node.slice)
                    if key:
                        td.reads[key].append(node.lineno)
                    else:
                        td.has_dynamic_key = True
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            if isinstance(target, ast.Subscript):
                name = _get_name(target.value)
                if name:
                    td = self._get_tracked(name)
                    if td:
                        key = _get_str_key(target.slice)
                        if key:
                            td.reads[key].append(target.lineno)
                        else:
                            td.has_dynamic_key = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        _record_call_interactions(self, node)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return):
        if node.value:
            _mark_returned_or_passed(self, node.value)
        self.generic_visit(node)

    visit_Yield = visit_Return
    visit_YieldFrom = visit_Return

    def visit_Compare(self, node: ast.Compare) -> None:
        """Handle "key" in d."""
        for i, op in enumerate(node.ops):
            if isinstance(op, ast.In | ast.NotIn):
                comparator = node.comparators[i]
                name = _get_name(comparator)
                if name:
                    td = self._get_tracked(name)
                    if td:
                        # The left side of `in` for the first op is node.left
                        left = node.left if i == 0 else node.comparators[i - 1]
                        key = _get_str_key(left)
                        if key:
                            td.reads[key].append(node.lineno)
        self.generic_visit(node)

    def visit_For(self, node: ast.For):
        """Handle `for x in d` — bulk read."""
        name = _get_name(node.iter)
        if name:
            td = self._get_tracked(name)
            if td:
                td.bulk_read = True
        self.generic_visit(node)

    def visit_Starred(self, node: ast.Starred):
        """Handle {**d} or func(*d)."""
        name = _get_name(node.value)
        if name:
            td = self._get_tracked(name)
            if td:
                td.has_star_unpack = True
        self.generic_visit(node)

    # -- Dict literal collection (standalone, non-assigned) --

    def visit_Dict(self, node: ast.Dict) -> None:
        """Collect dict literals for schema drift analysis."""
        if (
            all(
                isinstance(k, ast.Constant) and isinstance(k.value, str)
                for k in node.keys
                if k is not None
            )
            and len(node.keys) >= 3
            and all(k is not None for k in node.keys)
        ):
            keys = frozenset(k.value for k in node.keys if isinstance(k, ast.Constant))
            self._dict_literals.append(
                {
                    "file": self.filepath,
                    "line": node.lineno,
                    "keys": keys,
                }
            )
        self.generic_visit(node)
