#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import psycopg2
from psycopg2 import sql
import logging

# تكوين التسجيل (تم إصلاح الخطأ المطبعي في السطر format)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_database_url():
    """الحصول على عنوان URL لقاعدة البيانات من متغيرات البيئة."""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        logger.error("DATABASE_URL environment variable not found")
        return None
    
    # تعديل عنوان URL إذا كان يبدأ بـ postgres:// (لتوافق Heroku)
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    return database_url

def update_database_schema():
    """تحديث مخطط قاعدة البيانات لإضافة عمود grade_level_id."""
    database_url = get_database_url()
    if not database_url:
        return False
    
    conn = None
    cursor = None
    try:
        # الاتصال بقاعدة البيانات
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        # التحقق مما إذا كان العمود grade_level_id موجودًا بالفعل في جدول questions
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'questions' AND column_name = 'grade_level_id'
        """)
        
        if cursor.fetchone():
            logger.info("Column 'grade_level_id' already exists in 'questions' table.")
        else:
            # إضافة العمود grade_level_id إلى جدول questions
            cursor.execute("""
                ALTER TABLE questions 
                ADD COLUMN grade_level_id INTEGER
            """)
            
            # إنشاء فهرس للعمود الجديد
            cursor.execute("""
                CREATE INDEX idx_questions_grade_level_id 
                ON questions (grade_level_id)
            """)
            
            # تحديث العمود بقيمة افتراضية (1 للمرحلة الأولى)
            # يجب التأكد من وجود مرحلة ID=1 في جدول grade_levels قبل هذا
            # أو التعامل مع الحالة التي لا يوجد فيها
            cursor.execute("""
                UPDATE questions 
                SET grade_level_id = 1 
                WHERE grade_level_id IS NULL
            """)
            
            logger.info("Added 'grade_level_id' column to 'questions' table and set default values.")
        
        # التحقق مما إذا كان جدول grade_levels موجودًا
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'grade_levels'
            )
        """)
        
        if not cursor.fetchone()[0]:
            # إنشاء جدول grade_levels
            cursor.execute("""
                CREATE TABLE grade_levels (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # إدراج المراحل الدراسية الافتراضية
            cursor.execute("""
                INSERT INTO grade_levels (name) VALUES 
                ('أول ثانوي'),
                ('ثاني ثانوي'),
                ('ثالث ثانوي')
            """)
            
            logger.info("Created 'grade_levels' table and inserted default values.")
        else:
             logger.info("'grade_levels' table already exists.")

        # التحقق مما إذا كان جدول chapters موجودًا
        cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'chapters')")
        if not cursor.fetchone()[0]:
            cursor.execute("""
                CREATE TABLE chapters (
                    id SERIAL PRIMARY KEY,
                    grade_level_id INTEGER REFERENCES grade_levels(id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("Created 'chapters' table.")
        else:
            logger.info("'chapters' table already exists.")

        # التحقق مما إذا كان جدول lessons موجودًا
        cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'lessons')")
        if not cursor.fetchone()[0]:
            cursor.execute("""
                CREATE TABLE lessons (
                    id SERIAL PRIMARY KEY,
                    chapter_id INTEGER REFERENCES chapters(id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("Created 'lessons' table.")
        else:
            logger.info("'lessons' table already exists.")

        # التحقق من وجود عمود lesson_id في جدول questions
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'questions' AND column_name = 'lesson_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE questions ADD COLUMN lesson_id INTEGER REFERENCES lessons(id) ON DELETE SET NULL")
            logger.info("Added 'lesson_id' column to 'questions' table.")
        else:
            logger.info("Column 'lesson_id' already exists in 'questions' table.")

        # التحقق من وجود عمود chapter_id في جدول questions
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'questions' AND column_name = 'chapter_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE questions ADD COLUMN chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL")
            logger.info("Added 'chapter_id' column to 'questions' table.")
        else:
            logger.info("Column 'chapter_id' already exists in 'questions' table.")

        # تأكيد التغييرات
        conn.commit()
        logger.info("Database schema update completed successfully.")
        
        return True
    
    except Exception as e:
        logger.error(f"Error updating database schema: {e}")
        if conn:
            conn.rollback() # التراجع عن التغييرات في حالة حدوث خطأ
        return False
    finally:
        # إغلاق الاتصال دائماً
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            logger.info("Database connection closed.")

if __name__ == "__main__":
    logger.info("Starting database schema update...")
    success = update_database_schema()
    
    if success:
        logger.info("Database schema update finished successfully.")
        # الخروج بنجاح
        exit(0)
    else:
        logger.error("Database schema update failed.")
        # الخروج مع رمز خطأ
        exit(1)
