# ParkSmart testing evidence

## Test layers

| Layer | Tool | Scope |
| --- | --- | --- |
| Unit | pytest | Fee rules, serial payload parsing |
| Integration | pytest + Flask test client | Routes, DB, reservations, sessions, payments, PDF, email fallback, authorization |
| Browser E2E | Selenium + Chrome/Edge | Registration, login, reservation, QR admission, simulator sensors, billing, payment, PDF download, admin controls |
| Coverage | coverage.py | Python application coverage |
| Report | pytest-html | Shareable HTML result |

## Commands

Run non-browser tests:

```powershell
python -m pytest -q
```

Run Selenium tests in headless Chrome:

```powershell
python -m pytest --selenium --browser chrome -q --html=reports/selenium-report.html --self-contained-html
```

Run visible browser:

```powershell
python -m pytest --selenium --headed --browser chrome -q
```

Run with Edge:

```powershell
python -m pytest --selenium --browser edge -q
```

Generate coverage:

```powershell
coverage run -m pytest -q
coverage report -m
coverage html
```

Selenium Manager downloads matching browser drivers. Chrome or Edge must exist locally. Browser tests use isolated SQLite DB files, simulator sensor API, no real payment, and no SMTP server.

## Test-case traceability

| ID | Scenario | Automated layer |
| --- | --- | --- |
| TC01 | Registration | Selenium + pytest |
| TC02 | Valid login | Selenium + pytest |
| TC03 | Invalid login | Selenium |
| TC04 | Live slot monitoring | Selenium + pytest |
| TC05 | Reservation | Selenium + pytest |
| TC06 | Duplicate reservation rejection | Selenium + pytest |
| TC07 | Slot allocation | Selenium + pytest |
| TC08 | Vehicle entry | Selenium + pytest |
| TC09 | Vehicle exit | Selenium + pytest |
| TC10 | Duration calculation | pytest |
| TC11 | Fee calculation | pytest |
| TC12 | Bill generation | Selenium + pytest |
| TC13 | Simulated payment | Selenium + pytest |
| TC14 | PDF receipt | Selenium + pytest |
| TC15 | Admin authorization | Selenium + pytest |
| TC16 | Parking full | Selenium + pytest |
| TC17 | DB persistence | pytest |
| TC18 | ESP32 malformed/disconnected state | pytest |

Selenium browser screenshots are stored under `reports/screenshots/` when browser tests run. HTML results are stored under `reports/`.
