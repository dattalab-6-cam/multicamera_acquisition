
#include <Arduino.h>
#include <elapsedMillis.h>
#include <string.h>

/* MASTER LIST OF CHANGES TO MAKE IN FUTURE CODE
- allow pins to be defined in python (and take them in via serial)
- allow python to set the recording framerate
*/

const int SERIAL_START_DELAY = 100;

// HARDCODED PINS

// LED trigger pins
int LED1 = 38;
int LED2 = 39;
int LED3 = 40;
int LED4 = 41;
int LED5 = 14;
int LED6 = 15;
int LED7 = 16; // side led
int LED8 = 17; // side led
int LED9 = 20;
int LED10 = 21;
int LED11 = 22; // unused
int LED12 = 23; // unused

int BASLER1 = 1;
int BASLER2 = 3;
int BASLER3 = 5;
int BASLER4 = 7;
int BASLER5 = 9;  // Top camera
int BASLER6 = 11; // Bottom camera
int BASLER7 = 24; // unused
int BASLER8 = 26; // unused

// Camera trigger pins
int num_cams_TOP = 4;
int basler_trigger_pins_TOP[4] = {BASLER1, BASLER2, BASLER3, BASLER4};

int num_cams_BOTTOM = 2;
int basler_trigger_pins_BOTTOM[2] = {BASLER5, BASLER6};

// AZURE trigger pin
int azure_trigger_pin = 0;

// LED pins
int LED_IR_TOP[6] = {LED1, LED2, LED3, LED4, LED5, LED6};
int LED_IR_BOTTOM[5] = {LED7, LED8, LED9, LED10, LED11}; // Adjusted size and values

// Define the input GPIOs
int num_input = 4;
const int input_pins[4] = {33, 34, 35, 36};

// Number of azures in rig
const unsigned int NUM_AZURES = 2; // needed to determine basler frame times

// Azure timing params
const unsigned int AZURE_INV_RATE_USEC = 33333;            // sync pulses will be sent at this rate (1/30 of a second)
const unsigned int AZURE_TRIG_WIDTH_USEC = 10;             // azure sync pulses last for this long
const unsigned int AZURE_PULSE_PERIOD_USEC = 160;          // actually 125 usec but microsoft recommends calling it 160 to be safe, judging by oscope it appears to be 180
const unsigned int AZURE_INTERSUBFRAME_PERIOD_USEC = 1575; // I think? 0.125 pulse + 1.45 wait

// Basler timing params
const unsigned int BASLER_TRIG_WIDTH_USEC = 100;      // some random internet source suggested 100, let's try 50 for now.
const unsigned int BASLER_IR_PULSE_WIDTH_USEC = 1000; // make sure this is less than the separation between top + bottom baslers.
const int OFFSET_BETWEEN_BASLER_AZURE = 100;          // where to call basler's "0" relative to the pulse we send the Azure. My guess is 0 but might be different.
const int N_VALID_FRS = 5;
const int VALID_INV_FRAMERATES[N_VALID_FRS] = {6667, 8333, 11111, 16667, 33333};
bool ok_framerate = false;
long num_cycles = 0;
long inv_framerate = 0;

// Timers
elapsedMicros previous_pulse;
elapsedMicros basler_frame_timer;
elapsedMicros previous_basler_trigger_TOP;
elapsedMicros previous_basler_trigger_BOTTOM;
int current_basler_frame_idx_TOP = 0;
int current_basler_frame_idx_BOTTOM = 0;

unsigned int interrupt_check_period_millis = 1000;
elapsedMillis sinceInterruptCheck;

