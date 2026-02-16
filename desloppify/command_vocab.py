"""Canonical CLI command strings shared across narrative and command output.

Centralizing these avoids drift in coaching text and query payloads.
"""

from __future__ import annotations

SCAN = "desloppify scan"
STATUS = "desloppify status"
NEXT = "desloppify next"
ISSUES = "desloppify issues"

REVIEW_PREPARE = "desloppify review --prepare"
REVIEW_PREPARE_HOLISTIC = "desloppify review --prepare --holistic"

SHOW_WONTFIX = "desloppify show --status wontfix"
SHOW_WONTFIX_ALL = 'desloppify show "*" --status wontfix'

ZONE_SHOW = "desloppify zone show"
ZONE_SET_PRODUCTION = "desloppify zone set <file> production"

