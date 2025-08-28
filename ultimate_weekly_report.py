#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام التقارير الأسبوعية المتكامل والذكي
يوفر تحليلات عميقة وتوصيات ذكية لتحسين الأداء
"""

import os
import logging
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import schedule
import time
import threading
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from sqlalchemy import create_engine, text
from typing import Dict, List, Any, Optional, Tuple
import numpy as np
from io import BytesIO
import base64

# إعداد matplotlib للعربية
plt.rcParams['font.family'] = ['Arial Unicode MS', 'Tahoma', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

logger = logging.getLogger(__name__)

class UltimateWeeklyReportGenerator:
    """مولد التقارير الأسبوعية المتكامل والذكي"""
    
    def __init__(self):
        """تهيئة مولد التقارير"""
        self.reports_dir = "ultimate_reports"
        self.charts_dir = os.path.join(self.reports_dir, "charts")
        self.ensure_directories()
        
        # الحصول على اتصال قاعدة البيانات
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is required")
        
        self.engine = create_engine(self.database_url)
        
        # إعداد الألوان والأنماط
        self.colors = {
            'primary': '#2E86AB',
            'secondary': '#A23B72', 
            'success': '#F18F01',
            'warning': '#C73E1D',
            'info': '#6A994E',
            'light': '#F8F9FA',
            'dark': '#343A40'
        }
        
    def ensure_directories(self):
        """التأكد من وجود المجلدات المطلوبة"""
        for directory in [self.reports_dir, self.charts_dir]:
            if not os.path.exists(directory):
                os.makedirs(directory)
                logger.info(f"تم إنشاء مجلد: {directory}")
    
    def get_comprehensive_stats(self, week_start: datetime, week_end: datetime) -> Dict[str, Any]:
        """الحصول على إحصائيات شاملة ومتقدمة"""
        try:
            with self.engine.connect() as conn:
                # الإحصائيات العامة المتقدمة
                general_query = text("""
                    WITH user_stats AS (
                        SELECT 
                            u.user_id,
                            u.username,
                            u.first_name,
                            u.last_name,
                            u.grade,
                            u.first_seen_timestamp,
                            u.last_active_timestamp,
                            COUNT(qr.result_id) as total_quizzes,
                            AVG(qr.score) as avg_score,
                            AVG(qr.percentage) as avg_percentage,
                            MAX(qr.score) as best_score,
                            MIN(qr.score) as worst_score,
                            SUM(qr.total_questions) as total_questions_attempted,
                            AVG(qr.time_taken_seconds) as avg_time_taken,
                            COUNT(CASE WHEN qr.completed_at >= :week_start AND qr.completed_at <= :week_end THEN 1 END) as weekly_quizzes
                        FROM users u
                        LEFT JOIN quiz_results qr ON u.user_id = qr.user_id
                        GROUP BY u.user_id, u.username, u.first_name, u.last_name, u.grade, u.first_seen_timestamp, u.last_active_timestamp
                    ),
                    weekly_performance AS (
                        SELECT 
                            COUNT(DISTINCT qr.user_id) as active_users_this_week,
                            COUNT(qr.result_id) as total_quizzes_this_week,
                            AVG(qr.score) as avg_score_this_week,
                            AVG(qr.percentage) as avg_percentage_this_week,
                            SUM(qr.total_questions) as total_questions_this_week
                        FROM quiz_results qr
                        WHERE qr.completed_at >= :week_start AND qr.completed_at <= :week_end
                    )
                    SELECT 
                        (SELECT COUNT(*) FROM users) as total_registered_users,
                        (SELECT COUNT(*) FROM user_stats WHERE total_quizzes > 0) as users_with_activity,
                        (SELECT active_users_this_week FROM weekly_performance) as active_users_this_week,
                        (SELECT total_quizzes_this_week FROM weekly_performance) as total_quizzes_this_week,
                        (SELECT avg_score_this_week FROM weekly_performance) as avg_score_this_week,
                        (SELECT avg_percentage_this_week FROM weekly_performance) as avg_percentage_this_week,
                        (SELECT total_questions_this_week FROM weekly_performance) as total_questions_this_week,
                        (SELECT AVG(avg_score) FROM user_stats WHERE total_quizzes > 0) as overall_avg_score,
                        (SELECT AVG(avg_percentage) FROM user_stats WHERE total_quizzes > 0) as overall_avg_percentage
                """)
                
                result = conn.execute(general_query, {
                    'week_start': week_start.isoformat(),
                    'week_end': week_end.isoformat()
                }).fetchone()
                
                stats = {
                    'period': f"{week_start.strftime('%Y-%m-%d')} إلى {week_end.strftime('%Y-%m-%d')}",
                    'total_registered_users': result[0] or 0,
                    'users_with_activity': result[1] or 0,
                    'active_users_this_week': result[2] or 0,
                    'total_quizzes_this_week': result[3] or 0,
                    'avg_score_this_week': round(result[4] or 0, 2),
                    'avg_percentage_this_week': round(result[5] or 0, 2),
                    'total_questions_this_week': result[6] or 0,
                    'overall_avg_score': round(result[7] or 0, 2),
                    'overall_avg_percentage': round(result[8] or 0, 2),
                    'engagement_rate': round((result[2] or 0) / max(result[0] or 1, 1) * 100, 2)
                }
                
                return stats
                
        except Exception as e:
            logger.error(f"خطأ في الحصول على الإحصائيات الشاملة: {e}")
            return {}
    
    def get_user_progress_analysis(self, week_start: datetime, week_end: datetime) -> List[Dict[str, Any]]:
        """تحليل تقدم المستخدمين مع اتجاهات الأداء"""
        try:
            with self.engine.connect() as conn:
                progress_query = text("""
                    WITH user_performance AS (
                        SELECT 
                            u.user_id,
                            u.username,
                            COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '') as full_name,
                            u.grade,
                            u.first_seen_timestamp,
                            u.last_active_timestamp,
                            COUNT(qr.result_id) as total_quizzes,
                            COUNT(CASE WHEN qr.completed_at >= :week_start AND qr.completed_at <= :week_end THEN 1 END) as weekly_quizzes,
                            AVG(qr.score) as overall_avg_score,
                            AVG(qr.percentage) as overall_avg_percentage,
                            AVG(CASE WHEN qr.completed_at >= :week_start AND qr.completed_at <= :week_end THEN qr.score END) as weekly_avg_score,
                            AVG(CASE WHEN qr.completed_at >= :week_start AND qr.completed_at <= :week_end THEN qr.percentage END) as weekly_avg_percentage,
                            MAX(qr.score) as best_score,
                            MIN(qr.score) as worst_score,
                            SUM(qr.total_questions) as total_questions_attempted,
                            AVG(qr.time_taken_seconds) as avg_time_taken,
                            STDDEV(qr.score) as score_consistency
                        FROM users u
                        LEFT JOIN quiz_results qr ON u.user_id = qr.user_id
                        GROUP BY u.user_id, u.username, u.first_name, u.last_name, u.grade, u.first_seen_timestamp, u.last_active_timestamp
                        HAVING COUNT(qr.result_id) > 0
                    ),
                    recent_performance AS (
                        SELECT 
                            user_id,
                            AVG(CASE WHEN completed_at >= :week_start - INTERVAL '7 days' AND completed_at < :week_start THEN score END) as prev_week_avg_score,
                            AVG(CASE WHEN completed_at >= :week_start - INTERVAL '14 days' AND completed_at < :week_start - INTERVAL '7 days' THEN score END) as two_weeks_ago_avg_score
                        FROM quiz_results
                        GROUP BY user_id
                    )
                    SELECT 
                        up.*,
                        rp.prev_week_avg_score,
                        rp.two_weeks_ago_avg_score,
                        CASE 
                            WHEN up.weekly_avg_score > rp.prev_week_avg_score THEN 'تحسن'
                            WHEN up.weekly_avg_score < rp.prev_week_avg_score THEN 'تراجع'
                            ELSE 'ثابت'
                        END as performance_trend,
                        CASE 
                            WHEN up.overall_avg_percentage >= 90 THEN 'ممتاز'
                            WHEN up.overall_avg_percentage >= 80 THEN 'جيد جداً'
                            WHEN up.overall_avg_percentage >= 70 THEN 'جيد'
                            WHEN up.overall_avg_percentage >= 60 THEN 'مقبول'
                            ELSE 'يحتاج تحسين'
                        END as performance_level,
                        CASE 
                            WHEN up.weekly_quizzes >= 5 THEN 'نشط جداً'
                            WHEN up.weekly_quizzes >= 3 THEN 'نشط'
                            WHEN up.weekly_quizzes >= 1 THEN 'نشط قليلاً'
                            ELSE 'غير نشط'
                        END as activity_level
                    FROM user_performance up
                    LEFT JOIN recent_performance rp ON up.user_id = rp.user_id
                    ORDER BY up.overall_avg_percentage DESC, up.total_quizzes DESC
                """)
                
                results = conn.execute(progress_query, {
                    'week_start': week_start.isoformat(),
                    'week_end': week_end.isoformat()
                }).fetchall()
                
                user_progress = []
                for row in results:
                    # حساب معدل التحسن
                    improvement_rate = 0
                    if row[17] and row[16]:  # prev_week_avg_score و weekly_avg_score
                        improvement_rate = round(((row[16] - row[17]) / row[17]) * 100, 2)
                    
                    # تحديد التوصيات
                    recommendations = self._generate_user_recommendations(
                        row[9], row[16], row[18], row[4], row[21]  # overall_avg_percentage, weekly_avg_score, performance_trend, total_quizzes, activity_level
                    )
                    
                    user_progress.append({
                        'user_id': row[0],
                        'username': row[1] or f"مستخدم_{row[0]}",
                        'full_name': row[2].strip() or row[1] or f"مستخدم_{row[0]}",
                        'grade': row[3] or 'غير محدد',
                        'registration_date': row[4],
                        'last_active': row[5],
                        'total_quizzes': row[6] or 0,
                        'weekly_quizzes': row[7] or 0,
                        'overall_avg_score': round(row[8] or 0, 2),
                        'overall_avg_percentage': round(row[9] or 0, 2),
                        'weekly_avg_score': round(row[10] or 0, 2),
                        'weekly_avg_percentage': round(row[11] or 0, 2),
                        'best_score': row[12] or 0,
                        'worst_score': row[13] or 0,
                        'total_questions': row[14] or 0,
                        'avg_time_taken': round(row[15] or 0, 2),
                        'score_consistency': round(row[16] or 0, 2),
                        'prev_week_avg_score': round(row[17] or 0, 2),
                        'performance_trend': row[19] or 'غير محدد',
                        'performance_level': row[20] or 'غير محدد',
                        'activity_level': row[21] or 'غير محدد',
                        'improvement_rate': improvement_rate,
                        'recommendations': recommendations
                    })
                
                return user_progress
                
        except Exception as e:
            logger.error(f"خطأ في تحليل تقدم المستخدمين: {e}")
            return []
    
    def _generate_user_recommendations(self, overall_avg: float, weekly_avg: float, 
                                     trend: str, total_quizzes: int, activity_level: str) -> List[str]:
        """إنشاء توصيات مخصصة لكل مستخدم"""
        recommendations = []
        
        # توصيات بناءً على الأداء العام
        if overall_avg >= 90:
            recommendations.append("🌟 أداء ممتاز! استمر في التفوق")
            recommendations.append("💡 يمكنك مساعدة زملائك في المواضيع الصعبة")
        elif overall_avg >= 80:
            recommendations.append("👍 أداء جيد جداً! بإمكانك الوصول للامتياز")
            recommendations.append("📚 ركز على المواضيع التي تحصل فيها على درجات أقل")
        elif overall_avg >= 70:
            recommendations.append("📈 أداء جيد، لكن يمكن التحسن")
            recommendations.append("⏰ خصص وقتاً أكثر للمراجعة")
        elif overall_avg >= 60:
            recommendations.append("⚠️ الأداء مقبول لكن يحتاج تحسين")
            recommendations.append("📖 راجع المواد الأساسية مرة أخرى")
        else:
            recommendations.append("🚨 يحتاج تركيز أكثر على الدراسة")
            recommendations.append("👨‍🏫 ننصح بطلب المساعدة من المعلم")
        
        # توصيات بناءً على الاتجاه
        if trend == 'تحسن':
            recommendations.append("📊 اتجاه إيجابي! استمر على هذا المنوال")
        elif trend == 'تراجع':
            recommendations.append("📉 هناك تراجع، راجع استراتيجية الدراسة")
        
        # توصيات بناءً على النشاط
        if activity_level == 'غير نشط':
            recommendations.append("🔄 زد من عدد الاختبارات الأسبوعية")
        elif activity_level == 'نشط جداً':
            recommendations.append("🎯 نشاط ممتاز! ركز على جودة الإجابات")
        
        # توصيات بناءً على عدد الاختبارات
        if total_quizzes < 5:
            recommendations.append("🆕 مستخدم جديد، ننصح بالتدرب أكثر")
        
        return recommendations[:4]  # أقصى 4 توصيات
    
    def get_grade_performance_analysis(self, week_start: datetime, week_end: datetime) -> List[Dict[str, Any]]:
        """تحليل أداء الصفوف الدراسية"""
        try:
            with self.engine.connect() as conn:
                grade_query = text("""
                    SELECT 
                        u.grade,
                        COUNT(DISTINCT u.user_id) as total_students,
                        COUNT(DISTINCT CASE WHEN qr.completed_at >= :week_start AND qr.completed_at <= :week_end THEN u.user_id END) as active_students_this_week,
                        COUNT(qr.result_id) as total_quizzes_all_time,
                        COUNT(CASE WHEN qr.completed_at >= :week_start AND qr.completed_at <= :week_end THEN 1 END) as quizzes_this_week,
                        AVG(qr.score) as avg_score_all_time,
                        AVG(qr.percentage) as avg_percentage_all_time,
                        AVG(CASE WHEN qr.completed_at >= :week_start AND qr.completed_at <= :week_end THEN qr.score END) as avg_score_this_week,
                        AVG(CASE WHEN qr.completed_at >= :week_start AND qr.completed_at <= :week_end THEN qr.percentage END) as avg_percentage_this_week,
                        MAX(qr.score) as highest_score,
                        MIN(qr.score) as lowest_score,
                        AVG(qr.time_taken_seconds) as avg_time_taken
                    FROM users u
                    LEFT JOIN quiz_results qr ON u.user_id = qr.user_id
                    WHERE u.grade IS NOT NULL AND u.grade != ''
                    GROUP BY u.grade
                    ORDER BY u.grade
                """)
                
                results = conn.execute(grade_query, {
                    'week_start': week_start.isoformat(),
                    'week_end': week_end.isoformat()
                }).fetchall()
                
                grade_analysis = []
                for row in results:
                    engagement_rate = round((row[2] or 0) / max(row[1] or 1, 1) * 100, 2)
                    
                    # تحديد مستوى الأداء
                    avg_percentage = row[6] or 0
                    if avg_percentage >= 85:
                        performance_level = "ممتاز"
                    elif avg_percentage >= 75:
                        performance_level = "جيد جداً"
                    elif avg_percentage >= 65:
                        performance_level = "جيد"
                    elif avg_percentage >= 55:
                        performance_level = "مقبول"
                    else:
                        performance_level = "يحتاج تحسين"
                    
                    grade_analysis.append({
                        'grade': row[0],
                        'total_students': row[1] or 0,
                        'active_students_this_week': row[2] or 0,
                        'engagement_rate': engagement_rate,
                        'total_quizzes_all_time': row[3] or 0,
                        'quizzes_this_week': row[4] or 0,
                        'avg_score_all_time': round(row[5] or 0, 2),
                        'avg_percentage_all_time': round(row[6] or 0, 2),
                        'avg_score_this_week': round(row[7] or 0, 2),
                        'avg_percentage_this_week': round(row[8] or 0, 2),
                        'highest_score': row[9] or 0,
                        'lowest_score': row[10] or 0,
                        'avg_time_taken_minutes': round((row[11] or 0) / 60, 2),
                        'performance_level': performance_level
                    })
                
                return grade_analysis
                
        except Exception as e:
            logger.error(f"خطأ في تحليل أداء الصفوف: {e}")
            return []
    
    def get_difficult_questions_analysis(self, week_start: datetime, week_end: datetime) -> List[Dict[str, Any]]:
        """تحليل الأسئلة الصعبة والمشاكل الشائعة"""
        try:
            with self.engine.connect() as conn:
                difficult_query = text("""
                    SELECT 
                        ua.question_id,
                        COUNT(ua.answer_id) as total_attempts,
                        COUNT(CASE WHEN ua.is_correct = true THEN 1 END) as correct_attempts,
                        COUNT(CASE WHEN ua.is_correct = false THEN 1 END) as wrong_attempts,
                        ROUND(COUNT(CASE WHEN ua.is_correct = false THEN 1 END) * 100.0 / COUNT(ua.answer_id), 2) as error_rate,
                        COUNT(DISTINCT ua.attempt_id) as unique_attempts,
                        AVG(EXTRACT(EPOCH FROM ua.answer_time)) as avg_answer_time_seconds
                    FROM user_answers ua
                    JOIN quiz_results qr ON ua.attempt_id = qr.result_id
                    WHERE qr.completed_at >= :week_start AND qr.completed_at <= :week_end
                    GROUP BY ua.question_id
                    HAVING COUNT(ua.answer_id) >= 3
                    ORDER BY error_rate DESC, total_attempts DESC
                    LIMIT 20
                """)
                
                results = conn.execute(difficult_query, {
                    'week_start': week_start.isoformat(),
                    'week_end': week_end.isoformat()
                }).fetchall()
                
                difficult_questions = []
                for row in results:
                    success_rate = round(100 - (row[4] or 0), 2)
                    
                    # تصنيف مستوى الصعوبة
                    error_rate = row[4] or 0
                    if error_rate >= 80:
                        difficulty_level = "صعب جداً"
                        priority = "عالية"
                    elif error_rate >= 60:
                        difficulty_level = "صعب"
                        priority = "متوسطة"
                    elif error_rate >= 40:
                        difficulty_level = "متوسط"
                        priority = "منخفضة"
                    else:
                        difficulty_level = "سهل"
                        priority = "منخفضة"
                    
                    difficult_questions.append({
                        'question_id': row[0],
                        'total_attempts': row[1] or 0,
                        'correct_attempts': row[2] or 0,
                        'wrong_attempts': row[3] or 0,
                        'error_rate': row[4] or 0,
                        'success_rate': success_rate,
                        'unique_attempts': row[5] or 0,
                        'avg_answer_time_seconds': round(row[6] or 0, 2),
                        'difficulty_level': difficulty_level,
                        'review_priority': priority
                    })
                
                return difficult_questions
                
        except Exception as e:
            logger.error(f"خطأ في تحليل الأسئلة الصعبة: {e}")
            return []
    
    def get_time_patterns_analysis(self, week_start: datetime, week_end: datetime) -> Dict[str, Any]:
        """تحليل أنماط الوقت والنشاط"""
        try:
            with self.engine.connect() as conn:
                # تحليل النشاط حسب اليوم
                daily_query = text("""
                    SELECT 
                        EXTRACT(DOW FROM qr.completed_at) as day_of_week,
                        COUNT(qr.result_id) as quiz_count,
                        COUNT(DISTINCT qr.user_id) as active_users,
                        AVG(qr.score) as avg_score,
                        AVG(qr.percentage) as avg_percentage
                    FROM quiz_results qr
                    WHERE qr.completed_at >= :week_start AND qr.completed_at <= :week_end
                    GROUP BY EXTRACT(DOW FROM qr.completed_at)
                    ORDER BY day_of_week
                """)
                
                # تحليل النشاط حسب الساعة
                hourly_query = text("""
                    SELECT 
                        EXTRACT(HOUR FROM qr.completed_at) as hour_of_day,
                        COUNT(qr.result_id) as quiz_count,
                        COUNT(DISTINCT qr.user_id) as active_users,
                        AVG(qr.score) as avg_score
                    FROM quiz_results qr
                    WHERE qr.completed_at >= :week_start AND qr.completed_at <= :week_end
                    GROUP BY EXTRACT(HOUR FROM qr.completed_at)
                    ORDER BY quiz_count DESC
                    LIMIT 10
                """)
                
                daily_results = conn.execute(daily_query, {
                    'week_start': week_start.isoformat(),
                    'week_end': week_end.isoformat()
                }).fetchall()
                
                hourly_results = conn.execute(hourly_query, {
                    'week_start': week_start.isoformat(),
                    'week_end': week_end.isoformat()
                }).fetchall()
                
                days_arabic = {
                    0: 'الأحد', 1: 'الاثنين', 2: 'الثلاثاء', 3: 'الأربعاء',
                    4: 'الخميس', 5: 'الجمعة', 6: 'السبت'
                }
                
                daily_activity = []
                for row in daily_results:
                    daily_activity.append({
                        'day': days_arabic.get(int(row[0]), f'يوم {row[0]}'),
                        'day_number': int(row[0]),
                        'quiz_count': row[1] or 0,
                        'active_users': row[2] or 0,
                        'avg_score': round(row[3] or 0, 2),
                        'avg_percentage': round(row[4] or 0, 2)
                    })
                
                peak_hours = []
                for row in hourly_results:
                    hour = int(row[0])
                    time_period = "صباحاً" if hour < 12 else "مساءً"
                    display_hour = hour if hour <= 12 else hour - 12
                    if display_hour == 0:
                        display_hour = 12
                    
                    peak_hours.append({
                        'hour': f"{display_hour:02d}:00 {time_period}",
                        'hour_24': f"{hour:02d}:00",
                        'quiz_count': row[1] or 0,
                        'active_users': row[2] or 0,
                        'avg_score': round(row[3] or 0, 2)
                    })
                
                return {
                    'daily_activity': daily_activity,
                    'peak_hours': peak_hours,
                    'insights': self._generate_time_insights(daily_activity, peak_hours)
                }
                
        except Exception as e:
            logger.error(f"خطأ في تحليل أنماط الوقت: {e}")
            return {'daily_activity': [], 'peak_hours': [], 'insights': []}
    
    def _generate_time_insights(self, daily_activity: List[Dict], peak_hours: List[Dict]) -> List[str]:
        """إنشاء رؤى حول أنماط الوقت"""
        insights = []
        
        if daily_activity:
            # أكثر الأيام نشاطاً
            most_active_day = max(daily_activity, key=lambda x: x['quiz_count'])
            insights.append(f"📅 أكثر الأيام نشاطاً: {most_active_day['day']} ({most_active_day['quiz_count']} اختبار)")
            
            # أقل الأيام نشاطاً
            least_active_day = min(daily_activity, key=lambda x: x['quiz_count'])
            if least_active_day['quiz_count'] > 0:
                insights.append(f"📉 أقل الأيام نشاطاً: {least_active_day['day']} ({least_active_day['quiz_count']} اختبار)")
        
        if peak_hours:
            # أكثر الساعات نشاطاً
            peak_hour = peak_hours[0]
            insights.append(f"⏰ ساعة الذروة: {peak_hour['hour']} ({peak_hour['quiz_count']} اختبار)")
            
            # توصيات بناءً على أوقات النشاط
            morning_activity = sum(1 for h in peak_hours if 'صباحاً' in h['hour'])
            evening_activity = sum(1 for h in peak_hours if 'مساءً' in h['hour'])
            
            if morning_activity > evening_activity:
                insights.append("🌅 المستخدمون أكثر نشاطاً في الصباح")
            else:
                insights.append("🌙 المستخدمون أكثر نشاطاً في المساء")
        
        return insights
    
    def create_performance_charts(self, user_progress: List[Dict], grade_analysis: List[Dict], 
                                time_patterns: Dict) -> Dict[str, str]:
        """إنشاء الرسوم البيانية للأداء"""
        chart_paths = {}
        
        try:
            # إعداد الخط العربي
            plt.style.use('default')
            
            # 1. رسم بياني لتوزيع مستويات الأداء
            if user_progress:
                fig, ax = plt.subplots(figsize=(10, 6))
                performance_levels = [user['performance_level'] for user in user_progress]
                level_counts = pd.Series(performance_levels).value_counts()
                
                colors = [self.colors['success'], self.colors['primary'], self.colors['info'], 
                         self.colors['warning'], self.colors['secondary']]
                
                bars = ax.bar(level_counts.index, level_counts.values, color=colors[:len(level_counts)])
                ax.set_title('توزيع مستويات الأداء', fontsize=16, fontweight='bold', pad=20)
                ax.set_xlabel('مستوى الأداء', fontsize=12)
                ax.set_ylabel('عدد المستخدمين', fontsize=12)
                
                # إضافة القيم على الأعمدة
                for bar in bars:
                    height = bar.get_height()
                    ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                           f'{int(height)}', ha='center', va='bottom', fontweight='bold')
                
                plt.xticks(rotation=45)
                plt.tight_layout()
                
                chart_path = os.path.join(self.charts_dir, 'performance_distribution.png')
                plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                chart_paths['performance_distribution'] = chart_path
                plt.close()
            
            # 2. رسم بياني لأداء الصفوف
            if grade_analysis:
                fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
                
                grades = [grade['grade'] for grade in grade_analysis]
                avg_percentages = [grade['avg_percentage_all_time'] for grade in grade_analysis]
                engagement_rates = [grade['engagement_rate'] for grade in grade_analysis]
                
                # متوسط الدرجات
                bars1 = ax1.bar(grades, avg_percentages, color=self.colors['primary'])
                ax1.set_title('متوسط الدرجات حسب الصف', fontsize=14, fontweight='bold')
                ax1.set_xlabel('الصف الدراسي', fontsize=12)
                ax1.set_ylabel('متوسط النسبة المئوية', fontsize=12)
                ax1.set_ylim(0, 100)
                
                for bar in bars1:
                    height = bar.get_height()
                    ax1.text(bar.get_x() + bar.get_width()/2., height + 1,
                           f'{height:.1f}%', ha='center', va='bottom', fontweight='bold')
                
                # معدل المشاركة
                bars2 = ax2.bar(grades, engagement_rates, color=self.colors['success'])
                ax2.set_title('معدل المشاركة حسب الصف', fontsize=14, fontweight='bold')
                ax2.set_xlabel('الصف الدراسي', fontsize=12)
                ax2.set_ylabel('معدل المشاركة (%)', fontsize=12)
                ax2.set_ylim(0, 100)
                
                for bar in bars2:
                    height = bar.get_height()
                    ax2.text(bar.get_x() + bar.get_width()/2., height + 1,
                           f'{height:.1f}%', ha='center', va='bottom', fontweight='bold')
                
                plt.tight_layout()
                
                chart_path = os.path.join(self.charts_dir, 'grade_performance.png')
                plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                chart_paths['grade_performance'] = chart_path
                plt.close()
            
            # 3. رسم بياني للنشاط اليومي
            if time_patterns.get('daily_activity'):
                fig, ax = plt.subplots(figsize=(12, 6))
                
                daily_data = time_patterns['daily_activity']
                days = [day['day'] for day in daily_data]
                quiz_counts = [day['quiz_count'] for day in daily_data]
                
                bars = ax.bar(days, quiz_counts, color=self.colors['info'])
                ax.set_title('النشاط اليومي خلال الأسبوع', fontsize=16, fontweight='bold', pad=20)
                ax.set_xlabel('اليوم', fontsize=12)
                ax.set_ylabel('عدد الاختبارات', fontsize=12)
                
                for bar in bars:
                    height = bar.get_height()
                    ax.text(bar.get_x() + bar.get_width()/2., height + 0.5,
                           f'{int(height)}', ha='center', va='bottom', fontweight='bold')
                
                plt.xticks(rotation=45)
                plt.tight_layout()
                
                chart_path = os.path.join(self.charts_dir, 'daily_activity.png')
                plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                chart_paths['daily_activity'] = chart_path
                plt.close()
            
            logger.info(f"تم إنشاء {len(chart_paths)} رسم بياني")
            return chart_paths
            
        except Exception as e:
            logger.error(f"خطأ في إنشاء الرسوم البيانية: {e}")
            return {}
    
    def generate_smart_recommendations(self, general_stats: Dict, user_progress: List[Dict], 
                                     grade_analysis: List[Dict], difficult_questions: List[Dict],
                                     time_patterns: Dict) -> Dict[str, List[str]]:
        """إنشاء توصيات ذكية شاملة"""
        recommendations = {
            'للإدارة': [],
            'للمعلمين': [],
            'للمحتوى': [],
            'للنظام': []
        }
        
        try:
            # توصيات للإدارة
            engagement_rate = general_stats.get('engagement_rate', 0)
            if engagement_rate < 30:
                recommendations['للإدارة'].append("📢 معدل المشاركة منخفض - ننصح بحملة تحفيزية")
            elif engagement_rate > 70:
                recommendations['للإدارة'].append("🎉 معدل مشاركة ممتاز - استمروا في التحفيز")
            
            # تحليل المستخدمين المحتاجين للمساعدة
            struggling_users = [u for u in user_progress if u['performance_level'] == 'يحتاج تحسين']
            if len(struggling_users) > len(user_progress) * 0.3:
                recommendations['للإدارة'].append(f"⚠️ {len(struggling_users)} مستخدم يحتاج مساعدة إضافية")
            
            # توصيات للمعلمين
            if difficult_questions:
                high_error_questions = [q for q in difficult_questions if q['error_rate'] > 70]
                if high_error_questions:
                    recommendations['للمعلمين'].append(f"📚 {len(high_error_questions)} سؤال يحتاج شرح إضافي")
            
            # تحليل الصفوف الضعيفة
            if grade_analysis:
                weak_grades = [g for g in grade_analysis if g['avg_percentage_all_time'] < 60]
                if weak_grades:
                    grade_names = ', '.join([g['grade'] for g in weak_grades])
                    recommendations['للمعلمين'].append(f"🎯 الصفوف التالية تحتاج تركيز: {grade_names}")
            
            # توصيات للمحتوى
            if difficult_questions:
                very_difficult = [q for q in difficult_questions if q['error_rate'] > 80]
                if very_difficult:
                    recommendations['للمحتوى'].append(f"🔄 مراجعة {len(very_difficult)} سؤال صعب جداً")
                
                medium_difficult = [q for q in difficult_questions if 60 <= q['error_rate'] <= 80]
                if medium_difficult:
                    recommendations['للمحتوى'].append(f"💡 إضافة شرح لـ {len(medium_difficult)} سؤال متوسط الصعوبة")
            
            # توصيات للنظام
            if time_patterns.get('peak_hours'):
                peak_hour = time_patterns['peak_hours'][0]
                recommendations['للنظام'].append(f"⏰ ساعة الذروة {peak_hour['hour']} - تأكد من استقرار الخادم")
            
            # تحليل أنماط النشاط
            if time_patterns.get('daily_activity'):
                daily_data = time_patterns['daily_activity']
                weekend_activity = sum(day['quiz_count'] for day in daily_data if day['day'] in ['الجمعة', 'السبت'])
                weekday_activity = sum(day['quiz_count'] for day in daily_data if day['day'] not in ['الجمعة', 'السبت'])
                
                if weekend_activity > weekday_activity * 0.5:
                    recommendations['للنظام'].append("📱 نشاط عالي في عطلة نهاية الأسبوع - فرصة للمحتوى الإضافي")
            
            # إضافة توصيات عامة إذا كانت القوائم فارغة
            for category in recommendations:
                if not recommendations[category]:
                    recommendations[category].append("✅ الأداء جيد في هذا المجال")
            
            return recommendations
            
        except Exception as e:
            logger.error(f"خطأ في إنشاء التوصيات الذكية: {e}")
            return recommendations
    
    def create_ultimate_excel_report(self, week_start: datetime, week_end: datetime) -> str:
        """إنشاء التقرير النهائي المتكامل"""
        try:
            logger.info("بدء إنشاء التقرير المتكامل...")
            
            # جمع جميع البيانات
            general_stats = self.get_comprehensive_stats(week_start, week_end)
            user_progress = self.get_user_progress_analysis(week_start, week_end)
            grade_analysis = self.get_grade_performance_analysis(week_start, week_end)
            difficult_questions = self.get_difficult_questions_analysis(week_start, week_end)
            time_patterns = self.get_time_patterns_analysis(week_start, week_end)
            
            # إنشاء الرسوم البيانية
            chart_paths = self.create_performance_charts(user_progress, grade_analysis, time_patterns)
            
            # إنشاء التوصيات الذكية
            smart_recommendations = self.generate_smart_recommendations(
                general_stats, user_progress, grade_analysis, difficult_questions, time_patterns
            )
            
            # إنشاء اسم الملف
            week_str = week_start.strftime("%Y-%m-%d")
            filename = f"ultimate_weekly_report_{week_str}.xlsx"
            filepath = os.path.join(self.reports_dir, filename)
            
            # إنشاء ملف Excel
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                
                # الورقة 1: الملخص التنفيذي
                executive_summary = self._create_executive_summary(general_stats, user_progress, smart_recommendations)
                exec_df = pd.DataFrame(executive_summary)
                exec_df.to_excel(writer, sheet_name='الملخص التنفيذي', index=False)
                
                # الورقة 2: الإحصائيات العامة المتقدمة
                general_df = pd.DataFrame([general_stats])
                general_df.to_excel(writer, sheet_name='الإحصائيات العامة', index=False)
                
                # الورقة 3: تحليل تقدم المستخدمين
                if user_progress:
                    users_df = pd.DataFrame(user_progress)
                    users_df.to_excel(writer, sheet_name='تحليل تقدم المستخدمين', index=False)
                
                # الورقة 4: أداء الصفوف الدراسية
                if grade_analysis:
                    grades_df = pd.DataFrame(grade_analysis)
                    grades_df.to_excel(writer, sheet_name='أداء الصفوف', index=False)
                
                # الورقة 5: الأسئلة الصعبة والمشاكل
                if difficult_questions:
                    questions_df = pd.DataFrame(difficult_questions)
                    questions_df.to_excel(writer, sheet_name='الأسئلة الصعبة', index=False)
                
                # الورقة 6: تحليل أنماط الوقت
                if time_patterns.get('daily_activity'):
                    daily_df = pd.DataFrame(time_patterns['daily_activity'])
                    daily_df.to_excel(writer, sheet_name='النشاط اليومي', index=False)
                
                if time_patterns.get('peak_hours'):
                    hourly_df = pd.DataFrame(time_patterns['peak_hours'])
                    hourly_df.to_excel(writer, sheet_name='ساعات الذروة', index=False)
                
                # الورقة 7: التوصيات الذكية
                recommendations_data = []
                for category, recs in smart_recommendations.items():
                    for rec in recs:
                        recommendations_data.append({'الفئة': category, 'التوصية': rec})
                
                if recommendations_data:
                    rec_df = pd.DataFrame(recommendations_data)
                    rec_df.to_excel(writer, sheet_name='التوصيات الذكية', index=False)
            
            logger.info(f"تم إنشاء التقرير المتكامل بنجاح: {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"خطأ في إنشاء التقرير المتكامل: {e}")
            return None
    
    def _create_executive_summary(self, general_stats: Dict, user_progress: List[Dict], 
                                recommendations: Dict) -> List[Dict]:
        """إنشاء الملخص التنفيذي"""
        summary = []
        
        # الإحصائيات الرئيسية
        summary.append({
            'المؤشر': 'إجمالي المستخدمين المسجلين',
            'القيمة': general_stats.get('total_registered_users', 0),
            'الوصف': 'العدد الكلي للمستخدمين في النظام'
        })
        
        summary.append({
            'المؤشر': 'المستخدمين النشطين هذا الأسبوع',
            'القيمة': general_stats.get('active_users_this_week', 0),
            'الوصف': 'عدد المستخدمين الذين أجروا اختبارات'
        })
        
        summary.append({
            'المؤشر': 'معدل المشاركة',
            'القيمة': f"{general_stats.get('engagement_rate', 0)}%",
            'الوصف': 'نسبة المستخدمين النشطين من إجمالي المسجلين'
        })
        
        summary.append({
            'المؤشر': 'متوسط الدرجات هذا الأسبوع',
            'القيمة': f"{general_stats.get('avg_percentage_this_week', 0)}%",
            'الوصف': 'متوسط النسبة المئوية للاختبارات'
        })
        
        # تحليل الأداء
        if user_progress:
            excellent_users = len([u for u in user_progress if u['performance_level'] == 'ممتاز'])
            struggling_users = len([u for u in user_progress if u['performance_level'] == 'يحتاج تحسين'])
            
            summary.append({
                'المؤشر': 'المستخدمين المتفوقين',
                'القيمة': excellent_users,
                'الوصف': 'عدد المستخدمين بمستوى ممتاز'
            })
            
            summary.append({
                'المؤشر': 'المستخدمين المحتاجين للمساعدة',
                'القيمة': struggling_users,
                'الوصف': 'عدد المستخدمين الذين يحتاجون تحسين'
            })
        
        # أهم التوصيات
        summary.append({
            'المؤشر': 'أولوية التوصيات',
            'القيمة': 'للإدارة',
            'الوصف': recommendations.get('للإدارة', ['لا توجد توصيات'])[0]
        })
        
        return summary
    
    def send_ultimate_report_email(self, report_path: str, chart_paths: Dict[str, str], 
                                 week_start: datetime, week_end: datetime) -> bool:
        """إرسال التقرير المتكامل بالإيميل"""
        try:
            from handlers.admin_tools.email_notification import send_email_notification
            
            # إعداد محتوى الإيميل
            subject = f"📊 التقرير الأسبوعي المتكامل والذكي - {week_start.strftime('%Y-%m-%d')} إلى {week_end.strftime('%Y-%m-%d')}"
            
            body = f"""
            السلام عليكم ورحمة الله وبركاته
            
            🎯 نرسل لكم التقرير الأسبوعي المتكامل والذكي لأداء البوت التعليمي
            
            📅 فترة التقرير: {week_start.strftime('%Y-%m-%d')} إلى {week_end.strftime('%Y-%m-%d')}
            
            📊 محتويات التقرير:
            ✅ الملخص التنفيذي مع المؤشرات الرئيسية
            📈 تحليل تقدم المستخدمين مع اتجاهات الأداء
            🎓 أداء الصفوف الدراسية المختلفة
            ❓ تحليل الأسئلة الصعبة والمشاكل الشائعة
            ⏰ أنماط النشاط والأوقات المثلى
            💡 توصيات ذكية مخصصة لكل فئة
            📊 رسوم بيانية تفاعلية ملونة
            
            🎯 المميزات الجديدة:
            • تحليل اتجاهات الأداء (تحسن/تراجع/ثابت)
            • توصيات مخصصة لكل مستخدم
            • تصنيف مستويات الصعوبة للأسئلة
            • تحليل أنماط الوقت والنشاط
            • اقتراحات عملية للتحسين
            
            📧 هذا التقرير تم إنشاؤه تلقائياً بواسطة النظام الذكي
            
            مع أطيب التحيات
            🤖 فريق البوت التعليمي الذكي
            """
            
            # الحصول على إيميل المدير
            admin_email = os.getenv('ADMIN_EMAIL', 'admin@example.com')
            
            # إرسال الإيميل مع المرفقات
            success = send_email_notification(
                to_email=admin_email,
                subject=subject,
                body=body,
                attachment_path=report_path
            )
            
            if success:
                logger.info(f"تم إرسال التقرير المتكامل بنجاح إلى {admin_email}")
                return True
            else:
                logger.error("فشل في إرسال التقرير المتكامل")
                return False
                
        except Exception as e:
            logger.error(f"خطأ في إرسال التقرير المتكامل: {e}")
            return False
    
    def generate_and_send_ultimate_report(self) -> bool:
        """إنشاء وإرسال التقرير المتكامل"""
        try:
            # تحديد فترة الأسبوع الماضي
            today = datetime.now()
            week_start = today - timedelta(days=today.weekday() + 7)
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
            week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
            
            logger.info(f"إنشاء التقرير المتكامل للفترة: {week_start} - {week_end}")
            
            # إنشاء التقرير
            report_path = self.create_ultimate_excel_report(week_start, week_end)
            
            if not report_path:
                logger.error("فشل في إنشاء التقرير المتكامل")
                return False
            
            # إنشاء الرسوم البيانية
            user_progress = self.get_user_progress_analysis(week_start, week_end)
            grade_analysis = self.get_grade_performance_analysis(week_start, week_end)
            time_patterns = self.get_time_patterns_analysis(week_start, week_end)
            chart_paths = self.create_performance_charts(user_progress, grade_analysis, time_patterns)
            
            # إرسال التقرير
            success = self.send_ultimate_report_email(report_path, chart_paths, week_start, week_end)
            
            if success:
                logger.info("تم إنشاء وإرسال التقرير المتكامل بنجاح")
                return True
            else:
                logger.error("فشل في إرسال التقرير المتكامل")
                return False
                
        except Exception as e:
            logger.error(f"خطأ في إنشاء وإرسال التقرير المتكامل: {e}")
            return False


class UltimateWeeklyReportScheduler:
    """جدولة التقارير الأسبوعية المتكاملة"""
    
    def __init__(self, report_generator: UltimateWeeklyReportGenerator):
        self.report_generator = report_generator
        self.is_running = False
        self.scheduler_thread = None
        
    def start_scheduler(self):
        """بدء جدولة التقارير الأسبوعية المتكاملة"""
        try:
            # جدولة التقرير كل يوم أحد الساعة 9:00 صباحاً
            schedule.every().sunday.at("09:00").do(self._generate_weekly_report)
            
            self.is_running = True
            self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
            self.scheduler_thread.start()
            
            logger.info("تم بدء جدولة التقارير الأسبوعية المتكاملة - كل يوم أحد الساعة 9:00 صباحاً")
            
        except Exception as e:
            logger.error(f"خطأ في بدء جدولة التقارير المتكاملة: {e}")
    
    def _generate_weekly_report(self):
        """إنشاء التقرير الأسبوعي المجدول"""
        try:
            logger.info("بدء إنشاء التقرير الأسبوعي المجدول المتكامل")
            success = self.report_generator.generate_and_send_ultimate_report()
            
            if success:
                logger.info("تم إنشاء وإرسال التقرير الأسبوعي المجدول المتكامل بنجاح")
            else:
                logger.error("فشل في إنشاء التقرير الأسبوعي المجدول المتكامل")
                
        except Exception as e:
            logger.error(f"خطأ في التقرير الأسبوعي المجدول المتكامل: {e}")
    
    def stop_scheduler(self):
        """إيقاف جدولة التقارير"""
        self.is_running = False
        schedule.clear()
        logger.info("تم إيقاف جدولة التقارير الأسبوعية المتكاملة")
    
    def _run_scheduler(self):
        """تشغيل الجدولة في خيط منفصل"""
        while self.is_running:
            schedule.run_pending()
            time.sleep(60)


def is_ultimate_email_configured() -> bool:
    """التحقق من إعدادات الإيميل المتكاملة"""
    try:
        required_vars = ['EMAIL_USERNAME', 'EMAIL_PASSWORD', 'ADMIN_EMAIL']
        return all(os.getenv(var) for var in required_vars)
    except:
        return False


# مثال على الاستخدام
if __name__ == "__main__":
    # إنشاء مولد التقارير المتكامل
    report_generator = UltimateWeeklyReportGenerator()
    
    # إنشاء جدولة التقارير
    scheduler = UltimateWeeklyReportScheduler(report_generator)
    
    # بدء الجدولة
    scheduler.start_scheduler()
    
    # إنشاء تقرير فوري للاختبار
    # report_generator.generate_and_send_ultimate_report()
    
    logger.info("نظام التقارير الأسبوعية المتكامل والذكي يعمل...")

