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

    # تعريف دوال مساعدة مؤقتة - تم تعديلها لتتوافق مع التوقيع المتوقع
    async def safe_send_message(bot, chat_id, text, reply_markup=None, parse_mode=None):
        try: 
            return await bot.send_message(
                chat_id=chat_id, 
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        except Exception as e:
            logger.error(f"Error in safe_send_message: {e}")
            try:
                return await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
            except Exception as e2:
                logger.error(f"Second error in safe_send_message: {e2}")
                return None
                
    async def safe_edit_message_text(bot, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        try:
            return await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        except Exception as e:
            logger.error(f"Error in safe_edit_message_text: {e}")
            try:
                return await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=reply_markup
                )
            except Exception as e2:
                logger.error(f"Second error in safe_edit_message_text: {e2}")
                return None
                
    # Dummy DB_MANAGER
    class DummyDBManager:
        def register_or_update_user(*args, **kwargs): 
            logger.warning("Dummy DB_MANAGER.register_or_update_user called")
            return True
        def is_user_admin(*args, **kwargs): 
            logger.warning("Dummy DB_MANAGER.is_user_admin called")
            return False
        def get_system_message(self, key):
            logger.warning(f"Dummy DB_MANAGER.get_system_message called with key: {key}")
            if key == "about_bot_message":
                return ("**حول بوت كيمياء تحصيلي**\n\n"
                        "يهدف هذا البوت إلى مساعدتك في الاستعداد لاختبار التحصيلي في مادة الكيمياء "
                        "من خلال توفير مجموعة متنوعة من الأسئلة التدريبية التي تغطي مختلف جوانب المقرر. "
                        "يمكنك اختيار اختبارات عشوائية شاملة أو اختبارات مخصصة لوحدات دراسية معينة.\n\n"
                        "نتمنى لك كل التوفيق في رحلتك التعليمية!\n\n"
                        "**تطوير:** فريق Manus (هذا نص افتراضي)")
            return None
            
    DB_MANAGER = DummyDBManager()

# تعريف ثوابت حالات التسجيل
REGISTRATION_NAME = 20

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

    # اعتبار المستخدم مسجلاً افتراضياً إذا كان لديه اسم في قاعدة البيانات
    is_registered = True
    
    # الحصول على مدير قاعدة البيانات من context
    db_manager = context.bot_data.get("DB_MANAGER", DB_MANAGER)
    
    # التحقق من حالة التسجيل باستخدام DB_MANAGER
    if db_manager:
        try:
            # محاولة الحصول على معلومات المستخدم من قاعدة البيانات
            user_info = None
            if hasattr(db_manager, 'get_user_info'):
                user_info = db_manager.get_user_info(user.id)
            
            # التحقق من وجود معلومات المستخدم
            if not user_info or not user_info.get('full_name'):
                # إذا لم يكن هناك معلومات أو لم يكن هناك اسم، نعتبر المستخدم غير مسجل
                is_registered = False
                logger.info(f"User {user.id} not registered (no user_info or full_name).")
            else:
                # تخزين معلومات المستخدم في context.user_data
                context.user_data['registration_data'] = user_info
                context.user_data['is_registered'] = True
                logger.info(f"User {user.id} is registered with name: {user_info.get('full_name')}")
        except Exception as e:
            logger.error(f"Error checking registration status with DB_MANAGER: {e}")
            # في حالة حدوث خطأ، نفترض أن المستخدم غير مسجل
            is_registered = False
    
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
    
    # تحديث معلومات المستخدم الأساسية في قاعدة البيانات - فقط للمستخدمين المسجلين
    if is_registered and db_manager:
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
        logger.warning("DB_MANAGER not available or user not registered, skipping user registration.")

    # عرض القائمة الرئيسية فقط للمستخدمين المسجلين
    if is_registered:
        # الحصول على اسم المستخدم من قاعدة البيانات إذا كان متاحاً
        user_name = user.first_name
        if context.user_data.get('registration_data', {}).get('full_name'):
            user_name = context.user_data['registration_data']['full_name']
        
        welcome_text = f"أهلاً بك يا {user_name} في بوت كيمياء تحصيلي! 👋\n\n" \
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
    else:
        # هذا الجزء لن يتم تنفيذه عادة لأن المستخدم غير المسجل سيتم توجيهه للتسجيل في الشرط السابق
        # ولكن نضيفه كإجراء احترازي
        logger.warning(f"User {user.id} not registered but somehow reached end of start_command. Redirecting to registration.")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ يجب عليك التسجيل أولاً لاستخدام البوت."
        )
        try:
            from handlers.registration import start_registration
            await start_registration(update, context)
            return REGISTRATION_NAME
        except ImportError:
            return END

