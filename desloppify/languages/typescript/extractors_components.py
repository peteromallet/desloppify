"""TSX component extraction and passthrough detection helpers."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from desloppify.engine.detectors.base import ClassInfo
from desloppify.engine.detectors.passthrough import (
    classify_params,
    classify_passthrough_tier,
)
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.file_discovery import find_tsx_files

logger = logging.getLogger(__name__)

_COMPONENT_PATTERNS = [
    re.compile(
        r"(?:export\s+)?(?:const|let)\s+(\w+)"
        r"(?:\s*:\s*React\.FC\w*<[^>]*>)?"
        r"\s*=\s*\(\s*\{([^}]*)\}",
        re.DOTALL,
    ),
    re.compile(
        r"(?:export\s+)?function\s+(\w+)\s*\(\s*\{([^}]*)\}",
        re.DOTALL,
    ),
]


def extract_ts_components(path: Path) -> list[ClassInfo]:
    """Extract React component hook metrics from TSX files."""
    results = []
    for filepath in find_tsx_files(path):
        try:
            p = (
                Path(filepath)
                if Path(filepath).is_absolute()
                else PROJECT_ROOT / filepath
            )
            content = p.read_text()
            lines = content.splitlines()
            loc = len(lines)
            if loc < 100:
                continue

            context_hooks = len(re.findall(r"use\w+Context\s*\(", content))
            use_effects = len(re.findall(r"useEffect\s*\(", content))
            use_states = len(re.findall(r"useState\s*[<(]", content))
            use_refs = len(re.findall(r"useRef\s*[<(]", content))
            all_use_hooks = len(re.findall(r"use[A-Z]\w+\s*\(", content))
            custom_hooks = max(
                0, all_use_hooks - context_hooks - use_effects - use_states - use_refs
            )

            results.append(
                ClassInfo(
                    name=Path(filepath).stem,
                    file=filepath,
                    line=1,
                    loc=loc,
                    metrics={
                        "context_hooks": context_hooks,
                        "use_effects": use_effects,
                        "use_states": use_states,
                        "use_refs": use_refs,
                        "custom_hooks": custom_hooks,
                        "hook_total": context_hooks
                        + use_effects
                        + use_states
                        + use_refs,
                    },
                )
            )
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug(
                "Skipping unreadable TSX file %s in component extraction: %s",
                filepath,
                exc,
            )
            continue
    return results


def extract_props(destructured: str) -> list[str]:
    """Extract prop names from a destructuring pattern."""
    props = []
    cleaned = re.sub(
        r":\s*(?:React\.\w+(?:<[^>]*>)?|\w+(?:<[^>]*>)?(?:\[\])?)", "", destructured
    )
    for token in cleaned.split(","):
        token = token.strip()
        if not token:
            continue
        if token.startswith("..."):
            props.append(token[3:].strip())
            continue
        if ":" in token:
            _, alias = token.split(":", 1)
            alias = alias.split("=")[0].strip()
            if alias and alias.isidentifier():
                props.append(alias)
            continue
        name = token.split("=")[0].strip()
        if name and name.isidentifier():
            props.append(name)
    return props


def tsx_passthrough_pattern(name: str) -> str:
    """Match JSX same-name attribute: propName={propName}."""
    escaped = re.escape(name)
    return rf"\b{escaped}\s*=\s*\{{\s*{escaped}\s*\}}"


def detect_passthrough_components(path: Path) -> list[dict]:
    """Detect React components where most props are same-name forwarded to children."""
    entries = []
    for filepath in find_tsx_files(path):
        try:
            p = (
                Path(filepath)
                if Path(filepath).is_absolute()
                else PROJECT_ROOT / filepath
            )
            content = p.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug(
                "Skipping unreadable TSX file %s in passthrough detection: %s",
                filepath,
                exc,
            )
            continue

        for pattern in _COMPONENT_PATTERNS:
            for match in pattern.finditer(content):
                name = match.group(1)
                destructured = match.group(2)
                props = extract_props(destructured)
                if len(props) < 4:
                    continue

                body = content[match.end() :]
                passthrough, direct = classify_params(
                    props, body, tsx_passthrough_pattern
                )
                if len(passthrough) < 4:
                    continue

                ratio = len(passthrough) / len(props)
                classification = classify_passthrough_tier(len(passthrough), ratio)
                if classification is None:
                    continue
                tier, confidence = classification

                line = content[: match.start()].count("\n") + 1
                entries.append(
                    {
                        "file": filepath,
                        "component": name,
                        "total_props": len(props),
                        "passthrough": len(passthrough),
                        "direct": len(direct),
                        "ratio": round(ratio, 2),
                        "line": line,
                        "tier": tier,
                        "confidence": confidence,
                        "passthrough_props": sorted(passthrough),
                        "direct_props": sorted(direct),
                    }
                )

    return sorted(entries, key=lambda entry: (-entry["passthrough"], -entry["ratio"]))


__all__ = [
    "detect_passthrough_components",
    "extract_props",
    "extract_ts_components",
    "tsx_passthrough_pattern",
]
