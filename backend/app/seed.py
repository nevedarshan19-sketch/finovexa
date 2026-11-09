from __future__ import annotations

import logging
import random
import statistics
import zlib
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    AccountingBankImport,
    AccountingBankTransaction,
    AccountingClient,
    AccountingDocumentRequest,
    AccountingEnquiry,
    AccountingInvoice,
    AccountingInvoicePayment,
    AccountingMessage,
    AccountingNotification,
    AccountingQuotation,
    AccountingStockItem,
    AccountingHistoricalLedger,
    AccountingHistoricalVoucher,
    AccountingHistoricalVoucherLine,
    AccountingOpeningBalance,
    AccountingOpeningBalanceLine,
    AccountingTallyMigration,
    AccountingTask,
    AccountingVoucher,
    AIInsight,
    ApprovalRequest,
    AuditEvent,
    BrokerOrder,
    BusinessMembership,
    BusinessProfile,
    CashForecast,
    ChatMessage,
    Customer,
    EmployeeEntry,
    Expense,
    FinancialObligation,
    IntegrationConfig,
    InventoryItem,
    Invoice,
    InvoiceItem,
    InvoiceReminder,
    MarketCandle,
    MarketInstrument,
    MarketQuote,
    NewsArticle,
    Payment,
    PaymentEvent,
    PortfolioHolding,
    Product,
    ResearchSignal,
    User,
    utcnow,
)
from .security import hash_password, verify_password
from .services.accounting_math import (
    financial_year_for,
    split_gst,
    voucher_dedupe_hash,
)
from .services.agents import generate_business_insights
from .services.approvals import create_approval, payload_hash
from .services.audit import log_audit
from .services.business_context import ensure_membership, primary_business
from .services.finance import invoice_aging_summary, q2
from .services.gst import ensure_default_gst_rates
from .services.instruments import nifty50_demo_specs
from .services.payments import record_payment
from .services.pricing import DEFAULT_SETTINGS, DEFAULT_TERMS, ensure_pricing_seed
from .services.recovery import reminder_draft
from .tenancy import tenancy_bypass

DEMO_BUSINESS = "DN Ventures Pvt. Ltd"
DEMO_OWNER = "Darshan Yogesh Neve"

logger = logging.getLogger("finovexa.seed")

INSTRUMENTS = [
    {
        "symbol": "XAUUSD",
        "name": "Gold spot",
        "asset_class": "metal",
        "exchange": "Global OTC",
        "currency": "USD",
        "unit": "troy ounce",
        "external_key": None,
        "sector": None,
        "base": Decimal("3150.00"),
        "drift": Decimal("0.0009"),
        "volatility": 0.007,
    },
    {
        "symbol": "XAGUSD",
        "name": "Silver spot",
        "asset_class": "metal",
        "exchange": "Global OTC",
        "currency": "USD",
        "unit": "troy ounce",
        "external_key": None,
        "sector": None,
        "base": Decimal("38.40"),
        "drift": Decimal("0.0011"),
        "volatility": 0.014,
    },
    {
        "symbol": "NIFTY50",
        "name": "Nifty 50",
        "asset_class": "index",
        "exchange": "NSE",
        "currency": "INR",
        "unit": "index points",
        "external_key": "NSE_INDEX|Nifty 50",
        "sector": None,
        "base": Decimal("26800.00"),
        "drift": Decimal("0.0005"),
        "volatility": 0.006,
    },
    {
        "symbol": "SENSEX",
        "name": "BSE Sensex",
        "asset_class": "index",
        "exchange": "BSE",
        "currency": "INR",
        "unit": "index points",
        "external_key": "BSE_INDEX|SENSEX",
        "sector": None,
        "base": Decimal("87900.00"),
        "drift": Decimal("0.0005"),
        "volatility": 0.006,
    },
    {
        "symbol": "RELIANCE",
        "name": "Reliance Industries",
        "asset_class": "equity",
        "exchange": "NSE",
        "currency": "INR",
        "unit": "share",
        "external_key": "NSE_EQ|INE002A01018",
        "sector": "Energy",
        "base": Decimal("1485.00"),
        "drift": Decimal("0.0010"),
        "volatility": 0.011,
    },
    {
        "symbol": "TCS",
        "name": "Tata Consultancy Services",
        "asset_class": "equity",
        "exchange": "NSE",
        "currency": "INR",
        "unit": "share",
        "external_key": "NSE_EQ|INE467B01029",
        "sector": "Information Technology",
        "base": Decimal("4120.00"),
        "drift": Decimal("0.0008"),
        "volatility": 0.009,
    },
    {
        "symbol": "HDFCBANK",
        "name": "HDFC Bank",
        "asset_class": "equity",
        "exchange": "NSE",
        "currency": "INR",
        "unit": "share",
        "external_key": "NSE_EQ|INE040A01034",
        "sector": "Financials",
        "base": Decimal("1760.00"),
        "drift": Decimal("0.0006"),
        "volatility": 0.010,
    },
    {
        "symbol": "INFY",
        "name": "Infosys",
        "asset_class": "equity",
        "exchange": "NSE",
        "currency": "INR",
        "unit": "share",
        "external_key": "NSE_EQ|INE009A01021",
        "sector": "Information Technology",
        "base": Decimal("1890.00"),
        "drift": Decimal("0.0007"),
        "volatility": 0.010,
    },
]

_EXISTING_SYMBOLS = {spec["symbol"] for spec in INSTRUMENTS}
ALL_INSTRUMENTS = INSTRUMENTS + [
    spec for spec in nifty50_demo_specs() if spec["symbol"] not in _EXISTING_SYMBOLS
]

DEMO_NEWS = [
    {
        "slug": "gold-central-bank-demand",
        "title": "Gold holds near elevated levels as central-bank demand persists",
        "source": "FINOVEXA Demo Newsroom",
        "hours_ago": 3,
        "summary": "Sample market note: spot gold is trading near recent highs while official-sector buying and a softer dollar support demand. This is demo content for product evaluation.",
        "implications": "A stronger gold price can raise the value of existing holdings but also makes new entry more sensitive to timing and currency moves.",
        "risks": "Prices can reverse quickly if real yields rise or the dollar strengthens. Demo content is not investment advice.",
        "instruments": ["XAUUSD"],
    },
    {
        "slug": "silver-industrial-demand",
        "title": "Silver tracks industrial demand as supply deficit narrative continues",
        "source": "FINOVEXA Demo Newsroom",
        "hours_ago": 7,
        "summary": "Sample market note: silver has outperformed gold over the sample period, helped by industrial demand assumptions. This is seeded demo data.",
        "implications": "Silver's industrial exposure can amplify moves in both directions compared with gold.",
        "risks": "Higher volatility and demand cyclicality. Demo data must not be used for live decisions.",
        "instruments": ["XAGUSD"],
    },
    {
        "slug": "nifty-financials-it",
        "title": "Nifty 50 sample session ends higher led by financials and IT",
        "source": "FINOVEXA Demo Newsroom",
        "hours_ago": 11,
        "summary": "Demo wrap: the sample index advanced in a broad-based session, with banking and technology constituents contributing most of the gain.",
        "implications": "Index-level moves can mask concentration in a few large constituents.",
        "risks": "Headline index performance does not indicate future returns. Demo article.",
        "instruments": ["NIFTY50", "HDFCBANK", "TCS"],
    },
    {
        "slug": "rbi-policy-rate-sensitive",
        "title": "Rate-sensitive shares in focus ahead of policy expectations",
        "source": "FINOVEXA Demo Newsroom",
        "hours_ago": 16,
        "summary": "Demo note: market participants are watching policy commentary for signals on borrowing costs. No official decision has been reported in this sample article.",
        "implications": "Banks and capital-intensive businesses can be sensitive to rate expectations.",
        "risks": "Expectations may change before any policy decision. Demo content only.",
        "instruments": ["NIFTY50", "HDFCBANK"],
    },
    {
        "slug": "reliance-capacity-expansion",
        "title": "Reliance sample announcement points to new capacity plan",
        "source": "FINOVEXA Demo Newsroom",
        "hours_ago": 21,
        "summary": "Demo company note: the sample announcement describes a multi-year capacity expansion with no financial details disclosed in the excerpt.",
        "implications": "Capacity plans can affect medium-term growth expectations but require capital and execution.",
        "risks": "No valuation or execution assessment is available in this demo article.",
        "instruments": ["RELIANCE"],
    },
    {
        "slug": "tcs-transformation-mandate",
        "title": "TCS sample update cites multi-year transformation mandate",
        "source": "FINOVEXA Demo Newsroom",
        "hours_ago": 26,
        "summary": "Demo company note: a sample services mandate is described without contract value or margin information.",
        "implications": "Order-book news can support revenue visibility, but margins and timing matter.",
        "risks": "Details are incomplete and this is seeded demo content, not a company filing.",
        "instruments": ["TCS"],
    },
    {
        "slug": "hdfc-deposit-growth",
        "title": "HDFC Bank sample note shows steady deposit growth",
        "source": "FINOVEXA Demo Newsroom",
        "hours_ago": 31,
        "summary": "Demo banking note: deposit growth is described as steady in a sample update, with no full financial statements attached.",
        "implications": "Deposit trends influence funding costs and credit growth capacity.",
        "risks": "A single sample metric is not a complete credit-quality assessment.",
        "instruments": ["HDFCBANK"],
    },
    {
        "slug": "global-dollar-inflation",
        "title": "Global markets sample: dollar softens ahead of inflation data",
        "source": "FINOVEXA Demo Newsroom",
        "hours_ago": 36,
        "summary": "Demo macro note: the dollar eased in the sample period while investors awaited inflation prints. This article is illustrative.",
        "implications": "Currency moves affect commodity prices quoted in dollars and import costs.",
        "risks": "Macro data can surprise in either direction. Demo article only.",
        "instruments": ["XAUUSD", "NIFTY50"],
    },
]


def _business_days(start: date, end: date) -> list[date]:
    days = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def ensure_global_market_data(db: Session) -> None:
    instruments: dict[str, MarketInstrument] = {}
    for spec in ALL_INSTRUMENTS:
        instrument = (
            db.query(MarketInstrument).filter(MarketInstrument.symbol == spec["symbol"]).one_or_none()
        )
        if instrument is None:
            instrument = MarketInstrument(
                symbol=spec["symbol"],
                name=spec["name"],
                asset_class=spec["asset_class"],
                exchange=spec["exchange"],
                currency=spec["currency"],
                unit=spec["unit"],
                external_key=spec["external_key"],
                sector=spec["sector"],
            )
            db.add(instrument)
            db.flush()
        instruments[spec["symbol"]] = instrument
    db.commit()

    for spec in ALL_INSTRUMENTS:
        instrument = instruments[spec["symbol"]]
        has_candles = db.query(MarketCandle).filter(MarketCandle.instrument_id == instrument.id).count()
        if has_candles:
            continue
        rng = random.Random(zlib.crc32(spec["symbol"].encode("utf-8")) + 2026)
        days = _business_days(date.today() - timedelta(days=150), date.today())
        start_price = float(spec["base"]) * (1 - float(spec["drift"]) * 80)
        price = start_price
        for day in days:
            open_price = price
            shock = rng.gauss(float(spec["drift"]), spec["volatility"])
            price = max(1.0, price * (1 + shock))
            high = max(open_price, price) * (1 + abs(rng.gauss(0, spec["volatility"] / 3)))
            low = min(open_price, price) * (1 - abs(rng.gauss(0, spec["volatility"] / 3)))
            volume = rng.randint(200_000, 8_000_000) if spec["asset_class"] != "metal" else None
            db.add(
                MarketCandle(
                    instrument_id=instrument.id,
                    trading_date=day,
                    open=Decimal(str(round(open_price, 2))),
                    high=Decimal(str(round(high, 2))),
                    low=Decimal(str(round(low, 2))),
                    close=Decimal(str(round(price, 2))),
                    volume=volume,
                    data_mode="demo",
                )
            )
    db.commit()

    candles_by_symbol: dict[str, list[MarketCandle]] = {}
    for spec in ALL_INSTRUMENTS:
        instrument = instruments[spec["symbol"]]
        candles = (
            db.query(MarketCandle)
            .filter(MarketCandle.instrument_id == instrument.id)
            .order_by(MarketCandle.trading_date.asc())
            .all()
        )
        candles_by_symbol[spec["symbol"]] = candles

        latest_quote = (
            db.query(MarketQuote)
            .filter(MarketQuote.instrument_id == instrument.id)
            .order_by(MarketQuote.id.desc())
            .first()
        )
        if latest_quote is None and len(candles) >= 2:
            last, previous = candles[-1], candles[-2]
            price = last.close
            change = ((price - previous.close) / previous.close * 100) if previous.close else Decimal("0")
            db.add(
                MarketQuote(
                    instrument_id=instrument.id,
                    price=price,
                    previous_close=previous.close,
                    change_pct=change,
                    as_of=(utcnow() - timedelta(minutes=12)).replace(microsecond=0),
                    source="FINOVEXA demo feed (seeded)",
                    data_mode="demo",
                    session_status="demo",
                )
            )
    db.commit()

    if db.query(ResearchSignal).count() == 0:
        _seed_research_signals(db, instruments, candles_by_symbol)
    if db.query(NewsArticle).count() == 0:
        _seed_news(db)


def _seed_news(db: Session) -> None:
    now = utcnow()
    for item in DEMO_NEWS:
        db.add(
            NewsArticle(
                external_id=f"demo-{item['slug']}",
                title=item["title"],
                source=item["source"],
                url=f"https://example.com/finovexa-demo/{item['slug']}",
                published_at=(now - timedelta(hours=item["hours_ago"])).replace(microsecond=0),
                summary=item["summary"],
                implications=item["implications"],
                risks=item["risks"],
                instruments=item["instruments"],
                data_mode="demo",
            )
        )
    db.commit()


