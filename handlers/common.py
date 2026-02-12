# -*- coding: utf-8 -*-
"""Common handlers like /start and main menu navigation (Corrected v5 - Fixed safe_edit_message_text call)."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler

# Import necessary components from other modules
try:
    from config import logger, MAIN_MENU, QUIZ_MENU, INFO_MENU, STATS_MENU, END, REGISTRATION_NAME # Added END and REGISTRATION_NAME
    from utils.helpers import safe_send_message, safe_edit_message_text # Ensure these are async
    from database.manager import DB_MANAGER # Import the initialized DB_MANAGER instance
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
        # This placeholder now matches the likely signature that caused the error
        try: await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="Error: Bot function unavailable.", reply_markup=reply_markup, parse_mode=parse_mode)
        except: pass
    # Dummy DB_MANAGER
    class DummyDBManager:
        def register_or_update_user(*args, **kwargs): logger.warning("Dummy DB_MANAGER.register_or_update_user called"); return True
        def is_user_admin(*args, **kwargs): logger.warning("Dummy DB_MANAGER.is_user_admin called"); return False
        def get_user_info(*args, **kwargs): logger.warning("Dummy DB_MANAGER.get_user_info called"); return None
    DB_MANAGER = DummyDBManager()

def create_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Creates the main menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("🧠 بدء اختبار جديد", callback_data="start_quiz")],
        [InlineKeyboardButton("🎯 تقوية نقاط ضعفي", callback_data="start_weakness_quiz")],
        [InlineKeyboardButton("📚 استكمال الاختبار", callback_data="show_saved_quizzes")],
        [InlineKeyboardButton("📚 معلومات كيميائية", callback_data="menu_info")],
        [InlineKeyboardButton("📊 إحصائياتي ولوحة الصدارة", callback_data="menu_stats")],
        [InlineKeyboardButton("⏳ موعد التحصيلي", callback_data="exam_countdown")],
    ]
    
    # زر جدول المذاكرة — يظهر فقط إذا مفعّل
    try:
        try:
            from database.manager import get_bot_setting
        except ImportError:
            from manager import get_bot_setting
        if get_bot_setting('allow_study_schedule', 'off') == 'on':
            keyboard.append([InlineKeyboardButton("📅 جدول المذاكرة", callback_data="study_menu")])
    except Exception:
        pass
    
    keyboard += [
        [InlineKeyboardButton("👤 تعديل معلوماتي", callback_data="edit_my_info")],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data="about_bot")]
    ]
    
    # التحقق مما إذا كان المستخدم أدمن وإضافة زر لوحة تحكم الأدمن
    try:
        if DB_MANAGER and hasattr(DB_MANAGER, 'is_user_admin') and DB_MANAGER.is_user_admin(user_id):
            keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم الأدمن", callback_data="admin_show_tools_menu")])
            logger.info(f"Added admin panel button for admin user {user_id}")
    except Exception as e:
        logger.error(f"Error checking admin status for user {user_id}: {e}")
    
    return InlineKeyboardMarkup(keyboard)

# دالة للتحقق من حالة التسجيل مباشرة من قاعدة البيانات
def check_user_registration_directly(user_id, db_manager):
    """التحقق من حالة تسجيل المستخدم مباشرة من قاعدة البيانات"""
    try:
        if not db_manager or not hasattr(db_manager, 'get_user_info'):
            logger.warning(f"DB_MANAGER not available or missing get_user_info method for user {user_id}")
            return False  # افتراض أن المستخدم غير مسجل في حالة عدم وجود DB_MANAGER
        
        # التحقق من كون المستخدم أدمن — الأدمن دائماً يمر
        try:
            if hasattr(db_manager, 'is_user_admin') and db_manager.is_user_admin(user_id):
                return True
        except Exception:
            pass
        
        user_info = db_manager.get_user_info(user_id)
        if not user_info:
            logger.info(f"User {user_id} not found in database")
            return False
            
        # التحقق من وجود الاسم كحد أدنى (كافي لاستخدام القائمة)
        full_name = user_info.get('full_name')
        has_full_name = full_name not in [None, 'None', ''] and len(str(full_name).strip()) >= 3
        
        if not has_full_name:
            logger.info(f"User {user_id} has no valid name - not registered")
            return False
        
        # التحقق من باقي الحقول (للتسجيل الكامل)
        email = user_info.get('email')
        phone = user_info.get('phone')
        grade = user_info.get('grade')
        
        has_email = email not in [None, 'None', '']
        has_phone = phone not in [None, 'None', '']
        has_grade = grade not in [None, 'None', '']
        
        # المستخدم مسجل إذا عنده اسم + حقل واحد على الأقل
        is_registered = has_full_name and (has_email or has_phone or has_grade)
        
        if not is_registered:
            # حتى لو ما عنده غير الاسم، نعتبره مسجل مبدئياً
            is_registered = has_full_name
        
        logger.info(f"User {user_id} registration check: {is_registered}")
        
        return is_registered
    except Exception as e:
        logger.error(f"Error checking registration status for user {user_id}: {e}")
        return False  # افتراض أن المستخدم غير مسجل في حالة حدوث خطأ

async def start_command(update: Update, context: CallbackContext) -> int:
    """Handle the /start command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # التحقق من حالة تسجيل المستخدم
    is_registered = False
    
    # التحقق من حالة التسجيل المخزنة في context.user_data أولاً
    if context.user_data.get('is_registered', False):
        is_registered = True
    else:
        # التحقق من حالة التسجيل مباشرة من قاعدة البيانات
        db_manager = context.bot_data.get("DB_MANAGER", DB_MANAGER)
        is_registered = check_user_registration_directly(user.id, db_manager)
        
        # تخزين حالة التسجيل في context.user_data للاستخدام المستقبلي
        if is_registered:
            context.user_data['is_registered'] = True
    
    # إذا لم يكن المستخدم مسجلاً، توجيهه لإكمال التسجيل
    if not is_registered:
        logger.info(f"User {user.id} not registered. Redirecting to registration from start_command.")
        try:
            from .registration import start_registration
        except ImportError:
            try:
                from handlers.registration import start_registration
            except ImportError:
                try:
                    from registration import start_registration
                except ImportError as e:
                    logger.error(f"Error importing start_registration in start_command: {e}")
                    await safe_send_message(
                        context.bot,
                        chat_id,
                        text="⚠️ حدث خطأ في الوصول إلى صفحة التسجيل. يرجى المحاولة مرة أخرى لاحقاً."
                    )
                    return END
        
        # توجيه المستخدم لإكمال التسجيل
        await start_registration(update, context)
        return REGISTRATION_NAME  # توجيه المستخدم لإكمال التسجيل أولاً

    if DB_MANAGER:
        DB_MANAGER.register_or_update_user(
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            language_code=user.language_code
        )
    else:
        logger.warning("DB_MANAGER not available, skipping user registration.")

    # استخدام رسالة الترحيب
    welcome_text = "مرحباً بك في بوت الكيمياء التحصيلي! أنا هنا لمساعدتك في الاستعداد لاختباراتك. يمكنك البدء باختبار تجريبي أو اختيار وحدة معينة.\nتطوير الاستاذ حسين علي الموسى"
    db_m = context.bot_data.get("DB_MANAGER", DB_MANAGER) # Get from context or use global fallback
    # محاولة جلب رسالة الترحيب من قاعدة البيانات إذا كانت متوفرة
    if db_m and hasattr(db_m, 'get_system_message'):
        try:
            db_welcome = db_m.get_system_message("welcome_new_user")
            if db_welcome:
                welcome_text = db_welcome
        except Exception as e:
            logger.error(f"Error getting welcome message from DB: {e}")
    
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
    # تعريف المتغير data بشكل افتراضي لتجنب UnboundLocalError
    data = "main_menu"  # قيمة افتراضية
    
    query = update.callback_query
    user = update.effective_user
    state_to_return = MAIN_MENU 
    
    # التحقق من حالة تسجيل المستخدم قبل معالجة الاستدعاء
    is_registered = False
    
    # التحقق من حالة التسجيل المخزنة في context.user_data أولاً
    if context.user_data.get('is_registered', False):
        is_registered = True
    else:
        # التحقق من حالة التسجيل مباشرة من قاعدة البيانات
        db_manager = context.bot_data.get("DB_MANAGER", DB_MANAGER)
        is_registered = check_user_registration_directly(user.id, db_manager)
        
        # تخزين حالة التسجيل في context.user_data للاستخدام المستقبلي
        if is_registered:
            context.user_data['is_registered'] = True
    
    # إذا لم يكن المستخدم مسجلاً، توجيهه لإكمال التسجيل
    if not is_registered and query:
        logger.info(f"User {user.id} not registered. Redirecting to registration from main_menu_callback.")
        try:
            from .registration import start_registration
        except ImportError:
            try:
                from handlers.registration import start_registration
            except ImportError:
                try:
                    from registration import start_registration
                except ImportError as e:
                    logger.error(f"Error importing start_registration in main_menu_callback: {e}")
                    await query.answer("يجب عليك التسجيل أولاً")
                    await safe_send_message(
                        context.bot,
                        query.message.chat_id,
                        text="⚠️ يجب عليك التسجيل أولاً لاستخدام البوت. يرجى استخدام الأمر /start للتسجيل."
                    )
                    return END
        
        # توجيه المستخدم لإكمال التسجيل
        await query.answer("يجب عليك التسجيل أولاً")
        await start_registration(update, context)
        return REGISTRATION_NAME

    if query:
        # استخراج البيانات من callback_query
        data = query.data
        await query.answer()
        logger.info(f"Main menu callback: User {user.id} chose \t'{data}'.") 

        if data == "start_quiz":
            logger.debug(f"Callback 'start_quiz' received in main_menu_callback. Transitioning to QUIZ_MENU state for quiz handler.")
            # This will be handled by the quiz ConversationHandler's entry point
            # Returning QUIZ_MENU which should be the entry state for quiz selection flow
            return QUIZ_MENU
        elif data == "show_saved_quizzes":
            logger.debug(f"Callback 'show_saved_quizzes' received. Redirecting to saved quizzes menu.")
            # Import the handler from quiz.py
            try:
                from handlers.quiz import show_saved_quizzes_menu
            except ImportError:
                try:
                    from quiz import show_saved_quizzes_menu
                except ImportError as e:
                    logger.error(f"Error importing show_saved_quizzes_menu: {e}")
                    await query.answer("حدث خطأ في الوصول للاختبارات المحفوظة")
                    return MAIN_MENU
            return await show_saved_quizzes_menu(update, context)
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
        elif data == "main_menu" or data == "quiz_action_main_menu": 
            # معالجة زر القائمة الرئيسية من أي مكان (بما في ذلك قوائم الاختبارات)
            state_to_return = MAIN_MENU
        else:
            logger.warning(f"Unknown main menu callback data: '{data}' in main_menu_callback")
            state_to_return = MAIN_MENU 

    if state_to_return == MAIN_MENU:
        # استخدام رسالة الترحيب بدلاً من "القائمة الرئيسية:"
        menu_text = "مرحباً بك في بوت الكيمياء التحصيلي! أنا هنا لمساعدتك في الاستعداد لاختباراتك. يمكنك البدء باختبار تجريبي أو اختيار وحدة معينة.\nتطوير الاستاذ حسين علي الموسى"
        # محاولة جلب رسالة الترحيب من قاعدة البيانات إذا كانت متوفرة
        db_manager = context.bot_data.get("DB_MANAGER", DB_MANAGER)
        if db_manager and hasattr(db_manager, 'get_system_message'):
            try:
                db_welcome = db_manager.get_system_message("welcome_new_user")
                if db_welcome:
                    menu_text = db_welcome
            except Exception as e:
                logger.error(f"Error getting welcome message from DB: {e}")
        
        # إضافة عرض الـ Streak اليومي
        try:
            if db_manager and hasattr(db_manager, 'get_user_streak'):
                streak_data = db_manager.get_user_streak(user.id)
                current_streak = streak_data.get("current_streak", 0)
                if current_streak >= 2:
                    menu_text += f"\n\n🔥 سلسلة {current_streak} أيام متتالية! استمر!"
                elif current_streak == 1:
                    menu_text += f"\n\n🔥 يوم واحد نشط! كمّل باكر عشان تبني سلسلتك!"
        except Exception as e:
            logger.error(f"Error getting streak for user {user.id}: {e}")
        
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

