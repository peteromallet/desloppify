"""Dynamic import discovery for Python dependency hints."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from .deps_resolution import resolve_absolute_import, try_resolve_path

logger = logging.getLogger(__name__)


def _string_literal(node: ast.AST) -> str | None:
    """Return a string constant without evaluating arbitrary source expressions."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _import_module_bindings(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Return local names bound to the importlib module and import_module function."""

    module_bindings: set[str] = set()
    function_bindings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib" or alias.name.startswith("importlib."):
                    module_bindings.add(alias.asname or alias.name.partition(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    function_bindings.add(alias.asname or alias.name)
    return module_bindings, function_bindings


def _is_import_module_call(
    node: ast.Call,
    *,
    module_bindings: set[str],
    function_bindings: set[str],
) -> bool:
    """Return whether *node* is a call through a known importlib binding."""

    func = node.func
    return bool(
        node.args
        and (
            (
                isinstance(func, ast.Attribute)
                and func.attr == "import_module"
                and isinstance(func.value, ast.Name)
                and func.value.id in module_bindings
            )
            or (isinstance(func, ast.Name) and func.id in function_bindings)
        )
    )


def _mapping_module_specs(value: ast.AST) -> set[str]:
    """Extract first tuple/list members from a static lazy-export mapping."""

    if not isinstance(value, ast.Dict):
        return set()

    module_specs: set[str] = set()
    for entry in value.values:
        if isinstance(entry, ast.Tuple | ast.List) and entry.elts:
            spec = _string_literal(entry.elts[0])
        else:
            spec = _string_literal(entry)
        if spec:
            module_specs.add(spec)
    return module_specs


def _lazy_export_mappings(tree: ast.Module) -> dict[str, set[str]]:
    """Collect module-level literal mappings used by lazy package exports."""

    mappings: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        module_specs = _mapping_module_specs(value)
        if not module_specs:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                mappings[target.id] = module_specs
    return mappings


def _unpacked_mapping_binding(
    node: ast.AST,
    mappings: dict[str, set[str]],
) -> tuple[str, str] | None:
    """Return ``(local_name, mapping_name)`` for ``name, _ = MAPPING[...]``."""

    if isinstance(node, ast.Assign):
        targets = node.targets
        value = node.value
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        targets = [node.target]
        value = node.value
    else:
        return None
    if not (
        isinstance(value, ast.Subscript)
        and isinstance(value.value, ast.Name)
        and value.value.id in mappings
    ):
        return None
    for target in targets:
        if isinstance(target, ast.Tuple | ast.List) and target.elts:
            first = target.elts[0]
            if isinstance(first, ast.Name):
                return first.id, value.value.id
    return None


def _lazy_export_variable(argument: ast.AST) -> str | None:
    """Return the selected module variable for ``f\"{__name__}.{module}\"``."""

    if not isinstance(argument, ast.JoinedStr) or len(argument.values) != 3:
        return None
    package, separator, module = argument.values
    if not (
        isinstance(package, ast.FormattedValue)
        and isinstance(package.value, ast.Name)
        and package.value.id == "__name__"
        and _string_literal(separator) == "."
        and isinstance(module, ast.FormattedValue)
        and isinstance(module.value, ast.Name)
    ):
        return None
    return module.value.id


def _lazy_export_targets(
    tree: ast.Module,
    py_file: Path,
    *,
    module_bindings: set[str],
    function_bindings: set[str],
) -> set[str]:
    """Resolve child modules selected from literal package lazy-export mappings."""

    mappings = _lazy_export_mappings(tree)
    if not mappings:
        return set()

    targets: set[str] = set()
    for scope in ast.walk(tree):
        if not isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        bindings = {
            binding[0]: binding[1]
            for node in ast.walk(scope)
            if (binding := _unpacked_mapping_binding(node, mappings)) is not None
        }
        if not bindings:
            continue
        for node in ast.walk(scope):
            if not isinstance(node, ast.Call) or not _is_import_module_call(
                node,
                module_bindings=module_bindings,
                function_bindings=function_bindings,
            ):
                continue
            module_variable = _lazy_export_variable(node.args[0])
            mapping_name = bindings.get(module_variable)
            if mapping_name is None:
                continue
            for module_spec in mappings[mapping_name]:
                candidate = py_file.parent.joinpath(*module_spec.split("."))
                resolved = try_resolve_path(candidate)
                if resolved:
                    targets.add(resolved)
    return targets


def _is_explicit_legacy_module_alias(node: ast.Call) -> bool:
    """Recognize physical ``install_legacy_module_alias(__name__, target)`` wrappers."""

    func = node.func
    is_alias_installer = (
        isinstance(func, ast.Name) and func.id == "install_legacy_module_alias"
    ) or (
        isinstance(func, ast.Attribute) and func.attr == "install_legacy_module_alias"
    )
    return bool(
        is_alias_installer
        and len(node.args) >= 2
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "__name__"
        and _string_literal(node.args[1])
    )


def find_python_dynamic_imports(path: Path, extensions: list[str]) -> set[str]:
    """Find module files entered through dynamic imports or explicit alias wrappers."""

    del extensions
    targets: set[str] = set()
    for py_file in path.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            logger.debug(
                "Skipping unreadable file %s in dynamic import scan: %s",
                py_file,
                exc,
            )
            continue
        module_bindings, function_bindings = _import_module_bindings(tree)
        for node in tree.body:
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and _is_explicit_legacy_module_alias(node.value)
            ):
                targets.add(str(py_file.resolve()))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_import_module_call(
                node,
                module_bindings=module_bindings,
                function_bindings=function_bindings,
            ):
                continue
            spec = _string_literal(node.args[0])
            if spec is None:
                continue
            resolved = resolve_absolute_import(spec, path)
            if resolved:
                targets.add(resolved)
            else:
                targets.add(spec)
        targets.update(
            _lazy_export_targets(
                tree,
                py_file,
                module_bindings=module_bindings,
                function_bindings=function_bindings,
            )
        )
    return targets


__all__ = ["find_python_dynamic_imports"]
