from datetime import datetime, time, timedelta

from app.config import Config
from app.models import utcnow


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = 'isolated-test-secret'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    TOTAL_SLOTS = 4
    PARKING_RATE_FIRST_HOUR = 20
    PARKING_RATE_ADDITIONAL_HOUR = 10
    CURRENCY = 'INR'
    SIMULATOR_MODE = True
    HARDWARE_AUTOSTART = False
    GATE_OPEN_SECONDS = 60
    ENTRY_TIMEOUT_MINUTES = 10
    RESERVATION_EARLY_MINUTES = 15
    WALKIN_HOLD_MINUTES = 60
    TIMEZONE = 'UTC'
    HARDWARE_STALE_SECONDS = 10
    SMTP_HOST = ''
    SMTP_USER = ''
    SMTP_PASSWORD = ''
    SMTP_FROM = ''


def future_window():
    """Same-day booking window that remains valid near midnight."""
    day = utcnow().date() + timedelta(days=1)
    start = datetime.combine(day, time(10))
    return start, start + timedelta(hours=2)


def reservation_data(slot_id=1, vehicle='TN TEST 1000'):
    start, end = future_window()
    return {
        'date': start.date().isoformat(), 'start': start.strftime('%H:%M'),
        'end': end.strftime('%H:%M'), 'slot_id': str(slot_id),
        'vehicle_number': vehicle,
    }


def login(client, email='driver@parksmart.local', password='Driver@123'):
    response = client.post('/login', data={'email': email, 'password': password})
    assert response.status_code == 302
    return response
