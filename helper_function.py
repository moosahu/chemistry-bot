# -*- coding: utf-8 -*-
import logging
from telegram import Update, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext
from telegram.error import BadRequest, TelegramError

logger = logging.getLogger(__name__)

def safe_send_message(bot, chat_id, text, reply_markup=None, parse_mode=None):
    """Safely send a message, handling potential BadRequest errors."""
    try:
        return bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except BadRequest as e:
        logger.error(f"Error sending message to {chat_id}: {e}")
    except TelegramError as e:
        logger.error(f"Telegram error sending message to {chat_id}: {e}")
    return None

def safe_edit_message_text(query_or_update, text, reply_markup=None, parse_mode=None):
    """Safely edit message text, handling potential BadRequest errors."""
    message = None
    if isinstance(query_or_update, Update):
        if query_or_update.callback_query:
            message = query_or_update.callback_query.message
        elif query_or_update.message:
            # Cannot edit a user's message, this case might be invalid for editing
            logger.warning("Attempted to edit a standard message, which is not possible.")
            return None
    elif hasattr(query_or_update, 'message') and query_or_update.message: # Check if it's a CallbackQuery
        message = query_or_update.message

    if not message:
        logger.error("safe_edit_message_text: Could not find message to edit.")
        return None

    try:
        return message.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except BadRequest as e:
        # Common error: Message is not modified
        if "Message is not modified" in str(e):
            logger.warning(f"Message not modified: {e}")
            # Return the original message object if possible, or None
            return message
        else:
            logger.error(f"Error editing message {message.message_id} in chat {message.chat_id}: {e}")
    except TelegramError as e:
        logger.error(f"Telegram error editing message {message.message_id} in chat {message.chat_id}: {e}")
    return None

