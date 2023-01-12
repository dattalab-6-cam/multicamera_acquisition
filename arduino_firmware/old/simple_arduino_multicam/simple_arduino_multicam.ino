//#include <Arduino.h>

// camera trigger pins
int num_cams = 5;
int trigger_pins [5] = {A5, A1, A2, A3, A4};



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
    
    // trigger camera
    if (current_micros-previous_micros >= inv_framerate*2) {
      
      current_cycle += 1;
      previous_micros = current_micros;

      toggle_camera_triggers(trigger_pins, HIGH, num_cams);
      delayMicroseconds(exposure_time);
      toggle_camera_triggers(trigger_pins, LOW, num_cams);
    }

    // TODO check if input pins have flipped
    for (int pin : trigger_pins) { 
      if (digitalRead(pin)) {
        Serial.println("Input pin flipped");
      }
    }

  }
}



void setup() {
  
 
  for (int pin : trigger_pins) { 
    pinMode(pin, OUTPUT); 
  }

  toggle_camera_triggers(trigger_pins, LOW, num_cams);

  Serial.begin(9600);
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
