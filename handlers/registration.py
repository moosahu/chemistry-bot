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
    
    # إرسال رسالة الترحيب المخصصة أولاً
    welcome_message = "مرحباً بك في بوت الكيمياء التحصيلي! أنا هنا لمساعدتك في الاستعداد لاختباراتك. يمكنك البدء باختبار تجريبي أو اختيار وحدة معينة.\nتطوير الاستاذ حسين علي الموسى"
    await safe_send_message(
        context.bot,
        chat_id,
        text=welcome_message
    )
    
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
    
    # التحقق من اكتمال معلومات المستخدم
    is_registered = is_user_fully_registered(user_info)
    
    # تحديث حالة التسجيل في context.user_data
    context.user_data['is_registered'] = is_registered
    
    # إذا كان المستخدم مسجلاً (لديه جميع المعلومات الأساسية)، عرض القائمة الرئيسية
    if is_registered:
        logger.info(f"المستخدم {user_id} مسجل بالفعل، عرض القائمة الرئيسية")
        try:
            from handlers.common import main_menu_callback
        except ImportError:
            try:
                from common import main_menu_callback
            except ImportError as e:
                logger.error(f"خطأ في استيراد main_menu_callback: {e}")
                # إذا لم نتمكن من استيراد main_menu_callback، نعرض القائمة الرئيسية هنا
                menu_text = "القائمة الرئيسية:"
                keyboard = create_main_menu_keyboard(user_id, db_manager)
                await safe_send_message(
                    context.bot,
                    chat_id,
                    text=menu_text,
                    reply_markup=keyboard
                )
                return ConversationHandler.END # إنهاء المحادثة بعد عرض القائمة
        
        # استدعاء main_menu_callback لعرض القائمة الرئيسية
        await main_menu_callback(update, context)
        return ConversationHandler.END # إنهاء المحادثة بعد عرض القائمة
    else:
        # إذا لم يكن المستخدم مسجلاً، بدء عملية التسجيل
        logger.info(f"المستخدم {user_id} غير مسجل، بدء عملية التسجيل")
        return await start_registration(update, context)

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
            await start_registration(update, context)
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
    
    # طلب الاسم الكامل
    await safe_send_message(
        context.bot,
        chat_id,
        text="👤 الرجاء إدخال الاسم الكامل:"
    )
    return REGISTRATION_NAME

# معالجة إدخال الاسم
async def registration_name(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال الاسم في عملية التسجيل"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    full_name = update.message.text.strip()
    
    # التحقق من صحة الاسم
    if len(full_name) < 3:
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ الاسم قصير جداً. الرجاء إدخال الاسم الكامل (3 أحرف على الأقل):"
        )
        return REGISTRATION_NAME
    
    # تخزين الاسم في بيانات التسجيل المؤقتة
    context.user_data['registration_data']['full_name'] = full_name
    
    # طلب البريد الإلكتروني
    await safe_send_message(
        context.bot,
        chat_id,
        text="📧 الرجاء إدخال البريد الإلكتروني:"
    )
    return REGISTRATION_EMAIL

# معالجة إدخال البريد الإلكتروني
async def registration_email(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال البريد الإلكتروني في عملية التسجيل"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    email = update.message.text.strip()
    
    # التحقق من صحة البريد الإلكتروني
    if not is_valid_email(email):
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ البريد الإلكتروني غير صحيح. الرجاء إدخال بريد إلكتروني صحيح:"
        )
        return REGISTRATION_EMAIL
    
    # تخزين البريد الإلكتروني في بيانات التسجيل المؤقتة
    context.user_data['registration_data']['email'] = email
    
    # طلب رقم الجوال
    await safe_send_message(
        context.bot,
        chat_id,
        text="📱 الرجاء إدخال رقم الجوال (يبدأ بـ 05 أو +966 أو 00966):"
    )
    return REGISTRATION_PHONE

# معالجة إدخال رقم الجوال
async def registration_phone(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال رقم الجوال في عملية التسجيل"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    phone = update.message.text.strip()
    
    # التحقق من صحة رقم الجوال
    if not is_valid_phone(phone):
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ رقم الجوال غير صحيح. الرجاء إدخال رقم جوال سعودي صحيح (يبدأ بـ 05 أو +966 أو 00966):"
        )
        return REGISTRATION_PHONE
    
    # تخزين رقم الجوال في بيانات التسجيل المؤقتة
    context.user_data['registration_data']['phone'] = phone
    
    # طلب الصف الدراسي
    keyboard = create_grade_keyboard()
    await safe_send_message(
        context.bot,
        chat_id,
        text="🏫 الرجاء اختيار الصف الدراسي:",
        reply_markup=keyboard
    )
    return REGISTRATION_GRADE

