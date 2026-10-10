"""Selenium acceptance tests against a real, isolated Flask HTTP server."""
import shutil
import threading
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from werkzeug.serving import make_server

from app.models import utcnow
from tests.support import future_window, login as http_login

pytestmark = pytest.mark.e2e


def wait_for(driver, condition, timeout=15):
    return WebDriverWait(driver, timeout).until(condition)


def set_control_value(driver, name, value):
    # Native date/time keystrokes depend on OS locale. Set the canonical HTML
    # value; validation and submission still happen in the real browser.
    control = driver.find_element(By.NAME, name)
    driver.execute_script(
        "arguments[0].value = arguments[1]; "
        "arguments[0].dispatchEvent(new Event('input', {bubbles: true})); "
        "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
        control, value,
    )
    assert control.get_attribute('value') == value


def submit_form(driver, form):
    driver.execute_script('arguments[0].submit();', form)


def click_visible(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", element)


def evidence(driver, artifacts, name):
    directory = artifacts / 'screenshots'
    directory.mkdir(exist_ok=True)
    driver.save_screenshot(str(directory / f'{name}.png'))


@pytest.fixture
def e2e_server(app_factory, tmp_path):
    database = tmp_path / 'browser.db'
    app = app_factory(SQLALCHEMY_DATABASE_URI=f'sqlite:///{database.as_posix()}', GATE_OPEN_SECONDS=0.5)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}', app
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def browser_session(pytestconfig, artifacts):
    browser_name = pytestconfig.getoption('--browser')
    options = ChromeOptions() if browser_name == 'chrome' else EdgeOptions()
    if not pytestconfig.getoption('--headed'):
        options.add_argument('--headless=new')
    options.add_argument('--window-size=1440,1200')
    options.add_argument('--disable-background-networking')
    options.add_argument('--log-level=3')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    download_dir = artifacts / 'downloads'
    download_dir.mkdir(exist_ok=True)
    options.add_experimental_option('prefs', {
        'download.default_directory': str(download_dir),
        'download.prompt_for_download': False,
        'plugins.always_open_pdf_externally': True,
    })
    windows_binary = Path(
        r'C:\Program Files\Google\Chrome\Application\chrome.exe' if browser_name == 'chrome'
        else r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
    )
    if windows_binary.exists():
        options.binary_location = str(windows_binary)
    try:
        driver_class = webdriver.Chrome if browser_name == 'chrome' else webdriver.Edge
        driver = driver_class(options=options)
    except WebDriverException as exc:
        pytest.fail(f'{browser_name} startup failed: {exc.msg}', pytrace=False)
    driver.download_dir = download_dir
    driver.set_page_load_timeout(30)
    yield driver
    driver.quit()


@pytest.fixture
def browser(browser_session):
    browser_session.delete_all_cookies()
    return browser_session


def login(driver, base_url, email='driver@parksmart.local', password='Driver@123', admin=False):
    driver.get(f'{base_url}/login')
    driver.find_element(By.NAME, 'email').send_keys(email)
    driver.find_element(By.NAME, 'password').send_keys(password)
    driver.find_element(By.CSS_SELECTOR, 'form button').click()
    wait_for(driver, EC.url_contains('/admin' if admin else '/dashboard'))


def fill_reservation(driver, start, end, vehicle='TN SELENIUM 1001', force_slot=False):
    set_control_value(driver, 'date', start.strftime('%Y-%m-%d'))
    set_control_value(driver, 'start', start.strftime('%H:%M'))
    set_control_value(driver, 'end', end.strftime('%H:%M'))
    if force_slot:
        driver.execute_script(
            "const option = arguments[0].querySelector('option[value=\"1\"]'); "
            "option.disabled = false; arguments[0].value = '1';",
            driver.find_element(By.NAME, 'slot_id'),
        )
    else:
        Select(driver.find_element(By.NAME, 'slot_id')).select_by_value('1')
    set_control_value(driver, 'vehicle_number', vehicle)


def assert_alert(driver, text):
    wait_for(driver, EC.text_to_be_present_in_element((By.CSS_SELECTOR, '.alert'), text))


