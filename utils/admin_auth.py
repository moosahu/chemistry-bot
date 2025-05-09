# utils/admin_auth.py
import logging
from telegram import Update

# Module-level logger for admin_auth.py messages
module_logger = logging.getLogger(__name__)

class _AdminAuthDummyDBManager:
    """Internal dummy DB manager for admin authentication fallback."""
    def is_user_admin(self, user_id: int) -> bool:
        module_logger.error(f"[AdminAuth-Dummy] Real DB_MANAGER not loaded or failed. Denying admin for user {user_id}.")
        return False

# Attempt to import the real DB_MANAGER and its logger
DB_MANAGER = None
real_db_manager_imported = False

try:
    from database.manager import DB_MANAGER as real_DB_MANAGER
    # If the real DB_MANAGER is imported, we use it.
    # We assume real_DB_MANAGER has its own configured logger for its internal messages.
    DB_MANAGER = real_DB_MANAGER
    real_db_manager_imported = True
    module_logger.info("[AdminAuth] Successfully imported real DB_MANAGER from database.manager.")
except ImportError:
    module_logger.critical("[AdminAuth] CRITICAL: Failed to import real DB_MANAGER from database.manager. Using internal dummy fallback. Admin checks will FAIL.")
    DB_MANAGER = _AdminAuthDummyDBManager()
except Exception as e:
    module_logger.critical(f"[AdminAuth] CRITICAL: An unexpected error occurred while importing DB_MANAGER: {e}. Using internal dummy fallback.", exc_info=True)
    DB_MANAGER = _AdminAuthDummyDBManager()

if DB_MANAGER is None: # Should not happen if try/except is structured well, but as a safeguard
    module_logger.critical("[AdminAuth] CRITICAL: DB_MANAGER is still None after import attempts. Fallback to dummy was not assigned properly. THIS IS A BUG.")
    DB_MANAGER = _AdminAuthDummyDBManager()

def get_user_id_from_update_or_query(obj) -> int | None:
    """
    Extracts user_id from an Update object or a CallbackQuery object.
    """
    user_id = None
    if hasattr(obj, 'from_user') and obj.from_user:
        user_id = obj.from_user.id
    elif hasattr(obj, 'effective_user') and obj.effective_user:
        user_id = obj.effective_user.id
    elif hasattr(obj, 'message') and hasattr(obj.message, 'from_user') and obj.message.from_user:
         user_id = obj.message.from_user.id
    
    if user_id:
        module_logger.debug(f"[AdminAuth] Extracted user_id: {user_id} from object of type {type(obj)}")
    else:
        module_logger.warning(f"[AdminAuth] Could not extract user_id from object: {obj} of type {type(obj)}")
    return user_id

def is_admin(update_or_query) -> bool:
    """
    Checks if the user associated with the update or query is an admin.
    """
    user_id = get_user_id_from_update_or_query(update_or_query)

    if user_id is None:
        module_logger.error("[AdminAuth] CRITICAL: user_id is None after extraction. Denying admin access.")
        return False

    try:
        # DB_MANAGER is guaranteed to be an instance of either the real one or _AdminAuthDummyDBManager
        is_admin_flag = DB_MANAGER.is_user_admin(user_id)
        
        # Log the outcome. The dummy manager logs its own failure.
        # If the real one was used, log its finding.
        if real_db_manager_imported: # Check if the import was successful initially
             module_logger.info(f"[AdminAuth] Admin status for user {user_id} from DB: {is_admin_flag}")
        # If not real_db_manager_imported, the dummy has already logged.
        return is_admin_flag
    except AttributeError as e_attr:
        # This might occur if the real DB_MANAGER object is malformed or not what's expected.
        module_logger.critical(f"[AdminAuth] AttributeError: DB_MANAGER (real or dummy) is missing 'is_user_admin' method or not properly initialized for user {user_id}: {e_attr}", exc_info=True)
        return False
    except Exception as e_runtime:
        # Catch other potential runtime errors from the real DB_MANAGER.is_user_admin call
        module_logger.error(f"[AdminAuth] Runtime error during DB_MANAGER.is_user_admin call for user {user_id}: {e_runtime}", exc_info=True)
        return False

