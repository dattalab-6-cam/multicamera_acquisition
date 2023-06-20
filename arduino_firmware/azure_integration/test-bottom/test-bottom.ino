
// #include <Arduino.h>
#include <elapsedMillis.h>

/* MASTER LIST OF CHANGES TO MAKE IN FUTURE CODE
- allow pins to be defined in python (and take them in via serial)
- allow python to set the recording framerate
*/

const int SERIAL_START_DELAY = 100;

// Camera trigger pins
int num_cams_TOP = 5;
int basler_trigger_pins_TOP[5] = {A0};
int num_cams_BOTTOM = 1;
int basler_trigger_pins_BOTTOM[1] = {A3};

// AZURE trigger pin
int azure_trigger_pin = A5;

// LED pins
int IR1_top = 5;
int IR1_bottom = 4;

// Define the input GPIOs
int num_input = 4;
const int input_pins[4] = {22, 24, 26, 28};


void serial_flush(void)
{
  while (Serial.available())
    Serial.read();
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

void setup()
{

  // set up IR pins
  pinMode(IR1_top, OUTPUT);
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(IR1_bottom, OUTPUT);

  // turn LEDs off
  digitalWrite(IR1_top, HIGH);
  digitalWrite(IR1_bottom, HIGH);

  Serial.begin(9600);
  delay(SERIAL_START_DELAY);
}

void loop()
{

  // Stall until we receive serial input from Python
  Serial.println("Waiting...");
  Serial.println(Serial.available());
  delay(1000);

  // Python sends 8 bytes, which is a long int encoding the number of
  // Azure sync pulses we should do here & the framerate of the basler.
  if (Serial.available() == 8)
  {
    // turn LEDs off at beginning
    digitalWrite(IR1_top, LOW);
    digitalWrite(IR1_bottom, LOW);

    // Read in user params
    long num_cycles = readLongFromSerial();
    long inv_framerate = readLongFromSerial();
    // long num_azures = readLongFromSerial(); // TODO implement this
    // long num_baslers = readLongFromSerial(); // TODO implement this

    // tell python that we're starting recording
    Serial.println("Start");

    // Report params back to python
    Serial.print("Num cycles:");
    Serial.println(num_cycles);
    delay(5000);
    // send message that recording is finished
    Serial.println("Finished");
    serial_flush();
    // turn LEDs on at end
    digitalWrite(IR1_top, HIGH);
    digitalWrite(IR1_bottom, HIGH);
  }
  // If we receive more than 8 bytes, flush the serial buffer and wait for something new to happen
  else if (Serial.available() > 8)
  {
    serial_flush();
  }
}
