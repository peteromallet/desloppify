"""Next.js framework info derived from ecosystem-level detection evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class NextjsFrameworkInfo:
    package_root: Path
    package_json_relpath: str | None
    app_roots: tuple[str, ...]
    pages_roots: tuple[str, ...]

    @property
    def uses_app_router(self) -> bool:
        return bool(self.app_roots)

    @property
    def uses_pages_router(self) -> bool:
        return bool(self.pages_roots)


def _tuple_str(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v) for v in value if isinstance(v, str))


def nextjs_info_from_evidence(
    evidence: dict[str, Any] | None,
    *,
    package_root: Path,
    package_json_relpath: str | None,
) -> NextjsFrameworkInfo:
    """Convert generic framework evidence into Next.js routing context."""
    evidence_dict = evidence if isinstance(evidence, dict) else {}
    marker_dirs = _tuple_str(evidence_dict.get("marker_dir_hits"))
    return NextjsFrameworkInfo(
        package_root=package_root,
        package_json_relpath=package_json_relpath,
        app_roots=tuple(p for p in marker_dirs if p.endswith("/app") or p == "app"),
        pages_roots=tuple(p for p in marker_dirs if p.endswith("/pages") or p == "pages"),
    )


__all__ = ["NextjsFrameworkInfo", "nextjs_info_from_evidence"]
