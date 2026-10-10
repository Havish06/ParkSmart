import io
import json

from app.hardware import ESP32Serial


class FakeSerial:
    def __init__(self, payload):
        self.payload = io.BytesIO(payload.encode())

    def readline(self):
        return self.payload.readline()


def test_esp32_valid_slot_payload_is_parsed():
    adapter = ESP32Serial('fake')
    adapter.ser = FakeSerial(json.dumps({'type': 'slots', 'occupied': [False, True, False, True]}) + '\n')
    adapter.connected = True

    data = adapter.read_state()

    assert data['type'] == 'slots'
    assert adapter.latest == [False, True, False, True]
    assert adapter.last_seen is not None


def test_esp32_malformed_payload_is_ignored():
    adapter = ESP32Serial('fake')
    adapter.ser = FakeSerial('{not-json}\n')
    adapter.connected = True

    assert adapter.read_state() is None
    assert 'Invalid ESP32 payload' in adapter.last_error


def test_esp32_rejects_invalid_slot_shape():
    adapter = ESP32Serial('fake')
    adapter.ser = FakeSerial(json.dumps({'type': 'slots', 'occupied': [True, False]}) + '\n')
    adapter.connected = True

    data = adapter.read_state()

    assert data['type'] == 'slots'
    assert adapter.latest == [False, False, False, False]


def test_hardware_controller_rejects_invalid_slot_shape(app):
    controller = app.extensions['hardware']

    try:
        controller._process_states([True])
    except ValueError as exc:
        assert str(exc) == 'occupied must be a list of 4 booleans'
    else:
        raise AssertionError('invalid hardware state was accepted')
