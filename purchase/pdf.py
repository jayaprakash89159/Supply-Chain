"""Purchase order as a printable A4 PDF (ReportLab)."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from scportal.gstin import STATE_CODES

from .models import POApproval, PurchaseSettings
from .numbers import rupees_in_words

NAVY = colors.HexColor('#203B67')
LINE = colors.HexColor('#C9D3E3')


def _inr(value):
	from quotes.templatetags.humanize_inr import inr
	return inr(value)


def _p(text, style):
	return Paragraph(escape(str(text or '')).replace('\n', '<br/>'), style)


def render(order):
	company = PurchaseSettings.load()
	totals = order.totals()
	styles = getSampleStyleSheet()
	small = ParagraphStyle('small', parent=styles['Normal'], fontSize=8, leading=10)
	body = ParagraphStyle('body', parent=styles['Normal'], fontSize=9, leading=11.5)
	bold = ParagraphStyle('bold', parent=body, fontName='Helvetica-Bold')
	right = ParagraphStyle('right', parent=body, alignment=TA_RIGHT)
	title = ParagraphStyle('title', parent=styles['Title'], fontSize=15, textColor=NAVY, spaceAfter=0)

	buffer = BytesIO()
	doc = SimpleDocTemplate(
		buffer, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
		title=f'Purchase Order {order.display_number}', author=company.company_name,
	)
	story = []

	# Letterhead
	logo_path = Path(settings.BASE_DIR) / 'static' / 'img' / 'site' / 'vishwa-site-logo.jpg'
	logo = Image(str(logo_path), width=18 * mm, height=18 * mm) if logo_path.exists() else ''
	company_lines = (
		f'<b>{escape(company.company_name)}</b><br/>{escape(company.company_address)}'
		+ (f'<br/>GSTIN: {escape(company.company_gstin)}' if company.company_gstin else '')
		+ f'<br/>{escape(company.company_phone)} · {escape(company.company_email)}'
	)
	head = Table([[logo, Paragraph(company_lines, small), Paragraph('PURCHASE ORDER', title)]], colWidths=[22 * mm, 100 * mm, 60 * mm])
	head.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LINEBELOW', (0, 0), (-1, 0), 1.2, NAVY)]))
	story += [head, Spacer(1, 5 * mm)]

	# PO facts, vendor and delivery
	supply_code = order.place_of_supply or company.company_state_code
	facts = [
		['PO number', order.display_number],
		['PO date', (order.approved_at or order.created_at).strftime('%d %b %Y')],
		['Delivery by', order.delivery_date.strftime('%d %b %Y') if order.delivery_date else 'As agreed'],
		['Payment terms', order.payment_terms or 'As agreed'],
		['Place of supply', f'{STATE_CODES.get(supply_code, "")} ({supply_code})'],
	]
	if order.quote_request_id:
		facts.append(['Your quotation', f'against our RFQ of {order.quote_request.created_at:%d %b %Y}'])
	facts_table = Table([[_p(k, bold), _p(v, body)] for k, v in facts], colWidths=[28 * mm, 52 * mm])
	vendor = (
		f'<b>To: {escape(order.vendor_name)}</b> ({escape(order.vendor_code)})<br/>{escape(order.vendor_address)}'
		+ (f'<br/>GSTIN: {escape(order.vendor_gstin)}' if order.vendor_gstin else '')
		+ (f'<br/>Attn: {escape(order.vendor_contact)}' if order.vendor_contact else '')
		+ (f' · {escape(order.vendor_phone)}' if order.vendor_phone else '')
	).replace('\n', '<br/>')
	deliver = f'<b>Deliver to:</b><br/>{escape(order.delivery_address or "As advised")}'.replace('\n', '<br/>')
	if order.project_id:
		deliver = f'<b>Project:</b> {escape(str(order.project))}<br/>' + deliver
	parties = Table([[Paragraph(vendor, body), Paragraph(deliver, body), facts_table]], colWidths=[58 * mm, 46 * mm, 78 * mm])
	parties.setStyle(TableStyle([
		('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOX', (0, 0), (-1, -1), 0.5, LINE), ('INNERGRID', (0, 0), (-1, -1), 0.5, LINE),
		('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#F7F9FD')),
	]))
	story += [parties, Spacer(1, 5 * mm)]

	# Items
	rows = [[_p(h, bold) for h in ('#', 'Description', 'Qty', 'Unit', 'Rate (Rs.)', 'GST %', 'Amount (Rs.)')]]
	for line in order.lines.all():
		description = line.description + (f'\n{line.remark}' if line.remark else '')
		rows.append([
			_p(line.position, body), _p(description, body), _p(format(line.quantity.normalize(), 'f'), right), _p(line.unit, body),
			_p(_inr(line.rate), right), _p(format(line.gst_percent.normalize(), 'f'), right), _p(_inr(line.amount), right),
		])
	summary = [('Total before tax', totals['basic'])]
	if totals['freight']:
		summary.append(('Freight', totals['freight']))
	if order.interstate:
		summary.append(('IGST', totals['igst']))
	else:
		summary += [('CGST', totals['cgst']), ('SGST', totals['sgst'])]
	for label, value in summary:
		rows.append(['', _p(label, bold), '', '', '', '', _p(_inr(value), right)])
	rows.append(['', _p('GRAND TOTAL', bold), '', '', '', '', Paragraph(f'<b>Rs. {_inr(totals["grand"])}</b>', right)])
	items = Table(rows, colWidths=[8 * mm, 70 * mm, 16 * mm, 14 * mm, 24 * mm, 14 * mm, 36 * mm], repeatRows=1)
	first_total = len(rows) - len(summary) - 1
	items.setStyle(TableStyle([
		('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DCE6F2')), ('GRID', (0, 0), (-1, first_total - 1), 0.5, LINE),
		('BOX', (0, 0), (-1, -1), 0.5, LINE), ('LINEABOVE', (0, -1), (-1, -1), 1, NAVY),
		('SPAN', (1, -1), (5, -1)), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
		*[('SPAN', (1, r), (5, r)) for r in range(first_total, len(rows))],
	]))
	story += [items, Spacer(1, 2 * mm), _p(f'Amount in words: {rupees_in_words(totals["grand"])}', bold), Spacer(1, 4 * mm)]

	if order.notes:
		story += [_p('Notes', bold), _p(order.notes, body), Spacer(1, 3 * mm)]
	story += [_p('Terms and conditions', bold), _p(order.terms, small), Spacer(1, 6 * mm)]

	# Approval trail and signature
	trail = [
		f'{a.get_decision_display()}{" – " + a.level_name if a.level_name else ""}: {a.by.get_full_name() or a.by.get_username() if a.by else "—"}, {a.at:%d %b %Y}'
		for a in order.approvals.filter(round=order.approval_round, decision__in=[POApproval.Decision.APPROVED])
	]
	sign = Table([[
		_p('Approved by:\n' + ('\n'.join(trail) if trail else '—'), small),
		Paragraph(f'For <b>{escape(company.company_name)}</b><br/><br/><br/>Authorised signatory', ParagraphStyle('sig', parent=body, alignment=TA_RIGHT)),
	]], colWidths=[100 * mm, 82 * mm])
	sign.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'BOTTOM')]))
	story.append(sign)

	def footer(canvas, document):
		canvas.saveState()
		canvas.setFont('Helvetica', 7)
		canvas.setFillColor(colors.grey)
		canvas.drawString(14 * mm, 8 * mm, f'{order.display_number} · Page {document.page}')
		canvas.drawRightString(A4[0] - 14 * mm, 8 * mm, 'Computer-generated purchase order')
		canvas.restoreState()

	doc.build(story, onFirstPage=footer, onLaterPages=footer)
	return buffer.getvalue()
