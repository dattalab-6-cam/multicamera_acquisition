// Define the input GPIOs
const int input_pins [5] = {2,3,4,5,6};

// Set the initial state of input pins
int input_state [5] = {0,0,0,0,0};
int input_state_prev [5] = {0,0,0,0,0};    



void setup() {
  for (int pin : input_pins) { 
    pinMode(pin, INPUT); 
  }

  
  // initialize serial communication:
  Serial.begin(9600);
}


void loop() {

  int pin_i = 0;
  bool state_change = false;
  for (int pin : input_pins) { 
    input_state[pin_i]=digitalRead(pin);
    if (input_state[pin_i] != input_state_prev[pin_i]){
      state_change = true;
      input_state_prev[pin_i] = input_state[pin_i];
    }
    pin_i++; 
  }
  
  // compare the buttonState to its previous state
  if (state_change == true)
      {
        Serial.print("state change: ");
        for (int pin : input_state) { 
          Serial.print(pin);
          Serial.print(",");
        }
        Serial.println("");  
  }
      
    

}
