# -*- coding: utf-8 -*-
"""Configuration settings and constants for the Chemistry Telegram Bot."""

import logging
import os
from telegram.ext import ConversationHandler

# --- Environment Variables --- 

# Load environment variables (consider using python-dotenv for local development)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") # Use TELEGRAM_BOT_TOKEN
DATABASE_URL = os.environ.get("DATABASE_URL")
API_BASE_URL = os.environ.get("API_BASE_URL", "http://your-api-base-url.com/api") # Provide a default or ensure it's set

# Validate essential variables
if not TELEGRAM_BOT_TOKEN: # Check the correct variable name
    raise ValueError("Missing required environment variable: TELEGRAM_BOT_TOKEN")
    raise ValueError("Missing required environment variable: BOT_TOKEN")
if not DATABASE_URL:
    # Allow running without DB for testing some features, but log a warning
    logging.warning("Missing environment variable: DATABASE_URL. Database features will be disabled.")
if not API_BASE_URL or API_BASE_URL == "http://your-api-base-url.com/api":
    # Allow running without API for testing some features, but log a warning
    logging.warning(f"Missing or default environment variable: API_BASE_URL ('{API_BASE_URL}'). API features might be disabled or use a dummy URL.")

# --- Logging Configuration --- 

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO # Set default level to INFO
)
# Set higher logging level for httpx to avoid verbose DEBUG messages
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) # Set bot's own logger to DEBUG for more details

logger.info("Logging configured.")
logger.debug(f"API_BASE_URL set to: {API_BASE_URL}")
logger.debug(f"DATABASE_URL is {'set' if DATABASE_URL else 'NOT set'}.")

# --- Conversation States --- 

# Define states as integers. Ensure they are unique.
MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, SELECT_QUIZ_SCOPE, ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, INFO_MENU, STATS_MENU = range(9)

# Fallback state
END = ConversationHandler.END

# --- Quiz Settings --- 

# Timer for each question in seconds. Set to 0 or False to disable.
ENABLE_QUESTION_TIMER = True
QUESTION_TIMER_SECONDS = 60 # e.g., 60 seconds per question

# Delay before showing feedback or next question (in seconds)
FEEDBACK_DELAY = 1.5

# Number of options per question (assuming multiple choice)
NUM_OPTIONS = 4

# --- API Settings --- 

API_TIMEOUT = 15 # Timeout in seconds for API requests

# --- Database Settings --- 

# Connection details are handled via DATABASE_URL

# --- Other Constants --- 

# Define any other constants needed across modules
LEADERBOARD_LIMIT = 10

logger.info("Configuration loaded.")

