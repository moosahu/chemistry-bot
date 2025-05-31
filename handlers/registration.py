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

# استيراد وحدة إشعارات التسجيل
from handlers.admin_tools.registration_notification import notify_admin_on_registration

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

# تعريف ثوابت الحالات
try:
    from config import (
        MAIN_MENU,
        END
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
            from database.db_setup import users_table
            
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

# دالة معالجة أمر /start
async def start_command(update: Update, context: CallbackContext) -> None:
    """معالجة أمر /start بشكل منفصل عن محادثة التسجيل"""
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في start_command للمستخدم {user_id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return
    
    # التحقق من حالة تسجيل المستخدم
    user_info = get_user_info(db_manager, user_id)
    
    # التحقق من وجود المعلومات الأساسية وصحتها
    has_basic_info = False
    if user_info:
        # التحقق من أن جميع المعلومات الأساسية موجودة وصحيحة
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
        
        has_basic_info = all([has_full_name, has_email, has_phone, has_grade])
        
        logger.info(f"المستخدم {user_id} لديه معلومات أساسية صحيحة: {has_basic_info}")
    
    # إذا كان المستخدم مسجلاً (لديه جميع المعلومات الأساسية)، عرض القائمة الرئيسية
    if has_basic_info:
        logger.info(f"المستخدم {user_id} مسجل بالفعل، عرض القائمة الرئيسية")
        from handlers.common import main_menu_callback
        await main_menu_callback(update, context)
    else:
        # إذا لم يكن المستخدم مسجلاً، بدء عملية التسجيل
        logger.info(f"المستخدم {user_id} غير مسجل، بدء عملية التسجيل")
        await start_registration(update, context)

async def check_registration_status(update: Update, context: CallbackContext, db_manager=None):
    """
    التحقق من حالة تسجيل المستخدم وتوجيهه لإكمال التسجيل إذا لم يكن مسجلاً
    
    يعيد:
        bool: True إذا كان المستخدم مسجلاً، False إذا كان يحتاج للتسجيل
    """
    user = update.effective_user
    user_id = user.id
    
    # الحصول على مدير قاعدة البيانات من context أو استخدام المعطى
    if not db_manager:
        db_manager = context.bot_data.get("DB_MANAGER")
        if not db_manager:
            logger.error(f"لا يمكن الوصول إلى DB_MANAGER في check_registration_status للمستخدم {user_id}")
            # تغيير هنا: لا نفترض أن المستخدم مسجل في حالة عدم وجود مدير قاعدة بيانات
            # بدلاً من ذلك، نطلب منه التسجيل
            await start_registration(update, context)
            return False
    
    # التحقق من حالة تسجيل المستخدم
    user_info = get_user_info(db_manager, user_id)
    
    # طباعة معلومات التسجيل للتشخيص
    logger.info(f"التحقق من حالة تسجيل المستخدم {user_id}")
    
    # التحقق من وجود المعلومات الأساسية وصحتها
    has_basic_info = False
    if user_info:
        logger.info(f"معلومات المستخدم {user_id}: is_registered = {user_info.get('is_registered')}, نوع: {type(user_info.get('is_registered'))}")
        
        # التحقق من أن جميع المعلومات الأساسية موجودة وصحيحة
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
        
        has_basic_info = all([has_full_name, has_email, has_phone, has_grade])
        
        logger.info(f"المستخدم {user_id} لديه معلومات أساسية صحيحة: {has_basic_info}")
        logger.info(f"تفاصيل: الاسم: {has_full_name} ({full_name}), البريد: {has_email} ({email}), الجوال: {has_phone} ({phone}), الصف: {has_grade} ({grade})")
        
        # إذا كان لديه معلومات أساسية ولكن is_registered ليست True، نقوم بتحديثها
        if has_basic_info and not user_info.get('is_registered'):
            logger.info(f"تحديث حالة التسجيل للمستخدم {user_id} لأن لديه معلومات أساسية")
            save_user_info(db_manager, user_id, is_registered=True)
            # إعادة استرجاع المعلومات بعد التحديث
            user_info = get_user_info(db_manager, user_id)
    else:
        logger.info(f"لم يتم العثور على معلومات للمستخدم {user_id}")
    
    # التحقق من حالة التسجيل بشكل أكثر دقة
    is_registered = False
    
    # تغيير هنا: نتحقق أولاً من وجود المعلومات الأساسية
    if has_basic_info:
        # إذا كانت جميع المعلومات الأساسية موجودة، نعتبر المستخدم مسجلاً
        is_registered = True
        logger.info(f"اعتبار المستخدم {user_id} مسجلاً لأن لديه جميع المعلومات الأساسية")
    elif user_info:
        # إذا كانت المعلومات الأساسية غير مكتملة، نتحقق من قيمة is_registered
        reg_value = user_info.get('is_registered')
        if reg_value is not None:
            # تحويل القيمة إلى منطقية بشكل صريح
            if isinstance(reg_value, bool):
                is_registered = reg_value
            elif isinstance(reg_value, str):
                is_registered = reg_value.lower() in ('true', 't', 'yes', 'y', '1')
            elif isinstance(reg_value, int):
                is_registered = reg_value > 0
            else:
                is_registered = bool(reg_value)
    
    logger.info(f"نتيجة التحقق من تسجيل المستخدم {user_id}: {is_registered}")
    
    # إذا لم يكن هناك معلومات للمستخدم أو لم يكمل التسجيل
    if not is_registered:
        logger.info(f"المستخدم {user_id} غير مسجل، توجيهه لإكمال التسجيل")
        await start_registration(update, context)
        return False
    else:
        logger.info(f"المستخدم {user_id} مسجل بالفعل")
        return True

# بدء عملية التسجيل
async def start_registration(update: Update, context: CallbackContext) -> int:
    """بدء محادثة التسجيل الإلزامي"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # إرسال رسالة ترحيبية وبدء جمع المعلومات
    await safe_send_message(
        context.bot,
        chat_id,
        text="👋 مرحباً بك في بوت الاختبارات!\n\n"
             "للاستفادة من جميع ميزات البوت، يرجى إكمال عملية التسجيل أولاً.\n\n"
             "الخطوة الأولى: أدخل اسمك الكامل:"
    )
    
    # تهيئة بيانات التسجيل المؤقتة
    context.user_data['registration_data'] = {}
    
    return REGISTRATION_NAME

# معالجة إدخال الاسم
async def handle_name_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال الاسم من المستخدم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    name = update.message.text.strip()
    
    # التحقق من صحة الاسم
    if len(name) < 3:
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ الاسم قصير جداً. يرجى إدخال اسمك الكامل (3 أحرف على الأقل):"
        )
        return REGISTRATION_NAME
    
    # حفظ الاسم في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['full_name'] = name
    
    # طلب البريد الإلكتروني
    await safe_send_message(
        context.bot,
        chat_id,
        text="الخطوة الثانية: أدخل بريدك الإلكتروني:"
    )
    return REGISTRATION_EMAIL

# معالجة إدخال البريد الإلكتروني
async def handle_email_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال البريد الإلكتروني من المستخدم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    email = update.message.text.strip()
    
    # التحقق من صحة البريد الإلكتروني
    if not is_valid_email(email):
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ البريد الإلكتروني غير صحيح. يرجى إدخال بريد إلكتروني صالح:"
        )
        return REGISTRATION_EMAIL
    
    # حفظ البريد الإلكتروني في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['email'] = email
    
    # طلب رقم الجوال
    await safe_send_message(
        context.bot,
        chat_id,
        text="الخطوة الثالثة: أدخل رقم جوالك (مثال: 05xxxxxxxx):"
    )
    return REGISTRATION_PHONE

# معالجة إدخال رقم الجوال
async def handle_phone_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال رقم الجوال من المستخدم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    phone = update.message.text.strip()
    
    # التحقق من صحة رقم الجوال
    if not is_valid_phone(phone):
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ رقم الجوال غير صحيح. يرجى إدخال رقم جوال سعودي صالح (يبدأ بـ 05 أو +966 أو 00966):"
        )
        return REGISTRATION_PHONE
    
    # حفظ رقم الجوال في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['phone'] = phone
    
    # إرسال رسالة إعلامية
    await safe_send_message(
        context.bot,
        chat_id,
        text="تم التحقق من رقم الجوال بنجاح! ✅"
    )
    
    # طلب اختيار الصف الدراسي
    await safe_send_message(
        context.bot,
        chat_id,
        text="الخطوة الرابعة: اختر الصف الدراسي:",
        reply_markup=create_grade_keyboard()
    )
    return REGISTRATION_GRADE

# معالجة اختيار الصف الدراسي
async def handle_grade_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار الصف الدراسي من المستخدم"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    # استخراج الصف الدراسي من callback_data
    grade_data = query.data
    
    # تحديد نص الصف الدراسي بناءً على callback_data
    if grade_data == "grade_university":
        grade_text = "طالب جامعي"
    elif grade_data == "grade_teacher":
        grade_text = "معلم"
    elif grade_data == "grade_other":
        grade_text = "أخرى"
    elif grade_data.startswith("grade_secondary_"):
        grade_num = grade_data.split("_")[-1]
        grade_text = f"ثانوي {grade_num}"
    else:
        grade_text = "غير محدد"
    
    # حفظ الصف الدراسي في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['grade'] = grade_text
    
    # إعداد نص تأكيد المعلومات
    user_data = context.user_data['registration_data']
    confirmation_text = "مراجعة المعلومات:\n\n" \
                        f"الاسم: {user_data.get('full_name')}\n" \
                        f"البريد الإلكتروني: {user_data.get('email')}\n" \
                        f"رقم الجوال: {user_data.get('phone')}\n" \
                        f"الصف الدراسي: {grade_text}\n\n" \
                        "هل المعلومات صحيحة؟"
    
    # إرسال رسالة تأكيد المعلومات
    await query.answer()
    await safe_edit_message_text(
        context.bot,
        chat_id,
        query.message.message_id,
        text=confirmation_text,
        reply_markup=create_confirmation_keyboard()
    )
    return REGISTRATION_CONFIRM

# معالجة تأكيد التسجيل
async def handle_registration_confirmation(update: Update, context: CallbackContext) -> int:
    """معالجة تأكيد معلومات التسجيل من المستخدم"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    user_id = user.id
    
    # استخراج نوع التأكيد من callback_data
    confirmation_type = query.data
    
    if confirmation_type == "confirm_registration":
        # الحصول على مدير قاعدة البيانات
        db_manager = context.bot_data.get("DB_MANAGER")
        if not db_manager:
            logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_registration_confirmation للمستخدم {user_id}")
            await query.answer("حدث خطأ في الوصول إلى قاعدة البيانات")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
            )
            return ConversationHandler.END
        
        # حفظ معلومات التسجيل
        user_data = context.user_data['registration_data']
        success = save_user_info(
            db_manager,
            user_id,
            full_name=user_data.get('full_name'),
            email=user_data.get('email'),
            phone=user_data.get('phone'),
            grade=user_data.get('grade'),
            is_registered=True
        )
        
        if success:
            # إرسال إشعار للمدير عن المستخدم الجديد
            try:
                await notify_admin_on_registration(user_id, user_data, context)
                logger.info(f"تم طلب إرسال إشعار للمدير عن المستخدم الجديد {user_id}")
            except Exception as e:
                logger.error(f"خطأ في طلب إرسال إشعار للمدير عن المستخدم الجديد {user_id}: {e}")
            
            # إرسال رسالة نجاح التسجيل
            await query.answer("تم التسجيل بنجاح!")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="✅ تم تسجيلك بنجاح!\n\n"
                     "يمكنك الآن استخدام جميع ميزات البوت. اختر من القائمة أدناه:"
            )
            
            # عرض القائمة الرئيسية
            from handlers.common import main_menu_callback
            await main_menu_callback(update, context)
            return MAIN_MENU
        else:
            # إرسال رسالة فشل التسجيل
            await query.answer("حدث خطأ في التسجيل")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="⚠️ حدث خطأ في حفظ معلومات التسجيل. يرجى المحاولة مرة أخرى لاحقاً."
            )
            return ConversationHandler.END
    elif confirmation_type.startswith("edit_"):
        # استخراج نوع التعديل من callback_data
        edit_type = confirmation_type.replace("edit_", "")
        
        # توجيه المستخدم لتعديل المعلومات المطلوبة
        if edit_type == "name":
            await query.answer("تعديل الاسم")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="أدخل اسمك الكامل الجديد:"
            )
            return REGISTRATION_NAME
        elif edit_type == "email":
            await query.answer("تعديل البريد الإلكتروني")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="أدخل بريدك الإلكتروني الجديد:"
            )
            return REGISTRATION_EMAIL
        elif edit_type == "phone":
            await query.answer("تعديل رقم الجوال")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="أدخل رقم جوالك الجديد (مثال: 05xxxxxxxx):"
            )
            return REGISTRATION_PHONE
        elif edit_type == "grade":
            await query.answer("تعديل الصف الدراسي")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="اختر الصف الدراسي الجديد:",
                reply_markup=create_grade_keyboard()
            )
            return REGISTRATION_GRADE
    
    # في حالة عدم التعرف على نوع التأكيد
    await query.answer()
    return REGISTRATION_CONFIRM