def _seed_research_signals(
    db: Session, instruments: dict[str, MarketInstrument], candles: dict[str, list[MarketCandle]]
) -> None:
    for symbol in ("RELIANCE", "TCS", "HDFCBANK", "INFY"):
        instrument = instruments[symbol]
        rows = candles.get(symbol, [])
        if len(rows) < 30:
            continue
        closes = [float(row.close) for row in rows]
        momentum_30 = closes[-1] / closes[-30] - 1
        momentum_90 = closes[-1] / closes[-min(90, len(closes))] - 1
        returns = [
            (closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))
        ]
        volatility = statistics.pstdev(returns[-30:]) if len(returns) >= 30 else 0.01
        raw_score = 50 + momentum_30 * 180 + momentum_90 * 55 - volatility * 900
        score = int(max(20, min(85, round(raw_score))))
        if score >= 62:
            signal = "positive"
        elif score >= 45:
            signal = "neutral"
        else:
            signal = "caution"
        rationale = (
            f"Demo price history shows {momentum_30 * 100:+.1f}% over 30 sessions and "
            f"{momentum_90 * 100:+.1f}% over the available 90-session window. "
            f"Realised 30-session volatility is {volatility * 100:.1f}%."
        )
        risks = (
            "Model input is demo price data only: no earnings estimates, balance-sheet analysis, "
            "analyst consensus, news sentiment or liquidity assessment is included. "
            "Momentum can reverse and data may be stale. This is not investment advice or a suitability assessment."
        )
        methodology = (
            "Rules-based score: 50 base, +30-day momentum scaled 180, +90-session trend scaled 55, "
            "minus recent realised volatility scaled 900, clipped to 20–85. "
            "The score produces a model label (positive / neutral / caution). No third-party rating is used."
        )
        db.add(
            ResearchSignal(
                instrument_id=instrument.id,
                model_signal=signal,
                score=score,
                rationale=rationale,
                risks=risks,
                methodology=methodology,
                data_quality="demo_history",
                is_model_generated=True,
                generated_at=(utcnow() - timedelta(hours=2)).replace(microsecond=0),
            )
        )
    db.commit()


def create_user(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str,
    business_name: str,
    currency: str = "INR",
    is_demo: bool = False,
    opening_cash_balance: Decimal = Decimal("0.00"),
    min_cash_reserve: Decimal = Decimal("0.00"),
) -> User:
    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        full_name=full_name,
        is_demo=is_demo,
    )
    db.add(user)
    db.flush()
    profile = BusinessProfile(
        user_id=user.id,
        owner_id=user.id,
        business_name=business_name,
        currency=currency,
        timezone="Asia/Kolkata",
        reporting_period="monthly",
        min_cash_reserve=q2(min_cash_reserve),
        opening_cash_balance=q2(opening_cash_balance),
        opening_balance_date=date.today() - timedelta(days=180),
        risk_tolerance="balanced",
        research_interests=["RELIANCE", "TCS", "HDFCBANK"],
        reminder_tone="professional",
    )
    db.add(profile)
    db.flush()
    return user


def _initial_password_problem(password: str) -> str | None:
    if len(password) < 12:
        return "must be at least 12 characters"
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "must include a letter and a number"
    return None


_EMAIL_ADAPTER = TypeAdapter(EmailStr)


def _initial_email(value: str) -> str | None:
    """Normalize an INITIAL_* email with the same validation the login API uses."""
    try:
        return str(_EMAIL_ADAPTER.validate_python(value.strip())).lower()
    except ValidationError:
        return None


def _provision_account(
    db: Session,
    *,
    role: str,
    email: str,
    password: str,
    full_name: str,
    business_name: str = "",
) -> str:
    """Create one initial account. Existing accounts are never changed."""
    email = email.strip().lower()
    existing = db.query(User).filter(User.email == email).one_or_none()
    if existing is not None:
        if existing.role != role:
            logger.error(
                "Initial %s account %s not created: the email belongs to an existing %s account.",
                role,
                email,
                existing.role,
            )
            return "conflict"
        logger.info("Initial %s account %s already exists; left unchanged.", role, email)
        return "exists"

    if role == "owner":
        user = create_user(
            db,
            email=email,
            password=password,
            full_name=full_name,
            business_name=business_name.strip() or "My Business",
            is_demo=False,
        )
    else:
        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role=role,
            is_demo=False,
            is_active=True,
        )
        db.add(user)
    db.flush()
    log_audit(
        db,
        user_id=user.id,
        actor="system",
        action="auth.initial_account_provisioned",
        entity_type="user",
        entity_id=user.id,
        detail={"role": role, "email": email},
    )
    db.commit()
    logger.info("Provisioned initial %s account %s", role, email)
    return "created"


def provision_initial_accounts(db: Session) -> dict[str, str]:
    """Create the first production accounts from environment values.

    Runs on every start, is idempotent and never inserts business records.
    """
    specs = (
        (
            "owner",
            settings.INITIAL_OWNER_NAME or "Owner",
            settings.INITIAL_OWNER_EMAIL,
            settings.INITIAL_OWNER_PASSWORD,
        ),
        (
            "senior_accountant",
            settings.INITIAL_SENIOR_ACCOUNTANT_NAME or "Senior Accountant",
            settings.INITIAL_SENIOR_ACCOUNTANT_EMAIL,
            settings.INITIAL_SENIOR_ACCOUNTANT_PASSWORD,
        ),
        (
            "junior_accountant",
            settings.INITIAL_JUNIOR_ACCOUNTANT_NAME or "Junior Accountant",
            settings.INITIAL_JUNIOR_ACCOUNTANT_EMAIL,
            settings.INITIAL_JUNIOR_ACCOUNTANT_PASSWORD,
        ),
    )
    statuses: dict[str, str] = {}
    for role, full_name, email, password in specs:
        if not email.strip():
            statuses[role] = "not_configured"
            continue
        normalized = _initial_email(email)
        if normalized is None:
            statuses[role] = "invalid_email"
            logger.error("Initial %s account skipped: INITIAL_* email is not valid.", role)
            continue
        problem = _initial_password_problem(password)
        if problem:
            statuses[role] = "invalid_password"
            logger.error("Initial %s account skipped: the password %s.", role, problem)
            continue
        statuses[role] = _provision_account(
            db,
            role=role,
            email=normalized,
            password=password,
            full_name=full_name.strip() or role.replace("_", " ").title(),
            business_name=settings.INITIAL_BUSINESS_NAME if role == "owner" else "",
        )
    return statuses


def seed_demo_employee(db: Session, owner: User) -> User:
    employee = (
        db.query(User)
        .filter(User.email == settings.DEMO_EMPLOYEE_EMAIL.lower())
        .one_or_none()
    )
    if employee is None:
        employee = User(
            email=settings.DEMO_EMPLOYEE_EMAIL.lower(),
            password_hash=hash_password(settings.DEMO_EMPLOYEE_PASSWORD),
            full_name="Riya Sharma",
            role="employee",
            owner_id=owner.id,
            is_demo=True,
        )
        db.add(employee)
        db.flush()
        business = primary_business(db, owner.id)
        if business is not None:
            ensure_membership(db, business.id, employee.id, "employee")
        db.commit()
        db.refresh(employee)
        return employee
    changed = False
    if employee.role != "employee":
        employee.role = "employee"
        changed = True
    if employee.owner_id != owner.id:
        employee.owner_id = owner.id
        changed = True
    if not employee.is_active:
        employee.is_active = True
        changed = True
    if changed:
        db.commit()
    business = primary_business(db, owner.id)
    if business is not None:
        membership = (
            db.query(BusinessMembership)
            .filter(
                BusinessMembership.business_id == business.id,
                BusinessMembership.user_id == employee.id,
            )
            .one_or_none()
        )
        if membership is None:
            ensure_membership(db, business.id, employee.id, "employee")
            db.commit()
    return employee


def seed_developer(db: Session) -> User | None:
    email = settings.DEVELOPER_EMAIL.strip().lower()
    password = settings.DEVELOPER_PASSWORD
    if not email or not password:
        return None
    if len(password) < 12 or not any(c.isalpha() for c in password) or not any(
        c.isdigit() for c in password
    ):
        logger.error(
            "Developer account not seeded: DEVELOPER_PASSWORD must be at least 12 characters "
            "and include a letter and a number."
        )
        return None

    developer = db.query(User).filter(User.email == email).one_or_none()
    if developer is not None and developer.role != "developer":
        logger.error(
            "Developer account not seeded: %s already belongs to an owner or employee.", email
        )
        return None

    created = developer is None
    password_synced = False
    if developer is None:
        developer = User(
            email=email,
            password_hash=hash_password(password),
            full_name=settings.DEVELOPER_NAME.strip() or "Platform Developer",
            role="developer",
            is_demo=False,
            is_active=True,
        )
        db.add(developer)
        db.flush()
    else:
        if not developer.is_active:
            developer.is_active = True
        if developer.full_name != settings.DEVELOPER_NAME:
            developer.full_name = settings.DEVELOPER_NAME
        if not verify_password(password, developer.password_hash):
            developer.password_hash = hash_password(password)
            password_synced = True
    if created or password_synced:
        log_audit(
            db,
            user_id=developer.id,
            actor="system",
            action="developer.account_seeded",
            entity_type="user",
            entity_id=developer.id,
            detail={
                "email": email,
                "source": "environment",
                "event": "created" if created else "password_synced",
            },
        )
    db.commit()
    db.refresh(developer)
    return developer


def clear_user_business_data(db: Session, user: User) -> None:
    with tenancy_bypass():
        _clear_user_business_data(db, user)


