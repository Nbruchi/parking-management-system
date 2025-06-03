"""
Parking Management System - Payment Processing Module
This module handles payment processing for vehicles exiting the parking system.
It communicates with Arduino to read and write RFID cards, and process payments.
"""

import csv
import serial
import time
import serial.tools.list_ports
import platform
from datetime import datetime
import threading
import sqlite3
import os

# Configuration
CSV_FILE = 'plates_log.csv'
DB_FILE = 'parking.db'
RATE_PER_HOUR = 500  # Amount charged per hour (RWF)

class PaymentProcessor:
    def __init__(self):
        self.ser = None
        self.is_processing = False
        self.current_plate = None
        self.current_balance = None
        self.payment_thread = None
        self.original_entries = None  # For rollback

    def get_db(self):
        """Get database connection"""
        db = sqlite3.connect(DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES)
        db.row_factory = sqlite3.Row
        return db

    def connect_arduino(self):
        """Initialize Arduino connection"""
        port = self.detect_arduino_port()
        if not port:
            print("[ERROR] Arduino not found")
            return False

        try:
            self.ser = serial.Serial(port, 9600, timeout=1)
            print(f"[CONNECTED] Listening on {port}")
            time.sleep(2)  # Wait for Arduino to reset
            self.ser.reset_input_buffer()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to connect to Arduino: {e}")
            return False

    def detect_arduino_port(self):
        """Detects the Arduino port by checking available serial ports."""
        ports = list(serial.tools.list_ports.comports())
        system = platform.system()
        for port in ports:
            if system == "Linux":
                if "ttyUSB" in port.device or "ttyACM" in port.device:
                    return port.device
            elif system == "Darwin":
                if "usbmodem" in port.device or "usbserial" in port.device:
                    return port.device
            elif system == "Windows":
                if "COM6" in port.device:
                    return port.device
        return None

    def read_rfid_card(self):
        """Read RFID card data from Arduino using payment.ino protocol"""
        if not self.ser:
            print("[ERROR] Arduino not connected")
            return None, None

        try:
            # Clear any existing data
            self.ser.reset_input_buffer()
            
            # Wait for card data (plate,balance format)
            start_time = time.time()
            while time.time() - start_time < 5:  # 5 second timeout
                if self.ser.in_waiting:
                    line = self.ser.readline().decode().strip()
                    print(f"[DEBUG] Raw line: '{line}'")
                    
                    # Check for card data (plate,balance format)
                    if ',' in line and not line.startswith('['):
                        try:
                            # Split and clean the data
                            plate, balance = [x.strip() for x in line.split(',')]
                            # Remove any null characters or other non-printable characters
                            balance = ''.join(c for c in balance if c.isprintable())
                            balance = int(balance)
                            print(f"[DEBUG] Parsed card data - Plate: {plate}, Balance: {balance}")
                            
                            # Wait for READY signal
                            ready_time = time.time()
                            while time.time() - ready_time < 2:
                                if self.ser.in_waiting:
                                    ready_line = self.ser.readline().decode().strip()
                                    if ready_line == "READY":
                                        print("[DEBUG] Received READY signal")
                                        return plate, balance
                                time.sleep(0.01)
                            
                            print("[ERROR] No READY signal received")
                            return None, None
                            
                        except ValueError as e:
                            print(f"[ERROR] Invalid card data format: {e}")
                            print(f"[DEBUG] Failed to parse line: '{line}'")
                            continue
                
                time.sleep(0.01)
            
            print("[DEBUG] No card detected")
            return None, None
            
        except Exception as e:
            print(f"[ERROR] Failed to read card: {e}")
            return None, None

    def write_rfid_card(self, plate, new_balance):
        """Write updated balance to RFID card using payment.ino protocol"""
        try:
            print(f"[DEBUG] Sending new balance: {new_balance}")
            
            # Send new balance to Arduino
            self.ser.write(f"{new_balance}\n".encode())
            self.ser.flush()
            
            # Wait for response
            start_time = time.time()
            while time.time() - start_time < 5:  # 5 second timeout
                if self.ser.in_waiting:
                    response = self.ser.readline().decode().strip()
                    print(f"[DEBUG] Arduino response: {response}")
                    
                    if "[UPDATED]" in response:
                        print(f"[SUCCESS] Card updated successfully")
                        return True
                    elif "[ERROR]" in response or "[DENIED]" in response:
                        print(f"[ERROR] Arduino reported: {response}")
                        return False
                    elif "[TIMEOUT]" in response:
                        print("[ERROR] Arduino timed out")
                        return False
                
                time.sleep(0.01)
            
            print("[ERROR] Timeout waiting for Arduino response")
            return False
            
        except Exception as e:
            print(f"[ERROR] Failed to write to card: {e}")
            import traceback
            traceback.print_exc()
            return False

    def backup_csv_entries(self, entries):
        """Backup current CSV entries for potential rollback"""
        self.original_entries = entries.copy()

    def rollback_changes(self):
        """Rollback changes to CSV file"""
        if not self.original_entries:
            print("[ERROR] No backup available for rollback")
            return False

        try:
            with open(CSV_FILE, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerows(self.original_entries)
            print("[SUCCESS] Rolled back changes to CSV")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to rollback changes: {e}")
            return False

    def process_payment(self, plate, balance):
        """Process payment for a vehicle with transaction handling"""
        if self.is_processing:
            print("[ERROR] Already processing a payment")
            return

        print(f"[DEBUG] Starting payment process for plate: {plate}, balance: {balance}")
        self.is_processing = True
        self.original_entries = None  # Reset backup
        exit_time = datetime.now()  # Record exit time

        try:
            # Read existing entries from CSV
            with open(CSV_FILE, 'r') as f:
                rows = list(csv.reader(f))
                print(f"[DEBUG] Read {len(rows)} rows from CSV")

            if len(rows) < 2:  # Only header or empty file
                print("[ERROR] No entries found in log file")
                return

            # Backup current entries for rollback
            self.backup_csv_entries(rows)

            header = rows[0]
            expected_columns = len(header)
            print(f"[DEBUG] CSV header: {header}, expected columns: {expected_columns}")
            
            # Validate and clean entries
            valid_entries = []
            for i, row in enumerate(rows[1:], 1):  # Skip header
                if not row[0].strip():
                    continue
                    
                if len(row) < expected_columns:
                    row.extend([''] * (expected_columns - len(row)))
                elif len(row) > expected_columns:
                    row = row[:expected_columns]
                
                valid_entries.append(row)

            found = False
            total_amount_due = 0
            entries_to_update = []

            # Find all unpaid entries for the plate
            for i, row in enumerate(valid_entries):
                if row[0] == plate and row[1] == '0':
                    found = True
                    try:
                        entry_time_str = row[2]
                        entry_time = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
                        
                        # Calculate hours spent (round up to nearest hour)
                        hours_spent = (exit_time - entry_time).total_seconds() / 3600
                        hours_spent = int(hours_spent) + (1 if (hours_spent % 1) > 0 else 0)
                        
                        # Calculate amount due for this entry
                        amount_due = hours_spent * RATE_PER_HOUR
                        total_amount_due += amount_due
                        entries_to_update.append((i, amount_due, hours_spent, entry_time))
                        print(f"[DEBUG] Entry {i+1} calculation: {hours_spent} hours = {amount_due} RWF")
                    except ValueError as e:
                        print(f"[ERROR] Invalid timestamp format in entry {i+1}: {e}")
                        continue

            if not found:
                print(f"[DEBUG] No unpaid entries found for plate {plate}")
                return

            print(f"[DEBUG] Found {len(entries_to_update)} unpaid entries")
            print(f"[DEBUG] Total amount due: {total_amount_due} RWF")
            print(f"[DEBUG] Current balance: {balance} RWF")

            # Check if balance is sufficient
            if balance < total_amount_due:
                print(f"[PAYMENT] Insufficient balance. Required: {total_amount_due}, Available: {balance}")
                # Send 'I' to Arduino to indicate insufficient balance
                self.ser.write(b'I\n')
                return

            # Calculate new balance
            new_balance = balance - total_amount_due
            print(f"[DEBUG] Calculating new balance: {balance} - {total_amount_due} = {new_balance}")

            # Step 1: Update card balance
            print("\n[PAYMENT] Updating card balance...")
            if not self.write_rfid_card(plate, new_balance):
                print("[ERROR] Failed to update card balance")
                return

            # Step 2: Update CSV entries and database
            try:
                # Update CSV entries
                for i, amount, hours, entry_time in entries_to_update:
                    valid_entries[i][1] = '1'  # Mark as paid
                    valid_entries[i][3] = exit_time.strftime('%Y-%m-%d %H:%M:%S')  # Payment timestamp
                    print(f"[DEBUG] Updated entry {i+1}: {valid_entries[i]}")
                
                # Write back all valid entries
                with open(CSV_FILE, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(header)
                    writer.writerows(valid_entries)

                # Update database
                db = self.get_db()
                try:
                    for i, amount, hours, entry_time in entries_to_update:
                        # Update vehicle_logs table
                        db.execute('''
                            UPDATE vehicle_logs 
                            SET payment_status = 1,
                                payment_time = ?,
                                exit_time = ?,
                                payment_amount = ?
                            WHERE plate_number = ? 
                            AND entry_time = ?
                        ''', (
                            exit_time,
                            exit_time,
                            amount,
                            plate,
                            entry_time
                        ))
                    db.commit()
                    print("[DEBUG] Database updated successfully")
                except Exception as e:
                    print(f"[ERROR] Failed to update database: {e}")
                    db.rollback()
                finally:
                    db.close()
                
                print("[PAYMENT] All entries processed successfully")
                print(f"[PAYMENT] New balance: {new_balance} RWF")
                
            except Exception as e:
                print(f"[ERROR] Failed to update records: {e}")
                # Attempt to rollback card balance
                print("[PAYMENT] Attempting to rollback card balance...")
                if self.write_rfid_card(plate, balance):
                    print("[SUCCESS] Card balance rolled back")
                else:
                    print("[ERROR] Failed to rollback card balance")
                # Rollback CSV changes
                self.rollback_changes()
                return

        except Exception as e:
            print(f"[ERROR] Payment processing failed: {e}")
            import traceback
            traceback.print_exc()
            # Attempt rollback if we have backup
            if self.original_entries:
                self.rollback_changes()
        finally:
            self.is_processing = False
            self.original_entries = None  # Clear backup

    def run(self):
        """Main loop to process payments"""
        if not self.connect_arduino():
            return

        print("[SYSTEM] Payment system ready. Place card near reader to process payment...")
        try:
            while True:
                # Wait for card to be placed near reader
                plate, balance = self.read_rfid_card()
                
                if plate and balance is not None:
                    print(f"[PAYMENT] Processing payment for plate: {plate}")
                    # Process payment in a separate thread to avoid blocking
                    self.payment_thread = threading.Thread(
                        target=self.process_payment,
                        args=(plate, balance)
                    )
                    self.payment_thread.start()
                    # Wait for payment processing to complete
                    self.payment_thread.join()
                    print("[SYSTEM] Ready for next card...")
                
                time.sleep(0.1)  # Small delay to prevent CPU overuse

        except KeyboardInterrupt:
            print("\n[EXIT] Program terminated by user")
        except Exception as e:
            print(f"[ERROR] {e}")
        finally:
            if self.ser:
                self.ser.close()

if __name__ == "__main__":
    processor = PaymentProcessor()
    processor.run()