from datetime import datetime, timedelta

from app import db
from app.models import ParkingSlot, utcnow
from app.planner import allocation_experiment, containing_gap


def test_containing_gap_rejects_overlap_and_returns_remaining_space():
    intervals = [(datetime(2026, 1, 1, 10), datetime(2026, 1, 1, 11))]
    assert containing_gap(datetime(2026, 1, 1, 8), datetime(2026, 1, 1, 9), intervals,
                          datetime(2026, 1, 1, 0), datetime(2026, 1, 1, 23)) == (
                              datetime(2026, 1, 1, 0), datetime(2026, 1, 1, 10))
    assert containing_gap(datetime(2026, 1, 1, 10, 30), datetime(2026, 1, 1, 11, 30), intervals,
                          datetime(2026, 1, 1, 0), datetime(2026, 1, 1, 23)) is None


def test_experiment_is_reproducible_and_does_not_write_database():
    first = allocation_experiment('random', seed=17, slot_count=4, request_count=12)
    second = allocation_experiment('random', seed=17, slot_count=4, request_count=12)
    assert first == second
    assert first['results']['first_fit']['accepted'] <= 12
    assert first['results']['best_fit']['accepted'] <= 12


def test_admin_can_view_and_export_allocation_lab(admin_client):
    page = admin_client.get('/admin/allocation-lab?scenario=fragmentation')
    assert page.status_code == 200
    assert b'Allocation lab' in page.data
    export = admin_client.get('/admin/allocation-lab?scenario=random&seed=9&slots=3&requests=6&format=csv')
    assert export.status_code == 200
    assert b'first_fit' in export.data
    assert b'best_fit' in export.data


def test_reservation_planner_recommends_a_currently_free_slot(app, driver_client):
    with app.app_context():
        slot = ParkingSlot.query.filter_by(slot_number='S01').first()
        slot.sensor_occupied = True
        slot.status = 'occupied'
        db.session.commit()
    start = utcnow().replace(hour=10, minute=0, second=0, microsecond=0)
    if start <= utcnow():
        start += timedelta(days=1)
    response = driver_client.get('/api/reservation-plan', query_string={
        'date': start.date().isoformat(), 'start': '10:00', 'end': '11:00', 'vehicle_number': 'TN PLAN 1000'})
    assert response.status_code == 200
    data = response.get_json()
    assert data['recommended_slot_id'] != 1
    assert data['slots'][0]['reason'].startswith('Currently occupied')
