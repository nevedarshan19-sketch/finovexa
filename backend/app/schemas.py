from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=120)
    business_name: str = Field(min_length=2, max_length=160)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
            raise ValueError("Password must include at least one letter and one number.")
        return value


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    role: str = "owner"
    owner_id: int | None = None
    is_demo: bool


class BusinessSummaryOut(BaseModel):
    business_name: str
    currency: str
    timezone: str


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    business_name: str
    currency: str
    timezone: str
    reporting_period: str
    min_cash_reserve: Decimal
    opening_cash_balance: Decimal
    opening_balance_date: date
    risk_tolerance: str
    research_interests: list[str]
    reminder_tone: str
    legal_name: str | None = None
    gstin: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    state_code: str | None = None
    postal_code: str | None = None
    business_phone: str | None = None
    business_email: str | None = None
    invoice_terms: str | None = None
    logo_data_url: str | None = None


class AuthOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
    profile: ProfileOut | None = None
    business: BusinessSummaryOut | None = None


class EmployeeCreateIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=120)

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
            raise ValueError("Password must include at least one letter and one number.")
        return value


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    is_active: bool
    is_demo: bool
    created_at: datetime


class EmployeeStatusIn(BaseModel):
    is_active: bool


class DeveloperAccountCreateIn(BaseModel):
    role: Literal["owner", "employee", "senior_accountant", "junior_accountant"]
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=120)
    business_name: str | None = Field(default=None, min_length=2, max_length=160)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    owner_id: int | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
            raise ValueError("Password must include at least one letter and one number.")
        return value

    @model_validator(mode="after")
    def validate_target(self) -> "DeveloperAccountCreateIn":
        if self.role == "owner" and not self.business_name:
            raise ValueError("Business name is required for an owner account.")
        if self.role == "employee" and self.owner_id is None:
            raise ValueError("Select the owner this employee belongs to.")
        return self


class DeveloperAccountUpdateIn(BaseModel):
    is_active: bool | None = None
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
            raise ValueError("Password must include at least one letter and one number.")
        return value

    @model_validator(mode="after")
    def require_change(self) -> "DeveloperAccountUpdateIn":
        if (
            self.is_active is None
            and self.full_name is None
            and self.email is None
            and self.password is None
        ):
            raise ValueError("Provide at least one change.")
        return self


class ProfileUpdateIn(BaseModel):
    business_name: str | None = Field(default=None, min_length=2, max_length=160)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    timezone: str | None = Field(default=None, max_length=64)
    reporting_period: Literal["weekly", "monthly", "quarterly"] | None = None
    min_cash_reserve: Decimal | None = Field(default=None, ge=0, le=Decimal("1000000000"))
    opening_cash_balance: Decimal | None = Field(default=None, ge=0, le=Decimal("1000000000"))
    risk_tolerance: Literal["conservative", "balanced", "growth"] | None = None
    research_interests: list[str] | None = None
    reminder_tone: Literal["friendly", "professional", "firm"] | None = None
    legal_name: str | None = Field(default=None, max_length=160)
    gstin: str | None = Field(default=None, max_length=15)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    postal_code: str | None = Field(default=None, max_length=10)
    business_phone: str | None = Field(default=None, max_length=40)
    business_email: EmailStr | None = None
    invoice_terms: str | None = Field(default=None, max_length=3000)
    logo_data_url: str | None = Field(default=None, max_length=400000)

    @field_validator("research_interests")
    @classmethod
    def cap_interests(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return [item.strip()[:60] for item in value if item.strip()][:10]


class InvoiceItemIn(BaseModel):
    description: str = Field(min_length=1, max_length=255)
    quantity: Decimal = Field(gt=0, le=Decimal("100000"))
    unit_price: Decimal = Field(ge=0, le=Decimal("100000000"))
    product_id: int | None = None
    gst_rate: Decimal | None = Field(default=None, ge=0, le=100)


class EmployeeEntryIn(BaseModel):
    entry_type: Literal["invoice", "sale", "purchase"]
    counterparty: str = Field(min_length=2, max_length=160)
    counterparty_email: EmailStr | None = None
    counterparty_phone: str | None = Field(default=None, max_length=40)
    description: str = Field(min_length=2, max_length=255)
    amount: Decimal | None = Field(default=None, gt=0, le=Decimal("100000000"))
    amount_received: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000"))
    category: str | None = Field(default=None, max_length=60)
    payment_method: Literal[
        "cash", "upi", "bank", "card", "cheque", "paypal", "credit", "other"
    ] | None = None
    payment_reference: str | None = Field(default=None, max_length=120)
    payment_date: date | None = None
    entry_date: date
    due_date: date | None = None
    tax_rate: Decimal = Field(default=Decimal("18"), ge=0, le=100)
    items: list[InvoiceItemIn] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_shape(self) -> "EmployeeEntryIn":
        if self.amount is None and not self.items:
            raise ValueError("Provide an amount or at least one line item.")
        if self.entry_type == "purchase":
            if self.amount is None and not self.items:
                raise ValueError("Purchase entries need a total amount or line items.")
        elif self.payment_method is None:
            raise ValueError("Choose how the sale was paid, or select credit for an unpaid invoice.")
        if (
            self.entry_type == "invoice"
            and self.amount_received
            and self.amount_received > 0
            and self.payment_method in (None, "credit")
        ):
            raise ValueError("Choose the payment method used for the amount received.")
        if self.entry_type != "invoice" and self.amount_received:
            raise ValueError("Only an invoice entry can record a part-payment.")
        if self.entry_type != "invoice" and (self.payment_reference or self.payment_date):
            raise ValueError("Only an invoice entry can record payment details.")
        if self.payment_date and not self.amount_received:
            raise ValueError("Enter the amount received before choosing a payment date.")
        if self.due_date and self.due_date < self.entry_date:
            raise ValueError("Due date cannot be before the entry date.")
        return self


class EmployeeEntryUpdateIn(BaseModel):
    counterparty: str | None = Field(default=None, min_length=2, max_length=160)
    counterparty_email: EmailStr | None = None
    counterparty_phone: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, min_length=2, max_length=255)
    amount: Decimal | None = Field(default=None, gt=0, le=Decimal("100000000"))
    category: str | None = Field(default=None, max_length=60)
    payment_method: Literal[
        "cash", "upi", "bank", "card", "cheque", "paypal", "credit", "other"
    ] | None = None
    entry_date: date | None = None
    due_date: date | None = None
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100)
    items: list[InvoiceItemIn] | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)


