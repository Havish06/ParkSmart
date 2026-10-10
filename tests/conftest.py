import os
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from pathlib import Path
import re

import pytest

from app import create_app, db
from tests.support import TestConfig, login


def pytest_addoption(parser):
    parser.addoption('--selenium', action='store_true', help='Run Selenium browser tests.')
    parser.addoption('--headed', action='store_true', help='Show the browser during Selenium tests.')
    parser.addoption('--browser', choices=('chrome', 'edge'), default='chrome')
    parser.addoption('--artifacts', default='reports', help='Directory for browser screenshots/downloads.')


def pytest_collection_modifyitems(config, items):
    enabled = config.getoption('--selenium') or os.getenv('RUN_SELENIUM', '').lower() in {'1', 'true', 'yes'}
    if not enabled:
        skip = pytest.mark.skip(reason='Enable browser tests with --selenium or RUN_SELENIUM=1.')
        for item in items:
            if 'e2e' in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def app_factory():
    applications = []

    def make(**overrides):
        configuration = type('IsolatedTestConfig', (TestConfig,), overrides)
        application = create_app(configuration)
        applications.append(application)
        return application

    yield make
    for application in reversed(applications):
        application.extensions['hardware'].stop()
        with application.app_context():
            db.session.remove()
            db.engine.dispose()


@pytest.fixture
def app(app_factory):
    return app_factory()


@pytest.fixture
def driver_client(app):
    client = app.test_client()
    login(client)
    return client


@pytest.fixture
def admin_client(app):
    client = app.test_client()
    login(client, 'admin@parksmart.local', 'Admin@123')
    return client


@pytest.fixture(scope='session')
def artifacts(pytestconfig):
    directory = Path(pytestconfig.getoption('--artifacts')).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    driver = item.funcargs.get('browser')
    if driver is None or report.when != 'call':
        return
    directory = Path(item.config.getoption('--artifacts')).resolve() / 'screenshots'
    directory.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[^a-zA-Z0-9_-]', '_', item.name)
    path = directory / f'{name}-{report.outcome}.png'
    try:
        image = driver.get_screenshot_as_base64()
        driver.save_screenshot(str(path))
        if item.config.pluginmanager.hasplugin('html'):
            from pytest_html import extras
            report.extras = getattr(report, 'extras', []) + [extras.png(image, name='Browser screenshot')]
    except Exception as exc:
        report.sections.append(('Screenshot capture', str(exc)))
