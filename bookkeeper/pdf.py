"""Printable copies of the financial forms (ReportLab)."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import db, reports
from .money import fmt

NAVY = colors.HexColor("#13294B")
LIGHT = colors.HexColor("#EEF2F7")


def statement_table(statement: dict, width=6.5 * inch) -> Table:
    data, style = [], [
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, (label, cents, kind) in enumerate(statement["rows"]):
        data.append([label if kind != "line" else f"    {label}", "" if cents is None else fmt(cents)])
        if kind == "section":
            style += [("BACKGROUND", (0, i), (-1, i), NAVY), ("TEXTCOLOR", (0, i), (-1, i), colors.white),
                      ("FONTNAME", (0, i), (-1, i), "Helvetica-Bold")]
        elif kind == "subtotal":
            style += [("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"), ("LINEABOVE", (0, i), (-1, i), 0.5, colors.grey)]
        elif kind == "total":
            style += [("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"), ("BACKGROUND", (0, i), (-1, i), LIGHT),
                      ("LINEABOVE", (0, i), (-1, i), 1, NAVY)]
    table = Table(data, colWidths=[width * 0.68, width * 0.32])
    table.setStyle(TableStyle(style))
    return table


def grid_table(headers, rows, col_widths=None) -> Table:
    table = Table([headers] + rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return table


def financial_statements_pdf(conn) -> bytes:
    """Income statement, balance sheet, cash flow and inventory as one printable PDF."""
    styles = getSampleStyleSheet()
    company = db.get_setting(conn, "company_name")
    as_of = db.get_setting(conn, "current_date")
    start = db.get_setting(conn, "start_date")
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=inch, rightMargin=inch, topMargin=0.8 * inch,
                            bottomMargin=0.8 * inch, title=f"{company} - Financial Statements")
    story = []
    statements = [
        (reports.income_statement(conn), f"For the period {start} to {as_of}"),
        (reports.balance_sheet(conn), f"As of {as_of}"),
        (reports.cash_flow(conn), f"For the period {start} to {as_of}"),
    ]
    for statement, period in statements:
        story += [Paragraph(company, styles["Title"]), Paragraph(statement["title"], styles["Heading2"]),
                  Paragraph(period, styles["Normal"]), Spacer(1, 12), statement_table(statement), PageBreak()]

    inv = reports.inventory_report(conn)
    rows = [[p["name"], p["vendor"], f"{p['qty']:,}", f"${p['unit_cost_cents'] / 100:,.4f}", fmt(p["value_cents"]),
             f"{p['reorder_point']:,}", "REORDER" if p["reorder"] else ""] for p in inv["parts"]]
    story += [
        Paragraph(company, styles["Title"]), Paragraph("Inventory", styles["Heading2"]),
        Paragraph(f"As of {as_of}", styles["Normal"]), Spacer(1, 12),
        grid_table(["Part", "Vendor", "Quantity", "Cost/Unit", "Value", "Reorder Point", "Status"], rows),
        Spacer(1, 12),
        grid_table(["Measure", "Units", "Value"], [
            ["Raw materials (parts)", "", fmt(inv["raw_value_cents"])],
            ["Work in process (units under construction)", f"{inv['wip_qty']:,}", fmt(inv["wip_value_cents"])],
            ["Finished goods (complete units in stock)", f"{inv['finished_qty']:,}", fmt(inv["finished_value_cents"])],
            ["Total inventory", "", fmt(inv["total_value_cents"])],
            ["Units that can be built from current parts", f"{inv['buildable_units']:,}", ""],
        ]),
    ]
    doc.build(story)
    return buf.getvalue()
