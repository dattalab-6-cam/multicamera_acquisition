
/*
******************
CAREFUL
******************
Don't leave the lights all on for too long,
the circuitry isn't designed to pump a constant 60W. 
*/

// LED trigger pins
int LED1 = 38;
int LED2 = 39;
int LED3 = 40;
int LED4 = 41;
int LED5 = 14;
int LED6 = 15;
int LED7 = 16; // side led
int LED8 = 17; // side led

const int n_top = 6;
int top_pins [n_top] = {LED1, LED2, LED3, LED4, LED5, LED6};
const int n_bottom = 2;
int bottom_pins [n_bottom] = {LED7, LED8};

void setup() {
  // put your setup code here, to run once:
  for (int i=0; i < n_top; i++){
    pinMode(top_pins[i], OUTPUT);
  }
  for (int i=0; i < n_bottom; i++){
    pinMode(bottom_pins[i], OUTPUT);
  }
  Serial.begin(9600);
}

void loop() {
  // put your main code here, to run repeatedly:

  // top cams
  for (int i=0; i < n_top; i++){
    digitalWrite(top_pins[i], HIGH);
  }
  Serial.print("TOP");
  delay(3000);
  for (int i=0; i < n_top; i++){
    digitalWrite(top_pins[i], LOW);
  }
  Serial.println("-- > OFF");
  delay(1000);

  // bottom cams
  for (int i=0; i < n_bottom; i++){
    digitalWrite(bottom_pins[i], HIGH);
  }
  Serial.print("BOTTOM");
  delay(3000);
  for (int i=0; i < n_bottom; i++){
    digitalWrite(bottom_pins[i], LOW);
  }
  Serial.println("-- > OFF");
  delay(1000);

}
