/**
 * Parking Management System - RFID Card Reader/Writer Module
 * This Arduino sketch handles both reading and writing data to RFID cards.
 * It reads vehicle plate number and balance, and can update the balance.
 */
#include <SPI.h>
#include <MFRC522.h>
#include <ArduinoJson.h>

// Pin definitions for RFID-RC522 module
#define RST_PIN 9           
#define SS_PIN 10          

// Initialize RFID reader
MFRC522 mfrc522(SS_PIN, RST_PIN);
MFRC522::MIFARE_Key key;
MFRC522::StatusCode card_status;

// Block numbers for data storage
#define PLATE_BLOCK 2
#define BALANCE_BLOCK 4

void setup() {
    // Initialize serial communication and RFID module
    Serial.begin(9600);                                           
    SPI.begin();                                                 
    mfrc522.PCD_Init();                                             
    Serial.println(F("==== RFID CARD READER/WRITER ===="));
    Serial.println(F("Place your card near the reader..."));
    Serial.println();
}

void loop() {
    // Set default authentication key
    for (byte i = 0; i < 6; i++) {
        key.keyByte[i] = 0xFF;
    }

    // Check for commands from Python
    if (Serial.available() > 0) {
        char cmd = Serial.read();
        if (cmd == 'W') {
            // Wait for JSON data
            delay(100);  // Give time for data to arrive
            if (Serial.available() > 0) {
                handleWriteCommand();
            }
        }
        return;  // Process one command at a time
    }

    // Check for new card
    if (!mfrc522.PICC_IsNewCardPresent()) return;
    if (!mfrc522.PICC_ReadCardSerial()) return;

    Serial.println(F("Card detected!"));
    
    // Read card data from specific blocks
    String carPlate = readBlockData(PLATE_BLOCK, "Car Plate");
    String balance = readBlockData(BALANCE_BLOCK, "Balance");

    // Display card information
    Serial.println();
    Serial.println(F("===== Card Info ====="));
    Serial.print(F("🚗 Car Plate : "));
    Serial.println(carPlate);
    Serial.print(F("💰 Balance    : "));
    Serial.println(balance);
    Serial.println(F("====================="));
    Serial.println();

    // Cleanup and wait before next read
    mfrc522.PICC_HaltA();
    mfrc522.PCD_StopCrypto1();
    delay(1000); // wait before scanning again
}

void handleWriteCommand() {
    Serial.println(F("DEBUG: Received write command"));
    
    // Wait for JSON data to arrive
    delay(100);
    
    // Read all available data
    String jsonString = "";
    unsigned long startTime = millis();
    while (millis() - startTime < 1000) {  // 1 second timeout
        if (Serial.available()) {
            char c = Serial.read();
            if (c == '\n') break;  // End of JSON
            jsonString += c;
        }
        delay(1);
    }
    
    Serial.print(F("DEBUG: Received JSON string: "));
    Serial.println(jsonString);
    
    // Parse JSON
    StaticJsonDocument<200> doc;
    DeserializationError error = deserializeJson(doc, jsonString);
    
    if (error) {
        Serial.print(F("DEBUG: JSON Error: "));
        Serial.println(error.c_str());
        Serial.print(F("DEBUG: JSON string length: "));
        Serial.println(jsonString.length());
        Serial.println(F("Write failed: Invalid JSON"));
        return;
    }

    Serial.println(F("DEBUG: JSON parsed successfully"));

    // Check for new card
    if (!mfrc522.PICC_IsNewCardPresent()) {
        Serial.println(F("DEBUG: No card present"));
        Serial.println(F("Write failed: No card present"));
        return;
    }
    Serial.println(F("DEBUG: Card detected"));

    if (!mfrc522.PICC_ReadCardSerial()) {
        Serial.println(F("DEBUG: Could not read card serial"));
        Serial.println(F("Write failed: Could not read card"));
        return;
    }
    Serial.println(F("DEBUG: Card serial read successfully"));

    // Get data from JSON
    if (!doc.containsKey("plate") || !doc.containsKey("balance")) {
        Serial.println(F("DEBUG: Missing required JSON fields"));
        Serial.println(F("Write failed: Invalid JSON format"));
        return;
    }

    const char* plate = doc["plate"];
    int balance = doc["balance"];

    Serial.print(F("DEBUG: Received data - Plate: "));
    Serial.print(plate);
    Serial.print(F(", Balance: "));
    Serial.println(balance);

    // Write balance to card
    Serial.println(F("DEBUG: Attempting to write balance..."));
    if (writeBlockData(BALANCE_BLOCK, String(balance), "Balance")) {
        Serial.println(F("DEBUG: Write successful"));
        Serial.println(F("Write successful"));
    } else {
        Serial.println(F("DEBUG: Write failed"));
        Serial.println(F("Write failed"));
    }

    // Cleanup
    mfrc522.PICC_HaltA();
    mfrc522.PCD_StopCrypto1();
    Serial.println(F("DEBUG: Write operation completed"));
}

