#include <elapsedMillis.h>

// LED pins
int IR1_top    = 5;
int IR2_top    = 13;  // not actually used 
int IR1_bottom = 4; 
int IR2_bottom = 10;  // not actually used on Eli's rig

// Time related variables
elapsedMillis timeElapsed;
unsigned int flashInterval = 1000; // Time in ms

// LED state variable
bool isOn = false;

void setup() {
  // set up IR pins
  pinMode(IR1_top, OUTPUT);
  pinMode(IR1_bottom, OUTPUT);
  pinMode(LED_BUILTIN, OUTPUT);
}

void loop() {
  if(timeElapsed > flashInterval){
    timeElapsed = 0; // Reset the timer
    isOn = !isOn;    // Change the state
    // Switch LEDs on/off depending on the state
    digitalWrite(IR1_top, isOn ? HIGH : LOW);
    digitalWrite(IR1_bottom, isOn ? LOW : HIGH);
    digitalWrite(LED_BUILTIN, isOn ? HIGH : LOW);
  }
}