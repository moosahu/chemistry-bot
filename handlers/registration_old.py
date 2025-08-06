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

# نظام الحماية والتحقق من التسجيل
class BotSecurityManager:
    """مدير الحماية للبوت - يتحكم في الوصول للمستخدمين المسجلين فقط"""
    
    def __init__(self):
        self.failed_attempts = {}  # تتبع المحاولات الفاشلة
        self.blocked_users = set()  # المستخدمون المحظورون مؤقتاً
        self.max_attempts = 5  # الحد الأقصى للمحاولات الفاشلة
        
        # رسائل النظام
        self.messages = {
            "not_registered": "❌ عذراً، يجب عليك إكمال التسجيل أولاً لاستخدام البوت.\n\nيرجى إدخال معلوماتك الصحيحة للمتابعة.",
            "incomplete_registration": "⚠️ معلومات التسجيل غير مكتملة.\n\nيرجى إكمال جميع المعلومات المطلوبة للمتابعة.",
            "registration_required": "🔒 هذه الخدمة متاحة للمستخدمين المسجلين فقط.\n\nيرجى إكمال التسجيل أولاً.",
            "access_denied": "🚫 تم رفض الوصول. يرجى التأكد من صحة معلومات التسجيل.",
            "too_many_attempts": "⏰ تم تجاوز الحد الأقصى للمحاولات. يرجى المحاولة لاحقاً.",
            "user_blocked": "🚫 تم حظر حسابك مؤقتاً. تواصل مع الإدارة إذا كنت تعتقد أن هذا خطأ."
        }
    
    def is_user_blocked(self, user_id: int) -> bool:
        """التحقق من حظر المستخدم"""
        return user_id in self.blocked_users
    
    def block_user(self, user_id: int):
        """حظر مستخدم مؤقتاً"""
        self.blocked_users.add(user_id)
        logger.warning(f"تم حظر المستخدم {user_id} مؤقتاً")
    
    def unblock_user(self, user_id: int):
        """إلغاء حظر مستخدم"""
        self.blocked_users.discard(user_id)
        if user_id in self.failed_attempts:
            del self.failed_attempts[user_id]
        logger.info(f"تم إلغاء حظر المستخدم {user_id}")
    
    def record_failed_attempt(self, user_id: int):
        """تسجيل محاولة فاشلة"""
        if user_id not in self.failed_attempts:
            self.failed_attempts[user_id] = 0
        
        self.failed_attempts[user_id] += 1
        logger.warning(f"محاولة فاشلة للمستخدم {user_id}. العدد: {self.failed_attempts[user_id]}")
        
        # حظر المستخدم إذا تجاوز الحد الأقصى
        if self.failed_attempts[user_id] >= self.max_attempts:
            self.block_user(user_id)
    
    def reset_failed_attempts(self, user_id: int):
        """إعادة تعيين المحاولات الفاشلة"""
        if user_id in self.failed_attempts:
            del self.failed_attempts[user_id]
    
    async def check_user_access(self, update: Update, context: CallbackContext, db_manager=None) -> bool:
        """
        التحقق من صلاحية وصول المستخدم للبوت
        
        يعيد:
            bool: True إذا كان المستخدم مصرح له بالوصول، False إذا كان محظوراً أو غير مسجل
        """
        user = update.effective_user
        user_id = user.id
        chat_id = update.effective_chat.id
        
        # التحقق من الحظر المؤقت
        if self.is_user_blocked(user_id):
            await safe_send_message(
                context.bot,
                chat_id,
                text=self.messages["user_blocked"]
            )
            return False
        
        # التحقق من التسجيل
        if not db_manager:
            db_manager = context.bot_data.get("DB_MANAGER")
        
        if not db_manager:
            logger.error(f"لا يمكن الوصول إلى DB_MANAGER للمستخدم {user_id}")
            await safe_send_message(
                context.bot,
                chat_id,
                text="⚠️ حدث خطأ في النظام. يرجى المحاولة لاحقاً."
            )
            return False
        
        # الحصول على معلومات المستخدم
        user_info = get_user_info(db_manager, user_id)
        
        # التحقق من اكتمال التسجيل
        if not is_user_fully_registered(user_info):
            self.record_failed_attempt(user_id)
            await safe_send_message(
                context.bot,
                chat_id,
                text=self.messages["not_registered"]
            )
            return False
        
        # إعادة تعيين المحاولات الفاشلة عند النجاح
        self.reset_failed_attempts(user_id)
        
        # تحديث آخر نشاط للمستخدم
        save_user_info(db_manager, user_id, last_activity=datetime.now().isoformat())
        
        return True
    
    def require_registration(self, func):
        """ديكوريتر للتحقق من التسجيل قبل تنفيذ الدالة"""
        async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
            if not await self.check_user_access(update, context):
                return ConversationHandler.END
            
            return await func(update, context, *args, **kwargs)
        
        return wrapper

