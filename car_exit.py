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
import csv
from collections import Counter
import random
import sqlite3
from datetime import datetime

# Configure Tesseract OCR path
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Load YOLOv8 model for license plate detection
# model = YOLO(r'C:\Users\Admin\Desktop\Projects\parking-management-system\best.pt')
model = YOLO(r'./best.pt')

# Database file
DB_FILE = 'parking.db'

def get_db():
    """Get database connection"""
    db = sqlite3.connect(DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES)
    db.row_factory = sqlite3.Row
    return db

def log_vehicle_exit(plate_number, is_authorized=True):
    """Log vehicle exit in database"""
    exit_time = datetime.now()
    
    try:
        db = get_db()
        try:
            # Get the most recent entry that hasn't exited yet
            entry = db.execute('''
                SELECT id, entry_time
                FROM vehicle_logs 
                WHERE plate_number = ? 
                AND exit_time IS NULL
                ORDER BY entry_time DESC 
                LIMIT 1
            ''', (plate_number,)).fetchone()
            
            if not entry:
                print(f"[DB] No active entry found for {plate_number}")
                return False
                
            # For unauthorized exits, just log it
            if not is_authorized:
                db.execute('''
                    UPDATE vehicle_logs 
                    SET exit_time = ?,
                        is_unauthorized_exit = 1
                    WHERE id = ?
                ''', (exit_time, entry['id']))
                db.commit()
                print(f"[DB] Unauthorized exit logged for {plate_number}")
                return True
                
            # For authorized exits, just log it (payment already verified by is_payment_complete)
            db.execute('''
                UPDATE vehicle_logs 
                SET exit_time = ?,
                    is_unauthorized_exit = 0
                WHERE id = ?
            ''', (exit_time, entry['id']))
            db.commit()
            print(f"[DB] Authorized exit logged for {plate_number}")
            return True
                
        except Exception as e:
            print(f"[ERROR] Failed to log exit to database: {e}")
            db.rollback()
            return False
        finally:
            db.close()
            
    except Exception as e:
        print(f"[ERROR] Failed to log exit: {e}")
        return False

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

def is_payment_complete(plate_number):
    """
    Checks if payment has been completed for the most recent entry of a given plate number
    by reading directly from the CSV file.
    Returns True if the most recent entry is paid (status=1), False otherwise.
    """
    try:
        # Read the CSV file
        with open('plates_log.csv', 'r') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            
            # Get all entries for this plate
            entries = [row for row in reader if row[0] == plate_number]
            
            if not entries:
                print(f"[PAYMENT] No entries found for plate {plate_number}")
                return False
            
            # Get the most recent entry
            latest_entry = entries[-1]
            payment_status = int(latest_entry[1])  # Payment Status column
            
            if payment_status == 1:
                print(f"[PAYMENT] Most recent entry for {plate_number} is paid")
                return True
            else:
                print(f"[PAYMENT] Most recent entry for {plate_number} is NOT paid")
                return False
                
    except Exception as e:
        print(f"[ERROR] Failed to check payment status: {e}")
        return False

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

                                # Check payment status and control gate
                                if is_payment_complete(most_common):
                                    print(f"[ACCESS GRANTED] Payment complete for {most_common}")
                                    # Log authorized exit
                                    if log_vehicle_exit(most_common, is_authorized=True):
                                        if arduino:
                                            arduino.write(b'1')  # Open gate
                                            print("[GATE] Opening gate (sent '1')")
                                            time.sleep(15)
                                            arduino.write(b'0')  # Close gate
                                            print("[GATE] Closing gate (sent '0')")
                                    else:
                                        print("[ERROR] Failed to log exit, gate not opened")
                                else:
                                    print(f"[ACCESS DENIED] Payment NOT complete for {most_common}")
                                    # Log unauthorized exit attempt
                                    log_vehicle_exit(most_common, is_authorized=False)
                                    if arduino:
                                        arduino.write(b'2')  # Trigger warning buzzer
                                        print("[ALERT] Buzzer triggered (sent '2')")

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