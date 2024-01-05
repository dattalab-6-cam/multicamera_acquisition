
#include <Arduino.h>
#include <elapsedMillis.h>
#include <string.h>
#include <stdint.h> 

/*
Firmware for multi-camera acquisition system.
https://github.com/dattalab-6-cam/multicamera_acquisition

This code controls the output of a microcontroller (e.g. Arduino or Teensy) 
that triggers cameras and lights for a multi-camera acquisition system and 
listens to a specified set of input pins. The microcontroller also generates a
random sequence of bits that it broadcasts to a specified set of output pins.
The control flow is as follows.

1) When the microcontroller is ready to receive instructions, it will send the
string "READY" over the serial connection once per second. 

2) The microcontroller will wait for instructions from the python script, which
should consist of a sequence 7 lines, as follows:

    (1) STX (Start of Text) character, aka b'\x02'
    (2) integer specifying number of acquisition cycles to perform
    (3) integer specifying duration of each cycle in microseconds
    (4) comma separated list of input pins to monitor for state changes
    (5) comma separated list of output pins for the random bit sequence
    (6) integer specifying number of cycles between each update of the random bit
    (7) comma separated list of deterministic output state-change times in microseconds
    (8) comma separated list of deterministic output pins corresponding to the times in (8)
    (9) comma separated states (0 or 1) corresponding to the times in (8)
    (10) ETX (End of Text) character, aka b'\x03'

(3) After the microcontroller has seen a correctly formatted data packet, it
will send the string "RECEIVED" over the serial connection and then immediately
begin performing the specified acquisition cycles.

(4) If the microcontroller recieves any serial communication that is not
prefixed with the STX character, it will clear the serial buffer, send 
"ERROR" over the serial connection, and return to the main loop (i.e. step 1).

(5) During each acquisition cycle, the microcontroller will log all changes to
the input pins and when they occurred. It will then report these over serial
at the end of the cycle. The serial output will be a sequence of lines containing
the pin number, the state of the pin (0 or 1), the time in microseconds when
the state change occurred (from the start of that cycle), and the current 
acquisition cycle index. The output is formatted as follows, where <pin> is 
2 bytes (int16), <state> is 1 byte (uint8), <micros> is 4 bytes (unsigned long) 
and <cycleIndex> is 4 bytes (unsigned long):

    "<STX><pin><state><micros><cycleIndex>\n"

(6) Once per cycle, the microcontroller will check for an interrupt signal,
which should be the single character "I". If detected, the microcontroller will
send the string "INTERRUPTED" over the serial connection and return to the
main loop (i.e. step 1).

(7) When the microcontroller has completed the specified number of acquisition
cycles, it will send the string "F<ETX>" over the serial connection and return to the 
main loop (i.e. step 1).
*/

const int SERIAL_START_DELAY       = 100;  // Delay in milliseconds before starting serial communication
const int MAX_INPUT_PINS           = 18;   // Maximum number of input pins to monitor
const int MAX_RANDOM_OUTPUT_PINS   = 20;   // Maximum number of output pins for the random bit sequence
const int MAX_OUTPUT_STATE_CHANGES = 200;  // Maximum number of state changes to perform
const int MAX_INPUT_STATE_CHANGES  = 2000; // Maximum number of input state changes to log per cycle

// Global timing variables
elapsedMicros elapsed_cycle_time; 
unsigned long cycle_index = 0;

// Input pins to monitor
int num_input_pins;
unsigned long input_pins[MAX_INPUT_PINS];

// Buffers to store changes of input pin states
int previous_input_pin_states[MAX_INPUT_PINS];
int input_log_buffer_index = 0;
int16_t input_log_pins[MAX_INPUT_STATE_CHANGES];
uint8_t input_log_states[MAX_INPUT_STATE_CHANGES];
unsigned long input_log_times[MAX_INPUT_STATE_CHANGES];


/**
 * Interrupt service routine for input pins.
 * 
 * This function is called whenever the state of an input pin changes. It checks
 * which pin changed state and stores the pin number, the new state, and the
 * current time in appropriate buffers.
**/        
void inputStateISR() {
    for (int i = 0; i < num_input_pins; i++) {
        int current_state = digitalRead(input_pins[i]);
        if (current_state != previous_input_pin_states[i]) {
            if (input_log_buffer_index < MAX_INPUT_STATE_CHANGES) {
                input_log_pins[input_log_buffer_index] = static_cast<int16_t>(input_pins[i]);
                input_log_states[input_log_buffer_index] = static_cast<uint8_t>(current_state);
                input_log_times[input_log_buffer_index] = static_cast<unsigned long>(elapsed_cycle_time);
                previous_input_pin_states[i] = current_state;
                input_log_buffer_index++;
            }
        }
    }
}

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
 * Performs the acquisition loop.
 * 
 * @param num_cycles The number of acquisition cycles to perform.
 * @param cycle_duration The duration of each acquisition cycle in microseconds.
 * @param input_pins An array of input pins to monitor.
 * @param num_input_pins The number of input pins to monitor.
 * @param random_output_pins An array of output pins for the random bit sequence.
 * @param num_random_output_pins The number of output pins for the random bit sequence.
 * @param cycles_per_random_update The number of cycles between each update of the random bit.
 * @param state_change_times An array of times in microseconds when the deterministic output pins should change states.
 * @param state_change_pins An array of deterministic output pins to change states.
 * @param state_change_states An array of states (0 or 1) corresponding to the times in state_change_times.
 * @param num_state_changes The number of state changes to perform.
