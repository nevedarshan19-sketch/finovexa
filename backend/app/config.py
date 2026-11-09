from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    APP_NAME: str = "FINOVEXA AI"
    ENV: str = "development"
    API_PREFIX: str = "/api"
    SECRET_KEY: str = "dev-only-change-me-31f0c0de-4b9a8f2e6d1c"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 8 * 60
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'finovexa.db'}"
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    FRONTEND_URL: str = "http://localhost:5173"
    # Production runs against a clean database: no demo users, no demo business records.
    AUTO_SEED: bool = False
    DEMO_RESET_ENABLED: bool = False
    # Demo business starts with zero balances and no ledger records; tests enable the rich seed.
    SEED_DEMO_TRANSACTIONS: bool = False

    # Initial production accounts, provisioned once from environment values.
    # Existing accounts are never modified or overwritten.
    INITIAL_OWNER_NAME: str = ""
    INITIAL_OWNER_EMAIL: str = ""
    INITIAL_OWNER_PASSWORD: str = ""
    INITIAL_BUSINESS_NAME: str = ""
    INITIAL_SENIOR_ACCOUNTANT_NAME: str = ""
    INITIAL_SENIOR_ACCOUNTANT_EMAIL: str = ""
    INITIAL_SENIOR_ACCOUNTANT_PASSWORD: str = ""
    INITIAL_JUNIOR_ACCOUNTANT_NAME: str = ""
    INITIAL_JUNIOR_ACCOUNTANT_EMAIL: str = ""
    INITIAL_JUNIOR_ACCOUNTANT_PASSWORD: str = ""

    DEMO_EMAIL: str = "demo@finovexa.ai"
    DEMO_PASSWORD: str = "Demo1234!"
    DEMO_EMPLOYEE_EMAIL: str = "employee@finovexa.ai"
    DEMO_EMPLOYEE_PASSWORD: str = "Employee1234!"

    # Seeded accounting-practice accounts. Junior accountants can work only on
    # assigned clients and customers see only their own practice records.
    DEMO_SENIOR_ACCOUNTANT_NAME: str = "Anita Desai"
    DEMO_SENIOR_ACCOUNTANT_EMAIL: str = "senior@finovexa.ai"
    DEMO_SENIOR_ACCOUNTANT_PASSWORD: str = "Senior1234!"
    DEMO_JUNIOR_ACCOUNTANT_NAME: str = "Rahul Mehta"
    DEMO_JUNIOR_ACCOUNTANT_EMAIL: str = "junior@finovexa.ai"
    DEMO_JUNIOR_ACCOUNTANT_PASSWORD: str = "Junior1234!"
    DEMO_CLIENT_NAME: str = "Kabir Rao"
    DEMO_CLIENT_EMAIL: str = "client@finovexa.ai"
    DEMO_CLIENT_PASSWORD: str = "Client1234!"

    ACCOUNTING_UPLOAD_DIR: str = str(BASE_DIR / "uploads" / "accounting")
    ACCOUNTING_MAX_UPLOAD_MB: int = 10
    ACCOUNTING_TALLY_RETENTION_DAYS: int = 2555
    # Where uploaded documents live: "local" writes to ACCOUNTING_UPLOAD_DIR,
    # "database" stores the bytes in the database so they survive ephemeral disks.
    FILE_STORAGE: str = "local"
    # Fernet key (url-safe base64, 32 bytes) for Payment Connect statement originals.
    # When unset, a key is derived from SECRET_KEY so uploads are still encrypted at rest.
    PAYMENT_DOCUMENT_KEY: str = ""

    DEVELOPER_NAME: str = "Platform Developer"
    DEVELOPER_EMAIL: str = ""
    DEVELOPER_PASSWORD: str = ""

    LLM_PROVIDER: str = "none"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT_SECONDS: int = 45

    # PayPal stays in sandbox unless an owner explicitly selects live with live keys present.
    PAYPAL_ENVIRONMENT: str = "sandbox"
    PAYPAL_SANDBOX_CLIENT_ID: str = ""
    PAYPAL_SANDBOX_CLIENT_SECRET: str = ""
    PAYPAL_SANDBOX_WEBHOOK_ID: str = ""
    PAYPAL_SANDBOX_BASE_URL: str = "https://api-m.sandbox.paypal.com"
    PAYPAL_LIVE_CLIENT_ID: str = ""
    PAYPAL_LIVE_CLIENT_SECRET: str = ""
    PAYPAL_LIVE_WEBHOOK_ID: str = ""
    PAYPAL_LIVE_BASE_URL: str = "https://api-m.paypal.com"
    # Legacy single-environment variables. They are only used when the matching
    # PAYPAL_SANDBOX_* / PAYPAL_LIVE_* pair is absent, so existing deployments keep working.
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_BASE_URL: str = "https://api-m.sandbox.paypal.com"
    PAYPAL_WEBHOOK_ID: str = ""
    PAYPAL_DEMO_WEBHOOK_SECRET: str = "demo-paypal-webhook-secret"

    UPSTOX_CLIENT_ID: str = ""
    UPSTOX_CLIENT_SECRET: str = ""
    UPSTOX_REDIRECT_URI: str = "http://localhost:8000/api/integrations/upstox/callback"
    UPSTOX_ACCESS_TOKEN: str = ""
    UPSTOX_BASE_URL: str = "https://api.upstox.com/v2"
    UPSTOX_SANDBOX_URL: str = "https://sandbox-api.upstox.com/v2"
    UPSTOX_ORDER_BASE_URL: str = "https://api-hft.upstox.com/v2"
    UPSTOX_ORDER_PROXY_URL: str = ""
    UPSTOX_LIVE_TRADING_ENABLED: bool = False

    METALS_API_KEY: str = ""
    METALS_API_URL: str = "https://api.metals.dev/v1/latest"

    NEWS_API_KEY: str = ""

    # Collection reminders. Both transports stay off until explicitly enabled
    # and configured; otherwise approvals record a clearly labelled simulation.
    EMAIL_DELIVERY_ENABLED: bool = False
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "FINOVEXA AI"
    SMTP_STARTTLS: bool = True
    SMS_DELIVERY_ENABLED: bool = False
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""
    DELIVERY_TIMEOUT_SECONDS: int = 20

    # Keyless NSE quote source for the Investment Research market panel.
    YAHOO_FINANCE_BASE_URL: str = "https://query1.finance.yahoo.com"
    INDIA_MARKET_CACHE_SECONDS: int = 60

    # NIFTY 50 recommendation screen (technical model, informational only).
    NIFTY_RECOMMENDATION_CACHE_SECONDS: int = 600
    NIFTY_UPSIDE_THRESHOLD_PCT: float = 5.0
    NIFTY_CONSTITUENT_REFRESH: bool = True

    QUOTE_CACHE_MINUTES: int = 15
    NEWS_CACHE_MINUTES: int = 60

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def llm_configured(self) -> bool:
        return self.LLM_PROVIDER != "none" and bool(self.LLM_API_KEY)

    @property
    def legacy_paypal_environment(self) -> str:
        return "live" if "sandbox" not in self.PAYPAL_BASE_URL else "sandbox"

    def paypal_environment_configured(self, environment: str) -> bool:
        if environment == "live":
            return bool(
                (self.PAYPAL_LIVE_CLIENT_ID and self.PAYPAL_LIVE_CLIENT_SECRET)
                or (
                    self.legacy_paypal_environment == "live"
                    and self.PAYPAL_CLIENT_ID
                    and self.PAYPAL_CLIENT_SECRET
                )
            )
        return bool(
            (self.PAYPAL_SANDBOX_CLIENT_ID and self.PAYPAL_SANDBOX_CLIENT_SECRET)
            or (
                self.legacy_paypal_environment == "sandbox"
                and self.PAYPAL_CLIENT_ID
                and self.PAYPAL_CLIENT_SECRET
            )
        )

    def paypal_credentials(self, environment: str) -> dict[str, str]:
        if environment == "live":
            client_id = self.PAYPAL_LIVE_CLIENT_ID
            secret = self.PAYPAL_LIVE_CLIENT_SECRET
            webhook_id = self.PAYPAL_LIVE_WEBHOOK_ID
            base_url = self.PAYPAL_LIVE_BASE_URL
            if not (client_id and secret) and self.legacy_paypal_environment == "live":
                client_id, secret = self.PAYPAL_CLIENT_ID, self.PAYPAL_CLIENT_SECRET
                webhook_id = webhook_id or self.PAYPAL_WEBHOOK_ID
                base_url = self.PAYPAL_BASE_URL
        else:
            client_id = self.PAYPAL_SANDBOX_CLIENT_ID
            secret = self.PAYPAL_SANDBOX_CLIENT_SECRET
            webhook_id = self.PAYPAL_SANDBOX_WEBHOOK_ID
            base_url = self.PAYPAL_SANDBOX_BASE_URL
            if not (client_id and secret) and self.legacy_paypal_environment == "sandbox":
                client_id, secret = self.PAYPAL_CLIENT_ID, self.PAYPAL_CLIENT_SECRET
                webhook_id = webhook_id or self.PAYPAL_WEBHOOK_ID
                base_url = self.PAYPAL_BASE_URL or base_url
        return {
            "client_id": client_id,
            "client_secret": secret,
            "webhook_id": webhook_id or "",
            "base_url": (base_url or "").rstrip("/"),
        }

    @property
    def paypal_environment(self) -> str:
        return "live" if self.PAYPAL_ENVIRONMENT == "live" else "sandbox"

    @property
    def paypal_configured(self) -> bool:
        return self.paypal_environment_configured(self.paypal_environment)

    @property
    def upstox_configured(self) -> bool:
        return bool(self.UPSTOX_ACCESS_TOKEN)

    @property
    def upstox_live_ready(self) -> bool:
        return self.UPSTOX_LIVE_TRADING_ENABLED and self.upstox_configured

    @property
    def developer_configured(self) -> bool:
        return bool(self.DEVELOPER_EMAIL and self.DEVELOPER_PASSWORD)

    @property
    def paypal_mode(self) -> str:
        if not self.paypal_configured:
            return "simulated"
        return self.paypal_environment

    @property
    def email_configured(self) -> bool:
        return bool(self.SMTP_HOST and self.SMTP_FROM_EMAIL)

    @property
    def email_ready(self) -> bool:
        return self.EMAIL_DELIVERY_ENABLED and self.email_configured

    @property
    def sms_configured(self) -> bool:
        return bool(
            self.TWILIO_ACCOUNT_SID and self.TWILIO_AUTH_TOKEN and self.TWILIO_FROM_NUMBER
        )

    @property
    def sms_ready(self) -> bool:
        return self.SMS_DELIVERY_ENABLED and self.sms_configured


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
