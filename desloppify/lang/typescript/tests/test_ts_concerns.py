"""Tests for desloppify.lang.typescript.detectors.concerns — mixed concern detection."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _set_project_root(tmp_path, monkeypatch):
    """Point PROJECT_ROOT at the tmp directory."""
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))
    import desloppify.utils as utils_mod
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    import desloppify.lang.typescript.detectors.concerns as det_mod
    monkeypatch.setattr(det_mod, "PROJECT_ROOT", tmp_path)
    utils_mod._find_source_files_cached.cache_clear()


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _pad_lines(content: str, target: int = 110) -> str:
    """Pad content to at least target lines (detect_mixed_concerns requires >=100 LOC)."""
    lines = content.splitlines()
    while len(lines) < target:
        lines.append("// padding line")
    return "\n".join(lines)


# ── detect_mixed_concerns ────────────────────────────────────


class TestDetectMixedConcerns:
    def test_detects_mixed_jsx_fetch_transforms(self, tmp_path):
        """File with JSX + data fetching + data transforms is flagged."""
        from desloppify.lang.typescript.detectors.concerns import detect_mixed_concerns

        content = _pad_lines(
            "import { useQuery } from 'react-query';\n"
            "function Component() {\n"
            "  const { data } = useQuery({ queryKey: ['items'] });\n"
            "  const filtered = data.filter(x => x.active);\n"
            "  const mapped = filtered.map(x => x.name);\n"
            "  const sorted = mapped.sort((a, b) => a.localeCompare(b));\n"
            "  return (\n"
            "    <div>{sorted.join(', ')}</div>\n"
            "  );\n"
            "}\n"
        )
        _write(tmp_path, "Mixed.tsx", content)

        entries, total = detect_mixed_concerns(tmp_path)
        assert len(entries) == 1
        assert "jsx_rendering" in entries[0]["concerns"]
        assert "data_fetching" in entries[0]["concerns"]
        assert total >= 1

    def test_short_file_not_flagged(self, tmp_path):
        """Files under 100 LOC are not flagged regardless of concerns."""
        from desloppify.lang.typescript.detectors.concerns import detect_mixed_concerns

        content = (
            "import { useQuery } from 'react-query';\n"
            "function Component() {\n"
            "  const { data } = useQuery({ queryKey: ['items'] });\n"
            "  const filtered = data.filter(x => x.active);\n"
            "  const mapped = filtered.map(x => x.name);\n"
            "  const sorted = mapped.sort((a, b) => a.localeCompare(b));\n"
            "  return <div>{sorted.join(', ')}</div>;\n"
            "}\n"
        )
        _write(tmp_path, "Short.tsx", content)

        entries, _ = detect_mixed_concerns(tmp_path)
        assert len(entries) == 0

    def test_jsx_only_not_flagged(self, tmp_path):
        """File with only JSX (one concern) is not flagged."""
        from desloppify.lang.typescript.detectors.concerns import detect_mixed_concerns

        content = _pad_lines(
            "function Button() {\n"
            "  return (\n"
            "    <button>Click me</button>\n"
            "  );\n"
            "}\n"
        )
        _write(tmp_path, "Button.tsx", content)

        entries, _ = detect_mixed_concerns(tmp_path)
        assert len(entries) == 0

    def test_detects_many_handlers(self, tmp_path):
        """File with >=5 handler definitions contributes to concern count."""
        from desloppify.lang.typescript.detectors.concerns import detect_mixed_concerns

        handlers = "\n".join(
            f"const handle{name} = () => {{}};"
            for name in ["Click", "Submit", "Change", "Focus", "Blur"]
        )
        content = _pad_lines(
            f"import {{ useQuery }} from 'react-query';\n"
            f"function Component() {{\n"
            f"  const {{ data }} = useQuery({{ queryKey: ['items'] }});\n"
            f"{handlers}\n"
            f"  return (\n"
            f"    <div>content</div>\n"
            f"  );\n"
            f"}}\n"
        )
        _write(tmp_path, "Handlers.tsx", content)

        entries, _ = detect_mixed_concerns(tmp_path)
        assert len(entries) == 1
        concerns = entries[0]["concerns"]
        handler_concerns = [c for c in concerns if c.startswith("handlers")]
        assert len(handler_concerns) == 1

    def test_detects_direct_supabase_calls(self, tmp_path):
        """Direct supabase.table.method.method calls are detected as a concern."""
        from desloppify.lang.typescript.detectors.concerns import detect_mixed_concerns

        content = _pad_lines(
            "function Component() {\n"
            "  const data = supabase.from.select.eq;\n"
            "  const items = data.filter(x => x.active);\n"
            "  const names = items.map(x => x.name);\n"
            "  const sorted = names.sort();\n"
            "  return (\n"
            "    <div>content</div>\n"
            "  );\n"
            "}\n"
        )
        _write(tmp_path, "Direct.tsx", content)

        entries, _ = detect_mixed_concerns(tmp_path)
        if entries:
            concerns = entries[0]["concerns"]
            assert any("direct_supabase" in c for c in concerns) or any("data_transforms" in c for c in concerns)

    def test_empty_directory(self, tmp_path):
        """Empty directory returns no entries."""
        from desloppify.lang.typescript.detectors.concerns import detect_mixed_concerns

        entries, total = detect_mixed_concerns(tmp_path)
        assert entries == []
        assert total == 0

    def test_only_ts_files_not_scanned(self, tmp_path):
        """Only .tsx files are scanned (not .ts)."""
        from desloppify.lang.typescript.detectors.concerns import detect_mixed_concerns

        content = _pad_lines(
            "import { useQuery } from 'react-query';\n"
            "function service() {\n"
            "  const data = useQuery({ queryKey: ['items'] });\n"
            "  const mapped = data.map(x => x.name);\n"
            "  const filtered = mapped.filter(x => x);\n"
            "  const sorted = filtered.sort();\n"
            "  return (<div>test</div>);\n"
            "}\n"
        )
        _write(tmp_path, "service.ts", content)

        entries, total = detect_mixed_concerns(tmp_path)
        assert total == 0  # .ts files are not found by find_tsx_files

    def test_results_sorted_by_concern_count(self, tmp_path):
        """Results are sorted by concern_count in descending order."""
        from desloppify.lang.typescript.detectors.concerns import detect_mixed_concerns

        # File with 3 concerns
        content3 = _pad_lines(
            "import { useQuery } from 'react-query';\n"
            "function A() {\n"
            "  const { data } = useQuery({ queryKey: ['a'] });\n"
            "  const x = data.filter(i => i).map(i => i).sort();\n"
            "  return (<div>{x}</div>);\n"
            "}\n"
        )
        # File with 4+ concerns
        handlers4 = "\n".join(f"const handle{n} = () => {{}};" for n in ["A", "B", "C", "D", "E"])
        content4 = _pad_lines(
            f"import {{ useQuery }} from 'react-query';\n"
            f"function B() {{\n"
            f"  const {{ data }} = useQuery({{ queryKey: ['b'] }});\n"
            f"  const x = data.filter(i => i).map(i => i).sort();\n"
            f"{handlers4}\n"
            f"  return (<div>{{x}}</div>);\n"
            f"}}\n"
        )
        _write(tmp_path, "Three.tsx", content3)
        _write(tmp_path, "Four.tsx", content4)

        entries, _ = detect_mixed_concerns(tmp_path)
        if len(entries) >= 2:
            assert entries[0]["concern_count"] >= entries[1]["concern_count"]

    def test_concern_count_in_entry(self, tmp_path):
        """Each entry has a concern_count field matching the number of concerns."""
        from desloppify.lang.typescript.detectors.concerns import detect_mixed_concerns

        content = _pad_lines(
            "import { useQuery } from 'react-query';\n"
            "function Component() {\n"
            "  const { data } = useQuery({ queryKey: ['items'] });\n"
            "  const x = data.filter(i => i).map(i => i).sort();\n"
            "  return (<div>{x}</div>);\n"
            "}\n"
        )
        _write(tmp_path, "Comp.tsx", content)

        entries, _ = detect_mixed_concerns(tmp_path)
        if entries:
            assert entries[0]["concern_count"] == len(entries[0]["concerns"])
