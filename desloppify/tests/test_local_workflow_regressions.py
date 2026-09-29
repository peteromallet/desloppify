"""Synthetic regressions for source discovery, security batches and queue skips.

Run with a Python environment containing the patched desloppify installation.
All fixture files are temporary; Bandit process execution is mocked throughout.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from desloppify.base.discovery.source import set_exclusions
from desloppify.base.runtime_state import runtime_scope
from desloppify.engine._work_queue import snapshot
from desloppify.languages.python import _security
from desloppify.languages.python.detectors import bandit_adapter as bandit
from desloppify.languages.python.detectors import deps
from desloppify.languages.python.detectors import deps_dynamic as dynamic
from desloppify.languages.python.detectors import deps_resolution as resolution


class SyntheticProject(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix="desloppify-regression-"))
        self.root = Path(directory).resolve()
        runtime = self.enterContext(runtime_scope())
        runtime.project_root = self.root

    def write(self, relative, content="value = 1\n"):
        source = self.root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(content)
        return source


class DynamicDiscoveryTests(SyntheticProject):
    def test_exclusions_prune_directories_virtualenvs_and_individual_files(self):
        active = self.write("source/loader.py", "import importlib\nimportlib.import_module('active_plugin')\n")
        self.write("source/vendor/loader.py", "import importlib\nimportlib.import_module('vendor_plugin')\n")
        self.write("source/.venv-local/loader.py", "import importlib\nimportlib.import_module('venv_plugin')\n")
        self.write("source/ignored.py", "import importlib\nimportlib.import_module('ignored_plugin')\n")
        set_exclusions(["source/vendor", "source/ignored.py"])
        original_read = Path.read_text
        reads = []

        def read_selected(path, *args, **kwargs):
            self.assertEqual(path, active)
            reads.append(path)
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", read_selected):
            targets = dynamic.find_python_dynamic_imports(self.root / "source", [".py"])
        self.assertEqual(targets, {"active_plugin"})
        self.assertEqual(reads, [active])

    def test_relative_discovery_paths_resolve_against_project_root(self):
        self.write("source/loader.py", "import importlib\nimportlib.import_module('active_plugin')\n")
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(elsewhere)
            targets = dynamic.find_python_dynamic_imports(self.root / "source", [".py"])
        finally:
            os.chdir(previous)
        self.assertEqual(targets, {"active_plugin"})


class FlatScriptResolutionTests(SyntheticProject):
    def test_flat_script_imports_build_exact_forward_and_reverse_graph_edges(self):
        main = self.write("scripts/main.py", "import helper\nfrom helper import value\n")
        helper = self.write("scripts/helper.py")
        graph = deps.build_dep_graph(self.root)
        self.assertEqual(graph[str(main)]["imports"], {str(helper)})
        self.assertEqual(graph[str(helper)]["importers"], {str(main)})
        self.assertEqual(graph[str(main)]["import_count"], 1)
        self.assertEqual(graph[str(helper)]["importer_count"], 1)

    def test_project_root_lookup_precedes_siblings_when_scan_root_is_nested(self):
        self.write("component/scripts/main.py", "import helper\n")
        self.write("component/scripts/helper.py")
        helper = self.write("helper.py")
        self.assertEqual(
            resolution.resolve_python_import("helper", "component/scripts/main.py", self.root / "component"),
            str(helper),
        )

    def test_flat_script_sibling_import_resolves(self):
        self.write("scripts/main.py", "import helper\n")
        helper = self.write("scripts/helper.py")
        self.assertEqual(
            resolution.resolve_python_import("helper", "scripts/main.py", self.root),
            str(helper),
        )

    def test_project_root_import_keeps_precedence(self):
        self.write("scripts/main.py", "import helper\n")
        self.write("scripts/helper.py")
        helper = self.write("helper.py")
        self.assertEqual(
            resolution.resolve_python_import("helper", "scripts/main.py", self.root),
            str(helper),
        )

    def test_regular_packages_require_explicit_relative_import(self):
        self.write("package/__init__.py", "")
        self.write("package/main.py", "import helper\n")
        helper = self.write("package/helper.py")
        self.assertIsNone(resolution.resolve_python_import("helper", "package/main.py", self.root))
        self.assertEqual(
            resolution.resolve_python_import(".helper", "package/main.py", self.root),
            str(helper),
        )

    def test_flat_script_from_import_resolves_package_and_submodule(self):
        self.write("scripts/main.py", "from plugins import helper\n")
        package = self.write("scripts/plugins/__init__.py", "")
        helper = self.write("scripts/plugins/helper.py")
        self.assertEqual(
            set(resolution.resolve_python_from_import("plugins", "helper", "scripts/main.py", self.root)),
            {str(package), str(helper)},
        )
        self.assertEqual(resolution.resolve_python_import("plugins.helper", "scripts/main.py", self.root), str(helper))
        self.assertIsNone(resolution.resolve_python_import("missing", "scripts/main.py", self.root))


def bandit_output(filename, *, finding=False):
    result = {
        "results": [],
        "metrics": {filename: {}, "_totals": {}},
    }
    if finding:
        result["results"].append({
            "filename": filename,
            "test_id": "B602",
            "test_name": "subprocess_popen_with_shell_equals_true",
            "issue_severity": "HIGH",
            "issue_confidence": "HIGH",
            "issue_text": "Synthetic shell invocation.",
            "line_number": 1,
            "code": "subprocess.run(command, shell=True)",
            "more_info": "https://example.invalid/synthetic-bandit-finding",
        })
    return SimpleNamespace(stdout=json.dumps(result), returncode=1 if finding else 0)


class SecurityTargetTests(SyntheticProject):
    def test_security_phase_passes_discovered_files_and_policy_options(self):
        selected = ["source/alpha.py", "source/beta.py"]
        result = bandit.BanditScanResult([], 2, bandit.BanditRunStatus("ok"))
        with (
            patch.object(_security, "scan_root_from_files", return_value=self.root),
            patch.object(_security, "collect_exclude_dirs", return_value=[str(self.root / "vendor")]),
            patch.object(_security, "_load_bandit_skip_tests", return_value=["B101"]),
            patch.object(_security, "detect_with_bandit", return_value=result) as detect,
        ):
            security = _security.detect_python_security(selected, None)
        detect.assert_called_once_with(
            self.root,
            None,
            exclude_dirs=[str(self.root / "vendor")],
            skip_tests=["B101"],
            files=selected,
        )
        self.assertEqual(security.files_scanned, 2)

    def test_discovered_targets_are_absolute_deduplicated_and_nonrecursive(self):
        calls = []

        def run(command, **options):
            calls.append((command, options))
            return bandit_output(command[-1])

        with patch.object(bandit.subprocess, "run", side_effect=run):
            result = bandit.detect_with_bandit(self.root, None, files=["beta.py", "alpha.py", "alpha.py"])
        self.assertEqual(len(calls), 1)
        command, _ = calls[0]
        self.assertNotIn("-r", command)
        self.assertEqual(command[-2:], [str(self.root / "alpha.py"), str(self.root / "beta.py")])
        self.assertNotIn(str(self.root), command)
        self.assertEqual(result.status.state, "ok")

    def test_empty_discovery_does_not_start_a_process(self):
        with patch.object(bandit.subprocess, "run") as run:
            result = bandit.detect_with_bandit(self.root, None, files=[])
        run.assert_not_called()
        self.assertEqual(result.files_scanned, 0)
        self.assertEqual(result.entries, [])
        self.assertEqual(result.status.state, "ok")

    def test_batched_targets_preserve_findings_and_scanned_counts(self):
        calls = []

        def run(command, **options):
            calls.append(command)
            return bandit_output(command[-1], finding=True)

        with (
            patch.object(bandit, "_TARGET_BYTES_PER_BATCH", 1),
            patch.object(bandit.subprocess, "run", side_effect=run),
        ):
            result = bandit.detect_with_bandit(self.root, None, files=["alpha.py", "beta.py"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("-r" not in command for command in calls))
        self.assertEqual(result.files_scanned, 2)
        self.assertEqual(len(result.entries), 2)
        self.assertEqual({entry["file"] for entry in result.entries}, {"alpha.py", "beta.py"})
        self.assertEqual(result.status.state, "ok")

    def test_failed_batch_keeps_partial_findings_and_reduced_coverage(self):
        calls = []

        def run(command, **options):
            calls.append(options["timeout"])
            if len(calls) == 2:
                raise subprocess.TimeoutExpired(command, options["timeout"])
            return bandit_output(command[-1], finding=True)

        with (
            patch.object(bandit, "_TARGET_BYTES_PER_BATCH", 1),
            patch.object(bandit.time, "monotonic", side_effect=[100, 101, 102]),
            patch.object(bandit.subprocess, "run", side_effect=run),
        ):
            result = bandit.detect_with_bandit(
                self.root, None, timeout=10, files=["alpha.py", "beta.py", "gamma.py"],
            )
        self.assertEqual(calls, [9, 8])
        self.assertEqual(result.files_scanned, 1)
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.status.state, "timeout")
        self.assertEqual(result.status.coverage().status, "reduced")

    def test_shared_deadline_stops_before_starting_another_batch(self):
        with (
            patch.object(bandit, "_TARGET_BYTES_PER_BATCH", 1),
            patch.object(bandit.time, "monotonic", side_effect=[100, 101, 115]),
            patch.object(bandit.subprocess, "run", side_effect=lambda command, **options: bandit_output(command[-1])) as run,
        ):
            result = bandit.detect_with_bandit(self.root, None, timeout=10, files=["alpha.py", "beta.py"])
        self.assertEqual(run.call_count, 1)
        self.assertEqual(result.files_scanned, 1)
        self.assertEqual(result.status.state, "timeout")

    def test_legacy_recursive_call_without_discovery_is_preserved(self):
        with patch.object(bandit.subprocess, "run", return_value=bandit_output(str(self.root / "alpha.py"))) as run:
            result = bandit.detect_with_bandit(self.root, None)
        command = run.call_args.args[0]
        self.assertIn("-r", command)
        self.assertEqual(command[-1], str(self.root))
        self.assertEqual(result.files_scanned, 1)


class SkippedSyntheticReviewTests(unittest.TestCase):
    def test_skip_affects_phase_partition_and_unskip_restores_item_without_state_changes(self):
        state = {"synthetic_marker": True}
        initial = {"id": "subjective::example", "initial_review": True}
        postflight = {"id": "subjective::another_example", "initial_review": False}
        plan = {"skipped": {initial["id"]: {}, postflight["id"]: {}}}
        with patch.object(snapshot, "build_subjective_items", return_value=[initial, postflight]):
            partitions = snapshot._subjective_partitions(state, scoped_issues={}, threshold=85, plan=plan)
            self.assertEqual(partitions, ([], []))
            plan["skipped"].clear()
            restored = snapshot._subjective_partitions(state, scoped_issues={}, threshold=85, plan=plan)
        self.assertEqual(restored, ([initial], [postflight]))
        self.assertEqual(state, {"synthetic_marker": True})


if __name__ == "__main__":
    unittest.main(verbosity=2)
