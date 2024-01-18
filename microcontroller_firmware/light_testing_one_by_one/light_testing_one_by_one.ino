
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

const int n_pins = 8;
int pins [n_pins] = {LED1, LED2, LED3, LED4, LED5, LED6, LED7, LED8};

void setup() {
  // put your setup code here, to run once:
  for (int i=0; i < n_pins; i++){
    pinMode(pins[i], OUTPUT);
  }
  Serial.begin(9600);
}

void loop() {
  // put your main code here, to run repeatedly:
  for (int i=0; i < n_pins; i++){
    digitalWrite(pins[i], HIGH);
    digitalWrite(13, HIGH);
    Serial.print(i);
    delay(1000);
    digitalWrite(pins[i], LOW);
    digitalWrite(13, LOW);
    Serial.println("-- > OFF");
    delay(500);

  }
}
