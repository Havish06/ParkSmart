from datetime import datetime, timedelta
from functools import wraps
import math
import secrets
import threading
from datetime import timezone
from zoneinfo import ZoneInfo
from flask import current_app
from sqlalchemy.exc import IntegrityError
from sqlalchemy import update
from . import db
from .models import (User, ParkingSlot, Reservation, ParkingSession, Payment,
                     SystemLog, Notification, HardwareStatus, OccupancySample, utcnow)

# The serial worker and web requests use the same lifecycle lock. Unique DB
# indexes provide a second guard against two active admissions or payments.
lifecycle_lock = threading.RLock()


def synchronized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with lifecycle_lock:
            try:
                return fn(*args, **kwargs)
            except Exception:
                db.session.rollback()
                raise
    return wrapped


def log(event, description, severity='INFO'):
    db.session.add(SystemLog(event=event, description=str(description)[:500], severity=severity))


def notify(user_id, message, kind='info'):
    if user_id:
        db.session.add(Notification(user_id=user_id, message=message[:500], type=kind))


def local_label(value):
    zone = ZoneInfo(current_app.config.get('TIMEZONE', 'UTC'))
    return value.replace(tzinfo=timezone.utc).astimezone(zone).strftime('%Y-%m-%d %H:%M')


def email_user(user, subject, body, attachment=None, filename='receipt.pdf'):
    if not user:
        return False, 'No registered driver is linked to this session.'
    from .email_service import send_email
    if not current_app.config.get('SMTP_HOST') or not (current_app.config.get('SMTP_FROM') or current_app.config.get('SMTP_USER')):
        return False, 'SMTP not configured; notification saved in ParkSmart.'
    if current_app.config.get('ASYNC_EMAIL', True):
        app = current_app._get_current_object()
        recipient = user.email

        def deliver():
            with app.app_context():
                try:
                    ok, message = send_email(recipient, subject, body, attachment, filename)
                    log('EMAIL', f'{subject}: {message}', 'INFO' if ok else 'WARNING')
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    app.logger.exception('Background email failed: %s', subject)

        thread = threading.Thread(target=deliver, name='parksmart-email', daemon=True)
        thread.start()
        return True, 'Email queued.'
    ok, message = send_email(user.email, subject, body, attachment, filename)
    log('EMAIL', f'{subject}: {message}', 'INFO' if ok else 'WARNING')
    db.session.commit()
    return ok, message


def seed_data():
    for name, email, role, password in [
        ('ParkSmart Admin', 'admin@parksmart.local', 'admin', 'Admin@123'),
        ('Demo Driver', 'driver@parksmart.local', 'driver', 'Driver@123'),
    ]:
        existing = User.query.filter_by(email=email).first()
        if not existing:
            user = User(name=name, email=email, role=role, vehicle_number='TN DEMO 0001' if role == 'driver' else '')
            user.set_password(password)
            db.session.add(user)
        elif role == 'driver' and not existing.vehicle_number:
            existing.vehicle_number = 'TN DEMO 0001'
    for i in range(1, current_app.config['TOTAL_SLOTS'] + 1):
        if not ParkingSlot.query.filter_by(slot_number=f'S{i:02d}').first():
            db.session.add(ParkingSlot(slot_number=f'S{i:02d}', sensor_id=f'IR{i}'))
    if not db.session.get(HardwareStatus, 1):
        db.session.add(HardwareStatus(id=1))
    db.session.commit()


def vehicle_number(value):
    value = ' '.join(str(value or '').strip().upper().split())
    if not value or len(value) > 30:
        raise ValueError('Enter a vehicle number of 1–30 characters.')
    return value


def active_session(slot_id):
    return ParkingSession.query.filter_by(slot_id=slot_id, exit_time=None).filter(
        ParkingSession.status.in_(['awaiting_entry', 'active'])).first()


def reservation_conflict(slot_id, start, end, exclude=None):
    bookings = Reservation.query.filter_by(slot_id=slot_id).filter(
        Reservation.status.in_(['confirmed', 'checked_in'])).all()
    return next((r for r in bookings if r.id != exclude and r.starts_at < end and r.ends_at > start), None)


def available_for_reservation(slot, start, end, exclude=None):
    if not slot.enabled:
        return False, 'Disabled by administrator'
    if slot.sensor_health == 'fault':
        return False, 'Sensor fault'
    if slot.status in ('occupied', 'disabled') or slot.sensor_occupied or active_session(slot.id):
        return False, 'Currently occupied or allocated'
    if reservation_conflict(slot.id, start, end, exclude):
        return False, 'Reserved for this time'
    if start <= utcnow() + timedelta(minutes=current_app.config['RESERVATION_LOCK_MINUTES']):
        if slot.sensor_occupied or active_session(slot.id):
            return False, 'Currently occupied or allocated'
    return True, 'Available'


