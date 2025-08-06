# -*- coding: utf-8 -*-

"""
نظام الحماية مع التحكم الإداري اليدوي - النسخة النهائية
يستخدم قاعدة البيانات مع SQL آمن ومتوافق مع SQLAlchemy
"""

import logging
from datetime import datetime
from typing import Set, Dict, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters
)
from sqlalchemy import text

# إعداد التسجيل
logger = logging.getLogger(__name__)

class AdminSecurityManager:
    """مدير الحماية الإداري مع التحكم اليدوي"""
    
    def __init__(self, admin_ids: List[int]):
        self.admin_ids = set(admin_ids)
        self.blocked_users = {}  # نسخة احتياطية في الذاكرة
        
        # رسائل النظام
        self.messages = {
            "user_blocked": "🚫 تم حظرك من استخدام البوت.\nللاستفسار، تواصل مع الإدارة.",
            "not_registered": "📝 يجب عليك التسجيل أولاً لاستخدام البوت.\nاستخدم الأمر /start للتسجيل.",
            "admin_only": "👑 هذا الأمر متاح للمدراء فقط.",
            "access_denied": "🚫 تم رفض الوصول.",
            "database_error": "❌ خطأ في قاعدة البيانات. يرجى المحاولة لاحقاً."
        }
    
    def get_db_session(self, context: CallbackContext):
        """الحصول على جلسة قاعدة البيانات"""
        try:
            db_manager = context.bot_data.get("DB_MANAGER")
            if db_manager:
                logger.info(f"تم العثور على DB_MANAGER من النوع: {type(db_manager)}")
                
                # محاولة الحصول على الجلسة بطرق مختلفة
                if hasattr(db_manager, 'get_session'):
                    session = db_manager.get_session()
                    logger.info("تم الحصول على الجلسة من get_session()")
                    return session
                elif hasattr(db_manager, 'session'):
                    logger.info("تم الحصول على الجلسة من session")
                    return db_manager.session
                elif hasattr(db_manager, 'engine'):
                    logger.info("تم الحصول على الجلسة من engine")
                    from sqlalchemy.orm import sessionmaker
                    Session = sessionmaker(bind=db_manager.engine)
                    return Session()
                else:
                    # طباعة جميع الخصائص المتاحة للتشخيص
                    available_attrs = [attr for attr in dir(db_manager) if not attr.startswith('_')]
                    logger.info(f"الخصائص المتاحة في DB_MANAGER: {available_attrs}")
            
            logger.warning("لم يتم العثور على DB_MANAGER أو لا يحتوي على طرق الجلسة المتوقعة")
            return None
            
        except Exception as e:
            logger.error(f"خطأ في الحصول على جلسة قاعدة البيانات: {e}")
            return None
    
    def is_admin(self, user_id: int) -> bool:
        """التحقق من كون المستخدم مدير"""
        return user_id in self.admin_ids
    
    def is_user_blocked(self, user_id: int, context: CallbackContext) -> bool:
        """التحقق من حظر المستخدم"""
        try:
            session = self.get_db_session(context)
            if not session:
                logger.error("لا يمكن الحصول على جلسة قاعدة البيانات للتحقق من الحظر")
                return False
            
            try:
                # التحقق من الحظر باستخدام SQL آمن
                result = session.execute(
                    text("SELECT id FROM blocked_users WHERE user_id = :user_id AND is_active = true"),
                    {"user_id": user_id}
                ).fetchone()
                
                return result is not None
                
            except Exception as e:
                logger.error(f"خطأ في التحقق من حظر المستخدم {user_id}: {e}")
                return False
            finally:
                session.close()
            
        except Exception as e:
            logger.error(f"خطأ في التحقق من حظر المستخدم {user_id}: {e}")
            return False
    
    def block_user(self, user_id: int, admin_id: int, reason: str, context: CallbackContext) -> bool:
        """حظر مستخدم (بواسطة المدير)"""
        if user_id in self.admin_ids:
            logger.warning(f"محاولة حظر مدير: {user_id}")
            return False
        
        try:
            session = self.get_db_session(context)
            if not session:
                logger.error("لا يمكن الحصول على جلسة قاعدة البيانات")
                return False
            
            try:
                # التحقق من وجود المستخدم محظور بالفعل
                result = session.execute(
                    text("SELECT id FROM blocked_users WHERE user_id = :user_id AND is_active = true"),
                    {"user_id": user_id}
                ).fetchone()
                
                if result:
                    logger.info(f"المستخدم {user_id} محظور بالفعل")
                    return False
                
                # إدراج سجل حظر جديد
                session.execute(
                    text("""INSERT INTO blocked_users 
                           (user_id, blocked_by, blocked_at, reason, is_active) 
                           VALUES (:user_id, :blocked_by, CURRENT_TIMESTAMP, :reason, :is_active)"""),
                    {
                        "user_id": user_id,
                        "blocked_by": admin_id,
                        "reason": reason,
                        "is_active": True
                    }
                )
                session.commit()
                
                logger.info(f"تم حظر المستخدم {user_id} بواسطة المدير {admin_id}")
                return True
                
            except Exception as e:
                session.rollback()
                logger.warning(f"فشل حظر المستخدم {user_id}: {e}")
                return False
            finally:
                session.close()
            
        except Exception as e:
            logger.error(f"خطأ في حظر المستخدم {user_id}: {e}")
            return False
    
    def unblock_user(self, user_id: int, admin_id: int, context: CallbackContext) -> bool:
        """إلغاء حظر مستخدم (بواسطة المدير)"""
        try:
            session = self.get_db_session(context)
            if not session:
                logger.error("لا يمكن الحصول على جلسة قاعدة البيانات")
                return False
            
            try:
                # البحث عن المستخدم المحظور
                result = session.execute(
                    text("SELECT id FROM blocked_users WHERE user_id = :user_id AND is_active = true"),
                    {"user_id": user_id}
                ).fetchone()
                
                if not result:
                    logger.info(f"المستخدم {user_id} غير محظور")
                    return False
                
                # إلغاء الحظر
                session.execute(
                    text("""UPDATE blocked_users 
                           SET is_active = false, unblocked_by = :admin_id, unblocked_at = CURRENT_TIMESTAMP 
                           WHERE user_id = :user_id AND is_active = true"""),
                    {"admin_id": admin_id, "user_id": user_id}
                )
                session.commit()
                
                logger.info(f"تم إلغاء حظر المستخدم {user_id} بواسطة المدير {admin_id}")
                return True
                
            except Exception as e:
                session.rollback()
                logger.warning(f"فشل إلغاء حظر المستخدم {user_id}: {e}")
                return False
            finally:
                session.close()
            
        except Exception as e:
            logger.error(f"خطأ في إلغاء حظر المستخدم {user_id}: {e}")
            return False
    
    def get_blocked_users_list(self, context: CallbackContext) -> List[Dict]:
        """الحصول على قائمة المستخدمين المحظورين مع معلوماتهم"""
        try:
            session = self.get_db_session(context)
            if not session:
                logger.error("لا يمكن الحصول على جلسة قاعدة البيانات")
                return []
            
            try:
                # الحصول على قائمة المحظورين
                results = session.execute(
                    text("""SELECT user_id, blocked_by, blocked_at, reason 
                           FROM blocked_users 
                           WHERE is_active = true 
                           ORDER BY blocked_at DESC 
                           LIMIT 50""")
                ).fetchall()
                
                blocked_list = []
                for row in results:
                    blocked_list.append({
                        'user_id': row[0],
                        'blocked_by': row[1],
                        'blocked_at': row[2].isoformat() if row[2] else None,
                        'reason': row[3] or "غير محدد"
                    })
                
                return blocked_list
                
            except Exception as e:
                logger.error(f"خطأ في الحصول على قائمة المحظورين: {e}")
                return []
            finally:
                session.close()
            
        except Exception as e:
            logger.error(f"خطأ في الحصول على قائمة المحظورين: {e}")
            return []
    
    async def check_user_access(self, update: Update, context: CallbackContext, 
                              check_registration: bool = True) -> bool:
        """
        التحقق من صلاحية وصول المستخدم
        
        Args:
            update: تحديث تيليجرام
            context: سياق المحادثة
            check_registration: هل نتحقق من التسجيل أم لا
        
        Returns:
            bool: True إذا كان مصرح له بالوصول
        """
        user = update.effective_user
        user_id = user.id
        chat_id = update.effective_chat.id
        
        # التحقق من الحظر أولاً
        if self.is_user_blocked(user_id, context):
            logger.warning(f"[SECURITY] محاولة وصول من مستخدم محظور: {user_id}")
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=self.messages["user_blocked"]
                )
            except Exception as e:
                logger.error(f"خطأ في إرسال رسالة الحظر: {e}")
            return False
        
        # التحقق من التسجيل إذا كان مطلوباً
        if check_registration:
            # استيراد دوال التحقق من التسجيل
            try:
                from handlers.registration import is_user_fully_registered, get_user_info
                
                db_manager = context.bot_data.get("DB_MANAGER")
                if not db_manager:
                    logger.error(f"لا يمكن الوصول إلى DB_MANAGER للمستخدم {user_id}")
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text="⚠️ حدث خطأ في النظام. يرجى المحاولة لاحقاً."
                        )
                    except Exception as e:
                        logger.error(f"خطأ في إرسال رسالة الخطأ: {e}")
                    return False
                
                # التحقق من التسجيل
                user_info = get_user_info(db_manager, user_id)
                if not is_user_fully_registered(user_info):
                    logger.warning(f"[SECURITY] المستخدم {user_id} غير مسجل")
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=self.messages["not_registered"]
                        )
                    except Exception as e:
                        logger.error(f"خطأ في إرسال رسالة عدم التسجيل: {e}")
                    return False
                
            except ImportError as e:
                logger.error(f"خطأ في استيراد دوال التسجيل: {e}")
                return False
        
        return True
    
    def require_admin(self, func):
        """ديكوريتر للتحقق من صلاحيات المدير"""
        async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
            user_id = update.effective_user.id
            
            if not self.is_admin(user_id):
                try:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=self.messages["admin_only"]
                    )
                except Exception as e:
                    logger.error(f"خطأ في إرسال رسالة المدير فقط: {e}")
                return ConversationHandler.END
            
            return await func(update, context, *args, **kwargs)
        
        return wrapper
    
    def require_registration_and_not_blocked(self, func):
        """ديكوريتر للتحقق من التسجيل وعدم الحظر"""
        async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
            if not await self.check_user_access(update, context, check_registration=True):
                return ConversationHandler.END
            
            return await func(update, context, *args, **kwargs)
        
        return wrapper

