from __future__ import annotations

import base64
import io
from datetime import date
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.utils import ImageReader
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Invoice, Payment
from .finance import (
    money_text,
    payment_method_label,
    payment_state,
    payment_status_label,
    q2,
    supply_type_label,
)


def _address_lines(invoice: Invoice, customer: bool = False) -> list[str]:
    if customer:
        raw = invoice.customer_address
        name = invoice.customer_name or invoice.customer.name
        gstin = invoice.customer_gstin or invoice.customer.gstin
        state = invoice.customer_state or invoice.customer.state
        phone = invoice.customer_phone or invoice.customer.phone
        email = invoice.customer.email
    else:
        raw = invoice.supplier_address
        name = invoice.supplier_name or ""
        gstin = invoice.supplier_gstin
        state = invoice.supplier_state
        phone = None
        email = None
    lines = [name] if name else []
    if raw:
        lines.extend(part.strip() for part in raw.splitlines() if part.strip())
    if state and state not in " ".join(lines):
        lines.append(state)
    if gstin:
        lines.append(f"GSTIN: {gstin}")
    if phone:
        lines.append(f"Mobile: {phone}")
    if email:
        lines.append(email)
    return lines


def _logo(value: str | None) -> Image | None:
    if not value or "," not in value:
        return None
    try:
        payload = base64.b64decode(value.split(",", 1)[1])
        image = ImageReader(io.BytesIO(payload))
        width, height = image.getSize()
        max_w, max_h = 42 * mm, 18 * mm
        scale = min(max_w / width, max_h / height, 1)
        return Image(io.BytesIO(payload), width=width * scale, height=height * scale)
    except Exception:
        return None


