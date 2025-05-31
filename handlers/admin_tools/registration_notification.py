#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
وحدة ربط إشعارات البريد الإلكتروني بعملية التسجيل
تستخدم لإرسال تنبيهات للمدير عند تسجيل مستخدمين جدد
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from handlers.admin_tools.email_notification import send_new_user_notification_async

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def notify_admin_on_registration(user_id, user_data, context: ContextTypes.DEFAULT_TYPE):
    """
    إرسال إشعار للمدير عند تسجيل مستخدم جديد
    
    المعلمات:
        user_id (int): معرف المستخدم
        user_data (dict): بيانات المستخدم
        context (ContextTypes.DEFAULT_TYPE): سياق المحادثة
    """
    try:
        # الحصول على مدير قاعدة البيانات
        db_manager = context.bot_data.get("DB_MANAGER")
        if not db_manager:
            logger.error(f"لا يمكن الوصول إلى DB_MANAGER في notify_admin_on_registration للمستخدم {user_id}")
            return
        
        # الحصول على معلومات المستخدم الإضافية من قاعدة البيانات
        user_info = None
        if hasattr(db_manager, 'get_user_info'):
            user_info = db_manager.get_user_info(user_id)
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
        
        if not user_info:
            logger.error(f"لم يتم العثور على معلومات للمستخدم {user_id} في notify_admin_on_registration")
            return
        
        # دمج بيانات المستخدم من user_data و user_info
        notification_data = {
            'user_id': user_id,
            'username': user_info.get('username', ''),
            'full_name': user_data.get('full_name', user_info.get('full_name', '')),
            'email': user_data.get('email', user_info.get('email', '')),
            'phone': user_data.get('phone', user_info.get('phone', '')),
            'grade': user_data.get('grade', user_info.get('grade', ''))
        }
        
        # إرسال إشعار بريد إلكتروني للمدير
        success = await send_new_user_notification_async(notification_data)
        
        if success:
            logger.info(f"تم إرسال إشعار بريد إلكتروني للمدير عن المستخدم الجديد {user_id}")
        else:
            logger.warning(f"فشل إرسال إشعار بريد إلكتروني للمدير عن المستخدم الجديد {user_id}")
    
    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار للمدير عن المستخدم الجديد {user_id}: {e}")