class InvoiceCreateIn(BaseModel):
    customer_id: int
    number: str = Field(min_length=1, max_length=40)
    issue_date: date
    due_date: date
    tax_rate: Decimal = Field(default=Decimal("18"), ge=0, le=100)
    items: list[InvoiceItemIn] = Field(min_length=1, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)


class PaymentRecordIn(BaseModel):
    amount: Decimal = Field(gt=0, le=Decimal("100000000"))
    method: Literal["bank", "upi", "cash", "paypal", "card", "cheque", "other"] = "bank"
    reference: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)
    received_at: datetime | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class PaymentUpdateIn(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, le=Decimal("100000000"))
    method: Literal["bank", "upi", "cash", "paypal", "card", "cheque", "other"] | None = None
    reference: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)
    received_at: datetime | None = None


class PaymentReverseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class MatchPaymentIn(BaseModel):
    invoice_id: int
    confirm: bool = False


class ReminderDraftIn(BaseModel):
    tone: Literal["friendly", "professional", "firm"] | None = None
    instructions: str | None = Field(default=None, max_length=500)
    channel: Literal["email", "sms"] = "email"
    stage: Literal[
        "due_in_7", "due_today", "overdue_1_7", "overdue_8_14", "overdue_15_plus"
    ] | None = None


class ReminderApprovalIn(BaseModel):
    invoice_id: int
    channel: Literal["email", "sms"] = "email"
    recipient: str = Field(min_length=3, max_length=160)
    subject: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=20, max_length=4000)
    stage: Literal[
        "due_in_7", "due_today", "overdue_1_7", "overdue_8_14", "overdue_15_plus"
    ] | None = None

    @model_validator(mode="after")
    def check_channel_format(self) -> "ReminderApprovalIn":
        if self.channel == "sms":
            if len(self.body) > 320:
                raise ValueError("SMS text must be 320 characters or fewer.")
            if not re.fullmatch(r"\+?[0-9][0-9\s\-()]{6,19}", self.recipient.strip()):
                raise ValueError("Enter a valid mobile number for the SMS recipient.")
        else:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", self.recipient.strip()):
                raise ValueError("Enter a valid email address for the reminder recipient.")
        return self


class InvestmentApprovalIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: Literal["buy", "sell"] = "buy"
    quantity: int = Field(gt=0, le=100000)
    order_type: Literal["market", "limit"] = "market"
    limit_price: Decimal | None = Field(default=None, gt=0, le=Decimal("10000000"))
    execution_mode: Literal["simulated", "live"] = "simulated"


class OptionApprovalIn(BaseModel):
    expiry: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    strike: Decimal = Field(gt=0, le=Decimal("1000000"))
    option_type: Literal["call", "put"]
    side: Literal["buy", "sell"] = "buy"
    lots: int = Field(gt=0, le=10000)
    order_type: Literal["market", "limit"] = "market"
    limit_price: Decimal | None = Field(default=None, gt=0, le=Decimal("10000000"))
    execution_mode: Literal["simulated", "live"] = "simulated"


class CashflowInterventionIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    recommendation: str = Field(min_length=10, max_length=2000)
    financial_impact: Decimal | None = None


class ApproveIn(BaseModel):
    confirm: bool
    payload_hash: str = Field(min_length=64, max_length=64)
    note: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ChatIn(BaseModel):
    question: str = Field(min_length=3, max_length=1200)


class PayPalOrderIn(BaseModel):
    invoice_id: int


class SimulatePayPalIn(BaseModel):
    invoice_id: int
    amount: Decimal | None = Field(default=None, gt=0, le=Decimal("100000000"))


class PayPalSettingsIn(BaseModel):
    environment: Literal["sandbox", "live"]
    enabled: bool = True
    confirm_live: bool = False


class PayPalRefundIn(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, le=Decimal("100000000"))
    reason: str = Field(min_length=3, max_length=500)
    confirm: bool = False


class DemoResetIn(BaseModel):
    confirm: str


class ConfirmIn(BaseModel):
    confirm: bool


class IntegrationCheckIn(BaseModel):
    provider: Literal["paypal", "upstox", "metals", "news", "llm"]


# ------------------------------------------------------------------ GST billing


class GSTInvoiceItemIn(BaseModel):
    product_id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    hsn_sac: str | None = Field(default=None, max_length=12)
    unit: str = Field(default="pcs", min_length=1, max_length=24)
    item_type: Literal["goods", "services"] = "goods"
    quantity: Decimal = Field(gt=0, le=Decimal("100000"))
    unit_price: Decimal = Field(ge=0, le=Decimal("100000000"))
    discount: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    gst_rate: Decimal = Field(ge=0, le=100)


class BillingCustomerIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    company: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    gstin: str | None = Field(default=None, max_length=15)
    billing_address_line1: str | None = Field(default=None, max_length=200)
    billing_address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    postal_code: str | None = Field(default=None, max_length=10)


class GSTInvoiceIn(BaseModel):
    customer_id: int | None = None
    customer: BillingCustomerIn | None = None
    save_customer: bool = True
    number: str | None = Field(default=None, max_length=40)
    issue_date: date
    due_date: date
    pricing_mode: Literal["exclusive", "inclusive"] = "exclusive"
    place_of_supply_state: str | None = Field(default=None, max_length=80)
    place_of_supply_state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    items: list[GSTInvoiceItemIn] = Field(min_length=1, max_length=100)
    other_charges: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    round_to_rupee: bool = True
    confirm_supply_details: bool = False
    status: Literal["draft", "issued"] = "issued"
    notes: str | None = Field(default=None, max_length=2000)
    terms: str | None = Field(default=None, max_length=3000)

    @model_validator(mode="after")
    def validate_invoice(self) -> "GSTInvoiceIn":
        if self.due_date < self.issue_date:
            raise ValueError("Due date cannot be before the issue date.")
        if self.customer_id is None and self.customer is None:
            raise ValueError("Choose an existing customer or enter customer billing details.")
        if self.items and any(item.discount > item.quantity * item.unit_price for item in self.items):
            raise ValueError("A discount cannot exceed its line value.")
        return self


