#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import psycopg2
import json
import random
import logging
from urllib.parse import urlparse
from datetime import datetime

logger = logging.getLogger(__name__)

class QuizDatabase:
    """
    قاعدة بيانات للأسئلة والاختبارات باستخدام PostgreSQL.
    """

    def __init__(self):
        """
        تهيئة قاعدة البيانات والاتصال بـ PostgreSQL.
        """
        self.conn = None
        self.connect()
        self.create_tables()

    def connect(self):
        """
        الاتصال بقاعدة بيانات PostgreSQL باستخدام DATABASE_URL.
        """
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            logger.error("DATABASE_URL environment variable not set.")
            # يمكنك هنا إضافة إعدادات اتصال محلية للاختبار إذا أردت
            # مثال:
            # self.conn = psycopg2.connect(database="your_db", user="your_user", password="your_password", host="localhost", port="5432")
            raise ValueError("DATABASE_URL is not configured.")

        try:
            # تحليل DATABASE_URL
            result = urlparse(db_url)
            username = result.username
            password = result.password
            database = result.path[1:]
            hostname = result.hostname
            port = result.port

            self.conn = psycopg2.connect(
                database=database,
                user=username,
                password=password,
                host=hostname,
                port=port
            )
            logger.info("Database connection established.")
        except (Exception, psycopg2.Error) as error:
            logger.error(f"Error while connecting to PostgreSQL: {error}")
            self.conn = None

    def close_connection(self):
        """
        إغلاق الاتصال بقاعدة البيانات.
        """
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed.")

    def execute_query(self, query, params=None, fetch=False):
        """
        تنفيذ استعلام SQL.

        المعلمات:
            query (str): استعلام SQL.
            params (tuple, optional): المعلمات للاستعلام.
            fetch (bool): True لجلب النتائج، False لعمليات التعديل.

        العائد:
            list or None: قائمة بالنتائج إذا كان fetch=True، أو None.
        """
        if not self.conn or self.conn.closed:
            logger.warning("Database connection is closed. Reconnecting...")
            self.connect()
            if not self.conn:
                logger.error("Failed to reconnect to the database.")
                return None

        result = None
        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params)
                if fetch:
                    result = cur.fetchall()
            self.conn.commit() # Commit changes after successful execution
        except (Exception, psycopg2.Error) as error:
            logger.error(f"Error executing query: {error}\nQuery: {query}\nParams: {params}")
            # في حالة الخطأ، قم بإعادة الاتصال للمحاولة التالية
            self.conn.rollback() # Rollback changes on error
            self.close_connection()
            self.connect()
            result = None # Ensure result is None on error
        return result

    def create_tables(self):
        """
        إنشاء جداول قاعدة البيانات إذا لم تكن موجودة.
        """
        # جدول الأسئلة
        create_questions_table_query = """
        CREATE TABLE IF NOT EXISTS questions (
            id SERIAL PRIMARY KEY,
            question_text TEXT NOT NULL,
            options JSONB NOT NULL,            -- ['opt1', 'opt2', 'opt3', 'opt4']
            correct_answer_index INTEGER NOT NULL, -- 0-3
            explanation TEXT,
            chapter TEXT,
            lesson TEXT,
            question_image_id TEXT,       -- Telegram file ID
            option_image_ids JSONB        -- ['id1', 'id2', 'id3', 'id4'] or nulls
        );
        """
        self.execute_query(create_questions_table_query)
        logger.info("Ensured questions table exists.")
        
        # جدول سجل الاختبارات (للتقارير المفصلة)
        create_quiz_history_table_query = """
        CREATE TABLE IF NOT EXISTS quiz_history (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            quiz_type TEXT NOT NULL,      -- 'random', 'chapter', 'lesson', 'review'
            chapter TEXT,
            lesson TEXT,
            start_time TIMESTAMP NOT NULL,
            end_time TIMESTAMP,
            total_questions INTEGER NOT NULL,
            correct_answers INTEGER,
            time_taken INTEGER            -- بالثواني
        );
        """
        self.execute_query(create_quiz_history_table_query)
        logger.info("Ensured quiz_history table exists.")
        
        # جدول إجابات الاختبارات (لتتبع الإجابات الصحيحة والخاطئة)
        create_quiz_answers_table_query = """
        CREATE TABLE IF NOT EXISTS quiz_answers (
            id SERIAL PRIMARY KEY,
            quiz_history_id INTEGER NOT NULL REFERENCES quiz_history(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            user_answer_index INTEGER NOT NULL,
            is_correct BOOLEAN NOT NULL,
            answer_time TIMESTAMP NOT NULL
        );
        """
        self.execute_query(create_quiz_answers_table_query)
        logger.info("Ensured quiz_answers table exists.")

    def add_question(self, question_text, options, correct_answer_index, explanation, chapter=None, lesson=None, question_image_id=None, option_image_ids=None):
        """
        إضافة سؤال جديد إلى قاعدة البيانات.
        """
        if not isinstance(options, list) or len(options) < 2:
             logger.error("Invalid options format. Must be a list of at least 2 strings.")
             return False
        if not isinstance(correct_answer_index, int) or not (0 <= correct_answer_index < len(options)):
             logger.error("Invalid correct_answer_index.")
             return False

        # تأكد من أن option_image_ids قائمة بنفس طول options أو None
        if option_image_ids and (not isinstance(option_image_ids, list) or len(option_image_ids) != len(options)):
            logger.warning("option_image_ids length mismatch. Setting to None.")
            option_image_ids = None

        query = """
        INSERT INTO questions (question_text, options, correct_answer_index, explanation, chapter, lesson, question_image_id, option_image_ids)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
        """
        params = (
            question_text,
            json.dumps(options), # تحويل القائمة إلى JSON
            correct_answer_index,
            explanation,
            chapter,
            lesson,
            question_image_id,
            json.dumps(option_image_ids) if option_image_ids else None # تحويل القائمة إلى JSON
        )
        result = self.execute_query(query, params)
        # execute_query returns None for non-fetch queries, success is indicated by lack of error
        # We might need a better way to confirm success if needed.
        logger.info(f"Attempted to add question: {question_text[:50]}...")
        return True # Assume success if no error occurred

    def _map_row_to_dict(self, row):
        """
        تحويل صف من قاعدة البيانات إلى قاموس.
        """
        if not row:
            return None
        return {
            "id": row[0],
            "question": row[1],
            "options": row[2], # يتم استرجاعها كقائمة بايثون مباشرة من JSONB
            "correct_answer": row[3], # اسم الحقل في الكود القديم كان correct_answer
            "explanation": row[4],
            "chapter": row[5],
            "lesson": row[6],
            "question_image_id": row[7],
            "option_image_ids": row[8] # يتم استرجاعها كقائمة بايثون مباشرة من JSONB
        }

    def get_all_questions(self):
        """
        الحصول على جميع الأسئلة من قاعدة البيانات.
        """
        query = "SELECT id, question_text, options, correct_answer_index, explanation, chapter, lesson, question_image_id, option_image_ids FROM questions ORDER BY id;"
        rows = self.execute_query(query, fetch=True)
        return [self._map_row_to_dict(row) for row in rows] if rows else []

    def get_random_question(self, chapter=None, lesson=None, exclude_ids=None):
        """
        الحصول على سؤال عشوائي، مع إمكانية التصفية حسب الفصل أو الدرس واستبعاد أسئلة محددة.
        
        المعلمات:
            chapter (str, optional): اسم الفصل للتصفية.
            lesson (str, optional): اسم الدرس للتصفية.
            exclude_ids (list, optional): قائمة بمعرفات الأسئلة التي يجب استبعادها.
            
        العائد:
            dict or None: قاموس يمثل السؤال، أو None إذا لم يتم العثور على سؤال.
        """
        query = "SELECT id, question_text, options, correct_answer_index, explanation, chapter, lesson, question_image_id, option_image_ids FROM questions"
        conditions = []
        params = []

        if chapter:
            conditions.append("chapter = %s")
            params.append(chapter)
        if lesson:
            conditions.append("lesson = %s")
            params.append(lesson)
        if exclude_ids and isinstance(exclude_ids, list) and exclude_ids:
            placeholders = ', '.join(['%s'] * len(exclude_ids))
            conditions.append(f"id NOT IN ({placeholders})")
            params.extend(exclude_ids)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY RANDOM() LIMIT 1;"

        rows = self.execute_query(query, tuple(params), fetch=True)
        return self._map_row_to_dict(rows[0]) if rows else None

    def get_question_by_id(self, question_id):
        """
        الحصول على سؤال بواسطة معرفه الفريد (id).
        """
        query = "SELECT id, question_text, options, correct_answer_index, explanation, chapter, lesson, question_image_id, option_image_ids FROM questions WHERE id = %s;"
        rows = self.execute_query(query, (question_id,), fetch=True)
        return self._map_row_to_dict(rows[0]) if rows else None

    def delete_question(self, question_id):
        """
        حذف سؤال من قاعدة البيانات بواسطة معرفه الفريد (id).
        """
        # أولاً، تحقق مما إذا كان السؤال موجوداً (اختياري، لكن جيد)
        if not self.get_question_by_id(question_id):
            logger.warning(f"Attempted to delete non-existent question with id: {question_id}")
            return False

        query = "DELETE FROM questions WHERE id = %s;"
        self.execute_query(query, (question_id,))
        logger.info(f"Deleted question with id: {question_id}")
        return True # Assume success if no error

    def get_chapters(self):
        """
        الحصول على قائمة بجميع الفصول المتاحة.
        """
        query = "SELECT DISTINCT chapter FROM questions WHERE chapter IS NOT NULL ORDER BY chapter;"
        rows = self.execute_query(query, fetch=True)
        return [row[0] for row in rows] if rows else []

    def get_lessons(self, chapter=None):
        """
        الحصول على قائمة بجميع الدروس المتاحة، مع إمكانية التصفية حسب الفصل.
        """
        query = "SELECT DISTINCT lesson FROM questions WHERE lesson IS NOT NULL"
        params = []
        if chapter:
            query += " AND chapter = %s"
            params.append(chapter)
        query += " ORDER BY lesson;"
        rows = self.execute_query(query, tuple(params), fetch=True)
        return [row[0] for row in rows] if rows else []

    def get_questions_by_chapter(self, chapter):
        """
        الحصول على جميع الأسئلة لفصل معين.
        """
        query = "SELECT id, question_text, options, correct_answer_index, explanation, chapter, lesson, question_image_id, option_image_ids FROM questions WHERE chapter = %s ORDER BY id;"
        rows = self.execute_query(query, (chapter,), fetch=True)
        return [self._map_row_to_dict(row) for row in rows] if rows else []

    def get_questions_by_lesson(self, chapter, lesson):
        """
        الحصول على جميع الأسئلة لدرس معين داخل فصل معين.
        """
        query = "SELECT id, question_text, options, correct_answer_index, explanation, chapter, lesson, question_image_id, option_image_ids FROM questions WHERE chapter = %s AND lesson = %s ORDER BY id;"
        rows = self.execute_query(query, (chapter, lesson), fetch=True)
        return [self._map_row_to_dict(row) for row in rows] if rows else []

    # --- وظائف جديدة لدعم تقارير الأداء ووضع المراجعة ---
    
    def start_quiz(self, user_id, quiz_type, chapter=None, lesson=None, total_questions=10):
        """
        بدء اختبار جديد وتسجيله في قاعدة البيانات.
        
        المعلمات:
            user_id (int): معرف المستخدم.
            quiz_type (str): نوع الاختبار ('random', 'chapter', 'lesson', 'review').
            chapter (str, optional): اسم الفصل (للاختبارات حسب الفصل أو الدرس).
            lesson (str, optional): اسم الدرس (للاختبارات حسب الدرس).
            total_questions (int): العدد الإجمالي للأسئلة في الاختبار.
            
        العائد:
            int or None: معرف الاختبار الجديد، أو None في حالة الفشل.
        """
        query = """
        INSERT INTO quiz_history (user_id, quiz_type, chapter, lesson, start_time, total_questions)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
        """
        params = (
            user_id,
            quiz_type,
            chapter,
            lesson,
            datetime.now(),
            total_questions
        )
        result = self.execute_query(query, params, fetch=True)
        if result and result[0]:
            quiz_id = result[0][0]
            logger.info(f"Started new quiz (id: {quiz_id}) for user {user_id}")
            return quiz_id
        return None

    def record_answer(self, quiz_id, question_id, user_answer_index, is_correct):
        """
        تسجيل إجابة المستخدم على سؤال في اختبار.
        
        المعلمات:
            quiz_id (int): معرف الاختبار.
            question_id (int): معرف السؤال.
            user_answer_index (int): مؤشر إجابة المستخدم.
            is_correct (bool): ما إذا كانت الإجابة صحيحة.
            
        العائد:
            bool: True في حالة النجاح، False في حالة الفشل.
        """
        query = """
        INSERT INTO quiz_answers (quiz_history_id, question_id, user_answer_index, is_correct, answer_time)
        VALUES (%s, %s, %s, %s, %s);
        """
        params = (
            quiz_id,
            question_id,
            user_answer_index,
            is_correct,
            datetime.now()
        )
        self.execute_query(query, params)
        logger.info(f"Recorded answer for quiz {quiz_id}, question {question_id}")
        return True

    def end_quiz(self, quiz_id, correct_answers):
        """
        إنهاء اختبار وتسجيل النتائج النهائية.
        
        المعلمات:
            quiz_id (int): معرف الاختبار.
            correct_answers (int): عدد الإجابات الصحيحة.
            
        العائد:
            bool: True في حالة النجاح، False في حالة الفشل.
        """
        # حساب الوقت المستغرق
        query_start_time = "SELECT start_time FROM quiz_history WHERE id = %s;"
        result = self.execute_query(query_start_time, (quiz_id,), fetch=True)
        if not result or not result[0]:
            logger.error(f"Failed to find quiz with id {quiz_id}")
            return False
            
        start_time = result[0][0]
        end_time = datetime.now()
        time_taken = int((end_time - start_time).total_seconds())
        
        # تحديث سجل الاختبار
        query = """
        UPDATE quiz_history 
        SET end_time = %s, correct_answers = %s, time_taken = %s
        WHERE id = %s;
        """
        params = (
            end_time,
            correct_answers,
            time_taken,
            quiz_id
        )
        self.execute_query(query, params)
        logger.info(f"Ended quiz {quiz_id} with {correct_answers} correct answers in {time_taken} seconds")
        return True

    def get_quiz_report(self, quiz_id):
        """
        الحصول على تقرير مفصل عن اختبار.
        
        المعلمات:
            quiz_id (int): معرف الاختبار.
            
        العائد:
            dict or None: قاموس يحتوي على تقرير الاختبار، أو None في حالة الفشل.
        """
        # جلب معلومات الاختبار الأساسية
        query_quiz = """
        SELECT user_id, quiz_type, chapter, lesson, start_time, end_time, 
               total_questions, correct_answers, time_taken
        FROM quiz_history
        WHERE id = %s;
        """
        result_quiz = self.execute_query(query_quiz, (quiz_id,), fetch=True)
        if not result_quiz or not result_quiz[0]:
            logger.error(f"Failed to find quiz with id {quiz_id}")
            return None
            
        row = result_quiz[0]
        quiz_report = {
            "quiz_id": quiz_id,
            "user_id": row[0],
            "quiz_type": row[1],
            "chapter": row[2],
            "lesson": row[3],
            "start_time": row[4],
            "end_time": row[5],
            "total_questions": row[6],
            "correct_answers": row[7] or 0,
            "time_taken": row[8] or 0,
            "score_percentage": round((row[7] or 0) / row[6] * 100, 1) if row[6] > 0 else 0,
            "answers": []
        }
        
        # جلب تفاصيل الإجابات
        query_answers = """
        SELECT qa.question_id, qa.user_answer_index, qa.is_correct, qa.answer_time,
               q.question_text, q.options, q.correct_answer_index, q.explanation
        FROM quiz_answers qa
        JOIN questions q ON qa.question_id = q.id
        WHERE qa.quiz_history_id = %s
        ORDER BY qa.answer_time;
        """
        result_answers = self.execute_query(query_answers, (quiz_id,), fetch=True)
        if result_answers:
            for row in result_answers:
                answer = {
                    "question_id": row[0],
                    "user_answer_index": row[1],
                    "is_correct": row[2],
                    "answer_time": row[3],
                    "question_text": row[4],
                    "options": row[5],
                    "correct_answer_index": row[6],
                    "explanation": row[7]
                }
                quiz_report["answers"].append(answer)
        
        return quiz_report

    def get_user_quiz_history(self, user_id, limit=10):
        """
        الحصول على سجل اختبارات المستخدم.
        
        المعلمات:
            user_id (int): معرف المستخدم.
            limit (int): الحد الأقصى لعدد السجلات المسترجعة.
            
        العائد:
            list: قائمة بسجلات الاختبارات.
        """
        query = """
        SELECT id, quiz_type, chapter, lesson, start_time, end_time, 
               total_questions, correct_answers, time_taken
        FROM quiz_history
        WHERE user_id = %s
        ORDER BY start_time DESC
        LIMIT %s;
        """
        result = self.execute_query(query, (user_id, limit), fetch=True)
        if not result:
            return []
            
        history = []
        for row in result:
            quiz = {
                "quiz_id": row[0],
                "quiz_type": row[1],
                "chapter": row[2],
                "lesson": row[3],
                "start_time": row[4],
                "end_time": row[5],
                "total_questions": row[6],
                "correct_answers": row[7] or 0,
                "time_taken": row[8] or 0,
                "score_percentage": round((row[7] or 0) / row[6] * 100, 1) if row[6] > 0 else 0
            }
            history.append(quiz)
        
        return history

    def get_incorrect_questions(self, user_id, limit=50):
        """
        الحصول على الأسئلة التي أخطأ فيها المستخدم لوضع المراجعة.
        
        المعلمات:
            user_id (int): معرف المستخدم.
            limit (int): الحد الأقصى لعدد الأسئلة المسترجعة.
            
        العائد:
            list: قائمة بمعرفات الأسئلة التي أخطأ فيها المستخدم.
        """
        query = """
        SELECT DISTINCT q.id, q.question_text, q.options, q.correct_answer_index, 
                        q.explanation, q.chapter, q.lesson, q.question_image_id, q.option_image_ids,
                        COUNT(qa.id) as error_count
        FROM questions q
        JOIN quiz_answers qa ON q.id = qa.question_id
        JOIN quiz_history qh ON qa.quiz_history_id = qh.id
        WHERE qh.user_id = %s AND qa.is_correct = FALSE
        GROUP BY q.id
        ORDER BY error_count DESC, q.id
        LIMIT %s;
        """
        rows = self.execute_query(query, (user_id, limit), fetch=True)
        if not rows:
            return []
            
        questions = []
        for row in rows:
            question = self._map_row_to_dict(row[:-1])  # Exclude error_count from mapping
            question["error_count"] = row[-1]  # Add error_count separately
            questions.append(question)
            
        return questions

# مثال للاستخدام (إذا تم تشغيل الملف مباشرة)
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    # تأكد من تعيين DATABASE_URL كمتغير بيئة قبل التشغيل
    # مثال: export DATABASE_URL='postgres://user:password@host:port/database'
    if not os.environ.get("DATABASE_URL"):
        print("Please set the DATABASE_URL environment variable.")
    else:
        db = QuizDatabase()
        if db.conn:
            print("Connection successful!")
            db.close_connection()
