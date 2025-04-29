import logging
from telegram.error import BadRequest

logger = logging.getLogger(__name__) # Assuming logger is configured elsewhere or get root logger

def safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
    """Safely edits message text, handling 'Message is not modified' error."""
    try:
        query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info(f"Message not modified (likely duplicate button press): {e}")
        else:
            # Log other BadRequest errors as warnings
            logger.warning(f"BadRequest editing message text: {e}")
            # Optionally, notify user about the specific error if needed
            # query.message.reply_text(f"حدث خطأ أثناء تعديل الرسالة: {e}")
    except Exception as e:
        # Log other unexpected errors
        logger.error(f"Unexpected error editing message text: {e}")
        # Notify user about a generic error
        try:
            query.message.reply_text("حدث خطأ غير متوقع أثناء معالجة طلبك. تم إبلاغ المطورين.")
        except Exception as reply_e:
            logger.error(f"Failed to send error notification to user: {reply_e}")


