#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
منطق التسجيل الإلزامي للمستخدمين في بوت الاختبارات
يتضمن جمع الاسم، البريد الإلكتروني، رقم الجوال، والصف الدراسي
"""

import logging
import re
import random
import time
from datetime import datetime, timedelta
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
REGISTRATION_VERIFY_PHONE = 23  # حالة جديدة للتحقق من رقم الجوال
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

# توليد كود تحقق عشوائي
def generate_verification_code():
    """توليد كود تحقق عشوائي مكون من 6 أرقام"""
    return str(random.randint(100000, 999999))

# التحقق من صلاحية كود التحقق
def is_verification_code_valid(context: CallbackContext, user_id: int, code: str) -> bool:
    """التحقق من صلاحية كود التحقق المدخل"""
    if 'verification_data' not in context.user_data:
        logger.warning(f"لا توجد بيانات تحقق للمستخدم {user_id}")
        return False
    
    verification_data = context.user_data['verification_data']
    stored_code = verification_data.get('code')
    expiry_time = verification_data.get('expiry_time')
    
    # التحقق من وجود الكود وتطابقه
    if not stored_code or stored_code != code:
        logger.warning(f"كود التحقق غير صحيح للمستخدم {user_id}")
        return False
    
    # التحقق من صلاحية الكود
    current_time = datetime.now()
    if current_time > expiry_time:
        logger.warning(f"انتهت صلاحية كود التحقق للمستخدم {user_id}")
        return False
    
    logger.info(f"تم التحقق من كود التحقق بنجاح للمستخدم {user_id}")
    return True

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
        await safe_send_message(context.bot, chat_id, text="الاسم قصير جداً. يرجى إدخال اسمك الكامل:")
        return REGISTRATION_NAME
    
    # حفظ الاسم في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['full_name'] = name
    
    # طلب البريد الإلكتروني
    await safe_send_message(
        context.bot, 
        chat_id, 
        text=f"شكراً {name}!\n\nالخطوة الثانية: أدخل بريدك الإلكتروني:"
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
    context.user_data['registration_data']['email'] = email
    
    # طلب رقم الجوال
    await safe_send_message(
        context.bot, 
        chat_id, 
        text="الخطوة الثالثة: أدخل رقم جوالك (مثال: 05xxxxxxxx أو +966xxxxxxxxx):"
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
        await safe_send_message(context.bot, chat_id, text="رقم الجوال غير صحيح. يرجى إدخال رقم جوال سعودي صحيح (يبدأ بـ 05 أو +966 أو 00966):")
        return REGISTRATION_PHONE
    
    # حفظ رقم الجوال في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['phone'] = phone
    
    # إرسال رسالة انتظار للمستخدم
    wait_message = await safe_send_message(
        context.bot,
        chat_id,
        text="جاري إعداد كود التحقق... ⏳"
    )
    
    try:
        # توليد كود تحقق وتخزينه مع وقت انتهاء الصلاحية (10 دقائق)
        verification_code = generate_verification_code()
        expiry_time = datetime.now() + timedelta(minutes=10)
        
        # تخزين بيانات التحقق في بيانات المستخدم المؤقتة
        context.user_data['verification_data'] = {
            'code': verification_code,
            'expiry_time': expiry_time,
            'attempts': 0,
            'phone': phone,
            'message_id': wait_message.message_id if wait_message else None
        }
        
        # إنشاء لوحة مفاتيح لإعادة إرسال الكود
        keyboard = [
            [InlineKeyboardButton("🔄 إعادة إرسال الكود", callback_data="resend_code")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # إرسال كود التحقق (محاكاة لرسالة SMS)
        if wait_message:
            # تحديث رسالة الانتظار بدلاً من إرسال رسالة جديدة
            await safe_edit_message_text(
                context.bot,
                chat_id,
                wait_message.message_id,
                text=f"✅ تم إرسال كود التحقق إلى رقم الجوال {phone}.\n\n"
                     f"📱 <b>الكود هو: {verification_code}</b>\n\n"
                     "🔢 يرجى إدخال كود التحقق المكون من 6 أرقام:",
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        else:
            # إرسال رسالة جديدة في حالة فشل رسالة الانتظار
            await safe_send_message(
                context.bot,
                chat_id,
                text=f"✅ تم إرسال كود التحقق إلى رقم الجوال {phone}.\n\n"
                     f"📱 <b>الكود هو: {verification_code}</b>\n\n"
                     "🔢 يرجى إدخال كود التحقق المكون من 6 أرقام:",
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        
        logger.info(f"تم إرسال كود التحقق {verification_code} للمستخدم {user.id}")
        return REGISTRATION_VERIFY_PHONE
        
    except Exception as e:
        logger.error(f"خطأ في إرسال كود التحقق للمستخدم {user.id}: {e}")
        # في حالة حدوث خطأ، نرسل رسالة خطأ ونعود لطلب رقم الجوال
        if wait_message:
            await safe_edit_message_text(
                context.bot,
                chat_id,
                wait_message.message_id,
                text="⚠️ حدث خطأ في إرسال كود التحقق. يرجى المحاولة مرة أخرى."
            )
        else:
            await safe_send_message(
                context.bot,
                chat_id,
                text="⚠️ حدث خطأ في إرسال كود التحقق. يرجى المحاولة مرة أخرى."
            )
        return REGISTRATION_PHONE

# معالجة إدخال كود التحقق
async def handle_verification_code_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال كود التحقق من المستخدم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    code = update.message.text.strip()
    
    # التحقق من وجود بيانات التحقق
    if 'verification_data' not in context.user_data:
        logger.warning(f"لا توجد بيانات تحقق للمستخدم {user.id}")
        keyboard = [
            [InlineKeyboardButton("🔄 إعادة المحاولة", callback_data="retry_phone")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في عملية التحقق. يرجى إعادة المحاولة.",
            reply_markup=reply_markup
        )
        return REGISTRATION_PHONE
    
    # زيادة عدد المحاولات
    context.user_data['verification_data']['attempts'] += 1
    attempts = context.user_data['verification_data']['attempts']
    
    # التحقق من عدد المحاولات (الحد الأقصى 3 محاولات)
    if attempts > 3:
        logger.warning(f"المستخدم {user.id} تجاوز الحد الأقصى من المحاولات")
        keyboard = [
            [InlineKeyboardButton("🔄 إعادة المحاولة", callback_data="retry_phone")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ تجاوزت الحد الأقصى من المحاولات. يرجى إعادة المحاولة.",
            reply_markup=reply_markup
        )
        # إعادة تعيين بيانات التحقق
        del context.user_data['verification_data']
        return REGISTRATION_PHONE
    
    # التحقق من صحة الكود
    if not is_verification_code_valid(context, user.id, code):
        remaining_attempts = 3 - attempts
        
        # إنشاء لوحة مفاتيح لإعادة إرسال الكود
        keyboard = [
            [InlineKeyboardButton("🔄 إعادة إرسال الكود", callback_data="resend_code")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_send_message(
            context.bot,
            chat_id,
            text=f"❌ كود التحقق غير صحيح أو انتهت صلاحيته.\n"
                 f"⚠️ المحاولات المتبقية: {remaining_attempts}\n\n"
                 f"🔢 يرجى إدخال الكود الصحيح أو إعادة إرسال كود جديد:",
            reply_markup=reply_markup
        )
        return REGISTRATION_VERIFY_PHONE
    
    # تم التحقق بنجاح، الانتقال إلى الخطوة التالية
    logger.info(f"تم التحقق من رقم الجوال للمستخدم {user.id} بنجاح")
    
    # طلب الصف الدراسي
    keyboard = create_grade_keyboard()
    await safe_send_message(
        context.bot, 
        chat_id, 
        text="✅ تم التحقق من رقم الجوال بنجاح!\n\n"
             "الخطوة التالية: اختر الصف الدراسي:",
        reply_markup=keyboard
    )
    return REGISTRATION_GRADE

# معالجة إعادة إرسال كود التحقق
async def handle_resend_code(update: Update, context: CallbackContext) -> int:
    """معالجة طلب إعادة إرسال كود التحقق"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    
    # التحقق من وجود بيانات التحقق
    if 'verification_data' not in context.user_data:
        logger.warning(f"لا توجد بيانات تحقق للمستخدم {user.id} عند طلب إعادة إرسال الكود")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            message_id,
            text="⚠️ حدث خطأ في عملية التحقق. يرجى إدخال رقم الجوال مرة أخرى:"
        )
        return REGISTRATION_PHONE
    
    # الحصول على رقم الجوال من بيانات التحقق
    phone = context.user_data['verification_data'].get('phone')
    if not phone:
        logger.warning(f"لا يوجد رقم جوال في بيانات التحقق للمستخدم {user.id}")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            message_id,
            text="⚠️ حدث خطأ في عملية التحقق. يرجى إدخال رقم الجوال مرة أخرى:"
        )
        return REGISTRATION_PHONE
    
    # إرسال رسالة انتظار
    await safe_edit_message_text(
        context.bot,
        chat_id,
        message_id,
        text="جاري إعادة إرسال كود التحقق... ⏳"
    )
    
    try:
        # توليد كود تحقق جديد وتحديث وقت انتهاء الصلاحية
        verification_code = generate_verification_code()
        expiry_time = datetime.now() + timedelta(minutes=10)
        
        # تحديث بيانات التحقق في بيانات المستخدم المؤقتة
        context.user_data['verification_data'] = {
            'code': verification_code,
            'expiry_time': expiry_time,
            'attempts': 0,  # إعادة تعيين عدد المحاولات
            'phone': phone,
            'message_id': message_id
        }
        
        # إنشاء لوحة مفاتيح لإعادة إرسال الكود
        keyboard = [
            [InlineKeyboardButton("🔄 إعادة إرسال الكود", callback_data="resend_code")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # إرسال كود التحقق الجديد
        await safe_edit_message_text(
            context.bot,
            chat_id,
            message_id,
            text=f"✅ تم إعادة إرسال كود التحقق إلى رقم الجوال {phone}.\n\n"
                 f"📱 <b>الكود الجديد هو: {verification_code}</b>\n\n"
                 "🔢 يرجى إدخال كود التحقق المكون من 6 أرقام:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        
        logger.info(f"تم إعادة إرسال كود التحقق {verification_code} للمستخدم {user.id}")
        return REGISTRATION_VERIFY_PHONE
        
    except Exception as e:
        logger.error(f"خطأ في إعادة إرسال كود التحقق للمستخدم {user.id}: {e}")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            message_id,
            text="⚠️ حدث خطأ في إعادة إرسال كود التحقق. يرجى المحاولة مرة أخرى."
        )
        return REGISTRATION_PHONE

# معالجة إعادة المحاولة لإدخال رقم الجوال
async def handle_retry_phone(update: Update, context: CallbackContext) -> int:
    """معالجة طلب إعادة المحاولة لإدخال رقم الجوال"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    # تنظيف بيانات التحقق المؤقتة
    if 'verification_data' in context.user_data:
        del context.user_data['verification_data']
    
    # طلب رقم الجوال مرة أخرى
    await safe_edit_message_text(
        context.bot,
        chat_id,
        query.message.message_id,
        text="يرجى إدخال رقم جوالك مرة أخرى (مثال: 05xxxxxxxx أو +966xxxxxxxxx):"
    )
    
    return REGISTRATION_PHONE
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    # التحقق من وجود بيانات التسجيل
    if 'registration_data' not in context.user_data:
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="حدث خطأ في عملية التسجيل. يرجى البدء من جديد باستخدام الأمر /register"
        )
        return ConversationHandler.END
    
    # استخراج الصف الدراسي من callback_data
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
            return REGISTRATION_GRADE
        
        # حفظ الصف الدراسي في بيانات المستخدم المؤقتة
        context.user_data['registration_data']['grade'] = grade
        
        # عرض ملخص المعلومات للتأكيد
        registration_data = context.user_data['registration_data']
        summary_text = "مراجعة معلوماتك:\n\n" \
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

# معالجة تأكيد التسجيل أو تعديل المعلومات
async def handle_registration_confirmation(update: Update, context: CallbackContext) -> int:
    """معالجة تأكيد التسجيل أو تعديل المعلومات"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    # التحقق من وجود بيانات التسجيل
    if 'registration_data' not in context.user_data:
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="حدث خطأ في عملية التسجيل. يرجى البدء من جديد باستخدام الأمر /register"
        )
        return ConversationHandler.END
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_registration_confirmation للمستخدم {user.id}")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="حدث خطأ في حفظ معلومات التسجيل. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # حفظ معلومات التسجيل في قاعدة البيانات
    registration_data = context.user_data['registration_data']
    
    # تسجيل المعلومات قبل الحفظ للتشخيص
    logger.info(f"حفظ معلومات التسجيل للمستخدم {user.id}: {registration_data}")
    
    # إضافة حقل is_registered
    registration_data['is_registered'] = True
    
    # حفظ المعلومات في قاعدة البيانات
    success = save_user_info(db_manager, user.id, **registration_data)
    
    # التحقق من نجاح الحفظ
    if not success:
        logger.error(f"فشل حفظ معلومات التسجيل للمستخدم {user.id}")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="حدث خطأ في حفظ معلومات التسجيل. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # التحقق من حفظ is_registered بشكل صحيح
    user_info = get_user_info(db_manager, user.id)
    logger.info(f"التحقق من حفظ is_registered للمستخدم {user.id}: {user_info.get('is_registered') if user_info else None}")
    
    # إرسال رسالة تأكيد التسجيل
    await safe_edit_message_text(
        context.bot,
        chat_id,
        query.message.message_id,
        text="تم تسجيلك بنجاح! ✅\n\n"
             "يمكنك الآن استخدام جميع ميزات بوت الاختبارات.\n"
             "استخدم الأمر /start للبدء."
    )
    
    # تنظيف بيانات التسجيل المؤقتة
    if 'registration_data' in context.user_data:
        del context.user_data['registration_data']
    
    if 'verification_data' in context.user_data:
        del context.user_data['verification_data']
    
    return ConversationHandler.END

# معالجة تعديل حقل معين في معلومات التسجيل
async def handle_edit_registration_field(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل حقل معين في معلومات التسجيل"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    # التحقق من وجود بيانات التسجيل
    if 'registration_data' not in context.user_data:
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="حدث خطأ في عملية التسجيل. يرجى البدء من جديد باستخدام الأمر /register"
        )
        return ConversationHandler.END
    
    # استخراج الحقل المراد تعديله من callback_data
    field = query.data.split("_")[1]
    
    if field == "name":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال اسمك الكامل:"
        )
        return REGISTRATION_NAME
    elif field == "email":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال بريدك الإلكتروني:"
        )
        return REGISTRATION_EMAIL
    elif field == "phone":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال رقم جوالك (مثال: 05xxxxxxxx أو +966xxxxxxxxx):"
        )
        return REGISTRATION_PHONE
    elif field == "grade":
        keyboard = create_grade_keyboard()
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى اختيار الصف الدراسي:",
            reply_markup=keyboard
        )
        return REGISTRATION_GRADE
    else:
        # إذا لم يتم التعرف على الحقل، نعود إلى شاشة التأكيد
        registration_data = context.user_data['registration_data']
        summary_text = "مراجعة معلوماتك:\n\n" \
                      f"الاسم: {registration_data.get('full_name')}\n" \
                      f"البريد الإلكتروني: {registration_data.get('email')}\n" \
                      f"رقم الجوال: {registration_data.get('phone')}\n" \
                      f"الصف الدراسي: {registration_data.get('grade')}\n\n" \
                      "هل المعلومات صحيحة؟ يمكنك تأكيد المعلومات أو تعديلها."
        
        keyboard = create_confirmation_keyboard()
        
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=summary_text,
            reply_markup=keyboard
        )
        
        return REGISTRATION_CONFIRM