class GSTCalculateIn(BaseModel):
    pricing_mode: Literal["exclusive", "inclusive"] = "exclusive"
    place_of_supply_state: str | None = Field(default=None, max_length=80)
    place_of_supply_state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    items: list[GSTInvoiceItemIn] = Field(min_length=1, max_length=100)
    other_charges: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    round_to_rupee: bool = True
    confirm_supply_details: bool = True


class BillingProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    hsn_sac: str | None = Field(default=None, max_length=12)
    item_type: Literal["goods", "services"] = "goods"
    unit: str = Field(default="pcs", min_length=1, max_length=24)
    default_gst_rate: Decimal = Field(default=Decimal("18"), ge=0, le=100)
    unit_price: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    reorder_level: int = Field(default=0, ge=0, le=1000000)


class BillingProductUpdateIn(BillingProductIn):
    sku: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    item_type: Literal["goods", "services"] | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=24)
    default_gst_rate: Decimal | None = Field(default=None, ge=0, le=100)
    unit_price: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000"))
    unit_cost: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000"))
    reorder_level: int | None = Field(default=None, ge=0, le=1000000)
    gst_change_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_change(self) -> "BillingProductUpdateIn":
        fields = set(self.model_dump(exclude_unset=True)) - {"gst_change_reason"}
        if not fields:
            raise ValueError("Provide at least one change.")
        return self


class GSTRateIn(BaseModel):
    rate: Decimal = Field(ge=0, le=100)
    label: str | None = Field(default=None, max_length=60)


class GstCatalogueUpdateIn(BaseModel):
    gst_rate: Decimal | None = Field(default=None, ge=0, le=100)
    hsn_sac: str | None = Field(default=None, max_length=12)
    item_type: Literal["goods", "services"] | None = None
    hsn_verified: bool | None = None
    effective_from: date | None = None
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def require_change(self) -> "GstCatalogueUpdateIn":
        if (
            self.gst_rate is None
            and self.hsn_sac is None
            and self.item_type is None
            and self.hsn_verified is None
        ):
            raise ValueError("Provide a GST rate, HSN/SAC, item type or verification change.")
        return self


class GstCatalogueDecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=500)


class GstCatalogueSettingsIn(BaseModel):
    approval_mode: Literal["direct", "owner_approval"]


class GstCataloguePermissionIn(BaseModel):
    enabled: bool


class BillingSettingsIn(BaseModel):
    business_name: str | None = Field(default=None, min_length=1, max_length=160)
    legal_name: str | None = Field(default=None, max_length=160)
    gstin: str | None = Field(default=None, max_length=15)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    postal_code: str | None = Field(default=None, max_length=10)
    business_phone: str | None = Field(default=None, max_length=40)
    business_email: EmailStr | None = None
    invoice_terms: str | None = Field(default=None, max_length=3000)
    logo_data_url: str | None = Field(default=None, max_length=400000)


class ContactMessageIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    organisation: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    category: Literal["general", "support", "partnership", "developer"] = "general"
    subject: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=20, max_length=4000)
    consent: bool
    website: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def require_consent(self) -> "ContactMessageIn":
        if not self.consent:
            raise ValueError("Privacy consent is required before sending a message.")
        if self.website:
            raise ValueError("This submission was rejected by spam protection.")
        return self


# ---------------------------------------------------------------- tax engine


class TaxCalculatorLineIn(BaseModel):
    quantity: Decimal = Field(gt=0, le=Decimal("100000"))
    unit_price: Decimal = Field(ge=0, le=Decimal("100000000"))
    discount: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    gst_rate: Decimal = Field(ge=0, le=100)
    pricing_mode: Literal["exclusive", "inclusive"] = "exclusive"


class TaxCalculatorIn(BaseModel):
    supplier_state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    place_of_supply_state_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    other_charges: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    round_to_rupee: bool = True
    lines: list[TaxCalculatorLineIn] = Field(min_length=1, max_length=100)


class ITCEntryIn(BaseModel):
    supplier_name: str = Field(min_length=2, max_length=160)
    supplier_gstin: str | None = Field(default=None, max_length=20)
    invoice_number: str = Field(min_length=1, max_length=60)
    invoice_date: date
    taxable_value: Decimal = Field(ge=0, le=Decimal("1000000000"))
    gst_rate: Decimal = Field(ge=0, le=100)
    cgst_amount: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("1000000000"))
    sgst_amount: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("1000000000"))
    igst_amount: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("1000000000"))
    eligible_amount: Decimal | None = Field(default=None, ge=0, le=Decimal("1000000000"))
    status: Literal["eligible", "claimed", "blocked"] = "eligible"
    note: str | None = Field(default=None, max_length=1000)


class HSNClassificationIn(BaseModel):
    code: str = Field(min_length=2, max_length=8)
    description: str = Field(min_length=2, max_length=200)
    kind: Literal["goods", "services"] = "goods"
    gst_rate: Decimal = Field(ge=0, le=100)
    verified: bool = False
    note: str | None = Field(default=None, max_length=1000)


class SalaryIncomeIn(BaseModel):
    gross_salary: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))
    basic_salary: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))
    hra_received: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))
    rent_paid: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))
    professional_tax: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000"))
    employer_nps: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))
    metro_city: bool = False


class BusinessIncomeIn(BaseModel):
    net_profit: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))
    presumptive: Literal["none", "44ad", "44ada"] = "none"
    gross_receipts: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))
    digital_receipts_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class CapitalGainsIn(BaseModel):
    equity_stcg: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))
    equity_ltcg: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))
    other_ltcg: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))
    other_stcg: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))


class DeductionsIn(BaseModel):
    field_80c: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000"), alias="80C")
    field_80ccd1b: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000"), alias="80CCD1B")
    field_80d: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000"), alias="80D")
    field_80tta: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000"), alias="80TTA")
    field_80ttb: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000"), alias="80TTB")
    field_24b: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000"), alias="24B")
    field_80g: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000"), alias="80G")
    field_80e: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000"), alias="80E")
    other: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000"))

    model_config = ConfigDict(populate_by_name=True)

    def as_sections(self) -> dict[str, Decimal]:
        return {
            "80C": self.field_80c,
            "80CCD1B": self.field_80ccd1b,
            "80D": self.field_80d,
            "80TTA": self.field_80tta,
            "80TTB": self.field_80ttb,
            "24B": self.field_24b,
            "80G": self.field_80g,
            "80E": self.field_80e,
            "other": self.other,
        }


