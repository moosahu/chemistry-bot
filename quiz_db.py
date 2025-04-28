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
        # جدول المراحل الدراسية
        create_grade_levels_table_query = """
        CREATE TABLE IF NOT EXISTS grade_levels (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        );
        """
        self.execute_query(create_grade_levels_table_query)
        logger.info("Ensured grade_levels table exists.")
        
        # جدول الفصول
        create_chapters_table_query = """
        CREATE TABLE IF NOT EXISTS chapters (
            id SERIAL PRIMARY KEY,
            grade_level_id INTEGER REFERENCES grade_levels(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            UNIQUE(grade_level_id, name)
        );
        """
        self.execute_query(create_chapters_table_query)
        logger.info("Ensured chapters table exists.")
        
        # جدول الدروس
        create_lessons_table_query = """
        CREATE TABLE IF NOT EXISTS lessons (
            id SERIAL PRIMARY KEY,
            chapter_id INTEGER REFERENCES chapters(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            UNIQUE(chapter_id, name)
        );
        """
        self.execute_query(create_lessons_table_query)
        logger.info("Ensured lessons table exists.")
        
        # جدول الأسئلة (مع إضافة حقل المرحلة الدراسية)
        create_questions_table_query = """
        CREATE TABLE IF NOT EXISTS questions (
            id SERIAL PRIMARY KEY,
            question_text TEXT NOT NULL,
            options JSONB NOT NULL,            -- ['opt1', 'opt2', 'opt3', 'opt4']
            correct_answer_index INTEGER NOT NULL, -- 0-3
            explanation TEXT,
            grade_level_id INTEGER REFERENCES grade_levels(id) ON DELETE SET NULL,
            chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
            lesson_id INTEGER REFERENCES lessons(id) ON DELETE SET NULL,
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
            quiz_type TEXT NOT NULL,      -- 'random', 'chapter', 'lesson', 'review', 'grade_level'
            grade_level_id INTEGER REFERENCES grade_levels(id) ON DELETE SET NULL,
            chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
            lesson_id INTEGER REFERENCES lessons(id) ON DELETE SET NULL,
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
        
        # إضافة المراحل الدراسية الافتراضية إذا لم تكن موجودة
        self._initialize_default_grade_levels()

    def _initialize_default_grade_levels(self):
        """
        إضافة المراحل الدراسية الافتراضية إذا لم تكن موجودة.
        """
        default_grade_levels = ["أول ثانوي", "ثاني ثانوي", "ثالث ثانوي"]
        
        for grade_level in default_grade_levels:
            query = """
            INSERT INTO grade_levels (name)
            SELECT %s
            WHERE NOT EXISTS (SELECT 1 FROM grade_levels WHERE name = %s);
            """
            self.execute_query(query, (grade_level, grade_level))
        
        logger.info("Initialized default grade levels if needed.")

    # --- وظائف إدارة المراحل والفصول والدروس ---
    
    def get_grade_levels(self):
        """
        الحصول على قائمة بجميع المراحل الدراسية.
        
        العائد:
            list: قائمة بأزواج (id, name) للمراحل الدراسية.
        """
        query = "SELECT id, name FROM grade_levels ORDER BY id;"
        rows = self.execute_query(query, fetch=True)
        return rows if rows else []
    
    def add_grade_level(self, name):
        """
        إضافة مرحلة دراسية جديدة.
        
        المعلمات:
            name (str): اسم المرحلة الدراسية.
            
        العائد:
            int or None: معرف المرحلة الدراسية الجديدة، أو None في حالة الفشل.
        """
        query = """
        INSERT INTO grade_levels (name)
        VALUES (%s)
        ON CONFLICT (name) DO NOTHING
        RETURNING id;
        """
        result = self.execute_query(query, (name,), fetch=True)
        if result and result[0]:
            logger.info(f"Added new grade level: {name}")
            return result[0][0]
        
        # إذا كان هناك تعارض، ابحث عن المعرف الموجود
        query = "SELECT id FROM grade_levels WHERE name = %s;"
        result = self.execute_query(query, (name,), fetch=True)
        if result and result[0]:
            logger.info(f"Grade level already exists: {name}")
            return result[0][0]
        
        logger.error(f"Failed to add grade level: {name}")
        return None
    
    def get_chapters_by_grade(self, grade_level_id):
        """
        الحصول على قائمة بجميع الفصول لمرحلة دراسية معينة.
        
        المعلمات:
            grade_level_id (int): معرف المرحلة الدراسية.
            
        العائد:
            list: قائمة بأزواج (id, name) للفصول.
        """
        query = "SELECT id, name FROM chapters WHERE grade_level_id = %s ORDER BY id;"
        rows = self.execute_query(query, (grade_level_id,), fetch=True)
        return rows if rows else []
    
    def add_chapter(self, grade_level_id, name):
        """
        إضافة فصل جديد لمرحلة دراسية معينة.
        
        المعلمات:
            grade_level_id (int): معرف المرحلة الدراسية.
            name (str): اسم الفصل.
            
        العائد:
            int or None: معرف الفصل الجديد، أو None في حالة الفشل.
        """
        query = """
        INSERT INTO chapters (grade_level_id, name)
        VALUES (%s, %s)
        ON CONFLICT (grade_level_id, name) DO NOTHING
        RETURNING id;
        """
        result = self.execute_query(query, (grade_level_id, name), fetch=True)
        if result and result[0]:
            logger.info(f"Added new chapter: {name} to grade level {grade_level_id}")
            return result[0][0]
        
        # إذا كان هناك تعارض، ابحث عن المعرف الموجود
        query = "SELECT id FROM chapters WHERE grade_level_id = %s AND name = %s;"
        result = self.execute_query(query, (grade_level_id, name), fetch=True)
        if result and result[0]:
            logger.info(f"Chapter already exists: {name} in grade level {grade_level_id}")
            return result[0][0]
        
        logger.error(f"Failed to add chapter: {name} to grade level {grade_level_id}")
        return None
    
    def get_lessons_by_chapter(self, chapter_id):
        """
        الحصول على قائمة بجميع الدروس لفصل معين.
        
        المعلمات:
            chapter_id (int): معرف الفصل.
            
        العائد:
            list: قائمة بأزواج (id, name) للدروس.
        """
        query = "SELECT id, name FROM lessons WHERE chapter_id = %s ORDER BY id;"
        rows = self.execute_query(query, (chapter_id,), fetch=True)
        return rows if rows else []
    
    def add_lesson(self, chapter_id, name):
        """
        إضافة درس جديد لفصل معين.
        
        المعلمات:
            chapter_id (int): معرف الفصل.
            name (str): اسم الدرس.
            
        العائد:
            int or None: معرف الدرس الجديد، أو None في حالة الفشل.
        """
        query = """
        INSERT INTO lessons (chapter_id, name)
        VALUES (%s, %s)
        ON CONFLICT (chapter_id, name) DO NOTHING
        RETURNING id;
        """
        result = self.execute_query(query, (chapter_id, name), fetch=True)
        if result and result[0]:
            logger.info(f"Added new lesson: {name} to chapter {chapter_id}")
            return result[0][0]
        
        # إذا كان هناك تعارض، ابحث عن المعرف الموجود
        query = "SELECT id FROM lessons WHERE chapter_id = %s AND name = %s;"
        result = self.execute_query(query, (chapter_id, name), fetch=True)
        if result and result[0]:
            logger.info(f"Lesson already exists: {name} in chapter {chapter_id}")
            return result[0][0]
        
        logger.error(f"Failed to add lesson: {name} to chapter {chapter_id}")
        return None

    # --- وظائف إدارة الأسئلة (محدثة) ---
    
    def add_question(self, question_text, options, correct_answer_index, explanation=None, 
                    grade_level_id=None, chapter_id=None, lesson_id=None, 
                    question_image_id=None, option_image_ids=None):
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
        INSERT INTO questions (question_text, options, correct_answer_index, explanation, 
                              grade_level_id, chapter_id, lesson_id, 
                              question_image_id, option_image_ids)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
        """
        params = (
            question_text,
            json.dumps(options), # تحويل القائمة إلى JSON
            correct_answer_index,
            explanation,
            grade_level_id,
            chapter_id,
            lesson_id,
            question_image_id,
            json.dumps(option_image_ids) if option_image_ids else None # تحويل القائمة إلى JSON
        )
        result = self.execute_query(query, params, fetch=True)
        if result and result[0]:
            question_id = result[0][0]
            logger.info(f"Added new question (id: {question_id}): {question_text[:50]}...")
            return question_id
        
        logger.error(f"Failed to add question: {question_text[:50]}...")
        return None

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
            "grade_level_id": row[5],
            "chapter_id": row[6],
            "lesson_id": row[7],
            "question_image_id": row[8],
            "option_image_ids": row[9] # يتم استرجاعها كقائمة بايثون مباشرة من JSONB
        }

    def get_all_questions(self):
        """
        الحصول على جميع الأسئلة من قاعدة البيانات.
        """
        query = """
        SELECT id, question_text, options, correct_answer_index, explanation, 
               grade_level_id, chapter_id, lesson_id, 
               question_image_id, option_image_ids 
        FROM questions 
        ORDER BY id;
        """
        rows = self.execute_query(query, fetch=True)
        return [self._map_row_to_dict(row) for row in rows] if rows else []

    def get_random_question(self, grade_level_id=None, chapter_id=None, lesson_id=None, exclude_ids=None):
        """
        الحصول على سؤال عشوائي، مع إمكانية التصفية حسب المرحلة أو الفصل أو الدرس واستبعاد أسئلة محددة.
        """
        query = """
        SELECT id, question_text, options, correct_answer_index, explanation, 
               grade_level_id, chapter_id, lesson_id, 
               question_image_id, option_image_ids 
        FROM questions
        """
        conditions = []
        params = []

        if grade_level_id:
            conditions.append("grade_level_id = %s")
            params.append(grade_level_id)
        if chapter_id:
            conditions.append("chapter_id = %s")
            params.append(chapter_id)
        if lesson_id:
            conditions.append("lesson_id = %s")
            params.append(lesson_id)
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
        query = """
        SELECT id, question_text, options, correct_answer_index, explanation, 
               grade_level_id, chapter_id, lesson_id, 
               question_image_id, option_image_ids 
        FROM questions 
        WHERE id = %s;
        """
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

    def get_questions_by_grade_level(self, grade_level_id):
        """
        الحصول على جميع الأسئلة لمرحلة دراسية معينة.
        """
        query = """
        SELECT id, question_text, options, correct_answer_index, explanation, 
               grade_level_id, chapter_id, lesson_id, 
               question_image_id, option_image_ids 
        FROM questions 
        WHERE grade_level_id = %s 
        ORDER BY id;
        """
        rows = self.execute_query(query, (grade_level_id,), fetch=True)
        return [self._map_row_to_dict(row) for row in rows] if rows else []

    def get_questions_by_chapter(self, chapter_id):
        """
        الحصول على جميع الأسئلة لفصل معين.
        """
        query = """
        SELECT id, question_text, options, correct_answer_index, explanation, 
               grade_level_id, chapter_id, lesson_id, 
               question_image_id, option_image_ids 
        FROM questions 
        WHERE chapter_id = %s 
        ORDER BY id;
        """
        rows = self.execute_query(query, (chapter_id,), fetch=True)
        return [self._map_row_to_dict(row) for row in rows] if rows else []

    def get_questions_by_lesson(self, lesson_id):
        """
        الحصول على جميع الأسئلة لدرس معين.
        """
        query = """
        SELECT id, question_text, options, correct_answer_index, explanation, 
               grade_level_id, chapter_id, lesson_id, 
               question_image_id, option_image_ids 
        FROM questions 
        WHERE lesson_id = %s 
        ORDER BY id;
        """
        rows = self.execute_query(query, (lesson_id,), fetch=True)
        return [self._map_row_to_dict(row) for row in rows] if rows else []

    # --- وظائف تقارير الأداء ووضع المراجعة (محدثة) ---
    
    def start_quiz(self, user_id, quiz_type, grade_level_id=None, chapter_id=None, lesson_id=None, total_questions=10):
        """
        بدء اختبار جديد وتسجيله في قاعدة البيانات.
        """
        query = """
        INSERT INTO quiz_history (user_id, quiz_type, grade_level_id, chapter_id, lesson_id, start_time, total_questions)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
        """
        params = (
            user_id,
            quiz_type,
            grade_level_id,
            chapter_id,
            lesson_id,
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
        logger.info(f"Ended quiz {quiz_id} with {correct_answers} correct answers")
        return True

    def get_quiz_history(self, user_id, limit=10):
        """
        الحصول على سجل الاختبارات السابقة للمستخدم.
        """
        query = """
        SELECT id, quiz_type, grade_level_id, chapter_id, lesson_id, 
               start_time, end_time, total_questions, correct_answers, time_taken
        FROM quiz_history
        WHERE user_id = %s AND end_time IS NOT NULL
        ORDER BY end_time DESC
        LIMIT %s;
        """
        rows = self.execute_query(query, (user_id, limit), fetch=True)
        return rows if rows else []

    def get_quiz_details(self, quiz_id):
        """
        الحصول على تفاصيل اختبار معين.
        """
        query = """
        SELECT qh.id, qh.quiz_type, qh.grade_level_id, qh.chapter_id, qh.lesson_id,
               qh.start_time, qh.end_time, qh.total_questions, qh.correct_answers, qh.time_taken,
               gl.name as grade_level_name, 
               ch.name as chapter_name, 
               l.name as lesson_name
        FROM quiz_history qh
        LEFT JOIN grade_levels gl ON qh.grade_level_id = gl.id
        LEFT JOIN chapters ch ON qh.chapter_id = ch.id
        LEFT JOIN lessons l ON qh.lesson_id = l.id
        WHERE qh.id = %s;
        """
        rows = self.execute_query(query, (quiz_id,), fetch=True)
        return rows[0] if rows else None

    def get_quiz_answers(self, quiz_id):
        """
        الحصول على إجابات المستخدم في اختبار معين.
        """
        query = """
        SELECT qa.question_id, qa.user_answer_index, qa.is_correct, qa.answer_time,
               q.question_text, q.options, q.correct_answer_index, q.explanation,
               q.question_image_id, q.option_image_ids
        FROM quiz_answers qa
        JOIN questions q ON qa.question_id = q.id
        WHERE qa.quiz_history_id = %s
        ORDER BY qa.answer_time;
        """
        rows = self.execute_query(query, (quiz_id,), fetch=True)
        return rows if rows else []

    def get_incorrect_questions(self, user_id, limit=100):
        """
        الحصول على الأسئلة التي أخطأ فيها المستخدم سابقاً.
        """
        query = """
        SELECT DISTINCT q.id, q.question_text, q.options, q.correct_answer_index, q.explanation,
                        q.grade_level_id, q.chapter_id, q.lesson_id,
                        q.question_image_id, q.option_image_ids
        FROM quiz_answers qa
        JOIN questions q ON qa.question_id = q.id
        JOIN quiz_history qh ON qa.quiz_history_id = qh.id
        WHERE qh.user_id = %s AND qa.is_correct = FALSE
        ORDER BY RANDOM()
        LIMIT %s;
        """
        rows = self.execute_query(query, (user_id, limit), fetch=True)
        return [self._map_row_to_dict(row) for row in rows] if rows else []

    # --- وظائف مساعدة للتحويل من النظام القديم ---
    
    def migrate_legacy_questions(self):
        """
        تحويل الأسئلة من النظام القديم (chapter, lesson) إلى النظام الجديد (grade_level_id, chapter_id, lesson_id).
        """
        # التحقق من وجود جدول الأسئلة القديم
        check_query = """
        SELECT EXISTS (
            SELECT FROM information_schema.columns 
            WHERE table_name = 'questions' AND column_name = 'chapter'
        );
        """
        result = self.execute_query(check_query, fetch=True)
        if not result or not result[0][0]:
            logger.info("No legacy questions table found. Migration not needed.")
            return False
        
        # الحصول على جميع الأسئلة القديمة
        legacy_query = """
        SELECT id, question_text, options, correct_answer_index, explanation, 
               chapter, lesson, question_image_id, option_image_ids
        FROM questions;
        """
        legacy_questions = self.execute_query(legacy_query, fetch=True)
        if not legacy_questions:
            logger.info("No legacy questions found. Migration not needed.")
            return False
        
        # إضافة مرحلة دراسية افتراضية للأسئلة القديمة
        default_grade_level_id = self.add_grade_level("غير محدد")
        if not default_grade_level_id:
            logger.error("Failed to create default grade level for migration.")
            return False
        
        # تحويل كل سؤال
        for q in legacy_questions:
            q_id, q_text, q_options, q_correct, q_explanation, q_chapter, q_lesson, q_img, q_opt_imgs = q
            
            # إضافة الفصل إذا لم يكن موجوداً
            chapter_id = None
            if q_chapter:
                chapter_id = self.add_chapter(default_grade_level_id, q_chapter)
            
            # إضافة الدرس إذا لم يكن موجوداً
            lesson_id = None
            if q_lesson and chapter_id:
                lesson_id = self.add_lesson(chapter_id, q_lesson)
            
            # تحديث السؤال
            update_query = """
            UPDATE questions
            SET grade_level_id = %s, chapter_id = %s, lesson_id = %s
            WHERE id = %s;
            """
            self.execute_query(update_query, (default_grade_level_id, chapter_id, lesson_id, q_id))
        
        logger.info(f"Migrated {len(legacy_questions)} legacy questions to new structure.")
        return True
