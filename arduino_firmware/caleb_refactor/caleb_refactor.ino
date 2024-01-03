
#include <Arduino.h>
#include <elapsedMillis.h>
#include <string.h>

/*
Firmware for multi-camera acquisition system.
https://github.com/dattalab-6-cam/multicamera_acquisition

This code controls the output of a microcontroller (e.g. Arduino or Teensy) 
that controls cameras and lights for a multi-camera acquisition system, and 
listens for state changes on a set of input pins. The control flow is:

1) When the microcontroller is ready to receive instructions, it will send the
string "READY" over the serial connection once per second. 

2) The microcontroller will wait for instructions from the python script, which
should consist of a sequence 7 lines, as follows:

    (1) STX (Start of Text) character, aka b'\x02'
    (2) integer specifying the number of acquisition cycles to perform
    (3) integer specifying the duration of each cycle in microseconds
    (4) comma separated list of pins to monitor for state changes
    (5) comma separated list state-change times in microseconds
    (6) comma separated list of pins corresponding to the times in (5)
    (6) comma separated states (0 or 1) corresponding to the times in (5)
    (7) ETX (End of Text) character, aka b'\x03'

(3) After the microcontroller has seen a correctly formatted data packet, it
will send the string "RECEIVED" over the serial connection and then immediately
begin performing the specified acquisition cycles.

(4) If the microcontroller recieves any serial communication that is not
prefixed with the STX character, it will clear the serial buffer, send 
"ERROR" over the serial connection, and return to the main loop (i.e. step 1).

(5) During each acquisition cycle, the microcontroller will check the input 
pins specified in the data packet for state changes. If a state change is
detected on any pin, then the state of all pins plus the current cycle index
will be sent over the serial connection in the following format:

    "INPUT <pin1>:<state1>,...,<pinN>:<stateN>,<cycleIndex>\n"

(6) Once per second, the microcontroller will check for an interrupt signal,
which should be the single character "I". If detected, the microcontroller will
send the string "INTERRUPTED" over the serial connection and return to the
main loop (i.e. step 1).
*/

const int SERIAL_START_DELAY = 100; // Delay in milliseconds before starting serial communication
const int MAX_INPUT_PINS = 10;      // Maximum number of input pins to monitor
const int MAX_STATE_CHANGES = 200;  // Maximum number of state changes to monitor
const int INTERRUPT_CHECK_PERIOD_MILLIS = 1000; // Period in milliseconds between checks for interrupt signal


/**
 * Parses a comma-separated string into an array of unsigned long integers.
 * 
 * @param input The input string containing comma-separated numbers.
 * @param output An array to store the parsed unsigned long integers.
 * @param maxNumbers The maximum number of elements that can be stored in the output array.
 * @param count Pointer to an integer where the function will store the count of successfully parsed numbers.
 * 
 * Note: The output array should be pre-allocated with at least 'maxNumbers' elements.
 */
void parseLine(const char* input, unsigned long* output, int maxNumbers, int* count) {
    const char* start = input; // Pointer to the start of the number
    char* end;                 // Pointer to the end of the number
    int localCount = 0;           // Number of parsed numbers

    while (*start != '\0' && localCount < maxNumbers) {
        // Convert the number from string to unsigned long
        unsigned long number = strtoul(start, &end, 10);

        // If the pointers are the same, no number was found, so break
        if (start == end) {
            break;
        }

        // Store the number in the output array
        output[localCount] = number;
        localCount++;

        // Move to the next part of the string
        start = end;
        if (*start == ',') {
            start++; // Skip the comma
        }
    }

    if (count != nullptr) {
        *count = localCount; // Only update count if it's not a null pointer
    }
}

/**
* Reports the current state of the input pins to the serial connection as a
* comma-separated string of the form:
*
*   "INPUT <pin1>:<state1>,...,<pinN>:<stateN>,<cycleIndex>\n"
* 
* @param input_pins An array of input pins to monitor.
* @param current_states The current state of each input pin.
* @param num_input_pins The number of input pins to monitor.
* @param cycle_index The current acquisition cycle index.
**/
void reportInputStates(
    unsigned long* input_pins,
    int* current_states,
    int num_input_pins,
    unsigned long cycle_index
) {
    String output = "INPUT ";
    for (int i = 0; i < num_input_pins; i++) {
        output += String(input_pins[i]) + ":" + String(current_states[i]) + ",";
    }
    output += String(cycle_index);
    Serial.println(output);
}


