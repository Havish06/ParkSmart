from io import BytesIO
from flask import current_app
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from .models import Payment


def receipt_pdf(parking):
    payment = Payment.query.filter_by(session_id=parking.id).first()
    buf = BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.setTitle(f'ParkSmart receipt {parking.id}')
    pdf.setFont('Helvetica-Bold', 20)
    pdf.drawString(72, 780, 'ParkSmart - Parking Receipt')
    pdf.setFont('Helvetica', 11)
    rows = [
        ('Session', str(parking.id)), ('Vehicle', parking.vehicle_number),
        ('Slot', parking.slot.slot_number), ('Entry (UTC)', f'{parking.entry_time:%d-%m-%Y %H:%M}'),
        ('Exit (UTC)', f'{parking.exit_time:%d-%m-%Y %H:%M}' if parking.exit_time else 'Active'),
        ('Duration', f'{parking.duration_minutes or 0} minutes'),
        ('Fee', f'{current_app.config["CURRENCY"]} {parking.fee or 0:.2f}'),
        ('Payment', parking.payment_status.upper()),
        ('Transaction ID', payment.transaction_id if payment else 'Not paid'),
        ('Payment module', 'Simulated academic payment'),
    ]
    y = 740
    for key, value in rows:
        pdf.drawString(72, y, key + ':')
        pdf.drawRightString(520, y, str(value))
        y -= 28
    pdf.showPage()
    pdf.save()
    return buf.getvalue()
