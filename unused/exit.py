"""
Parking Management System - Vehicle Exit Module
This module handles vehicle exit detection, payment verification, and gate control.
It uses YOLOv8 for license plate detection and Tesseract OCR for text recognition.
"""

import cv2
from ultralytics import YOLO
import pytesseract
import os
import time
import serial
import serial.tools.list_ports
import random
import sqlite3
from datetime import datetime
from collections import Counter
import csv

# Configure Tesseract OCR path
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Load YOLOv8 model for license plate detection
model = YOLO(r'./best.pt')

# Database and CSV files
DB_FILE = 'parking.db'
CSV_FILE = 'plates_log.csv'

def get_db():
    """Get database connection"""
    db = sqlite3.connect(DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES)
    db.row_factory = sqlite3.Row
    return db

def update_csv_payment_status(plate_number, payment_status, payment_time=None):
    """Update payment status in CSV file"""
    try:
        # Read all entries
        entries = []
        with open(CSV_FILE, 'r', newline='') as f:
            reader = csv.reader(f)
            header = next(reader)  # Save header
            entries = list(reader)
        
        # Find the most recent entry for this plate
        for i in range(len(entries)-1, -1, -1):
            if entries[i][0] == plate_number and not entries[i][3]:  # If plate matches and no payment timestamp
                entries[i][1] = str(payment_status)  # Update payment status
                if payment_time:
                    entries[i][3] = payment_time.strftime('%Y-%m-%d %H:%M:%S')
                break
        
        # Write back all entries
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(entries)
            
        print(f"[CSV] Updated payment status for {plate_number}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to update CSV: {e}")
        return False

def check_and_log_exit(plate_number):
    """
    Atomically checks payment status from CSV and logs exit if authorized.
    Returns (success, is_authorized) tuple.
    """
    try:
        # Read payment status from CSV
        with open(CSV_FILE, 'r', newline='') as f:
            reader = csv.DictReader(f)
            entries = list(reader)
            
        # Find the most recent entry for this plate
        latest_entry = None
        for entry in reversed(entries):
            if entry['Plate Number'] == plate_number:
                latest_entry = entry
                break
                
        if not latest_entry:
            print(f"[CSV] No entry found for {plate_number}")
            return False, False
            
        # Check payment status from CSV
        is_authorized = int(latest_entry['Payment Status']) == 1
        exit_time = datetime.now()
        
        # Update CSV with payment timestamp if not already set
        if not latest_entry['Payment Timestamp']:
            latest_entry['Payment Timestamp'] = exit_time.strftime('%Y-%m-%d %H:%M:%S')
            # Write back all entries
            with open(CSV_FILE, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['Plate Number', 'Payment Status', 'Timestamp', 'Payment Timestamp'])
                writer.writeheader()
                writer.writerows(entries)
            print(f"[CSV] Updated payment timestamp for {plate_number}")
        
        if is_authorized:
            print(f"[CSV] Authorized exit logged for {plate_number}")
        else:
            print(f"[CSV] Unauthorized exit logged for {plate_number}")
            
        return True, is_authorized
            
    except Exception as e:
        print(f"[ERROR] Failed to process exit: {e}")
        return False, False

def detect_arduino_port():
    """
    Detects the Arduino port by checking available serial ports.
    Returns the port device name if found, None otherwise.
    """
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        if "Arduino" in port.description or "COM7" in port.description or "USB-SERIAL" in port.description:
            return port.device
    return None

# Initialize Arduino connection
arduino_port = detect_arduino_port()
if arduino_port:
    print(f"[CONNECTED] Arduino on {arduino_port}")
    arduino = serial.Serial(arduino_port, 9600, timeout=1)
    time.sleep(2)
else:
    print("[ERROR] Arduino not detected.")
    arduino = None

def mock_ultrasonic_distance():
    """
    Simulates ultrasonic sensor readings for testing.
    Returns a random distance between 10 and 40 cm.
    """
    return random.choice([random.randint(10, 40)])

# Initialize video capture and plate buffer
cap = cv2.VideoCapture(0)
plate_buffer = []

print("[EXIT SYSTEM] Ready. Press 'q' to quit.")

while True:
    # Read frame from webcam
    ret, frame = cap.read()
    if not ret:
        break

    # Get distance from ultrasonic sensor (mocked)
    distance = mock_ultrasonic_distance()
    print(f"[SENSOR] Distance: {distance} cm")

    # Process frame if vehicle is detected
    if distance <= 50:
        # Detect license plates using YOLOv8
        results = model(frame)

        for result in results:
            for box in result.boxes:
                # Extract plate region
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                plate_img = frame[y1:y2, x1:x2]

                # Preprocess image for OCR
                gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
                blur = cv2.GaussianBlur(gray, (5, 5), 0)
                thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

                # Perform OCR on plate image
                plate_text = pytesseract.image_to_string(
                    thresh, config='--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                ).strip().replace(" ", "")

                # Validate and process plate number
                if "RA" in plate_text:
                    start_idx = plate_text.find("RA")
                    plate_candidate = plate_text[start_idx:]
                    if len(plate_candidate) >= 7:
                        plate_candidate = plate_candidate[:7]
                        prefix, digits, suffix = plate_candidate[:3], plate_candidate[3:6], plate_candidate[6]
                        
                        # Validate plate format (3 letters + 3 numbers + 1 letter)
                        if (prefix.isalpha() and prefix.isupper() and
                            digits.isdigit() and suffix.isalpha() and suffix.isupper()):
                            print(f"[VALID] Plate Detected: {plate_candidate}")
                            plate_buffer.append(plate_candidate)

                            # Process plate after multiple detections
                            if len(plate_buffer) >= 3:
                                most_common = Counter(plate_buffer).most_common(1)[0][0]
                                plate_buffer.clear()

                                # Check payment and log exit atomically
                                success, is_authorized = check_and_log_exit(most_common)
                                
                                if success:
                                    if is_authorized:
                                        print(f"[ACCESS GRANTED] Payment complete for {most_common}")
                                        if arduino:
                                            arduino.write(b'1')  # Open gate
                                            print("[GATE] Opening gate (sent '1')")
                                            time.sleep(15)
                                            arduino.write(b'0')  # Close gate
                                            print("[GATE] Closing gate (sent '0')")
                                    else:
                                        print(f"[ACCESS DENIED] Payment NOT complete for {most_common}")
                                        if arduino:
                                            arduino.write(b'2')  # Trigger warning buzzer
                                            print("[ALERT] Buzzer triggered (sent '2')")
                                else:
                                    print(f"[ERROR] Failed to process exit for {most_common}")

                # Display processed images
                cv2.imshow("Plate", plate_img)
                cv2.imshow("Processed", thresh)
                time.sleep(0.5)

    # Display main feed with annotations
    annotated_frame = results[0].plot() if distance <= 50 else frame
    cv2.imshow('Webcam Feed', annotated_frame)

    # Check for exit command
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Cleanup
cap.release()
if arduino:
    arduino.close()
cv2.destroyAllWindows()
