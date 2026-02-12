"""Shared command factories for detect subcommands.

Commands that are structurally identical across languages (same detect call +
display_entries pattern, differing only in parameters) are generated here.
Language-specific commands with unique display logic stay in their own modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..utils import c, display_entries, print_table, rel


def make_cmd_large(file_finder: Callable, default_threshold: int):
    """Factory: detect large files."""
    def cmd_large(args):
        from ..detectors.large import detect_large_files
        threshold = getattr(args, "threshold", default_threshold)
        entries, _ = detect_large_files(Path(args.path), file_finder=file_finder,
                                     threshold=threshold)
        display_entries(args, entries,
            label=f"Large files (>{threshold} LOC)",
            empty_msg=f"No files over {threshold} lines.",
            columns=["File", "LOC"], widths=[70, 6],
            row_fn=lambda e: [rel(e["file"]), str(e["loc"])])
    return cmd_large


def make_cmd_complexity(
    file_finder: Callable, signals: list, default_threshold: int = 15,
):
    """Factory: detect complexity signals."""
    def cmd_complexity(args):
        from ..detectors.complexity import detect_complexity
        entries, _ = detect_complexity(Path(args.path), signals=signals,
                                    file_finder=file_finder, threshold=default_threshold)
        display_entries(args, entries,
            label="Complexity signals",
            empty_msg="No significant complexity signals found.",
            columns=["File", "LOC", "Score", "Signals"], widths=[55, 5, 6, 45],
            row_fn=lambda e: [rel(e["file"]), str(e["loc"]), str(e["score"]),
                              ", ".join(e["signals"][:4])])
    return cmd_complexity


def make_cmd_single_use(build_dep_graph: Callable, barrel_names: set[str]):
    """Factory: detect single-use abstractions."""
    def cmd_single_use(args):
        from ..detectors.single_use import detect_single_use_abstractions
        graph = build_dep_graph(Path(args.path))
        entries, _ = detect_single_use_abstractions(
            Path(args.path), graph, barrel_names=barrel_names)
        display_entries(args, entries,
            label="Single-use abstractions",
            empty_msg="No single-use abstractions found.",
            columns=["File", "LOC", "Only Imported By"], widths=[45, 5, 60],
            row_fn=lambda e: [rel(e["file"]), str(e["loc"]), e["sole_importer"]])
    return cmd_single_use


def make_cmd_passthrough(
    detect_fn: Callable, noun: str, name_key: str, total_key: str,
):
    """Factory: detect passthrough components/functions."""
    def cmd_passthrough(args):
        entries = detect_fn(Path(args.path))
        display_entries(args, entries,
            label=f"Passthrough {noun}s",
            empty_msg=f"No passthrough {noun}s found.",
            columns=["Name", "File", "PT/Total", "Ratio", "Tier", "Line"],
            widths=[30, 55, 10, 7, 5, 6],
            row_fn=lambda e: [e[name_key], rel(e["file"]),
                              f"{e['passthrough']}/{e[total_key]}",
                              f"{e['ratio']:.0%}", f"T{e['tier']}", str(e["line"])])
    return cmd_passthrough


def make_cmd_naming(
    file_finder: Callable, skip_names: set[str],
    skip_dirs: set[str] | None = None,
):
    """Factory: detect naming inconsistencies."""
    def cmd_naming(args):
        from ..detectors.naming import detect_naming_inconsistencies
        kwargs = dict(file_finder=file_finder, skip_names=skip_names)
        if skip_dirs:
            kwargs["skip_dirs"] = skip_dirs
        entries, _ = detect_naming_inconsistencies(Path(args.path), **kwargs)
        display_entries(args, entries,
            label="Naming inconsistencies",
            empty_msg="\nNo naming inconsistencies found.",
            columns=["Directory", "Majority", "Minority", "Outliers"],
            widths=[45, 20, 20, 40],
            row_fn=lambda e: [
                e["directory"], f"{e['majority']} ({e['majority_count']})",
                f"{e['minority']} ({e['minority_count']})",
                ", ".join(e["outliers"][:5])
                + (f" (+{len(e['outliers']) - 5})" if len(e["outliers"]) > 5 else "")])
    return cmd_naming


def make_cmd_smells(detect_smells_fn: Callable):
    """Factory: detect code smells."""
    def cmd_smells(args):
        import json
        entries, _ = detect_smells_fn(Path(args.path))
        if getattr(args, "json", False):
            print(json.dumps({"entries": entries}, indent=2))
            return
        if not entries:
            print(c("No code smells detected.", "green"))
            return
        total = sum(e["count"] for e in entries)
        print(c(f"\nCode smells: {total} instances across {len(entries)} patterns\n", "bold"))
        rows = []
        for e in entries[:getattr(args, "top", 20)]:
            sev_color = {"high": "red", "medium": "yellow", "low": "dim"}.get(e["severity"], "dim")
            rows.append([c(e["severity"].upper(), sev_color), e["label"],
                         str(e["count"]), str(e["files"])])
        print_table(["Sev", "Pattern", "Count", "Files"], rows, [8, 40, 6, 6])
        high = [e for e in entries if e["severity"] == "high"]
        for e in high:
            print(c(f"\n  {e['label']} ({e['count']} instances):", "red"))
            for m in e["matches"][:10]:
                print(f"    {rel(m['file'])}:{m['line']}  {m['content'][:60]}")
    return cmd_smells
