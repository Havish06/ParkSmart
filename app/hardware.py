"""ESP32 serial adapter and the simulator used by the browser demo."""
import json
import threading
import time
from datetime import datetime, timedelta
from .models import utcnow

try:
    import serial
except ImportError:  # pragma: no cover - optional dependency in deployments
    serial = None


class ESP32Serial:
    def __init__(self, port, baudrate=115200, timeout=1, expected_slots=4):
        self.port, self.baudrate, self.timeout = port, baudrate, timeout
        self.expected_slots = expected_slots
        self.ser = None
        self.connected = False
        self.latest = [False] * expected_slots
        self.last_seen = None
        self.last_error = ''
        self.lock = threading.Lock()

    def connect(self):
        if serial is None:
            self.last_error = 'pyserial is not installed'
            return False
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            self.connected = True
            self.last_error = ''
            return True
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            return False

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser, self.connected = None, False

    def send_gate(self, open_gate):
        if not self.connected or not self.ser:
            return False
        try:
            payload = {'cmd': 'gate', 'open': bool(open_gate)}
            with self.lock:
                self.ser.write((json.dumps(payload) + '\n').encode())
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self.connected = False
            return False

    def read_state(self):
        if not self.connected or not self.ser:
            return None
        try:
            line = self.ser.readline().decode(errors='ignore').strip()
        except Exception as exc:
            self.last_error = str(exc)
            self.connected = False
            return None
        if not line:
            return None
        try:
            data = json.loads(line)
        except (TypeError, ValueError):
            self.last_error = f'Invalid ESP32 payload: {line[:100]}'
            return None
        if data.get('type') == 'slots':
            occupied = data.get('occupied')
            if (isinstance(occupied, list) and len(occupied) == self.expected_slots
                    and all(isinstance(v, bool) for v in occupied)):
                self.latest = occupied
                self.last_seen = utcnow()
        return data


class HardwareController:
    def __init__(self, app):
        self.app = app
        self.stop_event = threading.Event()
        self.thread = None
        self.adapter = None
        self.gate_timer = None
        self.simulator_states = [False] * app.config['TOTAL_SLOTS']

    @property
    def simulator(self):
        return self.app.config['SIMULATOR_MODE']

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        if not self.simulator:
            self.adapter = ESP32Serial(
                self.app.config['SERIAL_PORT'],
                self.app.config['SERIAL_BAUDRATE'],
                self.app.config['SERIAL_TIMEOUT'],
                self.app.config['TOTAL_SLOTS'],
            )
        self.thread = threading.Thread(target=self._worker, name='parksmart-hardware', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.adapter:
            self.adapter.close()

    def _set_status(self, connected, gate=None, error=''):
        from . import db
        from .models import HardwareStatus
        status = db.session.get(HardwareStatus, 1)
        if not status:
            status = HardwareStatus(id=1)
            db.session.add(status)
        status.connected = connected
        status.last_seen = utcnow() if connected else status.last_seen
        if gate:
            status.gate_state = gate
            status.gate_close_at = utcnow() + timedelta(seconds=self.app.config['GATE_OPEN_SECONDS']) if gate == 'open' else None
        status.gate_health = 'normal' if connected or self.simulator else 'offline'
        status.last_error = error[:500]
        db.session.commit()

    def command_gate(self, open_gate):
        if self.adapter and not self.adapter.connected and not self.adapter.connect():
            self._set_status(False, error=self.adapter.last_error)
            raise ValueError('ESP32 is offline; gate command was not delivered.')
        delivered = self.adapter.send_gate(open_gate) if self.adapter else True
        if not delivered:
            error = self.adapter.last_error if self.adapter else 'Gate command failed'
            self._set_status(False, error=error)
            raise ValueError(error)
        self._set_status(True, 'open' if open_gate else 'closed')
        if open_gate:
            if self.gate_timer:
                self.gate_timer.cancel()
            self.gate_timer = threading.Timer(self.app.config['GATE_OPEN_SECONDS'], self._close_gate)
            self.gate_timer.daemon = True
            self.gate_timer.start()
        return True

    def _close_gate(self):
        with self.app.app_context():
            try:
                self.command_gate(False)
            except ValueError:
                pass

    def update_simulator(self, states):
        with self.app.app_context():
            if not self.simulator:
                raise ValueError('Simulator mode is disabled; use the ESP32 serial device.')
            if not isinstance(states, list) or len(states) != self.app.config['TOTAL_SLOTS'] or not all(isinstance(v, bool) for v in states):
                raise ValueError(f'occupied must be a list of {self.app.config["TOTAL_SLOTS"]} booleans')
            self.simulator_states = states
            self._process_states(states)

    def _process_states(self, states):
        from .services import sync_sensor_state
        expected = self.app.config['TOTAL_SLOTS']
        if (not isinstance(states, list) or len(states) != expected
                or not all(isinstance(value, bool) for value in states)):
            raise ValueError(f'occupied must be a list of {expected} booleans')
        for index, occupied in enumerate(states, start=1):
            sync_sensor_state(index, occupied, f'SIM-{index}' if occupied and self.simulator else None)
        self._set_status(True)

    def _mark_sensor_fault(self, reason):
        from . import db
        from .models import ParkingSlot, SystemLog
        slots = ParkingSlot.query.order_by(ParkingSlot.id).all()
        changed = False
        for slot in slots:
            if slot.sensor_health != 'fault':
                slot.sensor_health = 'fault'
                changed = True
        if changed:
            db.session.add(SystemLog(event='SENSOR_FAULT', severity='ERROR', description=reason[:500]))
            db.session.commit()

    def _worker(self):
        with self.app.app_context():
            while not self.stop_event.is_set():
                try:
                    if self.simulator:
                        self._set_status(True)
                    else:
                        if not self.adapter.connected:
                            self.adapter.connect()
                            self._set_status(self.adapter.connected, error=self.adapter.last_error)
                            if not self.adapter.connected:
                                self._mark_sensor_fault(self.adapter.last_error or 'ESP32 connection failed')
                        
                        data = self.adapter.read_state()
                        if data and data.get('type') == 'slots':
                            self._process_states(data['occupied'])

                        elif self.adapter.last_seen and (utcnow() - self.adapter.last_seen).total_seconds() > self.app.config['HARDWARE_STALE_SECONDS']:
                            self._set_status(False, error='No slot report received within stale timeout')
                            self._mark_sensor_fault('ESP32 heartbeat stale; sensor state cannot be trusted')
                    from .services import expire_records
                    expire_records()
                except Exception as exc:
                    self.app.logger.exception('Hardware worker failure')
                    try:
                        self._set_status(False, error=str(exc))
                    except Exception:
                        pass
                self.stop_event.wait(1 if self.simulator else 0.2)


hardware = None
