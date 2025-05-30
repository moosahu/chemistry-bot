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
    filters
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
    
    return True

async def start_registration(update: Update, context: CallbackContext) -> int:
    """بدء عملية التسجيل الإلزامي للمستخدم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    welcome_text = f"مرحباً {user.first_name}! 👋\n\n" \
                  "لاستخدام بوت الاختبارات، يرجى إكمال التسجيل أولاً.\n" \
                  "الخطوة الأولى: أدخل اسمك الكامل:"
    
    # حفظ بعض معلومات المستخدم الأساسية في user_data
    context.user_data['registration_data'] = {
        'user_id': user.id,
        'username': user.username,
        'telegram_first_name': user.first_name,
        'telegram_last_name': user.last_name
    }
    
    await safe_send_message(context.bot, chat_id, text=welcome_text)
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
            text="الاسم قصير جداً. يرجى إدخال اسمك الكامل (3 أحرف على الأقل):"
        )
        return REGISTRATION_NAME
    
    # حفظ الاسم في بيانات المستخدم المؤقتة
    if 'registration_data' not in context.user_data:
        context.user_data['registration_data'] = {}
    
    context.user_data['registration_data']['full_name'] = name
    
    # طلب البريد الإلكتروني
    await safe_send_message(
        context.bot,
        chat_id,
        text=f"شكراً {name}! 👍\n\n"
             "الخطوة التالية: أدخل بريدك الإلكتروني:"
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
            text="البريد الإلكتروني غير صحيح. يرجى إدخال بريد إلكتروني صالح:"
        )
        return REGISTRATION_EMAIL
    
    # حفظ البريد الإلكتروني في بيانات المستخدم المؤقتة
    if 'registration_data' not in context.user_data:
        context.user_data['registration_data'] = {}
    
    context.user_data['registration_data']['email'] = email
    
    # طلب رقم الجوال
    await safe_send_message(
        context.bot,
        chat_id,
        text="تم تسجيل البريد الإلكتروني! ✅\n\n"
             "الخطوة التالية: أدخل رقم جوالك (مثال: 05xxxxxxxx أو +966xxxxxxxxx):"
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
            text="رقم الجوال غير صحيح. يرجى إدخال رقم جوال سعودي صالح (يبدأ بـ 05 أو +966 أو 00966):"
        )
        return REGISTRATION_PHONE
    
    # حفظ رقم الجوال في بيانات المستخدم المؤقتة
    if 'registration_data' not in context.user_data:
        context.user_data['registration_data'] = {}
    
    context.user_data['registration_data']['phone'] = phone
    
    # الانتقال مباشرة إلى اختيار الصف الدراسي
    await safe_send_message(
        context.bot,
        chat_id,
        text="تم تسجيل رقم الجوال! ✅\n\n"
             "الخطوة الأخيرة: اختر الصف الدراسي:",
        reply_markup=create_grade_keyboard()
    )
    
    return REGISTRATION_GRADE

# معالجة اختيار الصف الدراسي
async def handle_grade_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار الصف الدراسي من المستخدم"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    try:
        # استخراج الصف الدراسي من callback_data
        grade_data = query.data
        
        if grade_data.startswith("grade_secondary_"):
            grade_number = grade_data.split("_")[-1]
            grade = f"ثانوي {grade_number}"
        elif grade_data == "grade_university":
            grade = "طالب جامعي"
        elif grade_data == "grade_teacher":
            grade = "معلم"
        elif grade_data == "grade_other":
            grade = "أخرى"
        else:
            # إذا لم يتم التعرف على الصف، نطلب من المستخدم الاختيار مرة أخرى
            await query.answer("خيار غير صالح. يرجى اختيار صف دراسي من القائمة.")
            return REGISTRATION_GRADE
        
        # حفظ الصف الدراسي في بيانات المستخدم المؤقتة
        if 'registration_data' not in context.user_data:
            context.user_data['registration_data'] = {}
        
        context.user_data['registration_data']['grade'] = grade
        
        # عرض ملخص المعلومات للتأكيد
        registration_data = context.user_data['registration_data']
        summary_text = "مراجعة معلومات التسجيل:\n\n" \
                      f"الاسم: {registration_data.get('full_name')}\n" \
                      f"البريد الإلكتروني: {registration_data.get('email')}\n" \
                      f"رقم الجوال: {registration_data.get('phone')}\n" \
                      f"الصف الدراسي: {grade}\n\n" \
                      "هل المعلومات صحيحة؟ يمكنك تأكيد المعلومات أو تعديلها."
        
        # إنشاء لوحة مفاتيح للتأكيد أو التعديل
        keyboard = create_confirmation_keyboard()
        
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=summary_text,
            reply_markup=keyboard
        )
        
        return REGISTRATION_CONFIRM
    except Exception as e:
        logger.error(f"خطأ في معالجة اختيار الصف الدراسي: {e}")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="حدث خطأ في اختيار الصف الدراسي. يرجى المحاولة مرة أخرى:",
            reply_markup=create_grade_keyboard()
        )
        return REGISTRATION_GRADE

# معالجة تأكيد التسجيل
async def handle_registration_confirmation(update: Update, context: CallbackContext) -> int:
    """معالجة تأكيد معلومات التسجيل"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    # التحقق من وجود بيانات التسجيل
    if 'registration_data' not in context.user_data:
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="⚠️ حدث خطأ في عملية التسجيل. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # الحصول على بيانات التسجيل
    registration_data = context.user_data['registration_data']
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_registration_confirmation للمستخدم {user.id}")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="⚠️ حدث خطأ في حفظ معلومات التسجيل. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    try:
        # حفظ معلومات التسجيل في قاعدة البيانات
        success = save_user_info(
            db_manager,
            user.id,
            full_name=registration_data.get('full_name'),
            email=registration_data.get('email'),
            phone=registration_data.get('phone'),
            grade=registration_data.get('grade'),
            is_registered=True,
            registration_date=datetime.now()
        )
        
        if not success:
            logger.error(f"فشل في حفظ معلومات التسجيل للمستخدم {user.id}")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="⚠️ حدث خطأ في حفظ معلومات التسجيل. يرجى المحاولة مرة أخرى لاحقاً."
            )
            return ConversationHandler.END
        
        # إرسال رسالة تأكيد التسجيل
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=f"🎉 تم تسجيلك بنجاح، {registration_data.get('full_name')}!\n\n"
                 "يمكنك الآن استخدام جميع ميزات بوت الاختبارات. استمتع! 😊",
            reply_markup=create_main_menu_keyboard(user.id, db_manager)
        )
        
        logger.info(f"تم تسجيل المستخدم {user.id} بنجاح")
        
        # تنظيف بيانات التسجيل المؤقتة
        if 'registration_data' in context.user_data:
            del context.user_data['registration_data']
        
        return MAIN_MENU
    except Exception as e:
        logger.error(f"خطأ في تأكيد التسجيل للمستخدم {user.id}: {e}")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="⚠️ حدث خطأ في تأكيد التسجيل. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END

