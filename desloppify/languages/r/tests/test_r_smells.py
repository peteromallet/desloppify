"""Tests for R-specific code smell detectors."""

from __future__ import annotations

from pathlib import Path

from desloppify.languages.r.detectors.smells import detect_smells


def _write(path: Path, rel_path: str, content: str) -> Path:
    target = path / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def _entry(entries: list[dict], smell_id: str) -> dict:
    return next(entry for entry in entries if entry["id"] == smell_id)


def test_detect_setwd(tmp_path):
    _write(tmp_path, "R/script.R", 'setwd("/some/path")\n')
    entries, total_files = detect_smells(tmp_path)
    assert total_files == 1
    smell = _entry(entries, "setwd")
    assert smell["count"] == 1


def test_detect_global_assign(tmp_path):
    _write(tmp_path, "R/script.R", "counter <<- 1\n")
    entries, _ = detect_smells(tmp_path)
    smell = _entry(entries, "global_assign")
    assert smell["count"] == 1


def test_detect_attach(tmp_path):
    _write(tmp_path, "R/script.R", "attach(mtcars)\n")
    entries, _ = detect_smells(tmp_path)
    smell = _entry(entries, "attach")
    assert smell["count"] == 1


def test_detect_dangerous_rm(tmp_path):
    _write(tmp_path, "R/script.R", "rm(list = ls())\n")
    entries, _ = detect_smells(tmp_path)
    smell = _entry(entries, "dangerous_rm")
    assert smell["count"] == 1


def test_detect_browser_leftover(tmp_path):
    _write(tmp_path, "R/script.R", "browser()\n")
    entries, _ = detect_smells(tmp_path)
    smell = _entry(entries, "browser_leftover")
    assert smell["count"] == 1


def test_detect_debug_leftover(tmp_path):
    _write(tmp_path, "R/script.R", "debug(my_func)\n")
    entries, _ = detect_smells(tmp_path)
    smell = _entry(entries, "debug_leftover")
    assert smell["count"] == 1


def test_detect_t_f_ambiguous(tmp_path):
    _write(tmp_path, "R/script.R", "x <- T\ny <- F\n")
    entries, _ = detect_smells(tmp_path)
    smell = _entry(entries, "t_f_ambiguous")
    assert smell["count"] == 2


def test_t_f_ignores_true_false(tmp_path):
    _write(tmp_path, "R/script.R", "x <- TRUE\ny <- FALSE\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "t_f_ambiguous" not in ids


def test_t_f_ignores_identifiers_containing_t_or_f(tmp_path):
    _write(tmp_path, "R/script.R", "data <- transform(df)\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "t_f_ambiguous" not in ids


def test_detect_one_to_n(tmp_path):
    _write(tmp_path, "R/script.R", "for (i in 1:n()) {\n}\n")
    entries, _ = detect_smells(tmp_path)
    smell = _entry(entries, "one_to_n")
    assert smell["count"] == 1


def test_detect_strings_as_factors(tmp_path):
    _write(tmp_path, "R/script.R", 'options(stringsAsFactors = FALSE)\n')
    entries, _ = detect_smells(tmp_path)
    smell = _entry(entries, "strings_as_factors")
    assert smell["count"] == 1


def test_detect_library_in_function(tmp_path):
    _write(
        tmp_path,
        "R/script.R",
        "my_func <- function(x) {\n  library(dplyr)\n  x %>% mutate(y = 1)\n}\n",
    )
    entries, _ = detect_smells(tmp_path)
    smell = _entry(entries, "library_in_function")
    assert smell["count"] == 1
    assert smell["matches"][0]["line"] == 2


def test_library_at_top_level_is_not_flagged(tmp_path):
    _write(tmp_path, "R/script.R", "library(dplyr)\n\nx <- 1\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "library_in_function" not in ids


def test_no_smells_in_clean_code(tmp_path):
    _write(
        tmp_path,
        "R/script.R",
        'library(dplyr)\n\nadd <- function(a, b) {\n  a + b\n}\n',
    )
    entries, total_files = detect_smells(tmp_path)
    assert total_files == 1
    assert entries == []


def test_skips_excluded_dirs(tmp_path):
    _write(tmp_path, "renv/library/script.R", "setwd('.')\n")
    _write(tmp_path, "R/clean.R", "x <- 1\n")
    entries, total_files = detect_smells(tmp_path)
    assert total_files == 1


def test_strips_comments_before_matching(tmp_path):
    _write(tmp_path, "R/script.R", "# setwd is bad\nx <- 1\n")
    entries, _ = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert "setwd" not in ids


def test_multiple_smells_in_one_file(tmp_path):
    _write(
        tmp_path,
        "R/script.R",
        'setwd("/tmp")\ncounter <<- 0\nbrowser()\nT\n',
    )
    entries, total_files = detect_smells(tmp_path)
    ids = {e["id"] for e in entries}
    assert total_files == 1
    assert "setwd" in ids
    assert "global_assign" in ids
    assert "browser_leftover" in ids
    assert "t_f_ambiguous" in ids


def test_handles_nonexistent_files_gracefully(tmp_path):
    entries, total_files = detect_smells(tmp_path)
    assert total_files == 0
    assert entries == []