# إلغاء عملية التسجيل
async def cancel_registration(update: Update, context: CallbackContext) -> int:
    """إلغاء عملية التسجيل"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # تنظيف بيانات التسجيل المؤقتة
    if 'registration_data' in context.user_data:
        del context.user_data['registration_data']
    
    if 'verification_data' in context.user_data:
        del context.user_data['verification_data']
    
    await safe_send_message(
        context.bot,
        chat_id,
        text="تم إلغاء عملية التسجيل. يمكنك البدء من جديد باستخدام الأمر /register"
    )
    
    return ConversationHandler.END

# عرض معلومات المستخدم الحالية وتعديلها
async def start_edit_user_info(update: Update, context: CallbackContext) -> int:
    """عرض معلومات المستخدم الحالية وتعديلها"""
    # التعامل مع الاستدعاء من زر أو أمر
    if update.callback_query:
        query = update.callback_query
        user = query.from_user
        chat_id = query.message.chat_id
        message_id = query.message.message_id
        is_callback = True
    else:
        user = update.effective_user
        chat_id = update.effective_chat.id
        message_id = None
        is_callback = False
    
    # التحقق من حالة تسجيل المستخدم
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في start_edit_user_info للمستخدم {user.id}")
        
        message_text = "حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        
        if is_callback:
            await safe_edit_message_text(context.bot, chat_id, message_id, text=message_text)
        else:
            await safe_send_message(context.bot, chat_id, text=message_text)
        
        return ConversationHandler.END
    
    # التحقق من حالة تسجيل المستخدم
    is_registered = await check_registration_status(update, context, db_manager)
    if not is_registered:
        # إذا لم يكن المستخدم مسجلاً، سيتم توجيهه لإكمال التسجيل في دالة check_registration_status
        return ConversationHandler.END
    
    # الحصول على معلومات المستخدم
    user_info = get_user_info(db_manager, user.id)
    
    if not user_info:
        message_text = "لم يتم العثور على معلوماتك. يرجى التسجيل أولاً باستخدام الأمر /register"
        
        if is_callback:
            await safe_edit_message_text(context.bot, chat_id, message_id, text=message_text)
        else:
            await safe_send_message(context.bot, chat_id, text=message_text)
        
        return ConversationHandler.END
    
    # معالجة القيم None أو 'None' أو الفارغة
    processed_user_info = {}
    for key, value in user_info.items():
        if value in [None, 'None', '']:
            processed_user_info[key] = "غير محدد"
        else:
            processed_user_info[key] = value
    
    # عرض معلومات المستخدم الحالية
    info_text = "معلوماتك الحالية:\n\n" \
               f"الاسم: {processed_user_info.get('full_name')}\n" \
               f"البريد الإلكتروني: {processed_user_info.get('email')}\n" \
               f"رقم الجوال: {processed_user_info.get('phone')}\n" \
               f"الصف الدراسي: {processed_user_info.get('grade')}\n\n" \
               "اختر المعلومات التي ترغب في تعديلها:"
    
    # إنشاء لوحة مفاتيح لتعديل المعلومات
    keyboard = create_edit_info_keyboard()
    
    if is_callback:
        await safe_edit_message_text(
            context.bot,
            chat_id,
            message_id,
            text=info_text,
            reply_markup=keyboard
        )
    else:
        await safe_send_message(
            context.bot,
            chat_id,
            text=info_text,
            reply_markup=keyboard
        )
    
    return EDIT_USER_INFO_MENU

# معالجة اختيار حقل لتعديله
async def handle_edit_info_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار حقل لتعديله"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    # استخراج الحقل المراد تعديله من callback_data
    field = query.data.split("_")[1]
    
    if field == "name":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال اسمك الكامل الجديد:"
        )
        return EDIT_USER_NAME
    elif field == "email":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال بريدك الإلكتروني الجديد:"
        )
        return EDIT_USER_EMAIL
    elif field == "phone":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال رقم جوالك الجديد (مثال: 05xxxxxxxx أو +966xxxxxxxxx):"
        )
        return EDIT_USER_PHONE
    elif field == "grade":
        keyboard = create_grade_keyboard()
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى اختيار الصف الدراسي الجديد:",
            reply_markup=keyboard
        )
        return EDIT_USER_GRADE
    elif field == "main":
        # العودة إلى القائمة الرئيسية
        try:
            # إظهار القائمة الرئيسية
            from handlers.common import main_menu_callback
            await main_menu_callback(update, context)
            # إنهاء محادثة تعديل المعلومات بشكل صريح
            logger.info(f"المستخدم {user.id} عاد للقائمة الرئيسية من تعديل المعلومات")
            return MAIN_MENU
        except Exception as e:
            logger.error(f"خطأ عند العودة للقائمة الرئيسية: {e}")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="جاري العودة للقائمة الرئيسية..."
            )
            return ConversationHandler.END
    else:
        # إذا لم يتم التعرف على الحقل، نعود إلى قائمة تعديل المعلومات
        return await start_edit_user_info(update, context)

# معالجة تعديل الاسم
async def handle_edit_name(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل الاسم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    name = update.message.text.strip()
    
    # التحقق من صحة الاسم
    if len(name) < 3:
        await safe_send_message(context.bot, chat_id, text="الاسم قصير جداً. يرجى إدخال اسمك الكامل:")
        return EDIT_USER_NAME
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_name للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="حدث خطأ في تحديث المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # تحديث الاسم في قاعدة البيانات
    success = save_user_info(db_manager, user.id, full_name=name)
    
    if not success:
        await safe_send_message(
            context.bot,
            chat_id,
            text="حدث خطأ في تحديث الاسم. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # إرسال رسالة تأكيد التحديث
    await safe_send_message(
        context.bot,
        chat_id,
        text=f"تم تحديث الاسم بنجاح إلى: {name}"
    )
    
    # العودة إلى قائمة تعديل المعلومات
    return await start_edit_user_info(update, context)

# معالجة تعديل البريد الإلكتروني
async def handle_edit_email(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل البريد الإلكتروني"""
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
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_email للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="حدث خطأ في تحديث المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # تحديث البريد الإلكتروني في قاعدة البيانات
    success = save_user_info(db_manager, user.id, email=email)
    
    if not success:
        await safe_send_message(
            context.bot,
            chat_id,
            text="حدث خطأ في تحديث البريد الإلكتروني. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # إرسال رسالة تأكيد التحديث
    await safe_send_message(
        context.bot,
        chat_id,
        text=f"تم تحديث البريد الإلكتروني بنجاح إلى: {email}"
    )
    
    # العودة إلى قائمة تعديل المعلومات
    return await start_edit_user_info(update, context)

# معالجة تعديل رقم الجوال
async def handle_edit_phone(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل رقم الجوال"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    phone = update.message.text.strip()
    
    # التحقق من صحة رقم الجوال
    if not is_valid_phone(phone):
        await safe_send_message(
            context.bot,
            chat_id,
            text="رقم الجوال غير صحيح. يرجى إدخال رقم جوال سعودي صحيح (يبدأ بـ 05 أو +966 أو 00966):"
        )
        return EDIT_USER_PHONE
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_phone للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="حدث خطأ في تحديث المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # تحديث رقم الجوال في قاعدة البيانات
    success = save_user_info(db_manager, user.id, phone=phone)
    
    if not success:
        await safe_send_message(
            context.bot,
            chat_id,
            text="حدث خطأ في تحديث رقم الجوال. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # إرسال رسالة تأكيد التحديث
    await safe_send_message(
        context.bot,
        chat_id,
        text=f"تم تحديث رقم الجوال بنجاح إلى: {phone}"
    )
    
    # العودة إلى قائمة تعديل المعلومات
    return await start_edit_user_info(update, context)

# معالجة تعديل الصف الدراسي
async def handle_edit_grade(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل الصف الدراسي"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    # استخراج الصف الدراسي من callback_data
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
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="حدث خطأ في تحديث الصف الدراسي. يرجى المحاولة مرة أخرى لاحقاً."
            )
            return ConversationHandler.END
        
        # إرسال رسالة تأكيد التحديث
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=f"تم تحديث الصف الدراسي بنجاح إلى: {grade}"
        )
        
        # العودة إلى قائمة تعديل المعلومات
        return await start_edit_user_info(update, context)
    except Exception as e:
        logger.error(f"خطأ في معالجة تعديل الصف الدراسي: {e}")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="حدث خطأ في تحديث الصف الدراسي. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END

# تعريف محادثة التسجيل
registration_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('register', start_registration)],
    states={
        REGISTRATION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name_input)],
        REGISTRATION_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_input)],
        REGISTRATION_PHONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone_input),
            CallbackQueryHandler(handle_retry_phone, pattern=r'^retry_phone$')
        ],
        REGISTRATION_VERIFY_PHONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_verification_code_input),
            CallbackQueryHandler(handle_resend_code, pattern=r'^resend_code$')
        ],
        REGISTRATION_GRADE: [CallbackQueryHandler(handle_grade_selection, pattern=r'^grade_')],
        REGISTRATION_CONFIRM: [
            CallbackQueryHandler(handle_registration_confirmation, pattern=r'^confirm_registration$'),
            CallbackQueryHandler(handle_edit_registration_field, pattern=r'^edit_')
        ],
    },
    fallbacks=[CommandHandler('cancel', cancel_registration)],
    name="registration_conversation",
    persistent=False
)

# تعريف محادثة تعديل المعلومات
edit_info_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("edit_info", start_edit_user_info),
        CallbackQueryHandler(start_edit_user_info, pattern=r"^edit_my_info$")
    ],
    states={
        EDIT_USER_INFO_MENU: [
            CallbackQueryHandler(handle_edit_info_selection, pattern=r"^edit_"),
            CallbackQueryHandler(handle_edit_info_selection, pattern=r"^main_menu$")
        ],
        EDIT_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_name)],
        EDIT_USER_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_email)],
        EDIT_USER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_phone)],
        EDIT_USER_GRADE: [CallbackQueryHandler(handle_edit_grade, pattern=r'^grade_')],
    },
    fallbacks=[CommandHandler('cancel', cancel_registration)],
    name="edit_info_conversation",
    persistent=False,
    map_to_parent={
        MAIN_MENU: MAIN_MENU,
        END: END
    }
)
