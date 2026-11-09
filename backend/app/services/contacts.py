from __future__ import annotations

import re

from fastapi import HTTPException


def normalize_phone(raw: str | None) -> str | None:
    """Normalize a customer mobile number to +91XXXXXXXXXX or an international E.164 value."""
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not digits:
        raise HTTPException(status_code=400, detail="Enter a valid mobile number.")
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    if len(digits) == 11 and digits.startswith("0") and digits[1] in "6789":
        return f"+91{digits[1:]}"
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return f"+{digits}"
    if 8 <= len(digits) <= 15:
        return f"+{digits}"
    raise HTTPException(
        status_code=400,
        detail="Enter a valid mobile number: 10 digits, or the full number with country code.",
    )