# معالجة طلب تعديل المعلومات
async def handle_edit_info_request(update: Update, context: CallbackContext) -> int:
    """معالجة طلب تعديل معلومات المستخدم"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    user_id = user.id
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_info_request للمستخدم {user_id}")
        await query.answer("حدث خطأ في الوصول إلى قاعدة البيانات")
        return ConversationHandler.END
    
    # الحصول على معلومات المستخدم
    user_info = get_user_info(db_manager, user_id)
    if not user_info:
        logger.error(f"لم يتم العثور على معلومات للمستخدم {user_id} في handle_edit_info_request")
        await query.answer("لم يتم العثور على معلوماتك")
        return ConversationHandler.END
    
    # حفظ معلومات المستخدم في context للاستخدام لاحقاً
    context.user_data['registration_data'] = {
        'user_id': user_id,
        'full_name': user_info.get('full_name'),
        'email': user_info.get('email'),
        'phone': user_info.get('phone'),
        'grade': user_info.get('grade')
    }
    
    # إعداد نص معلومات المستخدم
    info_text = "معلوماتك الحالية:\n\n" \
                f"الاسم: {user_info.get('full_name')}\n" \
                f"البريد الإلكتروني: {user_info.get('email')}\n" \
                f"رقم الجوال: {user_info.get('phone')}\n" \
                f"الصف الدراسي: {user_info.get('grade')}\n\n" \
                "اختر المعلومات التي ترغب في تعديلها:"
    
    # إرسال رسالة تعديل المعلومات
    await query.answer()
    await safe_edit_message_text(
        context.bot,
        chat_id,
        query.message.message_id,
        text=info_text,
        reply_markup=create_edit_info_keyboard()
    )
    return EDIT_USER_INFO_MENU

# معالجة اختيار نوع التعديل
async def handle_edit_info_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار نوع تعديل المعلومات"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    # استخراج نوع التعديل من callback_data
    field = query.data.replace("edit_", "")
    
    if field == "name":
        # تعديل الاسم
        await query.answer("تعديل الاسم")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="أدخل اسمك الكامل الجديد:"
        )
        return EDIT_USER_NAME
    elif field == "email":
        # تعديل البريد الإلكتروني
        await query.answer("تعديل البريد الإلكتروني")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="أدخل بريدك الإلكتروني الجديد:"
        )
        return EDIT_USER_EMAIL
    elif field == "phone":
        # تعديل رقم الجوال
        await query.answer("تعديل رقم الجوال")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="أدخل رقم جوالك الجديد (مثال: 05xxxxxxxx):"
        )
        return EDIT_USER_PHONE
    elif field == "grade":
        # تعديل الصف الدراسي
        await query.answer("تعديل الصف الدراسي")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى اختيار الصف الدراسي الجديد:",
            reply_markup=create_grade_keyboard()
        )
        return EDIT_USER_GRADE
    elif field == "main_menu":
        # العودة إلى القائمة الرئيسية
        from handlers.common import main_menu_callback
        await main_menu_callback(update, context)
        return ConversationHandler.END
    else:
        # إذا لم يتم التعرف على نوع التعديل، نعود إلى قائمة تعديل المعلومات
        user_info = context.user_data.get('registration_data', {})
        info_text = "معلوماتك الحالية:\n\n" \
                    f"الاسم: {user_info.get('full_name')}\n" \
                    f"البريد الإلكتروني: {user_info.get('email')}\n" \
                    f"رقم الجوال: {user_info.get('phone')}\n" \
                    f"الصف الدراسي: {user_info.get('grade')}\n\n" \
                    "اختر المعلومات التي ترغب في تعديلها:"
        
        await query.answer("خيار غير صالح")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
        )
        return EDIT_USER_INFO_MENU

# معالجة إدخال الاسم الجديد
async def handle_edit_name_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال الاسم الجديد"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id
    name = update.message.text.strip()
    
    # التحقق من صحة الاسم
    if len(name) < 3:
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ الاسم قصير جداً. يرجى إدخال اسمك الكامل (3 أحرف على الأقل):"
        )
        return EDIT_USER_NAME
    
    # تحديث الاسم في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['full_name'] = name
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_name_input للمستخدم {user_id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # حفظ الاسم الجديد في قاعدة البيانات
    success = save_user_info(db_manager, user_id, full_name=name)
    
    if success:
        # إعداد نص معلومات المستخدم المحدثة
        user_info = context.user_data.get('registration_data', {})
        info_text = "تم تحديث الاسم بنجاح! ✅\n\n" \
                    "معلوماتك الحالية:\n\n" \
                    f"الاسم: {user_info.get('full_name')}\n" \
                    f"البريد الإلكتروني: {user_info.get('email')}\n" \
                    f"رقم الجوال: {user_info.get('phone')}\n" \
                    f"الصف الدراسي: {user_info.get('grade')}\n\n" \
                    "هل ترغب في تعديل معلومات أخرى؟"
        
        # إرسال رسالة نجاح التحديث
        await safe_send_message(
            context.bot,
            chat_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
        )
        return EDIT_USER_INFO_MENU
    else:
        # إرسال رسالة فشل التحديث
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في تحديث الاسم. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END

# معالجة إدخال البريد الإلكتروني الجديد
async def handle_edit_email_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال البريد الإلكتروني الجديد"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id
    email = update.message.text.strip()
    
    # التحقق من صحة البريد الإلكتروني
    if not is_valid_email(email):
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ البريد الإلكتروني غير صحيح. يرجى إدخال بريد إلكتروني صالح:"
        )
        return EDIT_USER_EMAIL
    
    # تحديث البريد الإلكتروني في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['email'] = email
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_email_input للمستخدم {user_id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # حفظ البريد الإلكتروني الجديد في قاعدة البيانات
    success = save_user_info(db_manager, user_id, email=email)
    
    if success:
        # إعداد نص معلومات المستخدم المحدثة
        user_info = context.user_data.get('registration_data', {})
        info_text = "تم تحديث البريد الإلكتروني بنجاح! ✅\n\n" \
                    "معلوماتك الحالية:\n\n" \
                    f"الاسم: {user_info.get('full_name')}\n" \
                    f"البريد الإلكتروني: {user_info.get('email')}\n" \
                    f"رقم الجوال: {user_info.get('phone')}\n" \
                    f"الصف الدراسي: {user_info.get('grade')}\n\n" \
                    "هل ترغب في تعديل معلومات أخرى؟"
        
        # إرسال رسالة نجاح التحديث
        await safe_send_message(
            context.bot,
            chat_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
        )
        return EDIT_USER_INFO_MENU
    else:
        # إرسال رسالة فشل التحديث
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في تحديث البريد الإلكتروني. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END

# معالجة إدخال رقم الجوال الجديد
async def handle_edit_phone_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال رقم الجوال الجديد"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id
    phone = update.message.text.strip()
    
    # التحقق من صحة رقم الجوال
    if not is_valid_phone(phone):
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ رقم الجوال غير صحيح. يرجى إدخال رقم جوال سعودي صالح (يبدأ بـ 05 أو +966 أو 00966):"
        )
        return EDIT_USER_PHONE
    
    # تحديث رقم الجوال في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['phone'] = phone
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_phone_input للمستخدم {user_id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # حفظ رقم الجوال الجديد في قاعدة البيانات
    success = save_user_info(db_manager, user_id, phone=phone)
    
    if success:
        # إعداد نص معلومات المستخدم المحدثة
        user_info = context.user_data.get('registration_data', {})
        info_text = "تم تحديث رقم الجوال بنجاح! ✅\n\n" \
                    "معلوماتك الحالية:\n\n" \
                    f"الاسم: {user_info.get('full_name')}\n" \
                    f"البريد الإلكتروني: {user_info.get('email')}\n" \
                    f"رقم الجوال: {user_info.get('phone')}\n" \
                    f"الصف الدراسي: {user_info.get('grade')}\n\n" \
                    "هل ترغب في تعديل معلومات أخرى؟"
        
        # إرسال رسالة نجاح التحديث
        await safe_send_message(
            context.bot,
            chat_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
        )
        return EDIT_USER_INFO_MENU
    else:
        # إرسال رسالة فشل التحديث
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في تحديث رقم الجوال. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END

# معالجة اختيار الصف الدراسي الجديد
async def handle_edit_grade_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار الصف الدراسي الجديد"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    user_id = user.id
    
    # استخراج الصف الدراسي من callback_data
    grade_data = query.data
    
    # تحديد نص الصف الدراسي بناءً على callback_data
    if grade_data == "grade_university":
        grade_text = "طالب جامعي"
    elif grade_data == "grade_teacher":
        grade_text = "معلم"
    elif grade_data == "grade_other":
        grade_text = "أخرى"
    elif grade_data.startswith("grade_secondary_"):
        grade_num = grade_data.split("_")[-1]
        grade_text = f"ثانوي {grade_num}"
    else:
        grade_text = "غير محدد"
    
    # تحديث الصف الدراسي في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['grade'] = grade_text
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_grade_selection للمستخدم {user_id}")
        await query.answer("حدث خطأ في الوصول إلى قاعدة البيانات")
        return ConversationHandler.END
    
    # حفظ الصف الدراسي الجديد في قاعدة البيانات
    success = save_user_info(db_manager, user_id, grade=grade_text)
    
    if success:
        # إعداد نص معلومات المستخدم المحدثة
        user_info = context.user_data.get('registration_data', {})
        info_text = "تم تحديث الصف الدراسي بنجاح! ✅\n\n" \
                    "معلوماتك الحالية:\n\n" \
                    f"الاسم: {user_info.get('full_name')}\n" \
                    f"البريد الإلكتروني: {user_info.get('email')}\n" \
                    f"رقم الجوال: {user_info.get('phone')}\n" \
                    f"الصف الدراسي: {user_info.get('grade')}\n\n" \
                    "هل ترغب في تعديل معلومات أخرى؟"
        
        # إرسال رسالة نجاح التحديث
        await query.answer("تم تحديث الصف الدراسي")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
        )
        return EDIT_USER_INFO_MENU
    else:
        # إرسال رسالة فشل التحديث
        await query.answer("حدث خطأ في تحديث الصف الدراسي")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="⚠️ حدث خطأ في تحديث الصف الدراسي. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END

# معالجة إلغاء التسجيل أو التعديل
async def cancel_registration(update: Update, context: CallbackContext) -> int:
    """إلغاء عملية التسجيل أو التعديل"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    await safe_send_message(
        context.bot,
        chat_id,
        text="تم إلغاء العملية."
    )
    
    # مسح بيانات التسجيل المؤقتة
    if 'registration_data' in context.user_data:
        del context.user_data['registration_data']
    
    # العودة إلى القائمة الرئيسية
    from handlers.common import main_menu_callback
    await main_menu_callback(update, context)
    return ConversationHandler.END

