"""Python code smell tests -- split into focused modules.

Tests have been decomposed into:
  - test_py_smells_regex.py     -- regex-based detectors (eval, todo, url, magic, backtrack)
  - test_py_smells_ast.py       -- AST-based detectors (except, dead, noop, boundary, etc.)
  - test_py_smells_crossfile.py -- cross-file detectors, string helpers, output structure
"""