def first_available_slot():
    now = utcnow()
    end = now + timedelta(minutes=current_app.config['RESERVATION_LOCK_MINUTES'])
    return next((slot for slot in ParkingSlot.query.filter_by(enabled=True).order_by(ParkingSlot.id).all()
                 if not slot.sensor_occupied and slot.status == 'available'
                 and slot.sensor_health != 'fault' and not active_session(slot.id)
                 and not reservation_conflict(slot.id, now, end)), None)


def calculate_fee(minutes, first_hour=20, additional_hour=10):
    if minutes <= 0:
        return 0
    return round(first_hour + max(0, math.ceil((minutes - 60) / 60)) * additional_hour, 2)


@synchronized
def create_reservation(user, slot_id, vehicle, start, end):
    now = utcnow()
    if start < now or end <= start or start.date() != end.date():
        raise ValueError(f'Choose a future arrival and a later departure on the same date ({current_app.config.get("TIMEZONE", "UTC")}).')
    vehicle = vehicle_number(vehicle)
    slot = db.session.get(ParkingSlot, slot_id)
    if not slot:
        raise ValueError('Select a valid slot.')
    # Write-lock the slot before checking overlaps; this also serializes bookings
    # on SQLite across application processes.
    db.session.execute(update(ParkingSlot).where(ParkingSlot.id == slot_id).values(updated_at=now))
    bookable, reason = available_for_reservation(slot, start, end)
    if not bookable:
        raise ValueError(reason)
    for booking in Reservation.query.filter_by(vehicle_number=vehicle).filter(
            Reservation.status.in_(['confirmed', 'checked_in'])).all():
        if booking.starts_at < end and booking.ends_at > start:
            raise ValueError('This vehicle already has a reservation for that time.')
    reserved_minutes = max(1, math.ceil((end - start).total_seconds() / 60))
    reservation_fee = calculate_fee(reserved_minutes, current_app.config['PARKING_RATE_FIRST_HOUR'],
                                    current_app.config['PARKING_RATE_ADDITIONAL_HOUR'])
    booking = Reservation(user_id=user.id, slot_id=slot_id, vehicle_number=vehicle,
                          reservation_date=start.date(), start_time=start.time(), end_time=end.time(),
                          qr_token=secrets.token_urlsafe(24), reservation_fee=reservation_fee,
                          payment_status='paid',
                          payment_transaction_id='SIM-RES-' + secrets.token_hex(8).upper())
    db.session.add(booking)
    db.session.flush()
    message = (f'{booking.reference} confirmed and paid: {slot.slot_number}, {vehicle}, '
               f'{local_label(start)}–{end:%H:%M} {current_app.config.get("TIMEZONE", "UTC")}. '
               f'Reservation fee: {current_app.config["CURRENCY"]} {reservation_fee:.2f}.')
    notify(user.id, message, 'reservation')
    log('RESERVATION', message)
    db.session.commit()
    email_user(user, 'ParkSmart reservation confirmation', message + f'\nEntrance QR token: PARKSMART:{booking.qr_token}')
    return booking


@synchronized
def cancel_reservation(booking):
    if booking.status != 'confirmed':
        raise ValueError('Only a confirmed reservation can be cancelled.')
    booking.status = 'cancelled'
    notify(booking.user_id, f'{booking.reference} cancelled.', 'reservation')
    log('RESERVATION_CANCEL', booking.reference)
    db.session.commit()


@synchronized
def reschedule_reservation(booking, start, end):
    if booking.status != 'confirmed':
        raise ValueError('Only a confirmed reservation can be rescheduled.')
    if start < utcnow() or end <= start or start.date() != end.date():
        raise ValueError(f'Choose a future arrival and a later departure on the same date ({current_app.config.get("TIMEZONE", "UTC")}).')
    db.session.execute(update(ParkingSlot).where(ParkingSlot.id == booking.slot_id).values(updated_at=utcnow()))
    bookable, reason = available_for_reservation(booking.slot, start, end, booking.id)
    if not bookable:
        raise ValueError(reason)
    conflicts = Reservation.query.filter_by(vehicle_number=booking.vehicle_number).filter(
        Reservation.status.in_(['confirmed', 'checked_in']), Reservation.id != booking.id).all()
    if any(r.starts_at < end and r.ends_at > start for r in conflicts):
        raise ValueError('This vehicle already has a reservation for that time.')
    booking.reservation_date, booking.start_time, booking.end_time = start.date(), start.time(), end.time()
    reserved_minutes = max(1, math.ceil((end - start).total_seconds() / 60))
    booking.reservation_fee = calculate_fee(reserved_minutes, current_app.config['PARKING_RATE_FIRST_HOUR'],
                                            current_app.config['PARKING_RATE_ADDITIONAL_HOUR'])
    booking.payment_status = 'paid'
    booking.payment_transaction_id = 'SIM-RES-' + secrets.token_hex(8).upper()
    message = (f'{booking.reference} rescheduled: {local_label(start)}–{end:%H:%M} '
               f'{current_app.config.get("TIMEZONE", "UTC")}.')
    notify(booking.user_id, message, 'reservation')
    log('RESERVATION_RESCHEDULE', message)
    db.session.commit()
    email_user(booking.user, 'ParkSmart reservation updated', message)


