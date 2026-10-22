/*
ESP32 Example Code for Glove Testing Device
This is example firmware for ESP32 to communicate with the PC application
*/

#include <ArduinoJson.h>

// Pin definitions
const int PRESSURE_SENSOR_PIN = 34;      // ADC pin for pressure sensor
const int TEMPERATURE_SENSOR_PIN = 35;   // ADC pin for temperature sensor
const int LEAK_SENSOR_PIN = 32;          // Digital pin for leak detection
const int PUMP_CONTROL_PIN = 25;         // PWM pin for pump control
const int VALVE_CONTROL_PIN = 26;        // Digital pin for valve control

// Test parameters
float targetPressure = 0.0;
float targetTemperature = 0.0;
int testDuration = 0;
unsigned long testStartTime = 0;
bool testRunning = false;

// Current sensor values
float currentPressure = 0.0;
float currentTemperature = 0.0;
bool leakDetected = false;

void setup() {
  Serial.begin(115200);
  
  // Initialize pins
  pinMode(LEAK_SENSOR_PIN, INPUT);
  pinMode(PUMP_CONTROL_PIN, OUTPUT);
  pinMode(VALVE_CONTROL_PIN, OUTPUT);
  
  // Initialize sensors
  analogReadResolution(12);  // 12-bit ADC resolution
  
  // Send ready message
  sendStatus("IDLE");
  
  Serial.println("ESP32 Glove Test Device Ready");
}

void loop() {
  // Check for incoming commands
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    processCommand(command);
  }
  
  // If test is running, perform test operations
  if (testRunning) {
    runTest();
  }
  
  delay(100);
}

void processCommand(String cmd) {
  // Parse JSON command
  StaticJsonDocument<512> doc;
  DeserializationError error = deserializeJson(doc, cmd);
  
  if (error) {
    sendError("Invalid JSON");
    return;
  }
  
  const char* command = doc["cmd"];
  
  if (strcmp(command, "PING") == 0) {
    sendOK("Pong");
  }
  else if (strcmp(command, "START_TEST") == 0) {
    targetPressure = doc["params"]["pressure"];
    targetTemperature = doc["params"]["temperature"];
    testDuration = doc["params"]["duration"];
    
    startTest();
    sendOK("Test started");
  }
  else if (strcmp(command, "STOP_TEST") == 0) {
    stopTest();
    sendOK("Test stopped");
  }
  else if (strcmp(command, "GET_STATUS") == 0) {
    sendStatus(testRunning ? "RUNNING" : "IDLE");
  }
  else {
    sendError("Unknown command");
  }
}

void startTest() {
  testRunning = true;
  testStartTime = millis();
  
  // Open valve, start pump
  digitalWrite(VALVE_CONTROL_PIN, HIGH);
  analogWrite(PUMP_CONTROL_PIN, 128);  // 50% duty cycle
  
  sendStatus("RUNNING");
}

void stopTest() {
  testRunning = false;
  
  // Close valve, stop pump
  digitalWrite(VALVE_CONTROL_PIN, LOW);
  analogWrite(PUMP_CONTROL_PIN, 0);
  
  sendStatus("IDLE");
}

void runTest() {
  // Read sensors
  currentPressure = readPressure();
  currentTemperature = readTemperature();
  leakDetected = digitalRead(LEAK_SENSOR_PIN) == HIGH;
  
  // Send real-time data to PC
  sendData();
  
  // Check if test duration elapsed
  if (millis() - testStartTime >= (testDuration * 1000)) {
    stopTest();
  }
  
  // Simple pressure control (PID would be better in production)
  if (currentPressure < targetPressure * 0.95) {
    analogWrite(PUMP_CONTROL_PIN, 200);  // Increase pump speed
  } else if (currentPressure > targetPressure * 1.05) {
    analogWrite(PUMP_CONTROL_PIN, 50);   // Decrease pump speed
  } else {
    analogWrite(PUMP_CONTROL_PIN, 128);  // Maintain
  }
}

float readPressure() {
  // Read pressure sensor (0-100 kPa range)
  // This is example code - adjust for your actual sensor
  int rawValue = analogRead(PRESSURE_SENSOR_PIN);
  float voltage = (rawValue / 4095.0) * 3.3;  // Convert to voltage
  float pressure = voltage * 30.3;  // Example conversion factor
  return pressure;
}

float readTemperature() {
  // Read temperature sensor (0-50°C range)
  // This is example code - adjust for your actual sensor
  int rawValue = analogRead(TEMPERATURE_SENSOR_PIN);
  float voltage = (rawValue / 4095.0) * 3.3;
  float temperature = (voltage - 0.5) * 100.0;  // Example for TMP36
  return temperature;
}

void sendData() {
  StaticJsonDocument<256> doc;
  
  doc["type"] = "data";
  doc["pressure"] = currentPressure;
  doc["temperature"] = currentTemperature;
  doc["leak_detected"] = leakDetected;
  doc["timestamp"] = millis();
  
  serializeJson(doc, Serial);
  Serial.println();
}

void sendStatus(const char* status) {
  StaticJsonDocument<128> doc;
  
  doc["type"] = "status";
  doc["status"] = status;
  doc["timestamp"] = millis();
  
  serializeJson(doc, Serial);
  Serial.println();
}

void sendOK(const char* message) {
  StaticJsonDocument<128> doc;
  
  doc["status"] = "OK";
  doc["message"] = message;
  
  serializeJson(doc, Serial);
  Serial.println();
}

void sendError(const char* message) {
  StaticJsonDocument<128> doc;
  
  doc["status"] = "ERROR";
  doc["message"] = message;
  
  serializeJson(doc, Serial);
  Serial.println();
}
