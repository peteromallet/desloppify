#!/usr/bin/env python3
"""Validate review pipeline result files after each stage.

Usage:
    python review/validate.py --stage 1    # after Stage 1: check all stage1 files
    python review/validate.py --stage 2    # after Stage 2: check stage2 files + cross-item
    python review/validate.py --stage 3    # after Stage 3: check stage3 sections + execution log
    python review/validate.py              # check everything that exists
"""

import argparse
import json
import re
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"
FILENAME_RE = re.compile(r"^(pr|issue)-(\d+)(\.stage2)?\.json$")

# Required fields per file type
STAGE1_REQUIRED = {"number", "type", "title", "author", "stage1"}
STAGE1_INNER = {"verdict", "summary", "confidence", "scope_estimate"}
STAGE2_REQUIRED = {"number", "type", "role", "verdict", "summary", "confidence"}
STAGE3_REQUIRED = {"decision", "reasoning"}

VALID_VERDICTS_12 = {"ACCEPT", "ACCEPT_WITH_CONDITIONS", "ALREADY_FIXED", "NOT_ACTIONABLE", "REJECT"}
VALID_DECISIONS_3 = {"IMPLEMENT", "IMPLEMENT_WITH_CHANGES", "REJECT", "REJECT_AND_FIX", "DEFER", "CLOSE_FIXED", "CLOSE_NOT_ACTIONABLE"}
VALID_ROLES = {"challenger", "advocate"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_SCOPE = {"small", "medium", "large"}
VALID_TYPES = {"pr", "issue"}


def validate_filename(name: str) -> list[str]:
    """Check filename matches {type}-{number}[.stage2].json pattern."""
    if name.startswith("_") or name == "execution-log.json":
        return []
    m = FILENAME_RE.match(name)
    if not m:
        return [f"Bad filename: '{name}' — expected pr-NNN.json, issue-NNN.json, or *.stage2.json"]
    return []


def validate_stage1(path: Path) -> list[str]:
    """Validate a Stage 1 result file."""
    errors = []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"{path.name}: invalid JSON — {e}"]

    missing = STAGE1_REQUIRED - set(data.keys())
    if missing:
        errors.append(f"{path.name}: missing top-level fields: {missing}")
        return errors

    if data["type"] not in VALID_TYPES:
        errors.append(f"{path.name}: type must be 'pr' or 'issue', got '{data['type']}'")

    # Check filename matches content
    expected_name = f"{data['type']}-{data['number']}.json"
    if path.name != expected_name:
        errors.append(f"{path.name}: filename doesn't match content (expected {expected_name})")

    s1 = data.get("stage1", {})
    missing_inner = STAGE1_INNER - set(s1.keys())
    if missing_inner:
        errors.append(f"{path.name}: stage1 missing fields: {missing_inner}")

    if s1.get("verdict") not in VALID_VERDICTS_12:
        errors.append(f"{path.name}: stage1.verdict must be one of {VALID_VERDICTS_12}, got '{s1.get('verdict')}'")
    if s1.get("confidence") not in VALID_CONFIDENCE:
        errors.append(f"{path.name}: stage1.confidence must be one of {VALID_CONFIDENCE}")
    if s1.get("scope_estimate") not in VALID_SCOPE:
        errors.append(f"{path.name}: stage1.scope_estimate must be one of {VALID_SCOPE}")

    if s1.get("verdict") == "REJECT" and not s1.get("reject_reason"):
        errors.append(f"{path.name}: stage1 verdict is REJECT but reject_reason is empty")
    if s1.get("verdict") == "ACCEPT_WITH_CONDITIONS" and not s1.get("conditions"):
        errors.append(f"{path.name}: stage1 verdict is ACCEPT_WITH_CONDITIONS but conditions is empty")

    return errors


def validate_stage2(path: Path) -> list[str]:
    """Validate a Stage 2 result file."""
    errors = []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"{path.name}: invalid JSON — {e}"]

    missing = STAGE2_REQUIRED - set(data.keys())
    if missing:
        errors.append(f"{path.name}: missing fields: {missing}")
        return errors

    if data["type"] not in VALID_TYPES:
        errors.append(f"{path.name}: type must be 'pr' or 'issue'")

    expected_name = f"{data['type']}-{data['number']}.stage2.json"
    if path.name != expected_name:
        errors.append(f"{path.name}: filename doesn't match content (expected {expected_name})")

    if data.get("role") not in VALID_ROLES:
        errors.append(f"{path.name}: role must be one of {VALID_ROLES}, got '{data.get('role')}'")
    if data.get("verdict") not in VALID_VERDICTS_12:
        errors.append(f"{path.name}: verdict must be one of {VALID_VERDICTS_12}")
    if data.get("confidence") not in VALID_CONFIDENCE:
        errors.append(f"{path.name}: confidence must be one of {VALID_CONFIDENCE}")
    if not data.get("counter_case"):
        errors.append(f"{path.name}: counter_case is required (even when agreeing with Stage 1)")

    if data.get("verdict") == "REJECT" and not data.get("reject_reason"):
        errors.append(f"{path.name}: verdict is REJECT but reject_reason is empty")

    return errors


