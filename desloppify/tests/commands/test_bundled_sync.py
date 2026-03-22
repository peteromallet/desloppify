"""Guard: bundled skill docs in data/global/ must match docs/."""

from __future__ import annotations

from pathlib import Path

import pytest

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "global"


def _overlay_files() -> list[str]:
    return sorted(path.name for path in DOCS_DIR.glob("*.md"))


@pytest.mark.parametrize("filename", _overlay_files())
def test_bundled_matches_docs(filename: str) -> None:
    docs_content = (DOCS_DIR / filename).read_text(encoding="utf-8")
    bundled_path = DATA_DIR / filename
    assert bundled_path.exists(), f"Missing bundled copy: {filename}"
    assert bundled_path.read_text(encoding="utf-8") == docs_content, (
        f"Bundled {filename} has drifted from docs/{filename}. "
        "Run `make sync-docs` to fix."
    )


def test_no_extra_bundled_files() -> None:
    docs_names = {path.name for path in DOCS_DIR.glob("*.md")}
    bundled_names = {path.name for path in DATA_DIR.glob("*.md")}
    extra = bundled_names - docs_names
    assert not extra, f"Extra bundled files not in docs/: {extra}"