// State vars
int azure_trigger_state = 0;
int basler_trigger_state_TOP = 0;
int basler_ir_state_TOP = 0;
int basler_await_azure_TOP = 0;
int basler_trigger_state_BOTTOM = 0;
int basler_ir_state_BOTTOM = 0;
int basler_await_azure_BOTTOM = 0;
int done = 0;

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
    /*
    The azure_pulse_logic() function is used to control the triggering of an Azure pulse based
    on a set of timing parameters. It's expected to be continuously called within an Arduino loop.
     When it's time to start a pulse, the function triggers the pulse, resets the timer for the
     next pulse, iterates a global counter, and resets the Basler camera to the start of its cycle.
     When it's time to end a pulse, it ends the pulse and resets a counter indicating that the
     pulse has started. If it's not time to start or end a pulse, the function doesn't do anything.
    */

    int started_frame = 0;

    // Check if it's time to start a pulse.
    // If the current state is off (0) and enough time has passed since the previous pulse,
    // it's time to start a new pulse.
    if ((azure_trigger_state == 0) && (previous_pulse >= AZURE_INV_RATE_USEC))
    {

        // Start the Azure pulse by setting the Azure trigger pin to HIGH.
        digitalWrite(azure_trigger_pin, HIGH);
        azure_trigger_state = 1; // update the current state of the azure trigger pin

        // Reset the timer for the next pulse.
        // we want this to account for potential accumulating delays, hence subtraction instead of 0.
        previous_pulse = previous_pulse - AZURE_INV_RATE_USEC;

        // Iterate the global counter
        started_frame = 1;

        // Reset the Basler camera to the start of its cycle.
        // The timer and frame index for the top and bottom Baslers are set to 0,
        // and the Baslers are set to not await Azure.
        basler_frame_timer = 0; // we want this to be a hard reset wrt the azure pulses, hence 0 instead of subtraction.
        current_basler_frame_idx_TOP = 0;
        current_basler_frame_idx_BOTTOM = 0;
        basler_await_azure_TOP = 0;
        basler_await_azure_BOTTOM = 0;
    }
    // Check if it's time to end a pulse.
    // If the current state is on (1) and the pulse width has been reached,
    // it's time to end the pulse.
    else if ((azure_trigger_state == 1) && (previous_pulse >= AZURE_TRIG_WIDTH_USEC))
    {
        // End the Azure pulse by setting the Azure trigger pin to LOW.
        digitalWrite(azure_trigger_pin, LOW);
        azure_trigger_state = 0;
        started_frame = 0;
    }
    // Default case: It's not time to start or end a pulse.
    else
    {
        // default case: nothing to do.
        started_frame = 0;
    }
    // Return the state of the started frame counter.
    return started_frame;
}

int getNumFrameTimeElements(int _inv_framerate)
{
    /*  Returns the number of elements in the basler frame times array based on the inverse framerate.
        This is needed because the number of elements in the array changes based on the framerate.

    */
    int num_elements = 0;

    if (_inv_framerate == 6667)
    {
        num_elements = 5;
    }
    else if (_inv_framerate == 8333)
    {
        num_elements = 4;
    }
    else if (_inv_framerate == 11111)
    {
        num_elements = 3;
    }
    else if (_inv_framerate == 16667)
    {
        num_elements = 2;
    }
    else if (_inv_framerate == 33333)
    {
        num_elements = 1;
    }
    else
    {
        num_elements = 0;
    }

    return num_elements;
}

