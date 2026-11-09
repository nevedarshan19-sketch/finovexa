from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy.orm import Session

from ..models import GSTRate, User
from .finance import q2

RUPEE = Decimal("1")
DEFAULT_GST_RATES: tuple[tuple[str, str], ...] = (
    ("0", "0% — Nil rated / exempt"),
    ("5", "5%"),
    ("12", "12%"),
    ("18", "18%"),
    ("28", "28%"),
)

# Official GST state codes. Businesses must confirm the classification that applies to them.
INDIAN_STATES: tuple[tuple[str, str], ...] = (
    ("01", "Jammu and Kashmir"),
    ("02", "Himachal Pradesh"),
    ("03", "Punjab"),
    ("04", "Chandigarh"),
    ("05", "Uttarakhand"),
    ("06", "Haryana"),
    ("07", "Delhi"),
    ("08", "Rajasthan"),
    ("09", "Uttar Pradesh"),
    ("10", "Bihar"),
    ("11", "Sikkim"),
    ("12", "Arunachal Pradesh"),
    ("13", "Nagaland"),
    ("14", "Manipur"),
    ("15", "Mizoram"),
    ("16", "Tripura"),
    ("17", "Meghalaya"),
    ("18", "Assam"),
    ("19", "West Bengal"),
    ("20", "Jharkhand"),
    ("21", "Odisha"),
    ("22", "Chhattisgarh"),
    ("23", "Madhya Pradesh"),
    ("24", "Gujarat"),
    ("26", "Dadra and Nagar Haveli and Daman and Diu"),
    ("27", "Maharashtra"),
    ("29", "Karnataka"),
    ("30", "Goa"),
    ("31", "Lakshadweep"),
    ("32", "Kerala"),
    ("33", "Tamil Nadu"),
    ("34", "Puducherry"),
    ("35", "Andaman and Nicobar Islands"),
    ("36", "Telangana"),
    ("37", "Andhra Pradesh"),
    ("38", "Ladakh"),
    ("97", "Other Territory"),
    ("99", "Centre Jurisdiction"),
)

STATE_NAME_BY_CODE = dict(INDIAN_STATES)
STATE_CODE_BY_NAME = {name.lower(): code for code, name in INDIAN_STATES}
GSTIN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class GSTValidationError(ValueError):
    """Raised when a GST input cannot be safely calculated or classified."""


@dataclass(frozen=True)
class LineInput:
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    gst_rate: Decimal
    pricing_mode: str = "exclusive"


def state_name(code: str | None) -> str | None:
    if not code:
        return None
    return STATE_NAME_BY_CODE.get(str(code).zfill(2))


def state_code(name: str | None) -> str | None:
    if not name:
        return None
    return STATE_CODE_BY_NAME.get(name.strip().lower())


def normalize_state(name: str | None, code: str | None) -> tuple[str | None, str | None]:
    normalized_code = (str(code).zfill(2) if code else None) or state_code(name)
    if normalized_code is not None and normalized_code not in STATE_NAME_BY_CODE:
        raise GSTValidationError(
            f"State code {normalized_code} is not a recognised GST state code. Verify the supplier or place of supply."
        )
    normalized_name = STATE_NAME_BY_CODE.get(normalized_code) if normalized_code else name
    return normalized_name, normalized_code


def _gstin_checksum(base: str) -> str:
    total = 0
    for index, char in enumerate(base):
        value = GSTIN_ALPHABET.index(char)
        factor = 1 if index % 2 == 0 else 2
        product = value * factor
        total += product // 36 + product % 36
    return GSTIN_ALPHABET[(36 - total % 36) % 36]


def normalize_gstin(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = "".join(value.split()).upper()
    if not candidate:
        return None
    if len(candidate) != 15:
        raise GSTValidationError("GSTIN must be exactly 15 characters.")
    if candidate[:2] not in STATE_NAME_BY_CODE:
        raise GSTValidationError("GSTIN must begin with a valid GST state code.")
    if not candidate.isalnum():
        raise GSTValidationError("GSTIN can only contain letters and digits.")
    if _gstin_checksum(candidate[:14]) != candidate[14]:
        raise GSTValidationError(
            "GSTIN checksum is invalid. Check the number on the registration certificate; do not guess it."
        )
    return candidate


def normalize_rate(value: Decimal | int | float | str | None) -> Decimal:
    try:
        rate = Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, ValueError) as exc:
        raise GSTValidationError("GST rate must be a number.") from exc
    rate = rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rate < 0 or rate > 100:
        raise GSTValidationError("GST rate must be between 0 and 100 percent.")
    return rate


def ensure_default_gst_rates(db: Session, user: User) -> list[GSTRate]:
    rows = db.query(GSTRate).filter(GSTRate.user_id == user.id).order_by(GSTRate.sort_order).all()
    if rows:
        return rows
    rows = [
        GSTRate(
            user_id=user.id,
            rate=Decimal(rate),
            label=label,
            is_active=True,
            is_custom=False,
            sort_order=index,
        )
        for index, (rate, label) in enumerate(DEFAULT_GST_RATES)
    ]
    db.add_all(rows)
    db.flush()
    return rows


def validate_configured_rate(db: Session, user: User, rate: Decimal) -> Decimal:
    rate = normalize_rate(rate)
    active = {
        row.rate
        for row in ensure_default_gst_rates(db, user)
        if row.is_active
    }
    if rate not in active:
        raise GSTValidationError(
            f"GST rate {rate}% is not in the configured rate list. Add it in GST settings only "
            "after confirming it applies to this supply."
        )
    return rate