# إنشاء مثيل مدير الحماية
security_manager = BotSecurityManager()

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

# دالة معالجة أمر /start مع نظام الحماية المحسن
async def start_command(update: Update, context: CallbackContext) -> int:
    """معالجة أمر /start مع التحقق من الحماية والتسجيل"""
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id
    
    logger.info(f"[SECURITY] بدء فحص المستخدم {user_id} - {user.first_name}")
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"[SECURITY] خطأ حرج: لا يمكن الوصول إلى DB_MANAGER للمستخدم {user_id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في النظام. يرجى المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
    
    # التحقق من الحظر المؤقت أولاً
    if security_manager.is_user_blocked(user_id):
        logger.warning(f"[SECURITY] محاولة وصول من مستخدم محظور: {user_id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text=security_manager.messages["user_blocked"]
        )
        return ConversationHandler.END
    
    # التحقق من حالة تسجيل المستخدم
    user_info = get_user_info(db_manager, user_id)
    is_registered = is_user_fully_registered(user_info)
    
    # تحديث حالة التسجيل في context.user_data
    context.user_data['is_registered'] = is_registered
    
    # إذا كان المستخدم مسجلاً بالكامل
    if is_registered:
        logger.info(f"[SECURITY] المستخدم {user_id} مسجل ومصرح له بالوصول")
        
        # إعادة تعيين المحاولات الفاشلة
        security_manager.reset_failed_attempts(user_id)
        
        # تحديث آخر نشاط
        save_user_info(db_manager, user_id, last_activity=datetime.now().isoformat())
        
        # عرض القائمة الرئيسية
        try:
            from handlers.common import main_menu_callback
            await main_menu_callback(update, context)
        except ImportError:
            try:
                from common import main_menu_callback
                await main_menu_callback(update, context)
            except ImportError as e:
                logger.error(f"خطأ في استيراد main_menu_callback: {e}")
                # عرض القائمة الرئيسية مباشرة
                welcome_text = f"🔐 أهلاً بك يا {user.first_name} في بوت كيمياء تحصيلي! 👋\n\n" \
                               "✅ تم التحقق من هويتك بنجاح\n" \
                               "استخدم الأزرار أدناه لبدء اختبار أو استعراض المعلومات."
                keyboard = create_main_menu_keyboard(user_id, db_manager)
                await safe_send_message(
                    context.bot,
                    chat_id,
                    text=welcome_text,
                    reply_markup=keyboard
                )
        
        return ConversationHandler.END
    else:
        # المستخدم غير مسجل أو معلوماته ناقصة
        logger.warning(f"[SECURITY] المستخدم {user_id} غير مسجل أو معلوماته ناقصة")
        
        # تسجيل محاولة وصول غير مصرح بها
        security_manager.record_failed_attempt(user_id)
        
        # بدء عملية التسجيل
        return await start_registration(update, context)