# معالجة الرسائل غير المتوقعة
async def unexpected_message(update: Update, context: CallbackContext) -> None:
    """معالجة الرسائل غير المتوقعة أثناء التسجيل"""
    chat_id = update.effective_chat.id
    await safe_send_message(
        context.bot,
        chat_id,
        text="رسالة غير متوقعة. يرجى اتباع التعليمات أو استخدام الأزرار."
    )

# إنشاء معالج محادثة التسجيل
registration_handler = ConversationHandler(
    entry_points=[CommandHandler("register", start_registration)],
    states={
        REGISTRATION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name_input)],
        REGISTRATION_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_input)],
        REGISTRATION_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone_input)],
        REGISTRATION_GRADE: [CallbackQueryHandler(handle_grade_selection, pattern="^grade_")],
        REGISTRATION_CONFIRM: [CallbackQueryHandler(handle_registration_confirmation, pattern="^(confirm_registration|edit_)")]
    },
    fallbacks=[
        CommandHandler("cancel", cancel_registration),
        MessageHandler(filters.COMMAND, unexpected_message),
        MessageHandler(filters.TEXT, unexpected_message)
    ],
    map_to_parent={
        # العودة إلى القائمة الرئيسية
        MAIN_MENU: MAIN_MENU,
        # إنهاء المحادثة
        END: END
    }
)