async def main_menu_callback(update: Update, context: CallbackContext) -> int:
    """Handles callbacks from the main menu keyboard or returns to the main menu."""
    query = update.callback_query
    user = update.effective_user
    state_to_return = MAIN_MENU 
    
    # اعتبار المستخدم مسجلاً افتراضياً إذا كان لديه اسم في قاعدة البيانات
    is_registered = True
    
    # التحقق من حالة التسجيل المخزنة في context.user_data أولاً
    if context.user_data.get('is_registered', False):
        is_registered = True
    else:
        # إذا لم تكن حالة التسجيل موجودة في context.user_data، نتحقق من قاعدة البيانات
        db_manager = context.bot_data.get("DB_MANAGER")
        
        if db_manager and hasattr(db_manager, 'get_user_info'):
            try:
                user_info = db_manager.get_user_info(user.id)
                if not user_info or not user_info.get('full_name'):
                    # إذا لم يكن هناك معلومات أو لم يكن هناك اسم، نعتبر المستخدم غير مسجل
                    is_registered = False
                    logger.info(f"User {user.id} not registered (no user_info or full_name) in main_menu_callback.")
                else:
                    # تخزين معلومات المستخدم في context.user_data
                    context.user_data['registration_data'] = user_info
                    context.user_data['is_registered'] = True
                    logger.info(f"User {user.id} is registered with name: {user_info.get('full_name')} in main_menu_callback")
            except Exception as e:
                logger.error(f"Error checking registration status in main_menu_callback: {e}")
                # في حالة حدوث خطأ، نفترض أن المستخدم غير مسجل
                is_registered = False
    
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
            db_manager = context.bot_data.get("DB_MANAGER", DB_MANAGER)  # استخدام DB_MANAGER العالمي كقيمة افتراضية
            about_text_content = None
            
            if db_manager:
                try:
                    about_text_content = db_manager.get_system_message("about_bot_message")
                except Exception as e:
                    logger.error(f"Error getting about_bot_message from DB_MANAGER: {e}")
            
            if not about_text_content:
                logger.warning("Could not retrieve 'about_bot_message' from DB_MANAGER, using default.")
                about_text_content = ("**حول بوت كيمياء تحصيلي**\n\n"
                                  "يهدف هذا البوت إلى مساعدتك في الاستعداد لاختبار التحصيلي في مادة الكيمياء "
                                  "من خلال توفير مجموعة متنوعة من الأسئلة التدريبية التي تغطي مختلف جوانب المقرر. "
                                  "يمكنك اختيار اختبارات عشوائية شاملة أو اختبارات مخصصة لوحدات دراسية معينة.\n\n"
                                  "نتمنى لك كل التوفيق في رحلتك التعليمية!\n\n"
                                  "**تطوير:** فريق Manus (هذا نص افتراضي)")
            
            about_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 الرجوع إلى القائمة الرئيسية", callback_data="main_menu")]
            ])
            
            try:
                # محاولة تعديل الرسالة الحالية
                await safe_edit_message_text(
                    context.bot,
                    query.message.chat_id,
                    query.message.message_id,
                    text=about_text_content,
                    reply_markup=about_keyboard,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Error editing message for about_bot: {e}")
                # في حالة فشل تعديل الرسالة، نرسل رسالة جديدة
                await safe_send_message(
                    context.bot,
                    query.message.chat_id,
                    text=about_text_content,
                    reply_markup=about_keyboard,
                    parse_mode="Markdown"
                )
            
            return MAIN_MENU
        elif data == "main_menu":  # Return to main menu
            # الحصول على اسم المستخدم من قاعدة البيانات إذا كان متاحاً
            user_name = user.first_name
            if context.user_data.get('registration_data', {}).get('full_name'):
                user_name = context.user_data['registration_data']['full_name']
            
            welcome_text = f"أهلاً بك يا {user_name} في بوت كيمياء تحصيلي! 👋\n\n" \
                        "استخدم الأزرار أدناه لبدء اختبار أو استعراض المعلومات."
            
            keyboard = create_main_menu_keyboard(user.id)
            
            try:
                # محاولة تعديل الرسالة الحالية
                await safe_edit_message_text(
                    context.bot,
                    query.message.chat_id,
                    query.message.message_id,
                    text=welcome_text,
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"Error editing message for main_menu: {e}")
                # في حالة فشل تعديل الرسالة، نرسل رسالة جديدة
                await safe_send_message(
                    context.bot,
                    query.message.chat_id,
                    text=welcome_text,
                    reply_markup=keyboard
                )
            
            return MAIN_MENU
        else:
            logger.warning(f"Unknown main menu callback data: '{data}' in main_menu_callback")
    
    logger.debug(f"[DEBUG] main_menu_callback attempting to return state: {state_to_return}")
    return state_to_return

# إضافة alias للتوافق مع الكود القديم
start_handler = start_command
