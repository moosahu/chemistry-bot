#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import psycopg2
import logging
import sys

# تكوين التسجيل
logging.basicConfig(
    format=\'%(asctime)s - %(name)s - %(levelname)s - %(message)s\',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout) # تسجيل في المخرجات القياسية
    ]
)
logger = logging.getLogger(__name__)

def update_schema():
    """Updates the database schema to add the grade_level_id column to the questions table."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL environment variable not set.")
        return

    conn = None
    try:
        logger.info("Connecting to the database...")
        conn = psycopg2.connect(db_url, sslmode=\'require\')
        cur = conn.cursor()
        logger.info("Database connection successful.")

        # التحقق مما إذا كان العمود موجودًا بالفعل
        logger.info("Checking if \'grade_level_id\' column exists in \'questions\' table...")
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = \'public\' 
            AND table_name = \'questions\' 
            AND column_name = \'grade_level_id\';
        """)
        exists = cur.fetchone()

        if exists:
            logger.info("Column \'grade_level_id\' already exists in \'questions\' table. No changes needed.")
        else:
            # إضافة العمود grade_level_id إلى جدول questions
            logger.info("Adding \'grade_level_id\' column to \'questions\' table...")
            cur.execute("ALTER TABLE questions ADD COLUMN grade_level_id INTEGER;")
            conn.commit()
            logger.info("Column \'grade_level_id\' added successfully.")

            # (اختياري) إضافة مفتاح خارجي إذا كان جدول grade_levels موجودًا
            # logger.info("Adding foreign key constraint...")
            # cur.execute("ALTER TABLE questions ADD CONSTRAINT fk_grade_level FOREIGN KEY (grade_level_id) REFERENCES grade_levels (id) ON DELETE SET NULL;")
            # conn.commit()
            # logger.info("Foreign key constraint added successfully.")

        cur.close()

    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
        if conn:
            conn.rollback() # التراجع عن التغييرات في حالة حدوث خطأ
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
    finally:
        if conn:
            conn.close()
            logger.info("Database connection closed.")

if __name__ == "__main__":
    logger.info("Starting database schema update...")
    update_schema()
    logger.info("Database schema update process finished.")