# معالجة طلب تعديل المعلومات
async def handle_edit_request(update: Update, context: CallbackContext) -> int:
    """معالجة طلب تعديل معلومات التسجيل"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    # استخراج نوع التعديل من callback_data
    edit_type = query.data
    
    if edit_type == "edit_name":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال الاسم الجديد:"
        )
        return REGISTRATION_NAME
    elif edit_type == "edit_email":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال البريد الإلكتروني الجديد:"
        )
        return REGISTRATION_EMAIL
    elif edit_type == "edit_phone":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال رقم الجوال الجديد (مثال: 05xxxxxxxx أو +966xxxxxxxxx):"
        )
        return REGISTRATION_PHONE
    elif edit_type == "edit_grade":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى اختيار الصف الدراسي الجديد:",
            reply_markup=create_grade_keyboard()
        )
        return REGISTRATION_GRADE
    else:
        # إذا لم يتم التعرف على نوع التعديل، نعود إلى تأكيد التسجيل
        registration_data = context.user_data.get('registration_data', {})
        summary_text = "مراجعة معلومات التسجيل:\n\n" \
                      f"الاسم: {registration_data.get('full_name')}\n" \
                      f"البريد الإلكتروني: {registration_data.get('email')}\n" \
                      f"رقم الجوال: {registration_data.get('phone')}\n" \
                      f"الصف الدراسي: {registration_data.get('grade')}\n\n" \
                      "هل المعلومات صحيحة؟ يمكنك تأكيد المعلومات أو تعديلها."
        
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=summary_text,
            reply_markup=create_confirmation_keyboard()
        )
        return REGISTRATION_CONFIRM

# معالجة أمر تعديل المعلومات
async def handle_edit_info_command(update: Update, context: CallbackContext) -> int:
    """معالجة أمر تعديل معلومات المستخدم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_info_command للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # الحصول على معلومات المستخدم
    user_info = get_user_info(db_manager, user.id)
    if not user_info:
        logger.warning(f"لم يتم العثور على معلومات للمستخدم {user.id} في handle_edit_info_command")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ لم يتم العثور على معلوماتك. يرجى التسجيل أولاً."
        )
        return await start_registration(update, context)
    
    # حفظ معلومات المستخدم في بيانات المستخدم المؤقتة
    context.user_data['registration_data'] = {
        'user_id': user.id,
        'full_name': user_info.get('full_name'),
        'email': user_info.get('email'),
        'phone': user_info.get('phone'),
        'grade': user_info.get('grade')
    }
    
    # عرض معلومات المستخدم الحالية مع خيارات التعديل
    info_text = "معلوماتك الحالية:\n\n" \
               f"الاسم: {user_info.get('full_name')}\n" \
               f"البريد الإلكتروني: {user_info.get('email')}\n" \
               f"رقم الجوال: {user_info.get('phone')}\n" \
               f"الصف الدراسي: {user_info.get('grade')}\n\n" \
               "اختر المعلومات التي ترغب في تعديلها:"
    
    await safe_send_message(
        context.bot,
        chat_id,
        text=info_text,
        reply_markup=create_edit_info_keyboard()
    )
    
    return EDIT_USER_INFO_MENU

