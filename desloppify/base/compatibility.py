"""Python version compatibility layer.

Provides compatibility with older Python versions (3.10 and below)
by backporting required features from newer versions.
"""

from __future__ import annotations

import sys
import enum
from datetime import datetime, timedelta, timezone


# Python 3.10+ compatibility for timezone.utc
try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc


# Python 3.11+ compatibility for enum.StrEnum
try:
    from enum import StrEnum
except ImportError:
    class StrEnum(str, enum.Enum):
        """Backport of StrEnum for Python < 3.11."""
        def __str__(self) -> str:
            return self.value

        def __repr__(self) -> str:
            return f"{self.__class__.__name__}.{self.name}"


# Python 3.11+ compatibility for typing.NotRequired
try:
    from typing import NotRequired
except ImportError:
    from typing_extensions import NotRequired  # type: ignore


# Python 3.11+ compatibility for typing.Required
try:
    from typing import Required
except ImportError:
    from typing_extensions import Required  # type: ignore


# Python 3.11+ compatibility for tomllib
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore


__all__ = [
    "UTC",
    "StrEnum",
    "NotRequired",
    "Required",
    "tomllib",
]
