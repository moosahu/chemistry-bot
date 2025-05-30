#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
منطق التسجيل الإلزامي للمستخدمين في بوت الاختبارات
يتضمن جمع الاسم، البريد الإلكتروني، رقم الجوال، والصف الدراسي
"""

import logging
import re
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
REGISTRATION_GRADE = 23
REGISTRATION_CONFIRM = 24
EDIT_USER_INFO_MENU = 25
EDIT_USER_NAME = 26
EDIT_USER_EMAIL = 27
EDIT_USER_PHONE = 28
EDIT_USER_GRADE = 29

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
    
    # التحقق من وجود المعلومات الأساسية
    has_basic_info = False
    if user_info:
        logger.info(f"معلومات المستخدم {user_id}: is_registered = {user_info.get('is_registered')}, نوع: {type(user_info.get('is_registered'))}")
        
        # التحقق من أن جميع المعلومات الأساسية موجودة وليست None أو 'None'
        has_full_name = user_info.get('full_name') not in [None, 'None', '']
        has_email = user_info.get('email') not in [None, 'None', '']
        has_phone = user_info.get('phone') not in [None, 'None', '']
        has_grade = user_info.get('grade') not in [None, 'None', '']
        
        has_basic_info = all([has_full_name, has_email, has_phone, has_grade])
        
        logger.info(f"المستخدم {user_id} لديه معلومات أساسية: {has_basic_info}")
        logger.info(f"تفاصيل: الاسم: {has_full_name}, البريد: {has_email}, الجوال: {has_phone}, الصف: {has_grade}")
        
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
    
    return Truenc def start_registration(update: Update, context: CallbackContext) -> int:
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
        await safe_send_message(
            context.bot, 
            chat_id, 
            text="رقم الجوال غير صحيح. يرجى إدخال رقم جوال صالح (مثال: 05xxxxxxxx أو +966xxxxxxxxx):"
        )
        return REGISTRATION_PHONE
    
    # حفظ رقم الجوال في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['phone'] = phone
    
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
    await query.answer()
    
    user = update.effective_user
    chat_id = update.effective_chat.id
    grade_data = query.data
    
    # استخراج الصف الدراسي من البيانات
    if grade_data.startswith("grade_"):
        grade_type = grade_data.split("_")[1]
        
        if grade_type in ["secondary"]:
            grade_number = grade_data.split("_")[2]
            grade_text = f"الصف {grade_number} الثانوي"
        elif grade_type == "university":
            grade_text = "طالب جامعي"
        elif grade_type == "teacher":
            grade_text = "معلم"
        elif grade_type == "other":
            grade_text = "أخرى"
        else:
            grade_text = "غير محدد"
        
        # حفظ الصف الدراسي في بيانات المستخدم المؤقتة
        context.user_data['registration_data']['grade'] = grade_text
        
        # عرض ملخص المعلومات للتأكيد
        registration_data = context.user_data['registration_data']
        confirmation_text = "مراجعة معلومات التسجيل:\n\n" \
                           f"الاسم: {registration_data.get('full_name')}\n" \
                           f"البريد الإلكتروني: {registration_data.get('email')}\n" \
                           f"رقم الجوال: {registration_data.get('phone')}\n" \
                           f"الصف الدراسي: {grade_text}\n\n" \
                           "هل المعلومات صحيحة؟"
        
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=confirmation_text,
            reply_markup=create_confirmation_keyboard()
        )
        return REGISTRATION_CONFIRM
    
    # في حالة حدوث خطأ
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
    await query.answer()
    
    user = update.effective_user
    chat_id = update.effective_chat.id
    action = query.data
    
    if action == "confirm_registration":
        # حفظ معلومات التسجيل في قاعدة البيانات
        registration_data = context.user_data['registration_data']
        db_manager = context.bot_data.get("DB_MANAGER")
        
        if db_manager:
            # تحديث معلومات المستخدم في قاعدة البيانات
            success = save_user_info(
                db_manager=db_manager,
                user_id=user.id,
                first_name=user.first_name,
                last_name=user.last_name,
                username=user.username,
                language_code=user.language_code,
                full_name=registration_data.get('full_name'),
                email=registration_data.get('email'),
                phone=registration_data.get('phone'),
                grade=registration_data.get('grade'),
                is_registered=True
            )
            
            if success:
                logger.info(f"تم تسجيل المستخدم {user.id} بنجاح")
            else:
                logger.error(f"فشل تسجيل المستخدم {user.id}")
        else:
            logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_registration_confirmation للمستخدم {user.id}")
        
        # إظهار رسالة نجاح التسجيل
        success_text = f"تم التسجيل بنجاح! 🎉\n\nمرحباً بك {registration_data.get('full_name')} في بوت الاختبارات.\n\nيمكنك الآن استخدام جميع ميزات البوت."
        
        # إنشاء لوحة مفاتيح القائمة الرئيسية
        keyboard = create_main_menu_keyboard(user.id, db_manager)
        
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=success_text,
            reply_markup=keyboard
        )
        
        # تنظيف بيانات التسجيل المؤقتة
        if 'registration_data' in context.user_data:
            del context.user_data['registration_data']
        
        return MAIN_MENU
    
    elif action == "edit_name":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال اسمك الكامل مرة أخرى:"
        )
        return REGISTRATION_NAME
    
    elif action == "edit_email":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال بريدك الإلكتروني مرة أخرى:"
        )
        return REGISTRATION_EMAIL
    
    elif action == "edit_phone":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال رقم جوالك مرة أخرى (مثال: 05xxxxxxxx أو +966xxxxxxxxx):"
        )
        return REGISTRATION_PHONE
    
    elif action == "edit_grade":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى اختيار الصف الدراسي مرة أخرى:",
            reply_markup=create_grade_keyboard()
        )
        return REGISTRATION_GRADE
    
    # في حالة حدوث خطأ
    registration_data = context.user_data.get('registration_data', {})
    confirmation_text = "مراجعة معلومات التسجيل:\n\n" \
                       f"الاسم: {registration_data.get('full_name', 'غير محدد')}\n" \
                       f"البريد الإلكتروني: {registration_data.get('email', 'غير محدد')}\n" \
                       f"رقم الجوال: {registration_data.get('phone', 'غير محدد')}\n" \
                       f"الصف الدراسي: {registration_data.get('grade', 'غير محدد')}\n\n" \
                       "هل المعلومات صحيحة؟"
    
    await safe_edit_message_text(
        context.bot,
        chat_id,
        query.message.message_id,
        text=confirmation_text,
        reply_markup=create_confirmation_keyboard()
    )
    return REGISTRATION_CONFIRM

# بدء تعديل معلومات المستخدم
async def start_edit_user_info(update: Update, context: CallbackContext) -> int:
    """بدء عملية تعديل معلومات المستخدم"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # التحقق من حالة التسجيل أولاً
    db_manager = context.bot_data.get("DB_MANAGER")
    is_registered = await check_registration_status(update, context, db_manager)
    
    # إذا لم يكن المستخدم مسجلاً، سيتم توجيهه للتسجيل في check_registration_status
    if not is_registered:
        return REGISTRATION_NAME
    
    # الحصول على معلومات المستخدم من قاعدة البيانات
    user_info = get_user_info(db_manager, user.id)
    
    if not user_info:
        user_info = {
            'full_name': 'غير محدد',
            'email': 'غير محدد',
            'phone': 'غير محدد',
            'grade': 'غير محدد'
        }
    
    # معالجة القيم None واستبدالها بـ "غير محدد"
    processed_user_info = {
        'full_name': user_info.get('full_name') if user_info.get('full_name') not in [None, 'None'] else 'غير محدد',
        'email': user_info.get('email') if user_info.get('email') not in [None, 'None'] else 'غير محدد',
        'phone': user_info.get('phone') if user_info.get('phone') not in [None, 'None'] else 'غير محدد',
        'grade': user_info.get('grade') if user_info.get('grade') not in [None, 'None'] else 'غير محدد',
        'is_registered': user_info.get('is_registered', False)
    }
    
    # حفظ معلومات المستخدم المعالجة في user_data
    context.user_data['edit_user_info'] = processed_user_info
    
    # عرض معلومات المستخدم الحالية
    info_text = "معلوماتك الحالية:\n\n" \
               f"الاسم: {processed_user_info['full_name']}\n" \
               f"البريد الإلكتروني: {processed_user_info['email']}\n" \
               f"رقم الجوال: {processed_user_info['phone']}\n" \
               f"الصف الدراسي: {processed_user_info['grade']}\n\n" \
               "اختر المعلومات التي ترغب في تعديلها:"
    
    # التحقق مما إذا كان الاستدعاء من زر inline button أو من أمر نصي
    if update.callback_query:
        # إذا كان من زر، نستخدم edit_message_text لتعديل الرسالة الحالية
        query = update.callback_query
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
        )
    else:
        # إذا كان من أمر نصي، نستخدم send_message لإرسال رسالة جديدة
        await safe_send_message(
            context.bot,
            chat_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
    )
    return EDIT_USER_INFO_MENU

