"""
Parking Management System - Vehicle Entry Module
This module handles vehicle entry detection, license plate recognition, and gate control.
It uses YOLOv8 for license plate detection and Tesseract OCR for text recognition.
"""

import cv2
from ultralytics import YOLO
import os
import time
import serial
import serial.tools.list_ports
import csv
from collections import Counter
import pytesseract
import random
import sqlite3
from datetime import datetime

# Configure Tesseract OCR path
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Load YOLOv8 model for license plate detection
# model = YOLO(r'C:\Users\Admin\Desktop\Projects\parking-management-system\best.pt')
model = YOLO(r'./best.pt')

# Create directory for storing plate images
save_dir = 'plates'
os.makedirs(save_dir, exist_ok=True)

# Database and CSV files
DB_FILE = 'parking.db'
CSV_FILE = 'plates_log.csv'

def get_db():
    """Get database connection"""
    db = sqlite3.connect(DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    """Initialize database if it doesn't exist"""
    db = get_db()
    try:
        # Create vehicle_logs table if it doesn't exist
        db.execute('''
            CREATE TABLE IF NOT EXISTS vehicle_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate_number TEXT NOT NULL,
                entry_time TIMESTAMP NOT NULL,
                exit_time TIMESTAMP,
                payment_status INTEGER DEFAULT 0,
                payment_amount REAL,
                payment_time TIMESTAMP,
                is_unauthorized_exit INTEGER DEFAULT 0
            )
        ''')
        db.commit()
    except Exception as e:
        print(f"[ERROR] Failed to initialize database: {e}")
        db.rollback()
    finally:
        db.close()

# Initialize database
init_db()

# Initialize CSV file for logging
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Plate Number', 'Payment Status', 'Timestamp', 'Payment Timestamp'])

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

# Initialize video capture and variables
cap = cv2.VideoCapture(0)
plate_buffer = []
entry_cooldown = 300  # 5 minutes cooldown between entries
last_saved_plate = None
last_entry_time = 0

print("[SYSTEM] Ready. Press 'q' to exit.")

def log_vehicle_entry(plate_number):
    """Log vehicle entry in both CSV and database"""
    entry_time = datetime.now()
    entry_time_str = entry_time.strftime('%Y-%m-%d %H:%M:%S')
    
    try:
        # Log to CSV
        with open(CSV_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([plate_number, 0, entry_time_str, ''])
        print(f"[CSV] Entry logged for {plate_number}")
        
        # Log to database
        db = get_db()
        try:
            db.execute('''
                INSERT INTO vehicle_logs (
                    plate_number, entry_time, payment_status
                ) VALUES (?, ?, 0)
            ''', (plate_number, entry_time))
            db.commit()
            print(f"[DB] Entry logged for {plate_number}")
        except Exception as e:
            print(f"[ERROR] Failed to log entry to database: {e}")
            db.rollback()
        finally:
            db.close()
            
        return True
    except Exception as e:
        print(f"[ERROR] Failed to log entry: {e}")
        return False

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

                            # Save plate image
                            timestamp_str = time.strftime('%Y%m%d_%H%M%S')
                            image_filename = f"{plate_candidate}_{timestamp_str}.jpg"
                            save_path = os.path.join(save_dir, image_filename)
                            cv2.imwrite(save_path, plate_img)
                            print(f"[IMAGE SAVED] {save_path}")

                            # Process plate after multiple detections
                            if len(plate_buffer) >= 2:
                                most_common = Counter(plate_buffer).most_common(1)[0][0]
                                current_time = time.time()

                                # Check cooldown period
                                if (most_common != last_saved_plate or
                                    (current_time - last_entry_time) > entry_cooldown):
                                    # Log entry in both CSV and database
                                    if log_vehicle_entry(most_common):
                                        # Control gate if Arduino is connected
                                        if arduino:
                                            arduino.write(b'1')
                                            print("[GATE] Opening gate (sent '1')")
                                            time.sleep(15)
                                            arduino.write(b'0')
                                            print("[GATE] Closing gate (sent '0')")

                                        last_saved_plate = most_common
                                        last_entry_time = current_time
                                    else:
                                        print("[ERROR] Failed to log entry, gate not opened")
                                else:
                                    print("[SKIPPED] Duplicate within 5 min window.")
                                plate_buffer.clear()

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
