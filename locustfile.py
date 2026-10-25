"""ParkSmart non-functional load scenarios for Locust.

The default scenario is read-heavy: authenticated drivers view the dashboard,
slot state, history, and reservation planner. Write-heavy reservation and
simulator users are opt-in because they intentionally change parking data.

Example:
    python -m locust -f locustfile.py --host http://127.0.0.1:5000

Run the web UI at http://localhost:8089, or use the headless commands in
docs/LOCUST_TESTING.md.
"""

from datetime import datetime, timedelta
import hashlib
import os
from uuid import uuid4

from locust import HttpUser, between, tag, task
from locust.exception import StopUser


def env_int(name, default=0):
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def stable_number(value, modulo):
    digest = hashlib.sha256(value.encode('utf-8')).hexdigest()
    return int(digest[:8], 16) % modulo


def reservation_window(seed):
    """Return a future, same-day window accepted by the reservation form."""
    day = datetime.now().date() + timedelta(days=1)
    offset = stable_number(seed, 600)
    start = datetime.combine(day, datetime.min.time()).replace(hour=8) + timedelta(minutes=offset)
    return start, start + timedelta(minutes=5)


def response_body(response):
    return response.text[:500].replace('\n', ' ')


class AuthenticatedUser(HttpUser):
    """Shared login behavior for the load-test user types."""

    abstract = True

    def login_as(self, email, password, destination):
        with self.client.get('/login', name='GET /login', catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f'login page returned {response.status_code}')
                raise StopUser()

        with self.client.post(
            '/login',
            data={'email': email, 'password': password},
            name='POST /login',
            allow_redirects=False,
            catch_response=True,
        ) as response:
            location = response.headers.get('Location', '')
            if response.status_code != 302 or not location.endswith(destination):
                response.failure(
                    f'login returned {response.status_code} {location!r}: {response_body(response)}'
                )
                raise StopUser()

    def get_expected(self, path, name=None):
        with self.client.get(path, name=name or f'GET {path}', catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f'expected 200, got {response.status_code}: {response_body(response)}')


@tag('driver')
class DriverUser(AuthenticatedUser):
    """Read-heavy driver workload suitable for the default load test."""

    weight = 10
    wait_time = between(2, 5)

    def on_start(self):
        self.login_as(
            os.getenv('PARKSMART_DRIVER_EMAIL', 'driver@parksmart.local'),
            os.getenv('PARKSMART_DRIVER_PASSWORD', 'Driver@123'),
            '/dashboard',
        )
        self.vehicle = f'LT-{uuid4().hex[:10].upper()}'

    @task(5)
    def dashboard(self):
        self.get_expected('/dashboard')

    @task(3)
    def live_slots(self):
        self.get_expected('/api/slots')

    @task(2)
    def history(self):
        self.get_expected('/history')

    @task(1)
    def notifications(self):
        self.get_expected('/notifications')

    @task(1)
    def reservation_planner(self):
        start, end = reservation_window(self.vehicle)
        path = '/api/reservation-plan'
        query = {
            'date': start.date().isoformat(),
            'start': start.strftime('%H:%M'),
            'end': end.strftime('%H:%M'),
            'vehicle_number': self.vehicle,
        }
        with self.client.get(path, params=query, name='GET /api/reservation-plan', catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f'expected 200, got {response.status_code}: {response_body(response)}')

    @task(1)
    def fee_estimate(self):
        self.get_expected('/api/fee-estimate?minutes=60')


@tag('reservation')
class ReservationUser(AuthenticatedUser):
    """Opt-in reservation writer. Rejections are recorded as business outcomes."""

    weight = 0
    fixed_count = env_int('PARKSMART_RESERVATION_USERS')
    wait_time = between(5, 10)

    def on_start(self):
        self.login_as(
            os.getenv('PARKSMART_DRIVER_EMAIL', 'driver@parksmart.local'),
            os.getenv('PARKSMART_DRIVER_PASSWORD', 'Driver@123'),
            '/dashboard',
        )
        self.vehicle = f'LT-RES-{uuid4().hex[:8].upper()}'

    @task
    def create_reservation(self):
        start, end = reservation_window(self.vehicle)
        data = {
            'date': start.date().isoformat(),
            'start': start.strftime('%H:%M'),
            'end': end.strftime('%H:%M'),
            'slot_id': str(1 + stable_number(self.vehicle, 4)),
            'vehicle_number': self.vehicle,
        }
        with self.client.post(
            '/reserve',
            data=data,
            name='POST /reserve',
            allow_redirects=False,
            catch_response=True,
        ) as response:
            if response.status_code == 302:
                location = response.headers.get('Location', '')
                if not location.startswith('/reservation/'):
                    response.failure(f'unexpected reservation redirect: {location!r}')
            elif response.status_code == 200 and any(
                message in response.text
                for message in ('Reserved for this time', 'already has a reservation', 'currently occupied')
            ):
                response.success()
            else:
                response.failure(f'unexpected reservation result {response.status_code}: {response_body(response)}')


@tag('admin')
class AdminMonitorUser(AuthenticatedUser):
    """Opt-in read-only administrator monitoring workload."""

    weight = 0
    fixed_count = env_int('PARKSMART_ADMIN_USERS')
    wait_time = between(3, 6)

    def on_start(self):
        self.login_as(
            os.getenv('PARKSMART_ADMIN_EMAIL', 'admin@parksmart.local'),
            os.getenv('PARKSMART_ADMIN_PASSWORD', 'Admin@123'),
            '/admin',
        )

    @task(3)
    def admin_dashboard(self):
        self.get_expected('/admin')

    @task(2)
    def hardware_health(self):
        self.get_expected('/api/hardware')

    @task(1)
    def analytics(self):
        self.get_expected('/api/analytics')


@tag('simulator')
class SimulatorUser(AuthenticatedUser):
    """Opt-in single-user simulator workload; use one user only."""

    weight = 0
    fixed_count = min(1, env_int('PARKSMART_SIMULATOR_USERS'))
    wait_time = between(10, 20)

    def on_start(self):
        self.login_as(
            os.getenv('PARKSMART_ADMIN_EMAIL', 'admin@parksmart.local'),
            os.getenv('PARKSMART_ADMIN_PASSWORD', 'Admin@123'),
            '/admin',
        )
        self.occupied = False

    @task
    def sensor_transition(self):
        self.occupied = not self.occupied
        states = [self.occupied, False, False, False]
        with self.client.post(
            '/api/simulator/sensors',
            json={'occupied': states},
            name='POST /api/simulator/sensors',
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f'expected 200, got {response.status_code}: {response_body(response)}')
