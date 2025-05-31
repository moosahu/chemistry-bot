# -*- coding: utf-8 -*-
"""
وحدة التسجيل: تتعامل مع تسجيل المستخدمين الجدد وتعديل معلوماتهم.
"""

import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters
)

# استيراد الثوابت والأدوات المساعدة
try:
    from config import logger, MAIN_MENU, REGISTRATION_NAME, REGISTRATION_EMAIL, REGISTRATION_PHONE, REGISTRATION_GRADE, REGISTRATION_CONFIRM, EDIT_USER_INFO_MENU, EDIT_USER_NAME, EDIT_USER_EMAIL, EDIT_USER_PHONE, EDIT_USER_GRADE
    from utils.helpers import safe_send_message, safe_edit_message_text
except ImportError as e:
    # استخدام قيم افتراضية في حالة فشل الاستيراد
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing modules in registration.py: {e}. Using placeholders.")
    # تعريف ثوابت حالات المحادثة
    MAIN_MENU = 0
    REGISTRATION_NAME, REGISTRATION_EMAIL, REGISTRATION_PHONE, REGISTRATION_GRADE, REGISTRATION_CONFIRM = 20, 21, 22, 23, 24
    EDIT_USER_INFO_MENU, EDIT_USER_NAME, EDIT_USER_EMAIL, EDIT_USER_PHONE, EDIT_USER_GRADE = 30, 31, 32, 33, 34

    # تعريف دوال مساعدة بديلة
    async def safe_send_message(bot, chat_id, text, reply_markup=None, parse_mode=None):
        try:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Error in safe_send_message: {e}")

    async def safe_edit_message_text(bot, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Error in safe_edit_message_text: {e}")

# التحقق من صحة البريد الإلكتروني
def is_valid_email(email):
    """التحقق من صحة البريد الإلكتروني"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

# التحقق من صحة رقم الجوال
def is_valid_phone(phone):
    """التحقق من صحة رقم الجوال (يدعم الأرقام السعودية)"""
    # تنظيف الرقم من الرموز غير الضرورية
    phone = phone.strip().replace(' ', '').replace('-', '')
    
    # التحقق من الصيغ المختلفة للأرقام السعودية
    if phone.startswith('+966'):
        return len(phone) == 13 and phone[1:].isdigit()
    elif phone.startswith('00966'):
        return len(phone) == 14 and phone.isdigit()
    elif phone.startswith('05'):
        return len(phone) == 10 and phone.isdigit()
    elif phone.startswith('5'):
        return len(phone) == 9 and phone.isdigit()
    else:
        return False

# إنشاء لوحة مفاتيح اختيار الصف الدراسي
def create_grade_keyboard():
    """إنشاء لوحة مفاتيح اختيار الصف الدراسي"""
    keyboard = [
        [
            InlineKeyboardButton("ثانوي أول", callback_data="grade_secondary_1"),
            InlineKeyboardButton("ثانوي ثاني", callback_data="grade_secondary_2"),
            InlineKeyboardButton("ثانوي ثالث", callback_data="grade_secondary_3")
        ],
        [
            InlineKeyboardButton("طالب جامعي", callback_data="grade_university"),
            InlineKeyboardButton("معلم", callback_data="grade_teacher")
        ],
        [InlineKeyboardButton("أخرى", callback_data="grade_other")]
    ]
    return InlineKeyboardMarkup(keyboard)

# إنشاء لوحة مفاتيح تأكيد التسجيل
def create_confirmation_keyboard():
    """إنشاء لوحة مفاتيح تأكيد التسجيل"""
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد المعلومات", callback_data="confirm_registration")],
        [
            InlineKeyboardButton("تعديل الاسم", callback_data="edit_name"),
            InlineKeyboardButton("تعديل البريد", callback_data="edit_email")
        ],
        [
            InlineKeyboardButton("تعديل الجوال", callback_data="edit_phone"),
            InlineKeyboardButton("تعديل الصف", callback_data="edit_grade")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# إنشاء لوحة مفاتيح تعديل المعلومات
def create_edit_info_keyboard():
    """إنشاء لوحة مفاتيح تعديل المعلومات"""
    keyboard = [
        [
            InlineKeyboardButton("تعديل الاسم", callback_data="edit_name"),
            InlineKeyboardButton("تعديل البريد", callback_data="edit_email")
        ],
        [
            InlineKeyboardButton("تعديل الجوال", callback_data="edit_phone"),
            InlineKeyboardButton("تعديل الصف", callback_data="edit_grade")
        ],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# حفظ معلومات المستخدم في قاعدة البيانات
def save_user_info(db_manager, user_id, **kwargs):
    """حفظ معلومات المستخدم في قاعدة البيانات"""
    try:
        # التحقق من وجود دالة تحديث معلومات المستخدم
        if hasattr(db_manager, 'update_user_info'):
            db_manager.update_user_info(user_id, **kwargs)
            return True
        else:
            logger.error(f"DB_MANAGER does not have update_user_info method for user {user_id}")
            return False
    except Exception as e:
        logger.error(f"Error saving user info for user {user_id}: {e}")
        return False

# بدء عملية التسجيل
async def start_registration(update: Update, context: CallbackContext) -> int:
    """بدء عملية تسجيل مستخدم جديد"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    logger.info(f"Starting registration process for user {user.id}")
    
    # تهيئة بيانات التسجيل المؤقتة
    context.user_data['registration_data'] = {}
    
    # إرسال رسالة الترحيب وطلب الاسم
    await safe_send_message(
        context.bot,
        chat_id,
        text="مرحباً بك في بوت كيمياء تحصيلي! 👋\n\n"
             "لاستخدام البوت، يرجى إكمال التسجيل أولاً.\n\n"
             "الخطوة الأولى: أدخل اسمك الكامل:"
    )
    return REGISTRATION_NAME

# معالجة إدخال الاسم
async def handle_name_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال الاسم من المستخدم"""
    chat_id = update.effective_chat.id
    full_name = update.message.text.strip()
    
    # التحقق من صحة الاسم
    if len(full_name) < 3:
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ الاسم قصير جداً. يرجى إدخال اسمك الكامل:"
        )
        return REGISTRATION_NAME
    
    # حفظ الاسم في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['full_name'] = full_name
    
    # إرسال رسالة إعلامية
    await safe_send_message(
        context.bot,
        chat_id,
        text=f"تم تسجيل الاسم: {full_name} ✅"
    )
    
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
    
    # إرسال رسالة إعلامية
    await safe_send_message(
        context.bot,
        chat_id,
        text=f"تم تسجيل البريد الإلكتروني: {email} ✅"
    )
    
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
            # تحديث حالة التسجيل في context.user_data لضمان عدم إعادة طلب التسجيل
            context.user_data['is_registered'] = True
            
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
    
    # الحصول على معلومات المستخدم من قاعدة البيانات
    user_info = None
    if hasattr(db_manager, 'get_user_info'):
        user_info = db_manager.get_user_info(user_id)
    
    if not user_info:
        logger.error(f"لا يمكن الحصول على معلومات المستخدم {user_id} من قاعدة البيانات")
        await query.answer("حدث خطأ في الوصول إلى معلومات المستخدم")
        return ConversationHandler.END
    
    # تخزين معلومات المستخدم في context.user_data
    context.user_data['registration_data'] = {
        'full_name': user_info.get('full_name', ''),
        'email': user_info.get('email', ''),
        'phone': user_info.get('phone', ''),
        'grade': user_info.get('grade', '')
    }
    
    # إعداد نص معلومات المستخدم
    info_text = "معلوماتك الحالية:\n\n" \
                f"الاسم: {user_info.get('full_name', '')}\n" \
                f"البريد الإلكتروني: {user_info.get('email', '')}\n" \
                f"رقم الجوال: {user_info.get('phone', '')}\n" \
                f"الصف الدراسي: {user_info.get('grade', '')}\n\n" \
                "اختر المعلومات التي ترغب في تعديلها:"
    
    # إرسال رسالة معلومات المستخدم
    await query.answer()
    await safe_edit_message_text(
        context.bot,
        chat_id,
        query.message.message_id,
        text=info_text,
        reply_markup=create_edit_info_keyboard()
    )
    return EDIT_USER_INFO_MENU

# معالجة اختيار تعديل المعلومات
async def handle_edit_info_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار نوع المعلومات المراد تعديلها"""
    query = update.callback_query
    chat_id = query.message.chat_id
    
    # استخراج نوع التعديل من callback_data
    selection = query.data
    
    if selection == "edit_name":
        await query.answer("تعديل الاسم")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="أدخل اسمك الكامل الجديد:"
        )
        return EDIT_USER_NAME
    elif selection == "edit_email":
        await query.answer("تعديل البريد الإلكتروني")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="أدخل بريدك الإلكتروني الجديد:"
        )
        return EDIT_USER_EMAIL
    elif selection == "edit_phone":
        await query.answer("تعديل رقم الجوال")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="أدخل رقم جوالك الجديد (مثال: 05xxxxxxxx):"
        )
        return EDIT_USER_PHONE
    elif selection == "edit_grade":
        await query.answer("تعديل الصف الدراسي")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="اختر الصف الدراسي الجديد:",
            reply_markup=create_grade_keyboard()
        )
        return EDIT_USER_GRADE
    elif selection == "main_menu":
        await query.answer("العودة للقائمة الرئيسية")
        # استدعاء دالة القائمة الرئيسية
        from handlers.common import main_menu_callback
        return await main_menu_callback(update, context)
    
    # في حالة عدم التعرف على نوع الاختيار
    await query.answer()
    return EDIT_USER_INFO_MENU

