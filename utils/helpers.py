# -*- coding: utf-8 -*-
"""Utility functions for the Chemistry Telegram Bot."""

import logging
from telegram import Update
from telegram.ext import CallbackContext
from telegram.error import BadRequest, TelegramError

# Get logger instance
logger = logging.getLogger(__name__)

def safe_send_message(bot, chat_id, text, reply_markup=None, parse_mode=None):
    """Safely send a message, handling potential Telegram errors."""
    try:
        return bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except BadRequest as e:
        # Log specific BadRequest errors, e.g., chat not found, user blocked
        logger.error(f"BadRequest sending message to {chat_id}: {e}")
    except TelegramError as e:
        # Log other Telegram API errors
        logger.error(f"TelegramError sending message to {chat_id}: {e}")
    except Exception as e:
        # Log any other unexpected errors
        logger.exception(f"Unexpected error sending message to {chat_id}: {e}")
    return None

def safe_edit_message_text(query_or_bot, text, chat_id=None, message_id=None, reply_markup=None, parse_mode=None):
    """Safely edit message text, handling potential Telegram errors.

    Can be called with:
    - A CallbackQuery object (query_or_bot=query)
    - A Bot object and chat_id/message_id (query_or_bot=bot, chat_id=..., message_id=...)
    """
    try:
        if hasattr(query_or_bot, 'message') and query_or_bot.message: # It's a CallbackQuery
            # Check if the message text is actually different
            if query_or_bot.message.text == text and query_or_bot.message.reply_markup == reply_markup:
                logger.debug(f"Message {query_or_bot.message.message_id} text and markup unchanged, skipping edit.")
                return query_or_bot.message # Return the original message
            return query_or_bot.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        elif chat_id and message_id: # It's a Bot object
            bot = query_or_bot
            # Fetch the message first to check if modification is needed (optional, reduces API calls)
            # current_message = bot.get_message(chat_id=chat_id, message_id=message_id) # Needs get_message method
            # if current_message.text == text and current_message.reply_markup == reply_markup:
            #     logger.debug(f"Message {message_id} text and markup unchanged, skipping edit.")
            #     return current_message
            return bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        else:
            logger.error("safe_edit_message_text: Invalid arguments. Need CallbackQuery or Bot+chat_id+message_id.")
            return None
    except BadRequest as e:
        # Common error: Message is not modified
        if "Message is not modified" in str(e):
            logger.warning(f"Message not modified: {e}")
            # Return the original message object if possible
            if hasattr(query_or_bot, 'message') and query_or_bot.message:
                return query_or_bot.message
            return None # Cannot return original message if called with bot object
        elif "message can't be edited" in str(e):
             logger.warning(f"Message cannot be edited (likely too old or deleted): {e}")
        else:
            logger.error(f"BadRequest editing message: {e}")
    except TelegramError as e:
        logger.error(f"TelegramError editing message: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error editing message: {e}")
    return None

def remove_job_if_exists(name: str, context: CallbackContext) -> bool:
    """Remove job with given name. Returns whether job was removed."""
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        logger.debug(f"No job found with name: {name}")
        return False
    for job in current_jobs:
        job.schedule_removal()
        logger.info(f"Removed job with name: {name}")
    return True

# Note: create_main_menu_keyboard moved to handlers/common.py as it needs DB access (is_admin)




# --- Chemical Notation Formatting (from chemical_equations.py) ---

import re

def process_text_with_chemical_notation(text):
    """
    Process text to format chemical formulas and equations.
    Example: H2O -> H₂O, CO2 -> CO₂, -> -> →
    """
    if not text:
        return text
    
    # Subscripts for numbers following letters (e.g., H2O)
    text = re.sub(r'([A-Za-z])(\d+)', lambda m: m.group(1) + ''.join(['₀₁₂₃₄₅₆₇₈₉'[int(d)] for d in m.group(2)]), text)
    
    # Replace common reaction arrows
    text = text.replace(' -> ', ' → ')
    text = text.replace(' => ', ' ⇒ ')
    text = text.replace(' <-> ', ' ⇄ ')
    text = text.replace(' <=> ', ' ⇌ ')
    
    return text

def format_chemical_equation(equation):
    """Formats a chemical equation string using process_text_with_chemical_notation."""
    return process_text_with_chemical_notation(equation)




def format_duration(seconds: int) -> str:
    """Formats a duration in seconds into a human-readable string (e.g., 1h 30m 15s)."""
    if seconds < 0:
        return "0s"
    
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if seconds > 0 or not parts: # Always show seconds if it's the only unit or > 0
        parts.append(f"{seconds}s")
        
    return " ".join(parts)

