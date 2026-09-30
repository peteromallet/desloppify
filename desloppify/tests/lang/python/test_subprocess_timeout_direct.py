"""Synthetic AST contracts for synchronous subprocess timeout detection."""

import ast

import pytest

from desloppify.languages.python.detectors.smells_ast._tree_safety_detectors import (
    _detect_subprocess_no_timeout,
)


@pytest.mark.parametrize("cached_nodes", [False, True])
@pytest.mark.parametrize("completion", ["wait(timeout=5)", "communicate(timeout=5)"])
def test_popen_with_bounded_completion_does_not_need_constructor_timeout(
    cached_nodes, completion
):
    tree = ast.parse(
        "import subprocess\n"
        'process = subprocess.Popen(["worker"])\n'
        f"process.{completion}\n"
    )
    nodes = tuple(ast.walk(tree)) if cached_nodes else None

    assert _detect_subprocess_no_timeout("synthetic.py", tree, nodes) == []


@pytest.mark.parametrize("cached_nodes", [False, True])
def test_popen_creation_can_return_without_waiting_for_completion(cached_nodes):
    tree = ast.parse(
        "import subprocess\n"
        "def start_worker():\n"
        '    return subprocess.Popen(["worker"])\n'
    )
    nodes = tuple(ast.walk(tree)) if cached_nodes else None

    assert _detect_subprocess_no_timeout("synthetic.py", tree, nodes) == []


@pytest.mark.parametrize("cached_nodes", [False, True])
@pytest.mark.parametrize("bounded", [False, True])
@pytest.mark.parametrize("function", ["run", "call", "check_call", "check_output"])
def test_synchronous_calls_still_require_timeout(cached_nodes, bounded, function):
    keyword = ", timeout=5" if bounded else ""
    tree = ast.parse(f'import subprocess\nsubprocess.{function}(["worker"]{keyword})\n')
    nodes = tuple(ast.walk(tree)) if cached_nodes else None
    expected = (
        []
        if bounded
        else [
            {
                "file": "synthetic.py",
                "line": 2,
                "content": f"subprocess.{function}() without timeout",
            }
        ]
    )

    assert _detect_subprocess_no_timeout("synthetic.py", tree, nodes) == expected


@pytest.mark.parametrize("cached_nodes", [False, True])
def test_ignoring_popen_does_not_hide_unbounded_synchronous_calls(cached_nodes):
    tree = ast.parse(
        "import subprocess\n"
        'process = subprocess.Popen(["worker"])\n'
        'subprocess.run(["worker"])\n'
        "process.communicate(timeout=5)\n"
        'subprocess.check_call(["worker"], timeout=5)\n'
        'subprocess.check_output(["worker"])\n'
    )
    nodes = tuple(ast.walk(tree)) if cached_nodes else None

    assert _detect_subprocess_no_timeout("synthetic.py", tree, nodes) == [
        {
            "file": "synthetic.py",
            "line": 3,
            "content": "subprocess.run() without timeout",
        },
        {
            "file": "synthetic.py",
            "line": 6,
            "content": "subprocess.check_output() without timeout",
        },
    ]


@pytest.mark.parametrize("cached_nodes", [False, True])
def test_unrelated_receivers_are_not_subprocess_calls(cached_nodes):
    tree = ast.parse(
        "\n".join(
            f'other.{function}(["worker"])'
            for function in ("Popen", "run", "call", "check_call", "check_output")
        )
    )
    nodes = tuple(ast.walk(tree)) if cached_nodes else None

    assert _detect_subprocess_no_timeout("synthetic.py", tree, nodes) == []
