# ParkSmart

IoT-enabled smart parking management, reservation, and billing platform built with Flask.

## Features
- Driver registration/login and admin login
- Live four-slot dashboard
- ESP32 serial integration with hardware-free simulator mode
- Automatic first-available slot allocation
- Reservations with QR token
- Parking sessions and duration tracking
- Automatic billing and simulated payment
- PDF receipt generation
- Admin analytics, logs and system health
- QR admission and walk-in entry workflow with automatic gate commands
- Sensor-confirmed entry/exit, notifications, reservation expiry and slot fault states
- Admin simulator controls for IR transitions, gate control, users, reservations and sessions
- Responsive Bootstrap UI
- Explainable reservation planner that recommends a slot using interval fit, shows why other slots are unavailable, and suggests later windows
- Admin allocation lab that replays deterministic workloads against first-fit and best-fit policies with decision traces and CSV export

## Requirements

- Python 3.10 or newer
- Windows, macOS, or Linux
- An ESP32 is optional; simulator mode is enabled by default

## Setup and run

From the project directory, create and activate a virtual environment, then install the dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start the development server:

```powershell
python run.py
```

Open <http://127.0.0.1:5000> in a browser. The application creates its default SQLite database at `instance/parksmart.db` on first startup.

## Demo accounts

The application seeds these accounts automatically:

| Role | Email | Password |
| --- | --- | --- |
| Admin | `admin@parksmart.local` | `Admin@123` |
| Driver | `driver@parksmart.local` | `Driver@123` |

These credentials are for local development only. Change them before deploying the application.

## Configuration

The application loads an optional `.env` file and reads configuration from environment variables. Copy [`.env.example`](.env.example) to `.env` and adjust it before running the server:

```powershell
Copy-Item .env.example .env
# Edit .env, especially SECRET_KEY and DATABASE_URL
python run.py
```

Useful settings include:

- `DATABASE_URL`: database connection string; SQLite is used by default
- `SIMULATOR_MODE`: use `true` for the simulator or `false` for ESP32 serial input
- `SERIAL_PORT`: ESP32 serial port, such as `COM3` on Windows
- `SERIAL_BAUDRATE`: serial speed, `115200` by default
- `TOTAL_SLOTS`: number of configured parking slots
- `PARKING_RATE_FIRST_HOUR` and `PARKING_RATE_ADDITIONAL_HOUR`: billing rates
- `CURRENCY`: currency code, `INR` by default
- `GATE_OPEN_SECONDS`: how long the gate remains open before an automatic close command
- `ENTRY_TIMEOUT_MINUTES`: cancel an admission if its IR sensor never confirms entry
- `RESERVATION_EARLY_MINUTES`: how early a driver may present a reservation QR code
- `HARDWARE_STALE_SECONDS`: mark a serial ESP32 offline when no state report arrives
- `RESERVATION_LOCK_MINUTES`: protect a reserved slot from walk-ins and show it as reserved before the booking starts; defaults to 5
- `TIMEZONE`: timezone used for reservation form input and display; the local `.env` is set to `Asia/Kolkata`, while database timestamps remain UTC

Reservations use the simulated payment module at confirmation. The reservation fee is calculated from the selected reserved duration, stored against the booking, and shown with its simulated transaction ID. Reservation times are entered and displayed in the configured local timezone. Five minutes before the arrival time, the slot changes to `RESERVED` and is excluded from walk-in allocation until the reservation ends or is checked in.

### Gmail SMTP

ParkSmart sends reservation confirmations and completed-session receipts by email when SMTP is configured. Gmail requires two-step verification and a Google **App Password**; do not use your normal Gmail password.

In `.env`, set:

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-address@gmail.com
SMTP_PASSWORD=your-16-character-google-app-password
SMTP_FROM=your-address@gmail.com
SMTP_STARTTLS=true
```

Create the App Password from your Google Account's **Security → 2-Step Verification → App passwords** page. Restart `py run.py` after changing `.env`. The application stores the notification in the database even when SMTP is unavailable, so an email failure does not prevent billing or receipt generation.

## ESP32 integration

For a hardware-free demo, keep simulator mode enabled and use the simulator controls in the admin interface. A sensor transition from free to occupied confirms an allocated entry; occupied to free closes the session, calculates the bill and sends the receipt workflow. To connect an ESP32, set `SIMULATOR_MODE=false`, configure `SERIAL_PORT`, and upload [`esp32/parksmart_esp32.ino`](esp32/parksmart_esp32.ino). Follow the wiring and electrical safety guidance in [`docs/CIRCUIT.md`](docs/CIRCUIT.md).

The serial protocol is documented in [`esp32/README.md`](esp32/README.md). The backend starts a reconnecting worker, validates every payload, records hardware health, updates slots, and sends gate commands.

## Explainable allocation and evaluation

The reservation screen includes a live planner. It uses the current sensor state and confirmed reservations to build a schedule for each slot, then chooses the **smallest containing free gap**. This best-fit policy is deliberately explainable: the interface shows the recommended slot, the remaining gap after the visit, and the reason a slot was rejected. The planner is advisory; the final reservation transaction rechecks availability inside the existing lifecycle lock.

Administrators can open **Allocation lab** from the navigation. The lab replays the same workload against a first-fit baseline and ParkSmart's best-fit policy. The fragmentation teaching case is fixed, while random workloads are reproducible from a displayed seed. Each request is included in the trace, and the entire experiment can be downloaded as CSV for a report or viva demonstration. The lab is an offline simulation and never changes parking records.

## Tests

Install the dependencies and run the test suite with the same Python launcher:

```powershell
py -m pip install -r requirements.txt
py -m pytest -q
```

If you use `python` instead of `py`, use it for both commands:

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
```

Using `py -m pytest` is recommended because it guarantees that pytest runs from the same Python installation where the project dependencies were installed. Do not run `pytest` directly if Windows is selecting a different Python installation.

Run Selenium browser tests with installed Chrome:

```powershell
python -m pytest --selenium --browser chrome -q --html=reports/selenium-report.html --self-contained-html
```

Run visible browser tests with `--headed`. Use `--browser edge` for Microsoft Edge. Full test-layer details and TC01–TC18 traceability live in [`docs/TESTING.md`](docs/TESTING.md).

### How ParkSmart Differs from Existing Parking Management Systems

ParkSmart is designed as an integrated, web-based smart parking management platform that combines IoT-based slot monitoring with reservation management, QR-based admission, parking-session tracking, billing, receipt generation, and administrative controls.

Its key practical differentiator is the combination of **ESP32 hardware integration and a built-in hardware-free simulation mode**. This allows the application to demonstrate parking workflows without requiring physical hardware during every development or testing session.

Unlike a basic parking availability dashboard, ParkSmart aims to manage the broader parking lifecycle, from driver registration and slot allocation to admission, session tracking, fee calculation, and receipt generation. It also provides administrative tools for monitoring parking operations.

The project is intended as a modular academic prototype that can be extended with real payment-gateway integration, more advanced analytics, and additional parking infrastructure as future enhancements.


## Production note

The payment button is explicitly a simulated academic payment module and generates `SIM-...` transaction IDs. SMTP email is optional: when configured, reservation confirmation and completed-session receipts are sent; without it, notifications remain in the database and the PDF is still downloadable. Before real deployment, change the seeded credentials, set a strong `SECRET_KEY`, use PostgreSQL or another production database, serve the app over HTTPS with a production WSGI server, and replace simulated payments and email with real providers.
