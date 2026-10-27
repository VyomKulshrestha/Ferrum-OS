// FerrumOS car-kit firmware: Probots 2WD ESP32-CAM car (ESP32-CAM controller board + L298N).
//
// Speaks tools/car_kit/wire.py: one JSON datagram per command on UDP port 4210, one status
// datagram back with the same seq. tools/car_kit/mock_car.py simulates this sketch; keep
// the three in sync.
//
// Safety enforced here, whatever the host does:
//   - every drive command expires after ttl_ms (1..500): no fresh command, no motion;
//   - a closed bump switch latches the wheels off; clear_bump is refused while it is pressed;
//   - datagrams with the wrong token or the wrong keys are ignored; PWM is capped.
//
// Arduino IDE: board "AI Thinker ESP32-CAM" (esp32 core 2.x or 3.x), library ArduinoJson 7.
// Before the first run on the floor: compare the motor pins below with the kit's own sample
// code (Probots product page -> Downloads -> Code and Assembly Instructions), set PIN_TEST 1,
// and watch each wheel with the car lifted off the ground.

#include <WiFi.h>
#include <WiFiUdp.h>
#include <ArduinoJson.h>

// ---- configure ---------------------------------------------------------------------------
const char* WIFI_SSID = "your-home-wifi";      // station mode: car, laptop and phone on one network
const char* WIFI_PASS = "your-wifi-password";
const char* AP_SSID = "ferrum-car";            // fallback access point when the join fails
const char* AP_PASS = "change-me-please";      // 8+ characters
const char* TOKEN = "change-me";               // the host passes the same value as --token
const uint16_t PORT = 4210;
const int MAX_DRIVE_PWM = 200;                 // hard cap, matches the host's default max_pwm
const long MAX_TTL_MS = 500;
#define PIN_TEST 0                             // 1: spin each wheel once at boot, wheels off the ground

// L298N inputs with ENA/ENB jumpered on: left wheel IN1/IN2, right wheel IN3/IN4.
// Common ESP32-CAM car wiring; the kit's board may differ. GPIO 12 must be low at boot
// (flash-voltage strap): if the car resets in a loop, move that wire to another pin.
const int LEFT_A = 14, LEFT_B = 15, RIGHT_A = 13, RIGHT_B = 12;
// Both bump switches in parallel between BUMP_PIN and GND (normally open, internal pull-up).
const int BUMP_PIN = 2;
const int STATUS_LED = 33;                     // on-board red LED, active low (GPIO 4 flash LED stays off)

// ---- PWM across esp32 core 2.x / 3.x -------------------------------------------------------
const int PWM_FREQ = 1000, PWM_BITS = 8;

void pwmAttach(int pin, int channel) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(pin, PWM_FREQ, PWM_BITS);
#else
  ledcSetup(channel, PWM_FREQ, PWM_BITS);
  ledcAttachPin(pin, channel);
#endif
}

void pwmWrite(int pin, int channel, int duty) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(pin, duty);
#else
  ledcWrite(channel, duty);
#endif
}

// ---- state ---------------------------------------------------------------------------------
WiFiUDP udp;
int appliedL = 0, appliedR = 0;
bool driving = false, latched = false;
uint32_t deadline = 0;

void wheel(int a, int ca, int b, int cb, int pwm) {
  pwmWrite(a, ca, pwm > 0 ? pwm : 0);
  pwmWrite(b, cb, pwm < 0 ? -pwm : 0);
}

void setWheels(int l, int r) {
  appliedL = constrain(l, -MAX_DRIVE_PWM, MAX_DRIVE_PWM);
  appliedR = constrain(r, -MAX_DRIVE_PWM, MAX_DRIVE_PWM);
  wheel(LEFT_A, 2, LEFT_B, 3, appliedL);
  wheel(RIGHT_A, 4, RIGHT_B, 5, appliedR);
}

