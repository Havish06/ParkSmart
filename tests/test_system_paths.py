from datetime import timedelta

import pytest

from app import db
from app.models import (HardwareStatus, Notification, OccupancySample, ParkingSession,
                        Payment, ParkingSlot, Reservation, SystemLog, User, utcnow)
from app.receipts import receipt_pdf
from app.services import (create_reservation, expire_records, make_payment, slot_payload,
                          start_session, sync_sensor_state, walk_in)
from tests.support import future_window, login, reservation_data


def complete_session(app, slot_id=1, vehicle='TN SYSTEM 1000'):
    with app.app_context():
        user = User.query.filter_by(email='driver@parksmart.local').one()
        parking = start_session(slot_id, vehicle, user.id)
        sync_sensor_state(slot_id, True, vehicle)
        sync_sensor_state(slot_id, False)
        return parking.id


def test_fee_edges_and_zero_duration():
    from app.services import calculate_fee

    assert calculate_fee(0) == 0
    assert calculate_fee(1) == 20
    assert calculate_fee(60) == 20
    assert calculate_fee(61) == 30
    assert calculate_fee(121) == 40


def test_receipt_pdf_and_smtp_fallback(app):
    session_id = complete_session(app, slot_id=1, vehicle='TN PDF 1000')
    client = app.test_client()
    login(client)
    response = client.get(f'/bill/{session_id}/pdf')
    assert response.status_code == 200
    assert response.mimetype == 'application/pdf'
    assert response.data.startswith(b'%PDF')
    emailed = client.post(f'/bill/{session_id}/email', follow_redirects=True)
    assert emailed.status_code == 200
    assert b'SMTP not configured' in emailed.data


def test_payment_is_idempotent_and_persists_one_transaction(app):
    with app.app_context():
        session_id = complete_session(app, slot_id=2, vehicle='TN PAY 1000')
        parking = db.session.get(ParkingSession, session_id)
        first = make_payment(parking)
        second = make_payment(parking)
        assert first.id == second.id
        assert Payment.query.filter_by(session_id=session_id).count() == 1
        assert parking.payment_status == 'paid'


def test_reservation_expiry_creates_notification_and_log(app):
    with app.app_context():
        user = User.query.filter_by(email='driver@parksmart.local').one()
        start, end = future_window()
        booking = create_reservation(user, 1, 'TN EXPIRE 1000', start, end)
        now = utcnow()
        booking.reservation_date = now.date()
        booking.start_time = (now - timedelta(hours=2)).time()
        booking.end_time = (now - timedelta(minutes=1)).time()
        db.session.commit()
        expire_records()
        assert db.session.get(Reservation, booking.id).status == 'expired'
        assert Notification.query.filter_by(user_id=user.id, type='reservation').count() >= 1
        assert SystemLog.query.filter_by(event='RESERVATION_EXPIRED').count() == 1


def test_reservation_is_paid_and_locks_slot_five_minutes_before_start(app):
    with app.app_context():
        user = User.query.filter_by(email='driver@parksmart.local').one()
        start, end = future_window()
        booking = create_reservation(user, 1, 'TN RESERVED 1000', start, end)
        assert booking.payment_status == 'paid'
        assert booking.payment_transaction_id.startswith('SIM-RES-')
        assert booking.reservation_fee == 30

        now = utcnow().replace(second=0, microsecond=0)
        booking.reservation_date = now.date()
        booking.start_time = (now + timedelta(minutes=4)).time()
        booking.end_time = (now + timedelta(hours=2)).time()
        db.session.commit()

        slot = db.session.get(ParkingSlot, 1)
        assert slot_payload(slot)['status'] == 'reserved'
        walk_in_session = walk_in('TN TOO SOON 1000')
        assert walk_in_session.slot_id != 1


def test_parking_full_and_invalid_sensor_payload(app, admin_client):
    with app.app_context():
        for slot in ParkingSlot.query.order_by(ParkingSlot.id):
            slot.status = 'occupied'
            slot.sensor_occupied = True
        db.session.commit()
    response = admin_client.post('/admin/walk-in', data={'vehicle': 'TN FULL 1000'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Parking full:' in response.data
    invalid = admin_client.post('/api/simulator/sensors', json={'occupied': [True]})
    assert invalid.status_code == 400
    assert b'occupied must be a list of 4 booleans' in invalid.data


def test_reenabling_occupied_slot_preserves_occupancy(app, admin_client):
    with app.app_context():
        slot = ParkingSlot.query.filter_by(slot_number='S01').one()
        slot.enabled = False
        slot.status = 'disabled'
        slot.sensor_occupied = True
        db.session.commit()

    response = admin_client.post('/admin/slot/1/toggle', follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        slot = db.session.get(ParkingSlot, 1)
        assert slot.enabled is True
        assert slot.status == 'occupied'


def test_api_authorization_persistence_and_analytics(app_factory, tmp_path):
    database = tmp_path / 'persistence.db'
    application = app_factory(SQLALCHEMY_DATABASE_URI=f'sqlite:///{database.as_posix()}')
    client = application.test_client()
    assert client.get('/api/hardware').status_code == 302
    login(client, 'admin@parksmart.local', 'Admin@123')
    assert client.get('/api/analytics').status_code == 200
    with application.app_context():
        assert User.query.filter_by(email='driver@parksmart.local').one()
        assert db.session.get(HardwareStatus, 1)
