"""Direct contract tests for plan command and compatibility-surface boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_app_command_modules_avoid_engine_plan_compat_facade() -> None:
    root = _repo_root()
    app_cmd_dir = root / "app" / "commands"
    offenders: list[str] = []
    for path in app_cmd_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        rel = str(path.relative_to(root))
        has_compat_import = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if (node.module or "") == "desloppify.engine.plan":
                    has_compat_import = True
                    break
                if (node.module or "") == "desloppify.engine" and any(
                    alias.name == "plan" for alias in node.names
                ):
                    has_compat_import = True
                    break
            elif isinstance(node, ast.Import):
                if any(alias.name == "desloppify.engine.plan" for alias in node.names):
                    has_compat_import = True
                    break
        if has_compat_import:
            offenders.append(rel)
    assert offenders == []


def test_plan_command_modules_avoid_legacy_plan_api_hub() -> None:
    root = _repo_root()
    plan_cmd_dir = root / "app" / "commands" / "plan"
    offenders: list[str] = []
    for path in plan_cmd_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from desloppify.app.commands.plan.plan_api import" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_plan_command_modules_avoid_legacy_plan_queue_facade() -> None:
    root = _repo_root()
    plan_cmd_dir = root / "app" / "commands" / "plan"
    offenders: list[str] = []
    for path in plan_cmd_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "desloppify.engine.plan_queue":
                    offenders.append(rel)
                    break
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name
                    if mod == "desloppify.engine.plan_queue":
                        offenders.append(rel)
                        break
    assert offenders == []


def test_plan_cmd_routes_through_capability_packages() -> None:
    root = _repo_root()
    cmd_path = root / "app" / "commands" / "plan" / "cmd.py"
    text = cmd_path.read_text(encoding="utf-8")
    assert "from desloppify.app.commands.plan.cluster import cmd_cluster_dispatch" in text
    assert "from desloppify.app.commands.plan.commit_log import cmd_commit_log_dispatch" in text
    assert "from desloppify.app.commands.plan.override import (" in text
    assert "from desloppify.app.commands.plan.triage.command import cmd_plan_triage" in text


def test_development_philosophy_documents_passthrough_shim_exception() -> None:
    root = _repo_root()
    text = (root.parent / "dev" / "DEVELOPMENT_PHILOSOPHY.md").read_text(
        encoding="utf-8"
    )
    assert "Functionality compatibility shims are disallowed by default" in text
    assert "temporary passthrough-only compatibility facades" in text
    assert "owner + removal issue/date" in text
