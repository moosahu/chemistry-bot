#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
وحدة إرسال إشعارات البريد الإلكتروني للمدير
تستخدم لإرسال تنبيهات عند تسجيل مستخدمين جدد
"""

import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# إعدادات البريد الإلكتروني - تعتمد كلياً على متغيرات البيئة
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")  # يجب إعداده في متغيرات البيئة
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")  # يجب إعداده في متغيرات البيئة  
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")  # يجب إعداده في متغيرات البيئة

# التحقق من صحة الإعدادات
def is_email_configured():
    """التحقق من أن إعدادات البريد الإلكتروني تم تكوينها بشكل صحيح"""
    return (EMAIL_USERNAME is not None and EMAIL_USERNAME.strip() != "" and
            EMAIL_PASSWORD is not None and EMAIL_PASSWORD.strip() != "" and
            ADMIN_EMAIL is not None and ADMIN_EMAIL.strip() != "" and
            "@" in EMAIL_USERNAME and "@" in ADMIN_EMAIL)

def send_new_user_notification(user_data):
    """
    إرسال إشعار بريد إلكتروني للمدير عند تسجيل مستخدم جديد
    
    المعلمات:
        user_data (dict): بيانات المستخدم الجديد
    
    العائد:
        bool: True إذا تم إرسال البريد بنجاح، False خلاف ذلك
    """
    try:
        # التحقق من تكوين إعدادات البريد الإلكتروني
        if not is_email_configured():
            logger.warning("إعدادات البريد الإلكتروني غير مكونة بشكل صحيح. يرجى إعداد متغيرات البيئة التالية في Render:")
            logger.warning("- EMAIL_USERNAME: عنوان البريد الإلكتروني")
            logger.warning("- EMAIL_PASSWORD: كلمة مرور التطبيق من Gmail")
            logger.warning("- ADMIN_EMAIL: بريد المدير لاستقبال الإشعارات")
            return False
        # إنشاء رسالة البريد الإلكتروني
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USERNAME
        msg['To'] = ADMIN_EMAIL
        msg['Subject'] = f"تسجيل مستخدم جديد في بوت الاختبارات - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # إعداد محتوى الرسالة
        body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; direction: rtl; text-align: right; }}
                .container {{ padding: 20px; }}
                .header {{ background-color: #4CAF50; color: white; padding: 10px; text-align: center; }}
                .content {{ margin-top: 20px; }}
                .user-info {{ border: 1px solid #ddd; padding: 15px; border-radius: 5px; }}
                .footer {{ margin-top: 20px; font-size: 12px; color: #777; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>تسجيل مستخدم جديد في بوت الاختبارات</h2>
                </div>
                <div class="content">
                    <p>تم تسجيل مستخدم جديد في بوت الاختبارات. فيما يلي تفاصيل المستخدم:</p>
                    <div class="user-info">
                        <p><strong>معرف المستخدم:</strong> {user_data.get('user_id', 'غير متوفر')}</p>
                        <p><strong>اسم المستخدم:</strong> {user_data.get('username', 'غير متوفر')}</p>
                        <p><strong>الاسم الكامل:</strong> {user_data.get('full_name', 'غير متوفر')}</p>
                        <p><strong>البريد الإلكتروني:</strong> {user_data.get('email', 'غير متوفر')}</p>
                        <p><strong>رقم الجوال:</strong> {user_data.get('phone', 'غير متوفر')}</p>
                        <p><strong>الصف الدراسي:</strong> {user_data.get('grade', 'غير متوفر')}</p>
                        <p><strong>تاريخ التسجيل:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    </div>
                </div>
                <div class="footer">
                    <p>هذه رسالة آلية من نظام بوت الاختبارات. يرجى عدم الرد على هذا البريد الإلكتروني.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # إضافة المحتوى إلى الرسالة
        msg.attach(MIMEText(body, 'html'))
        
        # إنشاء اتصال SMTP وإرسال الرسالة
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()  # تفعيل TLS للأمان
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"تم إرسال إشعار بريد إلكتروني للمدير عن المستخدم الجديد {user_data.get('user_id')}")
        return True
    
    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار البريد الإلكتروني: {e}")
        return False

async def send_new_user_notification_async(user_data):
    """
    نسخة غير متزامنة من دالة إرسال إشعار البريد الإلكتروني
    
    المعلمات:
        user_data (dict): بيانات المستخدم الجديد
    
    العائد:
        bool: True إذا تم إرسال البريد بنجاح، False خلاف ذلك
    """
    import asyncio
    
    # تنفيذ دالة إرسال البريد الإلكتروني في مجموعة منفصلة لتجنب تعطيل البوت
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, send_new_user_notification, user_data)
    return result


def send_account_deletion_notification(user_data):
    """إرسال إشعار بريد إلكتروني للمدير عند حذف مستخدم حسابه"""
    try:
        if not is_email_configured():
            logger.warning("إعدادات البريد غير مكونة — لن يتم إرسال إشعار الحذف")
            return False

        msg = MIMEMultipart()
        msg['From'] = EMAIL_USERNAME
        msg['To'] = ADMIN_EMAIL
        msg['Subject'] = f"🗑 حذف حساب مستخدم - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; direction: rtl; text-align: right; }}
                .container {{ padding: 20px; }}
                .header {{ background-color: #e74c3c; color: white; padding: 10px; text-align: center; }}
                .content {{ margin-top: 20px; }}
                .user-info {{ border: 1px solid #ddd; padding: 15px; border-radius: 5px; background-color: #fff5f5; }}
                .footer {{ margin-top: 20px; font-size: 12px; color: #777; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>🗑 حذف حساب مستخدم</h2>
                </div>
                <div class="content">
                    <p>قام مستخدم بحذف حسابه من بوت الاختبارات:</p>
                    <div class="user-info">
                        <p><strong>معرف المستخدم:</strong> {user_data.get('user_id', 'غير متوفر')}</p>
                        <p><strong>الاسم:</strong> {user_data.get('full_name', 'غير متوفر')}</p>
                        <p><strong>البريد:</strong> {user_data.get('email', 'غير متوفر')}</p>
                        <p><strong>الجوال:</strong> {user_data.get('phone', 'غير متوفر')}</p>
                        <p><strong>الصف:</strong> {user_data.get('grade', 'غير متوفر')}</p>
                        <p><strong>عدد الاختبارات المحذوفة:</strong> {user_data.get('quizzes_deleted', 0)}</p>
                        <p><strong>تاريخ الحذف:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    </div>
                </div>
                <div class="footer">
                    <p>هذا إشعار تلقائي من بوت كيم تحصيلي</p>
                </div>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(body, 'html', 'utf-8'))
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.sendmail(EMAIL_USERNAME, ADMIN_EMAIL, msg.as_string())

        logger.info(f"تم إرسال إشعار حذف حساب المستخدم {user_data.get('user_id')}")
        return True
    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار الحذف: {e}")
        return False


async def send_account_deletion_notification_async(user_data):
    """نسخة غير متزامنة"""
    import asyncio
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, send_account_deletion_notification, user_data)
    return result