def test_complete_driver_admin_browser_workflow(e2e_server, browser, artifacts):
    base_url, _app = e2e_server
    driver = browser
    email = f'selenium-{uuid4().hex[:10]}@example.com'
    vehicle = 'TN SELENIUM 1001'
    driver.get(f'{base_url}/register')
    for name, value in [('name', 'Selenium Driver'), ('email', email),
                        ('vehicle_number', vehicle), ('password', 'SeleniumPass1')]:
        driver.find_element(By.NAME, name).send_keys(value)
    driver.find_element(By.CSS_SELECTOR, 'form button').click()
    wait_for(driver, EC.url_contains('/login'))
    login(driver, base_url, email, 'SeleniumPass1')
    driver.find_element(By.CSS_SELECTOR, 'a[href*="reserve"]').click()

    start = utcnow().replace(second=0, microsecond=0) + timedelta(minutes=2)
    end = start + timedelta(minutes=5)
    if start.date() != end.date():
        start = end.replace(hour=0, minute=2)
        end = start + timedelta(minutes=5)
    fill_reservation(driver, start, end, vehicle)
    driver.find_element(By.CSS_SELECTOR, 'form button').click()
    wait_for(driver, EC.url_contains('/reservation/'))
    image = driver.find_element(By.CSS_SELECTOR, '.qr-code')
    wait_for(driver, lambda current: current.execute_script('return arguments[0].naturalWidth > 0', image))
    assert driver.find_element(By.CSS_SELECTOR, 'h2').text.startswith('PS-')
    qr_token = driver.find_element(By.CSS_SELECTOR, '.token').text
    assert qr_token.startswith('PARKSMART:')
    evidence(driver, artifacts, '01-reservation-qr')

    driver.find_element(By.CSS_SELECTOR, 'a[href*="/entry"]').click()
    driver.find_element(By.NAME, 'qr_token').send_keys(qr_token)
    submit_form(driver, driver.find_elements(By.TAG_NAME, 'form')[0])
    wait_for(driver, EC.url_contains('/dashboard'))
    assert 'Awaiting IR confirmation' in driver.find_element(By.TAG_NAME, 'main').text
    driver.get(f'{base_url}/entry')
    qr_input = driver.find_element(By.NAME, 'qr_token')
    qr_input.send_keys(qr_token)
    submit_form(driver, driver.find_elements(By.TAG_NAME, 'form')[0])
    assert_alert(driver, 'already been used')

    driver.get(f'{base_url}/logout')
    login(driver, base_url, 'admin@parksmart.local', 'Admin@123', admin=True)
    sensor = driver.find_element(By.CSS_SELECTOR, '.sensor-toggle[data-index="0"]')
    click_visible(driver, sensor)
    wait_for(driver, lambda current: 'btn-danger' in sensor.get_attribute('class'))
    evidence(driver, artifacts, '02-admin-sensor-occupied')
    click_visible(driver, sensor)
    wait_for(driver, lambda current: 'btn-danger' not in sensor.get_attribute('class'))

    driver.get(f'{base_url}/logout')
    login(driver, base_url, email, 'SeleniumPass1')
    driver.find_element(By.CSS_SELECTOR, 'a[href*="history"]').click()
    driver.find_element(By.LINK_TEXT, 'unpaid').click()
    assert driver.find_element(By.CSS_SELECTOR, 'form[action*="/pay/"] button').is_displayed()
    evidence(driver, artifacts, '03-generated-bill')
    driver.find_element(By.CSS_SELECTOR, 'form[action*="/pay/"] button').click()
    assert_alert(driver, 'Simulated payment successful')
    assert 'SIM-' in driver.find_element(By.CSS_SELECTOR, '.receipt').text
    evidence(driver, artifacts, '04-paid-receipt')

    existing = {path.name: path.stat().st_mtime_ns for path in driver.download_dir.glob('*.pdf')}
    driver.find_element(By.LINK_TEXT, 'Download PDF').click()
    receipts = wait_for(driver, lambda current: [
        path for path in current.download_dir.glob('*.pdf')
        if path.stat().st_mtime_ns != existing.get(path.name) and path.stat().st_size > 0
    ])
    assert receipts[0].read_bytes().startswith(b'%PDF')
    shutil.copy2(receipts[0], artifacts / 'sample-paid-receipt.pdf')
    driver.find_element(By.CSS_SELECTOR, 'form[action$="/email"] button').click()
    assert_alert(driver, 'SMTP not configured')
    driver.get(f'{base_url}/notifications')
    assert 'Simulated payment successful' in driver.find_element(By.TAG_NAME, 'main').text
    evidence(driver, artifacts, '05-notifications')
    driver.get(f'{base_url}/history')
    assert driver.find_element(By.LINK_TEXT, 'paid').is_displayed()


def test_invalid_login_driver_authorization_and_logout(e2e_server, browser):
    base_url, _app = e2e_server
    browser.get(base_url)
    assert 'Smart parking.' in browser.find_element(By.TAG_NAME, 'h1').text
    browser.get(f'{base_url}/login')
    browser.find_element(By.NAME, 'email').send_keys('driver@parksmart.local')
    browser.find_element(By.NAME, 'password').send_keys('WrongPassword')
    browser.find_element(By.CSS_SELECTOR, 'form button').click()
    assert_alert(browser, 'Invalid email or password.')
    login(browser, base_url)
    browser.get(f'{base_url}/admin')
    wait_for(browser, EC.url_contains('/dashboard'))
    assert_alert(browser, 'Administrator access required.')
    browser.get(f'{base_url}/entry')
    qr_input = browser.find_element(By.NAME, 'qr_token')
    qr_input.send_keys('PARKSMART:invalid')
    assert qr_input.get_attribute('value') == 'PARKSMART:invalid'
    submit_form(browser, browser.find_elements(By.TAG_NAME, 'form')[0])
    assert_alert(browser, 'Invalid reservation QR token.')
    browser.get(f'{base_url}/logout')
    browser.get(f'{base_url}/dashboard')
    wait_for(browser, EC.url_contains('/login'))