# إنشاء مثيل مدير الحماية (سيتم تهيئته في الملف الرئيسي)
admin_security_manager = None

def initialize_admin_security(admin_ids: List[int]):
    """تهيئة مدير الحماية الإداري"""
    global admin_security_manager
    admin_security_manager = AdminSecurityManager(admin_ids)
    
    # إنشاء جدول المحظورين إذا لم يكن موجوداً
    try:
        from database.db_setup import get_engine
        from blocked_users_schema import create_blocked_users_table
        
        engine = get_engine()
        if engine:
            create_blocked_users_table(engine)
            logger.info("تم التحقق من جدول المستخدمين المحظورين")
    except Exception as e:
        logger.error(f"خطأ في إنشاء جدول المحظورين: {e}")
    
    logger.info(f"تم تهيئة نظام الحماية الإداري مع {len(admin_ids)} مدير")
    return admin_security_manager

def get_admin_security_manager():
    """الحصول على مثيل مدير الحماية"""
    return admin_security_manager

# دوال مساعدة للاستخدام في ملفات أخرى
def is_user_blocked(user_id: int, context: CallbackContext) -> bool:
    """التحقق من حظر المستخدم"""
    if admin_security_manager:
        return admin_security_manager.is_user_blocked(user_id, context)
    return False

def is_admin(user_id: int) -> bool:
    """التحقق من كون المستخدم مدير"""
    if admin_security_manager:
        return admin_security_manager.is_admin(user_id)
    return False

async def check_user_access(update: Update, context: CallbackContext) -> bool:
    """التحقق من صلاحية وصول المستخدم"""
    if admin_security_manager:
        return await admin_security_manager.check_user_access(update, context)
    return True

def require_admin(func):
    """ديكوريتر للتحقق من صلاحيات المدير"""
    if admin_security_manager:
        return admin_security_manager.require_admin(func)
    return func

def require_registration(func):
    """ديكوريتر للتحقق من التسجيل وعدم الحظر"""
    if admin_security_manager:
        return admin_security_manager.require_registration_and_not_blocked(func)
    return func

async def verify_user_access(update: Update, context: CallbackContext) -> bool:
    """دالة للتحقق من الوصول (للاستخدام في ملفات أخرى)"""
    if admin_security_manager:
        return await admin_security_manager.check_user_access(update, context)
    return True

