from __future__ import annotations

from pathlib import Path

from desloppify.languages.typescript.fixers.if_chain import fix_empty_if_chain


def test_same_line_else_chain_is_removed_completely(tmp_path: Path) -> None:
    target = tmp_path / "test.ts"
    target.write_text("if (x) {\n} else {\n}\n", encoding="utf-8")

    result = fix_empty_if_chain(
        [{"file": str(target), "line": 1}],
        dry_run=False,
    )

    assert result.entries == [
        {"file": str(target), "removed": ["empty_if_chain"], "lines_removed": 3}
    ]
    assert target.read_text(encoding="utf-8") == ""
