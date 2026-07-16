int coils[4] = {2, 3, 4, 5};  // D2-D5

void setup() {
  Serial.begin(9600);
  for (int i = 0; i < 4; i++) {
    pinMode(coils[i], OUTPUT);
    analogWrite(coils[i], 0);
  }
  Serial.println("4-coil REGO ring demo starting...");
}

void loop() {
  // Phase 1: center cluster
  center_cluster(4000);

  // Phase 2: static ring
  static_ring(6000);

  // Phase 3: rotating ring -- should smooth out the assymetries
  rotating_ring(12000);
}

// Phase 1: pull powder toward center 
void center_cluster(unsigned long ms) {
  Serial.println("Phase 1: Center cluster");
  int basePWM = 140;  
  for (int i = 0; i < 4; i++) analogWrite(coils[i], basePWM);     // basically, it should form a maximum at the center by,
  delay(ms);
}

// Phase 2: hold a simple ring 
void static_ring(unsigned long ms) {
  Serial.println("Phase 2: Static ring");
  int ringPWM = 120;  
  for (int i = 0; i < 4; i++) analogWrite(coils[i], ringPWM);
  delay(ms);
}

// Phase 3: slowly rotate the “hot spot”     -------------- might need some tuning
void rotating_ring(unsigned long ms) {
  Serial.println("Phase 3: Rotating ring");
  unsigned long tStart = millis();
  int basePWM = 110;   
  int boostPWM = 190;  

  while (millis() - tStart < ms) {
    for (int active = 0; active < 4; active++) {
      // set all to base first 
      for (int i = 0; i < 4; i++) analogWrite(coils[i], basePWM);
      // boost one coil
      analogWrite(coils[active], boostPWM);

      delay(400);  // how long the “hot spot” sits before moving
    }
  }

  // after rotation, go back to gentle ring
  for (int i = 0; i < 4; i++) analogWrite(coils[i], basePWM);
  delay(3000);
}
