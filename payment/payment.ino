/**
 * Parking Management System - Payment Processing Module
 * This Arduino sketch handles RFID card payment processing for the parking system.
 * It reads card data, processes payments, and updates card balances.
 */

#include <SPI.h>
#include <MFRC522.h>

// Pin definitions for RFID-RC522 module
#define RST_PIN 9
#define SS_PIN 10

// Initialize RFID reader
MFRC522 mfrc522(SS_PIN, RST_PIN);
MFRC522::MIFARE_Key key;
MFRC522::StatusCode card_status;

// State variables for payment processing
bool awaitingUpdate = false;    // Flag to track if waiting for balance update
bool sentReady = false;         // Flag to track if "READY" signal was sent
String currentPlate = "";       // Stores current vehicle plate number
long currentBalance = 0;        // Stores current card balance

// Timeout handling variables
unsigned long readySentTime = 0;
const unsigned long RESPONSE_TIMEOUT = 10000; // 10 seconds timeout

void setup() {
    // Initialize serial communication and RFID module
    Serial.begin(9600);
    SPI.begin();
    mfrc522.PCD_Init();

    // Set default authentication key
    for (byte i = 0; i < 6; i++) {
        key.keyByte[i] = 0xFF;
    }

    Serial.println(F("==== PAYMENT MODE RFID ===="));
    Serial.println(F("Place your card near the reader..."));
}

void loop() {
    // Card reading and initial data processing
    if (!awaitingUpdate) {
        // Check for new card
        if (!mfrc522.PICC_IsNewCardPresent() || !mfrc522.PICC_ReadCardSerial()) return;

        // Read card data
        currentPlate = readBlockData(2, "Car Plate");
        String balanceStr = readBlockData(4, "Balance");

        // Validate card data
        if (currentPlate.startsWith("[") || balanceStr.startsWith("[")) {
            Serial.println(F("⚠️ Invalid card data. Try again."));
            mfrc522.PICC_HaltA();
            mfrc522.PCD_StopCrypto1();
            delay(2000);
            return;
        }

        // Clean the data
        currentPlate.trim();  // Remove leading/trailing whitespace
        balanceStr.trim();    // Remove leading/trailing whitespace
        
        // Convert and validate balance
        currentBalance = balanceStr.toInt();

        // Send card data to PC (clean format)
        Serial.print(currentPlate);  // Already trimmed
        Serial.print(",");
        Serial.println(currentBalance);  // Send clean integer balance

        awaitingUpdate = true;
        sentReady = false;
    }

    // Send READY signal to PC
    if (awaitingUpdate && !sentReady) {
        Serial.println("READY");
        sentReady = true;
        readySentTime = millis();  // Start timeout timer
    }

    // Handle PC response and update card
    if (awaitingUpdate && sentReady) {
        // Check for timeout
        if (millis() - readySentTime > RESPONSE_TIMEOUT) {
            Serial.println("[TIMEOUT] No response from PC. Resetting.");
            awaitingUpdate = false;
            sentReady = false;
            mfrc522.PICC_HaltA();
            mfrc522.PCD_StopCrypto1();
            delay(1000);
            return;
        }

        // Process PC response
        if (Serial.available()) {
            String response = Serial.readStringUntil('\n');
            response.trim();

            Serial.print("[RECEIVED FROM PC]: ");
            Serial.println(response);

            if (response == "I") {
                Serial.println("[DENIED] Insufficient balance");
            } else {
                // Process new balance
                response.trim();
                long newBalance = response.toInt();
                Serial.print(newBalance);

                if (newBalance >= 0) {
                    // Update card with new balance
                    Serial.println("[WRITING] New balance to card...");
                    writeBlockData(4, String(newBalance));
                    Serial.println("DONE");
                    Serial.print("[UPDATED] New Balance: ");
                    Serial.println(newBalance);
                } else {
                    Serial.println("[ERROR] Invalid new balance received.");
                }
            }

            // Reset state
            awaitingUpdate = false;
            sentReady = false;

            mfrc522.PICC_HaltA();
            mfrc522.PCD_StopCrypto1();
            delay(2000);
        }
    }
}

/**
 * Reads data from a specific block on the RFID card
 * @param blockNumber The block number to read from
 * @param label Label for debugging purposes
 * @return String containing the read data
 */
String readBlockData(byte blockNumber, String label){
    byte buffer[18];
    byte bufferSize = sizeof(buffer);

    // Authenticate with the card
    card_status = mfrc522.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNumber, &key, &(mfrc522.uid));
    if (card_status != MFRC522::STATUS_OK) {
        Serial.print("❌ Auth failed for ");
        Serial.println(label);
        return "[Auth Fail]";
    }

    // Read the block
    card_status = mfrc522.MIFARE_Read(blockNumber, buffer, &bufferSize);
    if (card_status != MFRC522::STATUS_OK) {
        Serial.print("❌ Read failed for ");
        Serial.println(label);
        return "[Read Fail]";
    }

    // Convert buffer to string
    String data = "";
    for (uint8_t i = 0; i < 16; i++) {
        data += (char)buffer[i];
    }
    data.trim();
    return data;
}

/**
 * Writes data to a specific block on the RFID card
 * @param blockNumber The block number to write to
 * @param data The data to write
 */
void writeBlockData(byte blockNumber, String data) {
    byte buffer[16];
    data.trim();
    while (data.length() < 16) data += ' ';
    data.substring(0, 16).getBytes(buffer, 16);

    // Authenticate with the card
    card_status = mfrc522.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNumber, &key, &(mfrc522.uid));
    if (card_status != MFRC522::STATUS_OK) {
        Serial.println("❌ Auth failed on write");
        return;
    }

    // Write the data
    card_status = mfrc522.MIFARE_Write(blockNumber, buffer, 16);
    if (card_status != MFRC522::STATUS_OK) {
        Serial.println("❌ Write failed");
    }
}