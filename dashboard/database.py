import sqlite3
import click
import csv
from datetime import datetime
from flask import current_app, g
from flask.cli import with_appcontext
import os

def calculate_payment_amount(entry_time, payment_time):
    """Calculate payment amount based on duration"""
    if not payment_time:
        return None
        
    # Calculate duration in hours
    duration = payment_time - entry_time
    hours = duration.total_seconds() / 3600
    
    # Round up to nearest hour
    hours = int(hours) + (1 if hours % 1 > 0 else 0)
    
    # Minimum 1 hour
    hours = max(1, hours)
    
    # Calculate amount (500 RWF per hour)
    return hours * 500.0

def get_db():
    """Get database connection"""
    if 'db' not in g:
        g.db = sqlite3.connect(
            'parking.db',
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    """Close database connection"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def sync_csv_to_db():
    """Sync data from plates_log.csv to the database, avoiding duplicates"""
    db = get_db()
    
    # Read CSV file
    csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'plates_log.csv')
    if not os.path.exists(csv_path):
        print(f"Warning: {csv_path} not found")
        return

    try:
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Parse timestamps
                entry_time = datetime.strptime(row['Timestamp'], '%Y-%m-%d %H:%M:%S')
                payment_time = datetime.strptime(row['Payment Timestamp'], '%Y-%m-%d %H:%M:%S') if row['Payment Timestamp'] else None
                
                # Calculate payment amount based on duration
                payment_amount = calculate_payment_amount(entry_time, payment_time) if payment_time else None
                
                # Check if entry already exists in database
                existing = db.execute('''
                    SELECT id, payment_status, payment_time 
                    FROM vehicle_logs 
                    WHERE plate_number = ? 
                    AND entry_time = ?
                ''', (row['Plate Number'], entry_time)).fetchone()
                
                if not existing:
                    # Insert new entry
                    db.execute('''
                        INSERT INTO vehicle_logs (
                            plate_number, entry_time, payment_status,
                            payment_time, payment_amount
                        ) VALUES (?, ?, ?, ?, ?)
                    ''', (
                        row['Plate Number'],
                        entry_time,
                        int(row['Payment Status']),
                        payment_time,
                        payment_amount
                    ))
                elif existing and int(row['Payment Status']) == 1 and existing['payment_status'] == 0:
                    # Update payment status if it changed in CSV
                    db.execute('''
                        UPDATE vehicle_logs 
                        SET payment_status = ?,
                            payment_time = ?,
                            payment_amount = ?
                        WHERE id = ?
                    ''', (
                        int(row['Payment Status']),
                        payment_time,
                        payment_amount,
                        existing['id']
                    ))
        
        db.commit()
        print("[DB] Successfully synced CSV to database")
        
    except Exception as e:
        print(f"[ERROR] Failed to sync CSV to database: {e}")
        db.rollback()

def init_db():
    """Initialize database with schema"""
    db = get_db()

    # Create vehicle_logs table
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

    # Create daily_stats table
    db.execute('''
        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE UNIQUE NOT NULL,
            total_entries INTEGER DEFAULT 0,
            total_exits INTEGER DEFAULT 0,
            total_revenue REAL DEFAULT 0,
            unauthorized_exits INTEGER DEFAULT 0
        )
    ''')

    db.commit()
    
    # Initial sync from CSV
    sync_csv_to_db()

def init_app(app):
    """Register database functions with Flask app"""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(sync_db_command)

@click.command('init-db')
@with_appcontext
def init_db_command():
    """Clear existing data and create new tables."""
    init_db()
    click.echo('Initialized the database.')

@click.command('sync-db')
@with_appcontext
def sync_db_command():
    """Sync database with plates_log.csv"""
    sync_csv_to_db()
    click.echo('Synced database with CSV file.')

def get_daily_stats(date=None):
    """Get statistics for a specific date (defaults to today)"""
    if date is None:
        date = datetime.now().date()
    
    db = get_db()
    
    # Get stats from daily_stats table
    stats = db.execute('''
        SELECT total_entries, total_exits, total_revenue, unauthorized_exits
        FROM daily_stats
        WHERE date = ?
    ''', (date,)).fetchone()
    
    if stats:
        return dict(stats)
    
    # If no stats exist for today, calculate from vehicle_logs
    stats = {
        'total_entries': 0,
        'total_exits': 0,
        'total_revenue': 0,
        'unauthorized_exits': 0
    }
    
    # Get entries and exits for the date
    logs = db.execute('''
        SELECT 
            COUNT(*) as total_entries,
            SUM(CASE WHEN exit_time IS NOT NULL THEN 1 ELSE 0 END) as total_exits,
            SUM(CASE WHEN payment_status = 1 THEN payment_amount ELSE 0 END) as total_revenue,
            SUM(CASE WHEN is_unauthorized_exit = 1 THEN 1 ELSE 0 END) as unauthorized_exits
        FROM vehicle_logs
        WHERE date(entry_time) = date(?)
    ''', (date,)).fetchone()
    
    if logs:
        stats.update(dict(logs))
    
    # Insert or update daily_stats
    db.execute('''
        INSERT INTO daily_stats (date, total_entries, total_exits, total_revenue, unauthorized_exits)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            total_entries = excluded.total_entries,
            total_exits = excluded.total_exits,
            total_revenue = excluded.total_revenue,
            unauthorized_exits = excluded.unauthorized_exits
    ''', (date, stats['total_entries'], stats['total_exits'], 
          stats['total_revenue'] or 0, stats['unauthorized_exits']))
    
    db.commit()
    return stats

def get_recent_logs(limit=10):
    """Get most recent vehicle logs"""
    db = get_db()
    return db.execute('''
        SELECT 
            plate_number,
            entry_time,
            exit_time,
            payment_status,
            payment_amount,
            payment_time,
            is_unauthorized_exit
        FROM vehicle_logs
        ORDER BY entry_time DESC
        LIMIT ?
    ''', (limit,)).fetchall() 