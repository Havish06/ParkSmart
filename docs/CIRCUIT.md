# ParkSmart circuit setup

This is the wiring contract used by `esp32/parksmart_esp32.ino`. Build and test one slot at a time, then connect the servo. The exact sensor-module voltage limits must be checked against the module being used.

## Parts

- ESP32 development board
- Four digital-output IR obstacle or presence sensor modules
- One hobby servo for the entry gate
- Regulated 5 V supply suitable for the servo current
- USB cable for ESP32 power and serial communication
- Common-ground wiring; level shifter or divider if a sensor output is 5 V logic

## Wiring

| Device connection | ESP32 connection | Supply | Signal behavior |
|---|---|---|---|
| Slot 1 sensor `OUT` | GPIO32 | Sensor VCC per datasheet | HIGH means occupied for the current installation |
| Slot 2 sensor `OUT` | GPIO33 | Sensor VCC per datasheet | HIGH means occupied for the current installation |
| Slot 3 sensor `OUT` | GPIO25 | Sensor VCC per datasheet | HIGH means occupied for the current installation |
| Slot 4 sensor `OUT` | GPIO26 | Sensor VCC per datasheet | HIGH means occupied for the current installation |
| All sensor `GND` pins | ESP32 `GND` | — | Common reference |
| Gate servo signal (orange/yellow) | GPIO27 | — | PWM control |
| Gate servo `V+` (red) | External regulated +5 V | External 5 V | Do not use ESP32 3.3 V |
| Gate servo `GND` (brown/black) | External supply GND and ESP32 `GND` | — | Common ground is required |
| ESP32 | USB-C/USB | USB | Serial link to the computer |

The sensor power and logic level depend on the exact module. Power a module at 3.3 V when its datasheet permits it. If it requires 5 V and its `OUT` pin can reach 5 V, route `OUT` through a suitable level shifter or resistor divider before it reaches the ESP32 GPIO.

## Important electrical notes
- Do **not** feed 5 V into an ESP32 GPIO.
- Do **not** power the servo from the ESP32 3.3 V rail. Servo startup current can reset or damage the board.
- Connect the external servo-supply ground to an ESP32 `GND` pin.
- Use each sensor's digital `OUT` pin, not its analog output.
- Keep sensor wires short or add appropriate noise filtering if readings fluctuate.
- The current sketch is configured for active-high sensors because the installed modules report HIGH when an object is detected. If your sensor behavior differs, change `OCCUPIED_LOW` in the sketch before uploading.

## Bring-up sequence

1. Disconnect the servo supply and wire one IR sensor, including its ground.
2. Confirm that the sensor `OUT` voltage never exceeds the ESP32 GPIO limit.
3. Upload the sketch with the servo disconnected or its signal wire isolated.
4. Open the serial monitor at **115200 baud**. A healthy board emits a slot report at startup and at least every two seconds.
5. Cover and uncover each sensor. The corresponding value in `occupied` should change between `true` and `false`.
6. Turn off the ESP32, connect the servo's signal and external 5 V supply, and verify that both grounds are connected.
7. With the Flask application stopped, send a gate command only after confirming the servo moves safely through its full range. Adjust `gate.write(90)` and `gate.write(0)` in the sketch if the mechanical gate needs different angles.
8. Set `SIMULATOR_MODE=false` and the correct serial port in `.env`, then start the Flask application.

Example Windows `.env` hardware settings:

```dotenv
SIMULATOR_MODE=false
SERIAL_PORT=COM3
SERIAL_BAUDRATE=115200
SERIAL_TIMEOUT=1.0
TOTAL_SLOTS=4
```

On Linux, use the detected device path, commonly `/dev/ttyUSB0` or `/dev/ttyACM0`.

## Serial protocol
ESP32 -> PC JSON line:
`{"type":"slots","occupied":[false,true,false,false]}`

PC -> ESP32 JSON line:
`{"cmd":"gate","open":true}`

Use 115200 baud. The supplied sketch sends one slot-state JSON line whenever a slot state changes and periodically every two seconds so the backend can distinguish a healthy idle system from a disconnected ESP32.