@synchronized
def cancel_admission(parking):
    if parking.status != 'awaiting_entry' or parking.slot.sensor_occupied:
        raise ValueError('Only an entry that has not been confirmed by a sensor can be cancelled.')
    parking.status = 'cancelled'
    parking.active_slot_id, parking.active_vehicle = None, None
    parking.slot.status = 'available' if parking.slot.enabled else 'disabled'
    parking.slot.current_vehicle = None
    if parking.reservation:
        parking.reservation.status = 'confirmed' if parking.reservation.ends_at > utcnow() else 'expired'
    notify(parking.user_id, f'Entry for {parking.vehicle_number} cancelled. The space has been released.', 'entry')
    log('ADMISSION_CANCEL', f'Session {parking.id}: {parking.vehicle_number}')
    db.session.commit()


@synchronized
def start_session(slot_id, vehicle, user_id=None, reservation=None):
    vehicle = vehicle_number(vehicle)
    slot = db.session.get(ParkingSlot, slot_id)
    if not slot or not slot.enabled or slot.status in ('occupied', 'disabled') or slot.sensor_occupied or slot.sensor_health == 'fault' or active_session(slot_id):
        raise ValueError('That slot is unavailable.')
    if ParkingSession.query.filter_by(active_vehicle=vehicle).first():
        raise ValueError('This vehicle already has an active parking session.')
    now = utcnow()
    if not reservation and reservation_conflict(slot_id, now, now + timedelta(minutes=current_app.config['RESERVATION_LOCK_MINUTES'])):
        raise ValueError('That slot is held for an arriving reservation.')
    parking = ParkingSession(user_id=user_id, slot_id=slot_id, vehicle_number=vehicle,
                             active_slot_id=slot_id, active_vehicle=vehicle, entry_time=now,
                             reservation_id=reservation.id if reservation else None, status='awaiting_entry')
    slot.status, slot.current_vehicle = 'allocated', vehicle
    if reservation:
        reservation.status = 'checked_in'
    db.session.add(parking)
    try:
        db.session.flush()
    except IntegrityError as exc:
        raise ValueError('This slot or vehicle has already been admitted.') from exc
    current_app.extensions['hardware'].command_gate(True)
    notify(user_id, f'Assigned {slot.slot_number} to {vehicle}. Awaiting IR sensor confirmation.', 'entry')
    log('ADMISSION', f'{vehicle} assigned {slot.slot_number}; awaiting sensor')
    db.session.commit()
    return parking


@synchronized
def admit_reservation(token, user=None):
    token = str(token or '').strip()
    if token.startswith('PARKSMART:'):
        token = token[len('PARKSMART:'):]
    booking = Reservation.query.filter_by(qr_token=token).first()
    if not booking or (user and user.role != 'admin' and booking.user_id != user.id):
        raise ValueError('Invalid reservation QR token.')
    if booking.status != 'confirmed':
        raise ValueError('This reservation has already been used, cancelled, or expired.')
    if booking.payment_status != 'paid':
        raise ValueError('This reservation must be paid before it can be admitted.')
    now = utcnow()
    earliest = booking.starts_at - timedelta(minutes=current_app.config['RESERVATION_EARLY_MINUTES'])
    if not earliest <= now < booking.ends_at:
        zone = ZoneInfo(current_app.config.get('TIMEZONE', 'UTC'))
        format_time = lambda value: value.replace(tzinfo=timezone.utc).astimezone(zone).strftime('%d %b %Y %H:%M')
        raise ValueError(
            f'This reservation is outside its admission window. Valid window: '
            f'{format_time(earliest)}–{format_time(booking.ends_at)} '
            f'({current_app.config.get("TIMEZONE", "UTC")}).'
        )
    return start_session(booking.slot_id, booking.vehicle_number, booking.user_id, booking)


