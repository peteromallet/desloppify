"""God class/component detection via configurable rule-based analysis."""


def detect_gods(classes, rules, min_reasons: int = 2) -> tuple[list[dict], int]:
    """Find god classes/components — entities with too many responsibilities.

    Args:
        classes: list of ClassInfo objects (from extractors).
        rules: list of GodRule objects defining thresholds.
        min_reasons: minimum rule violations to flag as god.

    Returns (entries, total_classes_checked).
    """
    entries = []
    for cls in classes:
        reasons = []
        for rule in rules:
            value = rule.extract(cls)
            if value >= rule.threshold:
                reasons.append(f"{value} {rule.description}")

        if len(reasons) >= min_reasons:
            entries.append({
                "file": cls.file,
                "name": cls.name,
                "loc": cls.loc,
                "reasons": reasons,
                "signal_text": f"{cls.name} ({', '.join(reasons[:2])})",
                "detail": {**cls.metrics, "name": cls.name},
            })
    return sorted(entries, key=lambda e: -e["loc"]), len(classes)
