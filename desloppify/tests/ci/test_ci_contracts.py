from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")


REPO_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
INTEGRATION_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "integration.yml"
PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "python-publish.yml"
CI_PLAN = REPO_ROOT / "docs" / "ci_plan.md"
MAKEFILE = REPO_ROOT / "Makefile"
README = REPO_ROOT / "README.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _on_block(data: dict) -> dict:
    # PyYAML parses "on" as True under YAML 1.1 rules.
    return data.get("on", data.get(True, {}))


def _run_commands(job: dict) -> list[str]:
    return [step["run"] for step in job.get("steps", []) if "run" in step]


def _step_names(job: dict) -> list[str]:
    return [step.get("name", "") for step in job.get("steps", [])]


def _optional_dependencies() -> dict[str, list[str]]:
    doc = tomllib.loads(PYPROJECT.read_text())
    optional = doc.get("project", {}).get("optional-dependencies", {})
    return {str(key): list(value) for key, value in optional.items()}


def test_ci_workflow_jobs_are_bound_to_make_targets() -> None:
    ci = _load_yaml(CI_WORKFLOW)
    jobs = ci["jobs"]
    expected = {
        "lint": "make lint",
        "typecheck": "make typecheck",
        "arch-contracts": "make arch",
        "ci-contracts": "make ci-contracts",
        "tests-core": "make tests PYTEST_XML=pytest-core.xml",
        "tests-full": "make tests-full PYTEST_XML=pytest-full.xml",
        "package-smoke": "make package-smoke",
    }

    assert set(expected).issubset(jobs), "CI workflow missing required jobs."

    for job_name, expected_cmd in expected.items():
        job = jobs[job_name]
        runs = _run_commands(job)
        assert any(expected_cmd in run for run in runs), (
            f"{job_name} must execute `{expected_cmd}` for local/CI parity."
        )
        assert any(step.get("uses") == "actions/setup-python@v5" for step in job["steps"]), (
            f"{job_name} should use actions/setup-python@v5."
        )


def test_ci_workflow_has_expected_triggers() -> None:
    ci = _load_yaml(CI_WORKFLOW)
    on_block = _on_block(ci)
    assert "pull_request" in on_block
    assert on_block.get("push", {}).get("branches") == ["main"]


def test_integration_workflow_uses_deterministic_roslyn_path() -> None:
    wf = _load_yaml(INTEGRATION_WORKFLOW)
    on_block = _on_block(wf)
    assert "schedule" in on_block
    assert "workflow_dispatch" in on_block

    job = wf["jobs"]["roslyn-integration"]
    assert (
        job["env"]["DESLOPPIFY_TEST_CSHARP_ROSLYN_CMD"]
        == "python .github/scripts/roslyn_stub.py"
    )
    assert any(step.get("uses") == "actions/setup-dotnet@v4" for step in job["steps"])
    assert any("make integration-roslyn" in run for run in _run_commands(job))


def test_publish_workflow_keeps_release_safety_gates() -> None:
    wf = _load_yaml(PUBLISH_WORKFLOW)
    on_block = _on_block(wf)
    assert on_block.get("release", {}).get("types") == ["published"]
    assert on_block.get("push", {}).get("tags") == ["v*"]
    assert "workflow_dispatch" in on_block
    assert "push" in on_block and "branches" not in on_block.get("push", {})

    publish_job = wf["jobs"]["publish"]
    names = _step_names(publish_job)
    assert "Validate tag matches package version" in names
    assert "Check if version exists on PyPI" in names
    assert "Run packaging smoke gate" in names
    assert "Publish to PyPI" in names
    assert any("make package-smoke" in run for run in _run_commands(publish_job))


def test_makefile_contains_ci_gate_targets() -> None:
    text = MAKEFILE.read_text()
    targets = set(re.findall(r"^([a-zA-Z0-9_-]+):", text, flags=re.MULTILINE))
    expected = {
        "lint",
        "typecheck",
        "arch",
        "ci-contracts",
        "integration-roslyn",
        "tests",
        "tests-full",
        "package-smoke",
        "ci-fast",
        "ci",
    }
    assert expected.issubset(targets)


def test_readme_optional_extras_exist_in_pyproject() -> None:
    readme = README.read_text()
    referenced = set(re.findall(r"desloppify\[([a-zA-Z0-9_-]+)\]", readme))
    optional = _optional_dependencies()
    missing = sorted(extra for extra in referenced if extra not in optional)
    assert not missing, (
        "README references optional extras that are not defined in pyproject.toml: "
        f"{missing}"
    )


def test_full_extra_includes_all_optional_dependency_groups() -> None:
    optional = _optional_dependencies()
    full = set(optional.get("full", []))
    missing_dependencies: dict[str, list[str]] = {}
    for extra, deps in optional.items():
        if extra == "full":
            continue
        extra_missing = sorted(dep for dep in deps if dep not in full)
        if extra_missing:
            missing_dependencies[extra] = extra_missing

    assert not missing_dependencies, (
        "Optional extras must stay represented in [full] so README install guidance "
        f"does not drift: {missing_dependencies}"
    )


def test_ci_plan_required_checks_match_ci_workflow() -> None:
    ci = _load_yaml(CI_WORKFLOW)
    expected_contexts = [
        f"CI / {name}"
        for name in (
            "lint",
            "typecheck",
            "arch-contracts",
            "ci-contracts",
            "tests-core",
            "tests-full",
            "package-smoke",
        )
    ]

    doc = CI_PLAN.read_text()
    section = doc.split("Required status checks:", 1)[1].split("Pull request policy:", 1)[0]
    documented = re.findall(r"- `([^`]+)`", section)

    assert documented == expected_contexts
    for context in expected_contexts:
        job_name = context.split("CI / ", 1)[1]
        assert job_name in ci["jobs"], f"{context} has no matching CI workflow job."