String readBlockData(byte blockNumber, String label) {
    byte buffer[18];
    byte bufferSize = sizeof(buffer);

    // Authenticate with the card
    card_status = mfrc522.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNumber, &key, &(mfrc522.uid));
    if (card_status != MFRC522::STATUS_OK) {
        Serial.print(F("❌ Auth failed for "));
        Serial.print(label);
        Serial.print(F(": "));
        Serial.println(mfrc522.GetStatusCodeName(card_status));
        return "[Auth Fail]";
    }

    // Read the block
    card_status = mfrc522.MIFARE_Read(blockNumber, buffer, &bufferSize);
    if (card_status != MFRC522::STATUS_OK) {
        Serial.print(F("❌ Read failed for "));
        Serial.print(label);
        Serial.print(F(": "));
        Serial.println(mfrc522.GetStatusCodeName(card_status));
        return "[Read Fail]";
    }

    // Convert buffer to string
    String data = "";
    for (uint8_t i = 0; i < 16; i++) {
        data += (char)buffer[i];
    }
    data.trim(); // Remove extra padding
    return data;
}

bool writeBlockData(byte blockNumber, String data, String label) {
    Serial.print(F("DEBUG: Writing to block "));
    Serial.println(blockNumber);
    
    byte buffer[16];
    byte bufferSize = sizeof(buffer);

    // Pad data to 16 bytes
    data.toCharArray((char*)buffer, 16);
    for (int i = data.length(); i < 16; i++) {
        buffer[i] = ' ';  // Pad with spaces
    }

    Serial.print(F("DEBUG: Data to write: "));
    for (int i = 0; i < 16; i++) {
        Serial.print((char)buffer[i]);
    }
    Serial.println();

    // Authenticate with the card
    Serial.println(F("DEBUG: Authenticating..."));
    card_status = mfrc522.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNumber, &key, &(mfrc522.uid));
    if (card_status != MFRC522::STATUS_OK) {
        Serial.print(F("DEBUG: Auth failed - "));
        Serial.println(mfrc522.GetStatusCodeName(card_status));
        Serial.print(F("❌ Auth failed for "));
        Serial.print(label);
        Serial.print(F(": "));
        Serial.println(mfrc522.GetStatusCodeName(card_status));
        return false;
    }
    Serial.println(F("DEBUG: Authentication successful"));

    // Write the block
    Serial.println(F("DEBUG: Writing block..."));
    card_status = mfrc522.MIFARE_Write(blockNumber, buffer, 16);
    if (card_status != MFRC522::STATUS_OK) {
        Serial.print(F("DEBUG: Write failed - "));
        Serial.println(mfrc522.GetStatusCodeName(card_status));
        Serial.print(F("❌ Write failed for "));
        Serial.print(label);
        Serial.print(F(": "));
        Serial.println(mfrc522.GetStatusCodeName(card_status));
        return false;
    }
    Serial.println(F("DEBUG: Write successful"));

    return true;
}