# ParkSmart Locust load testing

## What this tests

Locust provides non-functional load testing. It measures how ParkSmart behaves
when multiple independent users make HTTP requests concurrently. It does not
replace the existing pytest and Selenium functional tests.

The load scenarios are defined in [`locustfile.py`](../locustfile.py):

- **DriverUser** — default read-heavy workload for dashboard, live slots,
  history, notifications, reservation planning, and fee estimates.
- **ReservationUser** — opt-in reservation-writing workload.
- **AdminMonitorUser** — opt-in admin dashboard, hardware, and analytics reads.
- **SimulatorUser** — opt-in single-user sensor transition workload.

Each virtual user has its own HTTP session and login cookie. SMTP is not used.
Use a disposable database because reservation and simulator scenarios write
records.

## Install Locust

Locust is pinned in `requirements.txt`. Install the project dependencies with:

```powershell
python -m pip install -r requirements.txt
```

## Start an isolated ParkSmart server

Do not run a load test against the normal development database. For a local
smoke test, use a disposable SQLite database and simulator mode.

PowerShell:

```powershell
$env:SIMULATOR_MODE = "true"
$env:HARDWARE_AUTOSTART = "false"
$env:DATABASE_URL = "sqlite:///instance/locust.db"
python run.py
```

The `DATABASE_URL` path is resolved relative to the project directory by the
application. Use PostgreSQL for meaningful write-concurrency measurements;
SQLite is only suitable for a small local smoke test.

## Run the default driver load test

Start the Locust web UI:

```powershell
python -m locust -f locustfile.py --host http://127.0.0.1:5000
```

Open <http://localhost:8089>. Start with a small number of users, such as 4,
and increase gradually. Record the user count, spawn rate, duration, average
response time, 95th-percentile response time, requests per second, and failure
rate.

Headless smoke test:

```powershell
python -m locust -f locustfile.py --host http://127.0.0.1:5000 --headless --user-classes DriverUser --users 4 --spawn-rate 1 --run-time 2m --csv reports/locust-driver-smoke --html reports/locust-driver-smoke.html
```

## Run the optional scenarios

Run read-only admin monitoring with two admin users:

```powershell
$env:PARKSMART_ADMIN_USERS = "2"
python -m locust -f locustfile.py --host http://127.0.0.1:5000 --headless --user-classes AdminMonitorUser --users 2 --spawn-rate 1 --run-time 5m --csv reports/locust-admin --html reports/locust-admin.html
```

Run reservation writers with four virtual users. Reservation conflicts are
valid business outcomes and are recorded by the test rather than treated as
transport failures.

```powershell
$env:PARKSMART_RESERVATION_USERS = "4"
python -m locust -f locustfile.py --host http://127.0.0.1:5000 --headless --user-classes ReservationUser --users 4 --spawn-rate 1 --run-time 2m --csv reports/locust-reservations --html reports/locust-reservations.html
```

Run the simulator separately with exactly one virtual user:

```powershell
$env:PARKSMART_SIMULATOR_USERS = "1"
python -m locust -f locustfile.py --host http://127.0.0.1:5000 --headless --user-classes SimulatorUser --users 1 --spawn-rate 1 --run-time 1m --csv reports/locust-simulator --html reports/locust-simulator.html
```

Do not run several simulator users together. Sensor state is global and the
simulator can create or close parking sessions.

## Suggested acceptance criteria

Set thresholds before running the test. For an academic local baseline, an
example starting point is:

- At least 95% of read requests succeed.
- 95th-percentile dashboard and slot requests are below 2 seconds.
- 95th-percentile planner requests are below 3 seconds.
- No unexpected 5xx responses.
- No lost or duplicated records in a reservation or simulator run.
- Response time and failure rate do not degrade sharply as users increase.

These are starting thresholds, not production guarantees. Report the machine,
Python version, database, server mode, number of slots, user count, spawn rate,
duration, and whether SQLite or PostgreSQL was used.

## User credentials and safety

The default credentials are the local seeded accounts. Override them instead
of using seeded credentials when testing a shared environment:

```powershell
$env:PARKSMART_DRIVER_EMAIL = "load-driver@example.com"
$env:PARKSMART_DRIVER_PASSWORD = "LoadDriverPass1"
$env:PARKSMART_ADMIN_EMAIL = "load-admin@example.com"
$env:PARKSMART_ADMIN_PASSWORD = "LoadAdminPass1"
```

Never point Locust at production, and do not commit load-test reports that
contain private data or real credentials.
