from __future__ import annotations

import hashlib
import hmac
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from ...config import settings


class PayPalError(Exception):
    pass


TRANSACTION_SEARCH_SCOPE = "https://uri.paypal.com/services/reporting/search/read"


def mask_secret_hint(value: str | None) -> str:
    """Return a non-reversible hint. Full credentials never leave the backend."""
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return f"••••{value[-4:]}"


class PayPalClient:
    """Thin PayPal REST client with environment-aware, cached OAuth tokens.

    Credentials live only in backend environment variables. The persisted runtime
    state selects which credential set is active; it never stores secrets.
    """

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_key: tuple[str, str] | None = None
        self._token_expires_at: float = 0.0
        self._lock = threading.Lock()
        self._runtime_environment: str | None = None
        self._runtime_enabled: bool | None = None

    def configure_runtime(self, environment: str | None, enabled: bool | None) -> None:
        environment = environment if environment in ("sandbox", "live") else None
        changed = environment != self._runtime_environment
        self._runtime_environment = environment
        self._runtime_enabled = enabled
        if changed:
            with self._lock:
                self._token = None
                self._token_key = None
                self._token_expires_at = 0.0

    @property
    def environment(self) -> str:
        if self._runtime_environment in ("sandbox", "live"):
            return self._runtime_environment
        return settings.paypal_environment

    @property
    def enabled(self) -> bool:
        return True if self._runtime_enabled is None else bool(self._runtime_enabled)

    @property
    def credentials(self) -> dict[str, str]:
        return settings.paypal_credentials(self.environment)

    @property
    def base_url(self) -> str:
        return self.credentials["base_url"]

    @property
    def webhook_id(self) -> str:
        return self.credentials["webhook_id"]

    @property
    def configured(self) -> bool:
        creds = self.credentials
        return bool(self.enabled and creds["client_id"] and creds["client_secret"])

    @property
    def mode(self) -> str:
        if not self.configured:
            return "simulated"
        return self.environment

    @property
    def client_id_hint(self) -> str:
        return mask_secret_hint(self.credentials["client_id"])

    @property
    def webhook_id_hint(self) -> str:
        return mask_secret_hint(self.webhook_id)

    def _access_token(self, scope: str | None = None) -> str:
        if not self.configured:
            raise PayPalError("PayPal credentials are not configured for this environment.")
        creds = self.credentials
        cache_key = (self.environment, creds["client_id"], scope or "")
        with self._lock:
            if (
                self._token
                and self._token_key == cache_key
                and time.monotonic() < self._token_expires_at - 60
            ):
                return self._token
            payload = {"grant_type": "client_credentials"}
            if scope:
                payload["scope"] = scope
            try:
                response = httpx.post(
                    f"{self.base_url}/v1/oauth2/token",
                    data=payload,
                    auth=(creds["client_id"], creds["client_secret"]),
                    timeout=20,
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise PayPalError("Could not reach PayPal. Check network connectivity.") from exc
            if response.status_code >= 400:
                raise PayPalError(
                    f"PayPal authentication failed ({response.status_code}). "
                    "Verify the credentials for the selected environment."
                )
            data = response.json()
            self._token = data["access_token"]
            self._token_key = cache_key
            self._token_expires_at = time.monotonic() + int(data.get("expires_in", 300))
            return self._token

    def _headers(
        self, idempotency_key: str | None = None, scope: str | None = None
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._access_token(scope)}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if idempotency_key:
            headers["PayPal-Request-Id"] = idempotency_key[:108]
        return headers

    @staticmethod
    def _provider_error(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return ""
        details = data.get("details") or []
        if details and isinstance(details, list):
            first = details[0] or {}
            issue = first.get("issue") or first.get("description")
            if issue:
                return str(issue)[:160]
        return str(data.get("message") or "")[:160]

    def create_order(
        self,
        *,
        invoice_id: int,
        invoice_number: str,
        amount: Decimal,
        currency: str,
        return_url: str,
        cancel_url: str,
        description: str,
        request_id: str | None = None,
    ) -> dict:
        if not self.configured:
            return {
                "id": None,
                "mode": "simulated",
                "status": "SIMULATED_CHECKOUT",
                "approve_url": None,
                "create_time": None,
                "note": "PayPal is not configured. Use the labelled simulated payment action.",
            }
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": f"invoice-{invoice_id}",
                    "custom_id": f"invoice:{invoice_id}",
                    "description": description[:127],
                    "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
                }
            ],
            "application_context": {
                "brand_name": "FINOVEXA AI",
                "user_action": "PAY_NOW",
                "return_url": return_url,
                "cancel_url": cancel_url,
                "shipping_preference": "NO_SHIPPING",
            },
        }
        try:
            response = httpx.post(
                f"{self.base_url}/v2/checkout/orders",
                json=payload,
                headers=self._headers(
                    idempotency_key=request_id
                    or f"finovexa-invoice-{invoice_id}-{invoice_number}-{amount}"
                ),
                timeout=25,
            )
        except httpx.HTTPError as exc:
            raise PayPalError("Could not create a PayPal order. Try again later.") from exc
        if response.status_code >= 400:
            detail = self._provider_error(response)
            raise PayPalError(
                f"PayPal rejected the order ({response.status_code})."
                + (f" {detail}" if detail else "")
            )
        data = response.json()
        approve_url = next(
            (link["href"] for link in data.get("links", []) if link.get("rel") == "approve"), None
        )
        return {
            "id": data.get("id"),
            "mode": self.mode,
            "status": data.get("status"),
            "approve_url": approve_url,
            "create_time": data.get("create_time"),
            "note": f"PayPal {self.mode} checkout order created.",
        }

    @staticmethod
    def _capture_from_order(data: dict) -> dict:
        purchase_unit = (data.get("purchase_units") or [{}])[0]
        capture = ((purchase_unit.get("payments") or {}).get("captures") or [{}])[0]
        amount = capture.get("amount") or purchase_unit.get("amount") or {}
        return {
            "order_id": data.get("id"),
            "status": data.get("status"),
            "capture_id": capture.get("id"),
            "capture_status": capture.get("status"),
            "amount": amount.get("value"),
            "currency": amount.get("currency_code"),
            "custom_id": purchase_unit.get("custom_id"),
            "payer_email": (data.get("payer") or {}).get("email_address"),
            "create_time": data.get("create_time"),
        }

    def capture_order(self, order_id: str, request_id: str | None = None) -> dict:
        if not self.configured:
            raise PayPalError("PayPal is not configured.")
        try:
            response = httpx.post(
                f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
                json={},
                headers=self._headers(
                    idempotency_key=request_id or f"finovexa-capture-{order_id}"
                ),
                timeout=25,
            )
        except httpx.HTTPError as exc:
            raise PayPalError("Could not reach PayPal to capture this payment.") from exc
        if response.status_code >= 400:
            detail = self._provider_error(response)
            raise PayPalError(
                f"PayPal capture failed ({response.status_code})."
                + (f" {detail}" if detail else "")
            )
        return self._capture_from_order(response.json())

    def get_order(self, order_id: str) -> dict:
        if not self.configured:
            raise PayPalError("PayPal is not configured.")
        try:
            response = httpx.get(
                f"{self.base_url}/v2/checkout/orders/{order_id}",
                headers=self._headers(),
                timeout=20,
            )
        except httpx.HTTPError as exc:
            raise PayPalError("Could not reach PayPal to retrieve this order.") from exc
        if response.status_code >= 400:
            raise PayPalError(f"PayPal could not find the order ({response.status_code}).")
        return self._capture_from_order(response.json())

    def get_capture(self, capture_id: str) -> dict:
        if not self.configured:
            raise PayPalError("PayPal is not configured.")
        try:
            response = httpx.get(
                f"{self.base_url}/v2/payments/captures/{capture_id}",
                headers=self._headers(),
                timeout=20,
            )
        except httpx.HTTPError as exc:
            raise PayPalError("Could not reach PayPal to retrieve this capture.") from exc
        if response.status_code >= 400:
            raise PayPalError(f"PayPal could not find the capture ({response.status_code}).")
        data = response.json()
        amount = data.get("amount") or {}
        return {
            "capture_id": data.get("id"),
            "status": data.get("status"),
            "amount": amount.get("value"),
            "currency": amount.get("currency_code"),
            "custom_id": data.get("custom_id"),
            "create_time": data.get("create_time"),
            "seller_protection": (data.get("seller_protection") or {}).get("status"),
        }

    def create_refund(
        self,
        *,
        capture_id: str,
        amount: Decimal,
        currency: str,
        request_id: str,
        note: str,
    ) -> dict:
        if not self.configured:
            raise PayPalError("PayPal is not configured.")
        payload = {
            "amount": {"value": f"{amount:.2f}", "currency_code": currency},
            "note_to_payer": note[:255],
        }
        try:
            response = httpx.post(
                f"{self.base_url}/v2/payments/captures/{capture_id}/refund",
                json=payload,
                headers=self._headers(idempotency_key=request_id),
                timeout=25,
            )
        except httpx.HTTPError as exc:
            raise PayPalError("Could not reach PayPal to create this refund.") from exc
        if response.status_code >= 400:
            detail = self._provider_error(response)
            raise PayPalError(
                f"PayPal rejected the refund ({response.status_code})."
                + (f" {detail}" if detail else "")
            )
        data = response.json()
        refund_amount = data.get("amount") or {}
        return {
            "refund_id": data.get("id"),
            "status": data.get("status"),
            "amount": refund_amount.get("value"),
            "currency": refund_amount.get("currency_code"),
            "create_time": data.get("create_time"),
        }

    def get_refund(self, refund_id: str) -> dict:
        if not self.configured:
            raise PayPalError("PayPal is not configured.")
        try:
            response = httpx.get(
                f"{self.base_url}/v2/payments/refunds/{refund_id}",
                headers=self._headers(),
                timeout=20,
            )
        except httpx.HTTPError as exc:
            raise PayPalError("Could not reach PayPal to retrieve this refund.") from exc
        if response.status_code >= 400:
            raise PayPalError(f"PayPal could not find the refund ({response.status_code}).")
        data = response.json()
        amount = data.get("amount") or {}
        return {
            "refund_id": data.get("id"),
            "status": data.get("status"),
            "amount": amount.get("value"),
            "currency": amount.get("currency_code"),
        }

    def check_connection(self) -> dict:
        if not self.configured:
            raise PayPalError("PayPal credentials are not configured for this environment.")
        self._access_token()
        return {
            "connected": True,
            "mode": self.mode,
            "environment": self.environment,
            "webhook_configured": bool(self.webhook_id),
        }

    def search_transactions(
        self,
        *,
        start_date: datetime,
        end_date: datetime,
        page: int = 1,
        page_size: int = 500,
        transaction_id: str | None = None,
        transaction_status: str | None = None,
    ) -> dict:
        """Official Reporting API search for the credential-owning merchant only.

        PayPal limits a single search window to 31 days. Third-party merchant
        history requires PayPal partner-network approval, which this client
        cannot grant itself.
        """
        if not self.configured:
            raise PayPalError("PayPal credentials are not configured for this environment.")
        params: dict[str, Any] = {
            "start_date": start_date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_date": end_date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fields": "transaction_info,payer_info",
            "page_size": min(max(int(page_size), 1), 500),
            "page": max(int(page), 1),
        }
        if transaction_id:
            params["transaction_id"] = transaction_id
        if transaction_status:
            params["transaction_status"] = transaction_status
        try:
            response = httpx.get(
                f"{self.base_url}/v1/reporting/transactions",
                params=params,
                headers=self._headers(scope=TRANSACTION_SEARCH_SCOPE),
                timeout=40,
            )
        except httpx.HTTPError as exc:
            raise PayPalError("Could not reach PayPal to search transactions.") from exc
        if response.status_code == 401:
            raise PayPalError(
                "PayPal rejected the transaction search token (401). "
                "Re-authorise the application for the reporting search scope."
            )
        if response.status_code == 403:
            raise PayPalError(
                "PayPal denied transaction-history access (403). The application needs the "
                "transaction-search scope and an eligible merchant account. Access to another "
                "merchant's history requires PayPal partner-network approval."
            )
        if response.status_code == 429:
            raise PayPalError(
                "PayPal rate-limited the transaction search (429). Wait a few minutes and retry."
            )
        if response.status_code >= 400:
            detail = self._provider_error(response)
            raise PayPalError(
                f"PayPal rejected the transaction search ({response.status_code})."
                + (f" {detail}" if detail else "")
            )
        try:
            return response.json()
        except ValueError as exc:
            raise PayPalError("PayPal returned an unreadable transaction search response.") from exc

    def verify_webhook(self, headers: dict[str, str], event: dict) -> bool:
        if not self.configured or not self.webhook_id:
            return False
        payload = {
            "auth_algo": headers.get("paypal-auth-algo", ""),
            "cert_url": headers.get("paypal-cert-url", ""),
            "transmission_id": headers.get("paypal-transmission-id", ""),
            "transmission_sig": headers.get("paypal-transmission-sig", ""),
            "transmission_time": headers.get("paypal-transmission-time", ""),
            "webhook_id": self.webhook_id,
            "webhook_event": event,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/v1/notifications/verify-webhook-signature",
                json=payload,
                headers=self._headers(),
                timeout=25,
            )
        except httpx.HTTPError:
            return False
        if response.status_code >= 400:
            return False
        return response.json().get("verification_status") == "SUCCESS"


def demo_signature(body: bytes) -> str:
    return "sha256=" + hmac.new(
        settings.PAYPAL_DEMO_WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


def verify_demo_signature(body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(demo_signature(body), signature)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


paypal_client = PayPalClient()
