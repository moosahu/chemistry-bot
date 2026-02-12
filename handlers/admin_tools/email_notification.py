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


def send_study_report_email(plans, filter_label="الكل"):
    """
    إرسال تقرير جداول المذاكرة بالإيميل مع جدول HTML مفصل
    
    المعلمات:
        plans (list): بيانات الجداول من get_study_schedule_report
        filter_label (str): نوع الفلتر (الكل / طلابي)
    """
    try:
        if not is_email_configured():
            logger.warning("إعدادات البريد غير مكونة — لن يتم إرسال تقرير جداول المذاكرة")
            return False

        # تصنيف الطلاب
        active_plans = [p for p in plans if p.get('is_active')]
        progressing = [p for p in active_plans if p.get('completed_days', 0) > 0]
        inactive = [p for p in active_plans if p.get('completed_days', 0) == 0]
        stopped = [p for p in progressing if p.get('days_since_activity') and p['days_since_activity'] > 3]
        consistent = [p for p in progressing if not p.get('days_since_activity') or p['days_since_activity'] <= 3]

        # بناء صفوف الجدول
        def build_rows(student_list, status_label, status_color):
            rows = ""
            for p in student_list:
                study_days = p.get('study_days', 0) or 1
                completed = p.get('completed_days', 0)
                pct = round(completed / study_days * 100) if study_days > 0 else 0
                star = "⭐ " if p.get('is_my_student') else ""
                name = p.get('full_name') or 'بدون اسم'
                grade = p.get('grade') or '-'
                subject = p.get('subject') or '-'
                last_act = ''
                if p.get('last_activity'):
                    try:
                        last_act = p['last_activity'].strftime('%m/%d')
                    except:
                        last_act = str(p['last_activity'])[:10]
                days_ago = p.get('days_since_activity', '-') or '-'
                created = ''
                if p.get('created_at'):
                    try:
                        created = p['created_at'].strftime('%m/%d')
                    except:
                        created = str(p['created_at'])[:10]

                # شريط التقدم بسيط
                bar_width = min(pct, 100)
                bar_color = '#27ae60' if pct >= 50 else '#f39c12' if pct >= 20 else '#e74c3c'
                progress_bar = f'<div style="background:#eee;border-radius:3px;height:12px;width:80px;display:inline-block;"><div style="background:{bar_color};height:12px;border-radius:3px;width:{bar_width}%;"></div></div> {pct}%'

                rows += f"""
                <tr>
                    <td style="padding:6px 8px;border:1px solid #ddd;">{star}{name}</td>
                    <td style="padding:6px 8px;border:1px solid #ddd;text-align:center;">{grade}</td>
                    <td style="padding:6px 8px;border:1px solid #ddd;text-align:center;">{subject[:30]}</td>
                    <td style="padding:6px 8px;border:1px solid #ddd;text-align:center;">{progress_bar}</td>
                    <td style="padding:6px 8px;border:1px solid #ddd;text-align:center;">{completed}/{study_days}</td>
                    <td style="padding:6px 8px;border:1px solid #ddd;text-align:center;">{last_act}</td>
                    <td style="padding:6px 8px;border:1px solid #ddd;text-align:center;">{days_ago}</td>
                    <td style="padding:6px 8px;border:1px solid #ddd;text-align:center;"><span style="color:{status_color};font-weight:bold;">{status_label}</span></td>
                    <td style="padding:6px 8px;border:1px solid #ddd;text-align:center;">{created}</td>
                </tr>"""
            return rows

        all_rows = ""
        all_rows += build_rows(consistent, "✅ مستمر", "#27ae60")
        all_rows += build_rows(stopped, "⚠️ متوقف", "#e67e22")
        all_rows += build_rows(inactive, "❌ لم يبدأ", "#e74c3c")

        now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

        body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; direction: rtl; text-align: right; background: #f5f5f5; }}
                .container {{ max-width: 900px; margin: 0 auto; padding: 20px; background: white; }}
                .header {{ background: linear-gradient(135deg, #2c3e50, #3498db); color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                .summary {{ display: flex; gap: 15px; margin: 20px 0; flex-wrap: wrap; }}
                .stat-box {{ flex: 1; min-width: 120px; padding: 15px; border-radius: 8px; text-align: center; }}
                .stat-box h3 {{ margin: 0; font-size: 24px; }}
                .stat-box p {{ margin: 5px 0 0; font-size: 12px; color: #666; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 13px; }}
                th {{ background: #2c3e50; color: white; padding: 10px 8px; border: 1px solid #2c3e50; }}
                tr:nth-child(even) {{ background: #f8f9fa; }}
                .footer {{ text-align: center; color: #999; font-size: 11px; margin-top: 30px; padding-top: 15px; border-top: 1px solid #eee; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>📅 تقرير جداول المذاكرة ({filter_label})</h2>
                    <p>{now_str}</p>
                </div>

                <div class="summary">
                    <div class="stat-box" style="background:#e8f5e9;">
                        <h3>{len(consistent)}</h3>
                        <p>✅ مستمرين</p>
                    </div>
                    <div class="stat-box" style="background:#fff3e0;">
                        <h3>{len(stopped)}</h3>
                        <p>⚠️ متوقفين</p>
                    </div>
                    <div class="stat-box" style="background:#ffebee;">
                        <h3>{len(inactive)}</h3>
                        <p>❌ لم يبدأوا</p>
                    </div>
                    <div class="stat-box" style="background:#e3f2fd;">
                        <h3>{len(plans)}</h3>
                        <p>📊 إجمالي الجداول</p>
                    </div>
                </div>

                <table>
                    <thead>
                        <tr>
                            <th>الطالب</th>
                            <th>الصف</th>
                            <th>المواد</th>
                            <th>التقدم</th>
                            <th>الأيام</th>
                            <th>آخر نشاط</th>
                            <th>أيام التوقف</th>
                            <th>الحالة</th>
                            <th>تاريخ الإنشاء</th>
                        </tr>
                    </thead>
                    <tbody>
                        {all_rows}
                    </tbody>
                </table>

                <div class="footer">
                    <p>بوت كيم تحصيلي — تقرير تلقائي @CHEMISTRY_QUIZ2_BOT</p>
                </div>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart()
        msg['From'] = EMAIL_USERNAME
        msg['To'] = ADMIN_EMAIL
        msg['Subject'] = f"📅 تقرير جداول المذاكرة ({filter_label}) — {now_str}"
        msg.attach(MIMEText(body, 'html', 'utf-8'))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.sendmail(EMAIL_USERNAME, ADMIN_EMAIL, msg.as_string())

        logger.info(f"[StudyReport] Email sent: {len(plans)} plans, filter={filter_label}")
        return True

    except Exception as e:
        logger.error(f"[StudyReport] Email error: {e}")
        return False
