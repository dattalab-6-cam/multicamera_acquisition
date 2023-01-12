#include <Arduino.h>

// camera trigger pins
int NUM_CAMS = 5;
int BAUDRATE = 9600; 
int SERIAL_START_DELAY = 100; // Time for USB Terminal to start
int trigger_pins [5] = {A5, A1, A2, A3, A4};
int input_pins [5] = {PB0, PB1, PB2, PB3, PB4};

enum INPUT_MASK {
    IN0_MASK = 1 << 0,
    IN1_MASK = 1 << 1,
    IN2_MASK = 1 << 2,
    IN3_MASK = 1 << 3,
    IN4_MASK = 1 << 4,
    IN5_MASK = 1 << 5,
    IN6_MASK = 1 << 6,
    IN7_MASK = 1 << 7,
};

long readLongFromSerial() {
  union u_tag { byte b[4]; long lval; } u;
  u.b[0] = Serial.read();
  u.b[1] = Serial.read();
  u.b[2] = Serial.read();
  u.b[3] = Serial.read();
  return u.lval;
}


void toggle_camera_triggers(int pins[], byte state, int num) {
  for (int i=0; i < num; i++) {
    digitalWrite(pins[i], state);
  }
}



void runAcquisition(
  long num_cycles,
  long exposure_time,
  long inv_framerate
  ) {

  unsigned long current_cycle = 0;
  unsigned long previous_micros = 0;
  unsigned long current_micros;

  while (current_cycle < num_cycles) {

    current_micros = micros();

    if (current_micros-previous_micros >= inv_framerate*2) {
      
      current_cycle += 1;
      previous_micros = current_micros;

      toggle_camera_triggers(trigger_pins, HIGH, NUM_CAMS);
      delayMicroseconds(exposure_time);
      toggle_camera_triggers(trigger_pins, LOW, NUM_CAMS);
    }

    // TODO check if input pins have flipped
    for (int pin : input_pins) { 
        if (digitalRead(pin)) {
            // do something
        } else {
            // do something else
        }
    }
  }
}



void setup() {
  
 
  for (int pin : trigger_pins) { 
    pinMode(pin, OUTPUT); 
  }

  toggle_camera_triggers(trigger_pins, LOW, NUM_CAMS);

  Serial.begin(BAUDRATE);
  delay(SERIAL_START_DELAY);
}

void loop() {

  //Serial.println("Waiting"); 

  // run acquisition when 3 params have been sent (each param is 4 bytes)
  // params are num_cycles, exposure_time, inv_framerate
  if (Serial.available() == 12) {

    Serial.println("Start");    

    long num_cycles    = readLongFromSerial();
    long exposure_time = readLongFromSerial();
    long inv_framerate = readLongFromSerial();

    runAcquisition(
      num_cycles,
      exposure_time,
      inv_framerate
      );

    // send message that recording is finished
    Serial.println("Finished");    
  }
}