@synchronized
def walk_in(vehicle, user_id=None):
    slot = first_available_slot()
    if not slot:
        raise ValueError('Parking full: no unreserved, working slots are available.')
    return start_session(slot.id, vehicle, user_id)


def record_occupancy():
    slots = ParkingSlot.query.filter_by(enabled=True).all()
    db.session.add(OccupancySample(occupied=sum(s.sensor_occupied for s in slots), total=len(slots)))


@synchronized
def sync_sensor_state(slot_id, occupied, vehicle=None):
    if type(occupied) is not bool:
        raise ValueError('Sensor occupancy must be a boolean.')
    slot = db.session.get(ParkingSlot, slot_id)
    if not slot:
        return False
    old = slot.sensor_occupied
    slot.sensor_occupied, slot.sensor_health, slot.last_seen = occupied, 'normal', utcnow()
    parking = active_session(slot_id)
    if occupied:
        if not parking:
            parking = ParkingSession(slot_id=slot.id, vehicle_number=vehicle or f'UNIDENTIFIED-{slot.sensor_id}',
                                     active_slot_id=slot.id, status='active')
            db.session.add(parking)
            log('UNASSIGNED_ENTRY', f'Physical occupancy detected at {slot.slot_number}', 'WARNING')
        elif parking.status == 'awaiting_entry':
            parking.status, parking.entry_time = 'active', utcnow()
            notify(parking.user_id, f'Parking started for {parking.vehicle_number} in {slot.slot_number}.', 'entry')
            log('ENTRY', f'{parking.vehicle_number} confirmed at {slot.slot_number}')
        slot.status, slot.current_vehicle = ('occupied' if slot.enabled else 'disabled'), parking.vehicle_number
    elif parking and parking.status == 'active':
        close_session(parking, sensor_exit=True)
    elif parking:
        slot.status = 'allocated'
    else:
        slot.status, slot.current_vehicle = ('available' if slot.enabled else 'disabled'), None
    if old != occupied:
        log('SLOT_STATUS', f'{slot.slot_number}: {"occupied" if occupied else "available"}')
        record_occupancy()
    db.session.commit()
    return True


@synchronized
def close_session(parking, sensor_exit=False):
    if parking.status == 'completed':
        return parking
    if parking.status != 'active':
        raise ValueError('Parking has not been confirmed by an IR sensor.')
    now = utcnow()
    parking.exit_time, parking.status = now, 'completed'
    parking.duration_minutes = max(1, math.ceil((now - parking.entry_time).total_seconds() / 60))
    parking.fee = calculate_fee(parking.duration_minutes, current_app.config['PARKING_RATE_FIRST_HOUR'],
                                current_app.config['PARKING_RATE_ADDITIONAL_HOUR'])
    parking.active_slot_id, parking.active_vehicle = None, None
    if current_app.config['SIMULATOR_MODE'] or sensor_exit:
        parking.slot.sensor_occupied = False
    parking.slot.status = ('occupied' if parking.slot.sensor_occupied else 'available') if parking.slot.enabled else 'disabled'
    parking.slot.current_vehicle = None
    if parking.reservation:
        parking.reservation.status = 'completed'
    message = f'Parking ended for {parking.vehicle_number}. Duration: {parking.duration_minutes} minutes. Bill: {current_app.config["CURRENCY"]} {parking.fee:.2f}.'
    notify(parking.user_id, message, 'bill')
    log('EXIT', message)
    try:
        current_app.extensions['hardware'].command_gate(True)
    except ValueError as exc:
        log('GATE_ERROR', str(exc), 'ERROR')
    db.session.commit()
    from .receipts import receipt_pdf
    email_user(parking.user, 'ParkSmart parking ended - bill', message, receipt_pdf(parking), f'parksmart_bill_{parking.id}.pdf')
    return parking


@synchronized
def make_payment(parking):
    if parking.status != 'completed':
        raise ValueError('Only a completed parking session can be paid.')
    existing = Payment.query.filter_by(session_id=parking.id).first()
    if existing:
        return existing
    payment = Payment(session_id=parking.id, amount=parking.fee,
                      transaction_id='SIM-' + secrets.token_hex(8).upper(), status='success')
    parking.payment_status = 'paid'
    db.session.add(payment)
    notify(parking.user_id, f'Simulated payment successful: {payment.transaction_id}, {current_app.config["CURRENCY"]} {parking.fee:.2f}.', 'payment')
    log('PAYMENT', f'Session {parking.id}: {payment.transaction_id}')
    db.session.commit()
    from .receipts import receipt_pdf
    email_user(parking.user, 'ParkSmart paid parking receipt', 'Your simulated payment was recorded. Your receipt is attached.',
               receipt_pdf(parking), f'parksmart_receipt_{parking.id}.pdf')
    return payment


