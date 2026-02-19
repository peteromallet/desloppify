"""Tests for boilerplate duplication detector."""

from pathlib import Path

from desloppify.engine.detectors.boilerplate_duplication import (
    detect_boilerplate_duplication,
)
from desloppify.utils import find_py_files


def _write(tmp_path: Path, rel: str, content: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_detects_repeated_boilerplate_across_three_files(tmp_path):
    snippet_a = (
        "from pathlib import Path\n\n"
        "def scan(filepath):\n"
        "    try:\n"
        "        content = Path(filepath).read_text()\n"
        "    except (OSError, UnicodeDecodeError):\n"
        "        return None\n"
        "    return content\n"
    )
    snippet_b = (
        "from pathlib import Path\n\n"
        "def load(file_path):\n"
        "    try:\n"
        "        text = Path(file_path).read_text()\n"
        "    except (OSError, UnicodeDecodeError):\n"
        "        return None\n"
        "    return text\n"
    )
    snippet_c = (
        "from pathlib import Path\n\n"
        "def parse(name):\n"
        "    try:\n"
        "        value = Path(name).read_text()\n"
        "    except (OSError, UnicodeDecodeError):\n"
        "        return None\n"
        "    return value\n"
    )

    _write(tmp_path, "a.py", snippet_a)
    _write(tmp_path, "b.py", snippet_b)
    _write(tmp_path, "c.py", snippet_c)

    entries, total = detect_boilerplate_duplication(tmp_path, file_finder=find_py_files)
    assert total == 3
    assert entries
    assert entries[0]["distinct_files"] >= 3
    files = {Path(loc["file"]).name for loc in entries[0]["locations"]}
    assert {"a.py", "b.py", "c.py"} <= files


def test_requires_three_distinct_files(tmp_path):
    snippet = (
        "from pathlib import Path\n\n"
        "def scan(filepath):\n"
        "    try:\n"
        "        content = Path(filepath).read_text()\n"
        "    except (OSError, UnicodeDecodeError):\n"
        "        return None\n"
        "    return content\n"
    )
    _write(tmp_path, "a.py", snippet)
    _write(tmp_path, "b.py", snippet.replace("scan", "scan_b"))

    entries, total = detect_boilerplate_duplication(tmp_path, file_finder=find_py_files)
    assert total == 2
    assert entries == []