# معالجة اختيار تعديل المعلومات
async def handle_edit_info_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار تعديل معلومات المستخدم"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    # استخراج نوع التعديل من callback_data
    field = query.data
    
    if field == "edit_name":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال الاسم الجديد:"
        )
        return EDIT_USER_NAME
    elif field == "edit_email":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال البريد الإلكتروني الجديد:"
        )
        return EDIT_USER_EMAIL
    elif field == "edit_phone":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال رقم الجوال الجديد (مثال: 05xxxxxxxx أو +966xxxxxxxxx):"
        )
        return EDIT_USER_PHONE
    elif field == "edit_grade":
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
        return MAIN_MENU
    else:
        # إذا لم يتم التعرف على نوع التعديل، نعود إلى قائمة تعديل المعلومات
        user_info = context.user_data.get('registration_data', {})
        info_text = "معلوماتك الحالية:\n\n" \
                   f"الاسم: {user_info.get('full_name')}\n" \
                   f"البريد الإلكتروني: {user_info.get('email')}\n" \
                   f"رقم الجوال: {user_info.get('phone')}\n" \
                   f"الصف الدراسي: {user_info.get('grade')}\n\n" \
                   "اختر المعلومات التي ترغب في تعديلها:"
        
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
        )
        return EDIT_USER_INFO_MENU

