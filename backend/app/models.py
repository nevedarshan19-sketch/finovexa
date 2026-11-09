from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, object_session, relationship

from .database import Base
from .tenancy import BusinessScoped, current_business_id


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def money() -> Mapped[Decimal]:
    return mapped_column(Numeric(16, 2), nullable=False, default=Decimal("0.00"))


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    businesses: Mapped[list[BusinessProfile]] = relationship(
        "BusinessProfile",
        primaryjoin="User.id == BusinessProfile.owner_id",
        foreign_keys="BusinessProfile.owner_id",
        order_by="BusinessProfile.id",
        viewonly=True,
    )

    @property
    def profile(self) -> BusinessProfile | None:
        """The business in scope for this request, or the owner's first business."""
        session = object_session(self)
        if session is None:
            return None
        business_id = current_business_id()
        if business_id is not None:
            return session.get(BusinessProfile, business_id) if business_id > 0 else None
        owner_id = self.id if self.role == "owner" else self.owner_id
        if owner_id is None:
            return None
        return (
            session.query(BusinessProfile)
            .filter(BusinessProfile.owner_id == owner_id)
            .order_by(BusinessProfile.is_archived, BusinessProfile.id)
            .first()
        )


class BusinessProfile(TimestampMixin, Base):
    __tablename__ = "business_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    business_name: Mapped[str] = mapped_column(String(160), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)
    reporting_period: Mapped[str] = mapped_column(String(20), default="monthly", nullable=False)
    min_cash_reserve: Mapped[Decimal] = money()
    opening_cash_balance: Mapped[Decimal] = money()
    opening_balance_date: Mapped[date] = mapped_column(Date, nullable=False)
    risk_tolerance: Mapped[str] = mapped_column(String(20), default="balanced", nullable=False)
    research_interests: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    reminder_tone: Mapped[str] = mapped_column(String(20), default="professional", nullable=False)
    gst_change_approval: Mapped[str] = mapped_column(
        String(20), default="direct", nullable=False
    )
    health_score_weights: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    legal_name: Mapped[str | None] = mapped_column(String(160))
    gstin: Mapped[str | None] = mapped_column(String(15))
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(80))
    state_code: Mapped[str | None] = mapped_column(String(2))
    postal_code: Mapped[str | None] = mapped_column(String(10))
    business_phone: Mapped[str | None] = mapped_column(String(40))
    business_email: Mapped[str | None] = mapped_column(String(255))
    invoice_terms: Mapped[str | None] = mapped_column(Text)
    logo_data_url: Mapped[str | None] = mapped_column(Text)

    business_type: Mapped[str] = mapped_column(
        String(32), default="private_limited", nullable=False
    )
    pan: Mapped[str | None] = mapped_column(String(10))
    financial_year_start_month: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    invoice_prefix: Mapped[str | None] = mapped_column(String(12))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User | None] = relationship(foreign_keys=[user_id])
    memberships: Mapped[list[BusinessMembership]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )


class BusinessMembership(TimestampMixin, Base):
    __tablename__ = "business_memberships"
    __table_args__ = (
        UniqueConstraint("business_id", "user_id", name="uq_business_membership_user"),
        Index("ix_business_memberships_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("business_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)

    business: Mapped[BusinessProfile] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(foreign_keys=[user_id])


class Customer(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "customers"
    __table_args__ = (Index("ix_customers_user_name", "user_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(40))
    gstin: Mapped[str | None] = mapped_column(String(15))
    billing_address_line1: Mapped[str | None] = mapped_column(String(200))
    billing_address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(80))
    state_code: Mapped[str | None] = mapped_column(String(2))
    postal_code: Mapped[str | None] = mapped_column(String(10))
    credit_limit: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), default=Decimal("0.00"), nullable=False
    )
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    credit_hold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), default=Decimal("0.00"), nullable=False
    )
    opening_balance_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    invoices: Mapped[list[Invoice]] = relationship(back_populates="customer")


