#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
منطق التسجيل الإلزامي للمستخدمين في بوت الاختبارات
يتضمن جمع الاسم، البريد الإلكتروني، رقم الجوال، والصف الدراسي
"""

import logging
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    Application
)

# تعريف الدوال المساعدة مباشرة في بداية الملف (خارج أي كتلة try/except)
async def safe_send_message(bot, chat_id, text, reply_markup=None, parse_mode=None):
    """إرسال رسالة بشكل آمن مع معالجة الأخطاء"""
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        logging.error(f"خطأ في إرسال الرسالة: {e}")
        try:
            # محاولة إرسال رسالة بدون تنسيق خاص
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup
            )
        except Exception as e2:
            logging.error(f"فشل محاولة إرسال الرسالة البديلة: {e2}")
            return None

async def safe_edit_message_text(bot, chat_id, message_id, text, reply_markup=None, parse_mode=None):
    """تعديل نص الرسالة بشكل آمن مع معالجة الأخطاء"""
    try:
        return await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        logging.error(f"خطأ في تعديل نص الرسالة: {e}")
        try:
            # محاولة تعديل الرسالة بدون تنسيق خاص
            return await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup
            )
        except Exception as e2:
            logging.error(f"فشل محاولة تعديل نص الرسالة البديلة: {e2}")
            return None

# إعداد التسجيل
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# دالة مساعدة لجلب رسالة الترحيب الموحدة
def get_unified_welcome_text(db_manager, user_first_name=None):
    welcome_message_key = "welcome_new_user"  # نفس المفتاح المستخدم في admin_new_tools.py
    # رسالة الترحيب الافتراضية المحددة من قبل المستخدم
    default_text = "مرحباً بك في بوت الكيمياء التحصيلي! أنا هنا لمساعدتك في الاستعداد لاختباراتك. يمكنك البدء باختبار تجريبي أو اختيار وحدة معينة.\nتطوير الاستاذ حسين علي الموسى"
    
    text_to_use = default_text
    if db_manager and hasattr(db_manager, 'get_system_message'):
        try:
            db_message = db_manager.get_system_message(welcome_message_key)
            if db_message:  # إذا كانت الرسالة موجودة في قاعدة البيانات وليست فارغة
                text_to_use = db_message
        except Exception as e:
            logger.error(f"Error getting system message '{welcome_message_key}': {e}")
            # يتم استخدام النص الافتراضي في حالة الخطأ

    # استبدال العنصر النائب إذا كان موجودًا في النص (سواء من قاعدة البيانات أو الافتراضي إذا تم تعديله ليشمله)
    if "{user.first_name}" in text_to_use:
        actual_user_name = user_first_name if user_first_name else "مستخدمنا العزيز"
        text_to_use = text_to_use.replace("{user.first_name}", actual_user_name)
    
    return text_to_use

# تعريف ثوابت الحالات
try:
    from config import (
        MAIN_MENU,
        END,
        REGISTRATION_NAME,
        REGISTRATION_EMAIL,
        REGISTRATION_PHONE,
        REGISTRATION_GRADE,
        REGISTRATION_CONFIRM,
        EDIT_USER_INFO_MENU,
        EDIT_USER_NAME,
        EDIT_USER_EMAIL,
        EDIT_USER_PHONE,
        EDIT_USER_GRADE
    )
except ImportError as e:
    logger.error(f"خطأ في استيراد الثوابت من config.py: {e}. استخدام قيم افتراضية.")
    # تعريف ثوابت افتراضية
    MAIN_MENU = 0
    END = -1
    
    # تعريف ثوابت حالات التسجيل
    REGISTRATION_NAME = 20
    REGISTRATION_EMAIL = 21
    REGISTRATION_PHONE = 22
    REGISTRATION_GRADE = 24
    REGISTRATION_CONFIRM = 25
    EDIT_USER_INFO_MENU = 26
    EDIT_USER_NAME = 27
    EDIT_USER_EMAIL = 28
    EDIT_USER_PHONE = 29
    EDIT_USER_GRADE = 30

# التحقق من صحة البريد الإلكتروني
def is_valid_email(email):
    """التحقق من صحة تنسيق البريد الإلكتروني"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

# التحقق من صحة رقم الجوال
def is_valid_phone(phone):
    """التحقق من صحة تنسيق رقم الجوال"""
    # يقبل أرقام سعودية تبدأ بـ 05 أو +966 أو 00966
    pattern = r'^(05\d{8}|\+966\d{9}|00966\d{9})$'
    return re.match(pattern, phone) is not None

# إنشاء لوحة مفاتيح للصفوف الدراسية
def create_grade_keyboard():
    """إنشاء لوحة مفاتيح للصفوف الدراسية"""
    keyboard = []
    
    # الصفوف الثانوية فقط (حذف الابتدائي والمتوسط)
    secondary_row = []
    for grade in range(1, 4):
        secondary_row.append(InlineKeyboardButton(f"ثانوي {grade}", callback_data=f"grade_secondary_{grade}"))
    keyboard.append(secondary_row)
    
    # خيارات أخرى
    keyboard.append([InlineKeyboardButton("طالب جامعي", callback_data="grade_university")])
    keyboard.append([InlineKeyboardButton("معلم", callback_data="grade_teacher")])
    keyboard.append([InlineKeyboardButton("أخرى", callback_data="grade_other")])
    
    return InlineKeyboardMarkup(keyboard)

# إنشاء لوحة مفاتيح لتأكيد المعلومات
def create_confirmation_keyboard():
    """إنشاء لوحة مفاتيح لتأكيد معلومات التسجيل"""
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد المعلومات", callback_data="confirm_registration")],
        [InlineKeyboardButton("✏️ تعديل الاسم", callback_data="edit_name")],
        [InlineKeyboardButton("✏️ تعديل البريد الإلكتروني", callback_data="edit_email")],
        [InlineKeyboardButton("✏️ تعديل رقم الجوال", callback_data="edit_phone")],
        [InlineKeyboardButton("✏️ تعديل الصف الدراسي", callback_data="edit_grade")]
    ]
    return InlineKeyboardMarkup(keyboard)

