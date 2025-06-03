# This file makes the dashboard directory a Python package
from .app import app
from .database import init_db, get_db, init_app

__all__ = ['app', 'init_db', 'get_db', 'init_app'] 