//#include <Arduino.h>
#include <elapsedMillis.h>

const int SERIAL_START_DELAY = 100;

// This code expects X long bytes at the beginning:
// 1: num_cycles
// 2: 
// NB basler rate currently fixed to work at 120 hz

// TODO: change python to not send inv_framerate.


// Azure timing params
const unsigned int AZURE_INV_RATE_USEC = 33333; // sync pulses will be sent at this rate
const unsigned int AZURE_TRIG_WIDTH_USEC = 10; // how long the sync pulse will be
const unsigned int AZURE_PULSE_PERIOD_USEC = 160; // actually 125 usec but microsoft recommends calling it 160 to be safe
const unsigned int AZURE_INTERSUBFRAME_PERIOD_USEC = 1575;  // I think? 0.125 pulse + 1.45 wait
//const unsigned int AZURE_INTERSUBFRAME_PERIOD_USEC = 1600;
const unsigned int NUM_AZURES = 2;
const unsigned int DESIRED_AVG_BASLER_INTERFRAME_USEC = 8333; // 120 hz

// Basler frame times are defined relative to each sync pulse being 0.
// TODO: re-write python code to configure baslers to take rising edge triggers.
// TODO: configure Baslers to start exposure asap, and to have a Timed exposure: https://docs.baslerweb.com/trigger-selector#frame-start-end-and-active-trigger
// TODO: take into account any line delay (~1 us), exposure start time (3.6 us for us?), any line debouncing. Ideally trigger delay should be 0.
// https://docs.baslerweb.com/trigger-activation
// https://docs.baslerweb.com/acquisition-timing-information#exposure-start-delay
const unsigned int BASLER_TRIG_WIDTH_USEC = 100;  // some random internet source suggested 100, let's try 50 for now.
const unsigned int BASLER_IR_PULSE_WIDTH_USEC = 1000;  // make sure this is less than the separation between top + bottom baslers.
const int initial_offset = 0;  // where to call basler's "0" relative to the pulse we send the Azure. My guess is 0 but might be different.
const int basler_f0 = NUM_AZURES*AZURE_PULSE_PERIOD_USEC + initial_offset;
const int basler_f1 = basler_f0 + AZURE_INTERSUBFRAME_PERIOD_USEC * 5;  // want to be as close to 8333 as possible here
const int basler_f2 = basler_f1 + DESIRED_AVG_BASLER_INTERFRAME_USEC - initial_offset;
const int basler_f3 = basler_f2 + DESIRED_AVG_BASLER_INTERFRAME_USEC;
const int basler_frame_times_TOP[4] = {basler_f0, basler_f1, basler_f2, basler_f3};  // and the period betw f3 and f0 will be slightly longer than 8.333, so it averages out correctly.


// nb as currently written, if f3 is > 33,333 it will break.

const int basler_frame_times_BOTTOM[4] = {basler_f0 + AZURE_INTERSUBFRAME_PERIOD_USEC,
  basler_f1 + AZURE_INTERSUBFRAME_PERIOD_USEC,
  basler_f2 + AZURE_INTERSUBFRAME_PERIOD_USEC,
  basler_f3 + AZURE_INTERSUBFRAME_PERIOD_USEC};

// Timers
elapsedMicros previous_pulse;
elapsedMicros previous_azure_trigger;
elapsedMicros basler_frame_timer;
elapsedMicros previous_basler_trigger_TOP;
elapsedMicros previous_basler_trigger_BOTTOM;
int current_basler_frame_idx_TOP = 0;
int current_basler_frame_idx_BOTTOM = 0;

// Camera trigger pins
 int num_cams_TOP = 5;
 int basler_trigger_pins_TOP[5] = {A2, A3};
int num_cams_BOTTOM = 1;
int basler_trigger_pins_BOTTOM[1] = {A1}; 
int azure_trigger_pin = A0; 

// State vars
int azure_trigger_state = 0;
int basler_trigger_state_TOP = 0;
int basler_ir_state_TOP = 0; 
int basler_await_azure_TOP = 0;
int basler_trigger_state_BOTTOM = 0;
int basler_ir_state_BOTTOM = 0; 
int basler_await_azure_BOTTOM = 0;
int done = 0;