# إنشاء لوحة مفاتيح لتعديل المعلومات
def create_edit_info_keyboard():
    """إنشاء لوحة مفاتيح لتعديل معلومات المستخدم"""
    keyboard = [
        [InlineKeyboardButton("✏️ تعديل الاسم", callback_data="edit_name")],
        [InlineKeyboardButton("✏️ تعديل البريد الإلكتروني", callback_data="edit_email")],
        [InlineKeyboardButton("✏️ تعديل رقم الجوال", callback_data="edit_phone")],
        [InlineKeyboardButton("✏️ تعديل الصف الدراسي", callback_data="edit_grade")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# إنشاء لوحة مفاتيح القائمة الرئيسية
def create_main_menu_keyboard(user_id, db_manager=None):
    """إنشاء لوحة مفاتيح القائمة الرئيسية"""
    keyboard = [
        [InlineKeyboardButton("🧠 بدء اختبار جديد", callback_data="start_quiz")],
        [InlineKeyboardButton("📚 معلومات كيميائية", callback_data="menu_info")],
        [InlineKeyboardButton("📊 إحصائياتي ولوحة الصدارة", callback_data="menu_stats")],
        [InlineKeyboardButton("👤 تعديل معلوماتي", callback_data="edit_my_info")],
        [InlineKeyboardButton("ℹ️ حول البوت", callback_data="about_bot")]
    ]
    # إضافة زر لوحة تحكم الأدمن إذا كان المستخدم أدمن
    # هذا الجزء يفترض أن db_manager لديه طريقة is_user_admin
    if db_manager and hasattr(db_manager, 'is_user_admin') and db_manager.is_user_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم الأدمن", callback_data="admin_show_tools_menu")])
    return InlineKeyboardMarkup(keyboard)

# حفظ أو تحديث معلومات المستخدم في قاعدة البيانات
def save_user_info(db_manager, user_id, **kwargs):
    """
    حفظ أو تحديث معلومات المستخدم في قاعدة البيانات
    
    المعلمات:
        db_manager: كائن مدير قاعدة البيانات
        user_id: معرف المستخدم
        **kwargs: معلومات المستخدم الإضافية (full_name, email, phone, grade, is_registered)
    
    يعيد:
        bool: True إذا تم الحفظ بنجاح، False إذا حدث خطأ
    """
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في save_user_info للمستخدم {user_id}")
        return False
    
    try:
        # استخدام الدالة المناسبة في مدير قاعدة البيانات
        if hasattr(db_manager, 'update_user'):
            # تحديث المستخدم باستخدام دالة update_user
            db_manager.update_user(
                user_id=user_id,
                **kwargs
            )
        elif hasattr(db_manager, 'save_user'):
            # حفظ المستخدم باستخدام دالة save_user
            db_manager.save_user(
                user_id=user_id,
                **kwargs
            )
        else:
            # استخدام SQLAlchemy مباشرة إذا لم تتوفر الدوال المناسبة
            from sqlalchemy import update, insert
            # التأكد من أن مسار db_setup صحيح أو تعديله حسب الحاجة
            from database.db_setup import users_table 
            
            # التحقق من وجود المستخدم
            with db_manager.engine.connect() as conn:
                result = conn.execute(
                    users_table.select().where(users_table.c.user_id == user_id)
                ).fetchone()
                
                if result:
                    # تحديث المستخدم الموجود
                    conn.execute(
                        update(users_table)
                        .where(users_table.c.user_id == user_id)
                        .values(**kwargs)
                    )
                else:
                    # إضافة مستخدم جديد
                    kwargs['user_id'] = user_id
                    conn.execute(
                        insert(users_table)
                        .values(**kwargs)
                    )
                
                conn.commit()
        
        logger.info(f"تم حفظ/تحديث معلومات المستخدم {user_id} بنجاح")
        return True
    except Exception as e:
        logger.error(f"خطأ في حفظ/تحديث معلومات المستخدم {user_id}: {e}")
        return False

# الحصول على معلومات المستخدم من قاعدة البيانات
def get_user_info(db_manager, user_id):
    """
    الحصول على معلومات المستخدم من قاعدة البيانات
    
    المعلمات:
        db_manager: كائن مدير قاعدة البيانات
        user_id: معرف المستخدم
    
    يعيد:
        dict: معلومات المستخدم، أو None إذا لم يتم العثور على المستخدم
    """
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في get_user_info للمستخدم {user_id}")
        return None
    
    try:
        # استخدام الدالة المناسبة في مدير قاعدة البيانات
        if hasattr(db_manager, 'get_user_info'):
            # الحصول على معلومات المستخدم باستخدام دالة get_user_info
            return db_manager.get_user_info(user_id)
        else:
            # استخدام SQLAlchemy مباشرة إذا لم تتوفر الدالة المناسبة
            from sqlalchemy import select
            from database.db_setup import users_table # التأكد من المسار
            
            with db_manager.engine.connect() as conn:
                result = conn.execute(
                    select(users_table).where(users_table.c.user_id == user_id)
                ).fetchone()
                
                if result:
                    # تحويل النتيجة إلى قاموس
                    user_info = dict(result._mapping)
                    return user_info
                else:
                    return None
    except Exception as e:
        logger.error(f"خطأ في الحصول على معلومات المستخدم {user_id}: {e}")
        return None

# التحقق من اكتمال معلومات المستخدم
def is_user_fully_registered(user_info):
    """
    التحقق من اكتمال معلومات المستخدم الأساسية
    
    المعلمات:
        user_info: قاموس يحتوي على معلومات المستخدم
    
    يعيد:
        bool: True إذا كانت جميع المعلومات الأساسية مكتملة، False إذا كان هناك نقص
    """
    if not user_info:
        return False
    
    # التحقق من وجود المعلومات الأساسية وصحتها
    full_name = user_info.get('full_name')
    email = user_info.get('email')
    phone = user_info.get('phone')
    grade = user_info.get('grade')
    
    # التحقق من الاسم (موجود وطوله أكبر من 3 أحرف)
    has_full_name = full_name not in [None, 'None', ''] and len(str(full_name).strip()) >= 3
    
    # التحقق من البريد الإلكتروني (موجود وصحيح)
    has_email = email not in [None, 'None', ''] and is_valid_email(str(email).strip())
    
    # التحقق من رقم الجوال (موجود وصحيح)
    has_phone = phone not in [None, 'None', ''] and is_valid_phone(str(phone).strip())
    
    # التحقق من الصف الدراسي (موجود وليس فارغاً)
    has_grade = grade not in [None, 'None', ''] and len(str(grade).strip()) > 0
    
    # اعتبار المستخدم مسجلاً فقط إذا كانت جميع المعلومات الأساسية موجودة
    return all([has_full_name, has_email, has_phone, has_grade])

# دالة معالجة أمر /start
async def start_command(update: Update, context: CallbackContext) -> int:
    """معالجة أمر /start بشكل منفصل عن محادثة التسجيل"""
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id
    
    logger.info(f"[DEBUG] Entering start_command for user {user_id}")
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في start_command للمستخدم {user_id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END # إنهاء المحادثة في حالة الخطأ
    
    # التحقق من حالة تسجيل المستخدم
    user_info = get_user_info(db_manager, user_id)
    is_registered = is_user_fully_registered(user_info)
    context.user_data['is_registered'] = is_registered
    
    if is_registered:
        logger.info(f"المستخدم {user_id} مسجل بالفعل، عرض القائمة الرئيسية مع رسالة الترحيب الموحدة")
        # المستخدم مسجل، رسالة الترحيب ستكون عنوان القائمة الرئيسية
        menu_title_text = get_unified_welcome_text(db_manager, user.first_name)
        
        try:
            # محاولة استيراد واستدعاء main_menu_callback
            # يفترض أن main_menu_callback المحدث سيعرض رسالة الترحيب + القائمة
            from handlers.common import main_menu_callback
            await main_menu_callback(update, context) 
            return ConversationHandler.END
        except ImportError:
            try:
                from common import main_menu_callback
                await main_menu_callback(update, context)
                return ConversationHandler.END
            except ImportError as e:
                logger.error(f"خطأ في استيراد main_menu_callback: {e}. عرض القائمة الرئيسية مباشرة.")
                # Fallback: عرض القائمة الرئيسية مباشرة مع رسالة الترحيب الموحدة كعنوان
                keyboard = create_main_menu_keyboard(user_id, db_manager)
                await safe_send_message(
                    context.bot,
                    chat_id,
                    text=menu_title_text, # استخدام رسالة الترحيب الموحدة كعنوان للقائمة
                    reply_markup=keyboard
                )
                return ConversationHandler.END
    else:
        # المستخدم غير مسجل، إرسال رسالة الترحيب ثم بدء التسجيل
        logger.info(f"المستخدم {user_id} غير مسجل، بدء عملية التسجيل")
        welcome_message_for_new_user = get_unified_welcome_text(db_manager, user.first_name)
        await safe_send_message(
            context.bot,
            chat_id,
            text=welcome_message_for_new_user # إرسال رسالة الترحيب بدون لوحة مفاتيح
        )
        return await start_registration(update, context) # دالة التسجيل ستبدأ بطلب المعلومات

async def check_registration_status(update: Update, context: CallbackContext, db_manager=None):
    """
    التحقق من حالة تسجيل المستخدم وتوجيهه لإكمال التسجيل إذا لم يكن مسجلاً
    
    يعيد:
        bool: True إذا كان المستخدم مسجلاً، False إذا كان يحتاج للتسجيل
    """
    user = update.effective_user
    user_id = user.id
    
    # التحقق من حالة التسجيل المخزنة في context.user_data أولاً
    if context.user_data.get('is_registered', False):
        logger.info(f"المستخدم {user_id} مسجل بالفعل (من context.user_data)")
        return True
    
    # الحصول على مدير قاعدة البيانات من context أو استخدام المعطى
    if not db_manager:
        db_manager = context.bot_data.get("DB_MANAGER")
        if not db_manager:
            logger.error(f"لا يمكن الوصول إلى DB_MANAGER في check_registration_status للمستخدم {user_id}")
            # لا نفترض أن المستخدم مسجل في حالة عدم وجود مدير قاعدة بيانات
            # بدلاً من ذلك، نطلب منه التسجيل
            await start_registration(update, context) # قد تحتاج هذه إلى تعديل إذا كانت start_registration تتوقع أن يتم استدعاؤها فقط من start_command
            return False
    
    # الحصول على معلومات المستخدم من قاعدة البيانات
    user_info = get_user_info(db_manager, user_id)
    
    # التحقق من اكتمال معلومات المستخدم
    is_registered = is_user_fully_registered(user_info)
    
    # تحديث حالة التسجيل في context.user_data
    context.user_data['is_registered'] = is_registered
    
    # إذا لم يكن المستخدم مسجلاً، توجيهه لإكمال التسجيل
    if not is_registered:
        logger.info(f"المستخدم {user_id} غير مسجل، توجيهه لإكمال التسجيل")
        # إرسال رسالة الترحيب الموحدة قبل بدء التسجيل، إذا لم تكن قد أُرسلت بالفعل
        # هذا الجزء قد يكون مكررًا إذا كان check_registration_status يُستدعى دائمًا بعد start_command
        # welcome_message_for_new_user = get_unified_welcome_text(db_manager, user.first_name)
        # await safe_send_message(context.bot, update.effective_chat.id, text=welcome_message_for_new_user)
        await start_registration(update, context)
        return False
    
    logger.info(f"المستخدم {user_id} مسجل بالفعل (من قاعدة البيانات)")
    return True

# بدء عملية التسجيل
async def start_registration(update: Update, context: CallbackContext) -> int:
    """بدء عملية تسجيل مستخدم جديد"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    logger.info(f"[DEBUG] Entering start_registration for user {user.id}")
    
    # تهيئة بيانات التسجيل المؤقتة
    context.user_data['registration_data'] = {}
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if db_manager:
        # محاولة الحصول على معلومات المستخدم الحالية
        user_info = get_user_info(db_manager, user.id)
        if user_info:
            # تخزين المعلومات الحالية في بيانات التسجيل المؤقتة
            context.user_data['registration_data'] = {
                'full_name': user_info.get('full_name', ''),
                'email': user_info.get('email', ''),
                'phone': user_info.get('phone', ''),
                'grade': user_info.get('grade', '')
            }
    
    # رسالة الترحيب الرئيسية أُرسلت بواسطة start_command
    # الآن فقط اطلب معلومات التسجيل
    registration_prompt_text = "لاستخدام البوت، يرجى إكمال التسجيل أولاً.\n\n" \
                               "الخطوة الأولى: أدخل اسمك الكامل:"
    
    if context.user_data['registration_data'].get('full_name'):
        registration_prompt_text += f"\n\n(الاسم الحالي: {context.user_data['registration_data'].get('full_name')})"
    
    await safe_send_message(
        context.bot,
        chat_id,
        text=registration_prompt_text
    )
    logger.info(f"[DEBUG] start_registration: Asked for name, returning state REGISTRATION_NAME ({REGISTRATION_NAME})")
    return REGISTRATION_NAME

# معالجة إدخال الاسم
async def handle_name_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال الاسم من المستخدم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    name = update.message.text.strip()
    
    # تسجيل معلومات التصحيح
    logger.info(f"[DEBUG] Entering handle_name_input for user {user.id}")
    logger.debug(f"[DEBUG] Received name from user {user.id}: {name}")
    
    # التحقق من صحة الاسم
    if len(name) < 3:
        logger.warning(f"[DEBUG] Invalid name received from user {user.id}: {name}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ الاسم قصير جداً. يرجى إدخال اسمك الكامل (3 أحرف على الأقل):"
        )
        logger.info(f"[DEBUG] handle_name_input: Asking for name again, returning state REGISTRATION_NAME ({REGISTRATION_NAME})")
        return REGISTRATION_NAME
    
    # حفظ الاسم في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['full_name'] = name
    logger.info(f"[DEBUG] Saved name '{name}' for user {user.id} in context.user_data")
    
    # إرسال رسالة تأكيد وطلب البريد الإلكتروني
    await safe_send_message(
        context.bot,
        chat_id,
        text=f"✅ تم تسجيل الاسم: {name}\n\n"
             "الخطوة الثانية: أدخل بريدك الإلكتروني:"
    )
    logger.info(f"[DEBUG] handle_name_input: Asked for email, returning state REGISTRATION_EMAIL ({REGISTRATION_EMAIL})")
    return REGISTRATION_EMAIL

# معالجة إدخال البريد الإلكتروني
async def handle_email_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال البريد الإلكتروني من المستخدم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    email = update.message.text.strip()
    
    # تسجيل معلومات التصحيح
    logger.info(f"[DEBUG] Entering handle_email_input for user {user.id}")
    logger.debug(f"[DEBUG] Received email from user {user.id}: {email}")
    
    # التحقق من صحة البريد الإلكتروني
    if not is_valid_email(email):
        logger.warning(f"[DEBUG] Invalid email received from user {user.id}: {email}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ البريد الإلكتروني غير صحيح. يرجى إدخال بريد إلكتروني صحيح:"
        )
        logger.info(f"[DEBUG] handle_email_input: Asking for email again, returning state REGISTRATION_EMAIL ({REGISTRATION_EMAIL})")
        return REGISTRATION_EMAIL
    
    # حفظ البريد الإلكتروني في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['email'] = email
    logger.info(f"[DEBUG] Saved email '{email}' for user {user.id} in context.user_data")
    
    # إرسال رسالة تأكيد وطلب رقم الجوال
    await safe_send_message(
        context.bot,
        chat_id,
        text=f"✅ تم تسجيل البريد الإلكتروني: {email}\n\n"
             "الخطوة الثالثة: أدخل رقم جوالك (يبدأ بـ 05 أو +966 أو 00966):"
    )
    logger.info(f"[DEBUG] handle_email_input: Asked for phone, returning state REGISTRATION_PHONE ({REGISTRATION_PHONE})")
    return REGISTRATION_PHONE

# معالجة إدخال رقم الجوال
async def handle_phone_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال رقم الجوال من المستخدم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    phone = update.message.text.strip()
    
    # تسجيل معلومات التصحيح
    logger.info(f"[DEBUG] Entering handle_phone_input for user {user.id}")
    logger.debug(f"[DEBUG] Received phone from user {user.id}: {phone}")
    
    # التحقق من صحة رقم الجوال
    if not is_valid_phone(phone):
        logger.warning(f"[DEBUG] Invalid phone received from user {user.id}: {phone}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ رقم الجوال غير صحيح. يرجى إدخال رقم جوال سعودي صحيح (يبدأ بـ 05 أو +966 أو 00966):"
        )
        logger.info(f"[DEBUG] handle_phone_input: Asking for phone again, returning state REGISTRATION_PHONE ({REGISTRATION_PHONE})")
        return REGISTRATION_PHONE
    
    # حفظ رقم الجوال في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['phone'] = phone
    logger.info(f"[DEBUG] Saved phone '{phone}' for user {user.id} in context.user_data")
    
    # إرسال رسالة تأكيد وطلب الصف الدراسي
    keyboard = create_grade_keyboard()
    await safe_send_message(
        context.bot,
        chat_id,
        text=f"✅ تم تسجيل رقم الجوال: {phone}\n\n"
             "الخطوة الرابعة: اختر الصف الدراسي:",
        reply_markup=keyboard
    )
    logger.info(f"[DEBUG] handle_phone_input: Asked for grade, returning state REGISTRATION_GRADE ({REGISTRATION_GRADE})")
    return REGISTRATION_GRADE

# معالجة اختيار الصف الدراسي
async def handle_grade_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار الصف الدراسي من المستخدم"""
    query = update.callback_query
    user = update.effective_user
    chat_id = query.message.chat_id
    
    # تسجيل معلومات التصحيح
    logger.info(f"[DEBUG] Entering handle_grade_selection for user {user.id}")
    logger.debug(f"[DEBUG] Received grade selection from user {user.id}: {query.data}")
    
    # التحقق من صحة البيانات
    if not query.data.startswith("grade_"):
        logger.warning(f"[DEBUG] Invalid grade selection received from user {user.id}: {query.data}")
        await query.answer("خيار غير صحيح")
        logger.info(f"[DEBUG] handle_grade_selection: Asking for grade again, returning state REGISTRATION_GRADE ({REGISTRATION_GRADE})")
        return REGISTRATION_GRADE
    
    # استخراج الصف الدراسي
    grade = query.data.replace("grade_", "")
    
    # حفظ الصف الدراسي في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['grade'] = grade
    logger.info(f"[DEBUG] Saved grade '{grade}' for user {user.id} in context.user_data")
    
    # إرسال رسالة تأكيد
    await query.answer("تم اختيار الصف الدراسي")
    
    # عرض ملخص المعلومات للتأكيد
    registration_data = context.user_data['registration_data']
    confirmation_text = "📋 الرجاء تأكيد المعلومات التالية:\n\n" \
                        f"👤 الاسم: {registration_data.get('full_name', '')}\n" \
                        f"📧 البريد الإلكتروني: {registration_data.get('email', '')}\n" \
                        f"📱 رقم الجوال: {registration_data.get('phone', '')}\n" \
                        f"🏫 الصف الدراسي: {grade}"
    
    keyboard = create_confirmation_keyboard()
    await safe_edit_message_text(
        context.bot,
        chat_id,
        query.message.message_id,
        text=confirmation_text,
        reply_markup=keyboard
    )
    logger.info(f"[DEBUG] handle_grade_selection: Asked for confirmation, returning state REGISTRATION_CONFIRM ({REGISTRATION_CONFIRM})")
    return REGISTRATION_CONFIRM

# معالجة تأكيد المعلومات
async def handle_confirmation(update: Update, context: CallbackContext) -> int:
    """معالجة تأكيد المعلومات من المستخدم"""
    query = update.callback_query
    user = update.effective_user
    chat_id = query.message.chat_id
    db_manager = context.bot_data.get("DB_MANAGER") # جلب db_manager هنا
    
    # تسجيل معلومات التصحيح
    logger.info(f"[DEBUG] Entering handle_confirmation for user {user.id}")
    logger.debug(f"[DEBUG] Received confirmation from user {user.id}: {query.data}")
    
    # التحقق من صحة البيانات
    if query.data not in ["confirm_registration", "edit_name", "edit_email", "edit_phone", "edit_grade"]:
        logger.warning(f"[DEBUG] Invalid confirmation received from user {user.id}: {query.data}")
        await query.answer("خيار غير صحيح")
        logger.info(f"[DEBUG] handle_confirmation: Asking for confirmation again, returning state REGISTRATION_CONFIRM ({REGISTRATION_CONFIRM})")
        return REGISTRATION_CONFIRM
    
    # إرسال رسالة تأكيد
    await query.answer()
    
    # معالجة الإجراء
    if query.data == "confirm_registration":
        # تأكيد المعلومات وحفظها في قاعدة البيانات
        registration_data = context.user_data['registration_data']
        
        if not db_manager: # التحقق من db_manager مرة أخرى
            logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_confirmation للمستخدم {user.id}")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
            )
            logger.info(f"[DEBUG] handle_confirmation: DB_MANAGER not found, returning state END ({END})")
            return ConversationHandler.END
        
        # حفظ المعلومات في قاعدة البيانات
        success = save_user_info(
            db_manager,
            user.id,
            full_name=registration_data.get('full_name', ''),
            email=registration_data.get('email', ''),
            phone=registration_data.get('phone', ''),
            grade=registration_data.get('grade', ''),
            is_registered=True,
            registration_date=datetime.now()
        )
        
        if not success:
            logger.error(f"فشل حفظ معلومات المستخدم {user.id} في قاعدة البيانات")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="⚠️ حدث خطأ في حفظ المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
            )
            logger.info(f"[DEBUG] handle_confirmation: Failed to save user info, returning state END ({END})")
            return ConversationHandler.END
        
        # تحديث حالة التسجيل في context.user_data
        context.user_data['is_registered'] = True
        logger.info(f"[DEBUG] User {user.id} is now registered")
        
        # إرسال رسالة تأكيد
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="✅ تم تسجيل معلوماتك بنجاح! يمكنك الآن استخدام جميع ميزات البوت."
        )
        
        # عرض القائمة الرئيسية مع رسالة الترحيب الموحدة
        menu_title_text = get_unified_welcome_text(db_manager, user.first_name)
        try:
            from handlers.common import main_menu_callback
            # يفترض أن main_menu_callback المحدث سيعرض رسالة الترحيب + القائمة
            await main_menu_callback(update, context)
            return ConversationHandler.END
        except ImportError:
            try:
                from common import main_menu_callback
                await main_menu_callback(update, context)
                return ConversationHandler.END
            except ImportError as e:
                logger.error(f"خطأ في استيراد main_menu_callback: {e}")
                # Fallback: عرض القائمة الرئيسية مباشرة مع رسالة الترحيب الموحدة كعنوان
                keyboard = create_main_menu_keyboard(user.id, db_manager)
                await safe_send_message(
                    context.bot,
                    chat_id,
                    text=menu_title_text, # استخدام رسالة الترحيب الموحدة كعنوان للقائمة
                    reply_markup=keyboard
                )
                logger.info(f"[DEBUG] handle_confirmation: Showing main menu, returning state END ({END})")
                return ConversationHandler.END
    
    elif query.data == "edit_name":
        # تعديل الاسم
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="👤 الرجاء إدخال الاسم الكامل:"
        )
        logger.info(f"[DEBUG] handle_confirmation: Editing name, returning state REGISTRATION_NAME ({REGISTRATION_NAME})")
        return REGISTRATION_NAME
    
    elif query.data == "edit_email":
        # تعديل البريد الإلكتروني
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="📧 الرجاء إدخال البريد الإلكتروني:"
        )
        logger.info(f"[DEBUG] handle_confirmation: Editing email, returning state REGISTRATION_EMAIL ({REGISTRATION_EMAIL})")
        return REGISTRATION_EMAIL
    
    elif query.data == "edit_phone":
        # تعديل رقم الجوال
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="📱 الرجاء إدخال رقم الجوال (يبدأ بـ 05 أو +966 أو 00966):"
        )
        logger.info(f"[DEBUG] handle_confirmation: Editing phone, returning state REGISTRATION_PHONE ({REGISTRATION_PHONE})")
        return REGISTRATION_PHONE
    
    elif query.data == "edit_grade":
        # تعديل الصف الدراسي
        keyboard = create_grade_keyboard()
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="🏫 الرجاء اختيار الصف الدراسي:",
            reply_markup=keyboard
        )
        logger.info(f"[DEBUG] handle_confirmation: Editing grade, returning state REGISTRATION_GRADE ({REGISTRATION_GRADE})")
        return REGISTRATION_GRADE

