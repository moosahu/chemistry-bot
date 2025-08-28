#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام التقارير الأسبوعية للبوت
يقوم بإنشاء تقرير Excel أسبوعي وإرساله بالإيميل
يستخدم نظام الإيميل الموجود في handlers.admin_tools.email_notification
"""

import logging
import smtplib
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os
from typing import Dict, List, Optional, Tuple
import schedule
import time
import threading

# إعداد التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# استيراد إعدادات الإيميل من النظام الموجود
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")

def is_email_configured():
    """التحقق من أن إعدادات البريد الإلكتروني تم تكوينها بشكل صحيح"""
    return (EMAIL_USERNAME is not None and EMAIL_USERNAME.strip() != "" and
            EMAIL_PASSWORD is not None and EMAIL_PASSWORD.strip() != "" and
            ADMIN_EMAIL is not None and ADMIN_EMAIL.strip() != "" and
            "@" in EMAIL_USERNAME and "@" in ADMIN_EMAIL)

class WeeklyReportGenerator:
    """مولد التقارير الأسبوعية"""
    
    def __init__(self, db_path: str):
        """
        تهيئة مولد التقارير
        
        Args:
            db_path: مسار قاعدة البيانات
        """
        self.db_path = db_path
        self.reports_dir = "weekly_reports"
        
        # إنشاء مجلد التقارير إذا لم يكن موجوداً
        os.makedirs(self.reports_dir, exist_ok=True)
        
    def get_week_range(self, date: datetime = None) -> Tuple[datetime, datetime]:
        """
        الحصول على نطاق الأسبوع (من الأحد إلى السبت)
        
        Args:
            date: التاريخ المرجعي (افتراضياً اليوم)
            
        Returns:
            tuple: (تاريخ بداية الأسبوع, تاريخ نهاية الأسبوع)
        """
        if date is None:
            date = datetime.now()
            
        # حساب بداية الأسبوع (الأحد)
        days_since_sunday = date.weekday() + 1  # Monday = 0, Sunday = 6
        if days_since_sunday == 7:  # إذا كان اليوم أحد
            days_since_sunday = 0
            
        week_start = date - timedelta(days=days_since_sunday)
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # حساب نهاية الأسبوع (السبت)
        week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
        
        return week_start, week_end
    
    def get_database_connection(self) -> sqlite3.Connection:
        """الحصول على اتصال بقاعدة البيانات"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # للحصول على النتائج كقاموس
            return conn
        except Exception as e:
            logger.error(f"خطأ في الاتصال بقاعدة البيانات: {e}")
            raise
    
    def get_weekly_stats(self, week_start: datetime, week_end: datetime) -> Dict:
        """
        الحصول على إحصائيات الأسبوع
        
        Args:
            week_start: بداية الأسبوع
            week_end: نهاية الأسبوع
            
        Returns:
            dict: إحصائيات الأسبوع
        """
        conn = self.get_database_connection()
        
        try:
            # إحصائيات عامة
            general_stats = {}
            
            # إجمالي المستخدمين المسجلين
            cursor = conn.execute("SELECT COUNT(*) as total_users FROM users")
            general_stats['total_users'] = cursor.fetchone()['total_users']
            
            # المستخدمين النشطين خلال الأسبوع
            cursor = conn.execute("""
                SELECT COUNT(DISTINCT user_id) as active_users 
                FROM quiz_sessions 
                WHERE start_timestamp BETWEEN ? AND ?
            """, (week_start.isoformat(), week_end.isoformat()))
            general_stats['active_users'] = cursor.fetchone()['active_users']
            
            # إجمالي الاختبارات المكتملة
            cursor = conn.execute("""
                SELECT COUNT(*) as completed_quizzes 
                FROM quiz_sessions 
                WHERE status = 'completed' 
                AND end_timestamp BETWEEN ? AND ?
            """, (week_start.isoformat(), week_end.isoformat()))
            general_stats['completed_quizzes'] = cursor.fetchone()['completed_quizzes']
            
            # إجمالي الأسئلة المجابة
            cursor = conn.execute("""
                SELECT COUNT(*) as total_questions 
                FROM question_interactions 
                WHERE answer_timestamp BETWEEN ? AND ?
            """, (week_start.isoformat(), week_end.isoformat()))
            general_stats['total_questions'] = cursor.fetchone()['total_questions']
            
            return general_stats
            
        except Exception as e:
            logger.error(f"خطأ في الحصول على الإحصائيات العامة: {e}")
            return {}
        finally:
            conn.close()
    
    def get_user_weekly_details(self, week_start: datetime, week_end: datetime) -> List[Dict]:
        """
        الحصول على تفاصيل المستخدمين للأسبوع
        
        Args:
            week_start: بداية الأسبوع
            week_end: نهاية الأسبوع
            
        Returns:
            list: قائمة بتفاصيل كل مستخدم
        """
        conn = self.get_database_connection()
        
        try:
            # الحصول على جميع المستخدمين مع إحصائياتهم
            query = """
            SELECT 
                u.user_id,
                u.username,
                u.first_seen_timestamp,
                u.last_active_timestamp,
                COUNT(DISTINCT qs.quiz_session_id) as weekly_quizzes,
                AVG(CASE WHEN qs.status = 'completed' THEN 
                    CAST(qs.score AS FLOAT) / qs.total_questions_in_quiz * 100 
                    ELSE NULL END) as avg_score,
                MAX(CASE WHEN qs.status = 'completed' THEN 
                    CAST(qs.score AS FLOAT) / qs.total_questions_in_quiz * 100 
                    ELSE NULL END) as max_score,
                MIN(CASE WHEN qs.status = 'completed' THEN 
                    CAST(qs.score AS FLOAT) / qs.total_questions_in_quiz * 100 
                    ELSE NULL END) as min_score,
                COUNT(qi.interaction_id) as total_questions_answered,
                SUM(CASE WHEN qi.is_correct = 1 THEN 1 ELSE 0 END) as correct_answers,
                SUM(CASE WHEN qi.is_correct = 0 THEN 1 ELSE 0 END) as incorrect_answers,
                COUNT(DISTINCT qs2.quiz_session_id) as total_quizzes_ever,
                AVG(CASE WHEN qs2.status = 'completed' THEN 
                    CAST(qs2.score AS FLOAT) / qs2.total_questions_in_quiz * 100 
                    ELSE NULL END) as overall_avg_score
            FROM users u
            LEFT JOIN quiz_sessions qs ON u.user_id = qs.user_id 
                AND qs.start_timestamp BETWEEN ? AND ?
            LEFT JOIN quiz_sessions qs2 ON u.user_id = qs2.user_id 
                AND qs2.status = 'completed'
            LEFT JOIN question_interactions qi ON qs.quiz_session_id = qi.quiz_session_id
                AND qi.answer_timestamp BETWEEN ? AND ?
            GROUP BY u.user_id, u.username, u.first_seen_timestamp, u.last_active_timestamp
            ORDER BY weekly_quizzes DESC, total_quizzes_ever DESC, u.user_id
            """
            
            cursor = conn.execute(query, (
                week_start.isoformat(), week_end.isoformat(),
                week_start.isoformat(), week_end.isoformat()
            ))
            
            users_data = []
            for row in cursor.fetchall():
                user_data = dict(row)
                
                # حساب نسبة النجاح
                total_answered = user_data['total_questions_answered'] or 0
                correct = user_data['correct_answers'] or 0
                
                if total_answered > 0:
                    user_data['success_rate'] = round((correct / total_answered) * 100, 2)
                else:
                    user_data['success_rate'] = 0
                
                # تنسيق النتائج
                user_data['avg_score'] = round(user_data['avg_score'] or 0, 2)
                user_data['max_score'] = round(user_data['max_score'] or 0, 2)
                user_data['min_score'] = round(user_data['min_score'] or 0, 2)
                user_data['overall_avg_score'] = round(user_data['overall_avg_score'] or 0, 2)
                
                # إضافة معلومات إضافية
                user_data['display_name'] = user_data['username'] or f"مستخدم {user_data['user_id']}"
                user_data['registration_date'] = user_data['first_seen_timestamp']
                user_data['last_activity'] = user_data['last_active_timestamp']
                
                # تحديد حالة النشاط
                if user_data['weekly_quizzes'] > 0:
                    user_data['activity_status'] = 'نشط هذا الأسبوع'
                elif user_data['total_quizzes_ever'] > 0:
                    user_data['activity_status'] = 'مسجل سابقاً'
                else:
                    user_data['activity_status'] = 'لم يبدأ أي اختبار'
                
                users_data.append(user_data)
            
            return users_data
            
        except Exception as e:
            logger.error(f"خطأ في الحصول على تفاصيل المستخدمين: {e}")
            return []
        finally:
            conn.close()
    
    def get_error_analysis(self, week_start: datetime, week_end: datetime) -> Dict:
        """
        تحليل الأخطاء الشائعة
        
        Args:
            week_start: بداية الأسبوع
            week_end: نهاية الأسبوع
            
        Returns:
            dict: تحليل الأخطاء
        """
        conn = self.get_database_connection()
        
        try:
            error_analysis = {}
            
            # الأسئلة الأكثر خطأً
            cursor = conn.execute("""
                SELECT 
                    question_id,
                    COUNT(*) as total_attempts,
                    SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) as wrong_answers,
                    ROUND(
                        CAST(SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) AS FLOAT) / 
                        COUNT(*) * 100, 2
                    ) as error_rate
                FROM question_interactions 
                WHERE answer_timestamp BETWEEN ? AND ?
                GROUP BY question_id
                HAVING total_attempts >= 5
                ORDER BY error_rate DESC, wrong_answers DESC
                LIMIT 10
            """, (week_start.isoformat(), week_end.isoformat()))
            
            error_analysis['most_difficult_questions'] = [dict(row) for row in cursor.fetchall()]
            
            # توزيع الدرجات
            cursor = conn.execute("""
                SELECT 
                    CASE 
                        WHEN CAST(score AS FLOAT) / total_questions_in_quiz * 100 >= 90 THEN 'ممتاز (90+)'
                        WHEN CAST(score AS FLOAT) / total_questions_in_quiz * 100 >= 80 THEN 'جيد جداً (80-89)'
                        WHEN CAST(score AS FLOAT) / total_questions_in_quiz * 100 >= 70 THEN 'جيد (70-79)'
                        WHEN CAST(score AS FLOAT) / total_questions_in_quiz * 100 >= 60 THEN 'مقبول (60-69)'
                        ELSE 'يحتاج تحسين (<60)'
                    END as grade_category,
                    COUNT(*) as count
                FROM quiz_sessions 
                WHERE status = 'completed' 
                AND end_timestamp BETWEEN ? AND ?
                GROUP BY grade_category
                ORDER BY 
                    CASE grade_category
                        WHEN 'ممتاز (90+)' THEN 1
                        WHEN 'جيد جداً (80-89)' THEN 2
                        WHEN 'جيد (70-79)' THEN 3
                        WHEN 'مقبول (60-69)' THEN 4
                        ELSE 5
                    END
            """, (week_start.isoformat(), week_end.isoformat()))
            
            error_analysis['grade_distribution'] = [dict(row) for row in cursor.fetchall()]
            
            return error_analysis
            
        except Exception as e:
            logger.error(f"خطأ في تحليل الأخطاء: {e}")
            return {}
        finally:
            conn.close()
    
    def create_excel_report(self, week_start: datetime, week_end: datetime) -> str:
        """
        إنشاء تقرير Excel
        
        Args:
            week_start: بداية الأسبوع
            week_end: نهاية الأسبوع
            
        Returns:
            str: مسار ملف التقرير
        """
        try:
            # الحصول على البيانات
            general_stats = self.get_weekly_stats(week_start, week_end)
            users_data = self.get_user_weekly_details(week_start, week_end)
            error_analysis = self.get_error_analysis(week_start, week_end)
            
            # إنشاء اسم الملف
            week_str = week_start.strftime("%Y-%m-%d")
            filename = f"weekly_report_{week_str}.xlsx"
            filepath = os.path.join(self.reports_dir, filename)
            
            # إنشاء ملف Excel
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                
                # Sheet 1: ملخص عام
                summary_data = {
                    'البيان': [
                        'فترة التقرير',
                        'إجمالي المستخدمين المسجلين',
                        'المستخدمين النشطين خلال الأسبوع',
                        'إجمالي الاختبارات المكتملة',
                        'إجمالي الأسئلة المجابة'
                    ],
                    'القيمة': [
                        f"{week_start.strftime('%Y-%m-%d')} إلى {week_end.strftime('%Y-%m-%d')}",
                        general_stats.get('total_users', 0),
                        general_stats.get('active_users', 0),
                        general_stats.get('completed_quizzes', 0),
                        general_stats.get('total_questions', 0)
                    ]
                }
                
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='ملخص عام', index=False)
                
                # Sheet 2: تفاصيل المستخدمين
                if users_data:
                    users_df = pd.DataFrame(users_data)
                    # اختيار الأعمدة المطلوبة وإعادة ترتيبها
                    columns_to_include = [
                        'user_id', 'display_name', 'registration_date', 'last_activity',
                        'activity_status', 'weekly_quizzes', 'total_quizzes_ever',
                        'avg_score', 'overall_avg_score', 'max_score', 'min_score',
                        'total_questions_answered', 'correct_answers', 'incorrect_answers', 'success_rate'
                    ]
                    
                    # التأكد من وجود الأعمدة
                    available_columns = [col for col in columns_to_include if col in users_df.columns]
                    users_df = users_df[available_columns]
                    
                    # إعادة تسمية الأعمدة للعربية
                    column_names = {
                        'user_id': 'معرف المستخدم',
                        'display_name': 'اسم المستخدم',
                        'registration_date': 'تاريخ التسجيل',
                        'last_activity': 'آخر نشاط',
                        'activity_status': 'حالة النشاط',
                        'weekly_quizzes': 'اختبارات هذا الأسبوع',
                        'total_quizzes_ever': 'إجمالي الاختبارات',
                        'avg_score': 'متوسط النتائج الأسبوعية',
                        'overall_avg_score': 'المتوسط العام',
                        'max_score': 'أعلى نتيجة',
                        'min_score': 'أقل نتيجة',
                        'total_questions_answered': 'الأسئلة المجابة',
                        'correct_answers': 'الإجابات الصحيحة',
                        'incorrect_answers': 'الإجابات الخاطئة',
                        'success_rate': 'نسبة النجاح %'
                    }
                    
                    users_df = users_df.rename(columns=column_names)
                    users_df.to_excel(writer, sheet_name='تفاصيل المستخدمين', index=False)
                
                # Sheet 3: تحليل الأخطاء
                if error_analysis.get('most_difficult_questions'):
                    difficult_df = pd.DataFrame(error_analysis['most_difficult_questions'])
                    difficult_df.columns = ['معرف السؤال', 'إجمالي المحاولات', 'الإجابات الخاطئة', 'نسبة الخطأ']
                    difficult_df.to_excel(writer, sheet_name='الأسئلة الأكثر صعوبة', index=False)
                
                if error_analysis.get('grade_distribution'):
                    grades_df = pd.DataFrame(error_analysis['grade_distribution'])
                    grades_df.columns = ['فئة الدرجة', 'العدد']
                    grades_df.to_excel(writer, sheet_name='توزيع الدرجات', index=False)
            
            logger.info(f"تم إنشاء التقرير بنجاح: {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"خطأ في إنشاء تقرير Excel: {e}")
            raise
    
    def send_email_report(self, report_path: str, week_start: datetime, week_end: datetime) -> bool:
        """
        إرسال التقرير بالإيميل
        
        Args:
            report_path: مسار ملف التقرير
            week_start: بداية الأسبوع
            week_end: نهاية الأسبوع
            
        Returns:
            bool: True إذا تم الإرسال بنجاح
        """
        try:
            # إنشاء رسالة الإيميل
            msg = MIMEMultipart()
            msg['From'] = EMAIL_USERNAME
            msg['To'] = ADMIN_EMAIL
            msg['Subject'] = f"تقرير أسبوعي - إحصائيات الاختبارات ({week_start.strftime('%Y-%m-%d')} - {week_end.strftime('%Y-%m-%d')})"
            
            # نص الرسالة
            body = f"""
السلام عليكم ورحمة الله وبركاته،

نرسل لكم التقرير الأسبوعي لإحصائيات الاختبارات للفترة من {week_start.strftime('%Y-%m-%d')} إلى {week_end.strftime('%Y-%m-%d')}.

يحتوي التقرير المرفق على:
- ملخص عام للإحصائيات
- تفاصيل أداء كل مستخدم
- تحليل الأخطاء الشائعة
- توزيع الدرجات

مع تحيات فريق البوت التعليمي
            """
            
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            # إرفاق ملف التقرير
            with open(report_path, "rb") as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
                
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename= {os.path.basename(report_path)}'
            )
            msg.attach(part)
            
            # إرسال الإيميل باستخدام النظام الموجود
            if not is_email_configured():
                logger.error("إعدادات البريد الإلكتروني غير مكونة بشكل صحيح")
                return False
                
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            
            text = msg.as_string()
            server.sendmail(EMAIL_USERNAME, ADMIN_EMAIL, text)
            server.quit()
            
            logger.info(f"تم إرسال التقرير بنجاح إلى {ADMIN_EMAIL}")
            return True
            
        except Exception as e:
            logger.error(f"خطأ في إرسال الإيميل: {e}")
            return False
    
    def generate_and_send_weekly_report(self) -> bool:
        """
        إنشاء وإرسال التقرير الأسبوعي
        
        Returns:
            bool: True إذا تم بنجاح
        """
        try:
            # الحصول على نطاق الأسبوع الماضي
            today = datetime.now()
            last_week_end = today - timedelta(days=today.weekday() + 1)  # نهاية الأسبوع الماضي
            week_start, week_end = self.get_week_range(last_week_end)
            
            logger.info(f"إنشاء تقرير للفترة: {week_start} - {week_end}")
            
            # إنشاء التقرير
            report_path = self.create_excel_report(week_start, week_end)
            
            # إرسال التقرير
            success = self.send_email_report(report_path, week_start, week_end)
            
            if success:
                logger.info("تم إنشاء وإرسال التقرير الأسبوعي بنجاح")
            else:
                logger.error("فشل في إرسال التقرير الأسبوعي")
                
            return success
            
        except Exception as e:
            logger.error(f"خطأ في إنشاء التقرير الأسبوعي: {e}")
            return False


