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
        logger.error(f"BadRequest sending message to {chat_id}: {e}")
    except TelegramError as e:
        logger.error(f"TelegramError sending message to {chat_id}: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error sending message to {chat_id}: {e}")
    return None

def safe_edit_message_text(query_or_bot, text, chat_id=None, message_id=None, reply_markup=None, parse_mode=None):
    """Safely edit message text, handling potential Telegram errors."""
    try:
        if hasattr(query_or_bot, 'message') and query_or_bot.message:
            if query_or_bot.message.text == text and query_or_bot.message.reply_markup == reply_markup:
                logger.debug(f"Message {query_or_bot.message.message_id} text and markup unchanged, skipping edit.")
                return query_or_bot.message
            return query_or_bot.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        elif chat_id and message_id:
            bot = query_or_bot
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
        if "Message is not modified" in str(e):
            logger.warning(f"Message not modified: {e}")
            if hasattr(query_or_bot, 'message') and query_or_bot.message:
                return query_or_bot.message
            return None
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

import re

def process_text_with_chemical_notation(text):
    if not text:
        return text
    text = re.sub(r'([A-Za-z])(\d+)', lambda m: m.group(1) + ''.join(['₀₁₂₃₄₅₆₇₈₉'[int(d)] for d in m.group(2)]), text)
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
    except BadRequest as e:
        if "message to delete not found" in str(e) or "message can't be deleted" in str(e):
            logger.warning(f"Message {message_id} in chat {chat_id} not found or already deleted: {e}")
        else:
            logger.error(f"BadRequest deleting message {message_id} in chat {chat_id}: {e}")
    except TelegramError as e:
        logger.error(f"TelegramError deleting message {message_id} in chat {chat_id}: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error deleting message {message_id} in chat {chat_id}: {e}")
    return False
# -*- coding: utf-8 -*-
# Add this function to your utils/helpers.py file
# Make sure other functions like safe_send_message, format_duration etc. are also present

def get_quiz_type_string(type_display_name: str) -> str:
    """Returns the quiz type display string, possibly with minor formatting."""
    if not type_display_name:
        return "غير محدد"
    return str(type_display_name) # Returns the name as is, assuming it's already user-friendly

# ... (ensure other helper functions like safe_send_message, safe_edit_message_text, safe_delete_message, remove_job_if_exists, format_duration are also in this file) ...
