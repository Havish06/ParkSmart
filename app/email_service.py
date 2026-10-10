import smtplib
from email.message import EmailMessage
from flask import current_app


def send_email(to, subject, body, attachment_bytes=None, attachment_name='receipt.pdf'):
    config = current_app.config
    host, user = config.get('SMTP_HOST'), config.get('SMTP_USER')
    sender = config.get('SMTP_FROM') or user
    if not host or not sender:
        return False, 'SMTP not configured; notification saved in ParkSmart.'
    msg = EmailMessage()
    msg['From'], msg['To'], msg['Subject'] = sender, to, subject
    msg.set_content(body)
    if attachment_bytes:
        msg.add_attachment(attachment_bytes, maintype='application', subtype='pdf', filename=attachment_name)
    try:
        with smtplib.SMTP(host, config.get('SMTP_PORT', 587), timeout=10) as smtp:
            if config.get('SMTP_STARTTLS', True):
                smtp.starttls()
            if user:
                smtp.login(user, config.get('SMTP_PASSWORD', ''))
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        current_app.logger.warning('Email delivery failed: %s', exc)
        return False, 'Email delivery failed; notification saved in ParkSmart.'
    return True, 'Email sent.'
