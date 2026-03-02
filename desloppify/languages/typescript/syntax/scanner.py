"""String-aware TypeScript character scanner."""

from __future__ import annotations

from collections.abc import Generator


def scan_code(
    text: str, start: int = 0, end: int | None = None
) -> Generator[tuple[int, str, bool], None, None]:
    """Yield ``(index, char, in_string)`` tuples while handling escapes."""
    i = start
    limit = end if end is not None else len(text)
    in_str = None
    while i < limit:
        ch = text[i]
        if in_str:
            if ch == "\\" and i + 1 < limit:
                yield (i, ch, True)
                i += 1
                yield (i, text[i], True)
                i += 1
                continue
            if ch == in_str:
                in_str = None
            yield (i, ch, in_str is not None)
        else:
            if ch in ("'", '"', "`"):
                in_str = ch
                yield (i, ch, True)
            else:
                yield (i, ch, False)
        i += 1

