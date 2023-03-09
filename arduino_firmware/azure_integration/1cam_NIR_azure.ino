
#include <Arduino.h>

const int SERIAL_START_DELAY = 100;



// This code expects X long bytes at the beginning:
// 1: num_cycles
// 2: 
// NB basler rate currently fixed to work at 120 hz

// TODO: change python to not send inv_framerate.


// Azure timing params
const int AZURE_INV_RATE_USEC = 33333; // sync pulses will be sent at this rate
const int AZURE_TRIG_WIDTH_USEC = 10;
const int AZURE_PULSE_PERIOD_USEC = 160; // actually 125 usec but microsoft recommends calling it 160 to be safe
const int AZURE_INTERSUBFRAME_PERIOD_USEC = 1575;  // I think? 125 + 1.45 wait
const int NUM_AZURES = 2;
const int DESIRED_AVG_BASLER_INTERFRAME_USEC = 8333;

// Basler frame times are defined relative to each sync pulse being 0.
// TODO: re-write python code to configure baslers to take rising edge triggers.
// TODO: configure Baslers to start exposure asap, and to have a Timed exposure: https://docs.baslerweb.com/trigger-selector#frame-start-end-and-active-trigger
// TODO: take into account any line delay (~1 us), exposure start time (3.6 us for us?), any line debouncing. Ideally trigger delay should be 0.
// https://docs.baslerweb.com/trigger-activation
// https://docs.baslerweb.com/acquisition-timing-information#exposure-start-delay
const int BASLER_TRIG_WIDTH_USEC = 50;  // some random internet source suggested 100, let's try 50 for now.
const int offset = 0;  // where to call basler's "0" relative to the pulse we send the Azure. My guess is 0 but might be different.
const int basler_f0 = NUM_AZURES*AZURE_PULSE_PERIOD_USEC + offset;
const int basler_f1 = basler_f0 + AZURE_INTERSUBFRAME_PERIOD_USEC * 5;  // want to be as close to 8333 as possible here
const int basler_f2 = basler_f1 + DESIRED_AVG_BASLER_INTERFRAME_USEC;
const int basler_f3 = basler_f2 + DESIRED_AVG_BASLER_INTERFRAME_USEC;
const int basler_frame_times[4] = {basler_f0, basler_f1, basler_f2, basler_f3};  // and the period betw f3 and f0 will be slightly longer than 8.333, so it averages out correctly.

// Timers
elapsedMicros previous_pulse;
elapsedMicros previous_basler;
elapsedMicros previous_basler_trigger;
int current_basler_frame_idx = 0;

// Camera trigger pins
// int num_cams = 5;
// int trigger_pins[5] = {A1, A2, A3, A4, A5};
int num_cams = 1;
int basler_trigger_pins[1] = {A1};
int azure_trigger_pin = A2;

// Trigger state vars
int azure_trigger_state = 0;
int basler_trigger_state = 0;


// Define the input GPIOs
int num_input = 4;
const int input_pins[4] = {22, 24, 26, 28};

// Set the initial state of input pins
int input_state[4] = {0, 0, 0, 0};
int input_state_prev[4] = {0, 0, 0, 0};



// check if input pins have flipped and print to serial
// TODO: make this use Serial.write(), which will be much faster.
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

void azure_pulse_logic(int *current_cycle)
{
  if ((previous_pulse >= AZURE_INV_RATE_USEC) && azure_trigger_state == 0){
    // Send the azure pulse
    digitalWrite(azure_trigger_pin, HIGH);
    azure_trigger_state = 1;
    previous_pulse = previous_pulse - AZURE_INV_RATE_USEC;

    // Iterate the global counter
    *current_cycle = *current_cycle + 1;
    
    // Reset the basler's to 0th frame of the cycle
    previous_basler = 0;  # we want this to be a hard reset wrt the azure pulses.
    current_basler_frame_idx = 0;

  } else if (((previous_pulse >= AZURE_TRIG_WIDTH_USEC) && azure_trigger_state == 1)){
    // Turn off the Azure pulse
    digitalWrite(azure_trigger_pin, LOW);
    azure_trigger_state = 0;
  }
}


void basler_pulse_logic(){
  if ((previous_basler >= basler_frame_times[current_basler_frame_idx]) && basler_trigger_state == 0){
    // Send the balser pulse and iterate relative frame idx
    digitalWrite(basler_trigger_pins[0], HIGH);
    basler_trigger_state = 1;
    previous_basler_trigger = 0;
    current_basler_frame_idx ++;

  } else if ((previous_basler_trigger >= BASLER_TRIG_WIDTH_USEC) && basler_trigger_state==1){
    // Turn off basler pulse
    digitalWrite(basler_trigger_pins[0], LOW);
    basler_trigger_state = 0;
  }
}


void runAcquisition(
    long num_cycles)
{

  unsigned long current_cycle = 0;

  while (current_cycle < num_cycles)
  {

    // do azure logic
    azure_pulse_logic(&current_cycle)
  
    // do basler logic
    basler_pulse_logic()

    // TODO: implement a buffer here; or at least, only do this in down-time between azure pulses.
    checkInputPins(current_cycle);
  }
}

void setup()
{

  // set up camera triggers
  for (int pin : basler_trigger_pins)
  {
    pinMode(pin, OUTPUT);
  }
  pinMode(azure_trigger_pin, OUTPUT);

  // set up input pins
  for (int pin : input_pins)
  {
    pinMode(pin, INPUT);
  }

  toggle_camera_triggers(basler_trigger_pins, LOW, num_cams);

  Serial.begin(9600);
  delay(SERIAL_START_DELAY);
}

void loop()
{

  // run acquisition when 1 params have been sent (each param is 4 bytes)
  // params are num_cycles, 
  if (Serial.available() == 4)
  {

    Serial.println("Start");
    // Serial.println(micros());

    long num_cycles = readLongFromSerial();

    runAcquisition(
        num_cycles);

    // send message that recording is finished
    // Serial.println(micros());
    Serial.println("Finished");
  }
}