int *getBaslerFrameTimes(int _inv_framerate, unsigned int num_azures, const char *cams)
{
    /* Returns an array of integers representing the timing parameters for triggering Basler frames.
        The function takes three arguments: the inverse framerate, the number of Azure sync pulses,
        and a string indicating which camera the frame times are for. The function returns an array
        of integers representing the timing parameters for triggering Basler frames. The function
        is designed to be called once at the beginning of the program. The function has two major
        portions, each dealing with a different Basler camera (top and bottom). For each camera,
        the function calculates the timing parameters for triggering Basler frames based on the
        inverse framerate and the number of Azure sync pulses. The function returns an array of
        integers representing the timing parameters for triggering Basler frames.
    */
    int *basler_frame_times = nullptr;
    int num_elements = getNumFrameTimeElements(_inv_framerate);

    int f0 = num_azures * AZURE_PULSE_PERIOD_USEC + OFFSET_BETWEEN_BASLER_AZURE;

    if (_inv_framerate == 6667)
    {
        int f1 = f0 + _inv_framerate;
        int f2 = f1 + _inv_framerate;
        int f3 = f2 + _inv_framerate;
        int f4 = f3 + _inv_framerate;

        if (strcmp(cams, "top") == 0)
        {
            basler_frame_times = new int[num_elements]{f0, f1, f2, f3, f4};
        }
        else
        {
            // last index due to IR pulses from azure starting before trigger
            basler_frame_times = new int[num_elements]{
                f0 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC,
                f1 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC,
                f2 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC,
                f3 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC,
                f4 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC};
        }
    }
    else if (_inv_framerate == 8333)
    {
        int f1 = f0 + AZURE_INTERSUBFRAME_PERIOD_USEC * 5;
        int f2 = f1 + _inv_framerate;
        int f3 = f2 + _inv_framerate;

        if (strcmp(cams, "top") == 0)
        {
            basler_frame_times = new int[num_elements]{f0, f1, f2, f3};
        }
        else
        {
            // last index due to IR pulses from azure starting before trigger
            basler_frame_times = new int[num_elements]{
                f0 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC,
                f1 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC,
                f2 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC,
                f3 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC};
        }
    }
    else if (_inv_framerate == 11111)
    {
        // int f0 = num_azures * AZURE_PULSE_PERIOD_USEC + OFFSET_BETWEEN_BASLER_AZURE;
        int f1 = f0 + _inv_framerate;
        int f2 = f1 + _inv_framerate;

        if (strcmp(cams, "top") == 0)
        {
            basler_frame_times = new int[num_elements]{f0, f1, f2};
        }
        else
        {
            basler_frame_times = new int[num_elements]{
                f0 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC,
                f1 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC,
                f2 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC};
        }
    }
    else if (_inv_framerate == 16667)
    {
        int f1 = f0 + _inv_framerate;

        if (strcmp(cams, "top") == 0)
        {
            basler_frame_times = new int[num_elements]{f0, f1};
        }
        else
        {
            basler_frame_times = new int[num_elements]{
                f0 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC,
                f1 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC};
        }
    }
    else if (_inv_framerate == 33333)
    {
        if (strcmp(cams, "top") == 0)
        {
            basler_frame_times = new int[num_elements]{f0};
        }
        else
        {
            basler_frame_times = new int[num_elements]{
                f0 + 2 * AZURE_INTERSUBFRAME_PERIOD_USEC};
        }
    }
    return basler_frame_times;
}