class IncomeTaxInputs(BaseModel):
    salary: SalaryIncomeIn = Field(default_factory=SalaryIncomeIn)
    business: BusinessIncomeIn = Field(default_factory=BusinessIncomeIn)
    other_income: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))
    capital_gains: CapitalGainsIn = Field(default_factory=CapitalGainsIn)
    deductions: DeductionsIn = Field(default_factory=DeductionsIn)

    def to_engine(self) -> dict:
        return {
            "salary": self.salary.model_dump(),
            "business": self.business.model_dump(),
            "other_income": self.other_income,
            "capital_gains": self.capital_gains.model_dump(),
            "deductions": self.deductions.as_sections(),
        }


class IncomeTaxCalculateIn(BaseModel):
    financial_year: str = Field(pattern=r"^\d{4}-\d{2}$")
    regime: Literal["new", "old"]
    inputs: IncomeTaxInputs


class IncomeTaxCompareIn(BaseModel):
    financial_year: str = Field(pattern=r"^\d{4}-\d{2}$")
    inputs: IncomeTaxInputs


class IncomeTaxEstimateSaveIn(IncomeTaxCompareIn):
    regime: Literal["new", "old"] | None = None


class TaxApprovalIn(BaseModel):
    approved_by_name: str = Field(min_length=3, max_length=120)
    membership_number: str = Field(min_length=3, max_length=60)
    approval_note: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------- accounting practice

from .accounting_catalog import (  # noqa: E402
    BUSINESS_TYPES,
    GST_STATUSES,
    REPORT_TYPES,
    SERVICE_KEYS,
    TALLY_EXPORT_FORMATS,
    TALLY_EXPORT_TYPES,
    TALLY_IMPORT_STATUSES,
    TALLY_MAPPING_FIELD_KEYS,
    TALLY_MIGRATION_FORMATS,
    TALLY_MIGRATION_IMPORT_TYPES,
    TALLY_VERSIONS,
    TALLY_VERSION_FORMATS,
    TURNOVER_RANGES,
    VOUCHER_TYPES,
    BUSINESS_EXPORT_CATEGORIES,
)

BusinessType = Literal[tuple(BUSINESS_TYPES)]  # type: ignore[valid-type]
TurnoverRange = Literal[tuple(TURNOVER_RANGES)]  # type: ignore[valid-type]
GSTStatus = Literal[tuple(GST_STATUSES)]  # type: ignore[valid-type]
ServiceKey = Literal[tuple(SERVICE_KEYS)]  # type: ignore[valid-type]


class AccountingEnquiryIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=180)
    contact_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    business_type: BusinessType
    turnover_range: TurnoverRange
    gst_status: GSTStatus
    services: list[ServiceKey] = Field(min_length=1, max_length=8)
    monthly_transactions: int | None = Field(default=None, ge=0, le=1_000_000)
    requirements: str | None = Field(default=None, max_length=3000)
    annual_turnover: Decimal | None = Field(default=None, ge=0, le=Decimal("1000000000000"))
    bank_accounts: int | None = Field(default=None, ge=0, le=100)
    payroll_required: bool = False
    inventory_required: bool = False
    financial_year: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    consent: bool
    website: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def require_consent(self) -> "AccountingEnquiryIn":
        if not self.consent:
            raise ValueError("Consent is required before submitting an enquiry.")
        if self.website:
            raise ValueError("This submission was rejected by spam protection.")
        return self


class AccountingEnquiryStatusIn(BaseModel):
    status: Literal["new", "contacted", "quoted", "quote_accepted", "onboarded", "declined"]
    internal_notes: str | None = Field(default=None, max_length=3000)


class QuotationScopeIn(BaseModel):
    service: ServiceKey
    description: str = Field(min_length=2, max_length=300)


class AccountingQuotationIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    billing_cadence: Literal["monthly", "quarterly", "annual", "one_time"] = "monthly"
    scope: list[QuotationScopeIn] = Field(min_length=1, max_length=8)
    terms: str | None = Field(default=None, max_length=3000)
    valid_until: date | None = None


class QuotationDecisionIn(BaseModel):
    decision: Literal["accepted", "declined"]
    note: str | None = Field(default=None, max_length=2000)


class QuotationLineIn(BaseModel):
    kind: Literal["service", "addon", "custom"] = "service"
    key: str | None = Field(default=None, max_length=48)
    label: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    service: ServiceKey | None = None
    # Annual amount. Zero means the senior has not priced the line yet.
    amount: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    cadence: Literal["annual", "one_time"] = "annual"


class QuotationDraftIn(BaseModel):
    enquiry_id: int | None = None
    client_id: int | None = None
    business_name: str | None = Field(default=None, max_length=180)
    contact_name: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    annual_turnover: Decimal | None = Field(default=None, ge=0, le=Decimal("1000000000000"))
    line_items: list[QuotationLineIn] = Field(min_length=1, max_length=40)
    discount_type: Literal["none", "percent", "amount"] = "none"
    discount_value: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    discount_note: str | None = Field(default=None, max_length=1000)
    payment_frequency: Literal["monthly", "quarterly", "annual", "one_time"] = "monthly"
    validity_days: int | None = Field(default=None, ge=1, le=365)
    terms: str | None = Field(default=None, max_length=4000)


class QuotationUpdateIn(BaseModel):
    annual_turnover: Decimal | None = Field(default=None, ge=0, le=Decimal("1000000000000"))
    line_items: list[QuotationLineIn] | None = Field(default=None, min_length=1, max_length=40)
    discount_type: Literal["none", "percent", "amount"] | None = None
    discount_value: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000"))
    discount_note: str | None = Field(default=None, max_length=1000)
    payment_frequency: Literal["monthly", "quarterly", "annual", "one_time"] | None = None
    validity_days: int | None = Field(default=None, ge=1, le=365)
    terms: str | None = Field(default=None, max_length=4000)


