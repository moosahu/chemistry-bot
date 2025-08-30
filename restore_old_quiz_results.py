#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
سكريبت لاستعادة نتائج الاختبارات القديمة
يعيد حساب النتائج من تفاصيل الإجابات المحفوظة
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

# إعداد التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class QuizResultsRestorer:
    """فئة لاستعادة نتائج الاختبارات القديمة"""
    
    def __init__(self, db_manager):
        """تهيئة المستعيد"""
        self.db_manager = db_manager
        logger.info("تم تهيئة مستعيد النتائج القديمة")
    
    def analyze_old_results(self) -> Dict[str, Any]:
        """تحليل النتائج القديمة لمعرفة ما يمكن استعادته"""
        try:
            # فحص النتائج القديمة
            query = """
                SELECT 
                    result_id,
                    user_id,
                    quiz_type,
                    total_questions,
                    score,
                    percentage,
                    answers_details,
                    completed_at,
                    CASE 
                        WHEN answers_details IS NOT NULL AND answers_details != 'null' 
                        THEN 'recoverable'
                        ELSE 'not_recoverable'
                    END as recovery_status
                FROM quiz_results 
                WHERE percentage = 0 OR score = 0
                ORDER BY completed_at DESC
            """
            
            results = self.db_manager._execute_query(query, fetch_all=True)
            
            if not results:
                return {
                    'total_zero_results': 0,
                    'recoverable': 0,
                    'not_recoverable': 0,
                    'sample_data': []
                }
            
            recoverable = [r for r in results if r['recovery_status'] == 'recoverable']
            not_recoverable = [r for r in results if r['recovery_status'] == 'not_recoverable']
            
            # عينة من البيانات القابلة للاستعادة
            sample_data = []
            for result in recoverable[:3]:  # أول 3 نتائج
                try:
                    answers_details = json.loads(result['answers_details']) if result['answers_details'] else []
                    sample_data.append({
                        'result_id': result['result_id'],
                        'user_id': result['user_id'],
                        'total_questions': result['total_questions'],
                        'answers_count': len(answers_details),
                        'has_correct_answers': any(ans.get('is_correct', False) for ans in answers_details),
                        'completed_at': result['completed_at']
                    })
                except Exception as e:
                    logger.warning(f"خطأ في تحليل النتيجة {result['result_id']}: {e}")
            
            return {
                'total_zero_results': len(results),
                'recoverable': len(recoverable),
                'not_recoverable': len(not_recoverable),
                'sample_data': sample_data
            }
            
        except Exception as e:
            logger.error(f"خطأ في تحليل النتائج القديمة: {e}")
            return {}
    
    def restore_single_result(self, result_id: int) -> bool:
        """استعادة نتيجة واحدة"""
        try:
            # الحصول على تفاصيل النتيجة
            query = """
                SELECT result_id, total_questions, answers_details
                FROM quiz_results 
                WHERE result_id = %s
            """
            
            result = self.db_manager._execute_query(query, (result_id,), fetch_one=True)
            
            if not result or not result['answers_details']:
                logger.warning(f"لا توجد تفاصيل إجابات للنتيجة {result_id}")
                return False
            
            # تحليل تفاصيل الإجابات
            try:
                answers_details = json.loads(result['answers_details'])
            except json.JSONDecodeError:
                logger.error(f"خطأ في تحليل JSON للنتيجة {result_id}")
                return False
            
            # حساب النتيجة الصحيحة
            correct_answers = 0
            total_answered = 0
            
            for answer in answers_details:
                if answer.get('status') == 'answered':
                    total_answered += 1
                    if answer.get('is_correct', False):
                        correct_answers += 1
            
            # حساب النسبة المئوية
            if total_answered > 0:
                percentage = (correct_answers / total_answered) * 100
            else:
                percentage = 0
            
            # تحديث النتيجة في قاعدة البيانات
            update_query = """
                UPDATE quiz_results 
                SET score = %s, percentage = %s
                WHERE result_id = %s
            """
            
            success = self.db_manager._execute_query(
                update_query, 
                (correct_answers, round(percentage, 2), result_id), 
                commit=True
            )
            
            if success:
                logger.info(f"تم استعادة النتيجة {result_id}: {correct_answers}/{total_answered} ({percentage:.2f}%)")
                return True
            else:
                logger.error(f"فشل في تحديث النتيجة {result_id}")
                return False
                
        except Exception as e:
            logger.error(f"خطأ في استعادة النتيجة {result_id}: {e}")
            return False
    
    def restore_all_recoverable_results(self) -> Dict[str, int]:
        """استعادة جميع النتائج القابلة للاستعادة"""
        try:
            # الحصول على جميع النتائج القابلة للاستعادة
            query = """
                SELECT result_id
                FROM quiz_results 
                WHERE (percentage = 0 OR score = 0)
                AND answers_details IS NOT NULL 
                AND answers_details != 'null'
                ORDER BY completed_at DESC
            """
            
            results = self.db_manager._execute_query(query, fetch_all=True)
            
            if not results:
                logger.info("لا توجد نتائج قابلة للاستعادة")
                return {'total': 0, 'restored': 0, 'failed': 0}
            
            total = len(results)
            restored = 0
            failed = 0
            
            logger.info(f"بدء استعادة {total} نتيجة...")
            
            for i, result in enumerate(results, 1):
                result_id = result['result_id']
                
                if self.restore_single_result(result_id):
                    restored += 1
                else:
                    failed += 1
                
                # تقرير التقدم كل 10 نتائج
                if i % 10 == 0:
                    logger.info(f"تم معالجة {i}/{total} نتيجة...")
            
            logger.info(f"انتهت الاستعادة: {restored} نجحت، {failed} فشلت من أصل {total}")
            
            return {
                'total': total,
                'restored': restored,
                'failed': failed
            }
            
        except Exception as e:
            logger.error(f"خطأ في استعادة النتائج: {e}")
            return {'total': 0, 'restored': 0, 'failed': 0}
    
    def create_backup_before_restore(self) -> bool:
        """إنشاء نسخة احتياطية قبل الاستعادة"""
        try:
            backup_query = """
                CREATE TABLE IF NOT EXISTS quiz_results_backup_before_restore AS 
                SELECT * FROM quiz_results 
                WHERE percentage = 0 OR score = 0
            """
            
            success = self.db_manager._execute_query(backup_query, commit=True)
            
            if success:
                logger.info("تم إنشاء نسخة احتياطية: quiz_results_backup_before_restore")
                return True
            else:
                logger.error("فشل في إنشاء النسخة الاحتياطية")
                return False
                
        except Exception as e:
            logger.error(f"خطأ في إنشاء النسخة الاحتياطية: {e}")
            return False


def main():
    """الدالة الرئيسية للاختبار"""
    print("🔧 سكريبت استعادة نتائج الاختبارات القديمة")
    print("هذا السكريبت يحتاج لتشغيله من داخل بيئة البوت مع الوصول لقاعدة البيانات")
    print("\nلاستخدام السكريبت:")
    print("1. استورد DatabaseManager من مشروعك")
    print("2. أنشئ instance من QuizResultsRestorer")
    print("3. استخدم analyze_old_results() لفحص البيانات")
    print("4. استخدم restore_all_recoverable_results() للاستعادة")


if __name__ == "__main__":
    main()

