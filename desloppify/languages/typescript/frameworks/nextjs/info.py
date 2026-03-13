"""Next.js framework info derived from generic TypeScript framework detection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desloppify.languages.typescript.frameworks.types import PrimaryFrameworkDetection


@dataclass(frozen=True)
class NextjsFrameworkInfo:
    is_primary: bool
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


def nextjs_info_from_detection(result: PrimaryFrameworkDetection) -> NextjsFrameworkInfo:
    candidate = next((c for c in result.candidates if c.id == "nextjs"), None)
    evidence = candidate.evidence if candidate is not None else {}
    return NextjsFrameworkInfo(
        is_primary=(result.primary_id == "nextjs"),
        package_root=result.package_root,
        package_json_relpath=result.package_json_relpath,
        app_roots=_tuple_str(evidence.get("app_roots")),
        pages_roots=_tuple_str(evidence.get("pages_roots")),
    )


__all__ = ["NextjsFrameworkInfo", "nextjs_info_from_detection"]

