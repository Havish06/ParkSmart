from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from . import db


def utcnow():
    """Return naive UTC for compatibility with the existing database columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='driver', nullable=False)
    vehicle_number = db.Column(db.String(30), default='', server_default='')
    active = db.Column(db.Boolean, default=True, nullable=False, server_default='1')
    created_at = db.Column(db.DateTime, default=utcnow)

    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class ParkingSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slot_number = db.Column(db.String(20), unique=True, nullable=False)
    status = db.Column(db.String(20), default='available', nullable=False)
    sensor_id = db.Column(db.String(20), nullable=False)
    current_vehicle = db.Column(db.String(50))
    enabled = db.Column(db.Boolean, default=True, nullable=False, server_default='1')
    sensor_occupied = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    sensor_health = db.Column(db.String(20), default='unknown', server_default='unknown')
    last_seen = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey('parking_slot.id'), nullable=False)
    vehicle_number = db.Column(db.String(30), nullable=False)
    reservation_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(20), default='confirmed')
    qr_token = db.Column(db.String(100), unique=True, nullable=False)
    reservation_fee = db.Column(db.Float, default=0, nullable=False, server_default='0')
    payment_status = db.Column(db.String(20), default='unpaid', nullable=False, server_default='unpaid')
    payment_transaction_id = db.Column(db.String(60), unique=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    user = db.relationship('User')
    slot = db.relationship('ParkingSlot')

    @property
    def reference(self):
        return f'PS-{self.reservation_date:%Y%m%d}-{self.id:04d}'

    @property
    def starts_at(self):
        return datetime.combine(self.reservation_date, self.start_time)

    @property
    def ends_at(self):
        return datetime.combine(self.reservation_date, self.end_time)

class ParkingSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    slot_id = db.Column(db.Integer, db.ForeignKey('parking_slot.id'), nullable=False)
    vehicle_number = db.Column(db.String(30), nullable=False)
    entry_time = db.Column(db.DateTime, default=utcnow, nullable=False)
    exit_time = db.Column(db.DateTime)
    duration_minutes = db.Column(db.Integer)
    fee = db.Column(db.Float, default=0)
    payment_status = db.Column(db.String(20), default='unpaid')
    status = db.Column(db.String(20), default='awaiting_entry', server_default='active', nullable=False)
    reservation_id = db.Column(db.Integer, db.ForeignKey('reservation.id'))
    active_slot_id = db.Column(db.Integer, unique=True)
    active_vehicle = db.Column(db.String(30), unique=True)
    user = db.relationship('User')
    slot = db.relationship('ParkingSlot')
    reservation = db.relationship('Reservation')

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('parking_session.id'), nullable=False, unique=True)
    amount = db.Column(db.Float, nullable=False)
    transaction_id = db.Column(db.String(50), unique=True, nullable=False)
    payment_time = db.Column(db.DateTime, default=utcnow)
    status = db.Column(db.String(20), default='success')
    session = db.relationship('ParkingSession')

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    message = db.Column(db.String(500), nullable=False)
    type = db.Column(db.String(30), default='info')
    created_at = db.Column(db.DateTime, default=utcnow)
    read_status = db.Column(db.Boolean, default=False)

class SystemLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=utcnow)
    event = db.Column(db.String(100), nullable=False)
    severity = db.Column(db.String(20), default='INFO')
    description = db.Column(db.String(500), nullable=False)


class HardwareStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    connected = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime)
    gate_state = db.Column(db.String(20), default='closed')
    gate_health = db.Column(db.String(20), default='unknown')
    gate_close_at = db.Column(db.DateTime)
    last_error = db.Column(db.String(500), default='')


class OccupancySample(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=utcnow, index=True)
    occupied = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
