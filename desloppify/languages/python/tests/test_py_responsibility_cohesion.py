"""Tests for responsibility cohesion detector."""

from pathlib import Path

from desloppify.languages.python.detectors.responsibility_cohesion import (
    detect_responsibility_cohesion,
)


def _write(tmp_path: Path, rel: str, content: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _padding_lines(count: int) -> str:
    return "\n".join(f"# pad {idx}" for idx in range(count))


def test_detects_disconnected_dumping_ground_module(tmp_path):
    module = (
        "import os\n"
        "import json\n"
        "import subprocess\n\n"
        "def path_rel(p):\n    return os.path.relpath(p)\n\n"
        "def path_abs(p):\n    return os.path.abspath(path_rel(p))\n\n"
        "def path_join(a, b):\n    return os.path.join(a, b)\n\n"
        "def json_loads(s):\n    return json.loads(s)\n\n"
        "def json_dumps(v):\n    return json.dumps(json_loads(v) if isinstance(v, str) else v)\n\n"
        "def json_read(fp):\n    return json_loads(open(fp).read())\n\n"
        "def cmd_run(args):\n    return subprocess.run(args, capture_output=True)\n\n"
        "def cmd_check(args):\n    return subprocess.check_output(args)\n\n"
        "def cmd_echo(msg):\n    return cmd_run(['echo', msg])\n\n"
        "def cmd_popen(args):\n    return subprocess.Popen(args)\n\n"
        + _padding_lines(270)
        + "\n"
    )
    _write(tmp_path, "utils.py", module)
    entries, candidates = detect_responsibility_cohesion(tmp_path)
    assert candidates == 1
    assert len(entries) == 1
    assert entries[0]["file"].endswith("utils.py")
    assert entries[0]["component_count"] >= 3
    assert entries[0]["function_count"] >= 10


def test_ignores_connected_module(tmp_path):
    module = (
        "def a():\n    return b()\n\n"
        "def b():\n    return c()\n\n"
        "def c():\n    return d()\n\n"
        "def d():\n    return e()\n\n"
        "def e():\n    return f()\n\n"
        "def f():\n    return g()\n\n"
        "def g():\n    return h()\n\n"
        "def h():\n    return i()\n\n"
        "def i():\n    return 1\n\n"
        + _padding_lines(220)
        + "\n"
    )
    _write(tmp_path, "focused.py", module)
    entries, _ = detect_responsibility_cohesion(tmp_path)
    assert entries == []


def test_ignores_small_files_even_if_disconnected(tmp_path):
    module = (
        "def a():\n    return 1\n\n"
        "def b():\n    return 2\n\n"
        "def c():\n    return 3\n\n"
        "def d():\n    return 4\n\n"
        "def e():\n    return 5\n\n"
        "def f():\n    return 6\n\n"
        "def g():\n    return 7\n\n"
        "def h():\n    return 8\n\n"
    )
    _write(tmp_path, "small_utils.py", module)
    entries, candidates = detect_responsibility_cohesion(tmp_path)
    assert candidates == 0
    assert entries == []