def validate_cross_item(path: Path) -> list[str]:
    """Validate _cross-item.json."""
    errors = []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"_cross-item.json: invalid JSON — {e}"]

    for key in ("duplicate_groups", "ordering", "interactions"):
        if key not in data:
            errors.append(f"_cross-item.json: missing '{key}' (use empty array if none)")
        elif not isinstance(data[key], list):
            errors.append(f"_cross-item.json: '{key}' must be an array")

    for i, group in enumerate(data.get("duplicate_groups", [])):
        if not group.get("items"):
            errors.append(f"_cross-item.json: duplicate_groups[{i}] has no items")
        if not group.get("preferred"):
            errors.append(f"_cross-item.json: duplicate_groups[{i}] has no preferred item")
        elif group.get("preferred") not in group.get("items", []):
            errors.append(f"_cross-item.json: duplicate_groups[{i}] preferred '{group['preferred']}' not in items list")

    return errors


def validate_stage3(path: Path) -> list[str]:
    """Check that a Stage 1 file has a valid stage3 section."""
    errors = []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"{path.name}: invalid JSON — {e}"]

    s3 = data.get("stage3")
    if s3 is None:
        return []  # not yet processed, that's ok

    missing = STAGE3_REQUIRED - set(s3.keys())
    if missing:
        errors.append(f"{path.name}: stage3 missing fields: {missing}")

    if s3.get("decision") not in VALID_DECISIONS_3:
        errors.append(f"{path.name}: stage3.decision must be one of {VALID_DECISIONS_3}, got '{s3.get('decision')}'")

    if s3.get("decision") in ("IMPLEMENT", "IMPLEMENT_WITH_CHANGES", "REJECT_AND_FIX") and not s3.get("commit"):
        errors.append(f"{path.name}: stage3 decision is {s3['decision']} but commit SHA is missing")

    return errors


def validate_execution_log(path: Path) -> list[str]:
    """Validate execution-log.json."""
    errors = []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"execution-log.json: invalid JSON — {e}"]

    if not isinstance(data, list):
        return ["execution-log.json: must be a JSON array"]

    for i, entry in enumerate(data):
        for field in ("number", "type", "decision"):
            if field not in entry:
                errors.append(f"execution-log.json[{i}]: missing '{field}'")

    return errors


def run(stage: int | None) -> list[str]:
    errors = []

    if not RESULTS_DIR.exists():
        return ["review/results/ directory does not exist. Run Stage 1 first."]

    # Check all filenames
    for f in RESULTS_DIR.iterdir():
        if f.is_file():
            errors.extend(validate_filename(f.name))

    # Collect stage1 and stage2 files
    stage1_files = sorted(RESULTS_DIR.glob("[!_]*.json"))
    stage1_files = [f for f in stage1_files if ".stage2." not in f.name and f.name != "execution-log.json"]
    stage2_files = sorted(RESULTS_DIR.glob("*.stage2.json"))

    # Stage 1 validation
    if stage is None or stage >= 1:
        if not stage1_files:
            errors.append("No Stage 1 result files found.")
        for f in stage1_files:
            errors.extend(validate_stage1(f))

    # Stage 2 validation
    if stage is None or stage >= 2:
        # Check completeness: every stage1 file should have a stage2 file
        stage1_stems = {f.stem for f in stage1_files}
        stage2_stems = {f.name.replace(".stage2.json", "") for f in stage2_files}
        missing_stage2 = stage1_stems - stage2_stems
        if missing_stage2:
            errors.append(f"Missing .stage2.json files for: {sorted(missing_stage2)}")

        for f in stage2_files:
            errors.extend(validate_stage2(f))

        cross = RESULTS_DIR / "_cross-item.json"
        if cross.exists():
            errors.extend(validate_cross_item(cross))
        elif stage == 2:
            errors.append("_cross-item.json not found. Stage 2 orchestrator must write it.")

    # Stage 3 validation
    if stage is None or stage >= 3:
        for f in stage1_files:
            errors.extend(validate_stage3(f))

        log = RESULTS_DIR / "execution-log.json"
        if log.exists():
            errors.extend(validate_execution_log(log))

    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate review pipeline results")
    parser.add_argument("--stage", type=int, choices=[1, 2, 3], help="Validate up to this stage")
    args = parser.parse_args()

    errors = run(args.stage)

    if errors:
        print(f"VALIDATION FAILED — {len(errors)} error(s):\n")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        stage_label = f"stage {args.stage}" if args.stage else "all stages"
        n1 = len(list(RESULTS_DIR.glob("[!_]*.json"))) - len(list(RESULTS_DIR.glob("*.stage2.json")))
        if (RESULTS_DIR / "execution-log.json").exists():
            n1 -= 1
        n2 = len(list(RESULTS_DIR.glob("*.stage2.json")))
        print(f"✓ Validation passed ({stage_label}): {n1} stage1 files, {n2} stage2 files")
        sys.exit(0)


if __name__ == "__main__":
    main()