void acquisitionLoop(
    unsigned long num_cycles,
    unsigned long cycle_duration,
    unsigned long* input_pins,
    int num_input_pins,
    unsigned long* state_change_times,
    unsigned long* state_change_pins,
    unsigned long* state_change_states,
    int num_state_changes
) {
    // Initialize the input pins
    for (int i = 0; i < num_input_pins; i++) {
        pinMode(input_pins[i], INPUT_PULLUP);
    }

    // Initialize the state change pins
    for (int i = 0; i < num_state_changes; i++) {
        pinMode(state_change_pins[i], OUTPUT);
    }

    // Initialize indexes
    unsigned long cycle_index = 0;
    int step_index = 0;

    // Create arrays for storing input pin states
    int previous_states[MAX_INPUT_PINS];
    int current_states[MAX_INPUT_PINS];

    // initialize flags
    bool state_changed = false;
    bool finished_wrap_up = false;

    // Initialize the current state of each input pin and report to python
    if (num_input_pins > 0) {
        for (int i = 0; i < num_input_pins; i++) {
            previous_states[i] = digitalRead(input_pins[i]);
        }
        reportInputStates(input_pins, previous_states, num_input_pins, cycle_index);
    }

    // Initialize timers
    elapsedMicros elapsed_cycle_time = 0;
    elapsedMillis elapsed_interrupt_check_time = 0;

    // Perform acquisition cycles
    while (cycle_index < num_cycles) {

        // Perform next state change
        if (step_index < num_state_changes) {
            if (elapsed_cycle_time >= state_change_times[step_index]) {
                // Change the state of the current pin
                digitalWrite(state_change_pins[step_index], state_change_states[step_index]);
                step_index++;
            }
        }
        
        // Wrap up the current cycle
        else if (!finished_wrap_up) {
            
            // Check for input state changes
            if (num_input_pins > 0) {
                for (int i = 0; i < num_input_pins; i++) {
                    current_states[i] = digitalRead(input_pins[i]);
                    if (current_states[i] != previous_states[i]) {
                        previous_states[i] = current_states[i];
                        state_changed = true;
                    }
                }
                if (state_changed) {
                    reportInputStates(input_pins, previous_states, num_input_pins, cycle_index);
                    state_changed = false;
                }
            }

            // Check for interrupt signal
            if (elapsed_interrupt_check_time > INTERRUPT_CHECK_PERIOD_MILLIS) {
                if (Serial.available() > 0) {
                    char interruptChar = Serial.read();
                    if (interruptChar == 'I') {
                        Serial.println("INTERRUPTED");
                        return;
                    } else {
                        Serial.flush();
                    }
                }
                elapsed_interrupt_check_time = 0;
            }
            finished_wrap_up = true;
        }

        // Start the next cycle
        else if (elapsed_cycle_time >= cycle_duration) {
            step_index = 0;
            cycle_index++;
            finished_wrap_up = false;
            elapsed_cycle_time = elapsed_cycle_time - cycle_duration;
        }
    }
}


void setup() {
    // Start the serial communication
    Serial.begin(9600);
    delay(SERIAL_START_DELAY);
}


void loop() {

    // Tell python that the arduino is ready to receive data
    Serial.println("READY");
    delay(1000);

    // Wait for python to send instructions
    if (Serial.available() > 0) {

        char firstChar = Serial.read();

        // If the first character is not the STX character, clear the serial
        // buffer, send an error message, and return to the main loop
        if (firstChar != '\x02') {
            Serial.flush();
            Serial.println("ERROR");
        } 
        // If the first character is the STX character, then parse the data
        // packet and begin acquisition
        else {
            // Read the number of cycles and the cycle duration
            unsigned long num_cycles = strtoul(Serial.readStringUntil('\n').c_str(), NULL, 10);
            unsigned long cycle_duration = strtoul(Serial.readStringUntil('\n').c_str(), NULL, 10);

            // Read the input pins to monitor
            unsigned long input_pins[MAX_INPUT_PINS];
            int num_input_pins;
            String line = Serial.readStringUntil('\n');
            parseLine(line.c_str(), input_pins, MAX_INPUT_PINS, &num_input_pins);

            // Read the state change times
            unsigned long state_change_times[MAX_STATE_CHANGES];
            int num_state_changes;
            line = Serial.readStringUntil('\n');
            parseLine(line.c_str(), state_change_times, MAX_STATE_CHANGES, &num_state_changes);

            // Read the state change pins
            unsigned long state_change_pins[MAX_STATE_CHANGES];
            line = Serial.readStringUntil('\n');
            parseLine(line.c_str(), state_change_pins, MAX_STATE_CHANGES, nullptr);
                    
            // Read the state change states
            unsigned long state_change_states[MAX_STATE_CHANGES];
            line = Serial.readStringUntil('\n');
            parseLine(line.c_str(), state_change_states, MAX_STATE_CHANGES, nullptr);

            // Read the ETX character
            char lastChar = Serial.read();

            // If the last character is not the ETX character, clear the serial
            // buffer, send an error message, and return to the main loop
            if (lastChar != '\x03') {
                Serial.flush();
                Serial.println("ERROR");
            }

            // If the last character is the ETX character, then send the
            // "RECEIVED" message and begin acquisition
            else {
                Serial.println("RECEIVED");
                acquisitionLoop(
                    num_cycles, 
                    cycle_duration, 
                    input_pins, 
                    num_input_pins, 
                    state_change_times, 
                    state_change_pins,
                    state_change_states,
                    num_state_changes
                ); 
            }
        }
    }
    Serial.flush();
}

