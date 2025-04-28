#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import psycopg2
import json
import random
import logging
from urllib.parse import urlparse

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
        self.create_table()

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

    def create_table(self):
        """
        إنشاء جدول الأسئلة إذا لم يكن موجوداً.
        """
        create_table_query = """
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
        self.execute_query(create_table_query)
        logger.info("Ensured questions table exists.")

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

    def get_random_question(self, chapter=None, lesson=None):
        """
        الحصول على سؤال عشوائي، مع إمكانية التصفية حسب الفصل أو الدرس.
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

    # --- وظائف الاستيراد والتصدير (تحتاج إلى إعادة نظر أو تبسيط/تعطيل) ---
    # تم تعطيل هذه الوظائف مؤقتاً لأنها تعتمد على الملفات و pandas
    # وتحتاج إلى إعادة تصميم لتعمل مع قاعدة البيانات بشكل فعال.

    def import_from_excel(self, file_path):
        logger.warning("Import from Excel is currently disabled in DB mode.")
        return 0, ["الاستيراد من Excel معطل حالياً في وضع قاعدة البيانات."]

    def import_from_csv(self, file_path):
        logger.warning("Import from CSV is currently disabled in DB mode.")
        return 0, ["الاستيراد من CSV معطل حالياً في وضع قاعدة البيانات."]

    def create_excel_template(self, output_file):
        logger.warning("Excel template creation is currently disabled in DB mode.")
        # يمكن إنشاء ملف قالب ثابت إذا لزم الأمر
        return False

    def create_csv_template(self, output_file):
        logger.warning("CSV template creation is currently disabled in DB mode.")
        # يمكن إنشاء ملف قالب ثابت إذا لزم الأمر
        return False

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

            # مثال لإضافة سؤال
            # db.add_question(
            #     question_text="ما هو رمز الماء؟",
            #     options=["H2O", "CO2", "O2", "N2"],
            #     correct_answer_index=0,
            #     explanation="الماء يتكون من ذرتي هيدروجين وذرة أكسجين.",
            #     chapter="1",
            #     lesson=" المركبات"
            # )

            # مثال لجلب جميع الأسئلة
            all_q = db.get_all_questions()
            print(f"Total questions: {len(all_q)}")
            if all_q:
                print("First question:", all_q[0])

            # مثال لجلب سؤال عشوائي
            random_q = db.get_random_question()
            if random_q:
                print("Random question:", random_q)

            # مثال لجلب الفصول
            chapters = db.get_chapters()
            print("Chapters:", chapters)

            # مثال لجلب الدروس لفصل معين
            if chapters:
                lessons = db.get_lessons(chapter=chapters[0])
                print(f"Lessons in chapter {chapters[0]}:", lessons)

            db.close_connection()

