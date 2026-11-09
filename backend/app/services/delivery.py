from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from ..config import settings


class DeliveryError(Exception):
    pass


@dataclass
class DeliveryResult:
    channel: str
    status: str
    recipient: str
    provider: str
    note: str
    provider_message_id: str | None = None


def send_email(*, recipient: str, subject: str, body: str) -> DeliveryResult:
    """Send via SMTP only when delivery is enabled and configured; otherwise simulate."""
    if not settings.email_ready:
        return DeliveryResult(
            channel="email",
            status="simulated_sent",
            recipient=recipient,
            provider="none",
            note=(
                "Email delivery is disabled or not configured. Nothing was sent externally; "
                "this reminder is recorded as a simulation."
            ),
        )

    message = EmailMessage()
    message["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.DELIVERY_TIMEOUT_SECONDS
        ) as smtp:
            smtp.ehlo()
            if settings.SMTP_STARTTLS:
                smtp.starttls()
                smtp.ehlo()
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise DeliveryError(f"Email delivery failed: {type(exc).__name__}.") from exc

    return DeliveryResult(
        channel="email",
        status="sent",
        recipient=recipient,
        provider="smtp",
        note="The configured SMTP server accepted the message for delivery.",
    )


def send_sms(*, recipient: str, body: str) -> DeliveryResult:
    """Send via Twilio only when delivery is enabled and configured; otherwise simulate."""
    if not settings.sms_ready:
        return DeliveryResult(
            channel="sms",
            status="simulated_sent",
            recipient=recipient,
            provider="none",
            note=(
                "SMS delivery is disabled or not configured. Nothing was sent externally; "
                "this reminder is recorded as a simulation."
            ),
        )

    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    )
    try:
        response = httpx.post(
            url,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            data={
                "To": recipient,
                "From": settings.TWILIO_FROM_NUMBER,
                "Body": body,
            },
            timeout=settings.DELIVERY_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise DeliveryError(f"SMS delivery failed: {type(exc).__name__}.") from exc

    if response.status_code >= 400:
        raise DeliveryError(
            f"Twilio rejected the message (HTTP {response.status_code}). "
            "Check the sender number and recipient opt-in status."
        )

    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return DeliveryResult(
        channel="sms",
        status="sent",
        recipient=recipient,
        provider="twilio",
        note="Twilio accepted the SMS for delivery.",
        provider_message_id=payload.get("sid"),
    )


def check_email_connection() -> str:
    if not settings.email_configured:
        raise DeliveryError("SMTP host and sender address are not configured.")
    try:
        with smtplib.SMTP(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.DELIVERY_TIMEOUT_SECONDS
        ) as smtp:
            smtp.ehlo()
            if settings.SMTP_STARTTLS:
                smtp.starttls()
                smtp.ehlo()
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.noop()
    except (OSError, smtplib.SMTPException) as exc:
        raise DeliveryError(f"SMTP connection failed: {type(exc).__name__}.") from exc
    return "SMTP connection and credentials accepted."


def check_sms_connection() -> str:
    if not settings.sms_configured:
        raise DeliveryError("Twilio account SID, auth token and sender number are not configured.")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}.json"
    try:
        response = httpx.get(
            url,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            timeout=settings.DELIVERY_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise DeliveryError(f"Twilio check failed: {type(exc).__name__}.") from exc
    if response.status_code >= 400:
        raise DeliveryError(f"Twilio rejected the credentials (HTTP {response.status_code}).")
    return "Twilio credentials accepted."
