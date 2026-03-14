"""Catalog metadata for R smell checks."""

from __future__ import annotations

R_SMELL_CHECKS = [
    {
        "id": "setwd",
        "label": "setwd() — non-portable working directory change",
        "pattern": r"(?<!\w)setwd\s*\(",
        "severity": "high",
    },
    {
        "id": "global_assign",
        "label": "<<- global assignment — can mask state",
        "pattern": r"<<-",
        "severity": "medium",
    },
    {
        "id": "attach",
        "label": "attach() — namespace pollution",
        "pattern": r"(?<!\w)attach\s*\(",
        "severity": "medium",
    },
    {
        "id": "dangerous_rm",
        "label": "rm(list=ls()) — dangerous cleanup",
        "pattern": r"rm\s*\(\s*list\s*=\s*ls\s*\(\s*\)\s*\)",
        "severity": "high",
    },
    {
        "id": "browser_leftover",
        "label": "browser() — debugging leftover",
        "pattern": r"(?<!\w)browser\s*\(",
        "severity": "medium",
    },
    {
        "id": "debug_leftover",
        "label": "debug() — debugging leftover",
        "pattern": r"(?<!\w)debug\s*\(",
        "severity": "medium",
    },
    {
        "id": "t_f_ambiguous",
        "label": "T/F used instead of TRUE/FALSE — ambiguous",
        "pattern": r"(?<![A-Za-z])[TF](?![A-Za-z0-9_])",
        "severity": "low",
    },
    {
        "id": "one_to_n",
        "label": "1:n() — off-by-one when n is 0",
        "pattern": r"1\s*:\s*n\s*\(",
        "severity": "high",
    },
    {
        "id": "strings_as_factors",
        "label": "options(stringsAsFactors=...) in script — version-specific",
        "pattern": r"options\s*\(\s*stringsAsFactors\s*=",
        "severity": "low",
    },
    {
        "id": "library_in_function",
        "label": "library()/require() inside function — side effect",
        "pattern": None,
        "severity": "low",
    },
]

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

__all__ = ["R_SMELL_CHECKS", "SEVERITY_ORDER"]
