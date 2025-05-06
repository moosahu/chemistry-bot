# -*- coding: utf-8 -*-
"""Utility functions for the Chemistry Telegram Bot."""

import logging
import re # Moved import re to the top with other imports
import telegram # Added import telegram for error types
from telegram import Update # Already present
from telegram.ext import CallbackContext # Already present
# from telegram.error import BadRequest, TelegramError # These are now handled via telegram.error.BadRequest etc.

# Import logger from config, or define a local one if preferred
# Assuming logger is configured and imported from config.py as we discussed
from config import logger # Make sure this line is present and correct

# Original safe_send_message - seems okay but ensure bot object is passed correctly if used elsewhere
async def safe_send_message(bot, chat_id, text, reply_markup=None, parse_mode=None):
    """Safely send a message, handling potential Telegram errors."""
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except telegram.error.BadRequest as e: # Use telegram.error.BadRequest
        logger.error(f"BadRequest sending message to {chat_id}: {e}")
    except telegram.error.TelegramError as e: # Use telegram.error.TelegramError
        logger.error(f"TelegramError sending message to {chat_id}: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error sending message to {chat_id}: {e}")
    return None

# NEW and CORRECTED safe_edit_message_text function
async def safe_edit_message_text(
    bot,  # Should be an instance of telegram.Bot
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup=None, # Should be an instance of telegram.InlineKeyboardMarkup or None
    parse_mode: str = "HTML"
):
    """Safely edits a message text, handling potential errors."""
    try:
        # logger.debug(f"Attempting to edit message: chat_id={chat_id}, msg_id={message_id}, text='{text[:50]}...' markup={reply_markup}")
        await bot.edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        logger.debug(f"Message {message_id} in chat {chat_id} edited successfully.")
        return True
    except telegram.error.BadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.warning(f"Failed to edit message {message_id} in chat {chat_id} (not modified): {e}")
            pass # Often, not modifying is not a critical error, can be ignored silently
        elif "message can't be edited" in str(e).lower():
             logger.warning(f"Message {message_id} in chat {chat_id} cannot be edited (likely too old or deleted): {e}")
        else:
            logger.error(f"Failed to edit message {message_id} in chat {chat_id} (BadRequest): {e}")
    except telegram.error.TelegramError as e:
        logger.error(f"Failed to edit message {message_id} in chat {chat_id} (TelegramError): {e}")
    except Exception as e:
        logger.error(f"Unexpected error editing message {message_id} in chat {chat_id}: {e}", exc_info=True)
    return False

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

def process_text_with_chemical_notation(text):
    if not text:
        return text
    # Ensure subscript mapping is correct and handles all digits
    subscript_map = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
    text = re.sub(r'([A-Za-z])(\d+)', lambda m: m.group(1) + m.group(2).translate(subscript_map), text)
    text = text.replace(' -> ', ' → ')
    text = text.replace(' => ', ' ⇒ ')
    text = text.replace(' <-> ', ' ⇄ ')
    text = text.replace(' <=> ', ' ⇌ ')
    return text

def format_chemical_equation(equation):
    return process_text_with_chemical_notation(equation)

def format_duration(seconds: int) -> str:
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
    if seconds > 0 or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)

async def safe_delete_message(bot, chat_id: int, message_id: int) -> bool:
    """Safely delete a message, handling potential Telegram errors."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Successfully deleted message {message_id} from chat {chat_id}")
        return True
    except telegram.error.BadRequest as e: # Use telegram.error.BadRequest
        if "message to delete not found" in str(e).lower() or "message can't be deleted" in str(e).lower():
            logger.warning(f"Message {message_id} in chat {chat_id} not found or already deleted: {e}")
        else:
            logger.error(f"BadRequest deleting message {message_id} in chat {chat_id}: {e}")
    except telegram.error.TelegramError as e: # Use telegram.error.TelegramError
        logger.error(f"TelegramError deleting message {message_id} in chat {chat_id}: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error deleting message {message_id} in chat {chat_id}: {e}")
    return False

def get_quiz_type_string(type_display_name: str) -> str:
    """Returns the quiz type display string, possibly with minor formatting."""
    if not type_display_name:
        return "غير محدد"
    return str(type_display_name) # Returns the name as is, assuming it's already user-friendly

logger.info("utils/helpers.py loaded with corrected safe_edit_message_text.")