# إنشاء alias للتوافق مع الكود القديم
registration_conv_handler = registration_handler

# معالج أمر تعديل المعلومات
edit_info_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(handle_edit_info_request, pattern=r'^edit_my_info$')],
    states={
        EDIT_USER_INFO_MENU: [CallbackQueryHandler(handle_edit_info_selection, pattern=r'^(edit_\w+|main_menu)$')],
        EDIT_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_name_input)],
        EDIT_USER_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_email_input)],
        EDIT_USER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_phone_input)],
        EDIT_USER_GRADE: [CallbackQueryHandler(handle_edit_grade_selection, pattern=r'^grade_')]
    },
    fallbacks=[
        CommandHandler("cancel", cancel_registration),
        MessageHandler(filters.COMMAND, unexpected_message),
        MessageHandler(filters.TEXT, unexpected_message)
    ],
    map_to_parent={
        # العودة إلى القائمة الرئيسية
        MAIN_MENU: MAIN_MENU,
        # إنهاء المحادثة
        END: END
    }
)

# دالة إعداد المعالجات
def setup_registration_handlers(application: Application):
    """إعداد معالجات التسجيل وتعديل المعلومات"""
    # تسجيل أمر /start بشكل منفصل
    application.add_handler(CommandHandler("start", start_command))
    
    # تسجيل محادثة تعديل المعلومات أولاً (مهم جداً للأولوية)
    application.add_handler(edit_info_handler)
    
    # تسجيل محادثة التسجيل بعد محادثة تعديل المعلومات
    application.add_handler(registration_handler)
    
    logger.info("تم إعداد معالجات التسجيل وتعديل المعلومات")
