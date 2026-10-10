from datetime import timedelta

from app import db
from app.models import Payment, ParkingSession, Reservation, utcnow
from tests.support import login, reservation_data


def test_registration_stores_hash_and_vehicle(app):
    client = app.test_client()
    response = client.post('/register', data={
        'name': 'New Driver', 'email': 'new@example.com',
        'vehicle_number': 'TN NEW 1234', 'password': 'LongEnough1',
    })
    assert response.status_code == 302
    with app.app_context():
        from app.models import User
        user = User.query.filter_by(email='new@example.com').one()
        assert user.vehicle_number == 'TN NEW 1234'
        assert user.password_hash != 'LongEnough1'
        assert user.check_password('LongEnough1')


def test_duplicate_reservation_is_rejected(app):
    client = app.test_client()
    login(client)
    data = reservation_data()
    assert client.post('/reserve', data=data).status_code == 302
    duplicate = client.post('/reserve', data=data)
    assert duplicate.status_code == 200
    assert b'Reserved for this time' in duplicate.data


def test_driver_cannot_access_admin_operations(app):
    client = app.test_client()
    login(client)
    response = client.get('/admin')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/dashboard')


def test_qr_sensor_billing_and_payment_workflow(app):
    driver = app.test_client()
    login(driver)
    response = driver.post('/reserve', data=reservation_data(slot_id=2, vehicle='TN FLOW 2000'))
    assert response.status_code == 302

    with app.app_context():
        booking = Reservation.query.filter_by(vehicle_number='TN FLOW 2000').one()
        now = utcnow()
        start = now + timedelta(minutes=2)
        end = start + timedelta(minutes=5)
        if end.date() != start.date():
            start = end.replace(hour=0, minute=2)
            end = start + timedelta(minutes=5)
        booking.reservation_date = start.date()
        booking.start_time = start.time().replace(second=0, microsecond=0)
        booking.end_time = end.time().replace(second=0, microsecond=0)
        db.session.commit()
        token = 'PARKSMART:' + booking.qr_token

    assert driver.post('/entry', data={'qr_token': token}).status_code == 302
    admin = app.test_client()
    login(admin, 'admin@parksmart.local', 'Admin@123')
    assert admin.post('/api/simulator/sensors', json={'occupied': [False, True, False, False]}).status_code == 200
    with app.app_context():
        parking = ParkingSession.query.filter_by(vehicle_number='TN FLOW 2000').one()
        assert parking.status == 'active'
        session_id = parking.id

    assert admin.post('/api/simulator/sensors', json={'occupied': [False, False, False, False]}).status_code == 200
    with app.app_context():
        parking = db.session.get(ParkingSession, session_id)
        assert parking.status == 'completed'
        assert parking.fee == 20

    assert driver.post(f'/pay/{session_id}').status_code == 302
    with app.app_context():
        assert Payment.query.filter_by(session_id=session_id).one().status == 'success'
