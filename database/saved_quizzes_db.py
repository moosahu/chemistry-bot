"""
إدارة الاختبارات المحفوظة في قاعدة البيانات
Saved Quizzes Database Management
"""

import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from sqlalchemy import Column, Integer, String, Text, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL, logger

Base = declarative_base()


class SavedQuiz(Base):
    """نموذج جدول الاختبارات المحفوظة"""
    __tablename__ = 'saved_quizzes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    quiz_id = Column(String(255), nullable=False, unique=True, index=True)
    quiz_name = Column(String(500), nullable=False)
    quiz_type = Column(String(100), nullable=False)
    quiz_scope_id = Column(String(255), nullable=False)
    questions_data = Column(Text, nullable=False)  # JSON string
    current_question_index = Column(Integer, nullable=False, default=0)
    score = Column(Integer, nullable=False, default=0)
    answers = Column(Text, nullable=False)  # JSON string
    total_questions = Column(Integer, nullable=False)
    quiz_start_time = Column(String(255), nullable=True)  # ISO format string
    db_quiz_session_id = Column(String(255), nullable=True)
    saved_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<SavedQuiz(id={self.id}, user_id={self.user_id}, quiz_name='{self.quiz_name}', progress={self.current_question_index}/{self.total_questions})>"


def get_db_session():
    """إنشاء جلسة قاعدة بيانات"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return Session()


def create_saved_quizzes_table():
    """إنشاء جدول الاختبارات المحفوظة إذا لم يكن موجوداً"""
    try:
        engine = create_engine(DATABASE_URL)
        Base.metadata.create_all(engine, tables=[SavedQuiz.__table__])
        logger.info("[SavedQuizzes DB] جدول saved_quizzes تم إنشاؤه أو التحقق من وجوده بنجاح")
        return True
    except Exception as e:
        logger.error(f"[SavedQuizzes DB] خطأ في إنشاء جدول saved_quizzes: {e}", exc_info=True)
        return False


def save_quiz_to_db(user_id: int, quiz_data: Dict) -> bool:
    """
    حفظ اختبار في قاعدة البيانات
    
    Args:
        user_id: معرف المستخدم
        quiz_data: بيانات الاختبار (نفس الهيكل المستخدم في context.user_data)
    
    Returns:
        True إذا تم الحفظ بنجاح، False خلاف ذلك
    """
    try:
        session = get_db_session()
        
        # التحقق من وجود اختبار بنفس quiz_id
        existing_quiz = session.query(SavedQuiz).filter_by(quiz_id=quiz_data["quiz_id"]).first()
        
        if existing_quiz:
            # تحديث الاختبار الموجود
            existing_quiz.current_question_index = quiz_data["current_question_index"]
            existing_quiz.score = quiz_data["score"]
            existing_quiz.answers = json.dumps(quiz_data["answers"], ensure_ascii=False)
            existing_quiz.saved_at = datetime.now(timezone.utc)
            logger.info(f"[SavedQuizzes DB] تحديث اختبار محفوظ: quiz_id={quiz_data['quiz_id']}, user={user_id}")
        else:
            # إنشاء اختبار جديد
            new_quiz = SavedQuiz(
                user_id=user_id,
                quiz_id=quiz_data["quiz_id"],
                quiz_name=quiz_data["quiz_name"],
                quiz_type=quiz_data["quiz_type"],
                quiz_scope_id=quiz_data["quiz_scope_id"],
                questions_data=json.dumps(quiz_data["questions_data"], ensure_ascii=False),
                current_question_index=quiz_data["current_question_index"],
                score=quiz_data["score"],
                answers=json.dumps(quiz_data["answers"], ensure_ascii=False),
                total_questions=quiz_data["total_questions"],
                quiz_start_time=quiz_data.get("quiz_start_time"),
                db_quiz_session_id=quiz_data.get("db_quiz_session_id"),
                saved_at=datetime.now(timezone.utc)
            )
            session.add(new_quiz)
            logger.info(f"[SavedQuizzes DB] حفظ اختبار جديد: quiz_id={quiz_data['quiz_id']}, user={user_id}")
        
        session.commit()
        session.close()
        return True
        
    except Exception as e:
        logger.error(f"[SavedQuizzes DB] خطأ في حفظ الاختبار: {e}", exc_info=True)
        try:
            session.rollback()
            session.close()
        except:
            pass
        return False


def get_saved_quizzes_for_user(user_id: int) -> Dict[str, Dict]:
    """
    استرجاع جميع الاختبارات المحفوظة لمستخدم معين
    
    Args:
        user_id: معرف المستخدم
    
    Returns:
        قاموس بنفس هيكل context.user_data["saved_quizzes"]
        {quiz_id: {quiz_data}}
    """
    try:
        session = get_db_session()
        
        saved_quizzes = session.query(SavedQuiz).filter_by(user_id=user_id).all()
        
        result = {}
        for quiz in saved_quizzes:
            result[quiz.quiz_id] = {
                "quiz_id": quiz.quiz_id,
                "quiz_name": quiz.quiz_name,
                "quiz_type": quiz.quiz_type,
                "quiz_scope_id": quiz.quiz_scope_id,
                "questions_data": json.loads(quiz.questions_data),
                "current_question_index": quiz.current_question_index,
                "score": quiz.score,
                "answers": json.loads(quiz.answers),
                "total_questions": quiz.total_questions,
                "quiz_start_time": quiz.quiz_start_time,
                "db_quiz_session_id": quiz.db_quiz_session_id,
                "saved_at": quiz.saved_at.isoformat() if quiz.saved_at else None
            }
        
        session.close()
        logger.info(f"[SavedQuizzes DB] تم استرجاع {len(result)} اختبار محفوظ للمستخدم {user_id}")
        return result
        
    except Exception as e:
        logger.error(f"[SavedQuizzes DB] خطأ في استرجاع الاختبارات المحفوظة: {e}", exc_info=True)
        try:
            session.close()
        except:
            pass
        return {}


def delete_saved_quiz(quiz_id: str) -> bool:
    """
    حذف اختبار محفوظ من قاعدة البيانات
    
    Args:
        quiz_id: معرف الاختبار
    
    Returns:
        True إذا تم الحذف بنجاح، False خلاف ذلك
    """
    try:
        session = get_db_session()
        
        quiz = session.query(SavedQuiz).filter_by(quiz_id=quiz_id).first()
        
        if quiz:
            session.delete(quiz)
            session.commit()
            logger.info(f"[SavedQuizzes DB] تم حذف الاختبار المحفوظ: quiz_id={quiz_id}")
            session.close()
            return True
        else:
            logger.warning(f"[SavedQuizzes DB] لم يتم العثور على الاختبار للحذف: quiz_id={quiz_id}")
            session.close()
            return False
        
    except Exception as e:
        logger.error(f"[SavedQuizzes DB] خطأ في حذف الاختبار المحفوظ: {e}", exc_info=True)
        try:
            session.rollback()
            session.close()
        except:
            pass
        return False


def get_saved_quiz_count_for_user(user_id: int) -> int:
    """
    الحصول على عدد الاختبارات المحفوظة لمستخدم معين
    
    Args:
        user_id: معرف المستخدم
    
    Returns:
        عدد الاختبارات المحفوظة
    """
    try:
        session = get_db_session()
        count = session.query(SavedQuiz).filter_by(user_id=user_id).count()
        session.close()
        return count
    except Exception as e:
        logger.error(f"[SavedQuizzes DB] خطأ في حساب الاختبارات المحفوظة: {e}", exc_info=True)
        try:
            session.close()
        except:
            pass
        return 0


def delete_old_saved_quizzes(days: int = 30) -> int:
    """
    حذف الاختبارات المحفوظة القديمة (تنظيف تلقائي)
    
    Args:
        days: عدد الأيام (الاختبارات الأقدم من هذا العدد سيتم حذفها)
    
    Returns:
        عدد الاختبارات المحذوفة
    """
    try:
        session = get_db_session()
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        old_quizzes = session.query(SavedQuiz).filter(SavedQuiz.saved_at < cutoff_date).all()
        count = len(old_quizzes)
        
        for quiz in old_quizzes:
            session.delete(quiz)
        
        session.commit()
        session.close()
        
        if count > 0:
            logger.info(f"[SavedQuizzes DB] تم حذف {count} اختبار محفوظ قديم (أقدم من {days} يوم)")
        
        return count
        
    except Exception as e:
        logger.error(f"[SavedQuizzes DB] خطأ في حذف الاختبارات القديمة: {e}", exc_info=True)
        try:
            session.rollback()
            session.close()
        except:
            pass
        return 0