# Function to clean up quiz session data - placeholder implementation
def cleanup_quiz_session_data(context, user_id, chat_id):
    """Clean up quiz session data."""
    logger.info(f"Cleaning up quiz session data for user {user_id}, chat {chat_id}")
    if "current_quiz_logic" in context.user_data:
        del context.user_data["current_quiz_logic"]
    if "quiz_instance_id" in context.user_data:
        del context.user_data["quiz_instance_id"]
    # Add any other cleanup needed
    logger.debug(f"Popped dynamic key: last_quiz_interaction_message_id_{user_id}")

start_handler = CommandHandler('start', start_command)
# This handler will catch 'main_menu' from quiz results or other places
# It will also catch 'about_bot' now
main_menu_nav_handler = CallbackQueryHandler(main_menu_callback, pattern='^(main_menu|about_bot)$')


# ============================================================
#  عرض العد التنازلي للتحصيلي (عداد رقمي)
# ============================================================
async def exam_countdown_callback(update: Update, context: CallbackContext) -> int:
    """عرض العد التنازلي لاختبار التحصيلي بعداد رقمي"""
    query = update.callback_query
    await query.answer()

    from datetime import datetime as dt

    try:
        from database.manager import get_exam_periods
    except ImportError:
        try:
            from manager import get_exam_periods
        except ImportError:
            logger.error("Cannot import get_exam_periods")
            await safe_edit_message_text(
                context.bot, query.message.chat_id, query.message.message_id,
                text="❌ خطأ في تحميل المواعيد",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]])
            )
            return MAIN_MENU

    periods = get_exam_periods()
    today = dt.now().date()

    # أرقام بارزة (Bold Math)
    def bold_num(n):
        bmap = {'0':'𝟬','1':'𝟭','2':'𝟮','3':'𝟯','4':'𝟰','5':'𝟱','6':'𝟲','7':'𝟳','8':'𝟴','9':'𝟵'}
        return ''.join(bmap.get(d, d) for d in str(n))

    def fmt_date(d):
        if not d: return "—"
        months = {1:'يناير',2:'فبراير',3:'مارس',4:'أبريل',5:'مايو',6:'يونيو',
                  7:'يوليو',8:'أغسطس',9:'سبتمبر',10:'أكتوبر',11:'نوفمبر',12:'ديسمبر'}
        if isinstance(d, str): d = dt.strptime(d, '%Y-%m-%d').date()
        greg = f"{d.day} {months.get(d.month, '')} {d.year}"
        # تحويل هجري
        try:
            from hijri_converter import Gregorian
            h = Gregorian(d.year, d.month, d.day).to_hijri()
            h_months = {1:'محرم',2:'صفر',3:'ربيع الأول',4:'ربيع الثاني',
                       5:'جمادى الأولى',6:'جمادى الآخرة',7:'رجب',8:'شعبان',
                       9:'رمضان',10:'شوال',11:'ذو القعدة',12:'ذو الحجة'}
            hijri = f"{h.day} {h_months.get(h.month, '')} {h.year}هـ"
            return f"{greg} ({hijri})"
        except Exception:
            return greg

    def to_date(d):
        if not d: return None
        if isinstance(d, str): return dt.strptime(d, '%Y-%m-%d').date()
        return d

    # فلترة — إخفاء المخفي فقط
    visible = [p for p in periods if p.get('status') != 'hidden']

    if not visible:
        text = (
            "⏳ موعد التحصيلي\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "📋 لم تُحدد المواعيد بعد\n"
            "ترقبوا الإعلان قريباً! 🔜"
        )
    else:
        text = "⏳ مواعيد اختبار التحصيلي\n"
        text += "━━━━━━━━━━━━━━━━━━\n"

        for p in visible:
            status = p.get('status', 'active')
            name = p.get('period_name', '')

            # فترة قريباً — بدون تفاصيل
            if status == 'upcoming':
                text += f"\n🔜 {name}\n"
                text += "   📋 المواعيد قريباً...\n"
                continue

            # === فترة مفعّلة ===
            exam_start = to_date(p.get('exam_start_date'))
            exam_end = to_date(p.get('exam_end_date'))

            text += f"\n📋 {name}\n"

            if exam_start and exam_end:
                text += f"📅 {fmt_date(exam_start)} — {fmt_date(exam_end)}\n"

                days_left = (exam_start - today).days

                if days_left > 0:
                    text += f"\n┌─────────────────┐\n"
                    text += f"│   ⏳ باقي  {bold_num(days_left)}  يوم   │\n"
                    text += f"└─────────────────┘\n"
                elif days_left == 0:
                    text += f"\n🔴  الاختبار اليوم!  🔴\n"
                elif days_left > -(exam_end - exam_start).days - 1:
                    text += f"\n🟢  الاختبار جاري الآن  🟢\n"
                else:
                    text += f"\n✅  انتهت هذه الفترة\n"

            # مواعيد التسجيل
            reg_boys = to_date(p.get('reg_boys_date'))
            reg_girls = to_date(p.get('reg_girls_date'))
            late_reg = to_date(p.get('late_reg_date'))
            last_reg = to_date(p.get('last_reg_date'))

            if any([reg_boys, reg_girls, late_reg, last_reg]):
                text += "\n📝 التسجيل:\n"

                if reg_boys:
                    days_to = (reg_boys - today).days
                    if days_to > 0:
                        text += f"  👦 البنين: {fmt_date(reg_boys)} (بعد {bold_num(days_to)} يوم)\n"
                    elif days_to == 0:
                        text += f"  👦 البنين: يبدأ اليوم! ✅\n"
                    else:
                        text += f"  👦 البنين: مفتوح ✅\n"

                if reg_girls:
                    days_to = (reg_girls - today).days
                    if days_to > 0:
                        text += f"  👧 البنات: {fmt_date(reg_girls)} (بعد {bold_num(days_to)} يوم)\n"
                    elif days_to == 0:
                        text += f"  👧 البنات: يبدأ اليوم! ✅\n"
                    else:
                        text += f"  👧 البنات: مفتوح ✅\n"

                if late_reg:
                    text += f"  ⚠️ متأخر: {fmt_date(late_reg)}\n"

                if last_reg:
                    days_close = (last_reg - today).days
                    if days_close > 0:
                        text += f"  🔒 يُغلق بعد: {bold_num(days_close)} يوم\n"
                    elif days_close == 0:
                        text += f"  🔴 آخر يوم للتسجيل!\n"
                    else:
                        text += f"  🔒 أُغلق التسجيل\n"

            notes = p.get('notes', '')
            if notes:
                text += f"\n💡 {notes}\n"

            text += "\n━━━━━━━━━━━━━━━━━━"

        text += "\n\n💪 كل يوم مراجعة يقرّبك من هدفك!"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data="exam_countdown")],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]
    ])

    await safe_edit_message_text(
        context.bot, query.message.chat_id, query.message.message_id,
        text=text, reply_markup=keyboard
    )
    return MAIN_MENU


exam_countdown_handler = CallbackQueryHandler(exam_countdown_callback, pattern='^exam_countdown$')

# It's assumed that quiz.py (or similar) will have its own ConversationHandler