# معالجة اختيار الصف الدراسي
async def registration_grade(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار الصف الدراسي في عملية التسجيل"""
    query = update.callback_query
    user = update.effective_user
    chat_id = query.message.chat_id
    
    # استخراج الصف الدراسي من البيانات المرسلة
    grade_data = query.data
    
    # التحقق من صحة البيانات
    if not grade_data.startswith("grade_"):
        await query.answer("خيار غير صحيح")
        return REGISTRATION_GRADE
    
    # استخراج الصف الدراسي
    grade = grade_data.replace("grade_", "")
    
    # تخزين الصف الدراسي في بيانات التسجيل المؤقتة
    context.user_data['registration_data']['grade'] = grade
    
    # تأكيد المعلومات
    await query.answer()
    
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
    return REGISTRATION_CONFIRM

# معالجة تأكيد المعلومات
async def registration_confirm(update: Update, context: CallbackContext) -> int:
    """معالجة تأكيد المعلومات في عملية التسجيل"""
    query = update.callback_query
    user = update.effective_user
    chat_id = query.message.chat_id
    
    # استخراج الإجراء من البيانات المرسلة
    action = query.data
    
    # التحقق من صحة البيانات
    if action not in ["confirm_registration", "edit_name", "edit_email", "edit_phone", "edit_grade"]:
        await query.answer("خيار غير صحيح")
        return REGISTRATION_CONFIRM
    
    await query.answer()
    
    # معالجة الإجراء
    if action == "confirm_registration":
        # تأكيد المعلومات وحفظها في قاعدة البيانات
        registration_data = context.user_data['registration_data']
        
        # الحصول على مدير قاعدة البيانات
        db_manager = context.bot_data.get("DB_MANAGER")
        if not db_manager:
            logger.error(f"لا يمكن الوصول إلى DB_MANAGER في registration_confirm للمستخدم {user.id}")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
            )
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
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="⚠️ حدث خطأ في حفظ المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
            )
            return ConversationHandler.END
        
        # تحديث حالة التسجيل في context.user_data
        context.user_data['is_registered'] = True
        
        # إرسال رسالة تأكيد
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="✅ تم تسجيل معلوماتك بنجاح! يمكنك الآن استخدام جميع ميزات البوت."
        )
        
        # عرض القائمة الرئيسية
        try:
            from handlers.common import main_menu_callback
        except ImportError:
            try:
                from common import main_menu_callback
            except ImportError as e:
                logger.error(f"خطأ في استيراد main_menu_callback: {e}")
                # إذا لم نتمكن من استيراد main_menu_callback، نعرض القائمة الرئيسية هنا
                menu_text = "القائمة الرئيسية:"
                keyboard = create_main_menu_keyboard(user.id, db_manager)
                await safe_send_message(
                    context.bot,
                    chat_id,
                    text=menu_text,
                    reply_markup=keyboard
                )
                return ConversationHandler.END
        
        # استدعاء main_menu_callback لعرض القائمة الرئيسية
        await main_menu_callback(update, context)
        return ConversationHandler.END
    
    elif action == "edit_name":
        # تعديل الاسم
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="👤 الرجاء إدخال الاسم الكامل:"
        )
        return REGISTRATION_NAME
    
    elif action == "edit_email":
        # تعديل البريد الإلكتروني
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="📧 الرجاء إدخال البريد الإلكتروني:"
        )
        return REGISTRATION_EMAIL
    
    elif action == "edit_phone":
        # تعديل رقم الجوال
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="📱 الرجاء إدخال رقم الجوال (يبدأ بـ 05 أو +966 أو 00966):"
        )
        return REGISTRATION_PHONE
    
    elif action == "edit_grade":
        # تعديل الصف الدراسي
        keyboard = create_grade_keyboard()
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="🏫 الرجاء اختيار الصف الدراسي:",
            reply_markup=keyboard
        )
        return REGISTRATION_GRADE

# معالجة أمر تعديل المعلومات
async def edit_info_command(update: Update, context: CallbackContext) -> int:
    """معالجة أمر تعديل المعلومات"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في edit_info_command للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # الحصول على معلومات المستخدم
    user_info = get_user_info(db_manager, user.id)
    
    # التحقق من وجود المستخدم
    if not user_info:
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ لم يتم العثور على معلوماتك. يرجى استخدام الأمر /start للتسجيل أولاً."
        )
        return ConversationHandler.END
    
    # تهيئة بيانات التسجيل المؤقتة
    context.user_data['registration_data'] = {
        'full_name': user_info.get('full_name', ''),
        'email': user_info.get('email', ''),
        'phone': user_info.get('phone', ''),
        'grade': user_info.get('grade', '')
    }
    
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
    return EDIT_USER_INFO_MENU

