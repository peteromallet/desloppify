"""DictKeyVisitor — AST visitor tracking dict key writes/reads per scope."""

from __future__ import annotations

import ast

from desloppify.languages.python.detectors.dict_keys import (
    TrackedDict,
    _get_name,
    _get_str_key,
)

from .visitor_helpers import (
    analyze_scope_issues,
    mark_assignment_escape,
    mark_returned_or_passed,
    record_call_interactions,
)


class DictKeyVisitor(ast.NodeVisitor):
    """Walk a module AST, tracking dict key writes/reads per function scope."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._scopes: list[dict[str, TrackedDict]] = []
        self._class_dicts: dict[str, TrackedDict] = {}  # self.x dicts
        self._in_init_or_setup = False
        self._issues: list[dict] = []
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
        self._issues.extend(analyze_scope_issues(self, scope, node.name))
        self._in_init_or_setup = prev_init

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        prev_class_dicts = self._class_dicts
        self._class_dicts = {}
        self.generic_visit(node)
        self._issues.extend(
            analyze_scope_issues(
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
                tracked = self._check_dict_creation(name, node.value, node.lineno)
                if tracked is not None and isinstance(target, ast.Attribute):
                    tracked.returned_or_passed = True
        # Also check for subscript writes: d["key"] = val
        for target in node.targets:
            self._check_subscript_write(target, node.lineno)
        mark_assignment_escape(self, node.targets, node.value)
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

    def _check_dict_creation(
        self,
        name: str,
        value: ast.expr,
        line: int,
    ) -> TrackedDict | None:
        """Detect local dict literals, dict(), and dict(key=value) constructors."""
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
            and not value.args
            and all(keyword.arg is not None for keyword in value.keywords)
        ):
            is_creation = True
            for kw in value.keywords:
                initial_keys.append(kw.arg)

        if is_creation:
            td = self._track(
                name, line, locally_created=True, initial_keys=initial_keys
            )
            # Store as class dict if it's self.x
            if name.startswith("self.") and self._in_init_or_setup:
                self._class_dicts[name] = td
            return td
        return None

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
        record_call_interactions(self, node)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return):
        if node.value:
            mark_returned_or_passed(self, node.value)
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