# معالجة اختيارات تعديل المعلومات
async def handle_edit_info_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيارات تعديل معلومات المستخدم"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    chat_id = update.effective_chat.id
    action = query.data
    
    if action == "edit_name":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال اسمك الكامل الجديد:"
        )
        return EDIT_USER_NAME
    
    elif action == "edit_email":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال بريدك الإلكتروني الجديد:"
        )
        return EDIT_USER_EMAIL
    
    elif action == "edit_phone":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى إدخال رقم جوالك الجديد (مثال: 05xxxxxxxx أو +966xxxxxxxxx):"
        )
        return EDIT_USER_PHONE
    
    elif action == "edit_grade":
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى اختيار الصف الدراسي الجديد:",
            reply_markup=create_grade_keyboard()
        )
        return EDIT_USER_GRADE
    
    elif action == "main_menu":
        # إعادة توجيه المستخدم إلى القائمة الرئيسية
        menu_text = "القائمة الرئيسية:"
        keyboard = create_main_menu_keyboard(user.id)
        
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=menu_text,
            reply_markup=keyboard
        )
        
        # استدعاء دالة القائمة الرئيسية من handlers.common
        try:
            from handlers.common import main_menu_callback
            # تعديل هنا: إرجاع END بدلاً من استدعاء main_menu_callback
            return END
        except ImportError:
            # تعديل هنا: إرجاع END بدلاً من MAIN_MENU
            return END
    
    # في حالة حدوث خطأ
    user_info = context.user_data.get('edit_user_info', {})
    info_text = "معلوماتك الحالية:\n\n" \
               f"الاسم: {user_info.get('full_name', 'غير محدد')}\n" \
               f"البريد الإلكتروني: {user_info.get('email', 'غير محدد')}\n" \
               f"رقم الجوال: {user_info.get('phone', 'غير محدد')}\n" \
               f"الصف الدراسي: {user_info.get('grade', 'غير محدد')}\n\n" \
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
        await safe_send_message(context.bot, chat_id, text="الاسم قصير جداً. يرجى إدخال اسمك الكامل:")
        return EDIT_USER_NAME
    
    # تحديث الاسم في بيانات المستخدم المؤقتة
    user_info = context.user_data.get('edit_user_info', {})
    user_info['full_name'] = name
    context.user_data['edit_user_info'] = user_info
    
    # تحديث معلومات المستخدم في قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if db_manager:
        success = save_user_info(
            db_manager=db_manager,
            user_id=user.id,
            full_name=name,
            is_registered=True
        )
        
        if success:
            logger.info(f"تم تحديث اسم المستخدم {user.id} إلى {name}")
        else:
            logger.error(f"فشل تحديث اسم المستخدم {user.id}")
    
    # عرض معلومات المستخدم المحدثة
    info_text = "تم تحديث معلوماتك بنجاح!\n\n" \
               f"الاسم: {name}\n" \
               f"البريد الإلكتروني: {user_info.get('email', 'غير محدد')}\n" \
               f"رقم الجوال: {user_info.get('phone', 'غير محدد')}\n" \
               f"الصف الدراسي: {user_info.get('grade', 'غير محدد')}\n\n" \
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
    
    # تحديث البريد الإلكتروني في بيانات المستخدم المؤقتة
    user_info = context.user_data.get('edit_user_info', {})
    user_info['email'] = email
    context.user_data['edit_user_info'] = user_info
    
    # تحديث معلومات المستخدم في قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if db_manager:
        success = save_user_info(
            db_manager=db_manager,
            user_id=user.id,
            email=email,
            is_registered=True
        )
        
        if success:
            logger.info(f"تم تحديث البريد الإلكتروني للمستخدم {user.id} إلى {email}")
        else:
            logger.error(f"فشل تحديث البريد الإلكتروني للمستخدم {user.id}")
    
    # عرض معلومات المستخدم المحدثة
    info_text = "تم تحديث معلوماتك بنجاح!\n\n" \
               f"الاسم: {user_info.get('full_name', 'غير محدد')}\n" \
               f"البريد الإلكتروني: {email}\n" \
               f"رقم الجوال: {user_info.get('phone', 'غير محدد')}\n" \
               f"الصف الدراسي: {user_info.get('grade', 'غير محدد')}\n\n" \
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
            text="رقم الجوال غير صحيح. يرجى إدخال رقم جوال صالح (مثال: 05xxxxxxxx أو +966xxxxxxxxx):"
        )
        return EDIT_USER_PHONE
    
    # تحديث رقم الجوال في بيانات المستخدم المؤقتة
    user_info = context.user_data.get('edit_user_info', {})
    user_info['phone'] = phone
    context.user_data['edit_user_info'] = user_info
    
    # تحديث معلومات المستخدم في قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if db_manager:
        success = save_user_info(
            db_manager=db_manager,
            user_id=user.id,
            phone=phone,
            is_registered=True
        )
        
        if success:
            logger.info(f"تم تحديث رقم الجوال للمستخدم {user.id} إلى {phone}")
        else:
            logger.error(f"فشل تحديث رقم الجوال للمستخدم {user.id}")
    
    # عرض معلومات المستخدم المحدثة
    info_text = "تم تحديث معلوماتك بنجاح!\n\n" \
               f"الاسم: {user_info.get('full_name', 'غير محدد')}\n" \
               f"البريد الإلكتروني: {user_info.get('email', 'غير محدد')}\n" \
               f"رقم الجوال: {phone}\n" \
               f"الصف الدراسي: {user_info.get('grade', 'غير محدد')}\n\n" \
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
    await query.answer()
    
    user = update.effective_user
    chat_id = update.effective_chat.id
    grade_data = query.data
    
    # استخراج الصف الدراسي من البيانات
    if grade_data.startswith("grade_"):
        grade_type = grade_data.split("_")[1]
        
        if grade_type in ["secondary"]:
            grade_number = grade_data.split("_")[2]
            grade_text = f"الصف {grade_number} الثانوي"
        elif grade_type == "university":
            grade_text = "طالب جامعي"
        elif grade_type == "teacher":
            grade_text = "معلم"
        elif grade_type == "other":
            grade_text = "أخرى"
        else:
            grade_text = "غير محدد"
        
        # تحديث الصف الدراسي في بيانات المستخدم المؤقتة
        user_info = context.user_data.get('edit_user_info', {})
        user_info['grade'] = grade_text
        context.user_data['edit_user_info'] = user_info
        
        # تحديث معلومات المستخدم في قاعدة البيانات
        db_manager = context.bot_data.get("DB_MANAGER")
        if db_manager:
            success = save_user_info(
                db_manager=db_manager,
                user_id=user.id,
                grade=grade_text,
                is_registered=True
            )
            
            if success:
                logger.info(f"تم تحديث الصف الدراسي للمستخدم {user.id} إلى {grade_text}")
            else:
                logger.error(f"فشل تحديث الصف الدراسي للمستخدم {user.id}")
        
        # عرض معلومات المستخدم المحدثة
        info_text = "تم تحديث معلوماتك بنجاح!\n\n" \
                   f"الاسم: {user_info.get('full_name', 'غير محدد')}\n" \
                   f"البريد الإلكتروني: {user_info.get('email', 'غير محدد')}\n" \
                   f"رقم الجوال: {user_info.get('phone', 'غير محدد')}\n" \
                   f"الصف الدراسي: {grade_text}\n\n" \
                   "هل ترغب في تعديل معلومات أخرى؟"
        
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
        )
        return EDIT_USER_INFO_MENU
    
    # في حالة حدوث خطأ
    await safe_edit_message_text(
        context.bot,
        chat_id,
        query.message.message_id,
        text="حدث خطأ في اختيار الصف الدراسي. يرجى المحاولة مرة أخرى:",
        reply_markup=create_grade_keyboard()
    )
    return EDIT_USER_GRADE

# إنشاء محادثة التسجيل
registration_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("register", start_registration),
        CommandHandler("start", start_registration)
    ],
    states={
        REGISTRATION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name_input)],
        REGISTRATION_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_input)],
        REGISTRATION_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone_input)],
        REGISTRATION_GRADE: [CallbackQueryHandler(handle_grade_selection, pattern=r"^grade_")],
        REGISTRATION_CONFIRM: [CallbackQueryHandler(handle_registration_confirmation)]
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: END)],
    name="registration_conversation",
    persistent=False
)

# إنشاء محادثة تعديل المعلومات
edit_info_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("edit_info", start_edit_user_info),
        CallbackQueryHandler(start_edit_user_info, pattern=r"^edit_my_info$")
    ],
    states={
        EDIT_USER_INFO_MENU: [CallbackQueryHandler(handle_edit_info_selection)],
        EDIT_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_name)],
        EDIT_USER_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_email)],
        EDIT_USER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_phone)],
        EDIT_USER_GRADE: [CallbackQueryHandler(handle_edit_grade, pattern=r"^grade_")]
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: END)],
    name="edit_info_conversation",
    persistent=False
)
