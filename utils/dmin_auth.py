# utils/admin_auth.py
from telegram import Update
# Assuming DB_MANAGER is accessible, e.g., imported from database.manager
# This path might need adjustment based on actual project structure
# Ensure your project structure allows this import, e.g., if utils and database are sibling directories
# If manager.py is in `database` and admin_auth.py is in `utils` (both under the main project root),
# and your main bot script runs from the root, this might involve sys.path manipulation or relative imports if part of a package.
# For a typical structure where `bot.py` is at root, and `handlers`, `utils`, `database` are subdirectories:
# from database.manager import DB_MANAGER, logger

# Simplified import for now, assuming DB_MANAGER is correctly imported where this module is used
# or that the user will adjust the import path as needed.

try:
    # Attempt to import from a common location if your project structure supports it.
    # If admin_auth.py is in utils/ and manager.py is in database/, and both are submodules of a main package:
    # from ..database.manager import DB_MANAGER, logger 
    # For now, let's assume a direct import path or that it's handled by the user's environment
    from database.manager import DB_MANAGER, logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logger.critical("CRITICAL: Failed to import DB_MANAGER in admin_auth.py. Admin checks will FAIL. Ensure database.manager.DB_MANAGER is accessible.")
    # Fallback to a dummy that always denies admin, to prevent accidental access if import fails.
    class DummyDBManager:
        def is_user_admin(self, user_id: int) -> bool:
            logger.error(f"[AdminAuth-Dummy] DB_MANAGER not loaded. Denying admin for user {user_id}.")
            return False
    DB_MANAGER = DummyDBManager()

def get_user_id_from_update_or_query(obj) -> int | None:
    """
    Extracts user_id from an Update object or a CallbackQuery object.
    Handles cases where obj is Update (with effective_user or message.from_user) 
    or CallbackQuery (with from_user).
    """
    user_id = None
    if hasattr(obj, 'from_user') and obj.from_user: # Primarily for CallbackQuery
        user_id = obj.from_user.id
    elif hasattr(obj, 'effective_user') and obj.effective_user: # For Update object (covers most cases)
        user_id = obj.effective_user.id
    # The above elif should cover update.message.from_user if effective_user is present.
    # Adding a more specific check for update.message just in case, though usually redundant.
    elif hasattr(obj, 'message') and hasattr(obj.message, 'from_user') and obj.message.from_user:
         user_id = obj.message.from_user.id
    
    if user_id:
        logger.debug(f"[AdminAuth] Extracted user_id: {user_id} from object of type {type(obj)}")
    else:
        logger.warning(f"[AdminAuth] Could not extract user_id from object: {obj} of type {type(obj)}")
    return user_id

def is_admin(update_or_query) -> bool:
    """
    Checks if the user associated with the update or query is an admin.
    'update_or_query' can be an Update object (from CommandHandler) 
    or a CallbackQuery object (from CallbackQueryHandler).
    """
    user_id = get_user_id_from_update_or_query(update_or_query)

    if user_id is None:
        # This case should ideally not happen if Telegram objects are passed correctly.
        logger.error("[AdminAuth] CRITICAL: user_id is None after extraction attempt. Denying admin access.")
        return False

    # Ensure DB_MANAGER is not the dummy one if possible
    if isinstance(DB_MANAGER, DummyDBManager):
        logger.error("[AdminAuth] DB_MANAGER is a dummy instance. Admin check for user {user_id} will default to False.")
        return DB_MANAGER.is_user_admin(user_id) # Will be False
    
    try:
        is_admin_flag = DB_MANAGER.is_user_admin(user_id)
        logger.info(f"[AdminAuth] User {user_id} admin status from DB: {is_admin_flag}")
        return is_admin_flag
    except Exception as e:
        logger.error(f"[AdminAuth] Error during DB_MANAGER.is_user_admin call for user {user_id}: {e}", exc_info=True)
        return False # Fail safe: if any error occurs during DB check, deny admin access.