@synchronized
def expire_records():
    now = utcnow()
    for booking in Reservation.query.filter_by(status='confirmed').all():
        if booking.ends_at <= now:
            booking.status = 'expired'
            notify(booking.user_id, f'{booking.reference} expired without check-in.', 'reservation')
            log('RESERVATION_EXPIRED', booking.reference)
    cutoff = now - timedelta(minutes=current_app.config['ENTRY_TIMEOUT_MINUTES'])
    for parking in ParkingSession.query.filter_by(status='awaiting_entry').filter(ParkingSession.entry_time < cutoff).all():
        parking.status = 'cancelled'
        parking.active_slot_id, parking.active_vehicle = None, None
        parking.slot.status, parking.slot.current_vehicle = 'available', None
        if parking.reservation:
            parking.reservation.status = 'confirmed' if parking.reservation.ends_at > now else 'expired'
        notify(parking.user_id, f'Admission for {parking.vehicle_number} timed out before sensor confirmation.', 'warning')
        log('ENTRY_TIMEOUT', f'Session {parking.id}', 'WARNING')
    db.session.commit()


def slot_payload(slot, include_vehicle=False):
    now = utcnow()
    reserved = reservation_conflict(slot.id, now, now + timedelta(minutes=current_app.config['RESERVATION_LOCK_MINUTES']))
    status = slot.status
    if not slot.enabled:
        status = 'disabled'
    elif slot.sensor_health == 'fault':
        status = 'fault'
    elif status == 'available' and reserved:
        status = 'reserved'
    # Reflect the time-based protection in the current request as well as the API
    # response. The persisted slot remains available outside the five-minute lock,
    # while allocation still checks the reservation conflict independently.
    if status == 'reserved':
        slot.status = 'reserved'
    return {'id': slot.id, 'slot': slot.slot_number, 'status': status,
            'vehicle': slot.current_vehicle if include_vehicle else None,
            'sensor_health': slot.sensor_health, 'sensor_id': slot.sensor_id,
            'occupied': slot.sensor_occupied, 'enabled': slot.enabled,
            'reserved_until': reserved.ends_at.isoformat() if reserved else None,
            'reservation_reference': reserved.reference if reserved else None}


def analytics():
    now = utcnow()
    today = now.date()
    sessions = ParkingSession.query.filter(ParkingSession.status.in_(['active', 'completed'])).all()
    payments = Payment.query.filter_by(status='success').all()
    bookings = Reservation.query.all()
    slots = ParkingSlot.query.order_by(ParkingSlot.id).all()
    samples = OccupancySample.query.filter(OccupancySample.timestamp >= datetime.combine(today, datetime.min.time())).all()
    completed = [s for s in sessions if s.exit_time]
    by_hour = [{'label': f'{hour:02d}:00', 'value': sum(s.entry_time.date() == today and s.entry_time.hour == hour for s in sessions)} for hour in range(24)]
    daily = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        daily.append({'label': day.isoformat(), 'value': round(sum(p.amount for p in payments if p.payment_time.date() == day), 2)})
    utilization = [{'label': slot.slot_number, 'value': sum(s.slot_id == slot.id for s in sessions)} for slot in slots]
    most_used = max(utilization, key=lambda item: item['value'], default={'label': '—', 'value': 0})
    enabled = [s for s in slots if s.enabled]
    peak = max([s.occupied for s in samples] + [sum(s.sensor_occupied for s in enabled)])
    return {
        'today_vehicles': sum(s.entry_time.date() == today for s in sessions),
        'today_reservations': sum(r.reservation_date == today for r in bookings),
        'today_revenue': round(sum(p.amount for p in payments if p.payment_time.date() == today), 2),
        'total_revenue': round(sum(p.amount for p in payments), 2),
        'average_duration': round(sum(s.duration_minutes or 0 for s in completed) / len(completed), 1) if completed else 0,
        'peak_occupancy': peak, 'most_used_slot': most_used['label'] if most_used['value'] else '—',
        'occupancy_percentage': round(100 * sum(s.sensor_occupied for s in enabled) / len(enabled), 1) if enabled else 0,
        'vehicles_per_hour': by_hour, 'daily_revenue': daily, 'slot_utilization': utilization,
        'occupancy_history': [{'label': f'{s.timestamp:%H:%M}', 'value': round(100 * s.occupied / s.total, 1) if s.total else 0} for s in samples[-100:]],
    }
