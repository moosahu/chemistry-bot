#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
منطق التسجيل الإلزامي للمستخدمين في بوت الاختبارات
يتضمن جمع الاسم، البريد الإلكتروني، والصف الدراسي
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

# استيراد الثوابت والمكونات اللازمة
try:
    from config import (
        logger,
        MAIN_MENU,
        REGISTRATION_NAME, REGISTRATION_EMAIL, REGISTRATION_GRADE, REGISTRATION_CONFIRM,
        EDIT_USER_INFO_MENU, EDIT_USER_NAME, EDIT_USER_EMAIL, EDIT_USER_GRADE,
        END
    )
    from ..utils.helpers import safe_send_message, safe_edit_message_text
except ImportError as e:
    # استخدام قيم افتراضية في حالة فشل الاستيراد
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"خطأ في استيراد الوحدات في registration.py: {e}. استخدام قيم افتراضية.")
    
    # تعريف ثوابت افتراضية
    MAIN_MENU = 0
    REGISTRATION_NAME, REGISTRATION_EMAIL, REGISTRATION_GRADE, REGISTRATION_CONFIRM = range(20, 24)
    EDIT_USER_INFO_MENU, EDIT_USER_NAME, EDIT_USER_EMAIL, EDIT_USER_GRADE = range(24, 28)
    END = -1
    
    # دوال مساعدة افتراضية
    async def safe_send_message(bot, chat_id, text, reply_markup=None, parse_mode=None):
        logger.error("استدعاء دالة safe_send_message الافتراضية!")
        try: await bot.send_message(chat_id=chat_id, text="خطأ: وظيفة البوت غير متاحة.")
        except: pass
    
    async def safe_edit_message_text(bot, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        logger.error("استدعاء دالة safe_edit_message_text الافتراضية!")
        try: await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="خطأ: وظيفة البوت غير متاحة.", reply_markup=reply_markup, parse_mode=parse_mode)
        except: pass