# معالجة تعديل الاسم
async def handle_edit_name_input(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل الاسم"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    full_name = update.message.text.strip()
    
    # التحقق من صحة الاسم
    if len(full_name) < 3:
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ الاسم قصير جداً. يرجى إدخال اسمك الكامل:"
        )
        return EDIT_USER_NAME
    
    # تحديث الاسم في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['full_name'] = full_name
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_name_input للمستخدم {user_id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="حدث خطأ في الوصول إلى قاعدة البيانات"
        )
        return ConversationHandler.END
    
    # حفظ الاسم الجديد في قاعدة البيانات
    success = save_user_info(db_manager, user_id, full_name=full_name)
    
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

# معالجة تعديل البريد الإلكتروني
async def handle_edit_email_input(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل البريد الإلكتروني"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
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
            text="حدث خطأ في الوصول إلى قاعدة البيانات"
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

# معالجة تعديل رقم الجوال
async def handle_edit_phone_input(update: Update, context: CallbackContext) -> int:
    """معالجة تعديل رقم الجوال"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
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
            text="حدث خطأ في الوصول إلى قاعدة البيانات"
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
        await query.answer("حدث خطأ في التحديث")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="⚠️ حدث خطأ في تحديث الصف الدراسي. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END

# تعريف محادثة التسجيل
registration_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("register", start_registration),
        CommandHandler("start", start_registration)  # إضافة أمر start لتوجيه المستخدمين الجدد مباشرة للتسجيل
    ],
    states={
        REGISTRATION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name_input)],
        REGISTRATION_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_input)],
        REGISTRATION_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone_input)],
        REGISTRATION_GRADE: [CallbackQueryHandler(handle_grade_selection, pattern=r'^grade_')],
        REGISTRATION_CONFIRM: [CallbackQueryHandler(handle_registration_confirmation, pattern=r'^(confirm_registration|edit_\w+)$')]
    },
    fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
    name="registration_conversation",
    persistent=False
)

# تعريف محادثة تعديل المعلومات
edit_info_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(handle_edit_info_request, pattern=r'^edit_my_info$')
    ],
    states={
        EDIT_USER_INFO_MENU: [CallbackQueryHandler(handle_edit_info_selection, pattern=r'^(edit_\w+|main_menu)$')],
        EDIT_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_name_input)],
        EDIT_USER_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_email_input)],
        EDIT_USER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_phone_input)],
        EDIT_USER_GRADE: [CallbackQueryHandler(handle_edit_grade_selection, pattern=r'^grade_')]
    },
    fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
    name="edit_info_conversation",
    persistent=False
)

# تسجيل الدوال في التطبيق
def register_handlers(application: Application):
    """تسجيل معالجات الرسائل والأوامر في التطبيق"""
    # تسجيل محادثة التسجيل
    application.add_handler(registration_conv_handler)
    
    # تسجيل محادثة تعديل المعلومات
    application.add_handler(edit_info_conv_handler)