def build_invoice_pdf(
    db: Session, invoice: Invoice, *, logo_data_url: str | None = None
) -> bytes:
    buffer = io.BytesIO()
    title = "TAX INVOICE" if invoice.supplier_gstin else "INVOICE"
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=18 * mm,
        title=f"{title} {invoice.number}",
        author="FINOVEXA AI",
        subject=f"Invoice {invoice.number}",
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "InvoiceBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.2, leading=10.5
    )
    small = ParagraphStyle(
        "InvoiceSmall", parent=body, fontSize=7.2, leading=9, textColor=colors.HexColor("#475569")
    )
    right = ParagraphStyle("InvoiceRight", parent=body, alignment=TA_RIGHT)
    right_small = ParagraphStyle("InvoiceRightSmall", parent=small, alignment=TA_RIGHT)
    heading = ParagraphStyle(
        "InvoiceHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        alignment=TA_RIGHT,
        textColor=colors.HexColor("#0f172a"),
    )
    section = ParagraphStyle(
        "InvoiceSection",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=2,
    )

    paid = q2(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.invoice_id == invoice.id, Payment.status == "confirmed")
        .scalar()
    )
    outstanding = q2(max(invoice.total_amount - paid, Decimal("0.00")))
    payments = (
        db.query(Payment)
        .filter(Payment.invoice_id == invoice.id, Payment.status == "confirmed")
        .order_by(
            func.coalesce(Payment.received_at, Payment.created_at).desc(), Payment.id.desc()
        )
        .all()
    )
    last_payment = payments[0] if payments else None
    state = payment_state(invoice, paid)
    currency = invoice.currency or "INR"
    story: list = []

    supplier_lines = _address_lines(invoice)
    logo = _logo(logo_data_url)
    header_left: list = []
    if logo is not None:
        header_left.append(logo)
        header_left.append(Spacer(1, 2 * mm))
    if supplier_lines:
        header_left.append(Paragraph(f"<b>{supplier_lines[0]}</b>", body))
        for line in supplier_lines[1:]:
            header_left.append(Paragraph(line, small))
    else:
        header_left.append(Paragraph(invoice.supplier_name or "Business", body))
    header_right = [
        Paragraph(title, heading),
        Paragraph(f"Invoice <b>{invoice.number}</b>", right),
        Paragraph(f"Invoice date: {invoice.issue_date:%d %b %Y}", right_small),
        Paragraph(f"Due date: {invoice.due_date:%d %b %Y}", right_small),
        Paragraph(f"Payment status: {payment_status_label(state)}", right_small),
    ]
    header = Table([[header_left, header_right]], colWidths=[100 * mm, 78 * mm])
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(header)
    story.append(Spacer(1, 5 * mm))

    bill_to = [Paragraph("BILL TO", section), Paragraph(invoice.customer_name or invoice.customer.name, body)]
    bill_lines = _address_lines(invoice, customer=True)[1:]
    for line in bill_lines:
        bill_to.append(Paragraph(line, small))
    supply = [
        Paragraph("SUPPLY DETAILS", section),
        Paragraph(
            f"Supplier state: {invoice.supplier_state or '—'} ({invoice.supplier_state_code or '—'})",
            small,
        ),
        Paragraph(
            f"Place of supply: {invoice.place_of_supply_state or '—'} "
            f"({invoice.place_of_supply_state_code or '—'})",
            small,
        ),
        Paragraph(
            supply_type_label(invoice.supply_type),
            small,
        ),
        Paragraph(
            f"Pricing: {'GST inclusive' if invoice.pricing_mode == 'inclusive' else 'GST exclusive'}",
            small,
        ),
    ]
    blocks = Table([[bill_to, supply]], colWidths=[89 * mm, 89 * mm])
    blocks.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(blocks)
    story.append(Spacer(1, 4 * mm))

    head = [
        "#",
        "Description",
        "HSN/SAC",
        "Qty",
        "Rate",
        "Disc.",
        "Taxable",
        "GST",
        "Amount",
    ]
    rows: list[list] = [head]
    for index, item in enumerate(invoice.items, start=1):
        description = [Paragraph(f"<b>{item.name or item.description}</b>", body)]
        if item.description and item.description != (item.name or ""):
            description.append(Paragraph(item.description, small))
        if item.item_type == "services":
            description.append(Paragraph("Service", small))
        rows.append(
            [
                str(index),
                description,
                item.hsn_sac or "—",
                f"{Decimal(item.quantity):g} {item.unit or ''}".strip(),
                money_text(item.unit_price, currency),
                money_text(item.discount_amount, currency) if item.discount_amount else "—",
                money_text(item.taxable_value, currency),
                f"{Decimal(item.gst_rate):g}% · {money_text(item.gst_amount, currency)}",
                money_text(item.final_amount, currency),
            ]
        )
    widths = [7 * mm, 54 * mm, 16 * mm, 15 * mm, 21 * mm, 16 * mm, 21 * mm, 27 * mm, 23 * mm]
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 7.4),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 7.2),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 4 * mm))

    totals_rows: list[list] = [
        ["Subtotal (before discount)", money_text(invoice.subtotal_amount, currency)],
        ["Discounts", money_text(invoice.discount_amount, currency)],
        ["Taxable value", money_text(invoice.taxable_amount, currency)],
    ]
    if invoice.supply_type == "intra_state":
        totals_rows.extend(
            [
                ["CGST", money_text(invoice.cgst_amount, currency)],
                ["SGST", money_text(invoice.sgst_amount, currency)],
            ]
        )
    elif invoice.supply_type == "inter_state":
        totals_rows.append(["IGST", money_text(invoice.igst_amount, currency)])
    else:
        totals_rows.append(
            ["GST (classification not verified)", money_text(invoice.tax_amount, currency)]
        )
    totals_rows.extend(
        [
            ["Other charges", money_text(invoice.other_charges, currency)],
            ["Rounding adjustment", money_text(invoice.rounding_adjustment, currency)],
            ["Total", money_text(invoice.total_amount, currency)],
            ["Amount paid", money_text(paid, currency)],
            ["Outstanding balance", money_text(outstanding, currency)],
        ]
    )
    totals = Table(totals_rows, colWidths=[52 * mm, 38 * mm], hAlign="RIGHT")
    totals.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 7.8),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, 2), (-1, 2), 0.4, colors.HexColor("#cbd5e1")),
                ("LINEABOVE", (0, -2), (-1, -2), 0.6, colors.HexColor("#94a3b8")),
                ("FONTNAME", (0, -2), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -2), (-1, -1), colors.HexColor("#f1f5f9")),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(totals)
    story.append(Spacer(1, 5 * mm))

    payment_rows: list[list] = [
        ["Total invoice amount", money_text(invoice.total_amount, currency)],
        ["Amount received", money_text(paid, currency)],
        ["Remaining balance", money_text(outstanding, currency)],
        ["Payment status", payment_status_label(state)],
        ["Payment mode", payment_method_label(last_payment.method) if last_payment else "Not paid"],
        [
            "Payment date",
            (
                (last_payment.received_at or last_payment.created_at).strftime("%d %b %Y")
                if last_payment
                else "—"
            ),
        ],
    ]
    if last_payment and last_payment.provider_ref:
        payment_rows.append(["Transaction reference", last_payment.provider_ref])
    if len(payments) > 1:
        payment_rows.append(["Payments recorded", f"{len(payments)} instalments"])
    payment_table = Table(
        [[Paragraph("PAYMENT RECEIVED", section), ""]] + payment_rows,
        colWidths=[52 * mm, 38 * mm],
        hAlign="RIGHT",
    )
    payment_table.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (-1, 0)),
                ("FONTSIZE", (0, 0), (-1, -1), 7.8),
                ("FONTNAME", (0, 1), (0, -1), "Helvetica"),
                ("FONTNAME", (1, 1), (1, -1), "Helvetica-Bold"),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8fafc")),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(payment_table)
    story.append(Spacer(1, 5 * mm))

    notes: list = []
    if invoice.notes:
        notes.append(Paragraph("NOTES", section))
        notes.append(Paragraph(invoice.notes, small))
    terms = invoice.terms
    if terms:
        notes.append(Paragraph("TERMS &amp; DECLARATIONS", section))
        notes.append(Paragraph(terms.replace("\n", "<br/>"), small))
    if notes:
        story.append(Table([[notes]], colWidths=[178 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(
        Paragraph(
            "Payment status is based on confirmed payments recorded in FINOVEXA. A browser success page "
            "alone is not proof of payment. Verify the applicable GST rate, HSN/SAC classification and "
            "place of supply before issuing a real tax invoice.",
            small,
        )
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#94a3b8"))
        canvas.drawString(16 * mm, 10 * mm, "Generated by FINOVEXA AI")
        canvas.drawRightString(
            A4[0] - 16 * mm, 10 * mm, f"Invoice {invoice.number} · Page {doc.page}"
        )
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