void reply(long seq, const char* op, bool pressed) {
  char out[160];
  int n = snprintf(out, sizeof(out),
                   "{\"ack\":\"%s\",\"bump\":%d,\"l\":%d,\"latched\":%d,\"r\":%d,\"seq\":%ld,\"up_ms\":%lu}",
                   op, pressed ? 1 : 0, appliedL, latched ? 1 : 0, appliedR, seq, (unsigned long)millis());
  udp.beginPacket(udp.remoteIP(), udp.remotePort());
  udp.write((const uint8_t*)out, n);
  udp.endPacket();
}

void handle(const char* buf, bool pressed) {
  JsonDocument doc;
  if (deserializeJson(doc, buf) || !doc.is<JsonObject>()) return;
  JsonObject msg = doc.as<JsonObject>();
  const char* op = msg["op"] | "";
  const char* tok = msg["tok"] | "";
  if (strcmp(tok, TOKEN) != 0 || !msg["seq"].is<long>()) return;
  long seq = msg["seq"];
  bool isDrive = strcmp(op, "drive") == 0;
  if (msg.size() != (isDrive ? 6u : 3u)) return;               // exact keys, as wire.py
  if (isDrive) {
    if (!msg["l"].is<int>() || !msg["r"].is<int>() || !msg["ttl_ms"].is<long>()) return;
    int l = msg["l"], r = msg["r"];
    long ttl = msg["ttl_ms"];
    if (ttl < 1 || ttl > MAX_TTL_MS || abs(l) > 255 || abs(r) > 255) return;
    if (!latched) {
      setWheels(l, r);
      deadline = millis() + (uint32_t)ttl;
      driving = true;
    }
  } else if (strcmp(op, "stop") == 0) {
    setWheels(0, 0);
    driving = false;
  } else if (strcmp(op, "clear_bump") == 0) {
    if (!pressed) latched = false;
  } else if (strcmp(op, "ping") != 0) {
    return;
  }
  reply(seq, op, pressed);
}

#if PIN_TEST
void pinTest() {
  const char* names[] = {"left forward", "left reverse", "right forward", "right reverse"};
  const int l[] = {140, -140, 0, 0}, r[] = {0, 0, 140, -140};
  for (int i = 0; i < 4; i++) {
    Serial.printf("pin test: %s\n", names[i]);   // a wheel turning the wrong way: swap its A/B pins
    setWheels(l[i], r[i]);
    delay(800);
    setWheels(0, 0);
    delay(600);
  }
}
#endif

void setup() {
  Serial.begin(115200);
  pinMode(STATUS_LED, OUTPUT);
  digitalWrite(STATUS_LED, HIGH);
  pwmAttach(LEFT_A, 2);
  pwmAttach(LEFT_B, 3);
  pwmAttach(RIGHT_A, 4);
  pwmAttach(RIGHT_B, 5);
  setWheels(0, 0);
  pinMode(BUMP_PIN, INPUT_PULLUP);
#if PIN_TEST
  pinTest();
#endif
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) delay(200);
  if (WiFi.status() == WL_CONNECTED) {
    WiFi.setSleep(false);                          // modem sleep adds 100+ ms of latency
    Serial.printf("ferrum-car on %s, UDP %u\n", WiFi.localIP().toString().c_str(), PORT);
  } else {
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASS);
    Serial.printf("ferrum-car access point %s at %s, UDP %u\n", AP_SSID, WiFi.softAPIP().toString().c_str(), PORT);
  }
  udp.begin(PORT);
}

void loop() {
  bool pressed = digitalRead(BUMP_PIN) == LOW;
  if (pressed && !latched) {
    latched = true;
    setWheels(0, 0);
    driving = false;
  }
  if (driving && (int32_t)(millis() - deadline) >= 0) {   // time-to-live ran out
    setWheels(0, 0);
    driving = false;
  }
  int size = udp.parsePacket();
  if (size > 0) {
    char buf[513];
    int len = udp.read(buf, sizeof(buf) - 1);
    if (size <= 512 && len > 0) {
      buf[len] = 0;
      handle(buf, pressed);
    }
  }
  // LED: solid = bump latched, blinking = driving, off = idle
  digitalWrite(STATUS_LED, latched ? LOW : (driving && (millis() / 100) % 2 ? LOW : HIGH));
}