void basler_pulse_logic(int num_elements, const int baslerFrameTimesTop[], const int baslerFrameTimesBottom[])
{
    /*
    The basler_pulse_logic() function is responsible for controlling the triggering of Basler
    frames based on a set of timing parameters. The function takes two arrays of integers as input,
     each representing timing parameters for triggering Basler frames. The function is designed
     to be repeatedly called in an Arduino loop. The function has two major portions, each
     dealing with a different Basler camera (top and bottom). For each camera, the function
     checks if it is time to start a frame. If so, it triggers the frame, turns on the IR lights,
      and prepares for the next frame. When it is time to end the frame, it stops the trigger
      and, after a set delay, turns off the IR lights.
    */

    // Check if it's time to start a top Basler frame.
    // Conditions for starting a frame: the current state is off (0), the frame timer has reached the current frame time,
    // and the Basler is not awaiting Azure.
    if (
        (basler_trigger_state_TOP == 0) && (basler_frame_timer >= baslerFrameTimesTop[current_basler_frame_idx_TOP]) && (not basler_await_azure_TOP))
    {
        // Start the Basler pulse and turn on the IR lights.
        toggle_camera_triggers(basler_trigger_pins_TOP, HIGH, num_cams_TOP);
        for (int pin : LED_IR_TOP)
        {
            digitalWrite(pin, HIGH);
        }
        // digitalWrite(IR1_top, LOW);

        // Update the state to indicate the pulse and IR lights have started.
        basler_trigger_state_TOP = 1;
        basler_ir_state_TOP = 1;

        // Reset the timer for the next Basler pulse.
        previous_basler_trigger_TOP = 0;

        // Advance the current Basler frame or wait until the next Azure trigger.
        // If it's not the last frame, move to the next frame.
        // If it's the last frame, reset to the first frame and set to await Azure.
        if (current_basler_frame_idx_TOP < num_elements - 1)
        {
            current_basler_frame_idx_TOP++;
        }
        else
        {
            current_basler_frame_idx_TOP = 0;
            basler_await_azure_TOP = 1;
        }
    }
    else if ((basler_trigger_state_TOP == 1) && (previous_basler_trigger_TOP >= BASLER_TRIG_WIDTH_USEC))
    {
        toggle_camera_triggers(basler_trigger_pins_TOP, LOW, num_cams_TOP);
        basler_trigger_state_TOP = 0;
    }
    // after ~1ms, turn off the IR lights
    if ((previous_basler_trigger_TOP >= BASLER_IR_PULSE_WIDTH_USEC) && basler_ir_state_TOP == 1)
    {
        // digitalWrite(IR1_top, HIGH);
        for (int pin : LED_IR_TOP)
        {
            digitalWrite(pin, LOW);
        }
        basler_ir_state_TOP = 0;
    }

    // same thing but for bottom basler

    if ((basler_frame_timer >= baslerFrameTimesBottom[current_basler_frame_idx_BOTTOM]) && basler_trigger_state_BOTTOM == 0 && (not basler_await_azure_BOTTOM))
    {
        // Send the balser pulse and iterate relative frame idx

        //    Serial.println(basler_frame_timer);

        toggle_camera_triggers(basler_trigger_pins_BOTTOM, HIGH, num_cams_BOTTOM);
        // digitalWrite(IR1_bottom, LOW);
        for (int pin : LED_IR_BOTTOM)
        {
            digitalWrite(pin, HIGH);
        }

        basler_trigger_state_BOTTOM = 1;
        basler_ir_state_BOTTOM = 1;
        previous_basler_trigger_BOTTOM = 0;

        // advance the current basler frame; or wait until the next azure trigger.
        if (current_basler_frame_idx_BOTTOM < num_elements - 1)
        {
            current_basler_frame_idx_BOTTOM++;
        }
        else
        {
            current_basler_frame_idx_BOTTOM = 0;
            basler_await_azure_BOTTOM = 1;
        }
    }
    else if ((previous_basler_trigger_BOTTOM >= BASLER_TRIG_WIDTH_USEC) && basler_trigger_state_BOTTOM == 1)
    {
        toggle_camera_triggers(basler_trigger_pins_BOTTOM, LOW, num_cams_BOTTOM);
        basler_trigger_state_BOTTOM = 0;
    }

    // after ~1ms, turn off the IR lights
    if ((previous_basler_trigger_BOTTOM >= BASLER_IR_PULSE_WIDTH_USEC) && basler_ir_state_BOTTOM == 1)
    {
        // digitalWrite(IR1_bottom, HIGH);
        for (int pin : LED_IR_BOTTOM)
        {
            digitalWrite(pin, LOW);
        }
        basler_ir_state_BOTTOM = 0;
    }
}

bool check_requested_framerate(int _inv_framerate)
{
    bool valid_val = false;
    for (int ii = 0; ii < N_VALID_FRS; ii++) 
    {
        if (_inv_framerate == VALID_INV_FRAMERATES[ii])
        {
            valid_val = true;
            break;
        }
    }
    return valid_val;
}

void serial_flush(void)
{
    while (Serial.available())
        Serial.read();
}

void runAcquisition(long num_cycles, int num_elements, const int baslerFrameTimesTop[], const int baslerFrameTimesBottom[])
{
    /* The runAcquisition() function is responsible for running the acquisition loop.
     */

    unsigned long current_cycle = 0;
    int frame_started = 0;

    previous_pulse = 0;         // (re)start azure clock
    basler_await_azure_TOP = 1; // stall basler until azure starts
    basler_await_azure_BOTTOM = 1;

    // Run the acquisition loop until the number of cycles is reached.
    while (current_cycle < num_cycles)
    {

        // do azure logic
        frame_started = azure_pulse_logic();
        current_cycle = current_cycle + frame_started; // add 1 for each az frame
        // do basler logic
        basler_pulse_logic(num_elements, baslerFrameTimesTop, baslerFrameTimesBottom);

        // Check if user is requesting an interrupt by sending a serial input
        if (sinceInterruptCheck >= interrupt_check_period_millis)
        {
            if (Serial.available())
            {
                Serial.read();
                Serial.println("Breaking!");
                Serial.flush();
                break;
            }
        }
    }
    done = 1;
}

