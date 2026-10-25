#include <Arduino.h>
#include <ESP32Servo.h>
#include <ArduinoJson.h>

// ParkSmart hardware contract
const int IR_PINS[4] = { 23, 22, 21, 19 };
const int SERVO_PIN = 27;
const bool OCCUPIED_LOW = true;
Servo gate;
bool lastOccupied[4] = { false, false, false, false };
unsigned long lastReport = 0;

bool readOccupied(int i) {
  int v = digitalRead(IR_PINS[i]);
  return OCCUPIED_LOW ? (v == LOW) : (v == HIGH);
}

void reportSlots() {
  StaticJsonDocument<256> doc;
  doc["type"] = "slots";
  JsonArray a = doc.createNestedArray("occupied");
  for (int i = 0; i < 4; i++) a.add(readOccupied(i));
  serializeJson(doc, Serial);
  Serial.println();
  lastReport = millis();
}

void handleCommand(const String &line) {
  StaticJsonDocument<128> doc;
  if (deserializeJson(doc, line)) return;
  if (doc["cmd"] == "gate") {
    bool open = doc["open"] | false;
    gate.write(open ? 90 : 0);
  }
}

void setup() {
  Serial.begin(115200);
  for (int i = 0; i < 4; i++) pinMode(IR_PINS[i], INPUT);
  gate.attach(SERVO_PIN);
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
  for (int i = 0; i < 4; i++) {
    bool now = readOccupied(i);
    if (now != lastOccupied[i]) changed = true;
    lastOccupied[i] = now;
  }
  if (changed || millis() - lastReport >= 2000) reportSlots();
  delay(100);
}
