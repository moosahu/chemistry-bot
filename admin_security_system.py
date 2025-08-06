#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام الحماية مع التحكم الإداري اليدوي
يسمح للمدير بحظر وإلغاء حظر المستخدمين يدوياً
"""

import logging
import json
import os
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
    """مدير الحماية مع التحكم الإداري اليدوي"""
    
    def __init__(self, admin_ids: List[int], blocked_users_file: str = "blocked_users.json"):
        self.admin_ids = set(admin_ids)  # معرفات المدراء
        self.blocked_users_file = blocked_users_file
        self.blocked_users: Set[int] = set()  # المستخدمون المحظورون
        self.blocked_users_info: Dict[int, Dict] = {}  # معلومات الحظر
        
        # تحميل قائمة المحظورين من الملف
        self.load_blocked_users()
        
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
            "access_denied": "🚫 تم رفض الوصول."
        }
    
    def load_blocked_users(self):
        """تحميل قائمة المستخدمين المحظورين من الملف"""
        try:
            if os.path.exists(self.blocked_users_file):
                with open(self.blocked_users_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.blocked_users = set(data.get('blocked_users', []))
                    self.blocked_users_info = data.get('blocked_users_info', {})
                    # تحويل مفاتيح معلومات الحظر إلى أرقام صحيحة
                    self.blocked_users_info = {
                        int(k): v for k, v in self.blocked_users_info.items()
                    }
                logger.info(f"تم تحميل {len(self.blocked_users)} مستخدم محظور")
        except Exception as e:
            logger.error(f"خطأ في تحميل قائمة المحظورين: {e}")
            self.blocked_users = set()
            self.blocked_users_info = {}
    
    def save_blocked_users(self):
        """حفظ قائمة المستخدمين المحظورين في الملف"""
        try:
            data = {
                'blocked_users': list(self.blocked_users),
                'blocked_users_info': {
                    str(k): v for k, v in self.blocked_users_info.items()
                },
                'last_updated': datetime.now().isoformat()
            }
            with open(self.blocked_users_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("تم حفظ قائمة المحظورين")
        except Exception as e:
            logger.error(f"خطأ في حفظ قائمة المحظورين: {e}")
    
    def is_admin(self, user_id: int) -> bool:
        """التحقق من كون المستخدم مدير"""
        return user_id in self.admin_ids
    
    def is_user_blocked(self, user_id: int) -> bool:
        """التحقق من حظر المستخدم"""
        return user_id in self.blocked_users
    
    def block_user(self, user_id: int, admin_id: int, reason: str = "غير محدد") -> bool:
        """حظر مستخدم (بواسطة المدير)"""
        if user_id in self.admin_ids:
            logger.warning(f"محاولة حظر مدير: {user_id}")
            return False
        
        if user_id not in self.blocked_users:
            self.blocked_users.add(user_id)
            self.blocked_users_info[user_id] = {
                'blocked_by': admin_id,
                'blocked_at': datetime.now().isoformat(),
                'reason': reason
            }
            self.save_blocked_users()
            logger.info(f"تم حظر المستخدم {user_id} بواسطة المدير {admin_id}")
            return True
        return False
    
    def unblock_user(self, user_id: int, admin_id: int) -> bool:
        """إلغاء حظر مستخدم (بواسطة المدير)"""
        if user_id in self.blocked_users:
            self.blocked_users.remove(user_id)
            if user_id in self.blocked_users_info:
                self.blocked_users_info[user_id]['unblocked_by'] = admin_id
                self.blocked_users_info[user_id]['unblocked_at'] = datetime.now().isoformat()
                # يمكن الاحتفاظ بالمعلومات للسجل أو حذفها
                # del self.blocked_users_info[user_id]
            self.save_blocked_users()
            logger.info(f"تم إلغاء حظر المستخدم {user_id} بواسطة المدير {admin_id}")
            return True
        return False
    
    def get_blocked_users_list(self) -> List[Dict]:
        """الحصول على قائمة المستخدمين المحظورين مع معلوماتهم"""
        blocked_list = []
        for user_id in self.blocked_users:
            info = self.blocked_users_info.get(user_id, {})
            blocked_list.append({
                'user_id': user_id,
                'blocked_by': info.get('blocked_by'),
                'blocked_at': info.get('blocked_at'),
                'reason': info.get('reason', 'غير محدد')
            })
        return blocked_list
    
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
        if self.is_user_blocked(user_id):
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
                from registration import is_user_fully_registered, get_user_info
                
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
    logger.info(f"تم تهيئة نظام الحماية الإداري مع {len(admin_ids)} مدير")
    return admin_security_manager

def get_admin_security_manager():
    """الحصول على مثيل مدير الحماية"""
    return admin_security_manager

# دوال مساعدة للاستخدام في ملفات أخرى
def is_user_blocked(user_id: int) -> bool:
    """التحقق من حظر المستخدم"""
    if admin_security_manager:
        return admin_security_manager.is_user_blocked(user_id)
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