class QuotationRejectIn(BaseModel):
    note: str = Field(min_length=3, max_length=2000)


class SoftwareTierUpdateIn(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    turnover_min: Decimal | None = Field(default=None, ge=0)
    turnover_max: Decimal | None = Field(default=None, ge=0)
    monthly_price: Decimal | None = Field(default=None, ge=0, le=Decimal("10000000"))
    description: str | None = Field(default=None, max_length=1000)
    features: list[str] | None = Field(default=None, max_length=12)
    is_active: bool | None = None


class ITRPriceUpdateIn(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    price_min: Decimal | None = Field(default=None, ge=0, le=Decimal("10000000"))
    price_max: Decimal | None = Field(default=None, ge=0, le=Decimal("10000000"))
    price_note: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class PricingAddonIn(BaseModel):
    key: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)
    amount: Decimal | None = Field(default=None, ge=0, le=Decimal("10000000"))
    cadence: Literal["annual", "one_time"] = "annual"
    is_active: bool = True


class PricingAddonUpdateIn(BaseModel):
    label: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    amount: Decimal | None = Field(default=None, ge=0, le=Decimal("10000000"))
    cadence: Literal["annual", "one_time"] | None = None
    is_active: bool | None = None


class PricingRulesIn(BaseModel):
    benchmark_percent: Decimal | None = Field(default=None, ge=0, le=100)
    annual_discount_percent: Decimal | None = Field(default=None, ge=0, le=100)
    quote_validity_days: int | None = Field(default=None, ge=1, le=365)
    tax_rate_percent: Decimal | None = Field(default=None, ge=0, le=100)
    tax_note: str | None = Field(default=None, max_length=2000)
    terms: str | None = Field(default=None, max_length=4000)


class AccountingClientIn(BaseModel):
    enquiry_id: int | None = None
    quotation_id: int | None = None
    business_name: str = Field(min_length=2, max_length=180)
    contact_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    business_type: BusinessType
    turnover_range: TurnoverRange
    gst_status: GSTStatus
    gstin: str | None = Field(default=None, pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
    pan_last4: str | None = Field(default=None, pattern=r"^[A-Z0-9]{4}$")
    financial_year: str = Field(pattern=r"^\d{4}-\d{2}$")
    service_package: str = Field(min_length=2, max_length=80)
    assigned_junior_user_id: int | None = None
    portal_password: str | None = Field(default=None, min_length=10, max_length=128)
    notes: str | None = Field(default=None, max_length=3000)

    @field_validator("pan_last4")
    @classmethod
    def upper_pan(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class AccountingClientUpdateIn(BaseModel):
    business_name: str | None = Field(default=None, min_length=2, max_length=180)
    contact_name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    business_type: BusinessType | None = None
    turnover_range: TurnoverRange | None = None
    gst_status: GSTStatus | None = None
    gstin: str | None = Field(default=None, pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
    pan_last4: str | None = Field(default=None, pattern=r"^[A-Z0-9]{4}$")
    financial_year: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    service_package: str | None = Field(default=None, min_length=2, max_length=80)
    status: Literal["onboarding", "active", "paused", "archived"] | None = None
    assigned_junior_user_id: int | None = None
    senior_accountant_user_id: int | None = None
    notes: str | None = Field(default=None, max_length=3000)


class ClientAssignmentIn(BaseModel):
    junior_user_id: int | None = None


class BusinessIntegrationLinkIn(BaseModel):
    business_profile_id: int = Field(gt=0)


class DraftGenerateIn(BaseModel):
    transaction_ids: list[int] | None = Field(default=None, max_length=200)
    limit: int = Field(default=50, ge=1, le=200)


class EntryDraftLineIn(BaseModel):
    ledger_name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    debit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=16, decimal_places=2)
    credit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=16, decimal_places=2)

    @model_validator(mode="after")
    def one_side(self) -> "EntryDraftLineIn":
        if (self.debit > 0) == (self.credit > 0):
            raise ValueError("Each draft line needs exactly one of debit or credit.")
        return self


class EntryDraftUpdateIn(BaseModel):
    voucher_type: Literal["sale", "receipt", "payment", "expense", "journal"] | None = None
    voucher_date: date | None = None
    party_name: str | None = Field(default=None, min_length=1, max_length=180)
    party_gstin: str | None = Field(default=None, max_length=15)
    narration: str | None = Field(default=None, max_length=2000)
    lines: list[EntryDraftLineIn] | None = Field(default=None, min_length=2, max_length=200)


class DraftDecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    acknowledge_source_change: bool = False


class LedgerMappingIn(BaseModel):
    transaction_type: Literal["sale", "receipt", "refund", "expense"]
    category: str = Field(default="", max_length=60)
    debit_ledger: str | None = Field(default=None, max_length=120)
    credit_ledger: str | None = Field(default=None, max_length=120)
    tax_ledger: str | None = Field(default=None, max_length=120)
    bank_ledger: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def has_a_ledger(self) -> "LedgerMappingIn":
        if not any(
            (value or "").strip()
            for value in (
                self.debit_ledger,
                self.credit_ledger,
                self.tax_ledger,
                self.bank_ledger,
            )
        ):
            raise ValueError("Set at least one suggested ledger.")
        return self


class AccountingTaskIn(BaseModel):
    client_id: int
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=3000)
    service_type: ServiceKey
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    due_date: date | None = None
    assigned_to_user_id: int | None = None


class AccountingTaskUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=3000)
    status: Literal[
        "unassigned", "assigned", "in_progress", "submitted", "changes_requested", "approved", "delivered", "cancelled"
    ] | None = None
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    due_date: date | None = None
    assigned_to_user_id: int | None = None
    progress: int | None = Field(default=None, ge=0, le=100)


class TaskReviewIn(BaseModel):
    decision: Literal["approve", "changes_requested"]
    notes: str | None = Field(default=None, max_length=3000)


class TaskSubmitIn(BaseModel):
    summary: str = Field(min_length=5, max_length=3000)
    progress: int = Field(default=100, ge=0, le=100)


class TaskCommentIn(BaseModel):
    body: str = Field(min_length=2, max_length=2000)


class DocumentRequestIn(BaseModel):
    client_id: int
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    due_date: date | None = None


