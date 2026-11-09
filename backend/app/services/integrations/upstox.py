from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlencode

import httpx

from ...config import settings


class UpstoxError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class UpstoxClient:
    @property
    def base_url(self) -> str:
        return settings.UPSTOX_BASE_URL.rstrip("/")

    @property
    def order_base_url(self) -> str:
        return settings.UPSTOX_ORDER_BASE_URL.rstrip("/")

    @property
    def token(self) -> str:
        return settings.UPSTOX_ACCESS_TOKEN

    @property
    def order_proxy(self) -> str | None:
        return settings.UPSTOX_ORDER_PROXY_URL or None

    @property
    def configured(self) -> bool:
        return settings.upstox_configured

    @property
    def live_trading_enabled(self) -> bool:
        return settings.UPSTOX_LIVE_TRADING_ENABLED

    @property
    def live_trading_ready(self) -> bool:
        return settings.upstox_live_ready

    @property
    def static_ip_proxy_configured(self) -> bool:
        return bool(settings.UPSTOX_ORDER_PROXY_URL)

    def authorization_url(self) -> str | None:
        if not settings.UPSTOX_CLIENT_ID:
            return None
        params = {
            "client_id": settings.UPSTOX_CLIENT_ID,
            "redirect_uri": settings.UPSTOX_REDIRECT_URI,
            "response_type": "code",
        }
        return f"https://api.upstox.com/v2/login/authorization/dialog?{urlencode(params)}"

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise UpstoxError("Upstox access token is not configured.")
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return ""
        message = ""
        errors = body.get("errors") if isinstance(body, dict) else None
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            message = str(errors[0].get("message") or errors[0].get("errorCode") or "")
        if not message and isinstance(body, dict):
            message = str(body.get("message") or "")
        message = " ".join(message.split())[:300]
        if "static ip" in message.lower():
            message += (
                " Upstox requires orders from a registered static IP. Configure "
                "UPSTOX_ORDER_PROXY_URL with a static-IP egress or deploy behind one."
            )
        return message

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        order: bool = False,
    ) -> Any:
        base = self.order_base_url if order else self.base_url
        headers = self._headers()
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        kwargs: dict[str, Any] = {"params": params, "headers": headers, "timeout": 20}
        if json_body is not None:
            kwargs["json"] = json_body
        if order and self.order_proxy:
            kwargs["proxy"] = self.order_proxy
        try:
            response = httpx.request(method, f"{base}{path}", **kwargs)
        except httpx.TimeoutException as exc:
            raise UpstoxError(
                "Upstox did not answer in time. The order may have reached the broker; "
                "check the Upstox order book before retrying."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstoxError("Could not reach Upstox.") from exc
        if response.status_code == 401:
            raise UpstoxError(
                "Upstox authorization expired. Re-authorize and update the token.",
                status_code=401,
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            raise UpstoxError(
                f"Upstox rate limit reached. Retry after {retry_after}s.", status_code=429
            )
        if response.status_code >= 400:
            detail = self._error_detail(response)
            raise UpstoxError(
                detail or f"Upstox request failed ({response.status_code}).",
                status_code=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise UpstoxError("Upstox returned a response that could not be read.") from exc
        if not isinstance(body, dict) or body.get("status") != "success":
            detail = self._error_detail(response)
            raise UpstoxError(detail or "Upstox returned an unsuccessful response.")
        return body.get("data", {})

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def place_order(self, payload: dict[str, Any]) -> dict:
        data = self._request("POST", "/order/place", json_body=payload, order=True)
        if not isinstance(data, dict) or not data.get("order_id"):
            raise UpstoxError(
                "Upstox accepted the request without returning an order id. "
                "Check the Upstox order book before retrying."
            )
        return data

    def get_order_details(self, order_id: str) -> dict:
        data = self._request("GET", "/order/details", params={"order_id": order_id}, order=True)
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        return data if isinstance(data, dict) else {}

    def get_order_book(self) -> list[dict]:
        data = self._request("GET", "/order/retrieve-all", order=True)
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            data = data["data"]
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    def cancel_order(self, order_id: str) -> dict:
        data = self._request(
            "DELETE", "/order/cancel", params={"order_id": order_id}, order=True
        )
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _parse_quote(quote: dict) -> dict | None:
        ohlc = quote.get("ohlc") or {}
        last_price = quote.get("last_price")
        close = ohlc.get("close")
        if last_price is None:
            return None
        change_pct = ((last_price - close) / close * 100) if close else 0
        return {
            "price": last_price,
            "previous_close": close or last_price,
            "change_pct": change_pct,
            "as_of": quote.get("last_trade_time") or quote.get("timestamp"),
            "source": "Upstox API",
            "volume": quote.get("volume"),
            "session_status": "live",
            "instrument_token": quote.get("instrument_token"),
        }

    def get_quote(self, instrument_key: str) -> dict:
        data = self._get("/market-quote/quotes", {"instrument_key": instrument_key})
        quote = next(iter(data.values()), None)
        if not quote:
            raise UpstoxError("Upstox did not return a quote for this instrument.")
        parsed = self._parse_quote(quote)
        if parsed is None:
            raise UpstoxError("Upstox quote is missing a last price.")
        return parsed

    def get_quotes(self, instrument_keys: list[str]) -> dict[str, dict]:
        keys = [key for key in dict.fromkeys(instrument_keys) if key]
        if not keys:
            return {}
        data = self._get("/market-quote/quotes", {"instrument_key": ",".join(keys)})
        quotes: dict[str, dict] = {}
        for key, quote in data.items():
            if not isinstance(quote, dict):
                continue
            parsed = self._parse_quote(quote)
            if parsed is None:
                continue
            quotes[key] = parsed
            token = parsed.get("instrument_token")
            if token:
                quotes[token] = parsed
        return quotes

    def get_historical(self, instrument_key: str, from_date: date, to_date: date) -> list[dict]:
        data = self._get(
            f"/historical-candle/{instrument_key}/day/{to_date.isoformat()}/{from_date.isoformat()}"
        )
        candles = data.get("candles") or []
        return [
            {
                "date": candle[0][:10],
                "open": candle[1],
                "high": candle[2],
                "low": candle[3],
                "close": candle[4],
                "volume": candle[5] if len(candle) > 5 else None,
            }
            for candle in candles
        ]

    def get_option_contracts(self, instrument_key: str) -> list[dict]:
        data = self._get("/option/contract", {"instrument_key": instrument_key})
        return data if isinstance(data, list) else []

    def get_option_chain(self, instrument_key: str, expiry_date: str) -> list[dict]:
        data = self._get(
            "/option/chain",
            {"instrument_key": instrument_key, "expiry_date": expiry_date},
        )
        return data if isinstance(data, list) else []

    def get_profile(self) -> dict:
        return self._get("/user/profile")


upstox_client = UpstoxClient()
