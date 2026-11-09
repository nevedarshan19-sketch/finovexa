from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import httpx

from ...config import settings


class MetalsError(Exception):
    pass


class MetalsClient:
    @property
    def configured(self) -> bool:
        return bool(settings.METALS_API_KEY)

    def fetch(self) -> dict:
        if not self.configured:
            raise MetalsError("Metals provider is not configured.")
        try:
            response = httpx.get(
                settings.METALS_API_URL,
                params={
                    "api_key": settings.METALS_API_KEY,
                    "currency": "USD",
                    "unit": "toz",
                },
                timeout=20,
            )
        except httpx.HTTPError as exc:
            raise MetalsError("Could not reach the metals data provider.") from exc
        if response.status_code == 429:
            raise MetalsError("Metals provider rate limit reached.")
        if response.status_code >= 400:
            raise MetalsError(f"Metals provider failed ({response.status_code}).")
        body = response.json()
        metals = body.get("metals") or {}
        if "gold" not in metals or "silver" not in metals:
            raise MetalsError("Metals provider response did not include gold and silver.")
        return {
            "gold": {
                "price": Decimal(str(metals["gold"])),
                "as_of": body.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                "source": "Metals.dev",
            },
            "silver": {
                "price": Decimal(str(metals["silver"])),
                "as_of": body.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                "source": "Metals.dev",
            },
        }


metals_client = MetalsClient()
