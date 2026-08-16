"""
Quote PDF generation service.
Generates professional branded PDF quotes.
"""
import io
import logging
from datetime import date

logger = logging.getLogger("quote_pdf")


async def generate_quote_pdf(
    quote: dict,
    line_items: list,
    settings: dict,
) -> bytes:
    """
    Generate a professional PDF for a quote.

    Args:
        quote: Quote data dict (from the quotes table)
        line_items: List of line item dicts (from quote_line_items table)
        settings: Quote settings dict (company details, branding)

    Returns:
        PDF file as bytes
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=15 * mm,
        bottomMargin=20 * mm,
    )

    primary = HexColor('#7c5cfc')
    dark_bg = HexColor('#1a1c22')
    light_text = HexColor('#e8e6e1')  # noqa: F841  # TODO(day2): defined but never applied to a style; header-on-dark_bg already uses `white` so no readability bug today, but this looks like unfinished palette wiring — confirm whether it's needed before deleting.
    muted = HexColor('#6b7280')
    border_color = HexColor('#e5e7eb')
    section_bg = HexColor('#f9fafb')

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'QuoteTitle',
        parent=styles['Heading1'],
        fontSize=22,
        textColor=dark_bg,
        spaceAfter=2 * mm,
        fontName='Helvetica-Bold',
    )

    subtitle_style = ParagraphStyle(
        'QuoteSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=muted,
        spaceAfter=6 * mm,
    )

    section_header_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=dark_bg,
        fontName='Helvetica-Bold',
        spaceBefore=6 * mm,
        spaceAfter=3 * mm,
    )

    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontSize=9,
        textColor=HexColor('#374151'),
        leading=13,
    )

    small_style = ParagraphStyle(
        'Small',
        parent=styles['Normal'],
        fontSize=8,
        textColor=muted,
        leading=11,
    )

    story = []

    # ── Header ──
    company_name = settings.get('company_name') or quote.get('business_name', 'Business Hero')

    story.append(Paragraph("QUOTE", title_style))
    story.append(Paragraph(
        f"{quote.get('quote_number', '')}",
        ParagraphStyle('QuoteNum', parent=subtitle_style, fontSize=14, textColor=primary)
    ))
    story.append(Spacer(1, 4 * mm))

    # Company and customer details side by side
    company_info = f"""
    <b>{company_name}</b><br/>
    {settings.get('company_address', '') or ''}<br/>
    {settings.get('company_phone', '') or ''}<br/>
    {settings.get('company_email', '') or ''}<br/>
    {f"VAT: {settings.get('vat_number')}" if settings.get('vat_number') else ''}
    """.strip()

    customer_info = f"""
    <b>Quote for:</b><br/>
    {quote.get('customer_name', '')}<br/>
    {quote.get('customer_address', '') or ''}<br/>
    {quote.get('customer_email', '') or ''}<br/>
    {quote.get('customer_phone', '') or ''}
    """.strip()

    info_table = Table(
        [[Paragraph(company_info, body_style), Paragraph(customer_info, body_style)]],
        colWidths=[90 * mm, 80 * mm],
    )
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 4 * mm))

    # Quote meta (dates, reference)
    meta_lines = []
    if quote.get('issue_date'):
        meta_lines.append(f"Issue date: {quote['issue_date']}")
    if quote.get('valid_until'):
        meta_lines.append(f"Valid until: {quote['valid_until']}")
    if quote.get('reference'):
        meta_lines.append(f"Reference: {quote['reference']}")
    if quote.get('project_reference'):
        meta_lines.append(f"Project: {quote['project_reference']}")
    if quote.get('job_location'):
        meta_lines.append(f"Location: {quote['job_location']}")

    if meta_lines:
        story.append(Paragraph("  |  ".join(meta_lines), small_style))
        story.append(Spacer(1, 3 * mm))

    # ── Job description ──
    if quote.get('job_title'):
        story.append(Paragraph(f"<b>{quote['job_title']}</b>", section_header_style))
    if quote.get('job_description'):
        story.append(Paragraph(quote['job_description'], body_style))
        story.append(Spacer(1, 4 * mm))

    # ── Line items grouped by trade ──
    groups: dict[str, list] = {}
    ungrouped = []
    for item in line_items:
        group = item.get('group_name', '')
        if group:
            if group not in groups:
                groups[group] = []
            groups[group].append(item)
        else:
            ungrouped.append(item)

    header_row = ['Description', 'Qty', 'Unit', 'Unit Cost', 'Total']
    col_widths = [80 * mm, 15 * mm, 15 * mm, 25 * mm, 25 * mm]

    def build_items_table(items, group_name=None):
        table_data = []
        if group_name:
            group_total = sum(float(i.get('line_total', 0)) for i in items)
            table_data.append([
                Paragraph(f"<b>{group_name}</b>", body_style),
                '', '', '',
                Paragraph(
                    f"<b>£{group_total:,.2f}</b>",
                    ParagraphStyle('GroupTotal', parent=body_style, alignment=TA_RIGHT),
                )
            ])
        for item in items:
            qty = float(item.get('quantity', 1))
            unit_cost = float(item.get('unit_cost', 0))
            line_total = float(item.get('line_total', qty * unit_cost))
            table_data.append([
                Paragraph(item.get('description', ''), body_style),
                Paragraph(f"{qty:g}", ParagraphStyle('r', parent=body_style, alignment=TA_RIGHT)),
                Paragraph(item.get('unit', 'each'), body_style),
                Paragraph(f"£{unit_cost:,.2f}", ParagraphStyle('r', parent=body_style, alignment=TA_RIGHT)),
                Paragraph(f"£{line_total:,.2f}", ParagraphStyle('r', parent=body_style, alignment=TA_RIGHT)),
            ])
        return table_data

    all_rows = [header_row]
    for group_name, items in groups.items():
        all_rows.extend(build_items_table(items, group_name))
    if ungrouped:
        all_rows.extend(build_items_table(ungrouped))

    items_table = Table(all_rows, colWidths=col_widths, repeatRows=1)

    table_style = [
        ('BACKGROUND', (0, 0), (-1, 0), dark_bg),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 3 * mm),
        ('TOPPADDING', (0, 0), (-1, 0), 3 * mm),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 1), (-1, -1), 2 * mm),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 2 * mm),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, border_color),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN', (3, 0), (4, -1), 'RIGHT'),
    ]

    row_idx = 1
    for group_name, items in groups.items():
        table_style.append(('BACKGROUND', (0, row_idx), (-1, row_idx), section_bg))
        table_style.append(('FONTNAME', (0, row_idx), (-1, row_idx), 'Helvetica-Bold'))
        row_idx += 1 + len(items)

    items_table.setStyle(TableStyle(table_style))
    story.append(items_table)
    story.append(Spacer(1, 4 * mm))

    # ── Totals ──
    subtotal = float(quote.get('subtotal', 0))
    tax_rate = float(quote.get('tax_rate', 20))
    tax_amount = float(quote.get('tax_amount', 0))
    discount = float(quote.get('discount_amount', 0))
    total = float(quote.get('total', 0))

    totals_data = []
    totals_data.append(['', '', '', 'Subtotal:', f"£{subtotal:,.2f}"])
    if discount > 0:
        totals_data.append(['', '', '', 'Discount:', f"-£{discount:,.2f}"])
    if tax_rate > 0:
        totals_data.append(['', '', '', f'VAT ({tax_rate:.0f}%):', f"£{tax_amount:,.2f}"])
    totals_data.append(['', '', '', 'TOTAL:', f"£{total:,.2f}"])

    totals_table = Table(totals_data, colWidths=col_widths)
    totals_table.setStyle(TableStyle([
        ('ALIGN', (3, 0), (4, -1), 'RIGHT'),
        ('FONTNAME', (3, -1), (4, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('FONTSIZE', (3, -1), (4, -1), 12),
        ('TEXTCOLOR', (3, -1), (4, -1), primary),
        ('TOPPADDING', (0, 0), (-1, -1), 2 * mm),
        ('LINEABOVE', (3, -1), (4, -1), 1, primary),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 6 * mm))

    # ── Customer notes ──
    if quote.get('customer_notes'):
        story.append(Paragraph("Notes", section_header_style))
        story.append(Paragraph(quote['customer_notes'], body_style))
        story.append(Spacer(1, 4 * mm))

    # ── Terms ──
    if quote.get('terms'):
        story.append(Paragraph("Terms &amp; Conditions", section_header_style))
        story.append(Paragraph(quote['terms'], small_style))
        story.append(Spacer(1, 4 * mm))

    # ── Footer ──
    footer_text = f"Generated by Business Hero | {date.today().strftime('%d %B %Y')}"
    if settings.get('company_registration'):
        footer_text += f" | Reg: {settings['company_registration']}"
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        footer_text,
        ParagraphStyle('Footer', parent=small_style, alignment=TA_CENTER, textColor=muted),
    ))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes
