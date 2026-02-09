"""Utility functions for the Chemistry Telegram Bot."""

import logging
import re
import telegram
from telegram import Update, InlineKeyboardMarkup, Bot
from telegram.ext import CallbackContext

from config import logger

async def safe_send_message(bot: Bot, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup = None, parse_mode: str = None):
    """Safely send a message, handling potential Telegram errors."""
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except telegram.error.BadRequest as e:
        logger.error(f"BadRequest sending message to {chat_id}: {e}")
    except telegram.error.TelegramError as e:
        logger.error(f"TelegramError sending message to {chat_id}: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error sending message to {chat_id}: {e}")
    return None

async def safe_edit_message_text(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup = None,
    parse_mode: str = "HTML"
) -> bool | str:
    """Safely edits a message text, handling potential errors.
    Returns True if successful.
    Returns "NO_TEXT_IN_MESSAGE" if edit failed due to no text in the original message.
    Returns False for other errors.
    """
    try:
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
            return False
        elif "message can't be edited" in str(e).lower():
             logger.warning(f"Message {message_id} in chat {chat_id} cannot be edited (likely too old or deleted): {e}")
             return False
        elif "there is no text in the message to edit" in str(e).lower():
            logger.warning(f"Failed to edit message {message_id} in chat {chat_id}: There is no text in the message to edit. Error: {e}")
            return "NO_TEXT_IN_MESSAGE"
        else:
            logger.error(f"Failed to edit message {message_id} in chat {chat_id} (BadRequest): {e}")
            return False
    except telegram.error.TelegramError as e:
        logger.error(f"Failed to edit message {message_id} in chat {chat_id} (TelegramError): {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error editing message {message_id} in chat {chat_id}: {e}", exc_info=True)
        return False

async def safe_edit_message_caption(bot: Bot, chat_id: int, message_id: int, caption: str, reply_markup: InlineKeyboardMarkup = None, parse_mode: str = None):
    """
    Safely edits the caption of a message.
    Returns True if successful, False otherwise.
    """
    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        logger.debug(f"Caption of message {message_id} in chat {chat_id} edited successfully.")
        return True
    except telegram.error.BadRequest as e:
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit caption of message {message_id} in chat {chat_id}, but it was not modified. Error: {e}")
        elif "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower():
            logger.warning(f"Failed to edit caption of message {message_id} in chat {chat_id}: Message not found or can't be edited. Error: {e}")
        elif "there is no caption in the message to edit" in str(e).lower() or "message doesn't have a caption" in str(e).lower():
             logger.warning(f"Failed to edit caption of message {message_id} in chat {chat_id}: No caption to edit. Error: {e}")
        else:
            logger.error(f"Failed to edit caption of message {message_id} in chat {chat_id} due to BadRequest: {e}")
    except telegram.error.Forbidden as e:
        logger.error(f"Failed to edit caption of message {message_id} in chat {chat_id} due to Forbidden: Bot was blocked or lacks permissions. Error: {e}")
    except telegram.error.TelegramError as e:
        logger.error(f"Failed to edit caption of message {message_id} in chat {chat_id} due to TelegramError: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while editing caption of message {message_id} in chat {chat_id}: {e}", exc_info=True)
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
    subscript_map = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
    text = re.sub(r'([A-Za-z])(\d+)', lambda m: m.group(1) + m.group(2).translate(subscript_map), text)
    text = text.replace(" -> ", " → ")
    text = text.replace(" => ", " ⇒ ")
    text = text.replace(" <-> ", " ⇄ ")
    text = text.replace(" <=> ", " ⇌ ")
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

async def safe_delete_message(bot: Bot, chat_id: int, message_id: int) -> bool:
    """Safely delete a message, handling potential Telegram errors."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Successfully deleted message {message_id} from chat {chat_id}")
        return True
    except telegram.error.BadRequest as e:
        if "message to delete not found" in str(e).lower() or "message can't be deleted" in str(e).lower():
            logger.warning(f"Message {message_id} in chat {chat_id} not found or already deleted: {e}")
        else:
            logger.error(f"BadRequest deleting message {message_id} in chat {chat_id}: {e}")
    except telegram.error.TelegramError as e:
        logger.error(f"TelegramError deleting message {message_id} in chat {chat_id}: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error deleting message {message_id} in chat {chat_id}: {e}")
    return False

def get_quiz_type_string(type_display_name: str) -> str:
    """Returns the quiz type display string, possibly with minor formatting."""
    if not type_display_name:
        return "غير محدد"
    return str(type_display_name)

logger.info("utils/helpers.py loaded with corrected safe_edit_message_text and added safe_edit_message_caption.")