// LED pins
int IR1_top    = 5;
int IR2_top    = 7;
int IR1_bottom = 4;
int IR2_bottom = 6; 

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

int azure_pulse_logic()
{
  int started_frame = 0;

  if ((azure_trigger_state == 0) && (previous_pulse >= AZURE_INV_RATE_USEC)){

    // Send the azure pulse
    digitalWrite(azure_trigger_pin, HIGH);
    azure_trigger_state = 1;
    previous_azure_trigger = 0;
    previous_pulse = previous_pulse - AZURE_INV_RATE_USEC;  // we want this to account for potential accumulating delays, hence subtraction instead of 0.

    // Iterate the global counter
    started_frame = 1;

    // Reset the baslers to 0th frame of the cycle
    basler_frame_timer = 0;  // we want this to be a hard reset wrt the azure pulses, hence 0 instead of subtraction.
    current_basler_frame_idx_TOP = 0;
    current_basler_frame_idx_BOTTOM = 0;
    basler_await_azure_TOP = 0;
    basler_await_azure_BOTTOM = 0;

  } else if ((azure_trigger_state == 1) && (previous_azure_trigger >= AZURE_TRIG_WIDTH_USEC)){
    // Turn off the Azure pulse
    digitalWrite(azure_trigger_pin, LOW);
    azure_trigger_state = 0;
    started_frame = 0;
  } else {
    // default case: nothing to do.
    started_frame = 0;
  }

  return started_frame;
}


void basler_pulse_logic(){


  if ((basler_trigger_state_TOP == 0) && (basler_frame_timer >= basler_frame_times_TOP[current_basler_frame_idx_TOP]) && (not basler_await_azure_TOP)){

    // Send the balser pulse and iterate relative frame idx
    toggle_camera_triggers(basler_trigger_pins_TOP, HIGH, num_cams_TOP);
    digitalWrite(IR1_top, HIGH);
    digitalWrite(IR2_top, HIGH);

    // debugging
//    if (current_basler_frame_idx_TOP != 1) {
//      digitalWrite(IR1_top, HIGH);
//      digitalWrite(IR2_top, HIGH);
//    }

    basler_trigger_state_TOP = 1;
    basler_ir_state_TOP = 1;
    previous_basler_trigger_TOP = 0;

    // advance the current basler frame; or wait until the next azure trigger.
    if (current_basler_frame_idx_TOP < 3){
      current_basler_frame_idx_TOP++;
    } else {
      current_basler_frame_idx_TOP = 0;
      basler_await_azure_TOP = 1;
    }

  } else if ((basler_trigger_state_TOP==1) && (previous_basler_trigger_TOP >= BASLER_TRIG_WIDTH_USEC)){

    toggle_camera_triggers(basler_trigger_pins_TOP, LOW, num_cams_TOP);
    basler_trigger_state_TOP = 0;
  }

  // after ~1ms, turn off the IR lights
  if ((previous_basler_trigger_TOP >= BASLER_IR_PULSE_WIDTH_USEC) && basler_ir_state_TOP==1){
    digitalWrite(IR1_top, LOW);
    digitalWrite(IR2_top, LOW);
    basler_ir_state_TOP = 0;
  }


  // same thing but for bottom basler

  if ((basler_frame_timer >= basler_frame_times_BOTTOM[current_basler_frame_idx_BOTTOM]) && basler_trigger_state_BOTTOM == 0 && (not basler_await_azure_BOTTOM)){    
    // Send the balser pulse and iterate relative frame idx

//    Serial.println(basler_frame_timer);

    toggle_camera_triggers(basler_trigger_pins_BOTTOM, HIGH, num_cams_BOTTOM);
    digitalWrite(IR1_bottom, HIGH);
    digitalWrite(IR2_bottom, HIGH);

    // debugging
//    if (current_basler_frame_idx_BOTTOM != 0) {
//      digitalWrite(IR1_bottom, HIGH);
//      digitalWrite(IR2_bottom, HIGH);
//    }

    basler_trigger_state_BOTTOM = 1;
    basler_ir_state_BOTTOM = 1;
    previous_basler_trigger_BOTTOM = 0;

    // advance the current basler frame; or wait until the next azure trigger.
    if (current_basler_frame_idx_BOTTOM < 3){
      current_basler_frame_idx_BOTTOM++;
    } else {
      current_basler_frame_idx_BOTTOM = 0;
      basler_await_azure_BOTTOM = 1;
    }

  } else if ((previous_basler_trigger_BOTTOM >= BASLER_TRIG_WIDTH_USEC) && basler_trigger_state_BOTTOM==1){
    toggle_camera_triggers(basler_trigger_pins_BOTTOM, LOW, num_cams_BOTTOM);
    basler_trigger_state_BOTTOM = 0;
  }

  // after ~1ms, turn off the IR lights
  if ((previous_basler_trigger_BOTTOM >= BASLER_IR_PULSE_WIDTH_USEC) && basler_ir_state_BOTTOM==1){
    digitalWrite(IR1_bottom, LOW);
    digitalWrite(IR2_bottom, LOW);
    basler_ir_state_BOTTOM = 0;
  }

}


