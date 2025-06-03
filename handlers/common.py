# -*- coding: utf-8 -*-
"""Common handlers like /start and main menu navigation (Corrected v6 - Persistent Admin Button)."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler

# Import necessary components from other modules
try:
    # Ensure REGISTRATION_NAME is imported if needed for redirection
    from config import logger, MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU, END, REGISTRATION_NAME 
    from utils.helpers import safe_send_message, safe_edit_message_text # Ensure these are async
    # Import the initialized DB_MANAGER instance if available globally, otherwise get from context
    try:
        from database.manager import DB_MANAGER
    except ImportError:
        DB_MANAGER = None # Will rely on context.bot_data
        logger.info("DB_MANAGER not imported globally in common.py, will use context.bot_data.")

except ImportError as e:
    # Fallback for potential import issues during development/restructuring
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing modules in handlers.common: {e}. Using placeholders.")
    # Define placeholders for constants and functions
    MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU, END, REGISTRATION_NAME = 0, 1, 7, 8, -1, 20 # Match config.py, added END and REGISTRATION_NAME
    async def safe_send_message(bot, chat_id, text, reply_markup=None, parse_mode=None):
        logger.error("Placeholder safe_send_message called!")
        try: await bot.send_message(chat_id=chat_id, text="Error: Bot function unavailable.")
        except: pass
    async def safe_edit_message_text(bot, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        logger.error("Placeholder safe_edit_message_text called with new signature!")
        try: await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="Error: Bot function unavailable.", reply_markup=reply_markup, parse_mode=parse_mode)
        except: pass
    # Dummy DB_MANAGER
    class DummyDBManager:
        def register_or_update_user(*args, **kwargs): logger.warning("Dummy DB_MANAGER.register_or_update_user called"); return True
        def is_user_admin(*args, **kwargs): logger.warning("Dummy DB_MANAGER.is_user_admin called"); return False
        def get_user_info(*args, **kwargs): logger.warning("Dummy DB_MANAGER.get_user_info called"); return None
        def get_system_message(*args, **kwargs): logger.warning("Dummy DB_MANAGER.get_system_message called"); return "Default Text"
    DB_MANAGER = DummyDBManager()

def create_main_menu_keyboard(user_id: int, db_manager) -> InlineKeyboardMarkup:
    """Creates the main menu keyboard, adding admin button if applicable."""
    keyboard = [
        [InlineKeyboardButton("🧠 بدء اختبار جديد", callback_data="start_quiz")],
        [InlineKeyboardButton("📚 معلومات كيميائية", callback_data="menu_info")],
        [InlineKeyboardButton("📊 إحصائياتي ولوحة الصدارة", callback_data="menu_stats")],
        [InlineKeyboardButton("👤 تعديل معلوماتي", callback_data="edit_my_info")],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data="about_bot")]
    ]
    
    # Add admin button if the user is an admin
    is_admin = False
    if db_manager and hasattr(db_manager, 'is_user_admin'):
        try:
            is_admin = db_manager.is_user_admin(user_id)
        except Exception as e:
            logger.error(f"Error checking admin status for user {user_id} in create_main_menu_keyboard: {e}")
            
    if is_admin:
        logger.info(f"User {user_id} is admin, adding admin panel button to main menu.")
        # Ensure the callback_data matches the handler in admin_new_tools.py
        keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم الأدمن", callback_data="admin_show_tools_menu")])
    else:
        logger.info(f"User {user_id} is not admin, standard main menu shown.")
        
    return InlineKeyboardMarkup(keyboard)

# دالة للتحقق من حالة التسجيل مباشرة من قاعدة البيانات
def check_user_registration_directly(user_id, db_manager):
    """التحقق من حالة تسجيل المستخدم مباشرة من قاعدة البيانات"""
    try:
        if not db_manager or not hasattr(db_manager, 'get_user_info'):
            logger.warning(f"DB_MANAGER not available or missing get_user_info method for user {user_id}")
            return False  # افتراض أن المستخدم غير مسجل في حالة عدم وجود DB_MANAGER
        
        user_info = db_manager.get_user_info(user_id)
        if not user_info:
            logger.info(f"User {user_id} not found in database")
            return False
            
        # التحقق من وجود جميع الحقول الأساسية
        full_name = user_info.get('full_name')
        email = user_info.get('email')
        phone = user_info.get('phone')
        grade = user_info.get('grade')
        
        # التحقق من أن جميع الحقول الأساسية موجودة وليست فارغة
        # Assuming validation functions are available or checks are sufficient here
        # Need is_valid_email, is_valid_phone if strict validation is required
        has_full_name = full_name not in [None, 'None', ''] and len(str(full_name).strip()) >= 3
        has_email = email not in [None, 'None', ''] # Basic check
        has_phone = phone not in [None, 'None', ''] # Basic check
        has_grade = grade not in [None, 'None', '']
        
        # اعتبار المستخدم مسجلاً فقط إذا كانت جميع الحقول الأساسية موجودة
        is_registered = all([has_full_name, has_email, has_phone, has_grade])
        
        logger.info(f"User {user_id} registration check: {is_registered}")
        # logger.info(f"Details: Name: {has_full_name} ({full_name}), Email: {has_email} ({email}), Phone: {has_phone} ({phone}), Grade: {has_grade} ({grade})")
        
        return is_registered
    except Exception as e:
        logger.error(f"Error checking registration status for user {user_id}: {e}")
        return False  # افتراض أن المستخدم غير مسجل في حالة حدوث خطأ

async def start_command(update: Update, context: CallbackContext) -> int:
    """Handle the /start command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id
    logger.info(f"Executing start_command for user {user_id}")

    # Get DB_MANAGER from context, fallback to global if needed (though context is preferred)
    db_manager = context.bot_data.get("DB_MANAGER", DB_MANAGER)
    if not db_manager:
        logger.error(f"DB_MANAGER is None in start_command for user {user_id}. Cannot proceed.")
        await safe_send_message(context.bot, chat_id, text="⚠️ حدث خطأ داخلي في البوت. يرجى المحاولة لاحقاً.")
        return END # Or ConversationHandler.END if used within one

    # Register or update user info in DB
    if hasattr(db_manager, 'register_or_update_user'):
        try:
            db_manager.register_or_update_user(
                user_id=user_id,
                first_name=user.first_name,
                last_name=user.last_name,
                username=user.username,
                language_code=user.language_code
            )
        except Exception as e:
            logger.error(f"Error registering/updating user {user_id} in start_command: {e}")
    else:
        logger.warning("DB_MANAGER does not have register_or_update_user method.")

    # Check registration status
    is_registered = False
    if context.user_data.get('is_registered', False):
        is_registered = True
        logger.info(f"User {user_id} registration status from context: True")
    else:
        is_registered = check_user_registration_directly(user_id, db_manager)
        logger.info(f"User {user_id} registration status from DB check: {is_registered}")
        if is_registered:
            context.user_data['is_registered'] = True

    # If not registered, redirect to registration
    if not is_registered:
        logger.info(f"User {user_id} not registered. Redirecting to registration from start_command.")
        try:
            # Import dynamically to avoid circular dependencies if possible
            from registration import start_registration, REGISTRATION_NAME
        except ImportError:
            try:
                from handlers.registration import start_registration, REGISTRATION_NAME
            except ImportError as e:
                logger.error(f"Critical: Cannot import start_registration for unregistered user {user_id}: {e}")
                await safe_send_message(context.bot, chat_id, text="⚠️ تعذر بدء عملية التسجيل. يرجى المحاولة مرة أخرى.")
                return END
        
        # Start the registration process
        return await start_registration(update, context)

    # If registered, show the main menu
    logger.info(f"User {user_id} is registered. Showing main menu.")
    welcome_text = f"أهلاً بك يا {user.first_name or 'مستخدمنا العزيز'} في بوت كيمياء تحصيلي! 👋\n\n" \
                   "استخدم الأزرار أدناه للتفاعل."
                   
    # Create the keyboard using the updated function that includes admin check
    keyboard = create_main_menu_keyboard(user_id, db_manager)
    
    # Clear any stale quiz data
    if "current_quiz_logic" in context.user_data:
        logger.info(f"Clearing existing current_quiz_logic for user {user_id} from /start command.")
        del context.user_data["current_quiz_logic"]
    if "quiz_instance_id" in context.user_data:
        del context.user_data["quiz_instance_id"]
        
    await safe_send_message(context.bot, chat_id, text=welcome_text, reply_markup=keyboard)
    # Since this is the main entry point, return the MAIN_MENU state
    # If this handler is *outside* a ConversationHandler, returning a state might not be necessary
    # However, if it can be reached *within* a conversation (e.g., user types /start mid-quiz), returning MAIN_MENU might be needed.
    # For safety and consistency with potential conversation flows, returning MAIN_MENU is reasonable.
    return MAIN_MENU

