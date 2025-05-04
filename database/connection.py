# -*- coding: utf-8 -*-
"""Handles database connection setup."""

import psycopg2
import logging
from urllib.parse import urlparse

# Import config variables
try:
    from config import DATABASE_URL, logger
except ImportError:
    # Fallback if config is not available
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error("Failed to import config. DATABASE_URL might be missing.")
    DATABASE_URL = None # Ensure it exists, even if None

def connect_db():
    """Connects to the PostgreSQL database using the DATABASE_URL from config."""
    if not DATABASE_URL:
        logger.error("[DB Connection] DATABASE_URL is not set. Cannot connect.")
        return None

    try:
        # Parse the database URL
        result = urlparse(DATABASE_URL)
        username = result.username
        password = result.password
        database = result.path[1:] # Remove leading slash
        hostname = result.hostname
        port = result.port

        # Establish connection
        conn = psycopg2.connect(
            database=database,
            user=username,
            password=password,
            host=hostname,
            port=port,
            sslmode="require" # Assuming Heroku-like environment requiring SSL
        )
        logger.info("[DB Connection] Database connection established successfully.")
        return conn
    except psycopg2.Error as e:
        logger.error(f"[DB Connection] Error connecting to database: {e}")
        # Log connection details (excluding password) for debugging
        logger.debug(f"[DB Connection] Attempted connection with: user={username}, db={database}, host={hostname}, port={port}, sslmode=require")
        return None
    except Exception as e:
        # Catch potential parsing errors if URL is invalid
        logger.error(f"[DB Connection] Error parsing database URL: {e}")
        return None

# Optional: Test connection if run directly
if __name__ == "__main__":
    logger.info("Attempting to connect to database directly...")
    connection = connect_db()
    if connection:
        logger.info("Direct connection successful!")
        connection.close()
        logger.info("Direct connection closed.")
    else:
        logger.error("Direct connection failed.")