def resolve_supply_type(supplier_state_code: str, place_of_supply_state_code: str) -> str:
    supplier = (supplier_state_code or "").zfill(2)
    place = (place_of_supply_state_code or "").zfill(2)
    if supplier not in STATE_NAME_BY_CODE:
        raise GSTValidationError("Supplier state is missing or invalid. Set it in GST settings.")
    if place not in STATE_NAME_BY_CODE:
        raise GSTValidationError(
            "Place of supply is missing or invalid. Confirm the customer's state before issuing this invoice."
        )
    return "intra_state" if supplier == place else "inter_state"


SUPPLY_UNVERIFIED = "unverified"


def tax_split(gst_amount: Decimal, supply_type: str) -> tuple[Decimal, Decimal, Decimal]:
    if supply_type == "intra_state":
        cgst = q2(gst_amount / 2)
        sgst = q2(gst_amount - cgst)
        return cgst, sgst, Decimal("0.00")
    if supply_type == "inter_state":
        return Decimal("0.00"), Decimal("0.00"), q2(gst_amount)
    raise GSTValidationError("Supply type must be intra_state or inter_state.")


def line_calculation(line: LineInput, supply_type: str) -> dict:
    quantity = Decimal(str(line.quantity))
    unit_price = Decimal(str(line.unit_price))
    discount = Decimal(str(line.discount or 0))
    rate = normalize_rate(line.gst_rate)
    pricing_mode = line.pricing_mode or "exclusive"
    if quantity <= 0:
        raise GSTValidationError("Quantity must be greater than zero.")
    if unit_price < 0:
        raise GSTValidationError("Unit price cannot be negative.")
    if discount < 0:
        raise GSTValidationError("Discount cannot be negative.")
    if pricing_mode not in ("exclusive", "inclusive"):
        raise GSTValidationError("Pricing mode must be exclusive or inclusive.")

    gross = q2(quantity * unit_price)
    if discount > gross:
        raise GSTValidationError(
            f"Discount {discount} cannot exceed the line value {gross}."
        )

    if pricing_mode == "inclusive":
        net_inclusive = q2(gross - discount)
        taxable = q2(net_inclusive / (Decimal("1") + rate / Decimal("100")))
        gst = q2(net_inclusive - taxable)
        final = net_inclusive
    else:
        taxable = q2(gross - discount)
        gst = q2(taxable * rate / Decimal("100"))
        final = q2(taxable + gst)

    cgst, sgst, igst = tax_split(gst, supply_type)
    return {
        "quantity": quantity,
        "unit_price": q2(unit_price),
        "gross_amount": gross,
        "discount": q2(discount),
        "taxable_value": taxable,
        "gst_rate": rate,
        "gst_amount": gst,
        "cgst_amount": cgst,
        "sgst_amount": sgst,
        "igst_amount": igst,
        "final_amount": q2(final),
        "pricing_mode": pricing_mode,
    }


def invoice_totals(
    lines: list[LineInput],
    *,
    supply_type: str,
    other_charges: Decimal | int | float | str = "0",
    round_to_rupee: bool = True,
) -> dict:
    if not lines:
        raise GSTValidationError("An invoice needs at least one line item.")
    if supply_type not in ("intra_state", "inter_state"):
        raise GSTValidationError("Supply type must be resolved before calculating totals.")
    calculated = [line_calculation(line, supply_type) for line in lines]
    subtotal = q2(sum((row["gross_amount"] for row in calculated), Decimal("0.00")))
    discount = q2(sum((row["discount"] for row in calculated), Decimal("0.00")))
    taxable = q2(sum((row["taxable_value"] for row in calculated), Decimal("0.00")))
    cgst = q2(sum((row["cgst_amount"] for row in calculated), Decimal("0.00")))
    sgst = q2(sum((row["sgst_amount"] for row in calculated), Decimal("0.00")))
    igst = q2(sum((row["igst_amount"] for row in calculated), Decimal("0.00")))
    tax = q2(cgst + sgst + igst)
    other = q2(other_charges)
    if other < 0:
        raise GSTValidationError("Other charges cannot be negative.")
    raw_total = q2(taxable + tax + other)
    if round_to_rupee:
        total = q2(raw_total.quantize(RUPEE, rounding=ROUND_HALF_UP))
        rounding = q2(total - raw_total)
    else:
        total = raw_total
        rounding = Decimal("0.00")
    if q2(taxable + tax + other + rounding) != total:
        raise GSTValidationError("Totals did not reconcile. No invoice was saved.")
    if q2(cgst + sgst + igst) != tax:
        raise GSTValidationError("Tax components did not reconcile. No invoice was saved.")
    if supply_type == "intra_state" and igst != 0:
        raise GSTValidationError("An intra-state invoice cannot carry IGST.")
    if supply_type == "inter_state" and (cgst != 0 or sgst != 0):
        raise GSTValidationError("An inter-state invoice cannot carry CGST or SGST.")
    return {
        "lines": calculated,
        "subtotal": subtotal,
        "discount": discount,
        "taxable_value": taxable,
        "cgst_amount": cgst,
        "sgst_amount": sgst,
        "igst_amount": igst,
        "tax_amount": tax,
        "other_charges": other,
        "rounding_adjustment": rounding,
        "raw_total": raw_total,
        "total_amount": total,
        "round_to_rupee": bool(round_to_rupee),
        "supply_type": supply_type,
    }


def state_options() -> list[dict]:
    return [{"code": code, "name": name} for code, name in INDIAN_STATES]