void setup()
{

    // set up IR pins
    // pinMode(IR1_top, OUTPUT);
    pinMode(LED_BUILTIN, OUTPUT);
    // pinMode(IR1_bottom, OUTPUT);

    // turn LEDs on at end
    // digitalWrite(IR1_top, HIGH);
    // digitalWrite(IR1_bottom, HIGH);
    for (int pin : LED_IR_TOP)
    {
        pinMode(pin, OUTPUT);
    }
    for (int pin : LED_IR_BOTTOM)
    {
        pinMode(pin, OUTPUT);
    }

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

    // Stall until we receive serial input from Python
    Serial.println("Waiting...");
    Serial.println(Serial.available());
    delay(1000);

    // Python sends 8 bytes, which is a long int encoding the number of
    // Azure sync pulses we should do here & the framerate of the basler.
    if (Serial.available() == 8)
    {
        // turn LEDs off at beginning
        // digitalWrite(IR1_top, HIGH);
        // digitalWrite(IR1_bottom, HIGH);

        // Read in user params
        num_cycles = readLongFromSerial();
        inv_framerate = readLongFromSerial();

        // Validate the params and only start if they're ok
        ok_framerate = check_requested_framerate(inv_framerate);
        Serial.print("Inv framerate ");
        Serial.print(inv_framerate);
        Serial.print(". OK? ");
        Serial.println(ok_framerate);

        if (ok_framerate)
        {
            // tell python that we're starting recording
            Serial.println("Start");
            ok_framerate = false;  // reset it

            // Report params back to python
            Serial.print("Num cycles:");
            Serial.println(num_cycles);

            // e.g. 8333 for 120 fps, 6667 for 150 fps = 1/fps * 1e6
            const unsigned int DESIRED_AVG_BASLER_INTERFRAME_USEC = inv_framerate;
            Serial.print("Desired avg basler interframe usec:");
            Serial.println(DESIRED_AVG_BASLER_INTERFRAME_USEC);

            const char cam_str_top[] = "top";
            const char cam_str_bottom[] = "bottom";

            // determine the basler frame times
            int *basler_frame_times_TOP = getBaslerFrameTimes(inv_framerate, NUM_AZURES, cam_str_top);
            int *basler_frame_times_BOTTOM = getBaslerFrameTimes(inv_framerate, NUM_AZURES, cam_str_bottom);

            // determines the number of elements in the basler frame
            int num_elements = getNumFrameTimeElements(inv_framerate);
            Serial.print("Num elements:");
            Serial.println(num_elements);

            // Print basler_frame_times_TOP
            for (int i = 0; i < num_elements; i++)
            {
                int t = basler_frame_times_TOP[i];
                Serial.print(t);
                Serial.print(',');
            }
            Serial.println();

            // Print basler_frame_times_BOTTOM
            for (int i = 0; i < num_elements; i++)
            {
                int t = basler_frame_times_BOTTOM[i];
                Serial.print(t);
                Serial.print(',');
            }
            Serial.println();

            // Run the aquisition loop
            runAcquisition(
                num_cycles,
                num_elements,
                basler_frame_times_TOP,
                basler_frame_times_BOTTOM);

            // send message that recording is finished
            Serial.println("Finished");
            serial_flush();
            // turn LEDs on at end
            // digitalWrite(IR1_top, HIGH);
            // digitalWrite(IR1_bottom, HIGH);
        }
    }
    // If we receive more than 8 bytes, flush the serial buffer and wait for something new to happen
    else if (Serial.available() > 8)
    {
        serial_flush();
    }
}