async def check_registration_status(update: Update, context: CallbackContext, db_manager=None):
    """
    التحقق من حالة تسجيل المستخدم مع نظام الحماية المحسن
    
    يعيد:
        bool: True إذا كان المستخدم مسجلاً ومصرح له، False إذا كان يحتاج للتسجيل أو محظور
    """
    user = update.effective_user
    user_id = user.id
    
    logger.info(f"[SECURITY] فحص حالة التسجيل للمستخدم {user_id}")
    
    # التحقق من الحظر المؤقت أولاً
    if security_manager.is_user_blocked(user_id):
        logger.warning(f"[SECURITY] المستخدم {user_id} محظور مؤقتاً")
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            text=security_manager.messages["user_blocked"]
        )
        return False
    
    # التحقق من حالة التسجيل المخزنة في context.user_data أولاً
    if context.user_data.get('is_registered', False):
        logger.info(f"[SECURITY] المستخدم {user_id} مسجل (من context.user_data)")
        # تحديث آخر نشاط
        if not db_manager:
            db_manager = context.bot_data.get("DB_MANAGER")
        if db_manager:
            save_user_info(db_manager, user_id, last_activity=datetime.now().isoformat())
        return True
    
    # الحصول على مدير قاعدة البيانات
    if not db_manager:
        db_manager = context.bot_data.get("DB_MANAGER")
        if not db_manager:
            logger.error(f"[SECURITY] لا يمكن الوصول إلى DB_MANAGER للمستخدم {user_id}")
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                text="⚠️ حدث خطأ في النظام. يرجى المحاولة لاحقاً."
            )
            return False
    
    # الحصول على معلومات المستخدم من قاعدة البيانات
    user_info = get_user_info(db_manager, user_id)
    
    # التحقق من اكتمال معلومات المستخدم
    is_registered = is_user_fully_registered(user_info)
    
    # تحديث حالة التسجيل في context.user_data
    context.user_data['is_registered'] = is_registered
    
    # إذا لم يكن المستخدم مسجلاً، تسجيل محاولة فاشلة وتوجيهه للتسجيل
    if not is_registered:
        logger.warning(f"[SECURITY] المستخدم {user_id} غير مسجل، توجيهه للتسجيل")
        security_manager.record_failed_attempt(user_id)
        await start_registration(update, context)
        return False
    
    logger.info(f"[SECURITY] المستخدم {user_id} مسجل ومصرح له (من قاعدة البيانات)")
    
    # إعادة تعيين المحاولات الفاشلة عند النجاح
    security_manager.reset_failed_attempts(user_id)
    
    # تحديث آخر نشاط
    save_user_info(db_manager, user_id, last_activity=datetime.now().isoformat())
    
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
    
    # إرسال رسالة الترحيب وطلب الاسم
    welcome_text = "مرحباً بك في بوت كيمياء تحصيلي! 👋\n\n" \
                   "لاستخدام البوت، يرجى إكمال التسجيل أولاً.\n\n" \
                   "الخطوة الأولى: أدخل اسمك الكامل:"
    
    # إذا كان لدينا اسم مسبق، نعرضه كاقتراح
    if context.user_data['registration_data'].get('full_name'):
        welcome_text += f"\n\n(الاسم الحالي: {context.user_data['registration_data'].get('full_name')})"
    
    await safe_send_message(
        context.bot,
        chat_id,
        text=welcome_text
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
            text="⚠️ البريد الإلكتروني غير صحيح. يرجى إدخال بريد إلكتروني صالح:"
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
             "الخطوة الثالثة: أدخل رقم جوالك (مثال: 05xxxxxxxx):"
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
            text="⚠️ رقم الجوال غير صحيح. يرجى إدخال رقم جوال سعودي صالح (يبدأ بـ 05 أو +966 أو 00966):"
        )
        logger.info(f"[DEBUG] handle_phone_input: Asking for phone again, returning state REGISTRATION_PHONE ({REGISTRATION_PHONE})")
        return REGISTRATION_PHONE
    
    # حفظ رقم الجوال في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['phone'] = phone
    logger.info(f"[DEBUG] Saved phone '{phone}' for user {user.id} in context.user_data")
    
    # إرسال رسالة تأكيد وطلب الصف الدراسي
    await safe_send_message(
        context.bot,
        chat_id,
        text=f"✅ تم تسجيل رقم الجوال: {phone}\n\n"
             "الخطوة الرابعة: يرجى اختيار الصف الدراسي:"
    )
    await safe_send_message(
        context.bot,
        chat_id,
        text="اختر الصف الدراسي:",
        reply_markup=create_grade_keyboard()
    )
    logger.info(f"[DEBUG] handle_phone_input: Asked for grade, returning state REGISTRATION_GRADE ({REGISTRATION_GRADE})")
    return REGISTRATION_GRADE