# معالجة اختيار قائمة تعديل المعلومات
async def edit_info_menu(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار قائمة تعديل المعلومات"""
    query = update.callback_query
    user = update.effective_user
    chat_id = query.message.chat_id
    
    # استخراج الإجراء من البيانات المرسلة
    action = query.data
    
    # التحقق من صحة البيانات
    if action not in ["edit_name", "edit_email", "edit_phone", "edit_grade", "main_menu"]:
        await query.answer("خيار غير صحيح")
        return EDIT_USER_INFO_MENU
    
    await query.answer()
    
    # معالجة الإجراء
    if action == "edit_name":
        # تعديل الاسم
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="👤 الرجاء إدخال الاسم الكامل:"
        )
        return EDIT_USER_NAME
    
    elif action == "edit_email":
        # تعديل البريد الإلكتروني
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="📧 الرجاء إدخال البريد الإلكتروني:"
        )
        return EDIT_USER_EMAIL
    
    elif action == "edit_phone":
        # تعديل رقم الجوال
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="📱 الرجاء إدخال رقم الجوال (يبدأ بـ 05 أو +966 أو 00966):"
        )
        return EDIT_USER_PHONE
    
    elif action == "edit_grade":
        # تعديل الصف الدراسي
        keyboard = create_grade_keyboard()
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="🏫 الرجاء اختيار الصف الدراسي:",
            reply_markup=keyboard
        )
        return EDIT_USER_GRADE
    
    elif action == "main_menu":
        # العودة للقائمة الرئيسية
        try:
            from handlers.common import main_menu_callback
        except ImportError:
            try:
                from common import main_menu_callback
            except ImportError as e:
                logger.error(f"خطأ في استيراد main_menu_callback: {e}")
                # إذا لم نتمكن من استيراد main_menu_callback، نعرض القائمة الرئيسية هنا
                menu_text = "القائمة الرئيسية:"
                db_manager = context.bot_data.get("DB_MANAGER")
                keyboard = create_main_menu_keyboard(user.id, db_manager)
                await safe_edit_message_text(
                    context.bot,
                    chat_id,
                    query.message.message_id,
                    text=menu_text,
                    reply_markup=keyboard
                )
                return ConversationHandler.END
        
        # استدعاء main_menu_callback لعرض القائمة الرئيسية
        await main_menu_callback(update, context)
        return ConversationHandler.END

# معالجة تعديل الاسم
async def edit_user_name(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل الاسم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    full_name = update.message.text.strip()
    
    # التحقق من صحة الاسم
    if len(full_name) < 3:
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ الاسم قصير جداً. الرجاء إدخال الاسم الكامل (3 أحرف على الأقل):"
        )
        return EDIT_USER_NAME
    
    # تخزين الاسم في بيانات التسجيل المؤقتة
    context.user_data['registration_data']['full_name'] = full_name
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في edit_user_name للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # حفظ المعلومات في قاعدة البيانات
    success = save_user_info(
        db_manager,
        user.id,
        full_name=full_name
    )
    
    if not success:
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في حفظ المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
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
             f"👤 الاسم: {full_name}\n"
             f"📧 البريد الإلكتروني: {context.user_data['registration_data'].get('email', '')}\n"
             f"📱 رقم الجوال: {context.user_data['registration_data'].get('phone', '')}\n"
             f"🏫 الصف الدراسي: {context.user_data['registration_data'].get('grade', '')}\n\n"
             "الرجاء اختيار المعلومات التي ترغب في تعديلها:",
        reply_markup=keyboard
    )
    return EDIT_USER_INFO_MENU

# معالجة تعديل البريد الإلكتروني
async def edit_user_email(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل البريد الإلكتروني"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    email = update.message.text.strip()
    
    # التحقق من صحة البريد الإلكتروني
    if not is_valid_email(email):
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ البريد الإلكتروني غير صحيح. الرجاء إدخال بريد إلكتروني صحيح:"
        )
        return EDIT_USER_EMAIL
    
    # تخزين البريد الإلكتروني في بيانات التسجيل المؤقتة
    context.user_data['registration_data']['email'] = email
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في edit_user_email للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # حفظ المعلومات في قاعدة البيانات
    success = save_user_info(
        db_manager,
        user.id,
        email=email
    )
    
    if not success:
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في حفظ المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
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
    return EDIT_USER_INFO_MENU

# معالجة تعديل رقم الجوال
async def edit_user_phone(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل رقم الجوال"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    phone = update.message.text.strip()
    
    # التحقق من صحة رقم الجوال
    if not is_valid_phone(phone):
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ رقم الجوال غير صحيح. الرجاء إدخال رقم جوال سعودي صحيح (يبدأ بـ 05 أو +966 أو 00966):"
        )
        return EDIT_USER_PHONE
    
    # تخزين رقم الجوال في بيانات التسجيل المؤقتة
    context.user_data['registration_data']['phone'] = phone
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في edit_user_phone للمستخدم {user.id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # حفظ المعلومات في قاعدة البيانات
    success = save_user_info(
        db_manager,
        user.id,
        phone=phone
    )
    
    if not success:
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في حفظ المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
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
    return EDIT_USER_INFO_MENU

# معالجة تعديل الصف الدراسي
async def edit_user_grade(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل الصف الدراسي"""
    query = update.callback_query
    user = update.effective_user
    chat_id = query.message.chat_id
    
    # استخراج الصف الدراسي من البيانات المرسلة
    grade_data = query.data
    
    # التحقق من صحة البيانات
    if not grade_data.startswith("grade_"):
        await query.answer("خيار غير صحيح")
        return EDIT_USER_GRADE
    
    # استخراج الصف الدراسي
    grade = grade_data.replace("grade_", "")
    
    # تخزين الصف الدراسي في بيانات التسجيل المؤقتة
    context.user_data['registration_data']['grade'] = grade
    
    # تأكيد المعلومات
    await query.answer()
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في edit_user_grade للمستخدم {user.id}")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # حفظ المعلومات في قاعدة البيانات
    success = save_user_info(
        db_manager,
        user.id,
        grade=grade
    )
    
    if not success:
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="⚠️ حدث خطأ في حفظ المعلومات. يرجى المحاولة مرة أخرى لاحقاً."
        )
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
    return EDIT_USER_INFO_MENU