class Product(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("user_id", "sku", name="uq_product_user_sku"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    hsn_sac: Mapped[str | None] = mapped_column(String(12))
    item_type: Mapped[str] = mapped_column(String(16), default="goods", nullable=False)
    unit: Mapped[str] = mapped_column(String(24), default="pcs", nullable=False)
    default_gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("18.00"), nullable=False
    )
    unit_price: Mapped[Decimal] = money()
    unit_cost: Mapped[Decimal] = money()
    reorder_level: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    gst_effective_from: Mapped[date | None] = mapped_column(Date)
    gst_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    gst_change_reason: Mapped[str | None] = mapped_column(Text)
    gst_updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    inventory: Mapped[InventoryItem | None] = relationship(
        back_populates="product", cascade="all, delete-orphan", uselist=False
    )


class GstCatalogueChange(TimestampMixin, BusinessScoped, Base):
    """Audited GST configuration change for one catalogue item.

    ``applied`` and ``approved`` rows describe rates already live on the product.
    ``pending_approval`` rows hold an accountant proposal until the owner decides.
    Issued invoices never change: they keep their own line-level GST snapshots.
    """

    __tablename__ = "gst_catalogue_changes"
    __table_args__ = (
        Index("ix_gst_changes_product_created", "product_id", "created_at"),
        Index("ix_gst_changes_status", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    new_gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    old_hsn_sac: Mapped[str | None] = mapped_column(String(12))
    new_hsn_sac: Mapped[str | None] = mapped_column(String(12))
    old_item_type: Mapped[str | None] = mapped_column(String(16))
    new_item_type: Mapped[str | None] = mapped_column(String(16))
    old_hsn_verified: Mapped[bool | None] = mapped_column(Boolean)
    new_hsn_verified: Mapped[bool | None] = mapped_column(Boolean)
    effective_from: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="applied", nullable=False)
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    requested_by_role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)
    decided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_note: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship()


class InventoryItem(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    product: Mapped[Product] = relationship(back_populates="inventory")


class GSTRate(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "gst_rates"
    __table_args__ = (UniqueConstraint("user_id", "rate", name="uq_gst_rate_user_rate"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Invoice(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("user_id", "number", name="uq_invoice_user_number"),
        Index("ix_invoices_user_due", "user_id", "due_date"),
        Index("ix_invoices_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    assigned_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="issued", nullable=False)
    pricing_mode: Mapped[str] = mapped_column(String(20), default="exclusive", nullable=False)
    supply_type: Mapped[str] = mapped_column(String(20), default="unverified", nullable=False)
    supplier_name: Mapped[str | None] = mapped_column(String(160))
    supplier_gstin: Mapped[str | None] = mapped_column(String(15))
    supplier_address: Mapped[str | None] = mapped_column(Text)
    supplier_state: Mapped[str | None] = mapped_column(String(80))
    supplier_state_code: Mapped[str | None] = mapped_column(String(2))
    customer_name: Mapped[str | None] = mapped_column(String(160))
    customer_gstin: Mapped[str | None] = mapped_column(String(15))
    customer_phone: Mapped[str | None] = mapped_column(String(24))
    customer_address: Mapped[str | None] = mapped_column(Text)
    customer_state: Mapped[str | None] = mapped_column(String(80))
    customer_state_code: Mapped[str | None] = mapped_column(String(2))
    place_of_supply_state: Mapped[str | None] = mapped_column(String(80))
    place_of_supply_state_code: Mapped[str | None] = mapped_column(String(2))
    subtotal_amount: Mapped[Decimal] = money()
    discount_amount: Mapped[Decimal] = money()
    taxable_amount: Mapped[Decimal] = money()
    tax_amount: Mapped[Decimal] = money()
    cgst_amount: Mapped[Decimal] = money()
    sgst_amount: Mapped[Decimal] = money()
    igst_amount: Mapped[Decimal] = money()
    other_charges: Mapped[Decimal] = money()
    rounding_adjustment: Mapped[Decimal] = money()
    total_amount: Mapped[Decimal] = money()
    round_to_rupee: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supply_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reminder_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    disputed_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    terms: Mapped[str | None] = mapped_column(Text)

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])
    assigned_employee: Mapped[User | None] = relationship(foreign_keys=[assigned_employee_id])
    customer: Mapped[Customer] = relationship(back_populates="invoices")
    items: Mapped[list[InvoiceItem]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceItem.id"
    )
    payments: Mapped[list[Payment]] = relationship(back_populates="invoice")
    reminders: Mapped[list[InvoiceReminder]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )

    @property
    def paid_amount(self) -> Decimal:
        return sum((p.amount for p in self.payments if p.status == "confirmed"), Decimal("0.00"))

    @property
    def outstanding_amount(self) -> Decimal:
        if self.status == "void":
            return Decimal("0.00")
        return max(self.total_amount - self.paid_amount, Decimal("0.00"))


class InvoiceItem(BusinessScoped, Base):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    hsn_sac: Mapped[str | None] = mapped_column(String(12))
    unit: Mapped[str] = mapped_column(String(24), default="pcs", nullable=False)
    item_type: Mapped[str] = mapped_column(String(16), default="goods", nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    discount_amount: Mapped[Decimal] = money()
    line_total: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    taxable_value: Mapped[Decimal] = money()
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("18.00"), nullable=False
    )
    cgst_amount: Mapped[Decimal] = money()
    sgst_amount: Mapped[Decimal] = money()
    igst_amount: Mapped[Decimal] = money()
    gst_amount: Mapped[Decimal] = money()
    final_amount: Mapped[Decimal] = money()
    pricing_mode: Mapped[str] = mapped_column(String(20), default="exclusive", nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="items")


class Payment(BusinessScoped, Base):
    __tablename__ = "payments"
    __table_args__ = (Index("ix_payments_user_received", "user_id", "received_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"))
    refund_of_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    method: Mapped[str] = mapped_column(String(24), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_ref: Mapped[str | None] = mapped_column(String(160))
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    sender_name: Mapped[str | None] = mapped_column(String(160))
    reconciliation_status: Mapped[str] = mapped_column(
        String(24), default="unmatched", nullable=False
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])
    invoice: Mapped[Invoice | None] = relationship(back_populates="payments")
    refund_parent: Mapped[Payment | None] = relationship(
        remote_side=[id], back_populates="refunds"
    )
    refunds: Mapped[list[Payment]] = relationship(back_populates="refund_parent")


class PaymentEvent(BusinessScoped, Base):
    __tablename__ = "payment_events"
    __table_args__ = (Index("ix_payment_events_processed", "provider", "processed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(255), nullable=False)
    verification: Mapped[str | None] = mapped_column(String(32))
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"))
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ProviderSetting(TimestampMixin, Base):
    """Non-secret runtime state for integrations whose credentials live in the backend env."""

    __tablename__ = "provider_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    environment: Mapped[str] = mapped_column(String(20), default="sandbox", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by: Mapped[User | None] = relationship(foreign_keys=[updated_by_user_id])


class PayPalOrder(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "paypal_orders"
    __table_args__ = (
        Index("ix_paypal_orders_user_created", "user_id", "created_at"),
        Index("ix_paypal_orders_invoice", "invoice_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), index=True
    )
    provider_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    mode: Mapped[str] = mapped_column(String(20), default="simulated", nullable=False)
    intent: Mapped[str] = mapped_column(String(20), default="CAPTURE", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="CREATED", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    approve_url: Mapped[str | None] = mapped_column(Text)
    capture_id: Mapped[str | None] = mapped_column(String(64), index=True)
    capture_status: Mapped[str | None] = mapped_column(String(32))
    payer_email: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)

    invoice: Mapped[Invoice | None] = relationship()
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])


class PayPalRefund(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "paypal_refunds"
    __table_args__ = (Index("ix_paypal_refunds_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"), index=True
    )
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"))
    refund_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL")
    )
    capture_id: Mapped[str | None] = mapped_column(String(64), index=True)
    provider_refund_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    request_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(20), default="simulated", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    payment: Mapped[Payment | None] = relationship(foreign_keys=[payment_id])
    refund_payment: Mapped[Payment | None] = relationship(foreign_keys=[refund_payment_id])
    invoice: Mapped[Invoice | None] = relationship()


class ReconciliationRecord(BusinessScoped, Base):
    __tablename__ = "reconciliation_records"
    __table_args__ = (Index("ix_reconciliation_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    amount_delta: Mapped[Decimal] = money()
    actor: Mapped[str] = mapped_column(String(160), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    payment: Mapped[Payment] = relationship()
    invoice: Mapped[Invoice | None] = relationship()


class Expense(BusinessScoped, Base):
    __tablename__ = "expenses"
    __table_args__ = (Index("ix_expenses_user_date", "user_id", "incurred_on"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    vendor: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    incurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), index=True
    )
    bill_number: Mapped[str | None] = mapped_column(String(60))
    due_date: Mapped[date | None] = mapped_column(Date)
    payment_status: Mapped[str] = mapped_column(
        String(16), default="unpaid", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])


class EmployeeEntry(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "employee_entries"
    __table_args__ = (
        Index("ix_employee_entries_owner_created", "owner_id", "created_at"),
        Index("ix_employee_entries_employee_created", "employee_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="submitted", nullable=False)
    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    counterparty: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(60))
    amount: Mapped[Decimal] = money()
    amount_received: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), default=Decimal("18.00"), nullable=False
    )
    payment_method: Mapped[str | None] = mapped_column(String(24))
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"))
    expense_id: Mapped[int | None] = mapped_column(ForeignKey("expenses.id", ondelete="SET NULL"))
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime)

    owner: Mapped[User] = relationship(foreign_keys=[owner_id])
    employee: Mapped[User] = relationship(foreign_keys=[employee_id])
    invoice: Mapped[Invoice | None] = relationship()
    expense: Mapped[Expense | None] = relationship()
    payment: Mapped[Payment | None] = relationship()


class FinancialObligation(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "financial_obligations"
    __table_args__ = (Index("ix_obligations_user_due", "user_id", "due_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)
    recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class CashForecast(BusinessScoped, Base):
    __tablename__ = "cash_forecasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    scenario: Mapped[str] = mapped_column(String(20), default="base", nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    minimum_reserve: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    shortfall_date: Mapped[date | None] = mapped_column(Date)
    series: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class MarketInstrument(TimestampMixin, Base):
    __tablename__ = "market_instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(20), nullable=False)
    exchange: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    external_key: Mapped[str | None] = mapped_column(String(120))
    sector: Mapped[str | None] = mapped_column(String(80))


class MarketQuote(Base):
    __tablename__ = "market_quotes"
    __table_args__ = (Index("ix_quotes_instrument_asof", "instrument_id", "as_of"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("market_instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    previous_close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    change_pct: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    data_mode: Mapped[str] = mapped_column(String(16), default="demo", nullable=False)
    session_status: Mapped[str | None] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class MarketCandle(Base):
    __tablename__ = "market_candles"
    __table_args__ = (
        UniqueConstraint("instrument_id", "trading_date", name="uq_candle_instrument_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("market_instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int | None] = mapped_column(Integer)
    data_mode: Mapped[str] = mapped_column(String(16), default="demo", nullable=False)


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    implications: Mapped[str | None] = mapped_column(Text)
    risks: Mapped[str | None] = mapped_column(Text)
    instruments: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    data_mode: Mapped[str] = mapped_column(String(16), default="demo", nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ResearchSignal(Base):
    __tablename__ = "research_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("market_instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_signal: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    risks: Mapped[str] = mapped_column(Text, nullable=False)
    methodology: Mapped[str] = mapped_column(Text, nullable=False)
    data_quality: Mapped[str] = mapped_column(String(40), nullable=False)
    is_model_generated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AIInsight(BusinessScoped, Base):
    __tablename__ = "ai_insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    finding: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    impact_amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    confidence: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    limitations: Mapped[str | None] = mapped_column(Text)
    recommended_action: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(20), default="deterministic", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ChatMessage(BusinessScoped, Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    mode: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ApprovalRequest(BusinessScoped, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (Index("ix_approvals_user_status", "user_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    financial_impact: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    risk_level: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class BrokerOrder(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "broker_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approval_id: Mapped[int] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("market_instruments.id", ondelete="RESTRICT"), nullable=False
    )
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(String(12), nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    status: Mapped[str] = mapped_column(String(32), default="simulated_pending", nullable=False)
    broker: Mapped[str] = mapped_column(String(32), default="simulated", nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(120))
    broker_status: Mapped[str | None] = mapped_column(String(40))
    broker_status_message: Mapped[str | None] = mapped_column(Text)
    order_tag: Mapped[str | None] = mapped_column(String(64))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    instrument: Mapped[MarketInstrument] = relationship()
    approval: Mapped[ApprovalRequest] = relationship()


class PortfolioHolding(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "portfolio_holdings"
    __table_args__ = (
        UniqueConstraint("user_id", "instrument_id", name="uq_portfolio_user_instrument"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("market_instruments.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    # demo_seed | simulated_fill. Live broker fills are deliberately not mirrored here.
    source: Mapped[str] = mapped_column(String(24), default="demo_seed", nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_trade_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    instrument: Mapped[MarketInstrument] = relationship()


class IntegrationConfig(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "integration_configs"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_integration_user_provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default="demo", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="not_configured", nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)


class AuditEvent(BusinessScoped, Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    actor: Mapped[str] = mapped_column(String(160), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class InvoiceReminder(BusinessScoped, Base):
    __tablename__ = "invoice_reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approval_id: Mapped[int | None] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(20), default="email", nullable=False)
    stage: Mapped[str | None] = mapped_column(String(24))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="prepared", nullable=False)
    delivery_note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="reminders")


class ContactMessage(Base):
    __tablename__ = "contact_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    organisation: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    consent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="new", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


# ---------------------------------------------------------------- pricing & quotation engine


class PricingSetting(TimestampMixin, Base):
    """Single-row configuration for quotation rules. Editable from the developer console."""

    __tablename__ = "pricing_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True, default="default", nullable=False)
    benchmark_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("2.00"), nullable=False
    )
    annual_discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    quote_validity_days: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    tax_rate_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("18.00"), nullable=False
    )
    tax_note: Mapped[str] = mapped_column(
        Text,
        default=(
            "Prices are exclusive of GST. Applicable taxes are shown separately on the invoice "
            "raised by the practice."
        ),
        nullable=False,
    )
    terms: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class SoftwareTier(TimestampMixin, Base):
    """A Business Manager monthly subscription tier keyed by annual turnover."""

    __tablename__ = "pricing_software_tiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    turnover_min: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    turnover_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    monthly_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    features: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ITRPrice(TimestampMixin, Base):
    """ITR filing price band. ITR filing is always separate from accounting packages."""

    __tablename__ = "pricing_itr_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    price_min: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    price_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    price_note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PricingAddon(TimestampMixin, Base):
    """Optional service charge the senior accountant can add to a quotation.

    A null amount means the charge is assessed during review; it is never presented as a
    fixed public price.
    """

    __tablename__ = "pricing_addons"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    cadence: Mapped[str] = mapped_column(String(20), default="annual", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PriceHistory(Base):
    __tablename__ = "pricing_price_history"
    __table_args__ = (Index("ix_pricing_history_entity", "entity_type", "entity_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(64), nullable=False)
    field: Mapped[str] = mapped_column(String(48), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    changed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- tax engine


class TaxRuleSet(TimestampMixin, Base):
    """One published set of income-tax rules for a financial year and regime.

    Slabs, surcharge bands, rebate limits, deduction caps and capital-gain rates all live in
    rows below this table, so a rule change never needs a code change.
    """

    __tablename__ = "tax_rule_sets"
    __table_args__ = (
        UniqueConstraint("financial_year", "regime", "version", name="uq_tax_rule_set_version"),
        Index("ix_tax_rule_sets_year", "financial_year", "regime"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)
    assessment_year: Mapped[str] = mapped_column(String(9), nullable=False)
    regime: Mapped[str] = mapped_column(String(8), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="published", nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    slabs: Mapped[list["TaxSlab"]] = relationship(
        back_populates="rule_set", cascade="all, delete-orphan", order_by="TaxSlab.sequence"
    )
    surcharge_bands: Mapped[list["TaxSurchargeBand"]] = relationship(
        back_populates="rule_set",
        cascade="all, delete-orphan",
        order_by="TaxSurchargeBand.sequence",
    )
    rebate: Mapped["TaxRebateRule | None"] = relationship(
        back_populates="rule_set", cascade="all, delete-orphan", uselist=False
    )
    constants: Mapped[list["TaxConstant"]] = relationship(
        back_populates="rule_set", cascade="all, delete-orphan"
    )
    deduction_caps: Mapped[list["TaxDeductionCap"]] = relationship(
        back_populates="rule_set", cascade="all, delete-orphan"
    )
    capital_gains_rules: Mapped[list["TaxCapitalGainsRule"]] = relationship(
        back_populates="rule_set", cascade="all, delete-orphan"
    )


class TaxSlab(TimestampMixin, Base):
    __tablename__ = "tax_slabs"
    __table_args__ = (Index("ix_tax_slabs_rule", "rule_set_id", "sequence"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_set_id: Mapped[int] = mapped_column(
        ForeignKey("tax_rule_sets.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lower_bound: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    upper_bound: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    rule_set: Mapped[TaxRuleSet] = relationship(back_populates="slabs")


class TaxSurchargeBand(TimestampMixin, Base):
    __tablename__ = "tax_surcharge_bands"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_set_id: Mapped[int] = mapped_column(
        ForeignKey("tax_rule_sets.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    income_above: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    rule_set: Mapped[TaxRuleSet] = relationship(back_populates="surcharge_bands")


class TaxRebateRule(TimestampMixin, Base):
    __tablename__ = "tax_rebate_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_set_id: Mapped[int] = mapped_column(
        ForeignKey("tax_rule_sets.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    income_limit: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    max_rebate: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    marginal_relief: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    rule_set: Mapped[TaxRuleSet] = relationship(back_populates="rebate")


class TaxConstant(TimestampMixin, Base):
    __tablename__ = "tax_constants"
    __table_args__ = (UniqueConstraint("rule_set_id", "code", name="uq_tax_constant_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_set_id: Mapped[int] = mapped_column(
        ForeignKey("tax_rule_sets.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(48), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))

    rule_set: Mapped[TaxRuleSet] = relationship(back_populates="constants")


class TaxDeductionCap(TimestampMixin, Base):
    __tablename__ = "tax_deduction_caps"
    __table_args__ = (
        UniqueConstraint("rule_set_id", "code", name="uq_tax_deduction_cap_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_set_id: Mapped[int] = mapped_column(
        ForeignKey("tax_rule_sets.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    cap_amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    percent_of_basic: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    rule_set: Mapped[TaxRuleSet] = relationship(back_populates="deduction_caps")


class TaxCapitalGainsRule(TimestampMixin, Base):
    __tablename__ = "tax_capital_gains_rules"
    __table_args__ = (
        UniqueConstraint("rule_set_id", "category", name="uq_tax_cg_category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_set_id: Mapped[int] = mapped_column(
        ForeignKey("tax_rule_sets.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    exemption_limit: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), default=Decimal("0.00"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)

    rule_set: Mapped[TaxRuleSet] = relationship(back_populates="capital_gains_rules")


class HSNSACClassification(TimestampMixin, BusinessScoped, Base):
    """Owner-maintained HSN (goods) or SAC (services) entry and the GST rate they confirmed."""

    __tablename__ = "hsn_sac_classifications"
    __table_args__ = (
        UniqueConstraint("user_id", "code", name="uq_hsn_user_code"),
        Index("ix_hsn_user_code", "user_id", "code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="goods", nullable=False)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class ITCEntry(TimestampMixin, BusinessScoped, Base):
    """Input Tax Credit recorded from a purchase bill."""

    __tablename__ = "itc_entries"
    __table_args__ = (Index("ix_itc_user_date", "user_id", "invoice_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    supplier_name: Mapped[str] = mapped_column(String(160), nullable=False)
    supplier_gstin: Mapped[str | None] = mapped_column(String(15))
    invoice_number: Mapped[str] = mapped_column(String(60), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    taxable_value: Mapped[Decimal] = money()
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    cgst_amount: Mapped[Decimal] = money()
    sgst_amount: Mapped[Decimal] = money()
    igst_amount: Mapped[Decimal] = money()
    eligible_amount: Mapped[Decimal] = money()
    status: Mapped[str] = mapped_column(String(16), default="eligible", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AccountingEnquiry(TimestampMixin, Base):
    """A public request for professional accounting services."""

    __tablename__ = "accounting_enquiries"
    __table_args__ = (Index("ix_accounting_enquiries_status", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    business_name: Mapped[str] = mapped_column(String(180), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    business_type: Mapped[str] = mapped_column(String(60), nullable=False)
    turnover_range: Mapped[str] = mapped_column(String(40), nullable=False)
    gst_status: Mapped[str] = mapped_column(String(40), nullable=False)
    services: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    monthly_transactions: Mapped[int | None] = mapped_column(Integer)
    requirements: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="new", nullable=False)
    source: Mapped[str] = mapped_column(String(24), default="website", nullable=False)
    consent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    assigned_senior_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    internal_notes: Mapped[str | None] = mapped_column(Text)
    # Quotation-request detail. The public form collects these so the senior can start
    # from the 2% indicative benchmark without re-keying the business profile.
    annual_turnover: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    bank_accounts: Mapped[int | None] = mapped_column(Integer)
    payroll_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    inventory_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    financial_year: Mapped[str | None] = mapped_column(String(9))
    benchmark_annual: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    customer_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AccountingQuotation(TimestampMixin, Base):
    """A prepared, customised quotation. Amounts are never generated automatically."""

    __tablename__ = "accounting_quotations"
    __table_args__ = (Index("ix_accounting_quotations_status", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    enquiry_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_enquiries.id", ondelete="SET NULL"), index=True
    )
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="SET NULL")
    )
    prepared_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    # Payable amount for one billing period (see payment_frequency), kept for legacy rows.
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    billing_cadence: Mapped[str] = mapped_column(String(24), default="monthly", nullable=False)
    scope: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    terms: Mapped[str | None] = mapped_column(Text)
    valid_until: Mapped[date | None] = mapped_column(Date)
    # draft -> approved -> sent -> accepted / declined, or rejected before sending.
    status: Mapped[str] = mapped_column(String(20), default="sent", nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime)
    response_note: Mapped[str | None] = mapped_column(Text)
    # Quote calculator snapshot. Every total is recomputed and stored server-side.
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    annual_turnover: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    benchmark_annual: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    subtotal_annual: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), default=Decimal("0.00"), nullable=False
    )
    total_annual: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), default=Decimal("0.00"), nullable=False
    )
    monthly_equivalent: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), default=Decimal("0.00"), nullable=False
    )
    discount_type: Mapped[str] = mapped_column(String(12), default="none", nullable=False)
    discount_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), default=Decimal("0.00"), nullable=False
    )
    discount_note: Mapped[str | None] = mapped_column(Text)
    payment_frequency: Mapped[str] = mapped_column(String(20), default="monthly", nullable=False)
    validity_days: Mapped[int | None] = mapped_column(Integer)
    tax_rate_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("18.00"), nullable=False
    )
    tax_note: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejected_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    rejection_note: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)

    enquiry: Mapped[AccountingEnquiry | None] = relationship()
    client: Mapped["AccountingClient | None"] = relationship()
    prepared_by: Mapped["User | None"] = relationship(foreign_keys=[prepared_by_user_id])
    approved_by: Mapped["User | None"] = relationship(foreign_keys=[approved_by_user_id])
    rejected_by: Mapped["User | None"] = relationship(foreign_keys=[rejected_by_user_id])


class AccountingClient(TimestampMixin, Base):
    """A business onboarded into the accounting practice."""

    __tablename__ = "accounting_clients"
    __table_args__ = (
        Index("ix_accounting_clients_status", "status", "created_at"),
        Index("ix_accounting_clients_integration", "integration_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    business_name: Mapped[str] = mapped_column(String(180), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    business_type: Mapped[str] = mapped_column(String(60), nullable=False)
    turnover_range: Mapped[str] = mapped_column(String(40), nullable=False)
    gst_status: Mapped[str] = mapped_column(String(40), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15))
    # Full PAN is never stored; the last four characters support verification only.
    pan_last4: Mapped[str | None] = mapped_column(String(4))
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)
    service_package: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="onboarding", nullable=False)
    customer_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    # Optional link to a Business Manager profile so the practice can see which
    # demo/self-service business this engagement belongs to.
    business_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_profiles.id", ondelete="SET NULL"), index=True
    )
    senior_accountant_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    assigned_junior_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    # Business Manager integration. Disabled until a senior explicitly links the
    # engagement; the owner can only read the resulting status.
    integration_status: Mapped[str] = mapped_column(
        String(24), default="not_linked", nullable=False
    )
    integration_enabled_at: Mapped[datetime | None] = mapped_column(DateTime)
    integration_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    integration_settings: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    gst_catalogue_access: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    customer_user: Mapped[User | None] = relationship(foreign_keys=[customer_user_id])
    business_profile: Mapped[BusinessProfile | None] = relationship()
    senior_accountant: Mapped[User | None] = relationship(foreign_keys=[senior_accountant_user_id])
    assigned_junior: Mapped[User | None] = relationship(foreign_keys=[assigned_junior_user_id])


class AccountingTask(TimestampMixin, Base):
    __tablename__ = "accounting_tasks"
    __table_args__ = (
        Index("ix_accounting_tasks_client_status", "client_id", "status"),
        Index("ix_accounting_tasks_assignee_due", "assigned_to_user_id", "due_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    service_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="unassigned", nullable=False)
    priority: Mapped[str] = mapped_column(String(16), default="normal", nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    assigned_to_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    review_notes: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)

    client: Mapped[AccountingClient] = relationship()
    assignee: Mapped[User | None] = relationship(foreign_keys=[assigned_to_user_id])
    comments: Mapped[list["AccountingTaskComment"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="AccountingTaskComment.id"
    )


class AccountingTaskComment(Base):
    __tablename__ = "accounting_task_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    author_label: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    task: Mapped[AccountingTask] = relationship(back_populates="comments")


class AccountingDocument(TimestampMixin, Base):
    __tablename__ = "accounting_documents"
    __table_args__ = (
        Index("ix_accounting_documents_client", "client_id", "created_at"),
        Index("ix_accounting_documents_hash", "client_id", "sha256"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    category: Mapped[str] = mapped_column(String(32), default="other", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), default="internal", nullable=False)
    source: Mapped[str] = mapped_column(String(24), default="accountant", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="received", nullable=False)
    verified_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)

    client: Mapped[AccountingClient] = relationship()


class AccountingDocumentRequest(TimestampMixin, Base):
    __tablename__ = "accounting_document_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    fulfilled_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_documents.id", ondelete="SET NULL")
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime)


class AccountingMessage(Base):
    __tablename__ = "accounting_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    author_label: Mapped[str] = mapped_column(String(160), nullable=False)
    author_role: Mapped[str] = mapped_column(String(24), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    read_by_staff_at: Mapped[datetime | None] = mapped_column(DateTime)
    read_by_customer_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AccountingVoucher(TimestampMixin, Base):
    """A posted sale, purchase, journal or payment for a client's books."""

    __tablename__ = "accounting_vouchers"
    __table_args__ = (
        UniqueConstraint("client_id", "dedupe_hash", name="uq_accounting_voucher_dedupe"),
        Index("ix_accounting_vouchers_client_date", "client_id", "voucher_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    voucher_type: Mapped[str] = mapped_column(String(16), nullable=False)
    number: Mapped[str] = mapped_column(String(60), nullable=False)
    voucher_date: Mapped[date] = mapped_column(Date, nullable=False)
    party_name: Mapped[str] = mapped_column(String(180), nullable=False)
    party_gstin: Mapped[str | None] = mapped_column(String(15))
    ledger_name: Mapped[str] = mapped_column(String(120), nullable=False)
    bank_ledger: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[str | None] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(Text)
    taxable_value: Mapped[Decimal] = money()
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"), nullable=False)
    inter_state: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cgst_amount: Mapped[Decimal] = money()
    sgst_amount: Mapped[Decimal] = money()
    igst_amount: Mapped[Decimal] = money()
    total_amount: Mapped[Decimal] = money()
    source: Mapped[str] = mapped_column(String(24), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="posted", nullable=False)
    dedupe_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Set only when a posted voucher originated from a Business Manager transaction.
    # Historical Tally imports never populate these columns.
    source_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_business_transactions.id", ondelete="SET NULL"), index=True
    )
    entry_draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_entry_drafts.id", ondelete="SET NULL"), index=True
    )
    source_hash: Mapped[str | None] = mapped_column(String(64))

    client: Mapped[AccountingClient] = relationship()


class AccountingVoucherLine(Base):
    """Debit/credit split for a posted voucher created through the integration."""

    __tablename__ = "accounting_voucher_lines"
    __table_args__ = (
        UniqueConstraint("voucher_id", "line_no", name="uq_accounting_voucher_line_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    voucher_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_vouchers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    ledger_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    debit: Mapped[Decimal] = money()
    credit: Mapped[Decimal] = money()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    voucher: Mapped[AccountingVoucher] = relationship()


class AccountingBusinessTransaction(TimestampMixin, Base):
    """Read-only inbox copy of one Business Manager transaction.

    Rows are keyed by (client, source_type, source_id) so repeated syncs cannot
    create duplicates. This inbox is intentionally separate from historical Tally
    imports, which live in AccountingHistoricalVoucher.
    """

    __tablename__ = "accounting_business_transactions"
    __table_args__ = (
        UniqueConstraint(
            "client_id", "source_type", "source_id", name="uq_business_txn_source"
        ),
        Index("ix_business_txns_client_date", "client_id", "transaction_date"),
        Index("ix_business_txns_client_status", "client_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_profiles.id", ondelete="SET NULL"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_ref: Mapped[str] = mapped_column(String(60), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(24), nullable=False)
    category: Mapped[str | None] = mapped_column(String(60))
    party_name: Mapped[str] = mapped_column(String(180), nullable=False)
    party_gstin: Mapped[str | None] = mapped_column(String(15))
    narration: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    taxable_value: Mapped[Decimal] = money()
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    cgst_amount: Mapped[Decimal] = money()
    sgst_amount: Mapped[Decimal] = money()
    igst_amount: Mapped[Decimal] = money()
    total_amount: Mapped[Decimal] = money()
    source_status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    issue_reason: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    client: Mapped[AccountingClient] = relationship()
    lines: Mapped[list["AccountingBusinessTransactionLine"]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="AccountingBusinessTransactionLine.line_no",
    )


class AccountingBusinessTransactionLine(Base):
    __tablename__ = "accounting_business_transaction_lines"
    __table_args__ = (
        UniqueConstraint("transaction_id", "line_no", name="uq_business_txn_line_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_business_transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    hsn_sac: Mapped[str | None] = mapped_column(String(12))
    item_type: Mapped[str] = mapped_column(String(16), default="goods", nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), default=Decimal("0.000"), nullable=False
    )
    unit: Mapped[str] = mapped_column(String(24), default="pcs", nullable=False)
    rate: Mapped[Decimal] = money()
    taxable_value: Mapped[Decimal] = money()
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    cgst_amount: Mapped[Decimal] = money()
    sgst_amount: Mapped[Decimal] = money()
    igst_amount: Mapped[Decimal] = money()
    total_amount: Mapped[Decimal] = money()
    suggested_ledger: Mapped[str | None] = mapped_column(String(120))

    transaction: Mapped[AccountingBusinessTransaction] = relationship(back_populates="lines")


class AccountingLedgerMapping(TimestampMixin, Base):
    """Client-scoped default ledgers used when drafting an accounting entry."""

    __tablename__ = "accounting_ledger_mappings"
    __table_args__ = (
        UniqueConstraint(
            "client_id", "transaction_type", "category", name="uq_ledger_mapping_scope"
        ),
        Index("ix_ledger_mappings_client", "client_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_type: Mapped[str] = mapped_column(String(24), nullable=False)
    category: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    debit_ledger: Mapped[str] = mapped_column(String(120), nullable=False)
    credit_ledger: Mapped[str] = mapped_column(String(120), nullable=False)
    tax_ledger: Mapped[str | None] = mapped_column(String(120))
    bank_ledger: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AccountingEntryDraft(TimestampMixin, Base):
    """A proposed double-entry voucher awaiting accountant review."""

    __tablename__ = "accounting_entry_drafts"
    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_entry_draft_transaction"),
        Index("ix_entry_drafts_client_status", "client_id", "status"),
        Index("ix_entry_drafts_client_date", "client_id", "voucher_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_business_transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    voucher_type: Mapped[str] = mapped_column(String(16), nullable=False)
    number: Mapped[str] = mapped_column(String(60), nullable=False)
    voucher_date: Mapped[date] = mapped_column(Date, nullable=False)
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)
    party_name: Mapped[str] = mapped_column(String(180), nullable=False)
    party_gstin: Mapped[str | None] = mapped_column(String(15))
    narration: Mapped[str | None] = mapped_column(Text)
    total_debit: Mapped[Decimal] = money()
    total_credit: Mapped[Decimal] = money()
    difference: Mapped[Decimal] = money()
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prepared_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    review_note: Mapped[str | None] = mapped_column(Text)

    transaction: Mapped[AccountingBusinessTransaction] = relationship()
    lines: Mapped[list["AccountingEntryDraftLine"]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="AccountingEntryDraftLine.line_no",
    )


class AccountingEntryDraftLine(Base):
    __tablename__ = "accounting_entry_draft_lines"
    __table_args__ = (
        UniqueConstraint("draft_id", "line_no", name="uq_entry_draft_line_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_entry_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    ledger_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    debit: Mapped[Decimal] = money()
    credit: Mapped[Decimal] = money()

    draft: Mapped[AccountingEntryDraft] = relationship(back_populates="lines")


class AccountingIntegrationRun(TimestampMixin, Base):
    """Audit record for each Business Manager to accounting sync attempt."""

    __tablename__ = "accounting_integration_runs"
    __table_args__ = (
        Index("ix_integration_runs_client", "client_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_profiles.id", ondelete="SET NULL")
    )
    run_type: Mapped[str] = mapped_column(String(24), default="manual_sync", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    client: Mapped[AccountingClient] = relationship()


class AccountingBankImport(TimestampMixin, Base):
    __tablename__ = "accounting_bank_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    imported_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_connections.id", ondelete="SET NULL"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    account_label: Mapped[str | None] = mapped_column(String(160))
    parsing_format: Mapped[str | None] = mapped_column(String(16))
    source_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uncertain_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="imported", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    transactions: Mapped[list["AccountingBankTransaction"]] = relationship(
        back_populates="import_record",
        cascade="all, delete-orphan",
        order_by="AccountingBankTransaction.txn_date",
    )


class AccountingBankTransaction(TimestampMixin, Base):
    __tablename__ = "accounting_bank_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_bank_imports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))
    debit: Mapped[Decimal] = money()
    credit: Mapped[Decimal] = money()
    direction: Mapped[str] = mapped_column(String(16), default="debit", nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    issues: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    corrected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_bank_transactions.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), default="unmatched", nullable=False)
    matched_voucher_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_vouchers.id", ondelete="SET NULL")
    )
    match_score: Mapped[int | None] = mapped_column(Integer)
    match_note: Mapped[str | None] = mapped_column(Text)

    import_record: Mapped[AccountingBankImport] = relationship(back_populates="transactions")


class AccountingTallyBatch(TimestampMixin, Base):
    __tablename__ = "accounting_tally_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(String(12), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(12), default="csv", nullable=False)
    stored_name: Mapped[str | None] = mapped_column(String(120))
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class AccountingStockItem(TimestampMixin, Base):
    """Stock item master exported to TallyPrime (name, SKU, HSN, unit, opening balance)."""

    __tablename__ = "accounting_stock_items"
    __table_args__ = (
        UniqueConstraint("client_id", "sku", name="uq_accounting_stock_item_sku"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    sku: Mapped[str] = mapped_column(String(60), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), default="Nos", nullable=False)
    hsn_sac: Mapped[str | None] = mapped_column(String(12))
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    opening_qty: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), default=Decimal("0.000"), nullable=False
    )
    opening_rate: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), default=Decimal("0.00"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AccountingTallyExport(TimestampMixin, Base):
    """A prepared Excel/CSV export batch that a senior accountant must approve."""

    __tablename__ = "accounting_tally_exports"
    __table_args__ = (
        Index("ix_accounting_tally_exports_client", "client_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    export_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    file_format: Mapped[str] = mapped_column(String(8), default="xlsx", nullable=False)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str | None] = mapped_column(String(120))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    voucher_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    master_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    prepared_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approval_note: Mapped[str | None] = mapped_column(Text)
    import_status: Mapped[str] = mapped_column(
        String(24), default="not_imported", nullable=False
    )
    import_note: Mapped[str | None] = mapped_column(Text)
    validation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    client: Mapped[AccountingClient] = relationship()


class AccountingDataExport(TimestampMixin, Base):
    """A read-only export of an authorized business's records for an accountant.

    The workbook and Tally files are immutable snapshots: later edits to the
    source records never rewrite an export that was already downloaded.
    """

    __tablename__ = "accounting_data_exports"
    __table_args__ = (
        Index("ix_accounting_data_exports_client", "client_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    export_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str | None] = mapped_column(String(120))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="exported", nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    client: Mapped[AccountingClient] = relationship()


class AccountingTallyMigration(TimestampMixin, Base):
    """A staged TallyPrime historical import awaiting review and approval."""

    __tablename__ = "accounting_tally_migrations"
    __table_args__ = (
        Index("ix_accounting_tally_migrations_client", "client_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(String(20), default="import", nullable=False)
    tally_version: Mapped[str] = mapped_column(String(40), nullable=False)
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    opening_date: Mapped[date | None] = mapped_column(Date)
    import_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_format: Mapped[str] = mapped_column(String(12), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str | None] = mapped_column(String(120))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="validated", nullable=False)
    prepared_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approval_note: Mapped[str | None] = mapped_column(Text)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime)
    rolled_back_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    mapping_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_tally_mapping_templates.id", ondelete="SET NULL")
    )
    validation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    retained_until: Mapped[date | None] = mapped_column(Date)

    rows: Mapped[list["AccountingTallyMigrationRow"]] = relationship(
        back_populates="migration",
        cascade="all, delete-orphan",
        order_by="AccountingTallyMigrationRow.row_number",
    )


class AccountingTallyMigrationRow(TimestampMixin, Base):
    __tablename__ = "accounting_tally_migration_rows"
    __table_args__ = (Index("ix_tally_migration_rows_batch", "migration_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    migration_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_tally_migrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    record_type: Mapped[str] = mapped_column(String(24), default="voucher", nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="valid", nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    problems: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    mapped: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    historical_voucher_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_historical_vouchers.id", ondelete="SET NULL")
    )

    migration: Mapped[AccountingTallyMigration] = relationship(back_populates="rows")


class AccountingTallyMappingTemplate(TimestampMixin, Base):
    __tablename__ = "accounting_tally_mapping_templates"
    __table_args__ = (
        Index("ix_tally_mapping_templates_client", "client_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE")
    )
    file_format: Mapped[str] = mapped_column(String(12), default="csv", nullable=False)
    import_type: Mapped[str] = mapped_column(String(32), default="complete", nullable=False)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    is_shared: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AccountingHistoricalLedger(TimestampMixin, Base):
    """A ledger master imported from Tally, kept separate from live entries."""

    __tablename__ = "accounting_historical_ledgers"
    __table_args__ = (
        UniqueConstraint(
            "client_id", "name", "financial_year", name="uq_historical_ledger_name"
        ),
        Index("ix_historical_ledgers_client", "client_id", "financial_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    migration_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_tally_migrations.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    group_name: Mapped[str] = mapped_column(String(120), default="Suspense Account", nullable=False)
    parent_group: Mapped[str | None] = mapped_column(String(120))
    gstin: Mapped[str | None] = mapped_column(String(15))
    party_type: Mapped[str] = mapped_column(String(16), default="other", nullable=False)
    opening_debit: Mapped[Decimal] = money()
    opening_credit: Mapped[Decimal] = money()
    opening_date: Mapped[date | None] = mapped_column(Date)
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)
    source_row: Mapped[int | None] = mapped_column(Integer)


class AccountingHistoricalVoucher(TimestampMixin, Base):
    """An imported Tally voucher. It never posts into the live FINOVEXA ledger."""

    __tablename__ = "accounting_historical_vouchers"
    __table_args__ = (
        UniqueConstraint("client_id", "fingerprint", name="uq_historical_voucher_fingerprint"),
        Index("ix_historical_vouchers_client_date", "client_id", "voucher_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    migration_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_tally_migrations.id", ondelete="SET NULL")
    )
    voucher_type: Mapped[str] = mapped_column(String(24), nullable=False)
    number: Mapped[str] = mapped_column(String(80), nullable=False)
    voucher_date: Mapped[date] = mapped_column(Date, nullable=False)
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)
    party_name: Mapped[str | None] = mapped_column(String(180))
    party_gstin: Mapped[str | None] = mapped_column(String(15))
    narration: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(String(120))
    original_type: Mapped[str | None] = mapped_column(String(60))
    taxable_value: Mapped[Decimal] = money()
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    cgst_amount: Mapped[Decimal] = money()
    sgst_amount: Mapped[Decimal] = money()
    igst_amount: Mapped[Decimal] = money()
    total_debit: Mapped[Decimal] = money()
    total_credit: Mapped[Decimal] = money()
    inter_state: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_format: Mapped[str] = mapped_column(String(12), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_row: Mapped[int | None] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="posted", nullable=False)

    lines: Mapped[list["AccountingHistoricalVoucherLine"]] = relationship(
        back_populates="voucher",
        cascade="all, delete-orphan",
        order_by="AccountingHistoricalVoucherLine.line_number",
    )


class AccountingHistoricalVoucherLine(Base):
    __tablename__ = "accounting_historical_voucher_lines"
    __table_args__ = (Index("ix_historical_voucher_lines_voucher", "voucher_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    voucher_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_historical_vouchers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    ledger_name: Mapped[str] = mapped_column(String(180), nullable=False)
    ledger_group: Mapped[str | None] = mapped_column(String(120))
    debit: Mapped[Decimal] = money()
    credit: Mapped[Decimal] = money()
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    stock_item: Mapped[str | None] = mapped_column(String(180))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(String(16))
    hsn_sac: Mapped[str | None] = mapped_column(String(12))
    narration: Mapped[str | None] = mapped_column(Text)
    is_party: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    voucher: Mapped[AccountingHistoricalVoucher] = relationship(back_populates="lines")


class AccountingOpeningBalance(TimestampMixin, Base):
    __tablename__ = "accounting_opening_balances"
    __table_args__ = (
        UniqueConstraint("client_id", "financial_year", name="uq_opening_balance_financial_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)
    opening_date: Mapped[date] = mapped_column(Date, nullable=False)
    migration_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_tally_migrations.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(24), default="pending_approval", nullable=False)
    prepared_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approval_note: Mapped[str | None] = mapped_column(Text)
    total_debit: Mapped[Decimal] = money()
    total_credit: Mapped[Decimal] = money()
    stock_value: Mapped[Decimal] = money()
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    lines: Mapped[list["AccountingOpeningBalanceLine"]] = relationship(
        back_populates="opening",
        cascade="all, delete-orphan",
        order_by="AccountingOpeningBalanceLine.line_number",
    )


class AccountingOpeningBalanceLine(Base):
    __tablename__ = "accounting_opening_balance_lines"
    __table_args__ = (Index("ix_opening_balance_lines_opening", "opening_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    opening_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_opening_balances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    ledger_name: Mapped[str] = mapped_column(String(180), nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(120))
    party_type: Mapped[str] = mapped_column(String(16), default="other", nullable=False)
    debit: Mapped[Decimal] = money()
    credit: Mapped[Decimal] = money()
    stock_item: Mapped[str | None] = mapped_column(String(180))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    value: Mapped[Decimal] = money()
    narration: Mapped[str | None] = mapped_column(Text)

    opening: Mapped[AccountingOpeningBalance] = relationship(back_populates="lines")


class AccountingReport(TimestampMixin, Base):
    __tablename__ = "accounting_reports"
    __table_args__ = (Index("ix_accounting_reports_client", "client_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)
    period_label: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    prepared_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    review_notes: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    client: Mapped[AccountingClient] = relationship()


class AccountingInvoice(TimestampMixin, Base):
    """A practice service invoice issued to an accounting client."""

    __tablename__ = "accounting_invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_label: Mapped[str | None] = mapped_column(String(40))
    subtotal: Mapped[Decimal] = money()
    tax_amount: Mapped[Decimal] = money()
    total_amount: Mapped[Decimal] = money()
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="issued", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    client: Mapped[AccountingClient] = relationship()
    payments: Mapped[list["AccountingInvoicePayment"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )

    @property
    def paid_amount(self) -> Decimal:
        return sum((p.amount for p in self.payments), Decimal("0.00"))

    @property
    def outstanding_amount(self) -> Decimal:
        if self.status == "void":
            return Decimal("0.00")
        return max(self.total_amount - self.paid_amount, Decimal("0.00"))


class AccountingInvoicePayment(Base):
    __tablename__ = "accounting_invoice_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(24), default="bank", nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    invoice: Mapped[AccountingInvoice] = relationship(back_populates="payments")


class AccountingNotification(Base):
    __tablename__ = "accounting_notifications"
    __table_args__ = (Index("ix_accounting_notifications_user", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class IncomeTaxEstimate(TimestampMixin, BusinessScoped, Base):
    """A saved, reproducible income-tax estimate with an optional accountant sign-off."""

    __tablename__ = "income_tax_estimates"
    __table_args__ = (Index("ix_tax_estimates_user_year", "user_id", "financial_year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False)
    regime: Mapped[str] = mapped_column(String(8), nullable=False)
    rule_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("tax_rule_sets.id", ondelete="SET NULL")
    )
    rule_version: Mapped[str | None] = mapped_column(String(40))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    approved_by_name: Mapped[str | None] = mapped_column(String(120))
    membership_number: Mapped[str | None] = mapped_column(String(60))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approval_note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class PaymentConnection(TimestampMixin, BusinessScoped, Base):
    """An owner-authorised link to a payment provider or a statement account.

    Credentials themselves never live here; only non-secret state, consent
    timestamps and the last sync outcome.
    """

    __tablename__ = "payment_connections"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "client_id",
            "provider",
            "environment",
            name="uq_payment_connections_owner_client_provider_env",
        ),
        Index("ix_payment_connections_client_provider", "client_id", "provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="SET NULL"), index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), default="sandbox", nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="sandbox", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    merchant_id: Mapped[str | None] = mapped_column(String(120))
    account_hint: Mapped[str | None] = mapped_column(String(160))
    outlet_label: Mapped[str | None] = mapped_column(String(120))
    permissions: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])
    transactions: Mapped[list["PaymentTransaction"]] = relationship(
        back_populates="connection"
    )
    sync_runs: Mapped[list["PaymentSyncRun"]] = relationship(back_populates="connection")


class PaymentTransaction(TimestampMixin, BusinessScoped, Base):
    """One provider, statement or demo money movement in the unified history."""

    __tablename__ = "payment_transactions"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "external_id", name="uq_payment_transactions_connection_external"
        ),
        Index("ix_payment_transactions_user_date", "user_id", "occurred_on"),
        Index("ix_payment_transactions_client_status", "client_id", "reconciliation_status"),
        Index("ix_payment_transactions_provider_status", "provider", "status"),
        Index("ix_payment_transactions_dedupe", "dedupe_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_connections.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_clients.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), default="sandbox", nullable=False)
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    parent_external_id: Mapped[str | None] = mapped_column(String(160))
    direction: Mapped[str] = mapped_column(String(16), default="incoming", nullable=False)
    txn_type: Mapped[str] = mapped_column(String(24), default="payment", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    fee_amount: Mapped[Decimal] = money()
    net_amount: Mapped[Decimal] = money()
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="unknown", nullable=False)
    occurred_on: Mapped[date | None] = mapped_column(Date)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime)
    description: Mapped[str | None] = mapped_column(Text)
    counterparty: Mapped[str | None] = mapped_column(String(200))
    reference: Mapped[str | None] = mapped_column(String(160))
    provider_reference: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(16), default="api", nullable=False)
    import_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_bank_imports.id", ondelete="SET NULL"), index=True
    )
    bank_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_bank_transactions.id", ondelete="SET NULL")
    )
    bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="SET NULL"), index=True
    )
    statement_import_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_statement_imports.id", ondelete="SET NULL"), index=True
    )
    value_date: Mapped[date | None] = mapped_column(Date)
    balance: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    match_category: Mapped[str | None] = mapped_column(String(2))
    explained_kind: Mapped[str | None] = mapped_column(String(24))
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    dedupe_hash: Mapped[str | None] = mapped_column(String(64))
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_transactions.id", ondelete="SET NULL"), index=True
    )
    reconciliation_status: Mapped[str] = mapped_column(
        String(24), default="unverified", nullable=False
    )
    matched_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), index=True
    )
    matched_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"), index=True
    )
    match_score: Mapped[int | None] = mapped_column(Integer)
    match_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)
    outlet_label: Mapped[str | None] = mapped_column(String(120))
    accounting_draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_entry_drafts.id", ondelete="SET NULL")
    )
    accounting_voucher_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_vouchers.id", ondelete="SET NULL")
    )

    connection: Mapped[PaymentConnection | None] = relationship(back_populates="transactions")
    invoice: Mapped[Invoice | None] = relationship(foreign_keys=[matched_invoice_id])
    payment: Mapped[Payment | None] = relationship(foreign_keys=[matched_payment_id])
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_user_id])
    duplicate_of: Mapped["PaymentTransaction | None"] = relationship(
        remote_side=[id], foreign_keys=[duplicate_of_id]
    )
    events: Mapped[list["PaymentReconciliationEvent"]] = relationship(
        back_populates="transaction"
    )


class PaymentSyncRun(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "payment_sync_runs"
    __table_args__ = (
        Index("ix_payment_sync_runs_connection_started", "connection_id", "started_at"),
        Index("ix_payment_sync_runs_provider_status", "provider", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("payment_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(String(24), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    range_start: Mapped[datetime | None] = mapped_column(DateTime)
    range_end: Mapped[datetime | None] = mapped_column(DateTime)
    fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    actor: Mapped[str | None] = mapped_column(String(160))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    connection: Mapped[PaymentConnection] = relationship(back_populates="sync_runs")


class PaymentReconciliationEvent(BusinessScoped, Base):
    __tablename__ = "payment_reconciliation_events"
    __table_args__ = (
        Index("ix_payment_reconciliation_events_txn_created", "transaction_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("payment_transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(160), default="system", nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"))
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"))
    expense_id: Mapped[int | None] = mapped_column(
        ForeignKey("expenses.id", ondelete="SET NULL"), index=True
    )
    supplier_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("supplier_payments.id", ondelete="SET NULL"), index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    transaction: Mapped[PaymentTransaction] = relationship(back_populates="events")


class StoredFile(TimestampMixin, Base):
    """Uploaded document bytes kept in the database for hosts without a disk."""

    __tablename__ = "stored_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    stored_name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class Supplier(TimestampMixin, BusinessScoped, Base):
    """Supplier master. Historical expense vendor text is never rewritten."""

    __tablename__ = "suppliers"
    __table_args__ = (
        Index("ix_suppliers_user_normalized_name", "user_id", "normalized_name"),
        Index("ix_suppliers_user_gstin", "user_id", "gstin"),
        Index("ix_suppliers_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(160), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255))
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(80))
    state_code: Mapped[str | None] = mapped_column(String(2))
    postal_code: Mapped[str | None] = mapped_column(String(10))
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    credit_limit: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), default=Decimal("0.00"), nullable=False
    )
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), default=Decimal("0.00"), nullable=False
    )
    opening_balance_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class SupplierPayment(TimestampMixin, BusinessScoped, Base):
    """Money-out against purchase bills. ``expense_id`` NULL marks an advance."""

    __tablename__ = "supplier_payments"
    __table_args__ = (
        Index("ix_supplier_payments_user_supplier_paid", "user_id", "supplier_id", "paid_on"),
        Index("ix_supplier_payments_user_expense", "user_id", "expense_id"),
        Index("ix_supplier_payments_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    expense_id: Mapped[int | None] = mapped_column(
        ForeignKey("expenses.id", ondelete="SET NULL"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(160))
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="confirmed", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    voided_at: Mapped[datetime | None] = mapped_column(DateTime)
    void_reason: Mapped[str | None] = mapped_column(Text)


class CustomerAdjustment(BusinessScoped, Base):
    """Credit notes, write-offs and other non-payment ledger adjustments."""

    __tablename__ = "customer_adjustments"
    __table_args__ = (
        UniqueConstraint("user_id", "number", name="uq_customer_adjustments_user_number"),
        Index(
            "ix_customer_adjustments_user_customer_date",
            "user_id",
            "customer_id",
            "issued_on",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class CreditAlertSettings(TimestampMixin, BusinessScoped, Base):
    __tablename__ = "credit_alert_settings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_credit_alert_settings_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    utilization_warn_pct: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    utilization_critical_pct: Mapped[int] = mapped_column(
        Integer, default=100, nullable=False
    )
    due_soon_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    overdue_escalation_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    supplier_due_soon_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class CreditAlert(TimestampMixin, BusinessScoped, Base):
    """Credit and payables alert. Deduplicated by a deterministic key."""

    __tablename__ = "credit_alerts"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_credit_alerts_dedupe_key"),
        Index("ix_credit_alerts_user_status_created", "user_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), index=True
    )
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), index=True
    )
    expense_id: Mapped[int | None] = mapped_column(
        ForeignKey("expenses.id", ondelete="SET NULL"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    due_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime)


class BankAccount(TimestampMixin, BusinessScoped, Base):
    """A bank account used for reconciliation. Only a masked number is stored."""

    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "account_fingerprint", name="uq_bank_accounts_user_fingerprint"
        ),
        Index("ix_bank_accounts_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bank_name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_number_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    account_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    ifsc: Mapped[str | None] = mapped_column(String(11))
    branch: Mapped[str | None] = mapped_column(String(120))
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), default=Decimal("0.00"), nullable=False
    )
    opening_balance_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    last_reconciled_on: Mapped[date | None] = mapped_column(Date)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class BankStatementImport(TimestampMixin, BusinessScoped, Base):
    """One immutable uploaded statement file per bank account and file hash."""

    __tablename__ = "bank_statement_imports"
    __table_args__ = (
        UniqueConstraint(
            "bank_account_id",
            "file_sha256",
            name="uq_bank_statement_imports_account_file",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bank_account_id: Mapped[int] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    stored_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("stored_files.id", ondelete="SET NULL")
    )
    column_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    status: Mapped[str] = mapped_column(String(16), default="imported", nullable=False)
    imported_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class BankMatchAllocation(BusinessScoped, Base):
    """Splits one bank transaction across invoices, bills or payments.

    Reversal marks a row ``reversed``; original statement and ledger rows are
    never deleted or overwritten.
    """

    __tablename__ = "bank_match_allocations"
    __table_args__ = (
        Index("ix_bank_match_allocations_txn_status", "transaction_id", "status"),
        Index("ix_bank_match_allocations_invoice_id", "invoice_id"),
        Index("ix_bank_match_allocations_payment_id", "payment_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("payment_transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL")
    )
    expense_id: Mapped[int | None] = mapped_column(
        ForeignKey("expenses.id", ondelete="SET NULL")
    )
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"))
    supplier_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("supplier_payments.id", ondelete="SET NULL")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="confirmed", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime)


class AISetting(TimestampMixin, Base):
    """Developer-controlled AI provider configuration. Single row, key encrypted."""

    __tablename__ = "ai_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    base_url: Mapped[str | None] = mapped_column(String(255))
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    key_hint: Mapped[str | None] = mapped_column(String(12))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    temperature: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), default=Decimal("0.20"), nullable=False
    )
    monthly_request_limit: Mapped[int | None] = mapped_column(Integer)
    monthly_token_limit: Mapped[int | None] = mapped_column(Integer)
    monthly_cost_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AIUsageEvent(Base):
    __tablename__ = "ai_usage_events"
    __table_args__ = (
        Index("ix_ai_usage_events_user_created", "user_id", "created_at"),
        Index("ix_ai_usage_events_created", "created_at"),
        Index("ix_ai_usage_events_business_created", "business_profile_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    business_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_profiles.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_estimate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0.000000"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    error: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class BusinessHealthSnapshot(Base):
    """Monthly Business Health Score with the inputs and weights used."""

    __tablename__ = "business_health_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "period", name="uq_business_health_snapshots_user_period"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_profile_id: Mapped[int] = mapped_column(
        ForeignKey("business_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    overall_score: Mapped[int | None] = mapped_column(Integer)
    cash_flow_score: Mapped[int | None] = mapped_column(Integer)
    profitability_score: Mapped[int | None] = mapped_column(Integer)
    collections_score: Mapped[int | None] = mapped_column(Integer)
    inventory_score: Mapped[int | None] = mapped_column(Integer)
    expense_control_score: Mapped[int | None] = mapped_column(Integer)
    weights: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    data_sufficiency: Mapped[str] = mapped_column(
        String(16), default="sufficient", nullable=False
    )
    strengths: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    weaknesses: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    recommendations: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
