//#include <Arduino.h>

// LED control pins
int NIR_top    = 5;
int UVA_top    = 2;
int UVC_top    = 6;
int NIR_bottom = 4;
int UVA_bottom = 3;
int UVC_bottom = 7; 

// camera trigger pins
int num_top_cams = 5;
int num_bottom_cams = 1;
int trigger_top [5] = {A5, A1, A2, A3, A4};
int trigger_bottom [1] = {A0}; 



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
  long inv_framerate,
  long phase_shift,
  long UV_duration,
  long UV_delay 
  ) {

  // compute on-off times for each output, calculated from duration settings

  // NIR illumination during first exposure of top cam
  const long NIR_top_on  = 0;
  const long NIR_top_off = exposure_time;

  // UVA illumination before second exposure of top cam
  const long UVA_top_on  = inv_framerate - UV_delay - UV_duration ;
  const long UVA_top_off = inv_framerate - UV_delay;

  // post-UVA exposure of the top camera
  const long post_UVA_top_trigger_on  = inv_framerate;
  const long post_UVA_top_trigger_off = inv_framerate + exposure_time;

  // NIR illumination during first exposure of bottom cam
  const long NIR_bottom_on  = phase_shift;
  const long NIR_bottom_off = phase_shift + exposure_time;

  // UVA illumination before second exposure of bottom cam
  const long UVA_bottom_on  = phase_shift + inv_framerate - UV_delay - UV_duration ;
  const long UVA_bottom_off = phase_shift + inv_framerate - UV_delay;

  // post-UVA exposure of the bottom camera
  const long post_UVA_bottom_trigger_on  = phase_shift + inv_framerate;
  const long post_UVA_bottom_trigger_off = phase_shift + inv_framerate + exposure_time;


  unsigned long current_cycle = 0;
  unsigned long previous_micros = 0;
  unsigned long current_micros;

  while (current_cycle < num_cycles) {

    current_micros = micros();

    if (current_micros-previous_micros >= inv_framerate*2) {
      
      current_cycle += 1;
      previous_micros = current_micros;

      // turn on top NIR and top camera trigger
      delayMicroseconds(NIR_top_on);
      toggle_camera_triggers(trigger_top, HIGH, num_top_cams);
      digitalWrite(NIR_top, HIGH);

      // turn off top NIR and top camera trigger
      delayMicroseconds(NIR_top_off - NIR_top_on);
      toggle_camera_triggers(trigger_top, LOW, num_top_cams);
      digitalWrite(NIR_top, LOW);

      // turn on bottom NIR and bottom camera trigger
      delayMicroseconds(NIR_bottom_on - NIR_top_off);
      toggle_camera_triggers(trigger_bottom, HIGH, num_bottom_cams);
      digitalWrite(NIR_bottom, HIGH);

      // turn off bottom NIR and bottom camera trigger
      delayMicroseconds(NIR_bottom_off - NIR_bottom_on);
      toggle_camera_triggers(trigger_bottom, LOW, num_bottom_cams);
      digitalWrite(NIR_bottom, LOW);
    
      // turn on top UVA
      delayMicroseconds(UVA_top_on - NIR_bottom_off);
      digitalWrite(UVA_top, HIGH);

      // turn off top UVA
      delayMicroseconds(UVA_top_off - UVA_top_on);
      digitalWrite(UVA_top, LOW);

      // turn on top camera trigger
      delayMicroseconds(post_UVA_top_trigger_on - UVA_top_off);
      toggle_camera_triggers(trigger_top, HIGH, num_top_cams);

      // turn off top camera trigger
      delayMicroseconds(post_UVA_top_trigger_off - post_UVA_top_trigger_on);
      toggle_camera_triggers(trigger_top, LOW, num_top_cams);

      // turn on bottom UVA
      delayMicroseconds(UVA_bottom_on - post_UVA_top_trigger_off);
      digitalWrite(UVA_bottom, HIGH);

      // turn off bottom UVA
      delayMicroseconds(UVA_bottom_off - UVA_bottom_on);
      digitalWrite(UVA_bottom, LOW);

      // turn on bottom camera trigger
      delayMicroseconds(post_UVA_bottom_trigger_on - UVA_bottom_off);
      toggle_camera_triggers(trigger_bottom, HIGH, num_bottom_cams);

      // turn off bottom camera trigger
      delayMicroseconds(post_UVA_bottom_trigger_off - post_UVA_bottom_trigger_on);
      toggle_camera_triggers(trigger_bottom, LOW, num_bottom_cams);
    }
  }
}



void setup() {
  
  pinMode(NIR_top, OUTPUT);
  pinMode(UVA_top, OUTPUT);
  pinMode(UVC_top, OUTPUT); 
  
  pinMode(NIR_bottom, OUTPUT);
  pinMode(UVA_bottom, OUTPUT);
  pinMode(UVC_bottom, OUTPUT); 
 
  for (int pin : trigger_top) { pinMode(pin, OUTPUT); }
  for (int pin : trigger_bottom) { pinMode(pin, OUTPUT); }

  toggle_camera_triggers(trigger_top, LOW, num_top_cams);
  toggle_camera_triggers(trigger_bottom, LOW, num_bottom_cams);

  Serial.begin(9600);
}

void loop() {

  // run acquisition when 6 params have been sent (each param is 4 bytes)
  if (Serial.available() == 24) {

    long num_cycles     = readLongFromSerial();
    long exposure_time = readLongFromSerial();
    long inv_framerate = readLongFromSerial();
    long phase_shift   = readLongFromSerial();
    long UV_duration   = readLongFromSerial();
    long UV_delay      = readLongFromSerial();  

    runAcquisition(
      num_cycles,
      exposure_time,
      inv_framerate,
      phase_shift,
      UV_duration,
      UV_delay );

    // send message that recording is finished
    Serial.println(1);    
  }
}
