"""DictKeyVisitor — AST visitor tracking dict key writes/reads per scope."""

from __future__ import annotations

import ast

from .dict_keys import TrackedDict, _CONFIG_NAMES, _get_name, _get_str_key, _BULK_READ_METHODS, _levenshtein, _is_singular_plural


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

    def _track(self, name: str, line: int, *, locally_created: bool,
               initial_keys: list[str] | None = None) -> TrackedDict:
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

    def _mark_returned_or_passed(self, node: ast.expr):
        """Mark a dict as returned or passed to a function."""
        # Handle tuples: return (a, b) or func(a, b)
        if isinstance(node, ast.Tuple):
            for elt in node.elts:
                self._mark_returned_or_passed(elt)
            return
        name = _get_name(node)
        if name:
            td = self._get_tracked(name)
            if td:
                td.returned_or_passed = True

    # -- Scope management --

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        prev_init = self._in_init_or_setup
        self._in_init_or_setup = node.name in ("__init__", "setUp", "setup")
        self._scopes.append({})
        self.generic_visit(node)
        scope = self._scopes.pop()
        self._analyze_scope(scope, node.name)
        self._in_init_or_setup = prev_init

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef):
        prev_class_dicts = self._class_dicts
        self._class_dicts = {}
        self.generic_visit(node)
        self._analyze_scope(self._class_dicts, f"class {node.name}", is_class=True)
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
            if all(isinstance(k, ast.Constant) and isinstance(k.value, str)
                   for k in value.keys if k is not None) and len(value.keys) >= 3:
                keys = [k.value for k in value.keys if isinstance(k, ast.Constant)]
                self._dict_literals.append({
                    "file": self.filepath, "line": line,
                    "keys": frozenset(keys),
                })
        elif (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
              and value.func.id == "dict"):
            is_creation = True
            for kw in value.keywords:
                if kw.arg:
                    initial_keys.append(kw.arg)

        if is_creation:
            td = self._track(name, line, locally_created=True,
                             initial_keys=initial_keys)
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
        # Check method calls on tracked dicts: d.get("key"), d.update({...}), etc.
        if isinstance(node.func, ast.Attribute):
            name = _get_name(node.func.value)
            method = node.func.attr
            if name:
                td = self._get_tracked(name)
                if td:
                    if method in ("get", "pop", "__getitem__", "__contains__"):
                        if node.args:
                            key = _get_str_key(node.args[0])
                            if key:
                                td.reads[key].append(node.lineno)
                            else:
                                td.has_dynamic_key = True
                    elif method == "setdefault":
                        if node.args:
                            key = _get_str_key(node.args[0])
                            if key:
                                td.reads[key].append(node.lineno)
                                td.writes[key].append(node.lineno)
                            else:
                                td.has_dynamic_key = True
                    elif method == "update":
                        # d.update({"k": v}) or d.update(k=v)
                        if node.args and isinstance(node.args[0], ast.Dict):
                            for k in node.args[0].keys:
                                sk = _get_str_key(k) if k else None
                                if sk:
                                    td.writes[sk].append(node.lineno)
                                elif k is None:
                                    td.has_dynamic_key = True
                        for kw in node.keywords:
                            if kw.arg:
                                td.writes[kw.arg].append(node.lineno)
                            else:
                                td.has_dynamic_key = True  # **kwargs
                    elif method in _BULK_READ_METHODS:
                        td.bulk_read = True

        # Check if a tracked dict is passed as argument (mark as escaped)
        for arg in node.args:
            self._mark_returned_or_passed(arg)
        for kw in node.keywords:
            if kw.arg is None:  # **d
                name = _get_name(kw.value)
                if name:
                    td = self._get_tracked(name)
                    if td:
                        td.has_star_unpack = True
            else:
                self._mark_returned_or_passed(kw.value)

        self.generic_visit(node)

    def visit_Return(self, node: ast.Return):
        if node.value:
            self._mark_returned_or_passed(node.value)
            # Also handle return {"k": v, ...} — not a tracked dict, but
            # handle return d where d is tracked
        self.generic_visit(node)

    def visit_Yield(self, node: ast.Yield):
        if node.value:
            self._mark_returned_or_passed(node.value)
        self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom):
        if node.value:
            self._mark_returned_or_passed(node.value)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        """Handle "key" in d."""
        for i, op in enumerate(node.ops):
            if isinstance(op, (ast.In, ast.NotIn)):
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
        if (all(isinstance(k, ast.Constant) and isinstance(k.value, str)
                for k in node.keys if k is not None)
                and len(node.keys) >= 3
                and all(k is not None for k in node.keys)):
            keys = frozenset(k.value for k in node.keys if isinstance(k, ast.Constant))
            self._dict_literals.append({
                "file": self.filepath, "line": node.lineno,
                "keys": keys,
            })
        self.generic_visit(node)

    # -- Scope analysis --

    def _analyze_scope(self, scope: dict[str, TrackedDict], func_name: str,
                       *, is_class: bool = False):
        """Analyze a completed scope for dict key issues."""
        for td in scope.values():
            if not td.locally_created:
                continue

            # Determine if dead-write warnings should be suppressed
            suppress_dead = (
                td.returned_or_passed
                or td.has_dynamic_key
                or td.has_star_unpack
                or td.bulk_read
                or any(td.name.lower().endswith(n) or td.name.lower() == n
                       for n in _CONFIG_NAMES)
                or (not is_class and func_name in ("__init__", "setUp", "setup"))
                or sum(len(v) for v in td.writes.values()) < 3
            )

            written_keys = set(td.writes.keys())
            read_keys = set(td.reads.keys())

            # Dead writes: written but never read
            dead_keys = written_keys - read_keys
            if not suppress_dead:
                for key in sorted(dead_keys):
                    lines = td.writes[key]
                    self._findings.append({
                        "file": self.filepath, "kind": "dead_write",
                        "variable": td.name, "key": key,
                        "line": lines[0], "func": func_name,
                        "tier": 3, "confidence": "medium",
                        "summary": (f'Dict key "{key}" written to `{td.name}` '
                                    f'at line {lines[0]} but never read'),
                        "detail": f"in {func_name}()",
                    })

            # Phantom reads: read but never written (on locally-created dict)
            phantom_keys = read_keys - written_keys
            for key in sorted(phantom_keys):
                lines = td.reads[key]
                self._findings.append({
                    "file": self.filepath, "kind": "phantom_read",
                    "variable": td.name, "key": key,
                    "line": lines[0], "func": func_name,
                    "tier": 2, "confidence": "high",
                    "summary": (f'Dict key "{key}" read at line {lines[0]} '
                                f'but never written to `{td.name}`'),
                    "detail": (f"Created at line {td.created_line} in "
                               f"{func_name}() — will raise KeyError or "
                               f"return None via .get()"),
                })

            # Near-miss: dead write key ≈ phantom read key
            for dk in sorted(dead_keys):
                for pk in sorted(phantom_keys):
                    dist = _levenshtein(dk, pk)
                    is_sp = _is_singular_plural(dk, pk)
                    if dist <= 2 or is_sp:
                        write_line = td.writes[dk][0]
                        read_line = td.reads[pk][0]
                        self._findings.append({
                            "file": self.filepath, "kind": "near_miss",
                            "variable": td.name, "key": f"{dk}~{pk}",
                            "line": write_line, "func": func_name,
                            "tier": 2, "confidence": "high",
                            "summary": (f'Possible key typo: "{dk}" vs "{pk}" '
                                        f'on dict `{td.name}` in {func_name}()'),
                            "detail": (f'Written: "{dk}" at line {write_line}, '
                                       f'Read: "{pk}" at line {read_line} '
                                       f'— edit distance {dist}'),
                        })

            # Overwritten keys: same key assigned twice with no read between
            for key, write_lines in td.writes.items():
                if len(write_lines) < 2:
                    continue
                read_lines = td.reads.get(key, [])
                for i in range(len(write_lines) - 1):
                    w1, w2 = write_lines[i], write_lines[i + 1]
                    # Check if any read of this key occurs between w1 and w2
                    has_read_between = any(w1 < r <= w2 for r in read_lines)
                    if not has_read_between:
                        self._findings.append({
                            "file": self.filepath, "kind": "overwritten_key",
                            "variable": td.name, "key": key,
                            "line": w2, "func": func_name,
                            "tier": 3, "confidence": "medium",
                            "summary": (f'Dict key "{key}" overwritten on `{td.name}` '
                                        f'at line {w2} (previously set at line {w1}, '
                                        f'never read between)'),
                            "detail": f"in {func_name}()",
                        })
