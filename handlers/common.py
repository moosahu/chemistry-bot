# -*- coding: utf-8 -*-
"""Common handlers like /start and main menu navigation (Corrected v5 - Fixed safe_edit_message_text call)."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler

# Import necessary components from other modules
try:
    from config import logger, MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU, END # Added END
    from utils.helpers import safe_send_message, safe_edit_message_text # Ensure these are async
    from database.manager import DB_MANAGER # Import the initialized DB_MANAGER instance
except ImportError as e:
    # Fallback for potential import issues during development/restructuring
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing modules in handlers.common: {e}. Using placeholders.")
    # Define placeholders for constants and functions
    MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU, END = 0, 1, 7, 8, -1 # Match config.py, added END
    async def safe_send_message(bot, chat_id, text, reply_markup=None, parse_mode=None):
        logger.error("Placeholder safe_send_message called!")
        try: await bot.send_message(chat_id=chat_id, text="Error: Bot function unavailable.")
        except: pass
    async def safe_edit_message_text(bot, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        logger.error("Placeholder safe_edit_message_text called with new signature!")
        # This placeholder now matches the likely signature that caused the error
        try: await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="Error: Bot function unavailable.", reply_markup=reply_markup, parse_mode=parse_mode)
        except: pass
    # Dummy DB_MANAGER
    class DummyDBManager:
        def register_or_update_user(*args, **kwargs): logger.warning("Dummy DB_MANAGER.register_or_update_user called"); return True
        def is_user_admin(*args, **kwargs): logger.warning("Dummy DB_MANAGER.is_user_admin called"); return False
    DB_MANAGER = DummyDBManager()

def create_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Creates the main menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("🧠 بدء اختبار جديد", callback_data="start_quiz")],
        [InlineKeyboardButton("📚 معلومات كيميائية", callback_data="menu_info")],
        [InlineKeyboardButton("📊 إحصائياتي ولوحة الصدارة", callback_data="menu_stats")],
        [InlineKeyboardButton("👤 تعديل معلوماتي", callback_data="edit_my_info")],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data="about_bot")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: CallbackContext) -> int:
    """Handles the /start command. Registers user and shows the main menu."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    logger.info(f"User {user.id} ({user.username or user.first_name}) started the bot in chat {chat_id}.")

    # التحقق من حالة تسجيل المستخدم - تعديل منطق التحقق لجعله أكثر صرامة
    is_registered = False
    
    # الحصول على مدير قاعدة البيانات من context
    db_manager = context.bot_data.get("DB_MANAGER", DB_MANAGER)
    
    # التحقق من حالة التسجيل باستخدام DB_MANAGER
    if db_manager:
        try:
            # محاولة الحصول على معلومات المستخدم من قاعدة البيانات
            user_info = None
            if hasattr(db_manager, 'get_user_info'):
                user_info = db_manager.get_user_info(user.id)
            
            # التحقق من وجود معلومات المستخدم وأنه مسجل
            if user_info:
                # التحقق من أن جميع المعلومات الأساسية موجودة وصحيحة
                full_name = user_info.get('full_name')
                email = user_info.get('email')
                phone = user_info.get('phone')
                grade = user_info.get('grade')
                
                # التحقق من الاسم (موجود وطوله أكبر من 3 أحرف)
                has_full_name = full_name not in [None, 'None', ''] and len(str(full_name).strip()) >= 3
                
                # التحقق من البريد الإلكتروني (موجود)
                has_email = email not in [None, 'None', '']
                
                # التحقق من رقم الجوال (موجود)
                has_phone = phone not in [None, 'None', '']
                
                # التحقق من الصف الدراسي (موجود وليس فارغاً)
                has_grade = grade not in [None, 'None', ''] and len(str(grade).strip()) > 0
                
                # اعتبار المستخدم مسجلاً فقط إذا كانت جميع المعلومات الأساسية موجودة
                is_registered = all([has_full_name, has_email, has_phone, has_grade])
                
                logger.info(f"User {user.id} registration status: {is_registered}")
                logger.info(f"Details: Name: {has_full_name}, Email: {has_email}, Phone: {has_phone}, Grade: {has_grade}")
        except Exception as e:
            logger.error(f"Error checking registration status with DB_MANAGER: {e}")
            is_registered = False  # في حالة حدوث خطأ، نفترض أن المستخدم غير مسجل
    
    # إذا لم يكن المستخدم مسجلاً، توجيهه لإكمال التسجيل
    if not is_registered:
        logger.info(f"User {user.id} not registered. Redirecting to registration.")
        try:
            # محاولة استيراد وحدة التسجيل بطرق مختلفة
            try:
                from .registration import start_registration
            except ImportError:
                try:
                    from handlers.registration import start_registration
                except ImportError:
                    # محاولة استيراد مطلق
                    from registration import start_registration
            
            # توجيه المستخدم لإكمال التسجيل
            await start_registration(update, context)
            return REGISTRATION_NAME
        except ImportError as e:
            logger.error(f"Error importing start_registration: {e}")
            # حتى في حالة فشل الاستيراد، نرسل رسالة للمستخدم تطلب منه التسجيل
            await safe_send_message(
                context.bot,
                chat_id,
                text="⚠️ يجب عليك التسجيل أولاً لاستخدام البوت. يرجى استخدام الأمر /register للتسجيل."
            )
            return END
    
    # تحديث معلومات المستخدم الأساسية في قاعدة البيانات
    if db_manager:
        try:
            if hasattr(db_manager, 'register_or_update_user'):
                db_manager.register_or_update_user(
                    user_id=user.id,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    username=user.username,
                    language_code=user.language_code
                )
        except Exception as e:
            logger.error(f"Error updating user basic info: {e}")
    else:
        logger.warning("DB_MANAGER not available, skipping user registration.")

    welcome_text = f"أهلاً بك يا {user.first_name} في بوت كيمياء تحصيلي! 👋\n\n" \
                   "استخدم الأزرار أدناه لبدء اختبار أو استعراض المعلومات."
    db_m = context.bot_data.get("DB_MANAGER", DB_MANAGER) # Get from context or use global fallback
    keyboard = create_main_menu_keyboard(user.id)
    # Clear any existing quiz logic from user_data to ensure a fresh start
    if "current_quiz_logic" in context.user_data:
        logger.info(f"Clearing existing current_quiz_logic for user {user.id} from /start command.")
        del context.user_data["current_quiz_logic"]
    if "quiz_instance_id" in context.user_data:
        del context.user_data["quiz_instance_id"]
        
    await safe_send_message(context.bot, chat_id, text=welcome_text, reply_markup=keyboard)
    return MAIN_MENU