def _clear_user_business_data(db: Session, user: User) -> None:
    invoice_ids = [row[0] for row in db.query(Invoice.id).filter(Invoice.user_id == user.id).all()]
    db.query(PortfolioHolding).filter(PortfolioHolding.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(EmployeeEntry).filter(EmployeeEntry.owner_id == user.id).delete(
        synchronize_session=False
    )
    db.query(BrokerOrder).filter(BrokerOrder.user_id == user.id).delete(synchronize_session=False)
    if invoice_ids:
        db.query(InvoiceReminder).filter(InvoiceReminder.invoice_id.in_(invoice_ids)).delete(
            synchronize_session=False
        )
    db.query(ApprovalRequest).filter(ApprovalRequest.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(Payment).filter(Payment.user_id == user.id).delete(synchronize_session=False)
    db.query(Invoice).filter(Invoice.user_id == user.id).delete(synchronize_session=False)
    db.query(Expense).filter(Expense.user_id == user.id).delete(synchronize_session=False)
    db.query(FinancialObligation).filter(FinancialObligation.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(CashForecast).filter(CashForecast.user_id == user.id).delete(synchronize_session=False)
    db.query(AIInsight).filter(AIInsight.user_id == user.id).delete(synchronize_session=False)
    db.query(ChatMessage).filter(ChatMessage.user_id == user.id).delete(synchronize_session=False)
    db.query(IntegrationConfig).filter(IntegrationConfig.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(AuditEvent).filter(AuditEvent.user_id == user.id).delete(synchronize_session=False)
    db.query(Product).filter(Product.user_id == user.id).delete(synchronize_session=False)
    db.query(Customer).filter(Customer.user_id == user.id).delete(synchronize_session=False)
    db.query(PaymentEvent).delete(synchronize_session=False)
    db.commit()


def _make_invoice(
    db: Session,
    *,
    user: User,
    customer: Customer,
    number: str,
    issue_days_ago: int,
    terms_days: int,
    items: list[tuple[Product, int]],
    payment_fraction: Decimal = Decimal("0"),
    method: str = "bank",
    payment_delay_days: int = 20,
    provider: str = "manual",
) -> Invoice:
    today = date.today()
    issue_date = today - timedelta(days=issue_days_ago)
    due_date = issue_date + timedelta(days=terms_days)
    profile = user.businesses[0]
    supplier_state = profile.state or "Maharashtra"
    supplier_code = profile.state_code or "27"
    customer_state = customer.state or supplier_state
    customer_code = customer.state_code or supplier_code
    supply_type = "intra_state" if supplier_code == customer_code else "inter_state"
    invoice = Invoice(
        user_id=user.id,
        customer_id=customer.id,
        number=number,
        issue_date=issue_date,
        due_date=due_date,
        currency=user.profile.currency,
        status="issued",
        pricing_mode="exclusive",
        supply_type=supply_type,
        supplier_name=profile.business_name,
        supplier_gstin=profile.gstin,
        supplier_address=", ".join(
            part for part in (profile.address_line1, profile.city, supplier_state) if part
        )
        or None,
        supplier_state=supplier_state,
        supplier_state_code=supplier_code,
        customer_name=customer.company or customer.name,
        customer_gstin=customer.gstin,
        customer_address=", ".join(
            part
            for part in (
                customer.billing_address_line1,
                customer.city,
                customer_state,
                customer.postal_code,
            )
            if part
        )
        or None,
        customer_state=customer_state,
        customer_state_code=customer_code,
        place_of_supply_state=customer_state,
        place_of_supply_state_code=customer_code,
        supply_verified=True,
        round_to_rupee=False,
        terms=profile.invoice_terms,
        notes="GST charged at the rate shown on each line. Demo record.",
    )
    db.add(invoice)
    db.flush()
    subtotal = Decimal("0.00")
    tax_total = Decimal("0.00")
    cgst_total = Decimal("0.00")
    sgst_total = Decimal("0.00")
    igst_total = Decimal("0.00")
    for product, quantity in items:
        line_total = q2(product.unit_price * quantity)
        subtotal = q2(subtotal + line_total)
        gst_rate = product.default_gst_rate or Decimal("18.00")
        gst = q2(line_total * gst_rate / Decimal("100"))
        if supply_type == "intra_state":
            cgst = q2(gst / 2)
            sgst = q2(gst - cgst)
            igst = Decimal("0.00")
        else:
            cgst = sgst = Decimal("0.00")
            igst = gst
        tax_total = q2(tax_total + gst)
        cgst_total = q2(cgst_total + cgst)
        sgst_total = q2(sgst_total + sgst)
        igst_total = q2(igst_total + igst)
        db.add(
            InvoiceItem(
                invoice_id=invoice.id,
                product_id=product.id,
                name=product.name,
                description=product.name,
                hsn_sac=product.hsn_sac,
                unit=product.unit,
                item_type=product.item_type,
                quantity=Decimal(quantity),
                unit_price=product.unit_price,
                discount_amount=Decimal("0.00"),
                line_total=line_total,
                taxable_value=line_total,
                gst_rate=gst_rate,
                cgst_amount=cgst,
                sgst_amount=sgst,
                igst_amount=igst,
                gst_amount=gst,
                final_amount=q2(line_total + gst),
                pricing_mode="exclusive",
            )
        )
    invoice.subtotal_amount = subtotal
    invoice.discount_amount = Decimal("0.00")
    invoice.taxable_amount = subtotal
    invoice.tax_amount = tax_total
    invoice.cgst_amount = cgst_total
    invoice.sgst_amount = sgst_total
    invoice.igst_amount = igst_total
    invoice.total_amount = q2(subtotal + tax_total)
    db.flush()
    log_audit(
        db,
        user_id=user.id,
        actor=user.email,
        action="invoice.issued",
        entity_type="invoice",
        entity_id=invoice.id,
        detail={"number": number, "total": str(invoice.total_amount), "customer": customer.name},
    )
    if payment_fraction > 0:
        amount = q2(invoice.total_amount * payment_fraction)
        paid_on = issue_date + timedelta(days=min(payment_delay_days, max(1, issue_days_ago - 1)))
        record_payment(
            db,
            user=user,
            invoice=invoice,
            amount=amount,
            method=method,
            provider=provider,
            provider_ref=f"DEMO-{number}-{provider.upper()}" if provider != "manual" else None,
            received_at=datetime.combine(paid_on, time(11, 30)),
            note=f"Demo payment for {number}",
            commit=True,
        )
    db.commit()
    return invoice


def _seed_expenses(db: Session, user: User) -> None:
    rng = random.Random(31)
    schedules = [
        ("Logistics", "SwiftMove Logistics", 12, 8_000, 18_000, 5),
        ("Marketing", "BrightReach Media", 28, 22_000, 45_000, 2),
        ("Software", "CloudSuite India", 30, 18_900, 18_900, 7),
        ("Utilities", "Metro Utilities", 30, 14_000, 19_000, 3),
        ("Office Supplies", "OfficeMart", 16, 4_000, 9_000, 6),
        ("Professional Fees", "Rao & Associates", 65, 24_000, 34_000, 20),
        ("Travel", "TravelDesk", 35, 18_000, 30_000, 12),
    ]
    today = date.today()
    for category, vendor, interval, low, high, first_offset in schedules:
        offset = first_offset
        while offset <= 90:
            amount = Decimal(rng.randint(low, high))
            db.add(
                Expense(
                    user_id=user.id,
                    category=category,
                    vendor=vendor,
                    amount=amount,
                    incurred_on=today - timedelta(days=offset),
                    note="Demo operating expense",
                )
            )
            offset += interval
    db.add(
        Expense(
            user_id=user.id,
            category="Equipment",
            vendor="ErgoFit Equipment",
            amount=Decimal("120000"),
            incurred_on=today - timedelta(days=8),
            note="Demo showroom fit-out equipment purchase",
        )
    )
    db.commit()


def _seed_obligations(db: Session, user: User) -> None:
    today = date.today()
    obligations = [
        ("Monthly office rent", "rent", Decimal("45000"), -30, "paid", True),
        ("Payroll — staff", "payroll", Decimal("185000"), -30, "paid", True),
        ("GST filing", "tax", Decimal("78000"), -45, "paid", True),
        ("Monthly office rent", "rent", Decimal("45000"), 5, "scheduled", True),
        ("Payroll — staff", "payroll", Decimal("185000"), 8, "scheduled", True),
        ("Supplier PO-8841", "supplier", Decimal("148000"), 12, "scheduled", False),
        ("GST filing", "tax", Decimal("96500"), 18, "scheduled", True),
        ("Equipment loan EMI", "debt", Decimal("42300"), 21, "scheduled", True),
        ("Payroll — staff", "payroll", Decimal("185000"), 38, "scheduled", True),
        ("GST filing", "tax", Decimal("92000"), 50, "scheduled", True),
        ("Business insurance", "other", Decimal("28000"), 52, "scheduled", False),
        ("Supplier PO-9012", "supplier", Decimal("110000"), 70, "scheduled", False),
    ]
    for name, category, amount, offset, status, recurring in obligations:
        db.add(
            FinancialObligation(
                user_id=user.id,
                name=name,
                category=category,
                amount=amount,
                due_date=today + timedelta(days=offset),
                status=status,
                recurring=recurring,
                notes="Demo obligation",
            )
        )
    db.commit()


def _seed_integration_rows(db: Session, user: User) -> None:
    rows = [
        ("paypal", "simulated" if not settings.paypal_configured else "sandbox", "demo" if not settings.paypal_configured else "configured"),
        ("upstox", "live" if settings.upstox_configured else "demo", "configured" if settings.upstox_configured else "demo"),
        ("metals", "live" if settings.METALS_API_KEY else "demo", "configured" if settings.METALS_API_KEY else "demo"),
        ("news", "live" if settings.NEWS_API_KEY else "demo", "configured" if settings.NEWS_API_KEY else "demo"),
        ("llm", "llm" if settings.llm_configured else "rules", "configured" if settings.llm_configured else "fallback"),
    ]
    for provider, mode, status in rows:
        db.add(
            IntegrationConfig(
                user_id=user.id,
                provider=provider,
                mode=mode,
                status=status,
                details={"note": "No credentials are stored in this record."},
                last_checked_at=utcnow(),
            )
        )
    db.commit()


def seed_demo_user(db: Session) -> User:
    existing = db.query(User).filter(User.email == settings.DEMO_EMAIL.lower()).one_or_none()
    if existing is not None:
        seed_demo_employee(db, existing)
        if existing.is_demo:
            if existing.full_name != DEMO_OWNER:
                existing.full_name = DEMO_OWNER
                db.commit()
            ensure_global_market_data(db)
            if settings.SEED_DEMO_TRANSACTIONS:
                seed_demo_portfolio(db, existing)
        db.commit()
        return existing
    ensure_global_market_data(db)
    user = create_user(
        db,
        email=settings.DEMO_EMAIL,
        password=settings.DEMO_PASSWORD,
        full_name=DEMO_OWNER,
        business_name=DEMO_BUSINESS,
        currency="INR",
        is_demo=True,
        opening_cash_balance=Decimal("900000")
        if settings.SEED_DEMO_TRANSACTIONS
        else Decimal("0"),
        min_cash_reserve=Decimal("300000")
        if settings.SEED_DEMO_TRANSACTIONS
        else Decimal("0"),
    )
    db.commit()
    seed_business_data(db, user)
    seed_demo_employee(db, user)
    db.commit()
    return user


DEMO_PORTFOLIO = (
    ("RELIANCE", 12, "1204.00"),
    ("TCS", 6, "2338.00"),
    ("HDFCBANK", 20, "651.50"),
    ("INFY", 10, "1182.40"),
    ("ITC", 40, "267.80"),
    ("SUNPHARMA", 8, "1693.00"),
)


def seed_demo_portfolio(db: Session, user: User) -> None:
    if db.query(PortfolioHolding).filter(PortfolioHolding.user_id == user.id).count():
        return
    symbols = [row[0] for row in DEMO_PORTFOLIO]
    instruments = {
        instrument.symbol: instrument
        for instrument in db.query(MarketInstrument)
        .filter(MarketInstrument.symbol.in_(symbols))
        .all()
    }
    opened_at = utcnow() - timedelta(days=45)
    for symbol, quantity, cost in DEMO_PORTFOLIO:
        instrument = instruments.get(symbol)
        if instrument is None:
            continue
        db.add(
            PortfolioHolding(
                user_id=user.id,
                instrument_id=instrument.id,
                quantity=quantity,
                average_cost=Decimal(cost),
                source="demo_seed",
                opened_at=opened_at,
                last_trade_at=opened_at,
            )
        )
    db.commit()


def seed_business_data(db: Session, user: User) -> None:
    ensure_global_market_data(db)
    profile = user.profile
    profile.business_name = DEMO_BUSINESS if user.is_demo else profile.business_name
    seeded_cash = Decimal("900000") if settings.SEED_DEMO_TRANSACTIONS else Decimal("0")
    profile.opening_cash_balance = q2(seeded_cash if user.is_demo else profile.opening_cash_balance)
    profile.opening_balance_date = date.today() - timedelta(days=180)
    seeded_reserve = Decimal("300000") if settings.SEED_DEMO_TRANSACTIONS else Decimal("0")
    profile.min_cash_reserve = q2(seeded_reserve if user.is_demo else profile.min_cash_reserve)
    profile.risk_tolerance = "balanced"
    profile.research_interests = ["RELIANCE", "TCS", "HDFCBANK"]
    if user.is_demo:
        profile.legal_name = DEMO_BUSINESS
        profile.address_line1 = "Unit 4, Laxmi Industrial Estate"
        profile.address_line2 = "New Link Road, Andheri West"
        profile.city = "Mumbai"
        profile.state = "Maharashtra"
        profile.state_code = "27"
        profile.postal_code = "400053"
        profile.business_phone = "+91 22 4000 1188"
        profile.business_email = settings.DEMO_EMAIL
        profile.invoice_terms = (
            "Payment due within the stated credit period. GST is charged at the rate shown "
            "against each line item. This is demo data for illustration only."
        )
    ensure_default_gst_rates(db, user)
    db.commit()

    if user.is_demo and settings.SEED_DEMO_TRANSACTIONS:
        seed_demo_portfolio(db, user)

    customer_specs = [
        (
            "Priya Nair",
            "Alpha Design Studio",
            "alpha@example.com",
            "+91 98200 11001",
            "14 Turner Road, Bandra West",
            "Mumbai",
            "Maharashtra",
            "27",
            "400050",
        ),
        (
            "Rohan Kapoor",
            "Beta Workspaces",
            "rohan@example.com",
            "+91 98200 11002",
            "80 Feet Road, Indiranagar",
            "Bengaluru",
            "Karnataka",
            "29",
            "560038",
        ),
        (
            "Meera Iyer",
            "Gamma Interiors",
            "meera@example.com",
            "+91 98200 11003",
            "22 Nungambakkam High Road",
            "Chennai",
            "Tamil Nadu",
            "33",
            "600034",
        ),
        (
            "Arjun Rao",
            "Delta Build Co.",
            "arjun@example.com",
            "+91 98200 11004",
            "7 Ashram Road",
            "Ahmedabad",
            "Gujarat",
            "24",
            "380009",
        ),
        (
            "Sara Khan",
            "Epsilon Labs",
            "sara@example.com",
            "+91 98200 11005",
            "3 Baner Road",
            "Pune",
            "Maharashtra",
            "27",
            "411045",
        ),
        (
            "Vikram Shah",
            "Zeta Retail",
            "vikram@example.com",
            "+91 98200 11006",
            "18 Ring Road",
            "Surat",
            "Gujarat",
            "24",
            "395002",
        ),
    ]
    customers = []
    for name, company, email, phone, address, city, state, state_code, postal_code in customer_specs:
        customer = Customer(
            user_id=user.id,
            name=name,
            company=company,
            email=email,
            phone=phone,
            billing_address_line1=address,
            city=city,
            state=state,
            state_code=state_code,
            postal_code=postal_code,
        )
        db.add(customer)
        customers.append(customer)
    db.flush()

    product_specs = [
        ("CH-ERG", "Ergo Pro Task Chair", 18_500, 11_900, 10, 34, "9401", 18),
        ("DK-LFT", "LiftDesk Pro", 34_000, 22_500, 6, 12, "9403", 18),
        ("MA-DUAL", "Dual Monitor Arm", 6_500, 3_900, 12, 9, "8302", 18),
        ("RSR-LAP", "Laptop Riser", 2_900, 1_700, 15, 4, "9403", 18),
        ("CB-STL", "Steel Filing Cabinet", 21_000, 12_800, 4, 8, "9403", 18),
        ("FR-ERG", "Ergonomic Footrest", 3_200, 1_650, 8, 26, "9403", 18),
    ]
    products = {}
    for sku, name, price, cost, reorder, stock, hsn_sac, gst_rate in product_specs:
        product = Product(
            user_id=user.id,
            sku=sku,
            name=name,
            description=f"{name} supplied by {DEMO_BUSINESS if user.is_demo else profile.business_name}.",
            hsn_sac=hsn_sac,
            item_type="goods",
            unit="pcs",
            default_gst_rate=Decimal(gst_rate),
            unit_price=Decimal(price),
            unit_cost=Decimal(cost),
            reorder_level=reorder,
        )
        db.add(product)
        db.flush()
        db.add(InventoryItem(product_id=product.id, quantity_on_hand=stock))
        products[sku] = product
    db.commit()

    if not settings.SEED_DEMO_TRANSACTIONS:
        _seed_integration_rows(db, user)
        log_audit(
            db,
            user_id=user.id,
            actor="system",
            action="demo.seeded",
            entity_type="business",
            entity_id=user.id,
            detail={
                "invoices": 0,
                "customers": len(customers),
                "products": len(products),
                "note": "Clean start: zero balances, no invoices, payments, expenses or portfolio.",
            },
        )
        db.commit()
        return

    invoices = []
    invoice_specs = [
        ("INV-1039", 5, "Zeta Retail", 125, 30, [("CH-ERG", 2), ("MA-DUAL", 1)], Decimal("0"), "bank", 20, "manual"),
        ("INV-1040", 4, "Epsilon Labs", 100, 30, [("DK-LFT", 5)], Decimal("0"), "bank", 30, "manual"),
        ("INV-1041", 0, "Alpha Design Studio", 84, 30, [("CH-ERG", 4), ("MA-DUAL", 3)], Decimal("1"), "bank", 50, "manual"),
        ("INV-1042", 1, "Beta Workspaces", 76, 30, [("DK-LFT", 3)], Decimal("0.45"), "upi", 55, "manual"),
        ("INV-1043", 2, "Gamma Interiors", 68, 30, [("CH-ERG", 5), ("RSR-LAP", 4)], Decimal("0"), "bank", 20, "manual"),
        ("INV-1044", 3, "Delta Build Co.", 60, 15, [("CB-STL", 2), ("FR-ERG", 5)], Decimal("1"), "paypal", 50, "paypal"),
        ("INV-1045", 4, "Epsilon Labs", 52, 30, [("DK-LFT", 4), ("CH-ERG", 2)], Decimal("0"), "bank", 20, "manual"),
        ("INV-1046", 5, "Zeta Retail", 45, 30, [("MA-DUAL", 2)], Decimal("1"), "bank", 32, "manual"),
        ("INV-1047", 0, "Alpha Design Studio", 39, 30, [("CH-ERG", 3), ("FR-ERG", 2)], Decimal("0.55"), "bank", 21, "manual"),
        ("INV-1048", 1, "Beta Workspaces", 32, 15, [("RSR-LAP", 5)], Decimal("0"), "bank", 10, "manual"),
        ("INV-1049", 2, "Gamma Interiors", 28, 30, [("DK-LFT", 5)], Decimal("0"), "bank", 10, "manual"),
        ("INV-1050", 3, "Delta Build Co.", 24, 15, [("CB-STL", 3)], Decimal("1"), "upi", 12, "manual"),
        ("INV-1051", 4, "Epsilon Labs", 20, 30, [("CH-ERG", 4), ("MA-DUAL", 2)], Decimal("0"), "bank", 10, "manual"),
        ("INV-1052", 5, "Zeta Retail", 15, 30, [("FR-ERG", 4)], Decimal("0.40"), "bank", 5, "manual"),
        ("INV-1053", 0, "Alpha Design Studio", 10, 30, [("DK-LFT", 3), ("RSR-LAP", 3)], Decimal("0"), "bank", 5, "manual"),
        ("INV-1054", 1, "Beta Workspaces", 6, 30, [("CH-ERG", 6)], Decimal("0"), "bank", 3, "manual"),
        ("INV-1055", 2, "Gamma Interiors", 2, 30, [("MA-DUAL", 3), ("CB-STL", 1)], Decimal("0"), "bank", 1, "manual"),
        ("INV-1056", 3, "Delta Build Co.", 41, 30, [("CH-ERG", 2)], Decimal("0"), "bank", 10, "manual"),
        ("INV-1057", 3, "Delta Build Co.", 38, 30, [("CH-ERG", 2)], Decimal("0"), "bank", 10, "manual"),
    ]
    for (
        number,
        index,
        _company,
        issue_ago,
        terms,
        item_specs,
        fraction,
        method,
        delay,
        provider,
    ) in invoice_specs:
        invoice = _make_invoice(
            db,
            user=user,
            customer=customers[index],
            number=number,
            issue_days_ago=issue_ago,
            terms_days=terms,
            items=[(products[sku], qty) for sku, qty in item_specs],
            payment_fraction=fraction,
            method=method,
            payment_delay_days=delay,
            provider=provider,
        )
        invoices.append(invoice)

    invoice_1055 = next(inv for inv in invoices if inv.number == "INV-1055")
    invoice_1054 = next(inv for inv in invoices if inv.number == "INV-1054")
    invoice_1052 = next(inv for inv in invoices if inv.number == "INV-1052")

    # A confirmed but unmatched bank transfer, suggesting reconciliation for INV-1055.
    record_payment(
        db,
        user=user,
        invoice=None,
        amount=invoice_1055.total_amount,
        method="bank",
        provider="bank_statement",
        provider_ref="NEFT-DEMO-88421",
        sender_name="Gamma Interiors",
        note="Bank statement line — customer name matches Gamma Interiors. Awaiting reconciliation.",
        received_at=datetime.combine(date.today() - timedelta(days=4), time(15, 10)),
        commit=True,
    )
    db.add(
        Payment(
            user_id=user.id,
            invoice_id=invoice_1054.id,
            amount=Decimal("30000.00"),
            currency=user.profile.currency,
            method="paypal",
            status="pending",
            provider="paypal",
            provider_ref="PPL-DEMO-PENDING-1054",
            note="PayPal pending demo payment — not cash until verified.",
            created_at=utcnow() - timedelta(days=2),
        )
    )
    db.add(
        Payment(
            user_id=user.id,
            invoice_id=invoice_1052.id,
            amount=Decimal("8000.00"),
            currency=user.profile.currency,
            method="paypal",
            status="failed",
            provider="paypal",
            provider_ref="PPL-DEMO-FAILED-1052",
            note="Simulated failed PayPal capture.",
            created_at=utcnow() - timedelta(days=1),
        )
    )
    db.add(
        PaymentEvent(
            provider="paypal",
            event_id="DEMO-WEBHOOK-EVT-10044",
            event_type="PAYMENT.CAPTURE.COMPLETED",
            payload_hash="0" * 64,
            outcome="Demo verified capture for INV-1044 · simulated event record",
        )
    )
    db.commit()

    _seed_expenses(db, user)
    _seed_obligations(db, user)
    _seed_integration_rows(db, user)

    # Refresh statuses after all payments.
    for invoice in invoices:
        from .services.payments import refresh_invoice_status

        refresh_invoice_status(db, invoice)
    db.commit()

    generate_business_insights(db, user, 90)
    _seed_approvals(db, user, invoices)
    log_audit(
        db,
        user_id=user.id,
        actor="system",
        action="demo.seeded",
        entity_type="business",
        entity_id=user.id,
        detail={
            "invoices": len(invoices),
            "customers": len(customers),
            "products": len(products),
            "note": "All seeded records are demo data.",
        },
    )
    db.commit()


def _seed_approvals(db: Session, user: User, invoices: list[Invoice]) -> None:
    from .services.approvals import approve_request, reject_request
    from .services.finance import confirmed_paid_by_invoice

    top = sorted(
        [invoice for invoice in invoices if invoice.outstanding_amount > 0],
        key=lambda invoice: (invoice.outstanding_amount, -invoice.due_date.toordinal()),
        reverse=True,
    )[0]
    tcs_instrument = (
        db.query(MarketInstrument).filter(MarketInstrument.symbol == "TCS").one()
    )
    paid_map = confirmed_paid_by_invoice(db, user.id)
    draft = reminder_draft(top, user.profile, user.profile.reminder_tone, paid_map.get(top.id))
    reminder = create_approval(
        db,
        user,
        action_type="reminder.send",
        title=f"Send payment reminder to {top.customer.name}",
        reason=f"Invoice {top.number} is overdue with {user.profile.currency} {top.outstanding_amount:,.2f} outstanding.",
        payload={
            "invoice_id": top.id,
            "invoice_number": top.number,
            "recipient": top.customer.email,
            "channel": "email",
            "subject": draft["subject"],
            "body": draft["body"],
        },
        evidence=[
            {
                "type": "invoice",
                "id": top.id,
                "label": f"{top.number} · {top.customer.company}",
                "amount": q2(top.outstanding_amount),
            }
        ],
        financial_impact=top.outstanding_amount,
        risk_level="low",
    )

    signal = (
        db.query(ResearchSignal)
        .filter(ResearchSignal.instrument_id == tcs_instrument.id)
        .order_by(ResearchSignal.generated_at.desc())
        .first()
    )
    quote = (
        db.query(MarketQuote)
        .filter(MarketQuote.instrument_id == tcs_instrument.id)
        .order_by(MarketQuote.id.desc())
        .first()
    )
    investment = create_approval(
        db,
        user,
        action_type="investment.order",
        title="Review simulated buy order · 1 × TCS",
        reason=(
            "Research model signal is positive on demo data. This is a simulated order for workflow review, "
            "not an analyst recommendation or live trade."
        ),
        payload={
            "symbol": "TCS",
            "side": "buy",
            "quantity": 1,
            "order_type": "market",
            "limit_price": None,
            "quote_price": float(quote.price) if quote else None,
            "quote_as_of": quote.as_of.isoformat() if quote and quote.as_of else None,
            "quote_data_mode": quote.data_mode if quote else None,
            "simulated": True,
        },
        evidence=[
            {
                "type": "research_signal",
                "id": signal.id if signal else None,
                "label": f"Model signal · TCS {signal.model_signal if signal else ''}",
            },
            {
                "type": "market_quote",
                "id": "TCS",
                "label": "Demo quote used for illustrative order value",
                "amount": q2(quote.price) if quote else None,
            },
        ],
        financial_impact=q2(quote.price) if quote else None,
        risk_level="high",
    )

    intervention = create_approval(
        db,
        user,
        action_type="cashflow.intervention",
        title="Acknowledge cash-flow action plan before payroll",
        reason=(
            "Upcoming payroll, rent and supplier payments cluster in the next two weeks. "
            "Approving records that the owner reviewed the advisory plan; it does not move money."
        ),
        payload={
            "recommendation": (
                "Prioritise reminders for invoices INV-1040 and INV-1045, hold non-essential marketing spend, "
                "and confirm payroll funding three days before the due date."
            ),
            "no_external_effect": True,
        },
        evidence=[
            {"type": "advisory", "id": "cashflow-plan", "label": "Cash-flow action plan (advisory only)"}
        ],
        financial_impact=Decimal("185000"),
        risk_level="medium",
    )

    # Demo approvals stay valid long enough for a walkthrough.
    now = utcnow()
    reminder.expires_at = now + timedelta(days=2)
    investment.expires_at = now + timedelta(days=2)
    intervention.expires_at = now + timedelta(days=3)
    db.commit()

    # One executed reminder to demonstrate the dispatch audit (simulated delivery).
    executed_invoice = next((inv for inv in invoices if inv.number == "INV-1043"), None)
    if executed_invoice is not None:
        executed_draft = reminder_draft(
            executed_invoice, user.profile, "professional", paid_map.get(executed_invoice.id)
        )
        executed = create_approval(
            db,
            user,
            action_type="reminder.send",
            title=f"Send payment reminder to {executed_invoice.customer.name}",
            reason=f"Invoice {executed_invoice.number} overdue collection follow-up.",
            payload={
                "invoice_id": executed_invoice.id,
                "invoice_number": executed_invoice.number,
                "recipient": executed_invoice.customer.email,
                "channel": "email",
                "subject": executed_draft["subject"],
                "body": executed_draft["body"],
            },
            financial_impact=executed_invoice.outstanding_amount,
            risk_level="low",
        )
        approve_request(db, user, executed.id, executed.payload_hash, True, note="Demo walkthrough")

    rejected = create_approval(
        db,
        user,
        action_type="cashflow.intervention",
        title="Defer supplier payment (review)",
        reason="Proposed deferral of a supplier obligation to protect cash.",
        payload={"recommendation": "Request a 15-day extension from the supplier.", "no_external_effect": True},
        financial_impact=Decimal("148000"),
        risk_level="medium",
    )
    reject_request(db, user, rejected.id, "Supplier relationship is important; keep the original date.")

    expired = create_approval(
        db,
        user,
        action_type="investment.order",
        title="Review simulated buy order · 2 × HDFCBANK",
        reason="Earlier research review; approval window elapsed before a decision.",
        payload={
            "symbol": "HDFCBANK",
            "side": "buy",
            "quantity": 2,
            "order_type": "market",
            "limit_price": None,
            "simulated": True,
        },
        financial_impact=Decimal("3520"),
        risk_level="high",
    )
    expired.expires_at = utcnow() - timedelta(hours=3)
    expired.status = "expired"
    log_audit(
        db,
        user_id=user.id,
        actor="system",
        action="approval.expired",
        entity_type="approval",
        entity_id=expired.id,
        detail={"title": expired.title},
    )
    db.commit()


def reset_demo(db: Session) -> User:
    user = db.query(User).filter(User.email == settings.DEMO_EMAIL.lower()).one_or_none()
    if user is None:
        return seed_demo_user(db)
    clear_user_business_data(db, user)
    db.query(User).filter(User.id == user.id).update({"password_hash": hash_password(settings.DEMO_PASSWORD)})
    employee = seed_demo_employee(db, user)
    employee.password_hash = hash_password(settings.DEMO_EMPLOYEE_PASSWORD)
    db.commit()
    db.refresh(user)
    seed_business_data(db, user)
    db.commit()
    return user


# ---------------------------------------------------------------- accounting practice


def _practice_user(
    db: Session, *, email: str, password: str, full_name: str, role: str
) -> User | None:
    email = email.strip().lower()
    if not email or not password:
        return None
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is not None and user.role != role:
        logger.warning("Accounting seed skipped %s: existing account has role %s.", email, user.role)
        return None
    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role=role,
            is_demo=True,
            is_active=True,
        )
        db.add(user)
        db.flush()
    elif not user.is_active:
        user.is_active = True
    return user


def _practice_voucher(
    db: Session,
    client: AccountingClient,
    *,
    voucher_type: str,
    number: str,
    voucher_date: date,
    party_name: str,
    party_gstin: str | None,
    ledger_name: str,
    category: str | None,
    taxable_value: Decimal,
    gst_rate: Decimal,
    inter_state: bool,
    created_by: User | None,
    bank_ledger: str | None = None,
    description: str | None = None,
) -> AccountingVoucher:
    amounts = split_gst(taxable_value, gst_rate, inter_state)
    voucher = AccountingVoucher(
        client_id=client.id,
        voucher_type=voucher_type,
        number=number,
        voucher_date=voucher_date,
        party_name=party_name,
        party_gstin=party_gstin,
        ledger_name=ledger_name,
        bank_ledger=bank_ledger,
        category=category,
        description=description or f"{voucher_type.title()} recorded for {party_name}",
        taxable_value=q2(taxable_value),
        gst_rate=gst_rate,
        inter_state=inter_state,
        cgst_amount=amounts["cgst"],
        sgst_amount=amounts["sgst"],
        igst_amount=amounts["igst"],
        total_amount=amounts["total"],
        source="manual",
        status="posted",
        dedupe_hash=voucher_dedupe_hash(
            client.id, voucher_type, number, voucher_date, amounts["total"]
        ),
        created_by_user_id=created_by.id if created_by else None,
    )
    db.add(voucher)
    db.flush()
    return voucher


def _ensure_dn_ventures_client(db: Session, senior: User, junior: User) -> AccountingClient | None:
    """Link the demo Business Manager business into the accounting practice.

    Idempotent: existing databases gain the client without reseeding Meridian or
    Sunrise. The books are seeded practice records; they are not derived from
    Business Manager invoices or expenses.
    """
    owner = db.query(User).filter(User.email == settings.DEMO_EMAIL.lower()).one_or_none()
    if owner is None or owner.profile is None:
        return None
    profile = owner.profile
    today = date.today()
    code = f"ACC-{today.year}-003"
    existing = (
        db.query(AccountingClient)
        .filter(AccountingClient.business_profile_id == profile.id)
        .one_or_none()
    )
    if existing is not None:
        return existing
    existing = db.query(AccountingClient).filter(AccountingClient.code == code).one_or_none()
    if existing is not None:
        existing.business_profile_id = profile.id
        return existing

    client = AccountingClient(
        code=code,
        business_name=profile.business_name or DEMO_BUSINESS,
        contact_name=owner.full_name,
        email=owner.email,
        phone=profile.business_phone,
        business_type="Private Limited",
        turnover_range="INR 1 crore - 5 crore",
        gst_status="Registered - regular",
        gstin=profile.gstin,
        pan_last4=None,
        financial_year=financial_year_for(today),
        service_package="GST accounting + bookkeeping",
        status="active",
        business_profile_id=profile.id,
        integration_status="linked",
        integration_enabled_at=utcnow() - timedelta(days=60),
        integration_settings={
            "sync_sources": ["invoice", "payment", "expense", "refund"],
            "include_voided": False,
            "draft_mode": "manual",
        },
        senior_accountant_user_id=senior.id,
        assigned_junior_user_id=junior.id,
        onboarded_at=utcnow() - timedelta(days=60),
        notes=(
            "Linked to the Business Manager demo business. Accounting books are seeded "
            "practice records. Business Manager data is reviewed by an accountant and is "
            "never posted automatically."
        ),
    )
    db.add(client)
    db.flush()

    month = today.replace(day=1)
    last_month = (month - timedelta(days=1)).replace(day=1)
    _practice_voucher(
        db, client,
        voucher_type="sale", number=f"DN-S-{last_month:%Y%m}-01",
        voucher_date=last_month + timedelta(days=8),
        party_name="Alpha Design Studio", party_gstin=None,
        ledger_name="Sales - office furniture", category="Furniture sales",
        taxable_value=Decimal("62000.00"), gst_rate=Decimal("18.00"),
        inter_state=False, created_by=junior,
    )
    _practice_voucher(
        db, client,
        voucher_type="sale", number=f"DN-S-{today:%Y%m}-01",
        voucher_date=today,
        party_name="Zeta Retail", party_gstin=None,
        ledger_name="Sales - office furniture", category="Furniture sales",
        taxable_value=Decimal("34000.00"), gst_rate=Decimal("18.00"),
        inter_state=True, created_by=junior,
    )
    _practice_voucher(
        db, client,
        voucher_type="purchase", number=f"DN-P-{today:%Y%m}-01",
        voucher_date=today,
        party_name="OfficeFit Supplies", party_gstin="27AABCO4444F1Z1",
        ledger_name="Purchases - stock", category="Inventory purchases",
        taxable_value=Decimal("24500.00"), gst_rate=Decimal("18.00"),
        inter_state=False, created_by=junior,
    )
    _practice_voucher(
        db, client,
        voucher_type="receipt", number=f"DN-R-{today:%Y%m}-01",
        voucher_date=today,
        party_name="Alpha Design Studio", party_gstin=None,
        ledger_name="ICICI Bank - Current", bank_ledger="ICICI Bank - Current",
        category="Receivable receipt", taxable_value=Decimal("40000.00"),
        gst_rate=Decimal("0.00"), inter_state=False, created_by=junior,
        description="Part receipt against DN-S sale from Alpha Design Studio",
    )
    _practice_voucher(
        db, client,
        voucher_type="payment", number=f"DN-PAY-{today:%Y%m}-01",
        voucher_date=today,
        party_name="OfficeFit Supplies", party_gstin="27AABCO4444F1Z1",
        ledger_name="ICICI Bank - Current", bank_ledger="ICICI Bank - Current",
        category="Supplier payment", taxable_value=Decimal("20000.00"),
        gst_rate=Decimal("0.00"), inter_state=False, created_by=junior,
        description="Payment against DN-P purchase from OfficeFit Supplies",
    )
    _practice_voucher(
        db, client,
        voucher_type="expense", number=f"DN-E-{today:%Y%m}-01",
        voucher_date=today,
        party_name="WeWork India", party_gstin=None,
        ledger_name="Office rent", bank_ledger="ICICI Bank - Current",
        category="Rent", taxable_value=Decimal("45000.00"),
        gst_rate=Decimal("0.00"), inter_state=False, created_by=junior,
        description="Monthly office rent paid by bank transfer",
    )

    db.add_all(
        [
            AccountingStockItem(
                client_id=client.id, name="Ergo Pro Task Chair", sku="CH-ERG", unit="Nos",
                hsn_sac="9401", gst_rate=Decimal("18.00"),
                opening_qty=Decimal("34.000"), opening_rate=Decimal("11900.00"),
                created_by_user_id=senior.id,
            ),
            AccountingStockItem(
                client_id=client.id, name="LiftDesk Pro", sku="DK-LFT", unit="Nos",
                hsn_sac="9403", gst_rate=Decimal("18.00"),
                opening_qty=Decimal("12.000"), opening_rate=Decimal("22500.00"),
                created_by_user_id=senior.id,
            ),
            AccountingStockItem(
                client_id=client.id, name="Dual Monitor Arm", sku="MA-DUAL", unit="Nos",
                hsn_sac="8302", gst_rate=Decimal("18.00"),
                opening_qty=Decimal("9.000"), opening_rate=Decimal("3900.00"),
                created_by_user_id=junior.id,
            ),
        ]
    )
    db.add(
        AccountingTask(
            client_id=client.id,
            title="Monthly GST working papers",
            description="Prepare GSTR-1 and 3B working papers from the linked demo books.",
            service_type="gst_accounting",
            status="in_progress",
            priority="high",
            due_date=today + timedelta(days=5),
            assigned_to_user_id=junior.id,
            created_by_user_id=senior.id,
            progress=40,
        )
    )
    log_audit(
        db,
        user_id=senior.id,
        actor=senior.email,
        action="accounting.client_created",
        entity_type="accounting_client",
        entity_id=client.id,
        detail={
            "client_id": client.id,
            "code": client.code,
            "business_profile_id": profile.id,
            "seeded": True,
        },
    )
    db.flush()
    return client


def _ensure_tally_history_demo(db: Session, senior: User, junior: User) -> None:
    """Seed file-based Tally history for Sunrise Interiors only.

    The data lives in the historical tables, never in the live voucher ledger.
    Meridian Traders is left untouched so the import workflow can be demonstrated
    on it from an empty starting point.
    """
    from .services.tally_migration import voucher_fingerprint

    sunrise = (
        db.query(AccountingClient)
        .filter(AccountingClient.business_name == "Sunrise Interiors")
        .one_or_none()
    )
    if sunrise is None:
        return
    if (
        db.query(AccountingHistoricalVoucher.id)
        .filter(AccountingHistoricalVoucher.client_id == sunrise.id)
        .first()
        is not None
    ):
        return

    today = date.today()
    stock_defs = [
        ("Office Chair", "BW-CHAIR", "9401", Decimal("18.00")),
        ("Workstation Desk", "BW-DESK", "9403", Decimal("18.00")),
        ("Storage Cabinet", "BW-CAB", "9403", Decimal("18.00")),
    ]
    existing_skus = {
        sku
        for (sku,) in db.query(AccountingStockItem.sku)
        .filter(AccountingStockItem.client_id == sunrise.id)
        .all()
    }
    for name, sku, hsn, gst_rate in stock_defs:
        if sku in existing_skus:
            continue
        db.add(
            AccountingStockItem(
                client_id=sunrise.id,
                name=name,
                sku=sku,
                unit="Nos",
                hsn_sac=hsn,
                gst_rate=gst_rate,
                opening_qty=Decimal("0.000"),
                opening_rate=Decimal("0.000"),
                created_by_user_id=senior.id,
            )
        )

    ledger_groups = {
        "Cash-in-Hand": "Cash-in-Hand",
        "HDFC Bank - Current": "Bank Accounts",
        "Kaveri Interiors": "Sundry Debtors",
        "Deccan Furnishings": "Sundry Debtors",
        "Timber House": "Sundry Creditors",
        "Capital Account": "Capital Account",
        "Sales - interiors": "Sales Accounts",
        "Purchases - materials": "Purchase Accounts",
        "Office rent": "Indirect Expenses",
        "Depreciation": "Indirect Expenses",
        "Accumulated Depreciation": "Fixed Assets",
        "Output CGST": "Duties & Taxes",
        "Output SGST": "Duties & Taxes",
        "Output IGST": "Duties & Taxes",
        "Input CGST": "Duties & Taxes",
        "Input SGST": "Duties & Taxes",
        "Closing Stock": "Stock-in-Hand",
    }
    party_ledgers = {
        "Kaveri Interiors": "customer",
        "Deccan Furnishings": "customer",
        "Timber House": "supplier",
    }

    def ensure_ledgers(batch: AccountingTallyMigration, financial_year: str) -> None:
        existing = {
            name
            for (name,) in db.query(AccountingHistoricalLedger.name)
            .filter(
                AccountingHistoricalLedger.client_id == sunrise.id,
                AccountingHistoricalLedger.financial_year == financial_year,
            )
            .all()
        }
        for name, group in ledger_groups.items():
            if name in existing:
                continue
            db.add(
                AccountingHistoricalLedger(
                    client_id=sunrise.id,
                    migration_id=batch.id,
                    name=name,
                    group_name=group,
                    party_type=party_ledgers.get(name, "other"),
                    financial_year=financial_year,
                    opening_debit=Decimal("0.00"),
                    opening_credit=Decimal("0.00"),
                )
            )

    def add_voucher(
        batch: AccountingTallyMigration,
        financial_year: str,
        *,
        voucher_type: str,
        number: str,
        on: date,
        party: str | None,
        narration: str,
        lines: list[tuple[str, str, str, str, str | None, str | None]],
        cgst: str = "0.00",
        sgst: str = "0.00",
        igst: str = "0.00",
        taxable: str = "0.00",
        gst_rate: str = "18.00",
        source_row: int,
    ) -> None:
        debit_total = sum((Decimal(line[2]) for line in lines), Decimal("0.00"))
        credit_total = sum((Decimal(line[3]) for line in lines), Decimal("0.00"))
        voucher = AccountingHistoricalVoucher(
            client_id=sunrise.id,
            migration_id=batch.id,
            voucher_type=voucher_type,
            number=number,
            voucher_date=on,
            financial_year=financial_year,
            party_name=party,
            narration=narration,
            taxable_value=Decimal(taxable),
            gst_rate=Decimal(gst_rate),
            cgst_amount=Decimal(cgst),
            sgst_amount=Decimal(sgst),
            igst_amount=Decimal(igst),
            total_debit=debit_total,
            total_credit=credit_total,
            inter_state=Decimal(igst) > 0,
            source_format="xml",
            source_filename=batch.filename,
            source_row=source_row,
            fingerprint=voucher_fingerprint(
                sunrise.id, voucher_type, number, on, debit_total
            ),
        )
        db.add(voucher)
        db.flush()
        for position, (ledger, group, debit, credit, stock_item, quantity) in enumerate(
            lines, start=1
        ):
            db.add(
                AccountingHistoricalVoucherLine(
                    voucher_id=voucher.id,
                    line_number=position,
                    ledger_name=ledger,
                    ledger_group=group,
                    debit=Decimal(debit),
                    credit=Decimal(credit),
                    stock_item=stock_item,
                    quantity=Decimal(quantity) if quantity else None,
                    is_party=ledger == party,
                )
            )

    def seed_year(
        financial_year: str,
        *,
        start: date,
        end: date,
        vouchers: list[dict],
        suffix: str,
    ) -> AccountingTallyMigration:
        batch = AccountingTallyMigration(
            client_id=sunrise.id,
            direction="import",
            tally_version="TallyPrime 4.1",
            financial_year=financial_year,
            period_from=start,
            period_to=end,
            import_type="complete",
            file_format="xml",
            filename=f"sunrise-tally-history-{financial_year}.xml",
            row_count=len(vouchers),
            valid_count=len(vouchers),
            imported_count=len(vouchers),
            status="imported",
            prepared_by_user_id=junior.id,
            submitted_at=utcnow() - timedelta(days=20),
            approved_by_user_id=senior.id,
            approved_at=utcnow() - timedelta(days=19),
            approval_note="Seeded demo history reviewed by the senior accountant.",
            retained_until=today + timedelta(days=settings.ACCOUNTING_TALLY_RETENTION_DAYS),
            mapping={},
            validation={
                "ok": True,
                "counts": {
                    "detected": len(vouchers),
                    "valid": len(vouchers),
                    "warnings": 0,
                    "errors": 0,
                    "duplicates": 0,
                },
                "issues": [],
                "checks": [],
                "totals": {},
            },
            details={
                "seeded": True,
                "live_ledger_untouched": True,
                "note": (
                    "Demo historical import. File-based migration only; the live FINOVEXA "
                    "ledger and Meridian demo client were not changed."
                ),
            },
        )
        db.add(batch)
        db.flush()
        ensure_ledgers(batch, financial_year)
        for index, voucher in enumerate(vouchers, start=1):
            add_voucher(batch, financial_year, source_row=index, **voucher)
        return batch

    def sale_lines(party: str, taxable: str, cgst: str, sgst: str, igst: str):
        total = Decimal(taxable) + Decimal(cgst) + Decimal(sgst) + Decimal(igst)
        lines = [
            (party, "Sundry Debtors", f"{total:.2f}", "0.00", None, None),
            ("Sales - interiors", "Sales Accounts", "0.00", f"{Decimal(taxable):.2f}", None, None),
        ]
        if Decimal(igst):
            lines.append(("Output IGST", "Duties & Taxes", "0.00", f"{Decimal(igst):.2f}", None, None))
        else:
            lines.append(("Output CGST", "Duties & Taxes", "0.00", f"{Decimal(cgst):.2f}", None, None))
            lines.append(("Output SGST", "Duties & Taxes", "0.00", f"{Decimal(sgst):.2f}", None, None))
        return lines

    prior_batch = seed_year(
        "2023-24",
        start=date(2023, 4, 1),
        end=date(2024, 3, 31),
        vouchers=[
            {
                "voucher_type": "sale",
                "number": "SI-2301",
                "on": date(2023, 6, 14),
                "party": "Kaveri Interiors",
                "narration": "Interior project billing",
                "lines": sale_lines("Kaveri Interiors", "100000.00", "9000.00", "9000.00", "0.00"),
                "taxable": "100000.00",
                "cgst": "9000.00",
                "sgst": "9000.00",
            },
            {
                "voucher_type": "sale",
                "number": "SI-2302",
                "on": date(2023, 11, 8),
                "party": "Deccan Furnishings",
                "narration": "Inter-state project billing",
                "lines": sale_lines("Deccan Furnishings", "60000.00", "0.00", "0.00", "10800.00"),
                "taxable": "60000.00",
                "igst": "10800.00",
            },
            {
                "voucher_type": "purchase",
                "number": "SI-P-2301",
                "on": date(2023, 7, 2),
                "party": "Timber House",
                "narration": "Material purchase",
                "lines": [
                    ("Purchases - materials", "Purchase Accounts", "40000.00", "0.00", None, None),
                    ("Input CGST", "Duties & Taxes", "3600.00", "0.00", None, None),
                    ("Input SGST", "Duties & Taxes", "3600.00", "0.00", None, None),
                    ("Timber House", "Sundry Creditors", "0.00", "47200.00", None, None),
                ],
                "taxable": "40000.00",
                "cgst": "3600.00",
                "sgst": "3600.00",
            },
        ],
        suffix="prior",
    )

    current_batch = seed_year(
        "2024-25",
        start=date(2024, 4, 1),
        end=date(2025, 3, 31),
        vouchers=[
            {
                "voucher_type": "sale",
                "number": "SI-2401",
                "on": date(2024, 5, 12),
                "party": "Kaveri Interiors",
                "narration": "Living room project billing",
                "lines": sale_lines("Kaveri Interiors", "120000.00", "10800.00", "10800.00", "0.00"),
                "taxable": "120000.00",
                "cgst": "10800.00",
                "sgst": "10800.00",
            },
            {
                "voucher_type": "sale",
                "number": "SI-2402",
                "on": date(2024, 8, 20),
                "party": "Deccan Furnishings",
                "narration": "Inter-state office fit-out",
                "lines": sale_lines("Deccan Furnishings", "90000.00", "0.00", "0.00", "16200.00"),
                "taxable": "90000.00",
                "igst": "16200.00",
            },
            {
                "voucher_type": "purchase",
                "number": "SI-P-2401",
                "on": date(2024, 6, 15),
                "party": "Timber House",
                "narration": "Workshop material purchase",
                "lines": [
                    ("Purchases - materials", "Purchase Accounts", "75000.00", "0.00", None, None),
                    ("Input CGST", "Duties & Taxes", "6750.00", "0.00", None, None),
                    ("Input SGST", "Duties & Taxes", "6750.00", "0.00", None, None),
                    ("Timber House", "Sundry Creditors", "0.00", "88500.00", None, None),
                ],
                "taxable": "75000.00",
                "cgst": "6750.00",
                "sgst": "6750.00",
            },
            {
                "voucher_type": "expense",
                "number": "SI-E-2401",
                "on": date(2024, 7, 1),
                "party": None,
                "narration": "Studio rent paid by bank",
                "lines": [
                    ("Office rent", "Indirect Expenses", "30000.00", "0.00", None, None),
                    ("HDFC Bank - Current", "Bank Accounts", "0.00", "30000.00", None, None),
                ],
            },
            {
                "voucher_type": "receipt",
                "number": "SI-R-2401",
                "on": date(2024, 9, 10),
                "party": "Kaveri Interiors",
                "narration": "Part receipt against SI-2401",
                "lines": [
                    ("HDFC Bank - Current", "Bank Accounts", "80000.00", "0.00", None, None),
                    ("Kaveri Interiors", "Sundry Debtors", "0.00", "80000.00", None, None),
                ],
            },
            {
                "voucher_type": "payment",
                "number": "SI-PAY-2401",
                "on": date(2024, 10, 5),
                "party": "Timber House",
                "narration": "Part payment against SI-P-2401",
                "lines": [
                    ("Timber House", "Sundry Creditors", "50000.00", "0.00", None, None),
                    ("HDFC Bank - Current", "Bank Accounts", "0.00", "50000.00", None, None),
                ],
            },
            {
                "voucher_type": "journal",
                "number": "SI-J-2401",
                "on": date(2025, 3, 31),
                "party": None,
                "narration": "Year-end depreciation",
                "lines": [
                    ("Depreciation", "Indirect Expenses", "15000.00", "0.00", None, None),
                    ("Accumulated Depreciation", "Fixed Assets", "0.00", "15000.00", None, None),
                ],
            },
        ],
        suffix="current",
    )

    opening = AccountingOpeningBalance(
        client_id=sunrise.id,
        financial_year="2024-25",
        opening_date=date(2024, 4, 1),
        migration_id=current_batch.id,
        status="approved",
        prepared_by_user_id=junior.id,
        approved_by_user_id=senior.id,
        approved_at=utcnow() - timedelta(days=19),
        approval_note="Seeded demo opening balances approved by the senior accountant.",
        total_debit=Decimal("608000.00"),
        total_credit=Decimal("608000.00"),
        stock_value=Decimal("128000.00"),
        details={"seeded": True, "source": "demo_history"},
    )
    db.add(opening)
    db.flush()
    opening_lines = [
        ("Cash-in-Hand", "Cash-in-Hand", "80000.00", "0.00", None, None, None),
        ("HDFC Bank - Current", "Bank Accounts", "220000.00", "0.00", None, None, None),
        ("Kaveri Interiors", "Sundry Debtors", "100000.00", "0.00", None, None, None),
        ("Deccan Furnishings", "Sundry Debtors", "80000.00", "0.00", None, None, None),
        ("Closing Stock", "Stock-in-Hand", "128000.00", "0.00", "Office Chair", "40", "3200"),
        ("Timber House", "Sundry Creditors", "0.00", "90000.00", None, None, None),
        ("Capital Account", "Capital Account", "0.00", "518000.00", None, None, None),
    ]
    for position, (ledger, group, debit, credit, stock_item, quantity, rate) in enumerate(
        opening_lines, start=1
    ):
        db.add(
            AccountingOpeningBalanceLine(
                opening_id=opening.id,
                line_number=position,
                ledger_name=ledger,
                group_name=group,
                party_type=party_ledgers.get(ledger, "other"),
                debit=Decimal(debit),
                credit=Decimal(credit),
                stock_item=stock_item,
                quantity=Decimal(quantity) if quantity else None,
                rate=Decimal(rate) if rate else None,
                value=Decimal(debit),
            )
        )
    prior_batch.details = {**(prior_batch.details or {}), "seed_group": "comparison_year"}
    current_batch.details = {**(current_batch.details or {}), "seed_group": "current_year"}


def _ensure_demo_pricing_data(db: Session, senior: User) -> None:
    """Repair practice records seeded before the pricing/quotation fields existed."""
    if senior is None:
        return
    today = date.today()
    fy = financial_year_for(today)

    enquiry_defaults = {
        "Nova Retail LLP": {
            "annual_turnover": Decimal("3500000.00"),
            "benchmark_annual": Decimal("70000.00"),
            "bank_accounts": 2,
            "payroll_required": True,
            "inventory_required": False,
        },
        "Coastal Foods": {
            "annual_turnover": Decimal("12000000.00"),
            "benchmark_annual": Decimal("240000.00"),
            "bank_accounts": 1,
            "payroll_required": False,
            "inventory_required": False,
        },
    }
    for enquiry in (
        db.query(AccountingEnquiry)
        .filter(AccountingEnquiry.business_name.in_(enquiry_defaults))
        .all()
    ):
        for field, value in enquiry_defaults[enquiry.business_name].items():
            current = getattr(enquiry, field)
            if current is None or (field == "bank_accounts" and current == 0):
                setattr(enquiry, field, value)
        if not enquiry.financial_year:
            enquiry.financial_year = fy
        if enquiry.business_name == "Coastal Foods" and enquiry.assigned_senior_user_id is None:
            enquiry.assigned_senior_user_id = senior.id

    coastal_lines = [
        {
            "kind": "service",
            "key": "bookkeeping",
            "label": "Bookkeeping",
            "description": "Monthly bookkeeping and ledger review.",
            "service": "bookkeeping",
            "amount": 60000.0,
            "cadence": "annual",
        },
        {
            "kind": "service",
            "key": "gst_accounting",
            "label": "GST accounting",
            "description": "Composition returns working papers.",
            "service": "gst_accounting",
            "amount": 60000.0,
            "cadence": "annual",
        },
        {
            "kind": "service",
            "key": "financial_statements",
            "label": "Financial statements",
            "description": "Quarterly draft financial statements.",
            "service": "financial_statements",
            "amount": 30000.0,
            "cadence": "annual",
        },
    ]
    coastal = (
        db.query(AccountingQuotation)
        .filter(AccountingQuotation.number.like("ACC-QT-%-0001"))
        .order_by(AccountingQuotation.id.desc())
        .first()
    )
    if coastal is not None and (not coastal.line_items or not coastal.total_annual):
        coastal.line_items = coastal_lines
        coastal.scope = [
            {"service": "bookkeeping", "description": "Monthly bookkeeping and ledger review."},
            {"service": "gst_accounting", "description": "Composition returns working papers."},
            {"service": "financial_statements", "description": "Quarterly draft financial statements."},
        ]
        coastal.amount = Decimal("12500.00")
        coastal.billing_cadence = "monthly"
        coastal.payment_frequency = "monthly"
        coastal.subtotal_annual = Decimal("150000.00")
        coastal.total_annual = Decimal("150000.00")
        coastal.monthly_equivalent = Decimal("12500.00")
        coastal.discount_type = "none"
        coastal.discount_value = Decimal("0.00")
        coastal.discount_amount = Decimal("0.00")
        coastal.annual_turnover = Decimal("12000000.00")
        coastal.benchmark_annual = Decimal("240000.00")
        coastal.tax_rate_percent = Decimal("18.00")
        coastal.tax_note = DEFAULT_SETTINGS["tax_note"]
        coastal.terms = coastal.terms or DEFAULT_TERMS
        coastal.validity_days = coastal.validity_days or 15
        coastal.valid_until = coastal.valid_until or (today + timedelta(days=15))
        coastal.approved_at = coastal.approved_at or (utcnow() - timedelta(days=4))
        coastal.approved_by_user_id = coastal.approved_by_user_id or senior.id
        coastal.sent_at = coastal.sent_at or coastal.approved_at

    meridian = (
        db.query(AccountingClient)
        .filter(AccountingClient.business_name == "Meridian Traders")
        .first()
    )
    if meridian is not None:
        existing = (
            db.query(AccountingQuotation)
            .filter(AccountingQuotation.client_id == meridian.id)
            .first()
        )
        number = f"ACC-QT-{today.year}-0003"
        number_taken = (
            db.query(AccountingQuotation)
            .filter(AccountingQuotation.number == number)
            .first()
        )
        if existing is None and number_taken is None:
            db.add(
                AccountingQuotation(
                    number=number,
                    client_id=meridian.id,
                    prepared_by_user_id=senior.id,
                    amount=Decimal("12000.00"),
                    billing_cadence="monthly",
                    scope=[
                        {"service": "bookkeeping", "description": "Monthly bookkeeping and ledger review."},
                        {"service": "gst_accounting", "description": "Monthly GSTR-1 and 3B filings support."},
                        {"service": "bank_reconciliation", "description": "Two bank accounts reconciled each month."},
                    ],
                    line_items=[
                        {
                            "kind": "service",
                            "key": "bookkeeping",
                            "label": "Bookkeeping",
                            "description": "Monthly bookkeeping and ledger review.",
                            "service": "bookkeeping",
                            "amount": 72000.0,
                            "cadence": "annual",
                        },
                        {
                            "kind": "service",
                            "key": "gst_accounting",
                            "label": "GST accounting",
                            "description": "Monthly GSTR-1 and 3B filings support.",
                            "service": "gst_accounting",
                            "amount": 48000.0,
                            "cadence": "annual",
                        },
                        {
                            "kind": "service",
                            "key": "bank_reconciliation",
                            "label": "Bank reconciliation",
                            "description": "Two bank accounts reconciled each month.",
                            "service": "bank_reconciliation",
                            "amount": 24000.0,
                            "cadence": "annual",
                        },
                    ],
                    terms=DEFAULT_TERMS,
                    valid_until=today + timedelta(days=13),
                    validity_days=15,
                    status="sent",
                    annual_turnover=Decimal("20000000.00"),
                    benchmark_annual=Decimal("400000.00"),
                    subtotal_annual=Decimal("144000.00"),
                    total_annual=Decimal("144000.00"),
                    monthly_equivalent=Decimal("12000.00"),
                    discount_type="none",
                    discount_value=Decimal("0.00"),
                    discount_amount=Decimal("0.00"),
                    payment_frequency="monthly",
                    tax_rate_percent=Decimal("18.00"),
                    tax_note=DEFAULT_SETTINGS["tax_note"],
                    approved_at=utcnow() - timedelta(days=3),
                    approved_by_user_id=senior.id,
                    sent_at=utcnow() - timedelta(days=2),
                )
            )
    db.flush()


def seed_accounting_practice(db: Session) -> None:
    """Seed the accounting practice demo in an idempotent way."""
    ensure_pricing_seed(db)
    senior = _practice_user(
        db,
        email=settings.DEMO_SENIOR_ACCOUNTANT_EMAIL,
        password=settings.DEMO_SENIOR_ACCOUNTANT_PASSWORD,
        full_name=settings.DEMO_SENIOR_ACCOUNTANT_NAME,
        role="senior_accountant",
    )
    junior = _practice_user(
        db,
        email=settings.DEMO_JUNIOR_ACCOUNTANT_EMAIL,
        password=settings.DEMO_JUNIOR_ACCOUNTANT_PASSWORD,
        full_name=settings.DEMO_JUNIOR_ACCOUNTANT_NAME,
        role="junior_accountant",
    )
    client_user = _practice_user(
        db,
        email=settings.DEMO_CLIENT_EMAIL,
        password=settings.DEMO_CLIENT_PASSWORD,
        full_name=settings.DEMO_CLIENT_NAME,
        role="customer",
    )
    if senior is None or junior is None:
        db.commit()
        return
    if db.query(AccountingClient).count() > 0:
        _ensure_dn_ventures_client(db, senior, junior)
        _ensure_tally_history_demo(db, senior, junior)
        _ensure_demo_pricing_data(db, senior)
        db.commit()
        return

    today = date.today()
    fy = financial_year_for(today)
    month = today.replace(day=1)
    last_month = (month - timedelta(days=1)).replace(day=1)

    meridian = AccountingClient(
        code=f"ACC-{today.year}-001",
        business_name="Meridian Traders",
        contact_name=settings.DEMO_CLIENT_NAME,
        email=settings.DEMO_CLIENT_EMAIL.lower(),
        phone="+91 98200 11223",
        business_type="Private Limited",
        turnover_range="INR 1 crore - 5 crore",
        gst_status="Registered - regular",
        gstin="27AAECM1234A1Z5",
        pan_last4="234A",
        financial_year=fy,
        service_package="GST accounting + bookkeeping",
        status="active",
        customer_user_id=client_user.id if client_user else None,
        senior_accountant_user_id=senior.id,
        assigned_junior_user_id=junior.id,
        onboarded_at=utcnow() - timedelta(days=90),
        notes="Monthly GST working papers and sales/purchase register cleanup.",
    )
    sunrise = AccountingClient(
        code=f"ACC-{today.year}-002",
        business_name="Sunrise Interiors",
        contact_name="Neha Kulkarni",
        email="accounts@sunriseinteriors.example.com",
        phone="+91 90040 55667",
        business_type="Partnership",
        turnover_range="INR 20 lakh - 1 crore",
        gst_status="Registered - regular",
        gstin="27AABCS5678B1Z2",
        pan_last4="678B",
        financial_year=fy,
        service_package="Bookkeeping",
        status="active",
        senior_accountant_user_id=senior.id,
        assigned_junior_user_id=None,
        onboarded_at=utcnow() - timedelta(days=45),
        notes="Awaiting junior allocation.",
    )
    db.add_all([meridian, sunrise])
    db.flush()

    enquiry_new = AccountingEnquiry(
        reference=f"ACC-ENQ-{today.year}-0001",
        business_name="Nova Retail LLP",
        contact_name="Priya Nair",
        email="priya@novaretail.example.com",
        phone="+91 99870 44556",
        business_type="LLP",
        turnover_range="INR 20 lakh - 1 crore",
        gst_status="Registered - regular",
        services=["bookkeeping", "gst_accounting", "bank_reconciliation"],
        monthly_transactions=240,
        requirements="Two GSTINs in Maharashtra. Need monthly GSTR-1 and 3B working papers.",
        annual_turnover=Decimal("3500000.00"),
        bank_accounts=2,
        payroll_required=True,
        inventory_required=False,
        financial_year=fy,
        benchmark_annual=Decimal("70000.00"),
        status="new",
        source="website",
    )
    enquiry_quoted = AccountingEnquiry(
        reference=f"ACC-ENQ-{today.year}-0002",
        business_name="Coastal Foods",
        contact_name="Arun Shetty",
        email="arun@coastalfoods.example.com",
        business_type="Proprietorship",
        turnover_range="INR 1 crore - 5 crore",
        gst_status="Registered - composition",
        services=["bookkeeping", "gst_accounting", "financial_statements"],
        monthly_transactions=120,
        requirements="Composition dealer; needs quarterly statements and annual financials.",
        annual_turnover=Decimal("12000000.00"),
        bank_accounts=1,
        payroll_required=False,
        inventory_required=False,
        financial_year=fy,
        benchmark_annual=Decimal("240000.00"),
        status="quoted",
        assigned_senior_user_id=senior.id,
    )
    enquiry_draft = AccountingEnquiry(
        reference=f"ACC-ENQ-{today.year}-0003",
        business_name="Aster Diagnostics",
        contact_name="Dr. Kavita Rao",
        email="kavita@asterdiagnostics.example.com",
        phone="+91 98330 77112",
        business_type="Private Limited",
        turnover_range="INR 20 lakh - 1 crore",
        gst_status="Registered - regular",
        services=["bookkeeping", "gst_accounting", "financial_statements"],
        monthly_transactions=180,
        requirements="Diagnostic lab with monthly payroll and a stock register for consumables.",
        annual_turnover=Decimal("4800000.00"),
        bank_accounts=2,
        payroll_required=True,
        inventory_required=True,
        financial_year=fy,
        benchmark_annual=Decimal("96000.00"),
        status="contacted",
        source="website",
        assigned_senior_user_id=senior.id,
    )
    db.add_all([enquiry_new, enquiry_quoted, enquiry_draft])
    db.flush()

    coastal_lines = [
        {
            "kind": "service",
            "key": "bookkeeping",
            "label": "Bookkeeping",
            "description": "Monthly bookkeeping and ledger review.",
            "service": "bookkeeping",
            "amount": 60000.0,
            "cadence": "annual",
        },
        {
            "kind": "service",
            "key": "gst_accounting",
            "label": "GST accounting",
            "description": "Composition returns working papers.",
            "service": "gst_accounting",
            "amount": 60000.0,
            "cadence": "annual",
        },
        {
            "kind": "service",
            "key": "financial_statements",
            "label": "Financial statements",
            "description": "Quarterly draft financial statements.",
            "service": "financial_statements",
            "amount": 30000.0,
            "cadence": "annual",
        },
    ]
    coastal_quotation = AccountingQuotation(
        number=f"ACC-QT-{today.year}-0001",
        enquiry_id=enquiry_quoted.id,
        prepared_by_user_id=senior.id,
        amount=Decimal("12500.00"),
        billing_cadence="monthly",
        scope=[
            {"service": "bookkeeping", "description": "Monthly bookkeeping and ledger review."},
            {"service": "gst_accounting", "description": "Composition returns working papers."},
            {"service": "financial_statements", "description": "Quarterly draft financial statements."},
        ],
        line_items=coastal_lines,
        terms=DEFAULT_TERMS,
        valid_until=today + timedelta(days=21),
        validity_days=21,
        status="sent",
        annual_turnover=Decimal("12000000.00"),
        benchmark_annual=Decimal("240000.00"),
        subtotal_annual=Decimal("150000.00"),
        total_annual=Decimal("150000.00"),
        monthly_equivalent=Decimal("12500.00"),
        discount_type="none",
        discount_value=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        payment_frequency="monthly",
        tax_rate_percent=Decimal("18.00"),
        tax_note=DEFAULT_SETTINGS["tax_note"],
        approved_at=utcnow() - timedelta(days=4),
        approved_by_user_id=senior.id,
        sent_at=utcnow() - timedelta(days=3),
    )

    aster_lines = [
        {
            "kind": "service",
            "key": "bookkeeping",
            "label": "Bookkeeping",
            "description": "Monthly books, ledgers and reconciliations.",
            "service": "bookkeeping",
            "amount": 48000.0,
            "cadence": "annual",
        },
        {
            "kind": "service",
            "key": "gst_accounting",
            "label": "GST accounting",
            "description": "Monthly GSTR-1 and 3B working papers.",
            "service": "gst_accounting",
            "amount": 30000.0,
            "cadence": "annual",
        },
        {
            "kind": "service",
            "key": "financial_statements",
            "label": "Financial statements",
            "description": "Annual financial statements and schedules.",
            "service": "financial_statements",
            "amount": 18000.0,
            "cadence": "annual",
        },
    ]
    aster_draft = AccountingQuotation(
        number=f"ACC-QT-{today.year}-0002",
        enquiry_id=enquiry_draft.id,
        prepared_by_user_id=senior.id,
        amount=Decimal("24000.00"),
        billing_cadence="quarterly",
        scope=[
            {"service": "bookkeeping", "description": "Monthly books, ledgers and reconciliations."},
            {"service": "gst_accounting", "description": "Monthly GSTR-1 and 3B working papers."},
            {"service": "financial_statements", "description": "Annual financial statements and schedules."},
        ],
        line_items=aster_lines,
        terms=DEFAULT_TERMS,
        valid_until=today + timedelta(days=15),
        validity_days=15,
        status="draft",
        annual_turnover=Decimal("4800000.00"),
        benchmark_annual=Decimal("96000.00"),
        subtotal_annual=Decimal("96000.00"),
        total_annual=Decimal("96000.00"),
        monthly_equivalent=Decimal("8000.00"),
        discount_type="none",
        discount_value=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        payment_frequency="quarterly",
        tax_rate_percent=Decimal("18.00"),
        tax_note=DEFAULT_SETTINGS["tax_note"],
    )

    meridian_lines = [
        {
            "kind": "service",
            "key": "bookkeeping",
            "label": "Bookkeeping",
            "description": "Monthly bookkeeping and ledger review.",
            "service": "bookkeeping",
            "amount": 72000.0,
            "cadence": "annual",
        },
        {
            "kind": "service",
            "key": "gst_accounting",
            "label": "GST accounting",
            "description": "Monthly GSTR-1 and 3B filings support.",
            "service": "gst_accounting",
            "amount": 48000.0,
            "cadence": "annual",
        },
        {
            "kind": "service",
            "key": "bank_reconciliation",
            "label": "Bank reconciliation",
            "description": "Two bank accounts reconciled each month.",
            "service": "bank_reconciliation",
            "amount": 24000.0,
            "cadence": "annual",
        },
    ]
    meridian_quotation = AccountingQuotation(
        number=f"ACC-QT-{today.year}-0003",
        client_id=meridian.id,
        prepared_by_user_id=senior.id,
        amount=Decimal("12000.00"),
        billing_cadence="monthly",
        scope=[
            {"service": "bookkeeping", "description": "Monthly bookkeeping and ledger review."},
            {"service": "gst_accounting", "description": "Monthly GSTR-1 and 3B filings support."},
            {"service": "bank_reconciliation", "description": "Two bank accounts reconciled each month."},
        ],
        line_items=meridian_lines,
        terms=DEFAULT_TERMS,
        valid_until=today + timedelta(days=13),
        validity_days=15,
        status="sent",
        annual_turnover=Decimal("20000000.00"),
        benchmark_annual=Decimal("400000.00"),
        subtotal_annual=Decimal("144000.00"),
        total_annual=Decimal("144000.00"),
        monthly_equivalent=Decimal("12000.00"),
        discount_type="none",
        discount_value=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        payment_frequency="monthly",
        tax_rate_percent=Decimal("18.00"),
        tax_note=DEFAULT_SETTINGS["tax_note"],
        approved_at=utcnow() - timedelta(days=3),
        approved_by_user_id=senior.id,
        sent_at=utcnow() - timedelta(days=2),
    )

    sunrise_quotation = AccountingQuotation(
        number=f"ACC-QT-{today.year}-0004",
        client_id=sunrise.id,
        prepared_by_user_id=senior.id,
        amount=Decimal("5000.00"),
        billing_cadence="monthly",
        scope=[{"service": "bookkeeping", "description": "Monthly bookkeeping."}],
        line_items=[
            {
                "kind": "service",
                "key": "bookkeeping",
                "label": "Bookkeeping",
                "description": "Monthly bookkeeping.",
                "service": "bookkeeping",
                "amount": 60000.0,
                "cadence": "annual",
            }
        ],
        terms=DEFAULT_TERMS,
        valid_until=today + timedelta(days=10),
        validity_days=15,
        status="accepted",
        annual_turnover=Decimal("8000000.00"),
        benchmark_annual=Decimal("160000.00"),
        subtotal_annual=Decimal("60000.00"),
        total_annual=Decimal("60000.00"),
        monthly_equivalent=Decimal("5000.00"),
        discount_type="none",
        discount_value=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        payment_frequency="monthly",
        tax_rate_percent=Decimal("18.00"),
        tax_note=DEFAULT_SETTINGS["tax_note"],
        approved_at=utcnow() - timedelta(days=12),
        approved_by_user_id=senior.id,
        sent_at=utcnow() - timedelta(days=10),
        accepted_at=utcnow() - timedelta(days=5),
        responded_at=utcnow() - timedelta(days=5),
        response_note="Accepted by the client over email.",
    )
    db.add_all([coastal_quotation, aster_draft, meridian_quotation, sunrise_quotation])
    db.flush()

    tasks = [
        AccountingTask(
            client_id=meridian.id,
            title="Bank reconciliation - current month",
            description="Import the bank statement and confirm suggested matches.",
            service_type="bank_reconciliation",
            status="in_progress",
            priority="high",
            due_date=today + timedelta(days=2),
            assigned_to_user_id=junior.id,
            created_by_user_id=senior.id,
            progress=55,
        ),
        AccountingTask(
            client_id=meridian.id,
            title="GSTR-1 working paper",
            description="Prepare the outward supply working paper from the sales register.",
            service_type="gst_accounting",
            status="submitted",
            priority="high",
            due_date=today - timedelta(days=1),
            assigned_to_user_id=junior.id,
            created_by_user_id=senior.id,
            progress=100,
            submitted_at=utcnow() - timedelta(hours=6),
        ),
        AccountingTask(
            client_id=meridian.id,
            title="Purchase register cleanup",
            description="Remove duplicate purchase vouchers and confirm supplier GSTINs.",
            service_type="sales_purchase",
            status="changes_requested",
            priority="normal",
            due_date=today + timedelta(days=4),
            assigned_to_user_id=junior.id,
            created_by_user_id=senior.id,
            progress=70,
            review_notes="Two supplier vouchers are missing GSTINs. Fix before resubmitting.",
            reviewed_by_user_id=senior.id,
            reviewed_at=utcnow() - timedelta(days=1),
        ),
        AccountingTask(
            client_id=meridian.id,
            title="Monthly book close",
            description="Close the books for the previous month and attach the trial balance.",
            service_type="bookkeeping",
            status="approved",
            priority="normal",
            due_date=today - timedelta(days=3),
            assigned_to_user_id=junior.id,
            created_by_user_id=senior.id,
            progress=100,
            submitted_at=utcnow() - timedelta(days=4),
            reviewed_by_user_id=senior.id,
            reviewed_at=utcnow() - timedelta(days=3),
            review_notes="Reviewed against the bank statement. Approved.",
        ),
        AccountingTask(
            client_id=sunrise.id,
            title="Opening ledger setup",
            description="Set up the opening balances and allocate the engagement to a junior accountant.",
            service_type="bookkeeping",
            status="unassigned",
            priority="normal",
            due_date=today + timedelta(days=6),
            created_by_user_id=senior.id,
        ),
    ]
    db.add_all(tasks)
    db.flush()

    previous_month = last_month
    _practice_voucher(
        db, meridian,
        voucher_type="sale", number=f"MT-S-{last_month:%Y%m}-01",
        voucher_date=previous_month + timedelta(days=6),
        party_name="Vertex Interiors", party_gstin="27AABCV1111C1Z9",
        ledger_name="Sales - furniture", category="Furniture sales",
        taxable_value=Decimal("85000.00"), gst_rate=Decimal("18.00"),
        inter_state=False, created_by=junior,
    )
    _practice_voucher(
        db, meridian,
        voucher_type="purchase", number=f"MT-P-{last_month:%Y%m}-01",
        voucher_date=previous_month + timedelta(days=9),
        party_name="Ergo Wholesale", party_gstin="27AABCE2222D1Z7",
        ledger_name="Purchases - stock", category="Inventory purchases",
        taxable_value=Decimal("32000.00"), gst_rate=Decimal("18.00"),
        inter_state=False, created_by=junior,
    )
    current_sale = _practice_voucher(
        db, meridian,
        voucher_type="sale", number=f"MT-S-{month:%Y%m}-01",
        voucher_date=month + timedelta(days=1),
        party_name="Vertex Interiors", party_gstin="27AABCV1111C1Z9",
        ledger_name="Sales - furniture", category="Furniture sales",
        taxable_value=Decimal("100000.00"), gst_rate=Decimal("18.00"),
        inter_state=False, created_by=junior,
    )
    _practice_voucher(
        db, meridian,
        voucher_type="sale", number=f"MT-S-{month:%Y%m}-02",
        voucher_date=month + timedelta(days=2),
        party_name="Northern Retail", party_gstin="07AABCN3333E1Z4",
        ledger_name="Sales - furniture", category="Furniture sales",
        taxable_value=Decimal("45000.00"), gst_rate=Decimal("18.00"),
        inter_state=True, created_by=junior,
    )
    current_purchase = _practice_voucher(
        db, meridian,
        voucher_type="purchase", number=f"MT-P-{month:%Y%m}-01",
        voucher_date=month + timedelta(days=2),
        party_name="Ergo Wholesale", party_gstin="27AABCE2222D1Z7",
        ledger_name="Purchases - stock", category="Inventory purchases",
        taxable_value=Decimal("12000.00"), gst_rate=Decimal("18.00"),
        inter_state=False, created_by=junior,
    )
    _practice_voucher(
        db, sunrise,
        voucher_type="sale", number=f"SI-S-{month:%Y%m}-01",
        voucher_date=month + timedelta(days=3),
        party_name="Walk-in customer", party_gstin=None,
        ledger_name="Sales - interiors", category="Interior projects",
        taxable_value=Decimal("50000.00"), gst_rate=Decimal("18.00"),
        inter_state=False, created_by=senior,
    )
    _practice_voucher(
        db, meridian,
        voucher_type="receipt", number=f"MT-R-{month:%Y%m}-01",
        voucher_date=month + timedelta(days=6),
        party_name="Vertex Interiors", party_gstin="27AABCV1111C1Z9",
        ledger_name="HDFC Bank - Current", bank_ledger="HDFC Bank - Current",
        category="Receivable receipt", taxable_value=Decimal("60000.00"),
        gst_rate=Decimal("0.00"), inter_state=False, created_by=junior,
        description="Part receipt against MT-S invoice from Vertex Interiors",
    )
    _practice_voucher(
        db, meridian,
        voucher_type="payment", number=f"MT-PAY-{month:%Y%m}-01",
        voucher_date=month + timedelta(days=7),
        party_name="Ergo Wholesale", party_gstin="27AABCE2222D1Z7",
        ledger_name="HDFC Bank - Current", bank_ledger="HDFC Bank - Current",
        category="Supplier payment", taxable_value=Decimal("12000.00"),
        gst_rate=Decimal("0.00"), inter_state=False, created_by=junior,
        description="Payment against MT-P purchase from Ergo Wholesale",
    )
    _practice_voucher(
        db, meridian,
        voucher_type="expense", number=f"MT-E-{month:%Y%m}-01",
        voucher_date=month + timedelta(days=4),
        party_name="Office Solutions", party_gstin=None,
        ledger_name="Office rent", bank_ledger="HDFC Bank - Current",
        category="Rent", taxable_value=Decimal("18000.00"),
        gst_rate=Decimal("0.00"), inter_state=False, created_by=junior,
        description="Monthly office rent paid by bank transfer",
    )

    db.add_all(
        [
            AccountingStockItem(
                client_id=meridian.id, name="LiftDesk Pro", sku="FP-LDP-01", unit="Nos",
                hsn_sac="9403", gst_rate=Decimal("18.00"),
                opening_qty=Decimal("12.000"), opening_rate=Decimal("18500.00"),
                created_by_user_id=senior.id,
            ),
            AccountingStockItem(
                client_id=meridian.id, name="Ergo Chair", sku="FP-EC-02", unit="Nos",
                hsn_sac="9401", gst_rate=Decimal("18.00"),
                opening_qty=Decimal("30.000"), opening_rate=Decimal("4200.00"),
                created_by_user_id=senior.id,
            ),
            AccountingStockItem(
                client_id=meridian.id, name="Storage Unit", sku="FP-SU-03", unit="Nos",
                hsn_sac="9403", gst_rate=Decimal("18.00"),
                opening_qty=Decimal("18.000"), opening_rate=Decimal("6300.00"),
                created_by_user_id=junior.id,
            ),
            AccountingStockItem(
                client_id=sunrise.id, name="Modular Sofa", sku="SI-MS-01", unit="Nos",
                hsn_sac="9401", gst_rate=Decimal("18.00"),
                opening_qty=Decimal("5.000"), opening_rate=Decimal("32000.00"),
                created_by_user_id=senior.id,
            ),
        ]
    )
    db.flush()

    invoice_one = AccountingInvoice(
        client_id=meridian.id,
        number=f"ACC-INV-{today.year}-0001",
        issue_date=today - timedelta(days=25),
        due_date=today + timedelta(days=5),
        period_label=f"{today:%B %Y}",
        subtotal=Decimal("15000.00"),
        tax_amount=Decimal("2700.00"),
        total_amount=Decimal("17700.00"),
        status="part_paid",
        notes="Monthly accounting retainer.",
        created_by_user_id=senior.id,
    )
    invoice_two = AccountingInvoice(
        client_id=sunrise.id,
        number=f"ACC-INV-{today.year}-0002",
        issue_date=today - timedelta(days=40),
        due_date=today - timedelta(days=10),
        period_label=f"{last_month:%B %Y}",
        subtotal=Decimal("7500.00"),
        tax_amount=Decimal("1350.00"),
        total_amount=Decimal("8850.00"),
        status="paid",
        notes="Bookkeeping retainer.",
        created_by_user_id=senior.id,
    )
    db.add_all([invoice_one, invoice_two])
    db.flush()
    db.add_all(
        [
            AccountingInvoicePayment(
                invoice_id=invoice_one.id,
                amount=Decimal("10000.00"),
                method="bank",
                reference="NEFT-889201",
                received_on=today - timedelta(days=10),
                recorded_by_user_id=senior.id,
            ),
            AccountingInvoicePayment(
                invoice_id=invoice_two.id,
                amount=Decimal("8850.00"),
                method="upi",
                reference="UPI-771200",
                received_on=today - timedelta(days=12),
                recorded_by_user_id=senior.id,
            ),
        ]
    )

    document_request = AccountingDocumentRequest(
        client_id=meridian.id,
        requested_by_user_id=junior.id,
        title="Purchase bills for the current month",
        description="Please upload the supplier purchase bills so the purchase register can be completed.",
        due_date=today + timedelta(days=5),
        status="pending",
    )
    db.add(document_request)
    db.add_all(
        [
            AccountingMessage(
                client_id=meridian.id,
                author_user_id=client_user.id if client_user else None,
                author_label=settings.DEMO_CLIENT_NAME,
                author_role="customer",
                body="Please share the document checklist for this month's GST filing.",
            ),
            AccountingMessage(
                client_id=meridian.id,
                author_user_id=junior.id,
                author_label=settings.DEMO_JUNIOR_ACCOUNTANT_NAME,
                author_role="junior_accountant",
                body="I have requested the purchase bills. Once uploaded I will finish reconciliation and submit for review.",
            ),
        ]
    )

    bank_import = AccountingBankImport(
        client_id=meridian.id,
        imported_by_user_id=junior.id,
        filename="meridian-bank-statement.csv",
        row_count=3,
        matched_count=0,
        status="imported",
    )
    db.add(bank_import)
    db.flush()
    db.add_all(
        [
            AccountingBankTransaction(
                import_id=bank_import.id,
                client_id=meridian.id,
                txn_date=month + timedelta(days=1),
                description="NEFT CR VERTEX INTERIORS",
                reference="NEFT-771200",
                credit=current_sale.total_amount,
                status="unmatched",
                match_score=90,
                match_note=f"Amount matches sale voucher {current_sale.number}.",
            ),
            AccountingBankTransaction(
                import_id=bank_import.id,
                client_id=meridian.id,
                txn_date=month + timedelta(days=2),
                description="UPI DR ERGO WHOLESALE",
                reference="UPI-441122",
                debit=current_purchase.total_amount,
                status="unmatched",
                match_score=90,
                match_note=f"Amount matches purchase voucher {current_purchase.number}.",
            ),
            AccountingBankTransaction(
                import_id=bank_import.id,
                client_id=meridian.id,
                txn_date=month + timedelta(days=3),
                description="IMPS CR NORTHERN RETAIL",
                reference="IMPS-900112",
                credit=Decimal("50000.00"),
                status="unmatched",
                match_score=40,
                match_note="No voucher matches this amount exactly.",
            ),
        ]
    )

    if client_user is not None:
        db.add(
            AccountingNotification(
                user_id=client_user.id,
                client_id=meridian.id,
                kind="document_request",
                title="Document requested",
                body="Purchase bills for the current month were requested.",
            )
        )
        db.add(
            AccountingNotification(
                user_id=junior.id,
                client_id=meridian.id,
                kind="task_assigned",
                title="Task assigned",
                body="Bank reconciliation - current month was assigned to you.",
            )
        )
    log_audit(
        db,
        user_id=senior.id,
        actor=senior.email,
        action="accounting.client_created",
        entity_type="accounting_client",
        entity_id=meridian.id,
        detail={"client_id": meridian.id, "code": meridian.code, "seeded": True},
    )
    log_audit(
        db,
        user_id=senior.id,
        actor=senior.email,
        action="accounting.client_created",
        entity_type="accounting_client",
        entity_id=sunrise.id,
        detail={"client_id": sunrise.id, "code": sunrise.code, "seeded": True},
    )
    log_audit(
        db,
        user_id=senior.id,
        actor=senior.email,
        action="accounting.quotation_drafted",
        entity_type="accounting_quotation",
        entity_id=aster_draft.id,
        detail={"quotation_id": aster_draft.id, "enquiry_id": enquiry_draft.id, "seeded": True},
    )
    log_audit(
        db,
        user_id=senior.id,
        actor=senior.email,
        action="accounting.quotation_approved",
        entity_type="accounting_quotation",
        entity_id=coastal_quotation.id,
        detail={"quotation_id": coastal_quotation.id, "seeded": True},
    )
    log_audit(
        db,
        user_id=senior.id,
        actor=senior.email,
        action="accounting.quotation_sent",
        entity_type="accounting_quotation",
        entity_id=coastal_quotation.id,
        detail={"quotation_id": coastal_quotation.id, "seeded": True},
    )
    log_audit(
        db,
        user_id=senior.id,
        actor=senior.email,
        action="accounting.quotation_sent",
        entity_type="accounting_quotation",
        entity_id=meridian_quotation.id,
        detail={"quotation_id": meridian_quotation.id, "seeded": True},
    )
    log_audit(
        db,
        user_id=senior.id,
        actor=senior.email,
        action="accounting.quotation_accepted",
        entity_type="accounting_quotation",
        entity_id=sunrise_quotation.id,
        detail={"quotation_id": sunrise_quotation.id, "seeded": True, "payment_triggered": False},
    )
    log_audit(
        db,
        user_id=senior.id,
        actor=senior.email,
        action="accounting.task_assigned",
        entity_type="accounting_task",
        entity_id=tasks[0].id,
        detail={"client_id": meridian.id, "task_id": tasks[0].id, "seeded": True},
    )
    _ensure_dn_ventures_client(db, senior, junior)
    _ensure_tally_history_demo(db, senior, junior)
    db.commit()
