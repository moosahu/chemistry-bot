
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
            logger.warning(f"Failed to edit message text (potential Markdown error?): {e}")
            # Optionally, try sending a new message as fallback if edit fails for other reasons
            # try:
            #     query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            # except Exception as send_e:
            #     logger.error(f"Failed to send new message after edit failed: {send_e}")
    except Exception as e:
        logger.error(f"Unexpected error editing message text: {e}")


