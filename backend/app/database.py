import json
from collections.abc import Generator
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def normalize_database_url(raw: str) -> str:
    """Map hosted Postgres URLs onto the psycopg 3 driver SQLAlchemy expects."""
    if raw.startswith("postgres://"):
        return "postgresql+psycopg://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw[len("postgresql://") :]
    return raw


DATABASE_URL = normalize_database_url(settings.DATABASE_URL)
IS_SQLITE = DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if IS_SQLITE else {}
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    json_serializer=lambda value: json.dumps(value, default=_json_default),
    pool_pre_ping=True,
    pool_recycle=1800,
    future=True,
)


if IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


from .tenancy import TenantSession  # noqa: E402  (tenancy has no database import)

SessionLocal = sessionmaker(
    bind=engine,
    class_=TenantSession,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def ensure_schema_upgrades(bind: Engine = engine) -> None:
    """Additive upgrade for databases created before newer columns and GST billing existed."""
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    def columns(table: str) -> set[str]:
        return {column["name"] for column in inspector.get_columns(table)}

    additions: list[str] = []
    backfill_gst = False
    backfill_integration_link = False
    if "users" in tables:
        user_columns = columns("users")
        if "role" not in user_columns:
            additions.append("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'owner'")
        if "owner_id" not in user_columns:
            additions.append(
                "ALTER TABLE users ADD COLUMN owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE"
            )
    for table in ("invoices", "payments", "expenses"):
        if table in tables and "created_by_user_id" not in columns(table):
            additions.append(
                f"ALTER TABLE {table} ADD COLUMN created_by_user_id INTEGER "
                "REFERENCES users(id) ON DELETE SET NULL"
            )
    if "employee_entries" in tables and "tax_rate" not in columns("employee_entries"):
        additions.append(
            "ALTER TABLE employee_entries ADD COLUMN tax_rate NUMERIC(6, 2) NOT NULL DEFAULT 18"
        )
    if "employee_entries" in tables and "line_items" not in columns("employee_entries"):
        additions.append(
            "ALTER TABLE employee_entries ADD COLUMN line_items JSON NOT NULL DEFAULT '[]'"
        )
    if "employee_entries" in tables and "amount_received" not in columns("employee_entries"):
        additions.append(
            "ALTER TABLE employee_entries ADD COLUMN amount_received NUMERIC(16, 2)"
        )
    if "payments" in tables:
        payment_columns = columns("payments")
        if "reconciliation_status" not in payment_columns:
            additions.append(
                "ALTER TABLE payments ADD COLUMN reconciliation_status "
                "VARCHAR(24) NOT NULL DEFAULT 'unmatched'"
            )
        if "reconciled_at" not in payment_columns:
            timestamp_type = "TIMESTAMP" if bind.dialect.name == "postgresql" else "DATETIME"
            additions.append(f"ALTER TABLE payments ADD COLUMN reconciled_at {timestamp_type}")
        if "refund_of_payment_id" not in payment_columns:
            additions.append(
                "ALTER TABLE payments ADD COLUMN refund_of_payment_id INTEGER "
                "REFERENCES payments(id) ON DELETE SET NULL"
            )
    if "payment_events" in tables:
        event_columns = columns("payment_events")
        if "verification" not in event_columns:
            additions.append("ALTER TABLE payment_events ADD COLUMN verification VARCHAR(32)")
        if "user_id" not in event_columns:
            additions.append(
                "ALTER TABLE payment_events ADD COLUMN user_id INTEGER "
                "REFERENCES users(id) ON DELETE CASCADE"
            )
        if "invoice_id" not in event_columns:
            additions.append(
                "ALTER TABLE payment_events ADD COLUMN invoice_id INTEGER "
                "REFERENCES invoices(id) ON DELETE SET NULL"
            )
        if "payment_id" not in event_columns:
            additions.append(
                "ALTER TABLE payment_events ADD COLUMN payment_id INTEGER "
                "REFERENCES payments(id) ON DELETE SET NULL"
            )
        if "details" not in event_columns:
            additions.append(
                "ALTER TABLE payment_events ADD COLUMN details JSON NOT NULL DEFAULT '{}'"
            )
    if "broker_orders" in tables:
        order_columns = columns("broker_orders")
        if "broker_status" not in order_columns:
            additions.append("ALTER TABLE broker_orders ADD COLUMN broker_status VARCHAR(40)")
        if "broker_status_message" not in order_columns:
            additions.append("ALTER TABLE broker_orders ADD COLUMN broker_status_message TEXT")
        if "order_tag" not in order_columns:
            additions.append("ALTER TABLE broker_orders ADD COLUMN order_tag VARCHAR(64)")
        if "last_synced_at" not in order_columns:
            timestamp_type = "TIMESTAMP" if bind.dialect.name == "postgresql" else "DATETIME"
            additions.append(
                f"ALTER TABLE broker_orders ADD COLUMN last_synced_at {timestamp_type}"
            )

    if "business_profiles" in tables:
        profile_columns = columns("business_profiles")
        for name, ddl in (
            ("legal_name", "VARCHAR(160)"),
            ("gstin", "VARCHAR(15)"),
            ("address_line1", "VARCHAR(200)"),
            ("address_line2", "VARCHAR(200)"),
            ("city", "VARCHAR(80)"),
            ("state", "VARCHAR(80)"),
            ("state_code", "VARCHAR(2)"),
            ("postal_code", "VARCHAR(10)"),
            ("business_phone", "VARCHAR(40)"),
            ("business_email", "VARCHAR(255)"),
            ("invoice_terms", "TEXT"),
            ("logo_data_url", "TEXT"),
            ("gst_change_approval", "VARCHAR(20) NOT NULL DEFAULT 'direct'"),
            ("health_score_weights", "JSON NOT NULL DEFAULT '{}'"),
        ):
            if name not in profile_columns:
                additions.append(f"ALTER TABLE business_profiles ADD COLUMN {name} {ddl}")

    if "customers" in tables:
        customer_columns = columns("customers")
        false_default = "FALSE" if bind.dialect.name == "postgresql" else "0"
        for name, ddl in (
            ("gstin", "VARCHAR(15)"),
            ("billing_address_line1", "VARCHAR(200)"),
            ("billing_address_line2", "VARCHAR(200)"),
            ("city", "VARCHAR(80)"),
            ("state", "VARCHAR(80)"),
            ("state_code", "VARCHAR(2)"),
            ("postal_code", "VARCHAR(10)"),
            ("credit_limit", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("payment_terms_days", "INTEGER NOT NULL DEFAULT 30"),
            ("credit_hold", f"BOOLEAN NOT NULL DEFAULT {false_default}"),
            ("opening_balance", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("opening_balance_date", "DATE"),
            ("notes", "TEXT"),
        ):
            if name not in customer_columns:
                additions.append(f"ALTER TABLE customers ADD COLUMN {name} {ddl}")

    if "expenses" in tables:
        expense_columns = columns("expenses")
        for name, ddl in (
            ("supplier_id", "INTEGER REFERENCES suppliers(id) ON DELETE SET NULL"),
            ("bill_number", "VARCHAR(60)"),
            ("due_date", "DATE"),
            ("payment_status", "VARCHAR(16) NOT NULL DEFAULT 'unpaid'"),
        ):
            if name not in expense_columns:
                additions.append(f"ALTER TABLE expenses ADD COLUMN {name} {ddl}")

    if "payment_transactions" in tables:
        transaction_columns = columns("payment_transactions")
        for name, ddl in (
            ("bank_account_id", "INTEGER REFERENCES bank_accounts(id) ON DELETE SET NULL"),
            (
                "statement_import_id",
                "INTEGER REFERENCES bank_statement_imports(id) ON DELETE SET NULL",
            ),
            ("value_date", "DATE"),
            ("balance", "NUMERIC(16, 2)"),
            ("match_category", "VARCHAR(2)"),
            ("explained_kind", "VARCHAR(24)"),
        ):
            if name not in transaction_columns:
                additions.append(f"ALTER TABLE payment_transactions ADD COLUMN {name} {ddl}")

    if "payment_reconciliation_events" in tables:
        event_columns = columns("payment_reconciliation_events")
        for name, ddl in (
            ("expense_id", "INTEGER REFERENCES expenses(id) ON DELETE SET NULL"),
            (
                "supplier_payment_id",
                "INTEGER REFERENCES supplier_payments(id) ON DELETE SET NULL",
            ),
        ):
            if name not in event_columns:
                additions.append(
                    f"ALTER TABLE payment_reconciliation_events ADD COLUMN {name} {ddl}"
                )

    if "products" in tables:
        product_columns = columns("products")
        false_default = "FALSE" if bind.dialect.name == "postgresql" else "0"
        for name, ddl in (
            ("description", "TEXT"),
            ("hsn_sac", "VARCHAR(12)"),
            ("item_type", "VARCHAR(16) NOT NULL DEFAULT 'goods'"),
            ("unit", "VARCHAR(24) NOT NULL DEFAULT 'pcs'"),
            ("default_gst_rate", "NUMERIC(5, 2) NOT NULL DEFAULT 18"),
            ("gst_effective_from", "DATE"),
            ("gst_verified", f"BOOLEAN NOT NULL DEFAULT {false_default}"),
            ("gst_change_reason", "TEXT"),
            (
                "gst_updated_by_user_id",
                "INTEGER REFERENCES users(id) ON DELETE SET NULL",
            ),
        ):
            if name not in product_columns:
                additions.append(f"ALTER TABLE products ADD COLUMN {name} {ddl}")

    if "invoices" in tables:
        invoice_columns = columns("invoices")
        true_default = "TRUE" if bind.dialect.name == "postgresql" else "1"
        false_default = "FALSE" if bind.dialect.name == "postgresql" else "0"
        for name, ddl in (
            ("pricing_mode", "VARCHAR(20) NOT NULL DEFAULT 'exclusive'"),
            ("supply_type", "VARCHAR(20) NOT NULL DEFAULT 'unverified'"),
            ("supplier_name", "VARCHAR(160)"),
            ("supplier_gstin", "VARCHAR(15)"),
            ("supplier_address", "TEXT"),
            ("supplier_state", "VARCHAR(80)"),
            ("supplier_state_code", "VARCHAR(2)"),
            ("customer_name", "VARCHAR(160)"),
            ("customer_gstin", "VARCHAR(15)"),
            ("customer_phone", "VARCHAR(24)"),
            ("customer_address", "TEXT"),
            ("customer_state", "VARCHAR(80)"),
            ("customer_state_code", "VARCHAR(2)"),
            ("place_of_supply_state", "VARCHAR(80)"),
            ("place_of_supply_state_code", "VARCHAR(2)"),
            ("discount_amount", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("taxable_amount", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("cgst_amount", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("sgst_amount", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("igst_amount", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("other_charges", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("rounding_adjustment", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("round_to_rupee", f"BOOLEAN NOT NULL DEFAULT {true_default}"),
            ("supply_verified", f"BOOLEAN NOT NULL DEFAULT {false_default}"),
            ("terms", "TEXT"),
        ):
            if name not in invoice_columns:
                additions.append(f"ALTER TABLE invoices ADD COLUMN {name} {ddl}")
        timestamp_type = "TIMESTAMP" if bind.dialect.name == "postgresql" else "DATETIME"
        if "assigned_employee_id" not in invoice_columns:
            additions.append(
                "ALTER TABLE invoices ADD COLUMN assigned_employee_id INTEGER "
                "REFERENCES users(id) ON DELETE SET NULL"
            )
        if "reminder_paused" not in invoice_columns:
            additions.append(
                f"ALTER TABLE invoices ADD COLUMN reminder_paused BOOLEAN NOT NULL DEFAULT {false_default}"
            )
        if "disputed_at" not in invoice_columns:
            additions.append(f"ALTER TABLE invoices ADD COLUMN disputed_at {timestamp_type}")

    if "invoice_reminders" in tables and "stage" not in columns("invoice_reminders"):
        additions.append("ALTER TABLE invoice_reminders ADD COLUMN stage VARCHAR(24)")

    if "accounting_vouchers" in tables:
        voucher_columns = columns("accounting_vouchers")
        if "bank_ledger" not in voucher_columns:
            additions.append("ALTER TABLE accounting_vouchers ADD COLUMN bank_ledger VARCHAR(120)")
        for name, ddl in (
            (
                "source_transaction_id",
                "INTEGER REFERENCES accounting_business_transactions(id) ON DELETE SET NULL",
            ),
            ("entry_draft_id", "INTEGER REFERENCES accounting_entry_drafts(id) ON DELETE SET NULL"),
            ("source_hash", "VARCHAR(64)"),
        ):
            if name not in voucher_columns:
                additions.append(f"ALTER TABLE accounting_vouchers ADD COLUMN {name} {ddl}")

    if "accounting_clients" in tables:
        client_columns = columns("accounting_clients")
        if "business_profile_id" not in client_columns:
            additions.append(
                "ALTER TABLE accounting_clients ADD COLUMN business_profile_id INTEGER "
                "REFERENCES business_profiles(id) ON DELETE SET NULL"
            )
        timestamp_type = "TIMESTAMP" if bind.dialect.name == "postgresql" else "DATETIME"
        false_default = "FALSE" if bind.dialect.name == "postgresql" else "0"
        for name, ddl in (
            ("integration_status", "VARCHAR(24) NOT NULL DEFAULT 'not_linked'"),
            ("integration_enabled_at", timestamp_type),
            ("integration_last_synced_at", timestamp_type),
            ("integration_settings", "JSON NOT NULL DEFAULT '{}'"),
            ("gst_catalogue_access", f"BOOLEAN NOT NULL DEFAULT {false_default}"),
        ):
            if name not in client_columns:
                additions.append(f"ALTER TABLE accounting_clients ADD COLUMN {name} {ddl}")
                if name == "integration_status":
                    backfill_integration_link = True

    if "accounting_enquiries" in tables:
        enquiry_columns = columns("accounting_enquiries")
        bool_default = "TRUE" if bind.dialect.name == "postgresql" else "1"
        for name, ddl in (
            ("annual_turnover", "NUMERIC(14, 2)"),
            ("bank_accounts", "INTEGER"),
            ("payroll_required", f"BOOLEAN NOT NULL DEFAULT {bool_default}"),
            ("inventory_required", f"BOOLEAN NOT NULL DEFAULT {bool_default}"),
            ("financial_year", "VARCHAR(9)"),
            ("benchmark_annual", "NUMERIC(16, 2)"),
            ("customer_user_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL"),
        ):
            if name not in enquiry_columns:
                additions.append(f"ALTER TABLE accounting_enquiries ADD COLUMN {name} {ddl}")

    if "accounting_quotations" in tables:
        quotation_columns = columns("accounting_quotations")
        for name, ddl in (
            ("line_items", "JSON"),
            ("annual_turnover", "NUMERIC(14, 2)"),
            ("benchmark_annual", "NUMERIC(16, 2)"),
            ("subtotal_annual", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("total_annual", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("monthly_equivalent", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("discount_type", "VARCHAR(12) NOT NULL DEFAULT 'none'"),
            ("discount_value", "NUMERIC(12, 2) NOT NULL DEFAULT 0"),
            ("discount_amount", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("discount_note", "TEXT"),
            ("payment_frequency", "VARCHAR(20) NOT NULL DEFAULT 'monthly'"),
            ("validity_days", "INTEGER"),
            ("tax_rate_percent", "NUMERIC(5, 2) NOT NULL DEFAULT 18"),
            ("tax_note", "TEXT"),
            ("approved_at", "TIMESTAMP"),
            ("approved_by_user_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL"),
            ("rejected_at", "TIMESTAMP"),
            ("rejected_by_user_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL"),
            ("rejection_note", "TEXT"),
            ("sent_at", "TIMESTAMP"),
        ):
            if name not in quotation_columns:
                additions.append(f"ALTER TABLE accounting_quotations ADD COLUMN {name} {ddl}")

    if "invoice_items" in tables:
        item_columns = columns("invoice_items")
        for name, ddl in (
            ("name", "VARCHAR(200)"),
            ("hsn_sac", "VARCHAR(12)"),
            ("unit", "VARCHAR(24) NOT NULL DEFAULT 'pcs'"),
            ("item_type", "VARCHAR(16) NOT NULL DEFAULT 'goods'"),
            ("discount_amount", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("taxable_value", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("gst_rate", "NUMERIC(5, 2) NOT NULL DEFAULT 18"),
            ("cgst_amount", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("sgst_amount", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("igst_amount", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("gst_amount", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("final_amount", "NUMERIC(16, 2) NOT NULL DEFAULT 0"),
            ("pricing_mode", "VARCHAR(20) NOT NULL DEFAULT 'exclusive'"),
        ):
            if name not in item_columns:
                additions.append(f"ALTER TABLE invoice_items ADD COLUMN {name} {ddl}")
                backfill_gst = True

    if "accounting_bank_imports" in tables:
        bank_import_columns = columns("accounting_bank_imports")
        for name, ddl in (
            ("connection_id", "INTEGER REFERENCES payment_connections(id) ON DELETE SET NULL"),
            ("account_label", "VARCHAR(160)"),
            ("parsing_format", "VARCHAR(16)"),
            ("source_sha256", "VARCHAR(64)"),
            ("uncertain_count", "INTEGER NOT NULL DEFAULT 0"),
            ("duplicate_count", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in bank_import_columns:
                additions.append(f"ALTER TABLE accounting_bank_imports ADD COLUMN {name} {ddl}")

    if "accounting_bank_transactions" in tables:
        bank_txn_columns = columns("accounting_bank_transactions")
        bank_false_default = "FALSE" if bind.dialect.name == "postgresql" else "0"
        for name, ddl in (
            ("direction", "VARCHAR(16) NOT NULL DEFAULT 'debit'"),
            ("raw", "JSON NOT NULL DEFAULT '{}'"),
            ("confidence", "INTEGER NOT NULL DEFAULT 100"),
            ("issues", "JSON NOT NULL DEFAULT '[]'"),
            ("corrected", f"BOOLEAN NOT NULL DEFAULT {bank_false_default}"),
            ("source_hash", "VARCHAR(64)"),
            (
                "duplicate_of_id",
                "INTEGER REFERENCES accounting_bank_transactions(id) ON DELETE SET NULL",
            ),
        ):
            if name not in bank_txn_columns:
                additions.append(
                    f"ALTER TABLE accounting_bank_transactions ADD COLUMN {name} {ddl}"
                )

    has_gst_invoice_columns = "invoices" in tables and {
        "supply_type",
        "supply_verified",
        "cgst_amount",
        "sgst_amount",
        "igst_amount",
    } <= columns("invoices")
    has_payment_columns = "payments" in tables

    if not additions and not has_gst_invoice_columns and not has_payment_columns:
        return
    with bind.begin() as connection:
        for statement in additions:
            connection.execute(text(statement))
        if bind.dialect.name in ("sqlite", "postgresql"):
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_users_owner_id ON users (owner_id)")
            )
            if "payments" in tables:
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_payments_refund_of_payment_id "
                        "ON payments (refund_of_payment_id)"
                    )
                )
            if "customers" in tables:
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_customers_user_credit_hold "
                        "ON customers (user_id, credit_hold)"
                    )
                )
            if "expenses" in tables:
                for index_name, columns in (
                    ("ix_expenses_user_supplier", "user_id, supplier_id"),
                    ("ix_expenses_user_due_date", "user_id, due_date"),
                    ("ix_expenses_user_payment_status", "user_id, payment_status"),
                ):
                    connection.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS {index_name} "
                            f"ON expenses ({columns})"
                        )
                    )
            if "payment_transactions" in tables:
                for index_name, columns in (
                    ("ix_payment_transactions_bank_account_id", "bank_account_id"),
                    ("ix_payment_transactions_statement_import_id", "statement_import_id"),
                    ("ix_payment_transactions_account_dedupe", "bank_account_id, dedupe_hash"),
                ):
                    connection.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS {index_name} "
                            f"ON payment_transactions ({columns})"
                        )
                    )
            if "payment_reconciliation_events" in tables:
                for index_name, column in (
                    ("ix_payment_reconciliation_events_expense_id", "expense_id"),
                    (
                        "ix_payment_reconciliation_events_supplier_payment_id",
                        "supplier_payment_id",
                    ),
                ):
                    connection.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS {index_name} "
                            f"ON payment_reconciliation_events ({column})"
                        )
                    )
            if "payment_events" in tables:
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_payment_events_processed "
                        "ON payment_events (provider, processed_at)"
                    )
                )
            if "accounting_clients" in tables:
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_accounting_clients_integration "
                        "ON accounting_clients (integration_status)"
                    )
                )
            if "accounting_vouchers" in tables:
                for index_name, column in (
                    ("ix_accounting_vouchers_source_transaction_id", "source_transaction_id"),
                    ("ix_accounting_vouchers_entry_draft_id", "entry_draft_id"),
                ):
                    connection.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS {index_name} "
                            f"ON accounting_vouchers ({column})"
                        )
                    )
            if "accounting_bank_imports" in tables:
                for index_name, column in (
                    ("ix_accounting_bank_imports_connection_id", "connection_id"),
                    ("ix_accounting_bank_imports_source_sha256", "source_sha256"),
                ):
                    connection.execute(
                        text(
                            f"CREATE INDEX IF NOT EXISTS {index_name} "
                            f"ON accounting_bank_imports ({column})"
                        )
                    )
            if "accounting_bank_transactions" in tables:
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_accounting_bank_transactions_source_hash "
                        "ON accounting_bank_transactions (source_hash)"
                    )
                )
            connection.execute(
                text(
                    "UPDATE payments SET reconciliation_status = 'matched' "
                    "WHERE invoice_id IS NOT NULL AND reconciliation_status = 'unmatched'"
                )
            )
        if backfill_integration_link:
            # Business links that already existed before this column was added stay
            # linked. No transaction, draft or voucher is created by the backfill.
            connection.execute(
                text(
                    "UPDATE accounting_clients SET integration_status = 'linked' "
                    "WHERE business_profile_id IS NOT NULL"
                )
            )
        if backfill_gst:
            statements = [
                "UPDATE invoices SET taxable_amount = subtotal_amount "
                "WHERE taxable_amount = 0 AND subtotal_amount > 0",
                "UPDATE invoices SET rounding_adjustment = "
                "total_amount - (taxable_amount + tax_amount + other_charges) "
                "WHERE total_amount > 0",
                "UPDATE invoice_items SET taxable_value = line_total WHERE taxable_value = 0",
                "UPDATE invoice_items SET gst_rate = COALESCE(("
                "SELECT ROUND(i.tax_amount * 100.0 / i.subtotal_amount, 2) FROM invoices i "
                "WHERE i.id = invoice_items.invoice_id AND i.subtotal_amount > 0), 0) "
                "WHERE gst_amount = 0",
                "UPDATE invoice_items SET gst_amount = ROUND(taxable_value * gst_rate / 100, 2), "
                "final_amount = taxable_value + ROUND(taxable_value * gst_rate / 100, 2) "
                "WHERE gst_amount = 0",
            ]
            for statement in statements:
                connection.execute(text(statement))
        if has_gst_invoice_columns:
            # Legacy invoices have no verified supplier / place-of-supply state, so the
            # CGST-SGST vs IGST split cannot be inferred. Keep the recorded tax total
            # intact but never fabricate a component split.
            false_literal = "FALSE" if bind.dialect.name == "postgresql" else "0"
            connection.execute(
                text(
                    "UPDATE invoices SET supply_type = 'unverified', "
                    f"supply_verified = {false_literal}, cgst_amount = 0, "
                    "sgst_amount = 0, igst_amount = 0 "
                    "WHERE (supplier_state_code IS NULL OR supplier_state_code = '' "
                    "OR place_of_supply_state_code IS NULL OR place_of_supply_state_code = '') "
                    "AND supply_type <> 'unverified'"
                )
            )
            connection.execute(
                text(
                    "UPDATE invoices SET cgst_amount = 0, sgst_amount = 0, igst_amount = 0 "
                    "WHERE supply_type = 'unverified' "
                    "AND (cgst_amount <> 0 OR sgst_amount <> 0 OR igst_amount <> 0)"
                )
            )
            if "invoice_items" in tables:
                connection.execute(
                    text(
                        "UPDATE invoice_items SET cgst_amount = 0, sgst_amount = 0, "
                        "igst_amount = 0 WHERE invoice_id IN "
                        "(SELECT id FROM invoices WHERE supply_type = 'unverified') "
                        "AND (cgst_amount <> 0 OR sgst_amount <> 0 OR igst_amount <> 0)"
                    )
                )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