def test_reservation_overlap_time_validation_and_cancel(e2e_server, browser):
    base_url, _app = e2e_server
    login(browser, base_url)
    start, end = future_window()
    browser.get(f'{base_url}/reserve')
    fill_reservation(browser, start, end)
    submit_form(browser, browser.find_element(By.CSS_SELECTOR, 'form.card'))
    if '/reservation/' not in browser.current_url:
        pytest.fail(f'Initial reservation rejected: {browser.find_element(By.CSS_SELECTOR, ".alert").text}')
    wait_for(browser, EC.url_contains('/reservation/'))
    browser.get(f'{base_url}/reserve')
    fill_reservation(browser, start, end, 'TN OTHER 1002', force_slot=True)
    submit_form(browser, browser.find_element(By.CSS_SELECTOR, 'form.card'))
    assert_alert(browser, 'Reserved for this time')
    fill_reservation(browser, start, start - timedelta(hours=1))
    submit_form(browser, browser.find_element(By.CSS_SELECTOR, 'form.card'))
    assert_alert(browser, 'Choose a future arrival')
    browser.get(f'{base_url}/dashboard')
    submit_form(browser, browser.find_element(By.CSS_SELECTOR, 'form[action$="/cancel"]'))
    assert_alert(browser, 'Reservation cancelled.')
    assert browser.find_element(By.CSS_SELECTOR, '.status-cancelled').text == 'cancelled'


def test_live_dashboard_updates_without_reload(e2e_server, browser):
    base_url, app = e2e_server
    login(browser, base_url)
    title = browser.find_element(By.CSS_SELECTOR, '[data-slot-id="1"] h3')
    assert title.text == 'AVAILABLE'
    with app.test_client() as device:
        http_login(device, 'admin@parksmart.local', 'Admin@123')
        assert device.post('/api/simulator/sensors', json={'occupied': [True, False, False, False]}).status_code == 200
    wait_for(browser, lambda current: title.text == 'OCCUPIED')
    with app.test_client() as device:
        http_login(device, 'admin@parksmart.local', 'Admin@123')
        device.post('/api/simulator/sensors', json={'occupied': [False] * 4})
    wait_for(browser, lambda current: title.text == 'AVAILABLE')


def test_walk_in_allocation_and_parking_full(e2e_server, browser):
    base_url, _app = e2e_server
    login(browser, base_url, 'admin@parksmart.local', 'Admin@123', admin=True)
    for index in range(1, 5):
        browser.find_element(By.NAME, 'vehicle').send_keys(f'TN WALK {index}')
        submit_form(browser, browser.find_element(By.CSS_SELECTOR, 'form[action$="/walk-in"]'))
        assert_alert(browser, f'assigned to S{index:02d}')
    browser.get(f'{base_url}/logout')
    login(browser, base_url)
    browser.get(f'{base_url}/entry')
    submit_form(browser, browser.find_element(By.CSS_SELECTOR, "form:has(input[name='vehicle_number'])"))
    assert_alert(browser, 'Parking full:')


def test_admin_slot_user_gate_and_analytics_controls(e2e_server, browser):
    base_url, app = e2e_server
    login(browser, base_url, 'admin@parksmart.local', 'Admin@123', admin=True)
    browser.find_element(By.CSS_SELECTOR, 'form[action="/admin/slot/1/toggle"] button').click()
    assert_alert(browser, 'S01 is now disabled.')
    browser.find_element(By.CSS_SELECTOR, 'form[action="/admin/slot/1/toggle"] button').click()
    assert_alert(browser, 'S01 is now enabled.')
    click_visible(browser, browser.find_element(By.CSS_SELECTOR, 'form[action="/admin/user/2/toggle"] button'))
    assert_alert(browser, 'driver@parksmart.local is now disabled.')
    click_visible(browser, browser.find_element(By.CSS_SELECTOR, "form:has(input[value='open']) button"))
    assert_alert(browser, 'Gate command sent.')
    with app.test_client() as monitor:
        http_login(monitor, 'admin@parksmart.local', 'Admin@123')
        wait_for(browser, lambda current: monitor.get('/api/hardware').get_json()['gate'] == 'closed')
    wait_for(browser, lambda current: current.find_element(By.ID, 'analytics-duration').text == '0 min')
    assert len(browser.find_elements(By.CSS_SELECTOR, '#vehicles-chart .bar-item')) == 24
    browser.get(f'{base_url}/logout')
    browser.get(f'{base_url}/login')
    browser.find_element(By.NAME, 'email').send_keys('driver@parksmart.local')
    browser.find_element(By.NAME, 'password').send_keys('Driver@123')
    browser.find_element(By.CSS_SELECTOR, 'form button').click()
    assert_alert(browser, 'Invalid email or password.')
