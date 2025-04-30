# db_utils.py
import os
import psycopg2
from psycopg2.extras import RealDictCursor

def get_db_connection():
    """Returns a connection to the PostgreSQL database."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable not set.")
    
    conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
    return conn