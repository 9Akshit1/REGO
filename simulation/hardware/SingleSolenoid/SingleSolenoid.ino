int SOLENOID_PIN = 2;

void setup() {
  pinMode(SOLENOID_PIN, OUTPUT);
  Serial.begin(9600);
  Serial.println("Solenoid should smoothly extend/retract");
}

void loop() {
  Serial.println("\n--- PWM SWEEP UP ---");
  // 0 to 255 (smooth acceleration)
  for(int pwm=0; pwm<=255; pwm+=5) {
    analogWrite(SOLENOID_PIN, pwm);
    Serial.print("PWM="); Serial.println(pwm);
    delay(100);
  }
  
  Serial.println("--- PWM SWEEP DOWN ---");
  // 255 to 0 (smooth deceleration)  
  for(int pwm=255; pwm>=0; pwm-=5) {
    analogWrite(SOLENOID_PIN, pwm);
    Serial.print("PWM="); Serial.println(pwm);
    delay(100);
  }
}