# التحقق من صحة البريد الإلكتروني
def is_valid_email(email):
    """التحقق من صحة تنسيق البريد الإلكتروني"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

# إنشاء لوحة مفاتيح للصفوف الدراسية
def create_grade_keyboard():
    """إنشاء لوحة مفاتيح للصفوف الدراسية"""
    keyboard = []
    
    # الصفوف الابتدائية
    primary_row = []
    for grade in range(1, 7):
        primary_row.append(InlineKeyboardButton(f"ابتدائي {grade}", callback_data=f"grade_primary_{grade}"))
        if len(primary_row) == 3:
            keyboard.append(primary_row)
            primary_row = []
    if primary_row:
        keyboard.append(primary_row)
    
    # الصفوف المتوسطة
    middle_row = []
    for grade in range(1, 4):
        middle_row.append(InlineKeyboardButton(f"متوسط {grade}", callback_data=f"grade_middle_{grade}"))
    keyboard.append(middle_row)
    
    # الصفوف الثانوية
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
        [InlineKeyboardButton("✏️ تعديل الصف الدراسي", callback_data="edit_grade")]
    ]
    return InlineKeyboardMarkup(keyboard)

# إنشاء لوحة مفاتيح لتعديل المعلومات
def create_edit_info_keyboard():
    """إنشاء لوحة مفاتيح لتعديل معلومات المستخدم"""
    keyboard = [
        [InlineKeyboardButton("✏️ تعديل الاسم", callback_data="edit_name")],
        [InlineKeyboardButton("✏️ تعديل البريد الإلكتروني", callback_data="edit_email")],
        [InlineKeyboardButton("✏️ تعديل الصف الدراسي", callback_data="edit_grade")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# التحقق من حالة تسجيل المستخدم
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
            return True  # نفترض أن المستخدم مسجل في حالة عدم وجود مدير قاعدة بيانات
    
    # التحقق من حالة تسجيل المستخدم
    user_info = db_manager.get_user_info(user_id) if hasattr(db_manager, 'get_user_info') else None
    
    # إذا لم يكن هناك معلومات للمستخدم أو لم يكمل التسجيل
    if not user_info or not user_info.get('is_registered', False):
        logger.info(f"المستخدم {user_id} غير مسجل، توجيهه لإكمال التسجيل")
        await start_registration(update, context)
        return False
    
    return True

# بدء عملية التسجيل
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
    
    # طلب اختيار الصف الدراسي
    await safe_send_message(
        context.bot, 
        chat_id, 
        text="الخطوة الثالثة: اختر الصف الدراسي:",
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
        
        if grade_type in ["primary", "middle", "secondary"]:
            grade_number = grade_data.split("_")[2]
            if grade_type == "primary":
                grade_text = f"الصف {grade_number} الابتدائي"
            elif grade_type == "middle":
                grade_text = f"الصف {grade_number} المتوسط"
            elif grade_type == "secondary":
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
            try:
                db_manager.register_or_update_user(
                    user_id=user.id,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    username=user.username,
                    language_code=user.language_code,
                    full_name=registration_data.get('full_name'),
                    email=registration_data.get('email'),
                    grade=registration_data.get('grade'),
                    is_registered=True
                )
                logger.info(f"تم تسجيل المستخدم {user.id} بنجاح")
            except Exception as e:
                logger.error(f"خطأ في تسجيل المستخدم {user.id}: {e}")
        else:
            logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_registration_confirmation للمستخدم {user.id}")
        
        # إظهار رسالة نجاح التسجيل
        success_text = f"تم التسجيل بنجاح! 🎉\n\nمرحباً بك {registration_data.get('full_name')} في بوت الاختبارات.\n\nيمكنك الآن استخدام جميع ميزات البوت."
        
        # إعادة توجيه المستخدم إلى القائمة الرئيسية
        from handlers.common import create_main_menu_keyboard
        keyboard = create_main_menu_keyboard(user.id)
        
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
    
    # الحصول على معلومات المستخدم من قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    user_info = None
    
    if db_manager and hasattr(db_manager, 'get_user_info'):
        try:
            user_info = db_manager.get_user_info(user.id)
        except Exception as e:
            logger.error(f"خطأ في الحصول على معلومات المستخدم {user.id}: {e}")
    
    if not user_info:
        user_info = {
            'full_name': 'غير محدد',
            'email': 'غير محدد',
            'grade': 'غير محدد'
        }
    
    # حفظ معلومات المستخدم الحالية في user_data
    context.user_data['edit_user_info'] = user_info
    
    # عرض معلومات المستخدم الحالية
    info_text = "معلوماتك الحالية:\n\n" \
               f"الاسم: {user_info.get('full_name', 'غير محدد')}\n" \
               f"البريد الإلكتروني: {user_info.get('email', 'غير محدد')}\n" \
               f"الصف الدراسي: {user_info.get('grade', 'غير محدد')}\n\n" \
               "اختر المعلومات التي ترغب في تعديلها:"
    
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
        from handlers.common import main_menu_callback
        return await main_menu_callback(update, context)
    
    # في حالة حدوث خطأ
    user_info = context.user_data.get('edit_user_info', {})
    info_text = "معلوماتك الحالية:\n\n" \
               f"الاسم: {user_info.get('full_name', 'غير محدد')}\n" \
               f"البريد الإلكتروني: {user_info.get('email', 'غير محدد')}\n" \
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
        try:
            db_manager.register_or_update_user(
                user_id=user.id,
                full_name=name,
                # الحفاظ على البيانات الأخرى كما هي
                email=user_info.get('email'),
                grade=user_info.get('grade'),
                is_registered=True
            )
            logger.info(f"تم تحديث اسم المستخدم {user.id} إلى {name}")
        except Exception as e:
            logger.error(f"خطأ في تحديث اسم المستخدم {user.id}: {e}")
    
    # عرض معلومات المستخدم المحدثة
    info_text = "تم تحديث معلوماتك بنجاح!\n\n" \
               f"الاسم: {name}\n" \
               f"البريد الإلكتروني: {user_info.get('email', 'غير محدد')}\n" \
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
        try:
            db_manager.register_or_update_user(
                user_id=user.id,
                email=email,
                # الحفاظ على البيانات الأخرى كما هي
                full_name=user_info.get('full_name'),
                grade=user_info.get('grade'),
                is_registered=True
            )
            logger.info(f"تم تحديث البريد الإلكتروني للمستخدم {user.id} إلى {email}")
        except Exception as e:
            logger.error(f"خطأ في تحديث البريد الإلكتروني للمستخدم {user.id}: {e}")
    
    # عرض معلومات المستخدم المحدثة
    info_text = "تم تحديث معلوماتك بنجاح!\n\n" \
               f"الاسم: {user_info.get('full_name', 'غير محدد')}\n" \
               f"البريد الإلكتروني: {email}\n" \
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
        
        if grade_type in ["primary", "middle", "secondary"]:
            grade_number = grade_data.split("_")[2]
            if grade_type == "primary":
                grade_text = f"الصف {grade_number} الابتدائي"
            elif grade_type == "middle":
                grade_text = f"الصف {grade_number} المتوسط"
            elif grade_type == "secondary":
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
            try:
                db_manager.register_or_update_user(
                    user_id=user.id,
                    grade=grade_text,
                    # الحفاظ على البيانات الأخرى كما هي
                    full_name=user_info.get('full_name'),
                    email=user_info.get('email'),
                    is_registered=True
                )
                logger.info(f"تم تحديث الصف الدراسي للمستخدم {user.id} إلى {grade_text}")
            except Exception as e:
                logger.error(f"خطأ في تحديث الصف الدراسي للمستخدم {user.id}: {e}")
        
        # عرض معلومات المستخدم المحدثة
        info_text = "تم تحديث معلوماتك بنجاح!\n\n" \
                   f"الاسم: {user_info.get('full_name', 'غير محدد')}\n" \
                   f"البريد الإلكتروني: {user_info.get('email', 'غير محدد')}\n" \
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
        CommandHandler("edit_info", start_edit_user_info)
    ],
    states={
        EDIT_USER_INFO_MENU: [CallbackQueryHandler(handle_edit_info_selection)],
        EDIT_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_name)],
        EDIT_USER_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_email)],
        EDIT_USER_GRADE: [CallbackQueryHandler(handle_edit_grade, pattern=r"^grade_")]
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: END)],
    name="edit_info_conversation",
    persistent=False
)