async def main_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles callbacks from the main menu keyboard or returns to the main menu."""
    query = update.callback_query
    user = update.effective_user
    state_to_return = MAIN_MENU 
    
    # التحقق من حالة تسجيل المستخدم قبل السماح بالوصول إلى أي ميزة
    is_registered = False
    db_manager = context.bot_data.get("DB_MANAGER")
    
    if db_manager and hasattr(db_manager, 'get_user_info'):
        try:
            user_info = db_manager.get_user_info(user.id)
            if user_info:
                # التحقق من أن جميع المعلومات الأساسية موجودة وصحيحة
                full_name = user_info.get('full_name')
                email = user_info.get('email')
                phone = user_info.get('phone')
                grade = user_info.get('grade')
                
                has_full_name = full_name not in [None, 'None', ''] and len(str(full_name).strip()) >= 3
                has_email = email not in [None, 'None', '']
                has_phone = phone not in [None, 'None', '']
                has_grade = grade not in [None, 'None', ''] and len(str(grade).strip()) > 0
                
                is_registered = all([has_full_name, has_email, has_phone, has_grade])
                logger.info(f"User {user.id} registration status in main_menu_callback: {is_registered}")
        except Exception as e:
            logger.error(f"Error checking registration status in main_menu_callback: {e}")
    
    # إذا لم يكن المستخدم مسجلاً، توجيهه لإكمال التسجيل
    if not is_registered and query:
        logger.info(f"User {user.id} not registered. Redirecting to registration from main_menu_callback.")
        try:
            # محاولة استيراد وحدة التسجيل بطرق مختلفة
            try:
                from .registration import start_registration
            except ImportError:
                try:
                    from handlers.registration import start_registration
                except ImportError:
                    from registration import start_registration
            
            # توجيه المستخدم لإكمال التسجيل
            await query.answer("يجب عليك التسجيل أولاً")
            await start_registration(update, context)
            return REGISTRATION_NAME
        except ImportError as e:
            logger.error(f"Error importing start_registration in main_menu_callback: {e}")
            await query.answer("يجب عليك التسجيل أولاً")
            await safe_send_message(
                context.bot,
                query.message.chat_id,
                text="⚠️ يجب عليك التسجيل أولاً لاستخدام البوت. يرجى استخدام الأمر /start للتسجيل."
            )
            return END

    if query:
        await query.answer()
        data = query.data
        logger.info(f"Main menu callback: User {user.id} chose 	'{data}'.") 

        if data == "start_quiz":
            logger.debug(f"Callback 'start_quiz' received in main_menu_callback. Transitioning to QUIZ_MENU state for quiz handler.")
            # This will be handled by the quiz ConversationHandler's entry point
            # Returning QUIZ_MENU which should be the entry state for quiz selection flow
            return QUIZ_MENU 
        elif data == "menu_info": 
            state_to_return = INFO_MENU
        elif data == "menu_stats": 
            state_to_return = STATS_MENU
        elif data == "about_bot":  # Handle new About Bot button
            db_manager = context.bot_data.get("DB_MANAGER")
            if db_manager:
                about_text_content = db_manager.get_system_message("about_bot_message")
                if not about_text_content:
                    logger.warning("Could not retrieve 'about_bot_message' from DB_MANAGER, using default.")
                    about_text_content = ("**حول بوت كيمياء تحصيلي**\n\n"
                                      "يهدف هذا البوت إلى مساعدتك في الاستعداد لاختبار التحصيلي في مادة الكيمياء "
                                      "من خلال توفير مجموعة متنوعة من الأسئلة التدريبية التي تغطي مختلف جوانب المقرر. "
                                      "يمكنك اختيار اختبارات عشوائية شاملة أو اختبارات مخصصة لوحدات دراسية معينة.\n\n"
                                      "نتمنى لك كل التوفيق في رحلتك التعليمية!\n\n"
                                      "**تطوير:** فريق Manus (هذا نص افتراضي)") # Default if not found
            else:
                logger.error("DB_MANAGER is None in common.py/main_menu_callback when trying to get 'about_bot_message'. Using hardcoded default.")
                about_text_content = ("**حول بوت كيمياء تحصيلي**\n\n"
                                  "يهدف هذا البوت إلى مساعدتك في الاستعداد لاختبار التحصيلي في مادة الكيمياء "
                                  "من خلال توفير مجموعة متنوعة من الأسئلة التدريبية التي تغطي مختلف جوانب المقرر. "
                                  "يمكنك اختيار اختبارات عشوائية شاملة أو اختبارات مخصصة لوحدات دراسية معينة.\n\n"
                                  "نتمنى لك كل التوفيق في رحلتك التعليمية!\n\n"
                                  "**تطوير:** فريق Manus (هذا نص افتراضي - DB_MANAGER غير متاح)")
            
            about_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 الرجوع إلى القائمة الرئيسية", callback_data="main_menu")]
            ])
            if query and query.message: # Ensure query.message is not None
                await safe_edit_message_text(
                    bot=context.bot,
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id,
                    text=about_text_content,
                    reply_markup=about_keyboard,
                    parse_mode="Markdown"
                )
            return MAIN_MENU # Stay in MAIN_MENU state, next interaction (back button) will be handled by this same callback
        elif data == "main_menu": 
            state_to_return = MAIN_MENU
        else:
            logger.warning(f"Unknown main menu callback data: '{data}' in main_menu_callback")
            state_to_return = MAIN_MENU 

    if state_to_return == MAIN_MENU:
        menu_text = "القائمة الرئيسية:"
        keyboard = create_main_menu_keyboard(user.id)
        if query and query.message: # Ensure query.message exists
            # *** CORRECTED THE CALL TO safe_edit_message_text ***
            await safe_edit_message_text(context.bot, query.message.chat_id, query.message.message_id, text=menu_text, reply_markup=keyboard)
        elif update.effective_chat: # Fallback for cases where query might not be available but we want to send a new menu
            await safe_send_message(context.bot, update.effective_chat.id, text=menu_text, reply_markup=keyboard)
        else:
            logger.error(f"Cannot send main menu for user {user.id}: no query.message and no update.effective_chat.")

    logger.debug(f"[DEBUG] main_menu_callback attempting to return state: {state_to_return}")
    # If the quiz ended and the user clicks "Main Menu" from the quiz results,
    # we need to ensure the conversation handler for the quiz is truly ended.
    if data == "main_menu" and context.user_data.get("current_quiz_logic"):
        logger.info(f"User {user.id} returning to main menu from quiz. Clearing quiz logic.")
        del context.user_data["current_quiz_logic"]
        if "quiz_instance_id" in context.user_data:
            del context.user_data["quiz_instance_id"]
        return END # Explicitly end any active conversation if 'main_menu' is chosen after a quiz
        
    return state_to_return

start_handler = CommandHandler('start', start_command)
# This handler will catch 'main_menu' from quiz results or other places
# It will also catch 'about_bot' now
main_menu_nav_handler = CallbackQueryHandler(main_menu_callback, pattern='^(main_menu|about_bot)$')

# It's assumed that quiz.py (or similar) will have its own ConversationHandler
# with an entry point for 'start_quiz', e.g.:
# CallbackQueryHandler(quiz_menu_entry, pattern='^start_quiz$')
# And that ConversationHandler will manage its own states, including QUIZ_MENU.

# The main_menu_callback here is primarily for navigating *to* the main menu
# or handling other main menu items not covered by other conversation handlers.