class DocumentReviewIn(BaseModel):
    status: Literal["verified", "rejected"]
    note: str | None = Field(default=None, max_length=2000)


class AccountingVoucherIn(BaseModel):
    client_id: int
    voucher_type: Literal[tuple(VOUCHER_TYPES)]  # type: ignore[valid-type]
    number: str = Field(min_length=1, max_length=60)
    voucher_date: date
    party_name: str = Field(min_length=2, max_length=180)
    party_gstin: str | None = Field(default=None, max_length=15)
    ledger_name: str = Field(min_length=2, max_length=120)
    bank_ledger: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=2000)
    taxable_value: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0, le=28, max_digits=5, decimal_places=2)
    inter_state: bool = False

    @model_validator(mode="after")
    def require_value(self) -> "AccountingVoucherIn":
        if self.taxable_value <= 0:
            raise ValueError("Taxable value must be greater than zero.")
        return self


class PortalMessageIn(BaseModel):
    body: str = Field(min_length=2, max_length=2000)


class AccountingReportIn(BaseModel):
    client_id: int
    report_type: Literal[tuple(REPORT_TYPES)]  # type: ignore[valid-type]
    financial_year: str = Field(pattern=r"^\d{4}-\d{2}$")
    period: str = Field(min_length=7, max_length=20, description="YYYY-MM for monthly, or FY label")


class ReportReviewIn(BaseModel):
    decision: Literal["approve", "changes_requested"]
    notes: str | None = Field(default=None, max_length=3000)