class WeeklyReportScheduler:
    """جدولة التقارير الأسبوعية"""
    
    def __init__(self, report_generator: WeeklyReportGenerator):
        """
        تهيئة جدولة التقارير
        
        Args:
            report_generator: مولد التقارير
        """
        self.report_generator = report_generator
        self.is_running = False
        self.scheduler_thread = None
    
    def start_scheduler(self):
        """بدء جدولة التقارير"""
        if self.is_running:
            logger.warning("جدولة التقارير تعمل بالفعل")
            return
        
        # جدولة التقرير كل يوم أحد الساعة 9:00 صباحاً
        schedule.every().sunday.at("09:00").do(self.report_generator.generate_and_send_weekly_report)
        
        self.is_running = True
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        
        logger.info("تم بدء جدولة التقارير الأسبوعية - كل يوم أحد الساعة 9:00 صباحاً")
    
    def stop_scheduler(self):
        """إيقاف جدولة التقارير"""
        self.is_running = False
        schedule.clear()
        logger.info("تم إيقاف جدولة التقارير الأسبوعية")
    
    def _run_scheduler(self):
        """تشغيل الجدولة في خيط منفصل"""
        while self.is_running:
            schedule.run_pending()
            time.sleep(60)  # فحص كل دقيقة


# إعدادات افتراضية للإيميل (يجب تخصيصها)
DEFAULT_EMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'sender_email': 'your_bot_email@gmail.com',
    'sender_password': 'your_app_password',
    'admin_email': 'admin@example.com'
}

# مثال على الاستخدام
if __name__ == "__main__":
    # إعداد مولد التقارير
    db_path = "bot_stats.db"  # مسار قاعدة البيانات
    
    # يجب تخصيص إعدادات الإيميل
    email_config = DEFAULT_EMAIL_CONFIG.copy()
    
    # إنشاء مولد التقارير
    report_generator = WeeklyReportGenerator(db_path, email_config)
    
    # إنشاء جدولة التقارير
    scheduler = WeeklyReportScheduler(report_generator)
    
    # بدء الجدولة
    scheduler.start_scheduler()
    
    # إنشاء تقرير فوري للاختبار
    # report_generator.generate_and_send_weekly_report()
    
    logger.info("نظام التقارير الأسبوعية يعمل...")