# معالجة أمر تعديل المعلومات
async def edit_info_command(update: Update, context: CallbackContext) -> int:
    """معالجة أمر تعديل المعلومات"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    db_manager = context.bot_data.get("DB_MANAGER") # جلب db_manager هنا
    
    # تسجيل معلومات التصحيح
    logger.info(f"[DEBUG] Entering edit_info_command for user {user.id}")
    
    if not db_manager: # التحقق من db_manager
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في edit_info_command للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] edit_info_command: DB_MANAGER not found, returning state END ({END})")
        return ConversationHandler.END
    
    # الحصول على معلومات المستخدم
    user_info = get_user_info(db_manager, user.id)
    
    # التحقق من وجود المستخدم
    if not user_info:
        logger.warning(f"[DEBUG] User info not found for user {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ لم يتم العثور على معلوماتك. يرجى استخدام الأمر /start للتسجيل أولاً."
        )
        logger.info(f"[DEBUG] edit_info_command: User info not found, returning state END ({END})")
        return ConversationHandler.END
    
    # تهيئة بيانات التسجيل المؤقتة
    context.user_data['registration_data'] = {
        'full_name': user_info.get('full_name', ''),
        'email': user_info.get('email', ''),
        'phone': user_info.get('phone', ''),
        'grade': user_info.get('grade', '')
    }
    logger.info(f"[DEBUG] Saved user info in context.user_data for user {user.id}")
    
    # عرض قائمة تعديل المعلومات
    keyboard = create_edit_info_keyboard()
    await safe_send_message(
        context.bot,
        chat_id,
        text="✏️ تعديل المعلومات الشخصية\n\n"
             f"👤 الاسم: {user_info.get('full_name', '')}\n"
             f"📧 البريد الإلكتروني: {user_info.get('email', '')}\n"
             f"📱 رقم الجوال: {user_info.get('phone', '')}\n"
             f"🏫 الصف الدراسي: {user_info.get('grade', '')}\n\n"
             "الرجاء اختيار المعلومات التي ترغب في تعديلها:",
        reply_markup=keyboard
    )
    logger.info(f"[DEBUG] edit_info_command: Showing edit info menu, returning state EDIT_USER_INFO_MENU ({EDIT_USER_INFO_MENU})")
    return EDIT_USER_INFO_MENU

# معالجة اختيار قائمة تعديل المعلومات
async def handle_edit_info_menu(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار قائمة تعديل المعلومات"""
    query = update.callback_query
    user = update.effective_user
    chat_id = query.message.chat_id
    db_manager = context.bot_data.get("DB_MANAGER") # جلب db_manager هنا
    
    # تسجيل معلومات التصحيح
    logger.info(f"[DEBUG] Entering handle_edit_info_menu for user {user.id}")
    logger.debug(f"[DEBUG] Received edit info menu selection from user {user.id}: {query.data}")
    
    # التحقق من صحة البيانات
    if query.data not in ["edit_name", "edit_email", "edit_phone", "edit_grade", "main_menu"]:
        logger.warning(f"[DEBUG] Invalid edit info menu selection received from user {user.id}: {query.data}")
        await query.answer("خيار غير صحيح")
        logger.info(f"[DEBUG] handle_edit_info_menu: Invalid selection, returning state EDIT_USER_INFO_MENU ({EDIT_USER_INFO_MENU})")
        return EDIT_USER_INFO_MENU
    
    # إرسال رسالة تأكيد
    await query.answer()
    
    # معالجة الإجراء
    if query.data == "edit_name":
        # تعديل الاسم
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="👤 الرجاء إدخال الاسم الكامل:"
        )
        logger.info(f"[DEBUG] handle_edit_info_menu: Editing name, returning state EDIT_USER_NAME ({EDIT_USER_NAME})")
        return EDIT_USER_NAME
    
    elif query.data == "edit_email":
        # تعديل البريد الإلكتروني
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="📧 الرجاء إدخال البريد الإلكتروني:"
        )
        logger.info(f"[DEBUG] handle_edit_info_menu: Editing email, returning state EDIT_USER_EMAIL ({EDIT_USER_EMAIL})")
        return EDIT_USER_EMAIL
    
    elif query.data == "edit_phone":
        # تعديل رقم الجوال
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="📱 الرجاء إدخال رقم الجوال (يبدأ بـ 05 أو +966 أو 00966):"
        )
        logger.info(f"[DEBUG] handle_edit_info_menu: Editing phone, returning state EDIT_USER_PHONE ({EDIT_USER_PHONE})")
        return EDIT_USER_PHONE
    
    elif query.data == "edit_grade":
        # تعديل الصف الدراسي
        keyboard = create_grade_keyboard()
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="🏫 الرجاء اختيار الصف الدراسي:",
            reply_markup=keyboard
        )
        logger.info(f"[DEBUG] handle_edit_info_menu: Editing grade, returning state EDIT_USER_GRADE ({EDIT_USER_GRADE})")
        return EDIT_USER_GRADE
    
    elif query.data == "main_menu":
        # العودة للقائمة الرئيسية مع رسالة الترحيب الموحدة
        menu_title_text = get_unified_welcome_text(db_manager, user.first_name)
        try:
            from handlers.common import main_menu_callback
            # يفترض أن main_menu_callback المحدث سيعرض رسالة الترحيب + القائمة
            await main_menu_callback(update, context)
            return ConversationHandler.END
        except ImportError:
            try:
                from common import main_menu_callback
                await main_menu_callback(update, context)
                return ConversationHandler.END
            except ImportError as e:
                logger.error(f"خطأ في استيراد main_menu_callback: {e}")
                # Fallback: عرض القائمة الرئيسية مباشرة مع رسالة الترحيب الموحدة كعنوان
                # التأكد من أن db_manager متاح هنا
                if not db_manager:
                    logger.error(f"DB_MANAGER is None when returning to main_menu fallback for user {user.id}")
                    await safe_edit_message_text(context.bot, chat_id, query.message.message_id, text="⚠️ حدث خطأ في النظام.")
                    return ConversationHandler.END
                
                keyboard = create_main_menu_keyboard(user.id, db_manager)
                # استخدام safe_edit_message_text لتعديل الرسالة الحالية
                await safe_edit_message_text(
                    context.bot,
                    chat_id,
                    query.message.message_id, # تعديل الرسالة الحالية
                    text=menu_title_text, # استخدام رسالة الترحيب الموحدة كعنوان للقائمة
                    reply_markup=keyboard
                )
                logger.info(f"[DEBUG] handle_edit_info_menu: Showing main menu, returning state END ({END})")
                return ConversationHandler.END

