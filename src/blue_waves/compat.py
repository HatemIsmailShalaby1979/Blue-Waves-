"""Compatibility helpers for Python < 3.11.

``StrEnum`` was added in Python 3.11. Blue Waves declares ``requires-python
>= 3.10``, so provide a drop-in backport that behaves identically (each member
is a ``str`` and ``.value`` is the lowercased name).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python 3.10 fallback

    class StrEnum(str, Enum):
        def __str__(self) -> str:
            return str(self.value)

        @staticmethod
        def _generate_next_value_(name: str, start: int, count: int, last_values: list[Any]) -> str:
            return name.lower()


__all__ = ["StrEnum"]
