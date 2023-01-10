// Define the input GPIOs
const int inputPin1 = 2;
const int inputPin2 = 2;
const int inputPin3 = 4;
const int inputPin4 = 5;
const int inputPin5 = 6;

// Set the initial state of input pins
int inputPin1State = 0;        
int inputPin2State = 0;        
int inputPin3State = 0;        
int inputPin4State = 0;        
int inputPin5State = 0;      

 // Set the previous state of input pins
 int inputPin1StatePrev = 0;        
 int inputPin2StatePrev = 0;        
 int inputPin3StatePrev = 0;        
 int inputPin4StatePrev = 0;        
 int inputPin5StatePrev = 0;        



void setup() {
  // initialize the button pin as a input:
  pinMode(inputPin1, INPUT);
  pinMode(inputPin2, INPUT);
  pinMode(inputPin3, INPUT);
  pinMode(inputPin4, INPUT);
  pinMode(inputPin5, INPUT);
  
  // initialize serial communication:
  Serial.begin(9600);
}


void loop() {
  // read the pushbutton input pin:
  inputPin1State = digitalRead(inputPin1);
  inputPin2State = digitalRead(inputPin2);
  inputPin3State = digitalRead(inputPin3);
  inputPin4State = digitalRead(inputPin4);
  inputPin5State = digitalRead(inputPin5);
  
  // compare the buttonState to its previous state
  if (
      (inputPin1State != inputPin1StatePrev) || 
      (inputPin2State != inputPin2StatePrev) ||
      (inputPin3State != inputPin3StatePrev) ||
      (inputPin4State != inputPin4StatePrev) ||
      (inputPin5State != inputPin5StatePrev)
      )
      {
        Serial.print("state change: ");
        Serial.print(inputPin1State);
        Serial.print(",");
        Serial.print(inputPin2State);
        Serial.print(",");
        Serial.print(inputPin3State);
        Serial.print(",");
        Serial.print(inputPin4State);
        Serial.print(",");
        Serial.println(inputPin5State);

         inputPin1StatePrev = inputPin1State;        
         inputPin2StatePrev = inputPin2State;        
         inputPin3StatePrev = inputPin3State;        
         inputPin4StatePrev = inputPin4State;        
         inputPin5StatePrev = inputPin5State;  

         
         
  }
      
    

}
