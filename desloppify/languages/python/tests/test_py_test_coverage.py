"""Tests for Python-specific static test coverage mapping."""

from desloppify.languages.python.test_coverage import (
    parse_test_import_specs,
    resolve_import_spec,
)


def test_resolve_import_spec_finds_unique_repository_source_root() -> None:
    production_files = {
        "backend/app/routers/alignment.py",
        "backend/app/services/sync_fix.py",
    }

    assert (
        resolve_import_spec(
            "app.routers.alignment",
            "backend/tests/test_alignment_router.py",
            production_files,
        )
        == "backend/app/routers/alignment.py"
    )
    assert (
        resolve_import_spec(
            "app.services.sync_fix",
            "backend/tests/test_sync_fix_service.py",
            production_files,
        )
        == "backend/app/services/sync_fix.py"
    )


def test_resolve_import_spec_rejects_ambiguous_source_roots() -> None:
    production_files = {
        "backend/app/services/sync_fix.py",
        "legacy/app/services/sync_fix.py",
    }

    assert (
        resolve_import_spec(
            "app.services.sync_fix",
            "tests/test_sync_fix_service.py",
            production_files,
        )
        is None
    )


def test_parse_test_import_specs_finds_dynamic_python_script_targets() -> None:
    content = """
import importlib.util
import runpy
from pathlib import Path

WORKER_PATH = Path(__file__).parents[1] / "cli" / "sync_worker.py"
spec = importlib.util.spec_from_file_location("sync_worker_test", WORKER_PATH)
runpy.run_path(str(Path(__file__).parents[2] / "launch.py"))
"""

    specs = parse_test_import_specs(content)

    assert "sync_worker.py" in specs
    assert "launch.py" in specs


def test_parse_test_import_specs_preserves_dynamic_script_path_suffix() -> None:
    content = """
import importlib.util
from pathlib import Path

HELPER_PATH = (
    Path(__file__).parents[2]
    / "backend"
    / "crusoe_runtime"
    / "crusoe_helper.py"
)
spec = importlib.util.spec_from_file_location("helper_test", HELPER_PATH)
"""

    assert (
        "backend/crusoe_runtime/crusoe_helper.py"
        in parse_test_import_specs(content)
    )


def test_resolve_import_spec_finds_unique_dynamic_python_script() -> None:
    production_files = {
        "backend/cli/sync_worker.py",
        "backend/app/services/sync_fix.py",
    }

    assert (
        resolve_import_spec(
            "sync_worker.py",
            "backend/tests/test_sync_worker.py",
            production_files,
        )
        == "backend/cli/sync_worker.py"
    )


def test_resolve_import_spec_prefers_exact_root_script_path() -> None:
    production_files = {
        "qwen.py",
        "backend/app/services/qwen.py",
    }

    assert (
        resolve_import_spec(
            "qwen.py",
            "backend/tests/test_qwen_captioner_scripts.py",
            production_files,
        )
        == "qwen.py"
    )


def test_resolve_import_spec_rejects_ambiguous_dynamic_python_script() -> None:
    production_files = {
        "backend/cli/sync_worker.py",
        "legacy/cli/sync_worker.py",
    }

    assert (
        resolve_import_spec(
            "sync_worker.py",
            "backend/tests/test_sync_worker.py",
            production_files,
        )
        is None
    )