# إنشاء معالج محادثة التسجيل
registration_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('register', start_registration)],
    states={
        REGISTRATION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_name)],
        REGISTRATION_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_email)],
        REGISTRATION_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, registration_phone)],
        REGISTRATION_GRADE: [CallbackQueryHandler(registration_grade, pattern=r'^grade_')],
        REGISTRATION_CONFIRM: [CallbackQueryHandler(registration_confirm, pattern=r'^(confirm_registration|edit_name|edit_email|edit_phone|edit_grade)$')],
    },
    fallbacks=[CommandHandler('cancel', lambda update, context: ConversationHandler.END)],
    name="registration_conversation",
    persistent=False
)

# إنشاء معالج محادثة تعديل المعلومات
edit_info_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('edit_info', edit_info_command),
        CallbackQueryHandler(edit_info_menu, pattern=r'^edit_my_info$')
    ],
    states={
        EDIT_USER_INFO_MENU: [CallbackQueryHandler(edit_info_menu, pattern=r'^(edit_name|edit_email|edit_phone|edit_grade|main_menu)$')],
        EDIT_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_user_name)],
        EDIT_USER_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_user_email)],
        EDIT_USER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_user_phone)],
        EDIT_USER_GRADE: [CallbackQueryHandler(edit_user_grade, pattern=r'^grade_')],
    },
    fallbacks=[CommandHandler('cancel', lambda update, context: ConversationHandler.END)],
    name="edit_info_conversation",
    persistent=False
)

# إنشاء معالج أمر /start
start_handler = CommandHandler('start', start_command)
