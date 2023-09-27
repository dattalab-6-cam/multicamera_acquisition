#include <elapsedMillis.h> // Include the elapsedMillis library

// Define the pins
const int topLedPin = 5;       // substitute your top led pin here
const int bottomLedPin = 3;     // substitute your bottom led pin here

// Define the interval for each LED (in microseconds)
const long topLedInterval = 1000000; // interval for top led (1 second)
const long bottomLedInterval = 1000000; // interval for bottom led (2 seconds)

// Define the LED states
bool state = false;

// Define the elapsedMicros variables
elapsedMicros timeElapsed;

void setup() {
  // Set the LED pins as output
  pinMode(topLedPin, OUTPUT);
  pinMode(bottomLedPin, OUTPUT);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(topLedPin, HIGH);
    digitalWrite(bottomLedPin, HIGH);
}

void loop() {
  // Check the elapsed time
  if (state && timeElapsed >= topLedInterval) {
    // State is true, means top led was ON, now turn it OFF and bottom led ON
    digitalWrite(topLedPin, LOW);
    //digitalWrite(bottomLedPin, HIGH);
    digitalWrite(LED_BUILTIN, LOW); // turn off the built-in LED
    state = !state; // Change state to false
    timeElapsed = 0; // reset the timer
  }
  else if (!state && timeElapsed >= bottomLedInterval) {
    // State is false, means bottom led was ON, now turn it OFF and top led ON
    digitalWrite(topLedPin, HIGH);
    //digitalWrite(bottomLedPin, LOW);
    digitalWrite(LED_BUILTIN, HIGH); // flash the built-in LED with the top led
    state = !state; // Change state to true
    timeElapsed = 0; // reset the timer
  }
}