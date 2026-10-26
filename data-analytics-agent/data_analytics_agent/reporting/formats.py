"""Explicit Python numeric formats for newly authored presentation choices."""

import math
import re
from decimal import Decimal


def validate_number_format(number_format: str, value=None) -> str:
    """Validate a new format without changing how saved history is loaded.

    Python accepts ``0.00`` as an implicit general format. Require its numeric
    presentation type so an Excel-like pattern cannot silently become scientific
    notation. Explicit scientific/general choices remain available.
    """
    if (
        not isinstance(number_format, str)
        or not 1 <= len(number_format) <= 20
        or number_format[-1] not in "bdoXxneEfFgG%"
        or any(int(part) > 1000 for part in re.findall(r"\d+", number_format))
    ):
        raise ValueError(
            "Use an explicit Python numeric format such as ,.2f, .1%, d or .2e; "
            "Excel-like patterns such as 0.00 are not supported."
        )
    if value is not None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float, Decimal))
            or not math.isfinite(float(value))
        ):
            raise ValueError("Metric formats require a finite saved numeric value.")
        candidates = [value]
    else:
        candidates = [1, 1.25, Decimal("1.25")]
    for candidate in candidates:
        try:
            format(candidate, number_format)
        except (ValueError, TypeError):
            continue
        return number_format
    raise ValueError(
        "This Python numeric format is not valid for the saved metric type."
    )