# معالجة تعديل الاسم
async def handle_edit_name(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل الاسم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    name = update.message.text.strip()
    db_manager = context.bot_data.get("DB_MANAGER") # جلب db_manager هنا
    
    # تسجيل معلومات التصحيح
    logger.info(f"[DEBUG] Entering handle_edit_name for user {user.id}")
    logger.debug(f"[DEBUG] Received name from user {user.id}: {name}")
    
    # التحقق من صحة الاسم
    if len(name) < 3:
        logger.warning(f"[DEBUG] Invalid name received from user {user.id}: {name}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ الاسم قصير جداً. يرجى إدخال اسمك الكامل (3 أحرف على الأقل):"
        )
        logger.info(f"[DEBUG] handle_edit_name: Asking for name again, returning state EDIT_USER_NAME ({EDIT_USER_NAME})")
        return EDIT_USER_NAME
    
    # حفظ الاسم في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['full_name'] = name
    logger.info(f"[DEBUG] Saved name '{name}' for user {user.id} in context.user_data")
    
    if not db_manager: # التحقق من db_manager
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_name للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_name: DB_MANAGER not found, returning state END ({END})")
        return ConversationHandler.END
    
    # حفظ المعلومات في قاعدة البيانات
    success = save_user_info(
        db_manager,
        user.id,
        full_name=name
    )
    
    if not success:
        logger.error(f"فشل حفظ اسم المستخدم {user.id} في قاعدة البيانات")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في حفظ المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_name: Failed to save user name, returning state END ({END})")
        return ConversationHandler.END
    
    # إرسال رسالة تأكيد
    await safe_send_message(
        context.bot,
        chat_id,
        text="✅ تم تعديل الاسم بنجاح!"
    )
    
    # عرض قائمة تعديل المعلومات
    keyboard = create_edit_info_keyboard()
    await safe_send_message(
        context.bot,
        chat_id,
        text="✏️ تعديل المعلومات الشخصية\n\n"
             f"👤 الاسم: {name}\n"
             f"📧 البريد الإلكتروني: {context.user_data['registration_data'].get('email', '')}\n"
             f"📱 رقم الجوال: {context.user_data['registration_data'].get('phone', '')}\n"
             f"🏫 الصف الدراسي: {context.user_data['registration_data'].get('grade', '')}\n\n"
             "الرجاء اختيار المعلومات التي ترغب في تعديلها:",
        reply_markup=keyboard
    )
    logger.info(f"[DEBUG] handle_edit_name: Showing edit info menu, returning state EDIT_USER_INFO_MENU ({EDIT_USER_INFO_MENU})")
    return EDIT_USER_INFO_MENU

# معالجة تعديل البريد الإلكتروني
async def handle_edit_email(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل البريد الإلكتروني"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    email = update.message.text.strip()
    db_manager = context.bot_data.get("DB_MANAGER") # جلب db_manager هنا
    
    # تسجيل معلومات التصحيح
    logger.info(f"[DEBUG] Entering handle_edit_email for user {user.id}")
    logger.debug(f"[DEBUG] Received email from user {user.id}: {email}")
    
    # التحقق من صحة البريد الإلكتروني
    if not is_valid_email(email):
        logger.warning(f"[DEBUG] Invalid email received from user {user.id}: {email}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ البريد الإلكتروني غير صحيح. يرجى إدخال بريد إلكتروني صحيح:"
        )
        logger.info(f"[DEBUG] handle_edit_email: Asking for email again, returning state EDIT_USER_EMAIL ({EDIT_USER_EMAIL})")
        return EDIT_USER_EMAIL
    
    # حفظ البريد الإلكتروني في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['email'] = email
    logger.info(f"[DEBUG] Saved email '{email}' for user {user.id} in context.user_data")
    
    if not db_manager: # التحقق من db_manager
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_email للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_email: DB_MANAGER not found, returning state END ({END})")
        return ConversationHandler.END
    
    # حفظ المعلومات في قاعدة البيانات
    success = save_user_info(
        db_manager,
        user.id,
        email=email
    )
    
    if not success:
        logger.error(f"فشل حفظ بريد المستخدم {user.id} في قاعدة البيانات")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في حفظ المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_email: Failed to save user email, returning state END ({END})")
        return ConversationHandler.END
    
    # إرسال رسالة تأكيد
    await safe_send_message(
        context.bot,
        chat_id,
        text="✅ تم تعديل البريد الإلكتروني بنجاح!"
    )
    
    # عرض قائمة تعديل المعلومات
    keyboard = create_edit_info_keyboard()
    await safe_send_message(
        context.bot,
        chat_id,
        text="✏️ تعديل المعلومات الشخصية\n\n"
             f"👤 الاسم: {context.user_data['registration_data'].get('full_name', '')}\n"
             f"📧 البريد الإلكتروني: {email}\n"
             f"📱 رقم الجوال: {context.user_data['registration_data'].get('phone', '')}\n"
             f"🏫 الصف الدراسي: {context.user_data['registration_data'].get('grade', '')}\n\n"
             "الرجاء اختيار المعلومات التي ترغب في تعديلها:",
        reply_markup=keyboard
    )
    logger.info(f"[DEBUG] handle_edit_email: Showing edit info menu, returning state EDIT_USER_INFO_MENU ({EDIT_USER_INFO_MENU})")
    return EDIT_USER_INFO_MENU

# معالجة تعديل رقم الجوال
async def handle_edit_phone(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل رقم الجوال"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    phone = update.message.text.strip()
    db_manager = context.bot_data.get("DB_MANAGER") # جلب db_manager هنا
    
    # تسجيل معلومات التصحيح
    logger.info(f"[DEBUG] Entering handle_edit_phone for user {user.id}")
    logger.debug(f"[DEBUG] Received phone from user {user.id}: {phone}")
    
    # التحقق من صحة رقم الجوال
    if not is_valid_phone(phone):
        logger.warning(f"[DEBUG] Invalid phone received from user {user.id}: {phone}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ رقم الجوال غير صحيح. يرجى إدخال رقم جوال سعودي صحيح (يبدأ بـ 05 أو +966 أو 00966):"
        )
        logger.info(f"[DEBUG] handle_edit_phone: Asking for phone again, returning state EDIT_USER_PHONE ({EDIT_USER_PHONE})")
        return EDIT_USER_PHONE
    
    # حفظ رقم الجوال في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['phone'] = phone
    logger.info(f"[DEBUG] Saved phone '{phone}' for user {user.id} in context.user_data")

    if not db_manager: # التحقق من db_manager
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_phone للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_phone: DB_MANAGER not found, returning state END ({END})")
        return ConversationHandler.END
    
    # حفظ المعلومات في قاعدة البيانات
    success = save_user_info(
        db_manager,
        user.id,
        phone=phone
    )
    
    if not success:
        logger.error(f"فشل حفظ رقم جوال المستخدم {user.id} في قاعدة البيانات")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في حفظ المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_phone: Failed to save user phone, returning state END ({END})")
        return ConversationHandler.END
    
    # إرسال رسالة تأكيد
    await safe_send_message(
        context.bot,
        chat_id,
        text="✅ تم تعديل رقم الجوال بنجاح!"
    )
    
    # عرض قائمة تعديل المعلومات
    keyboard = create_edit_info_keyboard()
    await safe_send_message(
        context.bot,
        chat_id,
        text="✏️ تعديل المعلومات الشخصية\n\n"
             f"👤 الاسم: {context.user_data['registration_data'].get('full_name', '')}\n"
             f"📧 البريد الإلكتروني: {context.user_data['registration_data'].get('email', '')}\n"
             f"📱 رقم الجوال: {phone}\n"
             f"🏫 الصف الدراسي: {context.user_data['registration_data'].get('grade', '')}\n\n"
             "الرجاء اختيار المعلومات التي ترغب في تعديلها:",
        reply_markup=keyboard
    )
    logger.info(f"[DEBUG] handle_edit_phone: Showing edit info menu, returning state EDIT_USER_INFO_MENU ({EDIT_USER_INFO_MENU})")
    return EDIT_USER_INFO_MENU

# معالجة تعديل الصف الدراسي
async def handle_edit_grade(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل الصف الدراسي"""
    query = update.callback_query
    user = update.effective_user
    chat_id = query.message.chat_id
    grade = query.data.replace("grade_", "") # استخراج الصف الدراسي
    db_manager = context.bot_data.get("DB_MANAGER") # جلب db_manager هنا
    
    # تسجيل معلومات التصحيح
    logger.info(f"[DEBUG] Entering handle_edit_grade for user {user.id}")
    logger.debug(f"[DEBUG] Received grade selection from user {user.id}: {query.data}")
    
    # التحقق من صحة البيانات
    if not query.data.startswith("grade_"):
        logger.warning(f"[DEBUG] Invalid grade selection received from user {user.id}: {query.data}")
        await query.answer("خيار غير صحيح")
        logger.info(f"[DEBUG] handle_edit_grade: Asking for grade again, returning state EDIT_USER_GRADE ({EDIT_USER_GRADE})")
        return EDIT_USER_GRADE
    
    # حفظ الصف الدراسي في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['grade'] = grade
    logger.info(f"[DEBUG] Saved grade '{grade}' for user {user.id} in context.user_data")
    
    # إرسال رسالة تأكيد
    await query.answer("تم اختيار الصف الدراسي")
    
    if not db_manager: # التحقق من db_manager
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_grade للمستخدم {user.id}")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_grade: DB_MANAGER not found, returning state END ({END})")
        return ConversationHandler.END
    
    # حفظ المعلومات في قاعدة البيانات
    success = save_user_info(
        db_manager,
        user.id,
        grade=grade
    )
    
    if not success:
        logger.error(f"فشل حفظ صف المستخدم {user.id} في قاعدة البيانات")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="⚠️ حدث خطأ في حفظ المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_grade: Failed to save user grade, returning state END ({END})")
        return ConversationHandler.END
    
    # إرسال رسالة تأكيد
    await safe_edit_message_text(
        context.bot,
        chat_id,
        query.message.message_id,
        text="✅ تم تعديل الصف الدراسي بنجاح!"
    )
    
    # عرض قائمة تعديل المعلومات
    keyboard = create_edit_info_keyboard()
    await safe_send_message(
        context.bot,
        chat_id,
        text="✏️ تعديل المعلومات الشخصية\n\n"
             f"👤 الاسم: {context.user_data['registration_data'].get('full_name', '')}\n"
             f"📧 البريد الإلكتروني: {context.user_data['registration_data'].get('email', '')}\n"
             f"📱 رقم الجوال: {context.user_data['registration_data'].get('phone', '')}\n"
             f"🏫 الصف الدراسي: {grade}\n\n"
             "الرجاء اختيار المعلومات التي ترغب في تعديلها:",
        reply_markup=keyboard
    )
    logger.info(f"[DEBUG] handle_edit_grade: Showing edit info menu, returning state EDIT_USER_INFO_MENU ({EDIT_USER_INFO_MENU})")
    return EDIT_USER_INFO_MENU

# إنشاء معالج محادثة التسجيل
registration_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('register', start_registration)], # عادةً ما يتم استدعاء start_registration من start_command
    states={
        REGISTRATION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name_input)],
        REGISTRATION_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_input)],
        REGISTRATION_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone_input)],
        REGISTRATION_GRADE: [CallbackQueryHandler(handle_grade_selection, pattern=r'^grade_')],
        REGISTRATION_CONFIRM: [CallbackQueryHandler(handle_confirmation, pattern=r'^(confirm_registration|edit_name|edit_email|edit_phone|edit_grade)$')],
    },
    fallbacks=[CommandHandler('cancel', lambda update, context: ConversationHandler.END)], # يجب توفير دالة إلغاء مناسبة
    name="registration_conversation",
    persistent=False
)

# إنشاء معالج محادثة تعديل المعلومات
edit_info_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('edit_info', edit_info_command),
        CallbackQueryHandler(handle_edit_info_menu, pattern=r'^edit_my_info$') # تم تعديل النمط ليشمل edit_my_info
    ],
    states={
        EDIT_USER_INFO_MENU: [CallbackQueryHandler(handle_edit_info_menu, pattern=r'^(edit_name|edit_email|edit_phone|edit_grade|main_menu)$')],
        EDIT_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_name)],
        EDIT_USER_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_email)],
        EDIT_USER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_phone)],
        EDIT_USER_GRADE: [CallbackQueryHandler(handle_edit_grade, pattern=r'^grade_')],
    },
    fallbacks=[CommandHandler('cancel', lambda update, context: ConversationHandler.END)], # يجب توفير دالة إلغاء مناسبة
    name="edit_info_conversation",
    persistent=False
)

# إنشاء معالج أمر /start
start_handler = CommandHandler('start', start_command)

