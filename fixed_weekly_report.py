#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام التقارير الأسبوعية المحسن والمتكامل
يعمل مع المكتبات الموجودة فقط (pandas, matplotlib, openpyxl)
"""

import os
import logging
import smtplib
import schedule
import time
import threading
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from sqlalchemy import create_engine, text
import json

logger = logging.getLogger(__name__)

class FixedWeeklyReportGenerator:
    """مولد التقارير الأسبوعية المحسن"""
    
    def __init__(self):
        """تهيئة مولد التقارير"""
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("متغير DATABASE_URL غير موجود")
        
        self.engine = create_engine(self.database_url)
        self.reports_dir = "fixed_reports"
        self.charts_dir = os.path.join(self.reports_dir, "charts")
        
        # إنشاء المجلدات
        os.makedirs(self.reports_dir, exist_ok=True)
        os.makedirs(self.charts_dir, exist_ok=True)
        
        logger.info(f"تم إعداد مولد التقارير المحسن - مجلد التقارير: {self.reports_dir}")
    
    def get_comprehensive_stats(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """الحصول على إحصائيات شاملة"""
        try:
            with self.engine.connect() as conn:
                # إحصائيات المستخدمين
                users_query = text("""
                    SELECT 
                        COUNT(*) as total_registered_users,
                        COUNT(CASE WHEN last_active_timestamp >= :start_date THEN 1 END) as active_users_this_week,
                        COUNT(CASE WHEN first_seen_timestamp >= :start_date THEN 1 END) as new_users_this_week
                    FROM users
                """)
                
                users_result = conn.execute(users_query, {
                    'start_date': start_date
                }).fetchone()
                
                # إحصائيات الاختبارات
                quiz_query = text("""
                    SELECT 
                        COUNT(*) as total_quizzes_this_week,
                        COUNT(DISTINCT user_id) as unique_users_this_week,
                        AVG(percentage) as avg_percentage_this_week,
                        SUM(total_questions) as total_questions_this_week,
                        AVG(time_taken_seconds) as avg_time_taken
                    FROM quiz_results 
                    WHERE completed_at >= :start_date AND completed_at <= :end_date
                """)
                
                quiz_result = conn.execute(quiz_query, {
                    'start_date': start_date,
                    'end_date': end_date
                }).fetchone()
                
                # حساب معدل المشاركة
                total_users = users_result.total_registered_users or 0
                active_users = users_result.active_users_this_week or 0
                engagement_rate = (active_users / total_users * 100) if total_users > 0 else 0
                
                return {
                    'total_registered_users': total_users,
                    'active_users_this_week': active_users,
                    'new_users_this_week': users_result.new_users_this_week or 0,
                    'engagement_rate': round(engagement_rate, 2),
                    'total_quizzes_this_week': quiz_result.total_quizzes_this_week or 0,
                    'unique_users_this_week': quiz_result.unique_users_this_week or 0,
                    'avg_percentage_this_week': round(quiz_result.avg_percentage_this_week or 0, 2),
                    'total_questions_this_week': quiz_result.total_questions_this_week or 0,
                    'avg_time_taken': round(quiz_result.avg_time_taken or 0, 2)
                }
                
        except Exception as e:
            logger.error(f"خطأ في الحصول على الإحصائيات الشاملة: {e}")
            return {}
    
    def get_user_progress_analysis(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """تحليل تقدم المستخدمين"""
        try:
            with self.engine.connect() as conn:
                query = text("""
                    SELECT 
                        u.user_id,
                        u.username,
                        u.first_name,
                        u.last_name,
                        u.full_name,
                        u.grade,
                        u.first_seen_timestamp,
                        u.last_active_timestamp,
                        COUNT(qr.result_id) as total_quizzes,
                        AVG(qr.percentage) as overall_avg_percentage,
                        SUM(qr.total_questions) as total_questions_answered,
                        AVG(qr.time_taken_seconds) as avg_time_per_quiz,
                        MAX(qr.completed_at) as last_quiz_date,
                        MIN(qr.completed_at) as first_quiz_date
                    FROM users u
                    LEFT JOIN quiz_results qr ON u.user_id = qr.user_id 
                        AND qr.completed_at >= :start_date 
                        AND qr.completed_at <= :end_date
                    GROUP BY u.user_id, u.username, u.first_name, u.last_name, 
                             u.full_name, u.grade, u.first_seen_timestamp, u.last_active_timestamp
                    ORDER BY overall_avg_percentage DESC NULLS LAST
                """)
                
                result = conn.execute(query, {
                    'start_date': start_date,
                    'end_date': end_date
                }).fetchall()
                
                users_analysis = []
                for row in result:
                    # تحديد مستوى الأداء
                    avg_percentage = row.overall_avg_percentage or 0
                    if avg_percentage >= 90:
                        performance_level = "ممتاز"
                    elif avg_percentage >= 80:
                        performance_level = "جيد جداً"
                    elif avg_percentage >= 70:
                        performance_level = "جيد"
                    elif avg_percentage >= 60:
                        performance_level = "متوسط"
                    elif avg_percentage > 0:
                        performance_level = "ضعيف"
                    else:
                        performance_level = "لم يشارك"
                    
                    # تحديد مستوى النشاط
                    total_quizzes = row.total_quizzes or 0
                    if total_quizzes >= 10:
                        activity_level = "نشط جداً"
                    elif total_quizzes >= 5:
                        activity_level = "نشط"
                    elif total_quizzes >= 1:
                        activity_level = "قليل النشاط"
                    else:
                        activity_level = "غير نشط"
                    
                    # تحليل الاتجاه (مبسط)
                    trend = "ثابت"  # يمكن تحسينه لاحقاً بتحليل أعمق
                    
                    users_analysis.append({
                        'user_id': row.user_id,
                        'username': row.username or 'غير محدد',
                        'full_name': row.full_name or f"{row.first_name or ''} {row.last_name or ''}".strip() or 'غير محدد',
                        'grade': row.grade or 'غير محدد',
                        'registration_date': row.first_seen_timestamp,
                        'last_active': row.last_active_timestamp,
                        'total_quizzes': total_quizzes,
                        'overall_avg_percentage': round(avg_percentage, 2),
                        'total_questions_answered': row.total_questions_answered or 0,
                        'avg_time_per_quiz': round(row.avg_time_per_quiz or 0, 2),
                        'performance_level': performance_level,
                        'activity_level': activity_level,
                        'trend': trend,
                        'last_quiz_date': row.last_quiz_date,
                        'first_quiz_date': row.first_quiz_date
                    })
                
                return users_analysis
                
        except Exception as e:
            logger.error(f"خطأ في تحليل تقدم المستخدمين: {e}")
            return []
    
    def get_grade_performance_analysis(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """تحليل أداء الصفوف الدراسية"""
        try:
            with self.engine.connect() as conn:
                query = text("""
                    SELECT 
                        u.grade,
                        COUNT(DISTINCT u.user_id) as total_students,
                        COUNT(qr.result_id) as total_quizzes,
                        AVG(qr.percentage) as avg_percentage,
                        COUNT(DISTINCT CASE WHEN qr.completed_at >= :start_date THEN u.user_id END) as active_students
                    FROM users u
                    LEFT JOIN quiz_results qr ON u.user_id = qr.user_id 
                        AND qr.completed_at >= :start_date 
                        AND qr.completed_at <= :end_date
                    WHERE u.grade IS NOT NULL AND u.grade != ''
                    GROUP BY u.grade
                    ORDER BY u.grade
                """)
                
                result = conn.execute(query, {
                    'start_date': start_date,
                    'end_date': end_date
                }).fetchall()
                
                grade_analysis = []
                for row in result:
                    participation_rate = (row.active_students / row.total_students * 100) if row.total_students > 0 else 0
                    
                    grade_analysis.append({
                        'grade': row.grade,
                        'total_students': row.total_students,
                        'active_students': row.active_students or 0,
                        'participation_rate': round(participation_rate, 2),
                        'total_quizzes': row.total_quizzes or 0,
                        'avg_percentage': round(row.avg_percentage or 0, 2)
                    })
                
                return grade_analysis
                
        except Exception as e:
            logger.error(f"خطأ في تحليل أداء الصفوف: {e}")
            return []
    
    def get_difficult_questions_analysis(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """تحليل الأسئلة الصعبة"""
        try:
            with self.engine.connect() as conn:
                query = text("""
                    SELECT 
                        ua.question_id,
                        COUNT(*) as total_attempts,
                        SUM(CASE WHEN ua.is_correct THEN 1 ELSE 0 END) as correct_answers,
                        ROUND(
                            (SUM(CASE WHEN ua.is_correct THEN 1 ELSE 0 END)::float / COUNT(*)) * 100, 
                            2
                        ) as success_rate
                    FROM user_answers ua
                    WHERE ua.answer_time >= :start_date AND ua.answer_time <= :end_date
                    GROUP BY ua.question_id
                    HAVING COUNT(*) >= 5  -- على الأقل 5 محاولات
                    ORDER BY success_rate ASC, total_attempts DESC
                    LIMIT 20
                """)
                
                result = conn.execute(query, {
                    'start_date': start_date,
                    'end_date': end_date
                }).fetchall()
                
                difficult_questions = []
                for row in result:
                    success_rate = row.success_rate or 0
                    
                    # تحديد مستوى الصعوبة
                    if success_rate < 30:
                        difficulty_level = "صعب جداً"
                        priority = "عالية"
                    elif success_rate < 50:
                        difficulty_level = "صعب"
                        priority = "متوسطة"
                    elif success_rate < 70:
                        difficulty_level = "متوسط"
                        priority = "منخفضة"
                    else:
                        difficulty_level = "سهل"
                        priority = "منخفضة"
                    
                    difficult_questions.append({
                        'question_id': row.question_id,
                        'total_attempts': row.total_attempts,
                        'correct_answers': row.correct_answers,
                        'wrong_answers': row.total_attempts - row.correct_answers,
                        'success_rate': success_rate,
                        'difficulty_level': difficulty_level,
                        'review_priority': priority
                    })
                
                return difficult_questions
                
        except Exception as e:
            logger.error(f"خطأ في تحليل الأسئلة الصعبة: {e}")
            return []
    
    def get_time_patterns_analysis(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """تحليل أنماط الوقت والنشاط"""
        try:
            with self.engine.connect() as conn:
                # النشاط اليومي
                daily_query = text("""
                    SELECT 
                        DATE(completed_at) as quiz_date,
                        COUNT(*) as quiz_count,
                        COUNT(DISTINCT user_id) as unique_users
                    FROM quiz_results
                    WHERE completed_at >= :start_date AND completed_at <= :end_date
                    GROUP BY DATE(completed_at)
                    ORDER BY quiz_date
                """)
                
                daily_result = conn.execute(daily_query, {
                    'start_date': start_date,
                    'end_date': end_date
                }).fetchall()
                
                # النشاط حسب الساعة
                hourly_query = text("""
                    SELECT 
                        EXTRACT(HOUR FROM completed_at) as hour,
                        COUNT(*) as quiz_count
                    FROM quiz_results
                    WHERE completed_at >= :start_date AND completed_at <= :end_date
                    GROUP BY EXTRACT(HOUR FROM completed_at)
                    ORDER BY quiz_count DESC
                    LIMIT 5
                """)
                
                hourly_result = conn.execute(hourly_query, {
                    'start_date': start_date,
                    'end_date': end_date
                }).fetchall()
                
                daily_activity = [
                    {
                        'date': row.quiz_date,
                        'quiz_count': row.quiz_count,
                        'unique_users': row.unique_users
                    }
                    for row in daily_result
                ]
                
                peak_hours = [
                    {
                        'hour': int(row.hour),
                        'quiz_count': row.quiz_count
                    }
                    for row in hourly_result
                ]
                
                return {
                    'daily_activity': daily_activity,
                    'peak_hours': peak_hours
                }
                
        except Exception as e:
            logger.error(f"خطأ في تحليل أنماط الوقت: {e}")
            return {'daily_activity': [], 'peak_hours': []}
    
    def generate_smart_recommendations(self, general_stats: Dict, user_progress: List, 
                                     grade_analysis: List, difficult_questions: List, 
                                     time_patterns: Dict) -> Dict[str, List[str]]:
        """إنشاء توصيات ذكية"""
        recommendations = {
            'للإدارة': [],
            'للمعلمين': [],
            'للمحتوى': [],
            'للنظام': []
        }
        
        try:
            # توصيات للإدارة
            engagement_rate = general_stats.get('engagement_rate', 0)
            if engagement_rate < 50:
                recommendations['للإدارة'].append(f"معدل المشاركة منخفض ({engagement_rate}%). يُنصح بحملة تحفيزية")
            
            active_users = general_stats.get('active_users_this_week', 0)
            total_users = general_stats.get('total_registered_users', 0)
            if total_users > 0 and active_users / total_users < 0.3:
                recommendations['للإدارة'].append("30% فقط من المستخدمين نشطين. يُنصح بمراجعة استراتيجية التفاعل")
            
            # توصيات للمعلمين
            weak_performers = [u for u in user_progress if u['performance_level'] in ['ضعيف', 'متوسط']]
            if len(weak_performers) > len(user_progress) * 0.3:
                recommendations['للمعلمين'].append(f"{len(weak_performers)} مستخدم يحتاجون مساعدة إضافية")
            
            # تحليل الصفوف الضعيفة
            weak_grades = [g for g in grade_analysis if g['avg_percentage'] < 70]
            for grade in weak_grades:
                recommendations['للمعلمين'].append(f"الصف {grade['grade']} يحتاج تركيز إضافي (متوسط: {grade['avg_percentage']}%)")
            
            # توصيات للمحتوى
            very_difficult = [q for q in difficult_questions if q['success_rate'] < 30]
            if very_difficult:
                recommendations['للمحتوى'].append(f"{len(very_difficult)} سؤال صعب جداً يحتاج مراجعة")
            
            # توصيات للنظام
            avg_time = general_stats.get('avg_time_taken', 0)
            if avg_time > 300:  # أكثر من 5 دقائق
                recommendations['للنظام'].append("متوسط وقت الإجابة مرتفع. قد تحتاج الأسئلة تبسيط")
            
            # توصيات الوقت
            peak_hours = time_patterns.get('peak_hours', [])
            if peak_hours:
                best_hour = peak_hours[0]['hour']
                recommendations['للنظام'].append(f"أفضل وقت للنشاط: الساعة {best_hour}:00. يُنصح بجدولة المحتوى الجديد")
            
        except Exception as e:
            logger.error(f"خطأ في إنشاء التوصيات الذكية: {e}")
        
        return recommendations
    
    def create_performance_charts(self, user_progress: List, grade_analysis: List, 
                                time_patterns: Dict) -> Dict[str, str]:
        """إنشاء الرسوم البيانية"""
        chart_paths = {}
        
        try:
            # إعداد matplotlib للعربية
            plt.rcParams['font.family'] = ['Arial Unicode MS', 'Tahoma', 'DejaVu Sans']
            
            # 1. توزيع مستويات الأداء
            if user_progress:
                performance_counts = {}
                for user in user_progress:
                    level = user['performance_level']
                    performance_counts[level] = performance_counts.get(level, 0) + 1
                
                if performance_counts:
                    fig, ax = plt.subplots(figsize=(10, 6))
                    levels = list(performance_counts.keys())
                    counts = list(performance_counts.values())
                    colors = ['#2E8B57', '#32CD32', '#FFD700', '#FF6347', '#DC143C', '#808080']
                    
                    bars = ax.bar(levels, counts, color=colors[:len(levels)])
                    ax.set_title('توزيع مستويات الأداء', fontsize=16, fontweight='bold')
                    ax.set_ylabel('عدد المستخدمين', fontsize=12)
                    ax.set_xlabel('مستوى الأداء', fontsize=12)
                    
                    # إضافة القيم على الأعمدة
                    for bar, count in zip(bars, counts):
                        height = bar.get_height()
                        ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                               f'{count}', ha='center', va='bottom', fontweight='bold')
                    
                    plt.xticks(rotation=45)
                    plt.tight_layout()
                    
                    chart_path = os.path.join(self.charts_dir, 'performance_distribution.png')
                    plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                    plt.close()
                    chart_paths['توزيع مستويات الأداء'] = chart_path
            
            # 2. مقارنة أداء الصفوف
            if grade_analysis:
                fig, ax = plt.subplots(figsize=(12, 6))
                grades = [g['grade'] for g in grade_analysis]
                percentages = [g['avg_percentage'] for g in grade_analysis]
                
                bars = ax.bar(grades, percentages, color='#4CAF50')
                ax.set_title('متوسط أداء الصفوف الدراسية', fontsize=16, fontweight='bold')
                ax.set_ylabel('متوسط النسبة المئوية (%)', fontsize=12)
                ax.set_xlabel('الصف الدراسي', fontsize=12)
                ax.set_ylim(0, 100)
                
                # إضافة خط المتوسط العام
                overall_avg = sum(percentages) / len(percentages) if percentages else 0
                ax.axhline(y=overall_avg, color='red', linestyle='--', 
                          label=f'المتوسط العام: {overall_avg:.1f}%')
                ax.legend()
                
                # إضافة القيم على الأعمدة
                for bar, percentage in zip(bars, percentages):
                    height = bar.get_height()
                    ax.text(bar.get_x() + bar.get_width()/2., height + 1,
                           f'{percentage:.1f}%', ha='center', va='bottom', fontweight='bold')
                
                plt.xticks(rotation=45)
                plt.tight_layout()
                
                chart_path = os.path.join(self.charts_dir, 'grade_performance.png')
                plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                plt.close()
                chart_paths['أداء الصفوف الدراسية'] = chart_path
            
            # 3. النشاط اليومي
            daily_activity = time_patterns.get('daily_activity', [])
            if daily_activity:
                fig, ax = plt.subplots(figsize=(12, 6))
                dates = [activity['date'] for activity in daily_activity]
                counts = [activity['quiz_count'] for activity in daily_activity]
                
                ax.plot(dates, counts, marker='o', linewidth=2, markersize=6, color='#2196F3')
                ax.fill_between(dates, counts, alpha=0.3, color='#2196F3')
                
                ax.set_title('النشاط اليومي للاختبارات', fontsize=16, fontweight='bold')
                ax.set_ylabel('عدد الاختبارات', fontsize=12)
                ax.set_xlabel('التاريخ', fontsize=12)
                
                # تنسيق التواريخ
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
                
                plt.xticks(rotation=45)
                plt.grid(True, alpha=0.3)
                plt.tight_layout()
                
                chart_path = os.path.join(self.charts_dir, 'daily_activity.png')
                plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                plt.close()
                chart_paths['النشاط اليومي'] = chart_path
            
        except Exception as e:
            logger.error(f"خطأ في إنشاء الرسوم البيانية: {e}")
        
        return chart_paths
    
    def create_fixed_excel_report(self, start_date: datetime, end_date: datetime) -> str:
        """إنشاء تقرير Excel محسن"""
        try:
            # جمع البيانات
            general_stats = self.get_comprehensive_stats(start_date, end_date)
            user_progress = self.get_user_progress_analysis(start_date, end_date)
            grade_analysis = self.get_grade_performance_analysis(start_date, end_date)
            difficult_questions = self.get_difficult_questions_analysis(start_date, end_date)
            time_patterns = self.get_time_patterns_analysis(start_date, end_date)
            smart_recommendations = self.generate_smart_recommendations(
                general_stats, user_progress, grade_analysis, difficult_questions, time_patterns
            )
            
            # إنشاء الرسوم البيانية
            chart_paths = self.create_performance_charts(user_progress, grade_analysis, time_patterns)
            
            # إنشاء ملف Excel
            report_filename = f"fixed_weekly_report_{start_date.strftime('%Y-%m-%d')}.xlsx"
            report_path = os.path.join(self.reports_dir, report_filename)
            
            with pd.ExcelWriter(report_path, engine='openpyxl') as writer:
                # 1. الملخص التنفيذي
                executive_summary = pd.DataFrame([
                    ['إجمالي المستخدمين المسجلين', general_stats.get('total_registered_users', 0)],
                    ['المستخدمين النشطين هذا الأسبوع', general_stats.get('active_users_this_week', 0)],
                    ['المستخدمين الجدد', general_stats.get('new_users_this_week', 0)],
                    ['معدل المشاركة (%)', general_stats.get('engagement_rate', 0)],
                    ['إجمالي الاختبارات', general_stats.get('total_quizzes_this_week', 0)],
                    ['متوسط الدرجات (%)', general_stats.get('avg_percentage_this_week', 0)],
                    ['إجمالي الأسئلة المجابة', general_stats.get('total_questions_this_week', 0)],
                    ['متوسط الوقت (ثانية)', general_stats.get('avg_time_taken', 0)]
                ], columns=['المؤشر', 'القيمة'])
                
                executive_summary.to_excel(writer, sheet_name='الملخص التنفيذي', index=False)
                
                # 2. تقدم المستخدمين
                if user_progress:
                    users_df = pd.DataFrame(user_progress)
                    users_df.to_excel(writer, sheet_name='تقدم المستخدمين', index=False)
                
                # 3. أداء الصفوف
                if grade_analysis:
                    grades_df = pd.DataFrame(grade_analysis)
                    grades_df.to_excel(writer, sheet_name='أداء الصفوف', index=False)
                
                # 4. الأسئلة الصعبة
                if difficult_questions:
                    questions_df = pd.DataFrame(difficult_questions)
                    questions_df.to_excel(writer, sheet_name='الأسئلة الصعبة', index=False)
                
                # 5. أنماط النشاط
                if time_patterns.get('daily_activity'):
                    daily_df = pd.DataFrame(time_patterns['daily_activity'])
                    daily_df.to_excel(writer, sheet_name='النشاط اليومي', index=False)
                
                if time_patterns.get('peak_hours'):
                    hourly_df = pd.DataFrame(time_patterns['peak_hours'])
                    hourly_df.to_excel(writer, sheet_name='ساعات الذروة', index=False)
                
                # 6. التوصيات الذكية
                recommendations_data = []
                for category, recs in smart_recommendations.items():
                    for rec in recs:
                        recommendations_data.append([category, rec])
                
                if recommendations_data:
                    recommendations_df = pd.DataFrame(recommendations_data, columns=['الفئة', 'التوصية'])
                    recommendations_df.to_excel(writer, sheet_name='التوصيات الذكية', index=False)
            
            logger.info(f"تم إنشاء التقرير المحسن: {report_path}")
            return report_path
            
        except Exception as e:
            logger.error(f"خطأ في إنشاء تقرير Excel المحسن: {e}")
            return None
    
    def send_email_report(self, report_path: str, chart_paths: Dict[str, str], 
                         start_date: datetime, end_date: datetime) -> bool:
        """إرسال التقرير بالإيميل"""
        try:
            # إعدادات الإيميل
            smtp_server = "smtp.gmail.com"
            smtp_port = 587
            sender_email = os.getenv('EMAIL_USERNAME')
            sender_password = os.getenv('EMAIL_PASSWORD')
            admin_email = os.getenv('ADMIN_EMAIL')
            
            if not all([sender_email, sender_password, admin_email]):
                logger.error("إعدادات الإيميل غير مكتملة")
                return False
            
            # إنشاء الرسالة
            msg = MIMEMultipart()
            msg['From'] = sender_email
            msg['To'] = admin_email
            msg['Subject'] = f"التقرير الأسبوعي المحسن - {start_date.strftime('%Y-%m-%d')} إلى {end_date.strftime('%Y-%m-%d')}"
            
            # محتوى الرسالة
            body = f"""