# معالجة اختيار الصف الدراسي
async def handle_grade_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار الصف الدراسي من المستخدم"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    
    # تسجيل معلومات التصحيح
    logger.info(f"[DEBUG] Entering handle_grade_selection for user {user.id}")
    logger.debug(f"[DEBUG] Received grade selection from user {user.id}: {query.data}")
    
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
        logger.warning(f"[DEBUG] Invalid grade selection received: {grade_data}")
        await query.answer("خيار غير صالح")
        # إعادة إرسال لوحة المفاتيح
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى اختيار الصف الدراسي:",
            reply_markup=create_grade_keyboard()
        )
        logger.info(f"[DEBUG] handle_grade_selection: Asking for grade again, returning state REGISTRATION_GRADE ({REGISTRATION_GRADE})")
        return REGISTRATION_GRADE
    
    # حفظ الصف الدراسي في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['grade'] = grade_text
    logger.info(f"[DEBUG] Saved grade '{grade_text}' for user {user.id} in context.user_data")
    
    # إعداد نص تأكيد المعلومات
    user_info = context.user_data.get('registration_data', {})
    confirmation_text = "يرجى مراجعة وتأكيد معلوماتك:\n\n" \
                        f"الاسم: {user_info.get('full_name')}\n" \
                        f"البريد الإلكتروني: {user_info.get('email')}\n" \
                        f"رقم الجوال: {user_info.get('phone')}\n" \
                        f"الصف الدراسي: {user_info.get('grade')}"
    
    # إرسال رسالة تأكيد المعلومات
    await query.answer()
    await safe_edit_message_text(
        context.bot,
        chat_id,
        query.message.message_id,
        text=confirmation_text,
        reply_markup=create_confirmation_keyboard()
    )
    logger.info(f"[DEBUG] handle_grade_selection: Asked for confirmation, returning state REGISTRATION_CONFIRM ({REGISTRATION_CONFIRM})")
    return REGISTRATION_CONFIRM

