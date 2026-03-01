"""Tests for desloppify.engine.detectors.coupling — coupling analysis detectors."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from desloppify.engine.detectors.coupling import (
    detect_boundary_candidates,
    detect_coupling_violations,
    detect_cross_tool_imports,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fixed prefixes for all tests — simulate a /project/src layout.
SHARED_PREFIX = "/project/src/shared/"
TOOLS_PREFIX = "/project/src/tools/"


def _graph_entry(
    *,
    imports: set[str] | None = None,
    importer_count: int = 0,
    importers: list[str] | None = None,
) -> dict:
    """Build a minimal graph node dict."""
    return {
        "imports": imports or set(),
        "importer_count": importer_count,
        "importers": importers or [],
    }


def _write_file(path: Path, lines: int = 20) -> Path:
    """Write a dummy file with the given number of lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"line {i}" for i in range(lines)))
    return path


# ===================================================================
# detect_coupling_violations
# ===================================================================


class TestDetectCouplingViolations:
    """Tests for shared -> tools backwards coupling detection."""

    def test_finds_shared_to_tools_imports(self):
        """Shared files importing from tools are coupling violations."""
        graph = {
            f"{SHARED_PREFIX}utils.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}editor/helpers.ts"},
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_coupling_violations(
                Path("/project"), graph, SHARED_PREFIX, TOOLS_PREFIX
            )

        assert len(entries) == 1
        assert entries[0]["file"] == f"{SHARED_PREFIX}utils.ts"
        assert entries[0]["tool"] == "editor"
        assert entries[0]["direction"] == "shared\u2192tools"
        assert total_edges.eligible_edges == 1

    def test_counts_shared_to_shared_edges(self):
        """Shared -> shared imports count toward total_edges but not as violations."""
        graph = {
            f"{SHARED_PREFIX}a.ts": _graph_entry(
                imports={f"{SHARED_PREFIX}b.ts"},
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_coupling_violations(
                Path("/project"), graph, SHARED_PREFIX, TOOLS_PREFIX
            )

        assert entries == []
        assert total_edges.eligible_edges == 1  # shared->shared edge counted

    def test_returns_entries_and_total_edges(self):
        """Return tuple is (violation_entries, total_cross_boundary_edges)."""
        graph = {
            f"{SHARED_PREFIX}a.ts": _graph_entry(
                imports={
                    f"{TOOLS_PREFIX}editor/foo.ts",
                    f"{SHARED_PREFIX}b.ts",
                },
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_coupling_violations(
                Path("/project"), graph, SHARED_PREFIX, TOOLS_PREFIX
            )

        assert len(entries) == 1
        assert total_edges.eligible_edges == 2  # one shared->tools + one shared->shared

    def test_sorted_by_file_then_target(self):
        """Results are sorted by (file, target)."""
        graph = {
            f"{SHARED_PREFIX}z.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}alpha/x.ts"},
            ),
            f"{SHARED_PREFIX}a.ts": _graph_entry(
                imports={
                    f"{TOOLS_PREFIX}beta/y.ts",
                    f"{TOOLS_PREFIX}alpha/w.ts",
                },
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_coupling_violations(
                Path("/project"), graph, SHARED_PREFIX, TOOLS_PREFIX
            )

        assert len(entries) == 3
        # a.ts targets should be sorted, then z.ts
        assert entries[0]["file"] == f"{SHARED_PREFIX}a.ts"
        assert entries[-1]["file"] == f"{SHARED_PREFIX}z.ts"
        # Within a.ts, sorted by target
        targets_for_a = [
            e["target"] for e in entries if e["file"] == f"{SHARED_PREFIX}a.ts"
        ]
        assert targets_for_a == sorted(targets_for_a)

    def test_tools_importing_shared_not_violation(self):
        """Tools -> shared is the correct direction, no violations."""
        graph = {
            f"{TOOLS_PREFIX}editor/main.ts": _graph_entry(
                imports={f"{SHARED_PREFIX}utils.ts"},
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_coupling_violations(
                Path("/project"), graph, SHARED_PREFIX, TOOLS_PREFIX
            )

        assert entries == []
        assert total_edges.eligible_edges == 0

    def test_non_shared_files_ignored(self):
        """Files outside shared/ prefix are skipped entirely."""
        graph = {
            "/project/src/other/x.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}editor/y.ts"},
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_coupling_violations(
                Path("/project"), graph, SHARED_PREFIX, TOOLS_PREFIX
            )

        assert entries == []
        assert total_edges.eligible_edges == 0

    def test_empty_graph(self):
        """Empty graph returns no entries and zero edges."""
        entries, total_edges = detect_coupling_violations(
            Path("/project"), {}, SHARED_PREFIX, TOOLS_PREFIX
        )
        assert entries == []
        assert total_edges.eligible_edges == 0

    def test_accepts_relative_graph_keys_with_absolute_prefixes(self):
        """Relative graph keys still match when prefixes are absolute."""
        graph = {
            "src/shared/utils.ts": _graph_entry(
                imports={"src/tools/editor/helpers.ts"},
            ),
        }
        with patch("desloppify.engine.detectors.coupling.rel", side_effect=lambda p: p):
            entries, total_edges = detect_coupling_violations(
                Path("/project"), graph, SHARED_PREFIX, TOOLS_PREFIX
            )
        assert len(entries) == 1
        assert total_edges.eligible_edges == 1
        assert entries[0]["tool"] == "editor"

    def test_rejects_empty_prefixes(self):
        """Empty prefixes are rejected explicitly (no silent no-op behavior)."""
        with pytest.raises(ValueError, match="shared_prefix"):
            detect_coupling_violations(Path("/project"), {}, "", TOOLS_PREFIX)
        with pytest.raises(ValueError, match="tools_prefix"):
            detect_coupling_violations(Path("/project"), {}, SHARED_PREFIX, "")

    def test_tool_name_extraction(self):
        """Tool name is the first path segment after tools_prefix."""
        graph = {
            f"{SHARED_PREFIX}a.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}my-tool/deep/nested/file.ts"},
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, _ = detect_coupling_violations(
                Path("/project"), graph, SHARED_PREFIX, TOOLS_PREFIX
            )

        assert entries[0]["tool"] == "my-tool"

    def test_tool_at_root_level(self):
        """Target directly under tools/ with no sub-path."""
        graph = {
            f"{SHARED_PREFIX}a.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}standalone.ts"},
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, _ = detect_coupling_violations(
                Path("/project"), graph, SHARED_PREFIX, TOOLS_PREFIX
            )

        assert entries[0]["tool"] == "standalone.ts"


# ===================================================================
# detect_boundary_candidates
# ===================================================================


class TestDetectBoundaryCandidates:
    """Tests for shared files that should move to a single tool."""

    def test_finds_single_tool_importers(self, tmp_path):
        """Shared file imported only by one tool is a boundary candidate."""
        shared_dir = tmp_path / "src" / "shared"
        shared_file = _write_file(shared_dir / "helper.ts", lines=40)

        sp = str(shared_dir) + "/"
        tp = str(tmp_path / "src" / "tools") + "/"

        graph = {
            str(shared_file): _graph_entry(
                importer_count=2,
                importers=[f"{tp}editor/a.ts", f"{tp}editor/b.ts"],
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total_shared = detect_boundary_candidates(
                tmp_path, graph, sp, tp, skip_basenames={"index.ts", "index.tsx"}
            )

        assert total_shared == 1
        assert len(entries) == 1
        assert entries[0]["file"] == str(shared_file)
        assert entries[0]["sole_tool"] == "src/tools/editor"
        assert entries[0]["importer_count"] == 2
        assert entries[0]["loc"] == 40

    def test_skips_index_files(self, tmp_path):
        """index.ts and index.tsx are skipped."""
        shared_dir = tmp_path / "src" / "shared"
        idx_ts = _write_file(shared_dir / "index.ts", lines=30)
        idx_tsx = _write_file(shared_dir / "index.tsx", lines=30)

        sp = str(shared_dir) + "/"
        tp = str(tmp_path / "src" / "tools") + "/"

        graph = {
            str(idx_ts): _graph_entry(
                importer_count=1,
                importers=[f"{tp}editor/a.ts"],
            ),
            str(idx_tsx): _graph_entry(
                importer_count=1,
                importers=[f"{tp}editor/b.ts"],
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total_shared = detect_boundary_candidates(
                tmp_path, graph, sp, tp, skip_basenames={"index.ts", "index.tsx"}
            )

        assert total_shared == 2
        assert entries == []

    def test_skips_components_ui(self, tmp_path):
        """Files under shared/components/ui/ are skipped."""
        shared_dir = tmp_path / "src" / "shared"
        ui_file = _write_file(shared_dir / "components" / "ui" / "Button.tsx", lines=50)

        sp = str(shared_dir) + "/"
        tp = str(tmp_path / "src" / "tools") + "/"

        graph = {
            str(ui_file): _graph_entry(
                importer_count=1,
                importers=[f"{tp}editor/form.tsx"],
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total_shared = detect_boundary_candidates(tmp_path, graph, sp, tp)

        assert total_shared == 1
        assert entries == []

    def test_skips_zero_importers(self, tmp_path):
        """Files with 0 importers are skipped (those are orphaned, different detector)."""
        shared_dir = tmp_path / "src" / "shared"
        orphan = _write_file(shared_dir / "orphan.ts", lines=30)

        sp = str(shared_dir) + "/"
        tp = str(tmp_path / "src" / "tools") + "/"

        graph = {
            str(orphan): _graph_entry(importer_count=0, importers=[]),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total_shared = detect_boundary_candidates(tmp_path, graph, sp, tp)

        assert total_shared == 1
        assert entries == []

    def test_multi_tool_importers_not_candidate(self, tmp_path):
        """Shared file imported by multiple tools is NOT a candidate."""
        shared_dir = tmp_path / "src" / "shared"
        shared_file = _write_file(shared_dir / "utils.ts", lines=30)

        sp = str(shared_dir) + "/"
        tp = str(tmp_path / "src" / "tools") + "/"

        graph = {
            str(shared_file): _graph_entry(
                importer_count=2,
                importers=[f"{tp}editor/a.ts", f"{tp}viewer/b.ts"],
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total_shared = detect_boundary_candidates(tmp_path, graph, sp, tp)

        assert total_shared == 1
        assert entries == []

    def test_non_tool_importer_disqualifies(self, tmp_path):
        """If any importer is outside tools/, the file is not a candidate."""
        shared_dir = tmp_path / "src" / "shared"
        shared_file = _write_file(shared_dir / "helper.ts", lines=30)

        sp = str(shared_dir) + "/"
        tp = str(tmp_path / "src" / "tools") + "/"

        graph = {
            str(shared_file): _graph_entry(
                importer_count=2,
                importers=[
                    f"{tp}editor/a.ts",
                    f"{sp}other.ts",  # non-tool importer
                ],
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total_shared = detect_boundary_candidates(tmp_path, graph, sp, tp)

        assert total_shared == 1
        assert entries == []

    def test_sorted_by_loc_descending(self, tmp_path):
        """Results are sorted by LOC descending."""
        shared_dir = tmp_path / "src" / "shared"
        small = _write_file(shared_dir / "small.ts", lines=20)
        large = _write_file(shared_dir / "large.ts", lines=80)

        sp = str(shared_dir) + "/"
        tp = str(tmp_path / "src" / "tools") + "/"

        graph = {
            str(small): _graph_entry(
                importer_count=1,
                importers=[f"{tp}editor/a.ts"],
            ),
            str(large): _graph_entry(
                importer_count=1,
                importers=[f"{tp}editor/b.ts"],
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total_shared = detect_boundary_candidates(tmp_path, graph, sp, tp)

        assert len(entries) == 2
        assert entries[0]["loc"] == 80
        assert entries[1]["loc"] == 20

    def test_returns_entries_and_total_shared(self, tmp_path):
        """Return tuple is (entries, total_shared_files_checked)."""
        shared_dir = tmp_path / "src" / "shared"
        f1 = _write_file(shared_dir / "a.ts", lines=20)
        f2 = _write_file(shared_dir / "b.ts", lines=20)
        f3 = _write_file(shared_dir / "c.ts", lines=20)

        sp = str(shared_dir) + "/"
        tp = str(tmp_path / "src" / "tools") + "/"

        graph = {
            str(f1): _graph_entry(importer_count=1, importers=[f"{tp}x/a.ts"]),
            str(f2): _graph_entry(
                importer_count=2, importers=[f"{tp}x/b.ts", f"{tp}y/c.ts"]
            ),
            str(f3): _graph_entry(importer_count=1, importers=[f"{tp}z/d.ts"]),
            # Non-shared file should not be counted in total
            f"{tp}x/a.ts": _graph_entry(importer_count=0),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total_shared = detect_boundary_candidates(tmp_path, graph, sp, tp)

        assert total_shared == 3  # Only shared files counted
        assert len(entries) == 2  # f1 and f3 are candidates (single tool each)

    def test_empty_graph(self, tmp_path):
        """Empty graph returns no entries and zero total."""
        entries, total_shared = detect_boundary_candidates(
            tmp_path, {}, SHARED_PREFIX, TOOLS_PREFIX
        )
        assert entries == []
        assert total_shared == 0

    def test_unreadable_candidate_file_is_skipped(self, tmp_path):
        """Unreadable candidate files follow the shared detector skip policy."""
        shared_dir = tmp_path / "src" / "shared"
        shared_dir.mkdir(parents=True, exist_ok=True)
        missing_file = shared_dir / "missing.ts"

        sp = str(shared_dir) + "/"
        tp = str(tmp_path / "src" / "tools") + "/"
        graph = {
            str(missing_file): _graph_entry(
                importer_count=1,
                importers=[f"{tp}editor/a.ts"],
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total_shared = detect_boundary_candidates(tmp_path, graph, sp, tp)

        assert total_shared == 1
        assert entries == []

    def test_accepts_relative_importers_with_absolute_tools_prefix(self, tmp_path):
        """Relative importer keys should still match absolute tools prefix values."""
        shared_dir = tmp_path / "src" / "shared"
        shared_file = _write_file(shared_dir / "helper.ts", lines=20)
        sp = str(shared_dir) + "/"
        tp = str(tmp_path / "src" / "tools") + "/"
        graph = {
            str(shared_file): _graph_entry(
                importer_count=1,
                importers=["src/tools/editor/a.ts"],
            ),
        }
        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: str(Path(p).relative_to(tmp_path)),
        ):
            entries, total_shared = detect_boundary_candidates(tmp_path, graph, sp, tp)
        assert total_shared == 1
        assert len(entries) == 1
        assert entries[0]["sole_tool"] == "src/tools/editor"

    def test_rejects_empty_prefixes(self, tmp_path):
        """Empty prefixes are rejected explicitly (no silent no-op behavior)."""
        with pytest.raises(ValueError, match="shared_prefix"):
            detect_boundary_candidates(tmp_path, {}, "", TOOLS_PREFIX)
        with pytest.raises(ValueError, match="tools_prefix"):
            detect_boundary_candidates(tmp_path, {}, SHARED_PREFIX, "")


# ===================================================================
# detect_cross_tool_imports
# ===================================================================


class TestDetectCrossToolImports:
    """Tests for tools/A importing from tools/B detection."""

    def test_finds_cross_tool_imports(self):
        """Importing from a different tool is a cross-tool violation."""
        graph = {
            f"{TOOLS_PREFIX}editor/main.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}viewer/utils.ts"},
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_cross_tool_imports(
                Path("/project"), graph, TOOLS_PREFIX
            )

        assert len(entries) == 1
        assert entries[0]["source_tool"] == "editor"
        assert entries[0]["target_tool"] == "viewer"
        assert entries[0]["direction"] == "tools\u2192tools"
        assert total_edges.eligible_edges == 1

    def test_same_tool_imports_counted_as_edges_not_violations(self):
        """Same-tool imports count toward total_edges but are not violations."""
        graph = {
            f"{TOOLS_PREFIX}editor/main.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}editor/helpers.ts"},
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_cross_tool_imports(
                Path("/project"), graph, TOOLS_PREFIX
            )

        assert entries == []
        assert total_edges.eligible_edges == 1  # edge counted, but not a violation

    def test_returns_entries_and_total_edges(self):
        """Return tuple is (violation_entries, total_cross_tool_edges)."""
        graph = {
            f"{TOOLS_PREFIX}editor/a.ts": _graph_entry(
                imports={
                    f"{TOOLS_PREFIX}viewer/b.ts",  # cross-tool
                    f"{TOOLS_PREFIX}editor/c.ts",  # same-tool
                },
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_cross_tool_imports(
                Path("/project"), graph, TOOLS_PREFIX
            )

        assert len(entries) == 1  # only the cross-tool import
        assert total_edges.eligible_edges == 2  # both edges counted

    def test_non_tools_files_ignored(self):
        """Files outside tools/ prefix are not checked."""
        graph = {
            f"{SHARED_PREFIX}utils.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}editor/a.ts"},
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_cross_tool_imports(
                Path("/project"), graph, TOOLS_PREFIX
            )

        assert entries == []
        assert total_edges.eligible_edges == 0

    def test_root_level_tools_file_skipped(self):
        """Files directly under tools/ (no sub-path) are skipped."""
        graph = {
            f"{TOOLS_PREFIX}config.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}editor/a.ts"},
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_cross_tool_imports(
                Path("/project"), graph, TOOLS_PREFIX
            )

        assert entries == []
        assert total_edges.eligible_edges == 0

    def test_imports_to_non_tools_not_counted(self):
        """Imports pointing outside tools/ are not counted at all."""
        graph = {
            f"{TOOLS_PREFIX}editor/main.ts": _graph_entry(
                imports={f"{SHARED_PREFIX}utils.ts"},
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_cross_tool_imports(
                Path("/project"), graph, TOOLS_PREFIX
            )

        assert entries == []
        assert total_edges.eligible_edges == 0

    def test_sorted_by_source_tool_then_file(self):
        """Results are sorted by (source_tool, file)."""
        graph = {
            f"{TOOLS_PREFIX}z-tool/main.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}editor/a.ts"},
            ),
            f"{TOOLS_PREFIX}alpha/main.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}editor/b.ts"},
            ),
            f"{TOOLS_PREFIX}alpha/aux.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}editor/c.ts"},
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_cross_tool_imports(
                Path("/project"), graph, TOOLS_PREFIX
            )

        assert len(entries) == 3
        # alpha files first (sorted by source_tool), then z-tool
        assert entries[0]["source_tool"] == "alpha"
        assert entries[1]["source_tool"] == "alpha"
        assert entries[2]["source_tool"] == "z-tool"
        # Within alpha, sorted by file path
        assert entries[0]["file"] < entries[1]["file"]

    def test_empty_graph(self):
        """Empty graph returns no entries and zero edges."""
        entries, total_edges = detect_cross_tool_imports(
            Path("/project"), {}, TOOLS_PREFIX
        )
        assert entries == []
        assert total_edges.eligible_edges == 0

    def test_accepts_relative_graph_keys_with_absolute_tools_prefix(self):
        """Relative graph keys still match absolute tools prefixes."""
        graph = {
            "src/tools/editor/main.ts": _graph_entry(
                imports={"src/tools/viewer/utils.ts"},
            ),
        }
        with patch("desloppify.engine.detectors.coupling.rel", side_effect=lambda p: p):
            entries, total_edges = detect_cross_tool_imports(
                Path("/project"), graph, TOOLS_PREFIX
            )
        assert len(entries) == 1
        assert total_edges.eligible_edges == 1
        assert entries[0]["source_tool"] == "editor"
        assert entries[0]["target_tool"] == "viewer"

    def test_rejects_empty_tools_prefix(self):
        """Empty tools prefix is rejected explicitly."""
        with pytest.raises(ValueError, match="tools_prefix"):
            detect_cross_tool_imports(Path("/project"), {}, "")

    def test_multiple_cross_tool_imports_from_same_file(self):
        """A single file importing from multiple other tools creates multiple entries."""
        graph = {
            f"{TOOLS_PREFIX}editor/main.ts": _graph_entry(
                imports={
                    f"{TOOLS_PREFIX}viewer/a.ts",
                    f"{TOOLS_PREFIX}dashboard/b.ts",
                },
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_cross_tool_imports(
                Path("/project"), graph, TOOLS_PREFIX
            )

        assert len(entries) == 2
        assert total_edges.eligible_edges == 2
        target_tools = {e["target_tool"] for e in entries}
        assert target_tools == {"viewer", "dashboard"}

    def test_bidirectional_cross_tool(self):
        """Cross-tool imports in both directions are both flagged."""
        graph = {
            f"{TOOLS_PREFIX}editor/main.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}viewer/utils.ts"},
            ),
            f"{TOOLS_PREFIX}viewer/main.ts": _graph_entry(
                imports={f"{TOOLS_PREFIX}editor/helpers.ts"},
            ),
        }

        with patch(
            "desloppify.engine.detectors.coupling.rel",
            side_effect=lambda p: p.replace("/project/", ""),
        ):
            entries, total_edges = detect_cross_tool_imports(
                Path("/project"), graph, TOOLS_PREFIX
            )

        assert len(entries) == 2
        assert total_edges.eligible_edges == 2
        source_tools = {e["source_tool"] for e in entries}
        assert source_tools == {"editor", "viewer"}