async def main_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles callbacks from the main menu keyboard or returns to the main menu."""
    query = update.callback_query
    user = update.effective_user
    user_id = user.id
    data = "main_menu" # Default if query is None (e.g., called directly)
    state_to_return = MAIN_MENU 
    
    logger.info(f"Executing main_menu_callback for user {user_id}")

    db_manager = context.bot_data.get("DB_MANAGER", DB_MANAGER)
    if not db_manager:
        logger.error(f"DB_MANAGER is None in main_menu_callback for user {user_id}. Cannot proceed reliably.")
        if query: await query.answer("⚠️ حدث خطأ داخلي.", show_alert=True)
        return END

    # Check registration status before processing callback
    is_registered = context.user_data.get('is_registered', False) or check_user_registration_directly(user_id, db_manager)
    if not is_registered:
        logger.info(f"User {user_id} not registered. Redirecting to registration from main_menu_callback.")
        if query: await query.answer("يجب عليك التسجيل أولاً.")
        try:
            from registration import start_registration, REGISTRATION_NAME
        except ImportError:
            try:
                from handlers.registration import start_registration, REGISTRATION_NAME
            except ImportError as e:
                logger.error(f"Critical: Cannot import start_registration for unregistered user {user_id} in main_menu_callback: {e}")
                if query: await safe_edit_message_text(context.bot, query.message.chat_id, query.message.message_id, text="⚠️ تعذر بدء عملية التسجيل.")
                return END
        # Start registration (needs await)
        # This might require returning the state from start_registration
        # For simplicity, we'll just send a message and end here, assuming start handles the state.
        await start_registration(update, context) # This should handle sending the first registration message
        return REGISTRATION_NAME # Return the state expected by the registration handler

    # Process the callback query if it exists
    if query:
        data = query.data
        await query.answer()
        logger.info(f"Main menu callback: User {user_id} chose '{data}'.") 

        # Handle specific main menu actions
        if data == "start_quiz":
            logger.debug(f"Callback 'start_quiz' received. Returning QUIZ_MENU state.")
            return QUIZ_MENU 
        elif data == "menu_info": 
            logger.debug(f"Callback 'menu_info' received. Returning INFO_MENU state.")
            return INFO_MENU
        elif data == "menu_stats": 
            logger.debug(f"Callback 'menu_stats' received. Returning STATS_MENU state.")
            return STATS_MENU
        elif data == "edit_my_info":
             logger.debug(f"Callback 'edit_my_info' received. Returning EDIT_USER_INFO_MENU state (expected by registration handler).")
             # This should be handled by the entry point of edit_info_conv_handler in registration.py
             # We just need to return a state that *doesn't* belong to the current handler if it's part of one.
             # If this handler is standalone, returning a specific state might trigger another handler.
             # Assuming edit_info_conv_handler has an entry point for 'edit_my_info'
             # Returning the state expected by that handler's entry point might be needed, or just END.
             # Let's assume the edit handler is triggered by the callback pattern directly.
             # So, we just need to ensure we don't interfere. Returning MAIN_MENU is safe.
             # However, the edit handler *needs* to be triggered. Let's assume the application adds it correctly.
             # We don't need to return a specific state here if the CallbackQueryHandler for edit_my_info is separate.
             pass # Let the dedicated handler for edit_my_info take over.
        elif data == "about_bot":
            logger.debug(f"Callback 'about_bot' received. Displaying about message.")
            about_text_content = "**حول بوت كيمياء تحصيلي**\n\nDefault about text." # Default
            if hasattr(db_manager, 'get_system_message'):
                try:
                    about_text_content = db_manager.get_system_message("about_bot_message") or about_text_content
                except Exception as e:
                    logger.error(f"Error getting 'about_bot_message': {e}")
            
            about_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 الرجوع إلى القائمة الرئيسية", callback_data="main_menu")]
            ])
            if query and query.message:
                await safe_edit_message_text(
                    bot=context.bot,
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id,
                    text=about_text_content,
                    reply_markup=about_keyboard,
                    parse_mode="Markdown"
                )
            state_to_return = MAIN_MENU # Stay in main menu state
        elif data == "main_menu": 
            logger.debug(f"Callback 'main_menu' received. Refreshing main menu.")
            state_to_return = MAIN_MENU
        # Add handling for admin button press if needed, though it should trigger its own handler
        elif data == "admin_show_tools_menu":
            logger.debug(f"Callback 'admin_show_tools_menu' received in main_menu_callback. This should be handled by admin_tools handler.")
            # We don't need to do anything here; the dedicated handler should catch this.
            pass
        else:
            logger.warning(f"Unknown main menu callback data: '{data}'")
            state_to_return = MAIN_MENU 

    # If returning to MAIN_MENU, refresh the display
    if state_to_return == MAIN_MENU:
        menu_text = "القائمة الرئيسية:"
        # Generate keyboard with potential admin button
        keyboard = create_main_menu_keyboard(user_id, db_manager)
        
        # Try editing the existing message, otherwise send a new one
        message_to_update = query.message if query else update.effective_message
        if message_to_update:
            try:
                await safe_edit_message_text(context.bot, message_to_update.chat_id, message_to_update.message_id, text=menu_text, reply_markup=keyboard)
            except Exception as e:
                logger.warning(f"Failed to edit message for main menu refresh ({e}), sending new message.")
                await safe_send_message(context.bot, user_id, text=menu_text, reply_markup=keyboard)
        else: # Fallback if no message context
             await safe_send_message(context.bot, user_id, text=menu_text, reply_markup=keyboard)

    logger.debug(f"main_menu_callback returning state: {state_to_return}")
    # Clean up quiz data if returning to main menu explicitly after a quiz
    if data == "main_menu" and context.user_data.get("current_quiz_logic"):
        logger.info(f"User {user_id} returning to main menu from quiz. Clearing quiz logic.")
        if "current_quiz_logic" in context.user_data: del context.user_data["current_quiz_logic"]
        if "quiz_instance_id" in context.user_data: del context.user_data["quiz_instance_id"]
        # Returning END might be necessary if this callback is part of a ConversationHandler
        # If it's a standalone handler, returning MAIN_MENU is fine.
        # Let's assume it might be called from within another conversation, so END is safer.
        return END 
        
    return state_to_return

# Function to clean up quiz session data - placeholder implementation
def cleanup_quiz_session_data(context, user_id, chat_id):
    """Clean up quiz session data."""
    logger.info(f"Cleaning up quiz session data for user {user_id}, chat {chat_id}")
    if "current_quiz_logic" in context.user_data:
        del context.user_data["current_quiz_logic"]
    if "quiz_instance_id" in context.user_data:
        del context.user_data["quiz_instance_id"]

# Define handlers
# start_handler should ideally be part of the registration ConversationHandler's entry points
# or handled carefully to check registration status before deciding the flow.
# For simplicity here, we assume it's a standalone handler.
start_handler = CommandHandler('start', start_command)

# Handler for navigating back to the main menu or handling 'about_bot'
# It should NOT handle 'admin_show_tools_menu' as that needs its own handler.
main_menu_nav_handler = CallbackQueryHandler(main_menu_callback, pattern='^(main_menu|about_bot)$')

# Note: Handlers for 'start_quiz', 'menu_info', 'menu_stats', 'edit_my_info', 'admin_show_tools_menu'
# should be defined in their respective modules (quiz, info, stats, registration, admin_tools)
# and added to the application dispatcher separately.