class ServiceInvoiceIn(BaseModel):
    client_id: int
    issue_date: date
    due_date: date
    period_label: str | None = Field(default=None, max_length=40)
    subtotal: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    tax_rate: Decimal = Field(default=Decimal("18"), ge=0, le=28, max_digits=5, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def due_after_issue(self) -> "ServiceInvoiceIn":
        if self.due_date < self.issue_date:
            raise ValueError("Due date cannot be before the issue date.")
        return self


class ServicePaymentIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    method: Literal["bank", "upi", "cash", "card", "cheque", "other"] = "bank"
    reference: str | None = Field(default=None, max_length=120)
    received_on: date


class TallyExportIn(BaseModel):
    client_id: int
    from_date: date
    to_date: date
    voucher_type: Literal[tuple(("all",) + VOUCHER_TYPES)] = "all"  # type: ignore[valid-type]

    @model_validator(mode="after")
    def ordered(self) -> "TallyExportIn":
        if self.to_date < self.from_date:
            raise ValueError("End date cannot be before the start date.")
        return self


class TallyExportBatchIn(BaseModel):
    client_id: int
    export_types: list[Literal[tuple(TALLY_EXPORT_TYPES)]] = Field(  # type: ignore[valid-type]
        min_length=1, max_length=len(TALLY_EXPORT_TYPES)
    )
    from_date: date | None = None
    to_date: date | None = None
    file_format: Literal[tuple(TALLY_EXPORT_FORMATS)] = "xlsx"  # type: ignore[valid-type]
    tally_version: Literal[tuple(TALLY_VERSIONS)] = "TallyPrime 4.1"  # type: ignore[valid-type]
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("export_types")
    @classmethod
    def unique_types(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for item in value:
            if item not in seen:
                seen.append(item)
        if not seen:
            raise ValueError("Choose at least one data type to export.")
        return seen

    @model_validator(mode="after")
    def ordered(self) -> "TallyExportBatchIn":
        if self.from_date and self.to_date:
            if self.to_date < self.from_date:
                raise ValueError("End date cannot be before the start date.")
            if (self.to_date - self.from_date).days > 800:
                raise ValueError("Export period cannot exceed 800 days.")
        if self.file_format == "json" and "json" not in TALLY_VERSION_FORMATS[self.tally_version]:
            raise ValueError(
                f"{self.tally_version} is not documented to support JSON export here. "
                "Use CSV + XML or Excel for this version."
            )
        return self


class TallyDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def rejection_needs_reason(self) -> "TallyDecisionIn":
        if self.decision == "reject" and not (self.note or "").strip():
            raise ValueError("Give a reason when rejecting an export batch.")
        return self


class TallyImportStatusIn(BaseModel):
    import_status: Literal[tuple(TALLY_IMPORT_STATUSES)]  # type: ignore[valid-type]
    note: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------- business exports

BusinessExportCategory = Literal[tuple(BUSINESS_EXPORT_CATEGORIES)]  # type: ignore[valid-type]


class BusinessExportIn(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    categories: list[BusinessExportCategory] = Field(  # type: ignore[valid-type]
        default_factory=lambda: list(BUSINESS_EXPORT_CATEGORIES),
        min_length=1,
        max_length=len(BUSINESS_EXPORT_CATEGORIES),
    )

    @field_validator("categories")
    @classmethod
    def unique_categories(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for item in value:
            if item not in seen:
                seen.append(item)
        if not seen:
            raise ValueError("Choose at least one category to export.")
        return seen

    @model_validator(mode="after")
    def ordered(self) -> "BusinessExportIn":
        if self.date_from and self.date_to:
            if self.date_to < self.date_from:
                raise ValueError("End date cannot be before the start date.")
            if (self.date_to - self.date_from).days > 3660:
                raise ValueError("Export period cannot exceed 10 financial years.")
        return self


class BusinessTallyExportIn(BusinessExportIn):
    file_format: Literal["xlsx", "xml"] = "xlsx"
    tally_version: Literal[tuple(TALLY_VERSIONS)] = "TallyPrime 4.1"  # type: ignore[valid-type]


# ---------------------------------------------------------------- Tally migration

TallyMigrationFormat = Literal[tuple(TALLY_MIGRATION_FORMATS)]  # type: ignore[valid-type]
TallyMigrationImportType = Literal[tuple(TALLY_MIGRATION_IMPORT_TYPES)]  # type: ignore[valid-type]
TallyVersion = Literal[tuple(TALLY_VERSIONS)]  # type: ignore[valid-type]


def _validate_mapping(mapping: dict[str, str] | None) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for target, column in (mapping or {}).items():
        if target not in TALLY_MAPPING_FIELD_KEYS:
            raise ValueError(f"{target!r} is not a recognised FINOVEXA import field.")
        if column is None or not str(column).strip():
            continue
        cleaned[target] = str(column).strip()[:200]
    return cleaned


class TallyMappingTemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    client_id: int | None = None
    file_format: TallyMigrationFormat = "csv"
    import_type: TallyMigrationImportType = "complete"
    mapping: dict[str, str] = Field(default_factory=dict)
    is_shared: bool = True

    @field_validator("mapping")
    @classmethod
    def mapping_fields(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned = _validate_mapping(value)
        if not cleaned:
            raise ValueError("Map at least one Tally column to a FINOVEXA field.")
        return cleaned


class TallyMappingTemplateUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    mapping: dict[str, str] | None = None
    is_shared: bool | None = None

    @field_validator("mapping")
    @classmethod
    def mapping_fields(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return None if value is None else _validate_mapping(value)


class TallyMigrationPreviewIn(BaseModel):
    file_format: TallyMigrationFormat
    filename: str = Field(min_length=1, max_length=255)
    data_url: str = Field(min_length=40, max_length=5_600_000)

    @field_validator("data_url")
    @classmethod
    def supported_file(cls, value: str) -> str:
        return _validate_data_url(value)


class TallyMigrationIn(BaseModel):
    client_id: int
    tally_version: TallyVersion = "TallyPrime 4.1"
    financial_year: str = Field(pattern=r"^\d{4}-\d{2}$")
    period_from: date | None = None
    period_to: date | None = None
    opening_date: date | None = None
    import_type: TallyMigrationImportType = "complete"
    file_format: TallyMigrationFormat = "csv"
    filename: str = Field(min_length=1, max_length=255)
    data_url: str = Field(min_length=40, max_length=5_600_000)
    mapping: dict[str, str] | None = None
    mapping_template_id: int | None = None
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("data_url")
    @classmethod
    def supported_file(cls, value: str) -> str:
        return _validate_data_url(value)

    @field_validator("mapping")
    @classmethod
    def mapping_fields(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return None if value is None else _validate_mapping(value)

    @field_validator("financial_year")
    @classmethod
    def financial_year_shape(cls, value: str) -> str:
        start, end = (int(part) for part in value.split("-"))
        if end != (start + 1) % 100:
            raise ValueError("Financial year must look like 2025-26 (consecutive years).")
        return value

    @model_validator(mode="after")
    def consistent(self) -> "TallyMigrationIn":
        if self.period_from and self.period_to and self.period_to < self.period_from:
            raise ValueError("End date cannot be before the start date.")
        supported = TALLY_VERSION_FORMATS[self.tally_version]
        if self.file_format not in supported:
            raise ValueError(
                f"{self.tally_version} does not document {self.file_format.upper()} import in this module. "
                f"Supported: {', '.join(fmt.upper() for fmt in supported)}."
            )
        if self.import_type == "opening_balances" and self.opening_date is None:
            raise ValueError("Choose the opening date for an opening balance import.")
        return self


class TallyMigrationRevalidateIn(BaseModel):
    mapping: dict[str, str] | None = None
    mapping_template_id: int | None = None

    @field_validator("mapping")
    @classmethod
    def mapping_fields(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return None if value is None else _validate_mapping(value)


class TallyMigrationDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def rejection_needs_reason(self) -> "TallyMigrationDecisionIn":
        if self.decision == "reject" and not (self.note or "").strip():
            raise ValueError("Give a reason when rejecting an import batch.")
        return self


class TallyOpeningBalanceLineIn(BaseModel):
    ledger_name: str = Field(min_length=1, max_length=180)
    group_name: str | None = Field(default=None, max_length=120)
    party_type: Literal["customer", "supplier", "other"] = "other"
    debit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=16, decimal_places=2)
    credit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=16, decimal_places=2)
    stock_item: str | None = Field(default=None, max_length=180)
    quantity: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    rate: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    narration: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def one_side(self) -> "TallyOpeningBalanceLineIn":
        if (self.debit > 0) == (self.credit > 0):
            raise ValueError("Each opening balance line needs exactly one of debit or credit.")
        return self


class TallyOpeningBalanceIn(BaseModel):
    client_id: int
    financial_year: str = Field(pattern=r"^\d{4}-\d{2}$")
    opening_date: date
    lines: list[TallyOpeningBalanceLineIn] = Field(min_length=1, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("financial_year")
    @classmethod
    def financial_year_shape(cls, value: str) -> str:
        start, end = (int(part) for part in value.split("-"))
        if end != (start + 1) % 100:
            raise ValueError("Financial year must look like 2025-26 (consecutive years).")
        return value

    @model_validator(mode="after")
    def balanced(self) -> "TallyOpeningBalanceIn":
        debit = sum((line.debit for line in self.lines), Decimal("0"))
        credit = sum((line.credit for line in self.lines), Decimal("0"))
        if abs(debit - credit) > Decimal("0.01"):
            raise ValueError(
                f"Opening balances must balance. Debit {debit} does not equal credit {credit}."
            )
        return self


class StockItemIn(BaseModel):
    client_id: int
    name: str = Field(min_length=2, max_length=180)
    sku: str = Field(min_length=1, max_length=60)
    unit: str = Field(default="Nos", min_length=1, max_length=16)
    hsn_sac: str | None = Field(default=None, max_length=12)
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0, le=28, max_digits=5, decimal_places=2)
    opening_qty: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=3)
    opening_rate: Decimal = Field(default=Decimal("0"), ge=0, max_digits=16, decimal_places=2)


class StockItemUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    unit: str | None = Field(default=None, min_length=1, max_length=16)
    hsn_sac: str | None = Field(default=None, max_length=12)
    gst_rate: Decimal | None = Field(default=None, ge=0, le=28, max_digits=5, decimal_places=2)
    opening_qty: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    opening_rate: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    is_active: bool | None = None


class GSTPrepareIn(BaseModel):
    client_id: int
    period: str = Field(pattern=r"^\d{4}-\d{2}$")


class BankRowsIn(BaseModel):
    client_id: int
    filename: str = Field(min_length=1, max_length=200)
    rows: list[dict] = Field(min_length=1, max_length=5000)


_DATA_URL_PREFIXES = (
    "data:application/pdf;base64,",
    "data:image/png;base64,",
    "data:image/jpeg;base64,",
    "data:text/csv;base64,",
    "data:text/plain;base64,",
    "data:application/octet-stream;base64,",
    "data:application/xml;base64,",
    "data:text/xml;base64,",
    "data:application/json;base64,",
    "data:text/json;base64,",
    "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,",
    "data:application/vnd.ms-excel;base64,",
)


def _validate_data_url(value: str) -> str:
    if not value.startswith(_DATA_URL_PREFIXES):
        raise ValueError(
            "Unsupported file type. Upload a PDF, image, CSV, Excel, XML or JSON file."
        )
    return value


class AccountingFileIn(BaseModel):
    client_id: int
    filename: str = Field(min_length=1, max_length=200)
    data_url: str = Field(min_length=40, max_length=5_600_000)

    @field_validator("data_url")
    @classmethod
    def supported_file(cls, value: str) -> str:
        return _validate_data_url(value)


class AccountingDocumentIn(AccountingFileIn):
    title: str | None = Field(default=None, max_length=200)
    category: Literal[
        "purchase_bill", "sale_bill", "bank_statement", "gst_return", "challan", "payroll", "other"
    ] = "other"
    request_id: int | None = None


class BillExtractIn(AccountingFileIn):
    pass


class BankFileIn(AccountingFileIn):
    pass


class TallyImportIn(AccountingFileIn):
    direction: Literal["import"] = "import"


class VoucherBulkIn(BaseModel):
    client_id: int
    rows: list[dict] = Field(min_length=1, max_length=1000)


class BankMatchIn(BaseModel):
    voucher_id: int | None = None
    note: str | None = Field(default=None, max_length=500)


class PaymentConnectionIn(BaseModel):
    provider: Literal["paypal", "google_pay", "bank_statement"]
    client_id: int | None = None
    label: str | None = Field(default=None, max_length=120)
    outlet_label: str | None = Field(default=None, max_length=120)
    environment: Literal["sandbox", "live", "manual"] | None = None
    merchant_id: str | None = Field(default=None, max_length=120)
    consent: bool = False
    note: str | None = Field(default=None, max_length=2000)


class PaymentSyncIn(BaseModel):
    client_id: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    days: int = Field(default=30, ge=1, le=366)
    trigger: Literal["manual", "scheduled", "retry"] = "manual"


class PaymentReconcileIn(BaseModel):
    client_id: int | None = None
    action: Literal["approve", "reject", "not_applicable", "reset", "suggest"]
    invoice_id: int | None = None
    note: str | None = Field(default=None, max_length=1000)


class GooglePayTrackIn(BaseModel):
    client_id: int | None = None
    merchant_id: str = Field(min_length=1, max_length=120)
    google_transaction_id: str = Field(min_length=1, max_length=160)
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    occurred_on: date
    status: Literal["completed", "pending", "failed", "refunded", "unknown"] = "unknown"
    description: str | None = Field(default=None, max_length=500)
    upi_reference: str | None = Field(default=None, max_length=160)
    outlet_label: str | None = Field(default=None, max_length=120)


class BankStatementPreviewIn(AccountingFileIn):
    account_label: str | None = Field(default=None, max_length=160)


class BankStatementCorrectionIn(BaseModel):
    row: int = Field(ge=1)
    txn_date: str | None = None
    description: str | None = Field(default=None, max_length=255)
    reference: str | None = Field(default=None, max_length=120)
    debit: Decimal | None = Field(default=None, ge=0)
    credit: Decimal | None = Field(default=None, ge=0)


class BankStatementImportIn(AccountingFileIn):
    account_label: str | None = Field(default=None, max_length=160)
    corrections: list[BankStatementCorrectionIn] = Field(default_factory=list, max_length=5000)


class SupplierIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    gstin: str | None = Field(default=None, max_length=15)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    state_code: str | None = Field(default=None, max_length=2)
    postal_code: str | None = Field(default=None, max_length=10)
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    credit_limit: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=16, decimal_places=2)
    opening_balance: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=16, decimal_places=2)
    opening_balance_date: date | None = None
    status: Literal["active", "on_hold", "inactive"] = "active"
    notes: str | None = Field(default=None, max_length=2000)


class SupplierPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    gstin: str | None = Field(default=None, max_length=15)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    state_code: str | None = Field(default=None, max_length=2)
    postal_code: str | None = Field(default=None, max_length=10)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    opening_balance: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    opening_balance_date: date | None = None
    status: Literal["active", "on_hold", "inactive"] | None = None
    notes: str | None = Field(default=None, max_length=2000)


class CustomerCreditIn(BaseModel):
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    credit_hold: bool | None = None
    opening_balance: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    opening_balance_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class SupplierPaymentIn(BaseModel):
    supplier_id: int
    expense_id: int | None = None
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    method: Literal["cash", "bank", "upi", "neft", "rtgs", "imps", "cheque", "other"] = "bank"
    reference: str | None = Field(default=None, max_length=160)
    paid_on: date
    note: str | None = Field(default=None, max_length=2000)


class SupplierPaymentVoidIn(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class CustomerAdjustmentIn(BaseModel):
    customer_id: int
    invoice_id: int | None = None
    kind: Literal["credit_note", "debit_note", "write_off"]
    number: str | None = Field(default=None, max_length=40)
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    issued_on: date
    reason: str = Field(min_length=2, max_length=255)


class AdjustmentVoidIn(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class CreditAlertSettingsIn(BaseModel):
    utilization_warn_pct: int = Field(default=80, ge=1, le=100)
    utilization_critical_pct: int = Field(default=100, ge=1, le=100)
    due_soon_days: int = Field(default=7, ge=0, le=365)
    overdue_escalation_days: int = Field(default=7, ge=1, le=365)
    supplier_due_soon_days: int = Field(default=7, ge=0, le=365)
    in_app_enabled: bool = True
    email_enabled: bool = False

    @model_validator(mode="after")
    def validate_thresholds(self):
        if self.utilization_warn_pct >= self.utilization_critical_pct:
            raise ValueError("Warning utilization must be below the critical utilization.")
        return self


class CreditAlertEvaluateIn(BaseModel):
    send_email: bool = False


class SupplierMatchIn(BaseModel):
    dry_run: bool = True
