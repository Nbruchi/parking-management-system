from flask import Flask, render_template
from datetime import datetime
from .database import get_daily_stats, get_recent_logs

app = Flask(__name__)

@app.route('/')
def index():
    """Main dashboard page"""
    # Get today's stats and recent logs from database
    stats = get_daily_stats()
    logs = get_recent_logs(limit=10)
    
    # Convert Row objects to dicts for template
    logs = [dict(log) for log in logs]
    
    return render_template('index.html', logs=logs, stats=stats)

if __name__ == '__main__':
    app.run(debug=True) 