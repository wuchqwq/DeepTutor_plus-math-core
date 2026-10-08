from __future__ import annotations

from dataclasses import dataclass
import re

_CJK_RE = re.compile("[\\u4e00-\\u9fff]")


class MathInputError(ValueError):
    """Rejected mathematical display, independent of any planner."""


@dataclass(frozen=True, slots=True)
class MathExpression:
    """One pure-math claim (§9.1): ``display`` has no prose (§9.2 enforced).

    ``gloss`` keeps the Chinese explanation out of ``display``; ``status`` is
    filled by the math validator; ``scope`` names exactly what was checked,
    including the normalized form (ARCH-13).
    """

    display: str
    gloss: str | None = None
    kind: str = "structural_or_conceptual"
    status: str = "not_checkable"
    scope: str = ""
    residual: str | None = None


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))