مرحباً،

إليك التقرير الأسبوعي المحسن لبوت الكيمياء التعليمي.

📊 فترة التقرير: {start_date.strftime('%Y-%m-%d')} إلى {end_date.strftime('%Y-%m-%d')}

📋 محتوى التقرير:
• الملخص التنفيذي مع المؤشرات الرئيسية
• تحليل مفصل لتقدم كل مستخدم
• أداء الصفوف الدراسية مع المقارنات
• الأسئلة الصعبة التي تحتاج مراجعة
• أنماط النشاط والأوقات المثلى
• توصيات ذكية للتحسين

📈 الرسوم البيانية المرفقة:
{chr(10).join([f"• {name}" for name in chart_paths.keys()])}

مع أطيب التحيات،
نظام التقارير المحسن
            """
            
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            # إرفاق ملف Excel
            if report_path and os.path.exists(report_path):
                with open(report_path, "rb") as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename= {os.path.basename(report_path)}'
                    )
                    msg.attach(part)
            
            # إرفاق الرسوم البيانية
            for chart_name, chart_path in chart_paths.items():
                if os.path.exists(chart_path):
                    with open(chart_path, "rb") as attachment:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(attachment.read())
                        encoders.encode_base64(part)
                        part.add_header(
                            'Content-Disposition',
                            f'attachment; filename= {chart_name}.png'
                        )
                        msg.attach(part)
            
            # إرسال الإيميل
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(sender_email, sender_password)
            text = msg.as_string()
            server.sendmail(sender_email, admin_email, text)
            server.quit()
            
            logger.info(f"تم إرسال التقرير المحسن بنجاح إلى {admin_email}")
            return True
            
        except Exception as e:
            logger.error(f"خطأ في إرسال التقرير المحسن: {e}")
            return False
    
    def generate_and_send_fixed_report(self) -> bool:
        """إنشاء وإرسال التقرير المحسن"""
        try:
            # تحديد فترة الأسبوع الماضي
            today = datetime.now()
            end_date = today - timedelta(days=today.weekday() + 1)  # نهاية الأسبوع الماضي
            start_date = end_date - timedelta(days=6)  # بداية الأسبوع الماضي
            
            # تعديل الأوقات
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            logger.info(f"إنشاء التقرير المحسن للفترة: {start_date} إلى {end_date}")
            
            # إنشاء التقرير
            report_path = self.create_fixed_excel_report(start_date, end_date)
            if not report_path:
                logger.error("فشل في إنشاء التقرير المحسن")
                return False
            
            # إنشاء الرسوم البيانية
            user_progress = self.get_user_progress_analysis(start_date, end_date)
            grade_analysis = self.get_grade_performance_analysis(start_date, end_date)
            time_patterns = self.get_time_patterns_analysis(start_date, end_date)
            chart_paths = self.create_performance_charts(user_progress, grade_analysis, time_patterns)
            
            # إرسال التقرير
            success = self.send_email_report(report_path, chart_paths, start_date, end_date)
            
            if success:
                logger.info("تم إنشاء وإرسال التقرير المحسن بنجاح")
            else:
                logger.error("فشل في إرسال التقرير المحسن")
            
            return success
            
        except Exception as e:
            logger.error(f"خطأ في إنشاء وإرسال التقرير المحسن: {e}")
            return False

class FixedWeeklyReportScheduler:
    """جدولة التقارير الأسبوعية المحسنة"""
    
    def __init__(self, report_generator: FixedWeeklyReportGenerator):
        self.report_generator = report_generator
        self.scheduler_thread = None
        self.running = False
    
    def start_scheduler(self):
        """بدء جدولة التقارير"""
        try:
            # جدولة التقرير الأسبوعي (كل يوم أحد الساعة 9:00 صباحاً)
            schedule.every().sunday.at("09:00").do(self._run_weekly_report)
            
            self.running = True
            self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
            self.scheduler_thread.start()
            
            logger.info("تم بدء جدولة التقارير المحسنة - كل يوم أحد الساعة 9:00 صباحاً")
            
        except Exception as e:
            logger.error(f"خطأ في بدء جدولة التقارير المحسنة: {e}")
    
    def _run_scheduler(self):
        """تشغيل الجدولة"""
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(60)  # فحص كل دقيقة
            except Exception as e:
                logger.error(f"خطأ في تشغيل جدولة التقارير المحسنة: {e}")
                time.sleep(60)
    
    def _run_weekly_report(self):
        """تشغيل التقرير الأسبوعي"""
        try:
            logger.info("بدء إنشاء التقرير الأسبوعي المحسن المجدول...")
            success = self.report_generator.generate_and_send_fixed_report()
            
            if success:
                logger.info("تم إنشاء وإرسال التقرير الأسبوعي المحسن المجدول بنجاح")
            else:
                logger.error("فشل في إنشاء التقرير الأسبوعي المحسن المجدول")
                
        except Exception as e:
            logger.error(f"خطأ في التقرير الأسبوعي المحسن المجدول: {e}")
    
    def stop_scheduler(self):
        """إيقاف الجدولة"""
        self.running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        logger.info("تم إيقاف جدولة التقارير المحسنة")

def is_fixed_email_configured() -> bool:
    """التحقق من إعدادات الإيميل المحسنة"""
    required_vars = ['EMAIL_USERNAME', 'EMAIL_PASSWORD', 'ADMIN_EMAIL']
    return all(os.getenv(var) for var in required_vars)