**/
void acquisitionLoop(
    unsigned long num_cycles,
    unsigned long cycle_duration,
    unsigned long* input_pins,
    int num_input_pins,
    unsigned long* random_output_pins,
    int num_random_output_pins,
    int cycles_per_random_update,
    unsigned long* state_change_times,
    unsigned long* state_change_pins,
    unsigned long* state_change_states,
    int num_state_changes
) {
    // Initialize the input pins
    for (int i = 0; i < num_input_pins; i++) {
        pinMode(input_pins[i], INPUT);
        attachInterrupt(digitalPinToInterrupt(input_pins[i]), inputStateISR, CHANGE);
    }

    // Initialize the deterministic output pins
    for (int i = 0; i < num_state_changes; i++) {
        pinMode(state_change_pins[i], OUTPUT);
    }

    // Initialize the random output pins
    for (int i = 0; i < num_random_output_pins; i++) {
        pinMode(random_output_pins[i], OUTPUT);
    }

    // Initialize indexes
    cycle_index = 0;
    int step_index = 0;

    // initialize flags
    bool finished_wrap_up = false;

    // Initialize the random bit
    int random_bit = 0;

    // Initialize timers
    elapsed_cycle_time = 0;

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

            // Report the current state of the input pins
            for (int i = 0; i < input_log_buffer_index; i++) {
                Serial.write(0x02); // STX 
                Serial.write((byte*)&input_log_pins[i], sizeof(int16_t)); // pin number
                Serial.write(input_log_states[i]); // pin state
                Serial.write((byte*)&input_log_times[i], sizeof(unsigned long)); // time in microseconds
                Serial.write((byte*)&cycle_index, sizeof(unsigned long)); // cycle index
                Serial.write('\n');
            }
            input_log_buffer_index = 0;
            

            // Update the random bit
            if (cycle_index % cycles_per_random_update == 0) {
                random_bit = random(0, 2);
                for (int i = 0; i < num_random_output_pins; i++) {
                    digitalWrite(random_output_pins[i], random_bit);
                }
            }

            // Check for interrupt signal
            if (Serial.available() > 0) {
                char interruptChar = Serial.read();
                if (interruptChar == 'I') {
                    Serial.println("INTERRUPTED");
                    return;
                } else {
                    Serial.flush();
                }
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
    // Send the finish message
    Serial.write("F");  
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

            // Read the list of input pins
            String line = Serial.readStringUntil('\n');
            parseLine(line.c_str(), input_pins, MAX_INPUT_PINS, &num_input_pins);

            // Read the list of random output pins
            unsigned long random_output_pins[MAX_RANDOM_OUTPUT_PINS];
            int num_random_output_pins;
            line = Serial.readStringUntil('\n');
            parseLine(line.c_str(), random_output_pins, MAX_RANDOM_OUTPUT_PINS, &num_random_output_pins);

            // Read the number of cycles between each random bit update
            int cycles_per_random_update = strtoul(Serial.readStringUntil('\n').c_str(), NULL, 10);

            // Read the state change times
            unsigned long state_change_times[MAX_OUTPUT_STATE_CHANGES];
            int num_state_changes;
            line = Serial.readStringUntil('\n');
            parseLine(line.c_str(), state_change_times, MAX_OUTPUT_STATE_CHANGES, &num_state_changes);

            // Read the state change pins
            unsigned long state_change_pins[MAX_OUTPUT_STATE_CHANGES];
            line = Serial.readStringUntil('\n');
            parseLine(line.c_str(), state_change_pins, MAX_OUTPUT_STATE_CHANGES, nullptr);
                    
            // Read the state change states
            unsigned long state_change_states[MAX_OUTPUT_STATE_CHANGES];
            line = Serial.readStringUntil('\n');
            parseLine(line.c_str(), state_change_states, MAX_OUTPUT_STATE_CHANGES, nullptr);

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
                    random_output_pins,
                    num_random_output_pins,
                    cycles_per_random_update,
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

