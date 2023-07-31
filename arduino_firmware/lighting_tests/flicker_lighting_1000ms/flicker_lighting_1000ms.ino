#include <elapsedMillis.h>

// LED pins
//int LED_IR_TOP[5] = {36, 37, 14, 15, 22};
//int LED_IR_BOTTOM[5] = {23, 24, 25, 26, 27}; // Adjusted size and values



// LED 1-4: B,L,R,F

int LED_IR_TOP[5] = {36, 37, 14, 15, 18};
int LED_IR_BOTTOM[5] = {19, 22, 23}; // Adjusted size and values


// Time related variables
elapsedMillis timeElapsed;
unsigned int flashInterval = 10000000; // Time in ms

// LED state variable
bool isOn = false;

void setup() {
  
  // set up IR pins
  for (int i = 0; i < 5; i++) {
    pinMode(LED_IR_TOP[i], OUTPUT);
    pinMode(LED_IR_BOTTOM[i], OUTPUT);
    digitalWrite(LED_IR_TOP[i], HIGH);
    digitalWrite(LED_IR_BOTTOM[i], LOW);
  }
  pinMode(LED_BUILTIN, OUTPUT);

  
  digitalWrite(LED_BUILTIN, HIGH);

}

void loop() {
  if(timeElapsed > flashInterval){
    timeElapsed = 0; // Reset the timer
    isOn = !isOn;    // Change the state
    // Switch LEDs on/off depending on the state
    for (int i = 0; i < 5; i++) {
      digitalWrite(LED_IR_TOP[i], isOn ? HIGH : HIGH);
      digitalWrite(LED_IR_BOTTOM[i], isOn ? LOW : LOW);
    }
    digitalWrite(LED_BUILTIN, isOn ? HIGH : LOW);
  }
}