# معالجة تأكيد التسجيل
async def handle_registration_confirmation(update: Update, context: CallbackContext) -> int:
    """معالجة تأكيد أو تعديل معلومات التسجيل"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    user_id = user.id
    
    # استخراج نوع التأكيد من callback_data
    confirmation_type = query.data
    
    # تسجيل معلومات التصحيح
    logger.info(f"[DEBUG] Entering handle_registration_confirmation for user {user_id}")
    logger.debug(f"[DEBUG] Received registration confirmation from user {user_id}: {confirmation_type}")
    
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
            logger.info(f"[DEBUG] handle_registration_confirmation: DB_MANAGER error, returning END ({END})")
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
            # تحديث حالة التسجيل في context.user_data
            context.user_data['is_registered'] = True
            logger.info(f"[DEBUG] User {user_id} registration successful and saved to DB.")
            
            # إرسال رسالة نجاح التسجيل
            await query.answer("تم التسجيل بنجاح!")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="✅ تم تسجيلك بنجاح!\n\n"
                     "يمكنك الآن استخدام جميع ميزات البوت."
            )
            
            # عرض القائمة الرئيسية بشكل منفصل
            welcome_text = f"أهلاً بك يا {user.first_name} في بوت كيمياء تحصيلي! 👋\n\n" \
                           "استخدم الأزرار أدناه لبدء اختبار أو استعراض المعلومات."
            keyboard = create_main_menu_keyboard(user_id, db_manager)
            await safe_send_message(
                context.bot,
                chat_id,
                text=welcome_text,
                reply_markup=keyboard
            )
            
            # إنهاء محادثة التسجيل
            logger.info(f"[DEBUG] handle_registration_confirmation: Registration complete, returning END ({END})")
            return ConversationHandler.END
        else:
            # إرسال رسالة فشل التسجيل
            logger.error(f"[DEBUG] Failed to save registration info for user {user_id} to DB.")
            await query.answer("حدث خطأ في التسجيل")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="⚠️ حدث خطأ في حفظ معلومات التسجيل. يرجى المحاولة مرة أخرى لاحقاً."
            )
            logger.info(f"[DEBUG] handle_registration_confirmation: DB save error, returning END ({END})")
            return ConversationHandler.END
    elif confirmation_type.startswith("edit_"):
        # استخراج نوع التعديل من callback_data
        field = confirmation_type.replace("edit_", "")
        logger.info(f"[DEBUG] User {user_id} requested to edit field: {field}")
        
        if field == "name":
            # تعديل الاسم
            await query.answer("تعديل الاسم")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="أدخل اسمك الكامل الجديد:"
            )
            logger.info(f"[DEBUG] handle_registration_confirmation: Editing name, returning state REGISTRATION_NAME ({REGISTRATION_NAME})")
            return REGISTRATION_NAME
        elif field == "email":
            # تعديل البريد الإلكتروني
            await query.answer("تعديل البريد الإلكتروني")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="أدخل بريدك الإلكتروني الجديد:"
            )
            logger.info(f"[DEBUG] handle_registration_confirmation: Editing email, returning state REGISTRATION_EMAIL ({REGISTRATION_EMAIL})")
            return REGISTRATION_EMAIL
        elif field == "phone":
            # تعديل رقم الجوال
            await query.answer("تعديل رقم الجوال")
            await safe_edit_message_text(
                context.bot,
                chat_id,
                query.message.message_id,
                text="أدخل رقم جوالك الجديد (مثال: 05xxxxxxxx):"
            )
            logger.info(f"[DEBUG] handle_registration_confirmation: Editing phone, returning state REGISTRATION_PHONE ({REGISTRATION_PHONE})")
            return REGISTRATION_PHONE
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
            logger.info(f"[DEBUG] handle_registration_confirmation: Editing grade, returning state REGISTRATION_GRADE ({REGISTRATION_GRADE})")
            return REGISTRATION_GRADE
        elif field == "main_menu":
            # العودة إلى القائمة الرئيسية
            logger.info(f"[DEBUG] handle_registration_confirmation: User chose main_menu, returning END ({END})")
            return ConversationHandler.END
        else:
            # إذا لم يتم التعرف على نوع التعديل، نعود إلى شاشة التأكيد
            logger.warning(f"[DEBUG] Invalid edit field received: {field}")
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
                reply_markup=create_confirmation_keyboard() # عرض لوحة التأكيد مجدداً
            )
            logger.info(f"[DEBUG] handle_registration_confirmation: Invalid edit field, returning state REGISTRATION_CONFIRM ({REGISTRATION_CONFIRM})")
            return REGISTRATION_CONFIRM
    
    # إذا لم يتم التعرف على نوع التأكيد، نعود إلى شاشة التأكيد
    logger.warning(f"[DEBUG] Invalid confirmation type received: {confirmation_type}")
    await query.answer("خيار غير صالح")
    logger.info(f"[DEBUG] handle_registration_confirmation: Invalid confirmation type, returning state REGISTRATION_CONFIRM ({REGISTRATION_CONFIRM})")
    return REGISTRATION_CONFIRM

# معالجة طلب تعديل المعلومات
async def handle_edit_info_request(update: Update, context: CallbackContext) -> int:
    """معالجة طلب تعديل معلومات المستخدم"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    user_id = user.id
    
    logger.info(f"[DEBUG] Entering handle_edit_info_request for user {user_id}")
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_info_request للمستخدم {user_id}")
        await query.answer("حدث خطأ في الوصول إلى قاعدة البيانات")
        logger.info(f"[DEBUG] handle_edit_info_request: DB_MANAGER error, returning END ({END})")
        return ConversationHandler.END
    
    # الحصول على معلومات المستخدم من قاعدة البيانات
    user_info = get_user_info(db_manager, user_id)
    
    if not user_info:
        logger.error(f"لا يمكن الحصول على معلومات المستخدم {user_id} من قاعدة البيانات")
        await query.answer("حدث خطأ في الوصول إلى معلومات المستخدم")
        logger.info(f"[DEBUG] handle_edit_info_request: User info not found, returning END ({END})")
        return ConversationHandler.END
    
    # تخزين معلومات المستخدم في context.user_data
    context.user_data['registration_data'] = {
        'full_name': user_info.get('full_name', ''),
        'email': user_info.get('email', ''),
        'phone': user_info.get('phone', ''),
        'grade': user_info.get('grade', '')
    }
    logger.info(f"[DEBUG] Loaded user info into context.user_data for editing: {context.user_data['registration_data']}")
    
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
    logger.info(f"[DEBUG] handle_edit_info_request: Displayed edit menu, returning state EDIT_USER_INFO_MENU ({EDIT_USER_INFO_MENU})")
    return EDIT_USER_INFO_MENU

