# utils/admin_auth.py (Modified)

ADMIN_USER_ID = 6448526509 # As provided by the user

def is_admin_user_check(user_id: int) -> bool:
    """Helper function to check if a user ID is admin."""
    return user_id == ADMIN_USER_ID

def is_admin(func):
    """
    Decorator to check if the user issuing the command or callback is an admin.
    It expects to decorate async functions that take (update, context, *args, **kwargs).
    """
    async def wrapper(update, context, *args, **kwargs):
        user = update.effective_user
        if not user or not is_admin_user_check(user.id):
            message_text = "عذراً، هذا الأمر مخصص للأدمن فقط."
            if update.callback_query:
                # For callback queries, it's good to answer them to remove the loading state.
                await update.callback_query.answer(message_text, show_alert=True)
                # Optionally, you might want to edit the message to inform the user,
                # or simply return to prevent the original function from executing.
                # Example: await update.callback_query.edit_message_text(text=message_text)
            elif update.message:
                await update.message.reply_text(message_text)
            return  # Stop further execution of the decorated function
        return await func(update, context, *args, **kwargs)
    return wrapper

# The ADMIN_USER_ID (6448526509) is used by the is_admin_user_check function.
# The merged_admin_interface.py imports and uses the @is_admin decorator.