# معالجة تعديل الاسم
async def handle_edit_name(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل اسم المستخدم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    name = update.message.text.strip()
    
    # التحقق من صحة الاسم
    if len(name) < 3:
        await safe_send_message(
            context.bot,
            chat_id,
            text="الاسم قصير جداً. يرجى إدخال اسمك الكامل (3 أحرف على الأقل):"
        )
        return EDIT_USER_NAME
    
    # حفظ الاسم الجديد في بيانات المستخدم المؤقتة
    if 'registration_data' not in context.user_data:
        context.user_data['registration_data'] = {}
    
    context.user_data['registration_data']['full_name'] = name
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_name للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في تحديث المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # تحديث الاسم في قاعدة البيانات
    success = save_user_info(db_manager, user.id, full_name=name)
    
    if not success:
        logger.error(f"فشل في تحديث اسم المستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في تحديث الاسم. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return EDIT_USER_INFO_MENU
    
    # عرض معلومات المستخدم المحدثة
    user_info = context.user_data.get('registration_data', {})
    info_text = "تم تحديث الاسم بنجاح! ✅\n\n" \
               "معلوماتك الحالية:\n\n" \
               f"الاسم: {name}\n" \
               f"البريد الإلكتروني: {user_info.get('email')}\n" \
               f"رقم الجوال: {user_info.get('phone')}\n" \
               f"الصف الدراسي: {user_info.get('grade')}\n\n" \
               "هل ترغب في تعديل معلومات أخرى؟"
    
    await safe_send_message(
        context.bot,
        chat_id,
        text=info_text,
        reply_markup=create_edit_info_keyboard()
    )
    
    return EDIT_USER_INFO_MENU

# معالجة تعديل البريد الإلكتروني
async def handle_edit_email(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل البريد الإلكتروني للمستخدم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    email = update.message.text.strip()
    
    # التحقق من صحة البريد الإلكتروني
    if not is_valid_email(email):
        await safe_send_message(
            context.bot,
            chat_id,
            text="البريد الإلكتروني غير صحيح. يرجى إدخال بريد إلكتروني صالح:"
        )
        return EDIT_USER_EMAIL
    
    # حفظ البريد الإلكتروني الجديد في بيانات المستخدم المؤقتة
    if 'registration_data' not in context.user_data:
        context.user_data['registration_data'] = {}
    
    context.user_data['registration_data']['email'] = email
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_email للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في تحديث المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # تحديث البريد الإلكتروني في قاعدة البيانات
    success = save_user_info(db_manager, user.id, email=email)
    
    if not success:
        logger.error(f"فشل في تحديث البريد الإلكتروني للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في تحديث البريد الإلكتروني. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return EDIT_USER_INFO_MENU
    
    # عرض معلومات المستخدم المحدثة
    user_info = context.user_data.get('registration_data', {})
    info_text = "تم تحديث البريد الإلكتروني بنجاح! ✅\n\n" \
               "معلوماتك الحالية:\n\n" \
               f"الاسم: {user_info.get('full_name')}\n" \
               f"البريد الإلكتروني: {email}\n" \
               f"رقم الجوال: {user_info.get('phone')}\n" \
               f"الصف الدراسي: {user_info.get('grade')}\n\n" \
               "هل ترغب في تعديل معلومات أخرى؟"
    
    await safe_send_message(
        context.bot,
        chat_id,
        text=info_text,
        reply_markup=create_edit_info_keyboard()
    )
    
    return EDIT_USER_INFO_MENU

# معالجة تعديل رقم الجوال
async def handle_edit_phone(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل رقم الجوال للمستخدم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    phone = update.message.text.strip()
    
    # التحقق من صحة رقم الجوال
    if not is_valid_phone(phone):
        await safe_send_message(
            context.bot,
            chat_id,
            text="رقم الجوال غير صحيح. يرجى إدخال رقم جوال سعودي صالح (يبدأ بـ 05 أو +966 أو 00966):"
        )
        return EDIT_USER_PHONE
    
    # حفظ رقم الجوال الجديد في بيانات المستخدم المؤقتة
    if 'registration_data' not in context.user_data:
        context.user_data['registration_data'] = {}
    
    context.user_data['registration_data']['phone'] = phone
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_phone للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في تحديث المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # تحديث رقم الجوال في قاعدة البيانات
    success = save_user_info(db_manager, user.id, phone=phone)
    
    if not success:
        logger.error(f"فشل في تحديث رقم الجوال للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في تحديث رقم الجوال. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return EDIT_USER_INFO_MENU
    
    # عرض معلومات المستخدم المحدثة
    user_info = context.user_data.get('registration_data', {})
    info_text = "تم تحديث رقم الجوال بنجاح! ✅\n\n" \
               "معلوماتك الحالية:\n\n" \
               f"الاسم: {user_info.get('full_name')}\n" \
               f"البريد الإلكتروني: {user_info.get('email')}\n" \
               f"رقم الجوال: {phone}\n" \
               f"الصف الدراسي: {user_info.get('grade')}\n\n" \
               "هل ترغب في تعديل معلومات أخرى؟"
    
    await safe_send_message(
        context.bot,
        chat_id,
        text=info_text,
        reply_markup=create_edit_info_keyboard()
    )
    
    return EDIT_USER_INFO_MENU

# معالجة تعديل الصف الدراسي
async def handle_edit_grade(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل الصف الدراسي للمستخدم"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    grade_data = query.data
    
    try:
        # استخراج الصف الدراسي من callback_data
        if grade_data.startswith("grade_secondary_"):
            grade_number = grade_data.split("_")[-1]
            grade = f"ثانوي {grade_number}"
        elif grade_data == "grade_university":
            grade = "طالب جامعي"
        elif grade_data == "grade_teacher":
            grade = "معلم"
        elif grade_data == "grade_other":
            grade = "أخرى"
        else:
            # إذا لم يتم التعرف على الصف، نطلب من المستخدم الاختيار مرة أخرى
            await query.answer("خيار غير صالح. يرجى اختيار صف دراسي من القائمة.")
            return EDIT_USER_GRADE
        
        # الحصول على مدير قاعدة البيانات
        db_manager = context.bot_data.get("DB_MANAGER")
        if not db_manager:
            logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_grade للمستخدم {user.id}")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="حدث خطأ في تحديث المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
            )
            return ConversationHandler.END
        
        # تحديث الصف الدراسي في قاعدة البيانات
        success = save_user_info(db_manager, user.id, grade=grade)
        
        if not success:
            logger.error(f"فشل في تحديث الصف الدراسي للمستخدم {user.id}")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="⚠️ حدث خطأ في تحديث الصف الدراسي. يرجى المحاولة مرة أخرى لاحقاً."
            )
            return EDIT_USER_INFO_MENU
        
        # حفظ الصف الدراسي الجديد في بيانات المستخدم المؤقتة
        if 'registration_data' not in context.user_data:
            context.user_data['registration_data'] = {}
        
        context.user_data['registration_data']['grade'] = grade
        
        # عرض معلومات المستخدم المحدثة
        user_info = context.user_data.get('registration_data', {})
        info_text = "تم تحديث الصف الدراسي بنجاح! ✅\n\n" \
                   "معلوماتك الحالية:\n\n" \
                   f"الاسم: {user_info.get('full_name')}\n" \
                   f"البريد الإلكتروني: {user_info.get('email')}\n" \
                   f"رقم الجوال: {user_info.get('phone')}\n" \
                   f"الصف الدراسي: {grade}\n\n" \
                   "هل ترغب في تعديل معلومات أخرى؟"
        
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
        )
        
        return EDIT_USER_INFO_MENU
    except Exception as e:
        logger.error(f"خطأ في معالجة تعديل الصف الدراسي: {e}")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="حدث خطأ في تحديث الصف الدراسي. يرجى المحاولة مرة أخرى:",
            reply_markup=create_grade_keyboard()
        )
        return EDIT_USER_GRADE

# معالجة زر تعديل المعلومات في القائمة الرئيسية
async def handle_edit_my_info(update: Update, context: CallbackContext) -> int:
    """معالجة زر تعديل المعلومات في القائمة الرئيسية"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_my_info للمستخدم {user.id}")
        await query.answer("حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً.")
        return ConversationHandler.END
    
    # الحصول على معلومات المستخدم
    user_info = get_user_info(db_manager, user.id)
    if not user_info:
        logger.warning(f"لم يتم العثور على معلومات للمستخدم {user.id} في handle_edit_my_info")
        await query.answer("لم يتم العثور على معلوماتك. يرجى التسجيل أولاً.")
        return await start_registration(update, context)
    
    # حفظ معلومات المستخدم في بيانات المستخدم المؤقتة
    context.user_data['registration_data'] = {
        'user_id': user.id,
        'full_name': user_info.get('full_name'),
        'email': user_info.get('email'),
        'phone': user_info.get('phone'),
        'grade': user_info.get('grade')
    }
    
    # عرض معلومات المستخدم الحالية مع خيارات التعديل
    info_text = "معلوماتك الحالية:\n\n" \
               f"الاسم: {user_info.get('full_name')}\n" \
               f"البريد الإلكتروني: {user_info.get('email')}\n" \
               f"رقم الجوال: {user_info.get('phone')}\n" \
               f"الصف الدراسي: {user_info.get('grade')}\n\n" \
               "اختر المعلومات التي ترغب في تعديلها:"
    
    await safe_edit_message_text(
        context.bot,
        chat_id,
        query.message.message_id,
        text=info_text,
        reply_markup=create_edit_info_keyboard()
    )
    
    return EDIT_USER_INFO_MENU

# معالجة الخروج من المحادثة
async def handle_cancel(update: Update, context: CallbackContext) -> int:
    """معالجة الخروج من المحادثة"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # تنظيف بيانات المستخدم المؤقتة
    if 'registration_data' in context.user_data:
        del context.user_data['registration_data']
    
    await safe_send_message(
        context.bot,
        chat_id,
        text="تم إلغاء العملية. يمكنك استخدام /start للبدء من جديد."
    )
    
    return ConversationHandler.END

# تعريف محادثة التسجيل
registration_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("start", start_registration),
        CommandHandler("register", start_registration)
    ],
    states={
        REGISTRATION_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name_input)
        ],
        REGISTRATION_EMAIL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_input)
        ],
        REGISTRATION_PHONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone_input)
        ],
        REGISTRATION_GRADE: [
            CallbackQueryHandler(handle_grade_selection, pattern=r'^grade_')
        ],
        REGISTRATION_CONFIRM: [
            CallbackQueryHandler(handle_registration_confirmation, pattern=r'^confirm_registration$'),
            CallbackQueryHandler(handle_edit_request, pattern=r'^edit_')
        ]
    },
    fallbacks=[
        CommandHandler("cancel", handle_cancel),
        CommandHandler("start", start_registration)
    ],
    name="registration_conversation",
    persistent=False
)

# تعريف محادثة تعديل المعلومات
edit_info_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("edit_info", handle_edit_info_command),
        CallbackQueryHandler(handle_edit_my_info, pattern=r'^edit_my_info$')
    ],
    states={
        EDIT_USER_INFO_MENU: [
            CallbackQueryHandler(handle_edit_info_selection, pattern=r'^(edit_|main_)')
        ],
        EDIT_USER_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_name)
        ],
        EDIT_USER_EMAIL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_email)
        ],
        EDIT_USER_PHONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_phone)
        ],
        EDIT_USER_GRADE: [
            CallbackQueryHandler(handle_edit_grade, pattern=r'^grade_')
        ]
    },
    fallbacks=[
        CommandHandler("cancel", handle_cancel),
        CommandHandler("start", start_registration)
    ],
    name="edit_info_conversation",
    persistent=False
)