# معالجة اختيار تعديل المعلومات
async def handle_edit_info_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار نوع المعلومات المراد تعديلها"""
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    
    logger.info(f"[DEBUG] Entering handle_edit_info_selection for user {user_id}")
    
    # استخراج نوع التعديل من callback_data
    field = query.data.replace("edit_", "")
    logger.debug(f"[DEBUG] User {user_id} selected field to edit: {field}")
    
    if field == "name":
        # تعديل الاسم
        await query.answer("تعديل الاسم")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="أدخل اسمك الكامل الجديد:"
        )
        logger.info(f"[DEBUG] handle_edit_info_selection: Editing name, returning state EDIT_USER_NAME ({EDIT_USER_NAME})")
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
        logger.info(f"[DEBUG] handle_edit_info_selection: Editing email, returning state EDIT_USER_EMAIL ({EDIT_USER_EMAIL})")
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
        logger.info(f"[DEBUG] handle_edit_info_selection: Editing phone, returning state EDIT_USER_PHONE ({EDIT_USER_PHONE})")
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
        logger.info(f"[DEBUG] handle_edit_info_selection: Editing grade, returning state EDIT_USER_GRADE ({EDIT_USER_GRADE})")
        return EDIT_USER_GRADE
    elif field == "main_menu":
        # العودة إلى القائمة الرئيسية
        logger.info(f"[DEBUG] handle_edit_info_selection: User chose main_menu, returning END ({END})")
        # عرض القائمة الرئيسية
        try:
            from handlers.common import main_menu_callback
        except ImportError:
            try:
                from common import main_menu_callback
            except ImportError as e:
                logger.error(f"خطأ في استيراد main_menu_callback: {e}")
                # إذا لم نتمكن من استيراد main_menu_callback، نعرض القائمة الرئيسية هنا
                db_manager = context.bot_data.get("DB_MANAGER")
                welcome_text = f"أهلاً بك يا {query.from_user.first_name} في بوت كيمياء تحصيلي! 👋\n\n" \
                               "استخدم الأزرار أدناه لبدء اختبار أو استعراض المعلومات."
                keyboard = create_main_menu_keyboard(user_id, db_manager)
                await safe_edit_message_text(
                    context.bot,
                    chat_id,
                    query.message.message_id,
                    text=welcome_text,
                    reply_markup=keyboard
                )
                return ConversationHandler.END
        
        await main_menu_callback(update, context)
        return ConversationHandler.END
    else:
        # إذا لم يتم التعرف على نوع التعديل، نعود إلى قائمة تعديل المعلومات
        logger.warning(f"[DEBUG] Invalid edit field selected: {field}")
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
        logger.info(f"[DEBUG] handle_edit_info_selection: Invalid edit field, returning state EDIT_USER_INFO_MENU ({EDIT_USER_INFO_MENU})")
        return EDIT_USER_INFO_MENU

# معالجة إدخال الاسم الجديد
async def handle_edit_name_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال الاسم الجديد"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id
    name = update.message.text.strip()
    
    logger.info(f"[DEBUG] Entering handle_edit_name_input for user {user_id}")
    logger.debug(f"[DEBUG] Received new name from user {user_id}: {name}")
    
    # التحقق من صحة الاسم
    if len(name) < 3:
        logger.warning(f"[DEBUG] Invalid new name received: {name}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ الاسم قصير جداً. يرجى إدخال اسمك الكامل (3 أحرف على الأقل):"
        )
        logger.info(f"[DEBUG] handle_edit_name_input: Asking for name again, returning state EDIT_USER_NAME ({EDIT_USER_NAME})")
        return EDIT_USER_NAME
    
    # تحديث الاسم في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['full_name'] = name
    logger.info(f"[DEBUG] Updated name to '{name}' in context.user_data")
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_name_input للمستخدم {user_id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_name_input: DB_MANAGER error, returning END ({END})")
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
        logger.info(f"[DEBUG] Successfully updated name for user {user_id} in DB.")
        await safe_send_message(
            context.bot,
            chat_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
        )
        logger.info(f"[DEBUG] handle_edit_name_input: Name updated, returning state EDIT_USER_INFO_MENU ({EDIT_USER_INFO_MENU})")
        return EDIT_USER_INFO_MENU
    else:
        # إرسال رسالة فشل التحديث
        logger.error(f"[DEBUG] Failed to update name for user {user_id} in DB.")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في تحديث الاسم. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_name_input: DB save error, returning END ({END})")
        return ConversationHandler.END

# معالجة إدخال البريد الإلكتروني الجديد
async def handle_edit_email_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال البريد الإلكتروني الجديد"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id
    email = update.message.text.strip()
    
    logger.info(f"[DEBUG] Entering handle_edit_email_input for user {user_id}")
    logger.debug(f"[DEBUG] Received new email from user {user_id}: {email}")
    
    # التحقق من صحة البريد الإلكتروني
    if not is_valid_email(email):
        logger.warning(f"[DEBUG] Invalid new email received: {email}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ البريد الإلكتروني غير صحيح. يرجى إدخال بريد إلكتروني صالح:"
        )
        logger.info(f"[DEBUG] handle_edit_email_input: Asking for email again, returning state EDIT_USER_EMAIL ({EDIT_USER_EMAIL})")
        return EDIT_USER_EMAIL
    
    # تحديث البريد الإلكتروني في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['email'] = email
    logger.info(f"[DEBUG] Updated email to '{email}' in context.user_data")
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_email_input للمستخدم {user_id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_email_input: DB_MANAGER error, returning END ({END})")
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
        logger.info(f"[DEBUG] Successfully updated email for user {user_id} in DB.")
        await safe_send_message(
            context.bot,
            chat_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
        )
        logger.info(f"[DEBUG] handle_edit_email_input: Email updated, returning state EDIT_USER_INFO_MENU ({EDIT_USER_INFO_MENU})")
        return EDIT_USER_INFO_MENU
    else:
        # إرسال رسالة فشل التحديث
        logger.error(f"[DEBUG] Failed to update email for user {user_id} in DB.")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في تحديث البريد الإلكتروني. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_email_input: DB save error, returning END ({END})")
        return ConversationHandler.END

# معالجة إدخال رقم الجوال الجديد
async def handle_edit_phone_input(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال رقم الجوال الجديد"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id
    phone = update.message.text.strip()
    
    logger.info(f"[DEBUG] Entering handle_edit_phone_input for user {user_id}")
    logger.debug(f"[DEBUG] Received new phone from user {user_id}: {phone}")
    
    # التحقق من صحة رقم الجوال
    if not is_valid_phone(phone):
        logger.warning(f"[DEBUG] Invalid new phone received: {phone}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ رقم الجوال غير صحيح. يرجى إدخال رقم جوال سعودي صالح (يبدأ بـ 05 أو +966 أو 00966):"
        )
        logger.info(f"[DEBUG] handle_edit_phone_input: Asking for phone again, returning state EDIT_USER_PHONE ({EDIT_USER_PHONE})")
        return EDIT_USER_PHONE
    
    # تحديث رقم الجوال في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['phone'] = phone
    logger.info(f"[DEBUG] Updated phone to '{phone}' in context.user_data")
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_phone_input للمستخدم {user_id}")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في الوصول إلى قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_phone_input: DB_MANAGER error, returning END ({END})")
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
        logger.info(f"[DEBUG] Successfully updated phone for user {user_id} in DB.")
        await safe_send_message(
            context.bot,
            chat_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
        )
        logger.info(f"[DEBUG] handle_edit_phone_input: Phone updated, returning state EDIT_USER_INFO_MENU ({EDIT_USER_INFO_MENU})")
        return EDIT_USER_INFO_MENU
    else:
        # إرسال رسالة فشل التحديث
        logger.error(f"[DEBUG] Failed to update phone for user {user_id} in DB.")
        await safe_send_message(
            context.bot,
            chat_id,
            text="⚠️ حدث خطأ في تحديث رقم الجوال. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_phone_input: DB save error, returning END ({END})")
        return ConversationHandler.END

# معالجة اختيار الصف الدراسي الجديد
async def handle_edit_grade_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار الصف الدراسي الجديد"""
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    user_id = user.id
    
    logger.info(f"[DEBUG] Entering handle_edit_grade_selection for user {user_id}")
    
    # استخراج الصف الدراسي من callback_data
    grade_data = query.data
    logger.debug(f"[DEBUG] Received new grade selection: {grade_data}")
    
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
        logger.warning(f"[DEBUG] Invalid new grade selection received: {grade_data}")
        await query.answer("خيار غير صالح")
        # إعادة إرسال لوحة المفاتيح
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="يرجى اختيار الصف الدراسي الجديد:",
            reply_markup=create_grade_keyboard()
        )
        logger.info(f"[DEBUG] handle_edit_grade_selection: Asking for grade again, returning state EDIT_USER_GRADE ({EDIT_USER_GRADE})")
        return EDIT_USER_GRADE
    
    # تحديث الصف الدراسي في بيانات المستخدم المؤقتة
    context.user_data['registration_data']['grade'] = grade_text
    logger.info(f"[DEBUG] Updated grade to '{grade_text}' in context.user_data")
    
    # الحصول على مدير قاعدة البيانات
    db_manager = context.bot_data.get("DB_MANAGER")
    if not db_manager:
        logger.error(f"لا يمكن الوصول إلى DB_MANAGER في handle_edit_grade_selection للمستخدم {user_id}")
        await query.answer("حدث خطأ في الوصول إلى قاعدة البيانات")
        logger.info(f"[DEBUG] handle_edit_grade_selection: DB_MANAGER error, returning END ({END})")
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
        logger.info(f"[DEBUG] Successfully updated grade for user {user_id} in DB.")
        await query.answer("تم تحديث الصف الدراسي")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text=info_text,
            reply_markup=create_edit_info_keyboard()
        )
        logger.info(f"[DEBUG] handle_edit_grade_selection: Grade updated, returning state EDIT_USER_INFO_MENU ({EDIT_USER_INFO_MENU})")
        return EDIT_USER_INFO_MENU
    else:
        # إرسال رسالة فشل التحديث
        logger.error(f"[DEBUG] Failed to update grade for user {user_id} in DB.")
        await query.answer("حدث خطأ في التحديث")
        await safe_edit_message_text(
            context.bot,
            chat_id,
            query.message.message_id,
            text="⚠️ حدث خطأ في تحديث الصف الدراسي. يرجى المحاولة مرة أخرى لاحقاً."
        )
        logger.info(f"[DEBUG] handle_edit_grade_selection: DB save error, returning END ({END})")
        return ConversationHandler.END

# تعريف محادثة التسجيل
registration_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("register", start_registration),
        CommandHandler("start", start_command)  # استخدام start_command كنقطة دخول
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

# إضافة تسجيلات لتأكيد تعريف المعالج
logger.info(f"[DEBUG] registration_conv_handler defined. Entry points: {registration_conv_handler.entry_points}")
logger.info(f"[DEBUG] registration_conv_handler states: {registration_conv_handler.states}")
logger.info(f"[DEBUG] State REGISTRATION_NAME ({REGISTRATION_NAME}) handler: {registration_conv_handler.states.get(REGISTRATION_NAME)}")

