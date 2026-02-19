"""Focused unit tests for context_holistic.selection helpers."""

from __future__ import annotations

from types import SimpleNamespace

from desloppify.intelligence.review.context_holistic import selection as selection_mod


def test_select_holistic_files_prefers_explicit_files(tmp_path):
    lang = SimpleNamespace(file_finder=lambda _path: ["ignored.py"])
    explicit = ["alpha.py", "beta.py"]

    selected = selection_mod.select_holistic_files(tmp_path, lang, explicit)

    assert selected == explicit


def test_select_holistic_files_uses_lang_file_finder(tmp_path):
    seen: dict[str, object] = {}

    def _finder(path):
        seen["path"] = path
        return ["picked.py"]

    lang = SimpleNamespace(file_finder=_finder)

    selected = selection_mod.select_holistic_files(tmp_path, lang, None)

    assert selected == ["picked.py"]
    assert seen["path"] == tmp_path


def test_sibling_behavior_context_reports_shared_pattern_outlier(tmp_path):
    svc_dir = tmp_path / "service"
    files = {
        str(svc_dir / "alpha.py"): "import shared_one\nimport shared_two\n",
        str(svc_dir / "beta.py"): "import shared_one\nimport shared_two\n",
        str(svc_dir / "gamma.py"): "import shared_two\n",
    }

    context = selection_mod._sibling_behavior_context(files, base_path=tmp_path)

    svc = context["service/"]
    assert "shared_one" in svc["shared_patterns"]
    assert svc["shared_patterns"]["shared_one"]["count"] == 2
    assert svc["shared_patterns"]["shared_one"]["total"] == 3
    assert svc["outliers"][0]["file"] == "service/gamma.py"
    assert "shared_one" in svc["outliers"][0]["missing"]


def test_testing_context_includes_high_importer_untested_file(tmp_path):
    target = tmp_path / "pkg" / "module.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def run():\n    return 1\n")

    lang = SimpleNamespace(
        dep_graph={
            str(target.resolve()): {
                "importers": {"consumer_a.py", "consumer_b.py", "consumer_c.py"}
            }
        }
    )
    state = {
        "findings": {
            "tc-1": {
                "detector": "test_coverage",
                "status": "open",
                "file": str(target),
            }
        }
    }
    file_contents = {str(target): target.read_text()}

    context = selection_mod._testing_context(lang, state, file_contents)

    assert context["total_files"] == 1
    assert context["critical_untested"] == [{"file": str(target), "importers": 3}]

