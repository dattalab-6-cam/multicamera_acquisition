// LED trigger pins
int pins_to_keep_off[] = {16, 17, 20, 21, 38, 39, 40, 41};
int led_pins[] = {14,15,22,23}; 
int pwm_vals[] = {220};

const int n_leds_off = 8;
const int n_leds = 4;
const int n_pwms = 1;


void setup() {
  // put your setup code here, to run once:
  
  for (int i=0; i < n_leds; i++){
    pinMode(led_pins[i], OUTPUT);
    analogWrite(led_pins[i], 0);
    analogWriteFrequency(led_pins[i], 146484);  // "ideal" freq for cpu 600 mhz that is above mouse upper hearing limit
  }

  for (int i=0; i < n_leds_off; i++){
    pinMode(pins_to_keep_off[i], OUTPUT);
    analogWrite(pins_to_keep_off[i], 0);
  }

  // Option 2: turn on forever
  for (int iPWM=0; iPWM < n_pwms; iPWM++){
    for (int iLED=0; iLED < n_leds; iLED++){
      analogWrite(led_pins[iLED], pwm_vals[iPWM]);
    }
  }

}

void loop() {
  // put your main code here, to run repeatedly:

  // Option 1: turn on /off
  // for (int iPWM=0; iPWM < n_pwms; iPWM++){
    
  //   // turn on
  //   for (int iLED=0; iLED < n_leds; iLED++){
  //     analogWrite(led_pins[iLED], pwm_vals[iPWM]);
  //   }
    
  //   delay(1000);

  //   // turn off
  //   for (int iLED=0; iLED < n_leds; iLED++){
  //     analogWrite(led_pins[iLED], 0);
  //   }

  //   delay(2000);
  // }
  
}
