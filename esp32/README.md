# ESP32 integration contract

The backend expects the ESP32 to report slot states as newline-delimited JSON. The sketch sends a report on change and a heartbeat every two seconds:
{"type":"slots","occupied":[false,false,true,false]}

The backend can command the gate using:
{"cmd":"gate","open":true}
{"cmd":"gate","open":false}

Recommended pins are in [`docs/CIRCUIT.md`](../docs/CIRCUIT.md).

The current web demo runs without hardware using simulator/admin controls. With `SIMULATOR_MODE=false`, the Flask hardware worker reconnects to the configured serial port, validates these payloads, updates the four database slots, records health/log events, and sends gate commands after reservation or walk-in admission. The Arduino sketch reads GPIO 32,33,25,26 and drives the servo on GPIO27.
