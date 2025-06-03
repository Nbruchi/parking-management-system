/**
 * Parking Management System - RFID Card Writer Module
 * This Arduino sketch writes data to RFID cards used in the parking system.
 * It allows registration of new cards with vehicle plate numbers and initial balance.
 */

#include <SPI.h>
#include <MFRC522.h>

// Pin definitions for RFID-RC522 module
#define RST_PIN  9 
#define SS_PIN   10  

// Initialize RFID reader
MFRC522 mfrc522(SS_PIN, RST_PIN);
MFRC522::MIFARE_Key key;
MFRC522::StatusCode card_status;

void setup() {
  // Initialize serial communication and RFID module
  Serial.begin(9600);
  SPI.begin();
  mfrc522.PCD_Init();
  Serial.println(F("==== CARD REGISTRATION ===="));
  Serial.println(F("Place your RFID card near the reader..."));
  Serial.println();
}

void loop() {
  // Set default authentication key
  for(byte i = 0; i < 6; i++) {
    key.keyByte[i] = 0xFF;
  }

  // Wait for a card
  if (!mfrc522.PICC_IsNewCardPresent()) return;
  if (!mfrc522.PICC_ReadCardSerial()) return;

  Serial.println(F("📶 Card detected!"));

  // Buffers for writing data
  byte carPlateBuff[16];
  byte balanceBuff[16];

  // Request and validate car plate number
  while (true) {
    Serial.println(F("Enter car plate number (must be exactly 7 characters, e.g., RAG234H), end with #:"));
    Serial.setTimeout(20000L); // Wait up to 20 seconds for input
    byte len = Serial.readBytesUntil('#', (char *)carPlateBuff, 16);

    if (len == 7) {
      padBuffer(carPlateBuff, len);
      break; // valid input
    } else {
      Serial.print(F("❌ Invalid input length (got "));
      Serial.print(len);
      Serial.println(F(" characters). Try again.\n"));
      flushSerial();
    }
  }

  // Request and validate balance
  while (true) {
    Serial.println(F("Enter balance (max 16 characters), end with #:"));
    Serial.setTimeout(20000L); // Wait up to 20 seconds for input
    byte len = Serial.readBytesUntil('#', (char *)balanceBuff, 16);

    if (len > 0 && len <= 16) {
      padBuffer(balanceBuff, len);
      break; // valid input
    } else {
      Serial.println(F("❌ Invalid balance input. Try again.\n"));
      flushSerial();
    }
  }

  // Define RFID data blocks
  byte carPlateBlock = 2;  // Block 2 for plate number
  byte balanceBlock = 4;   // Block 4 for balance

  // Write data to card
  writeBytesToBlock(carPlateBlock, carPlateBuff);
  writeBytesToBlock(balanceBlock, balanceBuff);

  // Display confirmation
  Serial.println();
  Serial.print(F("✅ Car Plate written to block "));
  Serial.print(carPlateBlock);
  Serial.print(F(": "));
  Serial.println((char*)carPlateBuff);

  Serial.print(F("✅ Balance written to block "));
  Serial.print(balanceBlock);
  Serial.print(F(": "));
  Serial.println((char*)balanceBuff);

  Serial.println(F("🔄 Please remove the card to write again."));
  Serial.println(F("--------------------------\n"));

  // Cleanup
  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();
  delay(2000);
}

/**
 * Pads the buffer with spaces up to 16 bytes
 * @param buffer The buffer to pad
 * @param len Current length of the buffer
 */
void padBuffer(byte* buffer, byte len) {
  for(byte i = len; i < 16; i++) {
    buffer[i] = ' ';
  }
}

/**
 * Clears the Serial input buffer
 */
void flushSerial() {
  while (Serial.available()) {
    Serial.read();
  }
}

/**
 * Authenticates and writes 16 bytes to a specific block on the RFID card
 * @param block The block number to write to
 * @param buff The buffer containing data to write
 */
void writeBytesToBlock(byte block, byte buff[]) {
  // Authenticate with the card
  card_status = mfrc522.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, block, &key, &(mfrc522.uid));

  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("❌ Authentication failed: "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
    return;
  } else {
    Serial.println(F("🔓 Authentication success."));
  }

  // Write data to the block
  card_status = mfrc522.MIFARE_Write(block, buff, 16);
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("❌ Write failed: "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
  } else {
    Serial.println(F("✅ Data written successfully."));
  }
}