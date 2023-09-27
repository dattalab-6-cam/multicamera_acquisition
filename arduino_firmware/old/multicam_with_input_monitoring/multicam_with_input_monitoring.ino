
// #include <Arduino.h>

const int SERIAL_START_DELAY = 1000;

// camera trigger pins
int num_cams = 8;
int trigger_pins[12] = {A1, A2, A3, A4, A5, 2, 15, 11, 7, 13, 19, 25};

// Define the input GPIOs
int num_input = 4;
const int input_pins[4] = {22, 24, 26, 28};

// Set the initial state of input pins
int input_state[4] = {0, 0, 0, 0};
int input_state_prev[4] = {0, 0, 0, 0};

// check if input pins have flipped and print to serial
void checkInputPins(int current_cycle)
{
  bool state_change = false;
  for (int pin_i = 0; pin_i < 4; pin_i++)
  {
    input_state[pin_i] = digitalRead(input_pins[pin_i]);
    if (input_state[pin_i] != input_state_prev[pin_i])
    {
      state_change = true;
      input_state_prev[pin_i] = input_state[pin_i];
    }
  }

  // compare the buttonState to its previous state
  if (state_change == true)
  {
    Serial.print("input: ");
    for (int pin_i = 0; pin_i < 4; pin_i++)
    {
      Serial.print(input_state[pin_i]);
      Serial.print(",");
    }
    Serial.print(current_cycle);
    Serial.print(",");
    Serial.println(millis());

    // TEST CODE
    // for (int pin_i = 0; pin_i < 4; pin_i++) {
    //  Serial.print(digitalRead(input_pins[pin_i]));
    //  Serial.print(",");
    //
    //}
  }
}

long readLongFromSerial()
{
  union u_tag
  {
    byte b[4];
    long lval;
  } u;
  u.b[0] = Serial.read();
  u.b[1] = Serial.read();
  u.b[2] = Serial.read();
  u.b[3] = Serial.read();
  return u.lval;
}

void toggle_camera_triggers(int pins[], byte state, int num)
{
  for (int i = 0; i < num; i++)
  {
    digitalWrite(pins[i], state);
  }
}

void runAcquisition(
    long num_cycles,
    long inv_framerate)
{

  unsigned long current_cycle = 0;
  unsigned long previous_micros = 0;
  unsigned long current_micros;
    

  while (current_cycle < num_cycles)
  {

    current_micros = micros();

    // trigger camera
    if (current_micros - previous_micros >= inv_framerate)
    {

      current_cycle += 1;
      previous_micros = current_micros;

      // trigger the cameras shutter
      toggle_camera_triggers(trigger_pins, HIGH, num_cams);
      // wait for half the interframe period
      delayMicroseconds(inv_framerate/2);
      // close the camera shutter
      toggle_camera_triggers(trigger_pins, LOW, num_cams);

      // Check to see if the pin states have changed
      checkInputPins(current_cycle);
    }
  }
}

void setup()
{

  // set up camera triggers
  for (int pin : trigger_pins)
  {
    pinMode(pin, OUTPUT);
  }
  // set up input pins
  for (int pin : input_pins)
  {
    pinMode(pin, INPUT);
  }

  toggle_camera_triggers(trigger_pins, LOW, num_cams);

  Serial.begin(9600);
  delay(SERIAL_START_DELAY);
}

void loop()
{

  // run acquisition when 2 params have been sent (each param is 4 bytes)
  // params are num_cycles, inv_framerate
  if (Serial.available() == 8)
  {

    Serial.println("Start");
    // Serial.println(micros());

    long num_cycles = readLongFromSerial();
    long inv_framerate = readLongFromSerial();

    runAcquisition(
        num_cycles,
        inv_framerate);

    // send message that recording is finished
    // Serial.println(micros());
    Serial.println("Finished");
  }
}
