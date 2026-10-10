import os
from pathlib import Path, PureWindowsPath
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / 'instance'
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(BASE_DIR / '.env')


def database_uri():
    """Resolve project-relative SQLite URLs before Flask-SQLAlchemy sees them."""
    configured = os.getenv('DATABASE_URL')
    if not configured:
        return f"sqlite:///{(INSTANCE_DIR / 'parksmart.db').as_posix()}"

    prefix = 'sqlite:///'
    if configured.startswith(prefix) and not configured.startswith('sqlite:////') and configured != 'sqlite:///:memory:':
        database_path = configured[len(prefix):]
        if not Path(database_path).is_absolute() and not PureWindowsPath(database_path).is_absolute():
            configured = f"sqlite:///{(BASE_DIR / database_path).as_posix()}"
    return configured

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-only-change-me')
    SQLALCHEMY_DATABASE_URI = database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TOTAL_SLOTS = int(os.getenv('TOTAL_SLOTS', '4'))
    PARKING_RATE_FIRST_HOUR = float(os.getenv('PARKING_RATE_FIRST_HOUR', '20'))
    PARKING_RATE_ADDITIONAL_HOUR = float(os.getenv('PARKING_RATE_ADDITIONAL_HOUR', '10'))
    CURRENCY = os.getenv('CURRENCY', 'INR')
    SIMULATOR_MODE = os.getenv('SIMULATOR_MODE', 'true').lower() == 'true'
    SERIAL_PORT = os.getenv('SERIAL_PORT', 'COM3')
    SERIAL_BAUDRATE = int(os.getenv('SERIAL_BAUDRATE', '115200'))
    SERIAL_TIMEOUT = float(os.getenv('SERIAL_TIMEOUT', '1.0'))
    HARDWARE_AUTOSTART = os.getenv('HARDWARE_AUTOSTART', 'true').lower() == 'true'
    HARDWARE_STALE_SECONDS = float(os.getenv('HARDWARE_STALE_SECONDS', '10'))
    GATE_OPEN_SECONDS = float(os.getenv('GATE_OPEN_SECONDS', '5'))
    ENTRY_TIMEOUT_MINUTES = int(os.getenv('ENTRY_TIMEOUT_MINUTES', '10'))
    RESERVATION_EARLY_MINUTES = int(os.getenv('RESERVATION_EARLY_MINUTES', '15'))
    WALKIN_HOLD_MINUTES = int(os.getenv('WALKIN_HOLD_MINUTES', '60'))
    RESERVATION_LOCK_MINUTES = int(os.getenv('RESERVATION_LOCK_MINUTES', '5'))
    TIMEZONE = os.getenv('TIMEZONE', 'UTC')
    PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', 'http://127.0.0.1:5000').rstrip('/')
    CSRF_ENABLED = True
    SMTP_HOST = os.getenv('SMTP_HOST', '')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
    SMTP_FROM = os.getenv('SMTP_FROM', '')
    SMTP_STARTTLS = os.getenv('SMTP_STARTTLS', 'true').lower() == 'true'
    ASYNC_EMAIL = os.getenv('ASYNC_EMAIL', 'true').lower() == 'true'