void runAcquisition(
    long num_cycles)
{

  unsigned long current_cycle = 0;
  int frame_started = 0;

  previous_pulse = 0; // (re)start azure clock
  basler_await_azure_TOP = 1;  // stall basler until azure starts
  basler_await_azure_BOTTOM = 1;

  while (current_cycle < num_cycles)
  {

    // do azure logic
    frame_started = azure_pulse_logic();
    current_cycle = current_cycle + frame_started; // add 1 for each az frame

    // do basler logic
    basler_pulse_logic();

    // TODO: implement a buffer here; or at least, only do this in down-time between azure pulses.
//    checkInputPins(current_cycle);

  }

  done = 1;

}

void setup()
{

  // set up IR pins
  pinMode(IR1_top, OUTPUT);
  pinMode(IR2_top, OUTPUT); 
  pinMode(IR1_bottom, OUTPUT);
  pinMode(IR2_bottom, OUTPUT);

  // set up camera triggers
  for (int pin : basler_trigger_pins_TOP)
  {
    pinMode(pin, OUTPUT);
  }
  for (int pin : basler_trigger_pins_BOTTOM)
  {
    pinMode(pin, OUTPUT);
  }
  pinMode(azure_trigger_pin, OUTPUT);

  // set up input pins
  for (int pin : input_pins)
  {
    pinMode(pin, INPUT);
  }

  toggle_camera_triggers(basler_trigger_pins_TOP, LOW, num_cams_TOP);
  toggle_camera_triggers(basler_trigger_pins_BOTTOM, LOW, num_cams_BOTTOM);

  Serial.begin(9600);
  delay(SERIAL_START_DELAY);
}

void loop()
{

  // run acquisition when 1 params have been sent (each param is 4 bytes)
  // params are num_cycles, 
  if ((Serial.available() == 8) and not (done==1))
  {

    Serial.println("Start");

    // Read in user params
    long num_cycles = readLongFromSerial();

    // Framerate is currently hardcoded, so this value is ignored
    long inv_framerate = readLongFromSerial(); 

    // Report params
    Serial.print("Num cycles:");
    Serial.println(num_cycles);
    for (int t: basler_frame_times_TOP)
      {
        Serial.print(t);
        Serial.print(',');
      }
    Serial.println();
    for (int t: basler_frame_times_BOTTOM)
      {
        Serial.print(t);
        Serial.print(',');
      }
    Serial.println();


    // Do the magic!
    runAcquisition(
        num_cycles);

    // turn LEDs off at end
    digitalWrite(IR1_top, LOW);
    digitalWrite(IR2_top, LOW);
    digitalWrite(IR1_bottom, LOW);
    digitalWrite(IR2_bottom, LOW);

    // send message that recording is finished
    // Serial.println(micros());
    Serial.println("Finished");

    delay(1000000);
  }
}