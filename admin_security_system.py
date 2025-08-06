#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام الحماية مع التحكم الإداري اليدوي - يستخدم قاعدة البيانات
يسمح للمدير بحظر وإلغاء حظر المستخدمين يدوياً
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

# إعداد التسجيل
logger = logging.getLogger(__name__)

class AdminSecurityManager:
    """مدير الحماية مع التحكم الإداري اليدوي - يستخدم قاعدة البيانات"""
    
    def __init__(self, admin_ids: List[int]):
        self.admin_ids = set(admin_ids)  # معرفات المدراء
        
        # رسائل النظام
        self.messages = {
            "not_registered": "❌ عذراً، يجب عليك التسجيل أولاً لاستخدام البوت.\n\nاستخدم الأمر /start للتسجيل.",
            "user_blocked": "🚫 تم حظرك من استخدام هذا البوت.\n\nإذا كنت تعتقد أن هذا خطأ، تواصل مع الإدارة.",
            "admin_only": "👑 هذا الأمر متاح للمدراء فقط.",
            "user_not_found": "❌ لم يتم العثور على المستخدم.",
            "user_blocked_success": "✅ تم حظر المستخدم بنجاح.",
            "user_unblocked_success": "✅ تم إلغاء حظر المستخدم بنجاح.",
            "user_already_blocked": "⚠️ المستخدم محظور بالفعل.",
            "user_not_blocked": "⚠️ المستخدم غير محظور.",
            "access_denied": "🚫 تم رفض الوصول.",
            "database_error": "❌ خطأ في قاعدة البيانات. يرجى المحاولة لاحقاً."
        }
    
    def get_db_session(self, context: CallbackContext):
        """الحصول على جلسة قاعدة البيانات"""
        try:
            db_manager = context.bot_data.get("DB_MANAGER")
            if db_manager and hasattr(db_manager, 'get_session'):
                return db_manager.get_session()
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
                logger.error("لا يمكن الحصول على جلسة قاعدة البيانات")
                return False
            
            from blocked_users_schema import is_user_blocked_in_db
            result = is_user_blocked_in_db(session, user_id)
            session.close()
            return result
            
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
            
            from blocked_users_schema import block_user_in_db
            success, message = block_user_in_db(session, user_id, admin_id, reason)
            session.close()
            
            if success:
                logger.info(f"تم حظر المستخدم {user_id} بواسطة المدير {admin_id}")
            else:
                logger.warning(f"فشل حظر المستخدم {user_id}: {message}")
            
            return success
            
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
            
            from blocked_users_schema import unblock_user_in_db
            success, message = unblock_user_in_db(session, user_id, admin_id)
            session.close()
            
            if success:
                logger.info(f"تم إلغاء حظر المستخدم {user_id} بواسطة المدير {admin_id}")
            else:
                logger.warning(f"فشل إلغاء حظر المستخدم {user_id}: {message}")
            
            return success
            
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
            
            from blocked_users_schema import get_blocked_users_list_from_db
            result = get_blocked_users_list_from_db(session)
            session.close()
            return result
            
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

