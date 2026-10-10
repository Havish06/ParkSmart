#include <Arduino.h>
#include <ESP32Servo.h>
#include <ArduinoJson.h>

// ParkSmart hardware contract
const int IR_PINS[4] = {32, 33, 25, 26};
const int SERVO_PIN = 27;

// The installed modules report HIGH when an object is detected.
// Set this to true if your modules report LOW when an object is detected.
const bool OCCUPIED_LOW = false;

Servo gate;
bool lastOccupied[4] = {false, false, false, false};
unsigned long lastReport = 0;

bool readOccupied(int index) {
  int value = digitalRead(IR_PINS[index]);
  return OCCUPIED_LOW ? (value == LOW) : (value == HIGH);
}

void reportSlots() {
  StaticJsonDocument<256> document;
  document["type"] = "slots";
  JsonArray occupied = document.createNestedArray("occupied");
  JsonArray raw = document.createNestedArray("raw");
  for (int index = 0; index < 4; index++) {
    int value = digitalRead(IR_PINS[index]);
    raw.add(value);
    occupied.add(OCCUPIED_LOW ? (value == LOW) : (value == HIGH));
  }
  serializeJson(document, Serial);
  Serial.println();
  lastReport = millis();
}

void handleCommand(const String &line) {
  StaticJsonDocument<128> document;
  if (deserializeJson(document, line)) {
    return;
  }
  if (document["cmd"] == "gate") {
    bool open = document["open"] | false;
    gate.write(open ? 90 : 0);
    StaticJsonDocument<96> response;
    response["type"] = "gate";
    response["open"] = open;
    serializeJson(response, Serial);
    Serial.println();
  }
}

void setup() {
  Serial.begin(115200);
  for (int index = 0; index < 4; index++) {
    pinMode(IR_PINS[index], INPUT);
  }
  gate.setPeriodHertz(50);
  gate.attach(SERVO_PIN, 500, 2400);
  gate.write(0);
  delay(500);
  reportSlots();
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    handleCommand(line);
  }

  bool changed = false;
  for (int index = 0; index < 4; index++) {
    bool current = readOccupied(index);
    if (current != lastOccupied[index]) {
      changed = true;
    }
    lastOccupied[index] = current;
  }

  if (changed || millis() - lastReport >= 2000) {
    reportSlots();
  }
  delay(100);
}
