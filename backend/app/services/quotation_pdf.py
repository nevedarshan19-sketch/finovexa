"""PDF rendering for accounting quotations.

The PDF states the approval trail and makes clear that a quotation is not a tax invoice and
does not collect payment.
"""

from __future__ import annotations

import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..models import AccountingQuotation
from .accounting import quotation_status
from .finance import money_text


def _date(value) -> str:
    return value.strftime("%d %b %Y") if value else "—"


def build_quotation_pdf(
    quotation: AccountingQuotation,
    *,
    approved_by_name: str | None = None,
    prepared_by_name: str | None = None,
    customer_name: str | None = None,
) -> bytes:
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=f"Quotation {quotation.number}",
        author="FINOVEXA AI",
        subject=f"Accounting services quotation {quotation.number}",
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "QuoteBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.4, leading=11
    )
    small = ParagraphStyle(
        "QuoteSmall", parent=body, fontSize=7.2, leading=9.2, textColor=colors.HexColor("#475569")
    )
    right_small = ParagraphStyle("QuoteRight", parent=small, alignment=TA_RIGHT)
    heading = ParagraphStyle(
        "QuoteHeading",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=20,
        alignment=TA_RIGHT,
        textColor=colors.HexColor("#0f172a"),
    )
    section = ParagraphStyle(
        "QuoteSection",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=7.8,
        leading=10,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=2,
    )
    currency = quotation.currency or "INR"
    enquiries = quotation.enquiry
    business_name = (
        customer_name
        or (enquiries.business_name if enquiries is not None else None)
        or (quotation.client.business_name if quotation.client is not None else None)
        or "Client"
    )
    contact = enquiries.contact_name if enquiries is not None else "—"
    email = enquiries.email if enquiries is not None else "—"
    phone = enquiries.phone if enquiries is not None else None
    status_label = quotation_status(quotation).replace("_", " ").title()

    story: list = []
    header_left = [
        Paragraph("<b>FINOVEXA AI</b>", body),
        Paragraph("Accounting practice", small),
        Paragraph("Professional accounting, GST working papers and Tally-ready records.", small),
    ]
    header_right = [
        Paragraph("QUOTATION", heading),
        Paragraph(f"<b>{quotation.number}</b>", right_small),
        Paragraph(f"Prepared: {_date(quotation.created_at)}", right_small),
        Paragraph(f"Valid until: {_date(quotation.valid_until)}", right_small),
        Paragraph(f"Status: {status_label}", right_small),
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

    details = [
        Paragraph("PREPARED FOR", section),
        Paragraph(f"<b>{business_name}</b>", body),
        Paragraph(str(contact), small),
        Paragraph(str(email), small),
    ]
    if phone:
        details.append(Paragraph(str(phone), small))
    engagement = [Paragraph("ENGAGEMENT", section)]
    if enquiries is not None:
        engagement.extend(
            [
                Paragraph(f"Business type: {enquiries.business_type}", small),
                Paragraph(f"GST status: {enquiries.gst_status}", small),
            ]
        )
    if quotation.annual_turnover is not None:
        engagement.append(
            Paragraph(
                f"Annual turnover: {money_text(Decimal(quotation.annual_turnover), currency)}",
                small,
            )
        )
    if quotation.benchmark_annual is not None:
        engagement.append(
            Paragraph(
                f"2% indicative benchmark: {money_text(Decimal(quotation.benchmark_annual), currency)}",
                small,
            )
        )
    if enquiries is not None and enquiries.financial_year:
        engagement.append(Paragraph(f"Financial year: {enquiries.financial_year}", small))
    blocks = Table([[details, engagement]], colWidths=[89 * mm, 89 * mm])
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

    rows: list[list] = [["#", "Service", "Billing", "Annual fee"]]
    for index, line in enumerate(quotation.line_items or [], start=1):
        description = [Paragraph(f"<b>{line.get('label') or 'Service'}</b>", body)]
        if line.get("description"):
            description.append(Paragraph(str(line["description"]), small))
        cadence = "One time" if line.get("cadence") == "one_time" else "Annual"
        rows.append(
            [
                str(index),
                description,
                cadence,
                money_text(Decimal(str(line.get("amount") or 0)), currency),
            ]
        )
    if len(rows) == 1:
        legacy_scope = quotation.scope or []
        for index, line in enumerate(legacy_scope, start=1):
            rows.append(
                [
                    str(index),
                    Paragraph(str(line.get("description") or line.get("service") or "Service"), body),
                    "As agreed",
                    money_text(Decimal(quotation.amount), currency),
                ]
            )
    table = Table(rows, colWidths=[10 * mm, 105 * mm, 28 * mm, 35 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 7.6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (3, 1), (3, -1), "RIGHT"),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 4 * mm))

    totals = [
        ["Annual subtotal", money_text(Decimal(quotation.subtotal_annual), currency)],
    ]
    if Decimal(quotation.discount_amount) > 0:
        if quotation.discount_type == "percent":
            label = f"Approved discount ({Decimal(quotation.discount_value):g}%)"
        else:
            label = "Approved discount"
        totals.append([label, f"- {money_text(Decimal(quotation.discount_amount), currency)}"])
    totals.extend(
        [
            ["Final annual fee", money_text(Decimal(quotation.total_annual), currency)],
            ["Monthly equivalent", money_text(Decimal(quotation.monthly_equivalent), currency)],
            [
                "Payment schedule",
                f"{quotation.payment_frequency.replace('_', ' ').title()} · "
                f"{money_text(Decimal(quotation.amount), currency)} per payment",
            ],
        ]
    )
    final_row = len(totals) - 3
    totals_table = Table(totals, colWidths=[120 * mm, 58 * mm])
    totals_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8.2),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, final_row), (-1, final_row), 0.7, colors.HexColor("#94a3b8")),
                ("FONTNAME", (0, final_row), (-1, final_row), "Helvetica-Bold"),
                ("FONTNAME", (0, final_row + 1), (-1, final_row + 1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, final_row + 1), (-1, final_row + 1), colors.HexColor("#0f766e")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    story.append(totals_table)
    story.append(Spacer(1, 4 * mm))

    if quotation.tax_note:
        story.append(
            Paragraph(
                f"<b>Taxes:</b> {quotation.tax_note} GST rate for guidance: "
                f"{Decimal(quotation.tax_rate_percent):g}%.",
                small,
            )
        )
        story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            "<b>Important:</b> This quotation is not a tax invoice. Accepting it does not "
            "collect any payment; a separate invoice and secure payment process apply. "
            "ITR filing is a separate paid service and is not included in bookkeeping packages. "
            "Only authorised professionals perform regulated filing or certification work.",
            small,
        )
    )
    story.append(Spacer(1, 4 * mm))

    if quotation.terms:
        story.append(Paragraph("TERMS AND CONDITIONS", section))
        for line in str(quotation.terms).splitlines():
            if line.strip():
                story.append(Paragraph(line.strip(), small))
        story.append(Spacer(1, 3 * mm))

    approval = [Paragraph("APPROVAL", section)]
    if quotation.approved_at:
        approval.append(
            Paragraph(
                f"Approved by senior accountant: <b>{approved_by_name or 'Senior accountant'}</b> "
                f"on {_date(quotation.approved_at)}.",
                small,
            )
        )
    elif quotation.status == "rejected":
        approval.append(Paragraph("Rejected before issue. A revised quotation is required.", small))
    else:
        approval.append(
            Paragraph(
                "Draft — not approved. Final accounting prices require senior accountant approval.",
                small,
            )
        )
    if prepared_by_name:
        approval.append(Paragraph(f"Prepared by: {prepared_by_name}", small))
    story.append(Table([[approval]], colWidths=[178 * mm]))
    story[-1].setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]))

    document.build(story)
    return buffer.getvalue()
