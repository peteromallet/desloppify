"""Flat directory detection — directories with too many source files."""

import logging
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

from desloppify.core.file_paths import resolve_scan_file

THIN_WRAPPER_NAMES = frozenset(
    {
        "components",
        "hooks",
        "utils",
        "services",
        "state",
        "contexts",
        "contracts",
        "types",
        "models",
        "adapters",
        "helpers",
        "core",
        "common",
    }
)


def format_flat_dir_summary(entry: dict) -> str:
    """Render a human-readable summary for a flat/fragmented directory entry."""
    kind = str(entry.get("kind", "overload"))
    file_count = int(entry.get("file_count", 0))
    child_dir_count = int(entry.get("child_dir_count", 0))
    combined_score = int(entry.get("combined_score", file_count))
    sparse_child_count = int(entry.get("sparse_child_count", 0))
    sparse_file_threshold = int(entry.get("sparse_child_file_threshold", 1))
    parent_sibling_count = int(entry.get("parent_sibling_count", 0))
    wrapper_item_count = int(entry.get("wrapper_item_count", 0))
    if kind == "fragmented":
        return (
            "Directory fragmentation: "
            f"{file_count} files, {child_dir_count} child dirs "
            f"(combined {combined_score}); "
            f"{sparse_child_count}/{child_dir_count} child dirs have <= "
            f"{sparse_file_threshold} file(s) — consider flattening/grouping"
        )
    if kind == "overload_fragmented":
        return (
            "Directory overload: "
            f"{file_count} files, {child_dir_count} child dirs "
            f"(combined {combined_score}); "
            f"{sparse_child_count}/{child_dir_count} child dirs have <= "
            f"{sparse_file_threshold} file(s)"
        )
    if kind == "thin_wrapper":
        return (
            "Thin wrapper directory: "
            f"{file_count} files, {child_dir_count} child dirs "
            f"({wrapper_item_count} item) in parent with "
            f"{parent_sibling_count} sibling dirs — consider flattening"
        )
    return (
        "Directory overload: "
        f"{file_count} files, {child_dir_count} child dirs "
        f"(combined {combined_score}) — consider grouping by domain"
    )


def detect_flat_dirs(
    path: Path,
    file_finder,
    threshold: int = 20,
    *,
    child_dir_threshold: int = 10,
    child_dir_weight: int = 3,
    combined_threshold: int = 30,
    sparse_parent_child_threshold: int = 8,
    sparse_child_file_threshold: int = 1,
    sparse_child_count_threshold: int = 6,
    sparse_child_ratio_threshold: float = 0.7,
    thin_wrapper_parent_sibling_threshold: int = 10,
    thin_wrapper_max_file_count: int = 1,
    thin_wrapper_max_child_dir_count: int = 1,
    thin_wrapper_names: tuple[str, ...] = (
        "components",
        "hooks",
        "utils",
        "services",
        "state",
        "contexts",
        "contracts",
        "types",
        "models",
        "adapters",
        "helpers",
        "core",
        "common",
    ),
) -> tuple[list[dict], int]:
    """Find overloaded/fragmented directories using count and fan-out heuristics."""
    files = file_finder(path)
    scan_root = path.resolve()
    dir_counts: Counter[str] = Counter()
    child_dirs: dict[str, set[str]] = {}
    for f in files:
        try:
            resolved_file = resolve_scan_file(f, scan_root=path).resolve()
            parent_path = resolved_file.parent
            parent_rel = parent_path.relative_to(scan_root)
        except (OSError, ValueError) as exc:
            logger.debug("Skipping unresolvable file %s: %s", f, exc)
            continue

        parent = str((scan_root / parent_rel).resolve())
        dir_counts[parent] += 1
        # Track direct subdirectory fan-out for every ancestor.
        parts = parent_rel.parts
        for idx in range(len(parts) - 1):
            ancestor = (scan_root / Path(*parts[: idx + 1])).resolve()
            child = (scan_root / Path(*parts[: idx + 2])).resolve()
            ancestor_key = str(ancestor)
            child_dirs.setdefault(ancestor_key, set()).add(str(child))

    all_dirs: set[str] = set(dir_counts.keys())
    all_dirs.update(child_dirs.keys())
    for children in child_dirs.values():
        all_dirs.update(children)

    thin_names = {name.lower() for name in thin_wrapper_names}
    if not thin_names:
        thin_names = set(THIN_WRAPPER_NAMES)

    entries = []
    for dir_path in sorted(all_dirs):
        file_count = int(dir_counts.get(dir_path, 0))
        direct_children = child_dirs.get(dir_path, set())
        direct_child_count = len(direct_children)
        combined_score = file_count + (child_dir_weight * direct_child_count)
        has_local_files = dir_path in dir_counts

        if has_local_files:
            overloaded = (
                file_count >= threshold
                or direct_child_count >= child_dir_threshold
                or combined_score >= combined_threshold
            )
            if overloaded:
                entries.append(
                    {
                        "directory": dir_path,
                        "file_count": file_count,
                        "child_dir_count": direct_child_count,
                        "combined_score": combined_score,
                        "kind": "overload",
                    }
                )
                continue
            # Conservative anti-fragmentation signal:
            # only flag when a parent has many child dirs and most are single-file leaves.
            sparse_child_count = 0
            for child in direct_children:
                child_file_count = int(dir_counts.get(child, 0))
                child_child_count = len(child_dirs.get(child, set()))
                if (
                    child_file_count <= sparse_child_file_threshold
                    and child_child_count == 0
                ):
                    sparse_child_count += 1
            sparse_child_ratio = (
                float(sparse_child_count) / float(direct_child_count)
                if direct_child_count
                else 0.0
            )
            fragmented = (
                direct_child_count >= sparse_parent_child_threshold
                and sparse_child_count >= sparse_child_count_threshold
                and sparse_child_ratio >= sparse_child_ratio_threshold
            )
            if fragmented:
                entries.append(
                    {
                        "directory": dir_path,
                        "file_count": file_count,
                        "child_dir_count": direct_child_count,
                        "combined_score": combined_score,
                        "kind": "fragmented",
                        "sparse_child_count": sparse_child_count,
                        "sparse_child_ratio": sparse_child_ratio,
                        "sparse_child_file_threshold": sparse_child_file_threshold,
                    }
                )
                continue

        dir_name = Path(dir_path).name.lower()
        parent_key = str(Path(dir_path).parent)
        parent_sibling_count = len(child_dirs.get(parent_key, set()))
        wrapper_item_count = file_count + direct_child_count
        thin_wrapper = (
            dir_name in thin_names
            and wrapper_item_count == 1
            and file_count <= thin_wrapper_max_file_count
            and direct_child_count <= thin_wrapper_max_child_dir_count
            and parent_sibling_count >= thin_wrapper_parent_sibling_threshold
        )
        if thin_wrapper:
            entries.append(
                {
                    "directory": dir_path,
                    "file_count": file_count,
                    "child_dir_count": direct_child_count,
                    "combined_score": combined_score,
                    "kind": "thin_wrapper",
                    "parent_sibling_count": parent_sibling_count,
                    "wrapper_item_count": wrapper_item_count,
                }
            )
    return sorted(
        entries,
        key=lambda e: (
            -int(e["combined_score"]),
            -int(e.get("parent_sibling_count", 0)),
            -int(e.get("sparse_child_count", 0)),
            -int(e["child_dir_count"]),
            -int(e["file_count"]),
        ),
    ), len(all_dirs)
