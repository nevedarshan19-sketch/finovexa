"""Idempotent, additive migration for multi-business isolation.

Existing installations keep ``business_profiles`` as the business table: the
first profile of every owner becomes that owner's first business, and every
business record gains a ``business_id`` that points back to it. No row is
deleted, truncated or reseeded, and every step can run repeatedly.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, inspect, text

logger = logging.getLogger("finovexa.business")

# Tables that store business data. Every one of them carries business_id.
TENANT_TABLES: tuple[str, ...] = (
    "customers",
    "products",
    "inventory_items",
    "gst_rates",
    "invoices",
    "invoice_items",
    "invoice_reminders",
    "payments",
    "payment_events",
    "paypal_orders",
    "paypal_refunds",
    "reconciliation_records",
    "expenses",
    "employee_entries",
    "financial_obligations",
    "cash_forecasts",
    "ai_insights",
    "chat_messages",
    "approval_requests",
    "broker_orders",
    "portfolio_holdings",
    "integration_configs",
    "audit_events",
    "hsn_sac_classifications",
    "itc_entries",
    "income_tax_estimates",
    "payment_connections",
    "payment_transactions",
    "payment_sync_runs",
    "payment_reconciliation_events",
)

# Tables scoped directly through a user column (owner, or the employee's owner).
_USER_COLUMNS: dict[str, str] = {
    "customers": "user_id",
    "products": "user_id",
    "gst_rates": "user_id",
    "invoices": "user_id",
    "payments": "user_id",
    "payment_events": "user_id",
    "paypal_orders": "user_id",
    "paypal_refunds": "user_id",
    "reconciliation_records": "user_id",
    "expenses": "user_id",
    "financial_obligations": "user_id",
    "cash_forecasts": "user_id",
    "ai_insights": "user_id",
    "chat_messages": "user_id",
    "approval_requests": "user_id",
    "broker_orders": "user_id",
    "portfolio_holdings": "user_id",
    "integration_configs": "user_id",
    "audit_events": "user_id",
    "hsn_sac_classifications": "user_id",
    "itc_entries": "user_id",
    "income_tax_estimates": "user_id",
    "payment_connections": "user_id",
    "payment_transactions": "user_id",
}

_OWNER_COLUMNS: dict[str, str] = {
    "employee_entries": "owner_id",
}

# Child tables inherit the business of their parent row.
_CHILD_SOURCES: dict[str, tuple[str, str]] = {
    "invoice_items": ("invoices", "invoice_id"),
    "invoice_reminders": ("invoices", "invoice_id"),
    "inventory_items": ("products", "product_id"),
    "payment_sync_runs": ("payment_connections", "connection_id"),
    "payment_reconciliation_events": ("payment_transactions", "transaction_id"),
}

_PROFILE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("owner_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE"),
    ("business_type", "VARCHAR(32) NOT NULL DEFAULT 'private_limited'"),
    ("pan", "VARCHAR(10)"),
    ("financial_year_start_month", "INTEGER NOT NULL DEFAULT 4"),
    ("invoice_prefix", "VARCHAR(12)"),
    ("is_archived", "BOOLEAN NOT NULL DEFAULT {false}"),
    ("archived_at", "TIMESTAMP"),
)


def _false_literal(bind: Engine) -> str:
    return "FALSE" if bind.dialect.name == "postgresql" else "0"


def _run(bind: Engine, statement: str) -> None:
    with bind.begin() as connection:
        connection.execute(text(statement))


def _try(bind: Engine, statement: str) -> None:
    try:
        _run(bind, statement)
    except Exception as exc:  # pragma: no cover - dialect specific DDL
        logger.debug("Business migration step skipped: %s (%s)", statement, exc)


def ensure_business_schema(bind: Engine) -> None:
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "business_profiles" not in tables:
        return

    def columns(table: str) -> set[str]:
        return {column["name"] for column in inspector.get_columns(table)}

    false = _false_literal(bind)
    additions: list[str] = []
    profile_columns = columns("business_profiles")
    for name, ddl in _PROFILE_COLUMNS:
        if name not in profile_columns:
            additions.append(
                f"ALTER TABLE business_profiles ADD COLUMN {name} {ddl.format(false=false)}"
            )

    for table in TENANT_TABLES:
        if table in tables and "business_id" not in columns(table):
            additions.append(
                f"ALTER TABLE {table} ADD COLUMN business_id INTEGER "
                "REFERENCES business_profiles(id) ON DELETE CASCADE"
            )

    for statement in additions:
        _run(bind, statement)

    for table in TENANT_TABLES:
        if table in tables:
            _try(
                bind,
                f"CREATE INDEX IF NOT EXISTS ix_{table}_business_id "
                f"ON {table} (business_id)",
            )

    if bind.dialect.name == "postgresql":
        # A business now has its own row; the legacy one-business-per-user
        # constraint must not block a second business. NULL user_id stays valid.
        _try(
            bind,
            "ALTER TABLE business_profiles DROP CONSTRAINT IF EXISTS "
            "business_profiles_user_id_key",
        )
        _try(bind, "ALTER TABLE business_profiles ALTER COLUMN user_id DROP NOT NULL")
        _try(bind, "ALTER TABLE business_profiles DROP CONSTRAINT IF EXISTS business_profiles_owner_id_fkey")

    _backfill(bind, tables)


def _backfill(bind: Engine, tables: set[str]) -> None:
    false = _false_literal(bind)
    _run(bind, "UPDATE business_profiles SET owner_id = user_id WHERE owner_id IS NULL")

    # Owners that somehow have no profile row still get a first business.
    if "users" in tables:
        _run(
            bind,
            "INSERT INTO business_profiles (user_id, owner_id, business_name, currency, "
            "timezone, reporting_period, min_cash_reserve, opening_cash_balance, "
            "opening_balance_date, risk_tolerance, research_interests, reminder_tone, "
            "business_type, financial_year_start_month, is_archived, created_at, updated_at) "
            "SELECT u.id, u.id, u.full_name, 'INR', 'Asia/Kolkata', 'monthly', 0, 0, "
            "CURRENT_DATE, 'balanced', '[]', 'professional', 'private_limited', 4, "
            f"{false}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM users u "
            "WHERE u.role = 'owner' AND NOT EXISTS ("
            "SELECT 1 FROM business_profiles bp WHERE bp.owner_id = u.id)"
        )

    primary = "(SELECT bp.id FROM business_profiles bp WHERE bp.owner_id = {owner} ORDER BY bp.id LIMIT 1)"

    for table, column in _USER_COLUMNS.items():
        if table not in tables:
            continue
        owner = (
            f"COALESCE((SELECT u.owner_id FROM users u WHERE u.id = {table}.{column}), "
            f"{table}.{column})"
        )
        _run(
            bind,
            f"UPDATE {table} SET business_id = {primary.format(owner=owner)} "
            "WHERE business_id IS NULL",
        )

    for table, column in _OWNER_COLUMNS.items():
        if table not in tables:
            continue
        _run(
            bind,
            f"UPDATE {table} SET business_id = {primary.format(owner=f'{table}.{column}')} "
            "WHERE business_id IS NULL",
        )

    for table, (parent, key) in _CHILD_SOURCES.items():
        if table in tables and parent in tables:
            _run(
                bind,
                f"UPDATE {table} SET business_id = (SELECT p.business_id FROM {parent} p "
                f"WHERE p.id = {table}.{key}) WHERE business_id IS NULL",
            )

    # Payment events may be recorded without a user; inherit through the
    # invoice or payment they refer to.
    if "payment_events" in tables:
        _try(
            bind,
            "UPDATE payment_events SET business_id = (SELECT i.business_id FROM invoices i "
            "WHERE i.id = payment_events.invoice_id) "
            "WHERE business_id IS NULL AND invoice_id IS NOT NULL",
        )
        _try(
            bind,
            "UPDATE payment_events SET business_id = (SELECT p.business_id FROM payments p "
            "WHERE p.id = payment_events.payment_id) "
            "WHERE business_id IS NULL AND payment_id IS NOT NULL",
        )

    _seed_memberships(bind, tables)


def _seed_memberships(bind: Engine, tables: set[str]) -> None:
    if "business_memberships" not in tables:
        return

    # Owners are members of their own businesses.
    _run(
        bind,
        "INSERT INTO business_memberships "
        "(business_id, user_id, role, status, created_at, updated_at) "
        "SELECT bp.id, bp.owner_id, 'owner', 'active', CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP FROM business_profiles bp "
        "WHERE bp.owner_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM business_memberships m WHERE m.business_id = bp.id "
        "AND m.user_id = bp.owner_id)",
    )

    # Existing employees keep their access through the owner's first business.
    if "users" in tables:
        _run(
            bind,
            "INSERT INTO business_memberships "
            "(business_id, user_id, role, status, created_at, updated_at) "
            "SELECT bp.id, u.id, 'employee', 'active', CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP FROM users u JOIN business_profiles bp "
            "ON bp.owner_id = u.owner_id WHERE u.role = 'employee' "
            "AND bp.id = (SELECT MIN(b.id) FROM business_profiles b "
            "WHERE b.owner_id = u.owner_id) AND NOT EXISTS ("
            "SELECT 1 FROM business_memberships m WHERE m.business_id = bp.id "
            "AND m.user_id = u.id)",
        )

    # Accountants are members of every business they are assigned to.
    if "accounting_clients" in tables:
        _run(
            bind,
            "INSERT INTO business_memberships "
            "(business_id, user_id, role, status, created_at, updated_at) "
            "SELECT DISTINCT ac.business_profile_id, u.id, u.role, 'active', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM accounting_clients ac "
            "JOIN users u ON u.id IN (ac.senior_accountant_user_id, "
            "ac.assigned_junior_user_id) WHERE ac.business_profile_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM business_memberships m "
            "WHERE m.business_id = ac.business_profile_id AND m.user_id = u.id)",
        )
