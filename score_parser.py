"""Shared parsing helpers for scores shown by the activity UI."""

import re
from decimal import Decimal, ROUND_HALF_UP


_SCORE_RE = re.compile(
    r"(\d+(?:\.\d+)?)(万|亿|千|[wWkK])?(\+)?(?:票|分)?",
    re.IGNORECASE,
)


def parse_score(text: str) -> tuple[int, bool]:
    """Return ``(score, is_approximate)`` for a displayed score.

    The Wbox page currently uses values such as ``2085.1w``.  Any compact
    unit is approximate because the UI has already rounded the underlying
    value before exposing it to the accessibility tree.
    """

    raw = re.sub(r"[,，\s]", "", text)
    raw = re.sub(r"^(推荐值|推荐数|票数|得分|总分|：|:)+", "", raw)
    match = _SCORE_RE.fullmatch(raw)
    if not match:
        raise ValueError(f"Unrecognized score format: {text!r}")

    number, unit, plus = match.groups()
    multipliers = {
        None: 1,
        "": 1,
        "千": 1_000,
        "k": 1_000,
        "万": 10_000,
        "w": 10_000,
        "亿": 100_000_000,
    }
    multiplier = multipliers[(unit or "").lower()]
    score = int(
        (Decimal(number) * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    approximate = bool(unit) or bool(plus) or "." in number
    return score, approximate
