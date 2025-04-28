#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import json
import time
import re
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode, InputMediaPhoto
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters, 
    CallbackQueryHandler, ConversationHandler, CallbackContext
)
from telegram.error import TelegramError, BadRequest

# استيراد قاعدة البيانات المحسنة مع دعم المراحل الدراسية
from quiz_db import QuizDatabase

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# المتغيرات العامة
TOKEN = "8167394360:AAG-b3v-VDmxLtWVQCuBkc694Mt3ZCs18IY"  # !!! استبدل هذا بتوكن البوت الخاص بك !!!
ADMIN_USER_ID = 6448526509  # !!! استبدل هذا بمعرف المستخدم الرقمي الخاص بك !!!

# إنشاء قاعدة البيانات
QUIZ_DB = QuizDatabase()

# حالات المحادثة
(
    MAIN_MENU, ADMIN_MENU, QUIZ_MENU, QUIZ_QUESTION, QUIZ_RESULT,
    ADD_QUESTION, ADD_QUESTION_OPTIONS, ADD_QUESTION_CORRECT, ADD_QUESTION_EXPLANATION,
    ADD_QUESTION_CHAPTER, ADD_QUESTION_LESSON, ADD_QUESTION_IMAGE, ADD_OPTION_IMAGES,
    VIEW_QUESTIONS, DELETE_QUESTION, QUIZ_TYPE, QUIZ_CHAPTER, QUIZ_LESSON,
    QUIZ_REVIEW, QUIZ_HISTORY, QUIZ_DETAILS, QUIZ_TIMER,
    MANAGE_STRUCTURE, ADD_GRADE_LEVEL, ADD_CHAPTER, ADD_LESSON,
    SELECT_GRADE_LEVEL, SELECT_CHAPTER, SELECT_LESSON,
    ADD_QUESTION_GRADE_LEVEL
) = range(31)

# حالات إضافية للمحادثة
WAITING_FOR_GRADE_LEVEL = 100
WAITING_FOR_CHAPTER = 101
WAITING_FOR_LESSON = 102

# قواميس لتخزين بيانات المستخدم المؤقتة
user_data = {}
quiz_data = {}
temp_messages = {}

# وظائف مساعدة
def is_admin(user_id):
    """التحقق مما إذا كان المستخدم مسؤولاً."""
    return str(user_id) == str(ADMIN_USER_ID)

def get_main_menu_keyboard():
    """إنشاء لوحة مفاتيح القائمة الرئيسية."""
    keyboard = [
        [InlineKeyboardButton("🧪 بدء اختبار", callback_data="quiz")],
        [InlineKeyboardButton("📊 تقارير الأداء", callback_data="history")],
    ]
    
    # إضافة زر الإدارة للمسؤولين فقط
    if ADMIN_USER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ الإدارة", callback_data="admin")])
    
    return InlineKeyboardMarkup(keyboard)

def get_admin_menu_keyboard():
    """إنشاء لوحة مفاتيح قائمة الإدارة."""
    keyboard = [
        [InlineKeyboardButton("➕ إضافة سؤال", callback_data="add_question")],
        [InlineKeyboardButton("👁️ عرض الأسئلة", callback_data="view_questions")],
        [InlineKeyboardButton("🗂️ إدارة الهيكل التعليمي", callback_data="manage_structure")],
        [InlineKeyboardButton("🔙 العودة", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_structure_menu_keyboard():
    """إنشاء لوحة مفاتيح قائمة إدارة الهيكل التعليمي."""
    keyboard = [
        [InlineKeyboardButton("➕ إضافة مرحلة دراسية", callback_data="add_grade_level")],
        [InlineKeyboardButton("➕ إضافة فصل", callback_data="add_chapter")],
        [InlineKeyboardButton("➕ إضافة درس", callback_data="add_lesson")],
        [InlineKeyboardButton("👁️ عرض الهيكل الحالي", callback_data="view_structure")],
        [InlineKeyboardButton("🔙 العودة", callback_data="back_to_admin")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_quiz_type_keyboard():
    """إنشاء لوحة مفاتيح لاختيار نوع الاختبار."""
    keyboard = [
        [InlineKeyboardButton("📚 أول ثانوي", callback_data="grade_level_1")],
        [InlineKeyboardButton("📚 ثاني ثانوي", callback_data="grade_level_2")],
        [InlineKeyboardButton("📚 ثالث ثانوي", callback_data="grade_level_3")],
        [InlineKeyboardButton("🔄 تحصيلي عام", callback_data="comprehensive")],
        [InlineKeyboardButton("❌ مراجعة الأخطاء", callback_data="review")],
        [InlineKeyboardButton("🔙 العودة", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_timer_keyboard():
    """إنشاء لوحة مفاتيح لاختيار مدة الاختبار."""
    keyboard = [
        [
            InlineKeyboardButton("5 دقائق", callback_data="timer_5"),
            InlineKeyboardButton("10 دقائق", callback_data="timer_10"),
            InlineKeyboardButton("15 دقيقة", callback_data="timer_15")
        ],
        [InlineKeyboardButton("بدون وقت", callback_data="timer_0")],
        [InlineKeyboardButton("🔙 العودة", callback_data="back_to_quiz_type")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_grade_levels_keyboard(for_quiz=False):
    """إنشاء لوحة مفاتيح لاختيار المرحلة الدراسية."""
    grade_levels = QUIZ_DB.get_grade_levels()
    keyboard = []
    
    for grade_id, grade_name in grade_levels:
        callback_data = f"quiz_grade_{grade_id}" if for_quiz else f"grade_{grade_id}"
        keyboard.append([InlineKeyboardButton(grade_name, callback_data=callback_data)])
    
    back_callback = "back_to_quiz_type" if for_quiz else "back_to_structure"
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data=back_callback)])
    
    return InlineKeyboardMarkup(keyboard)

def get_chapters_keyboard(grade_level_id, for_quiz=False):
    """إنشاء لوحة مفاتيح لاختيار الفصل."""
    chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    keyboard = []
    
    for chapter_id, chapter_name in chapters:
        callback_data = f"quiz_chapter_{chapter_id}" if for_quiz else f"chapter_{chapter_id}"
        keyboard.append([InlineKeyboardButton(chapter_name, callback_data=callback_data)])
    
    back_callback = "back_to_grade_selection" if for_quiz else "back_to_grade_selection_admin"
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data=back_callback)])
    
    return InlineKeyboardMarkup(keyboard)

def get_lessons_keyboard(chapter_id, for_quiz=False):
    """إنشاء لوحة مفاتيح لاختيار الدرس."""
    lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
    keyboard = []
    
    for lesson_id, lesson_name in lessons:
        callback_data = f"quiz_lesson_{lesson_id}" if for_quiz else f"lesson_{lesson_id}"
        keyboard.append([InlineKeyboardButton(lesson_name, callback_data=callback_data)])
    
    back_callback = "back_to_chapter_selection" if for_quiz else "back_to_chapter_selection_admin"
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data=back_callback)])
    
    return InlineKeyboardMarkup(keyboard)

def get_yes_no_keyboard(callback_prefix):
    """إنشاء لوحة مفاتيح نعم/لا."""
    keyboard = [
        [
            InlineKeyboardButton("نعم", callback_data=f"{callback_prefix}_yes"),
            InlineKeyboardButton("لا", callback_data=f"{callback_prefix}_no")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def format_time(seconds):
    """تنسيق الوقت بالثواني إلى صيغة دقائق:ثواني."""
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"

# وظائف المعالجة الرئيسية
def start(update: Update, context: CallbackContext):
    """معالجة أمر /start."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} started the bot")
    
    # ترحيب بالمستخدم
    message = (
        "👋 مرحباً بك في بوت اختبارات الكيمياء!\n\n"
        "يمكنك استخدام هذا البوت للتدرب على أسئلة الكيمياء والاستعداد للاختبارات.\n\n"
        "اختر من القائمة أدناه:"
    )
    
    update.message.reply_text(message, reply_markup=get_main_menu_keyboard())
    return MAIN_MENU

def help_command(update: Update, context: CallbackContext):
    """معالجة أمر /help."""
    help_text = (
        "🔍 *دليل استخدام بوت اختبارات الكيمياء*\n\n"
        "*الأوامر الأساسية:*\n"
        "/start - بدء البوت وعرض القائمة الرئيسية\n"
        "/help - عرض هذه الرسالة\n\n"
        
        "*للمستخدمين:*\n"
        "• اضغط على 'بدء اختبار' لبدء اختبار جديد\n"
        "• اختر المرحلة الدراسية ثم الفصل أو الدرس\n"
        "• اختر مدة الاختبار (أو بدون وقت)\n"
        "• أجب على الأسئلة باختيار الإجابة الصحيحة\n"
        "• اطلع على نتيجتك وتقرير أدائك بعد الانتهاء\n\n"
        
        "*للمسؤولين:*\n"
        "• استخدم قائمة 'الإدارة' لإضافة أو عرض الأسئلة\n"
        "• يمكنك إدارة الهيكل التعليمي (المراحل، الفصول، الدروس)\n"
        "• يمكنك إضافة أسئلة مع صور للسؤال والخيارات\n\n"
        
        "للحصول على مساعدة إضافية، تواصل مع مطور البوت."
    )
    
    update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    return MAIN_MENU

def button_handler(update: Update, context: CallbackContext):
    """معالجة الضغط على الأزرار."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    logger.info(f"User {user_id} pressed button: {data}")
    query.answer()
    
    # القائمة الرئيسية
    if data == "quiz":
        return show_quiz_types(update, context)
    elif data == "history":
        return show_quiz_history(update, context)
    elif data == "admin":
        if is_admin(user_id):
            return show_admin_menu(update, context)
        else:
            query.edit_message_text("⛔ عذراً، هذه الميزة متاحة للمسؤولين فقط.", reply_markup=get_main_menu_keyboard())
            return MAIN_MENU
    
    # قائمة الإدارة
    elif data == "add_question":
        return start_add_question(update, context)
    elif data == "view_questions":
        return view_questions(update, context)
    elif data == "manage_structure":
        return show_structure_menu(update, context)
    elif data == "back_to_main":
        query.edit_message_text("القائمة الرئيسية:", reply_markup=get_main_menu_keyboard())
        return MAIN_MENU
    
    # قائمة إدارة الهيكل التعليمي
    elif data == "add_grade_level":
        return start_add_grade_level(update, context)
    elif data == "add_chapter":
        return start_add_chapter(update, context)
    elif data == "add_lesson":
        return start_add_lesson(update, context)
    elif data == "view_structure":
        return view_structure(update, context)
    elif data == "back_to_admin":
        return show_admin_menu(update, context)
    
    # اختيار نوع الاختبار
    elif data.startswith("grade_level_"):
        grade_level_id = int(data.split("_")[-1])
        context.user_data["selected_grade_level_id"] = grade_level_id
        return select_quiz_timer(update, context)
    elif data == "comprehensive":
        context.user_data["quiz_type"] = "comprehensive"
        return select_quiz_timer(update, context)
    elif data == "review":
        context.user_data["quiz_type"] = "review"
        return select_quiz_timer(update, context)
    
    # اختيار المؤقت
    elif data.startswith("timer_"):
        minutes = int(data.split("_")[-1])
        context.user_data["timer_minutes"] = minutes
        
        if context.user_data.get("quiz_type") == "comprehensive":
            return start_comprehensive_quiz(update, context)
        elif context.user_data.get("quiz_type") == "review":
            return start_review_quiz(update, context)
        elif "selected_grade_level_id" in context.user_data:
            grade_level_id = context.user_data["selected_grade_level_id"]
            grade_levels = QUIZ_DB.get_grade_levels()
            grade_name = next((name for id, name in grade_levels if id == grade_level_id), "غير معروف")
            
            query.edit_message_text(
                f"اخترت: {grade_name}\n\n"
                "هل تريد اختبار على فصل أو درس محدد؟",
                reply_markup=get_chapters_keyboard(grade_level_id, for_quiz=True)
            )
            return QUIZ_CHAPTER
    
    # اختيار الفصل للاختبار
    elif data.startswith("quiz_chapter_"):
        chapter_id = int(data.split("_")[-1])
        context.user_data["selected_chapter_id"] = chapter_id
        
        query.edit_message_text(
            "هل تريد اختبار على درس محدد؟",
            reply_markup=get_lessons_keyboard(chapter_id, for_quiz=True)
        )
        return QUIZ_LESSON
    
    # اختيار الدرس للاختبار
    elif data.startswith("quiz_lesson_"):
        lesson_id = int(data.split("_")[-1])
        context.user_data["selected_lesson_id"] = lesson_id
        return start_quiz_by_lesson(update, context)
    
    # العودة إلى اختيار نوع الاختبار
    elif data == "back_to_quiz_type":
        return show_quiz_types(update, context)
    
    # العودة إلى اختيار المرحلة الدراسية
    elif data == "back_to_grade_selection":
        return show_quiz_types(update, context)
    
    # العودة إلى اختيار الفصل
    elif data == "back_to_chapter_selection":
        grade_level_id = context.user_data.get("selected_grade_level_id")
        if grade_level_id:
            query.edit_message_text(
                "اختر الفصل:",
                reply_markup=get_chapters_keyboard(grade_level_id, for_quiz=True)
            )
            return QUIZ_CHAPTER
        else:
            return show_quiz_types(update, context)
    
    # معالجة إضافة المراحل والفصول والدروس
    elif data.startswith("grade_"):
        grade_level_id = int(data.split("_")[-1])
        context.user_data["selected_grade_level_id"] = grade_level_id
        
        grade_levels = QUIZ_DB.get_grade_levels()
        grade_name = next((name for id, name in grade_levels if id == grade_level_id), "غير معروف")
        
        query.edit_message_text(
            f"اخترت المرحلة الدراسية: {grade_name}\n\n"
            "اختر الفصل:",
            reply_markup=get_chapters_keyboard(grade_level_id)
        )
        return SELECT_CHAPTER
    
    elif data.startswith("chapter_"):
        chapter_id = int(data.split("_")[-1])
        context.user_data["selected_chapter_id"] = chapter_id
        
        query.edit_message_text(
            "اختر الدرس:",
            reply_markup=get_lessons_keyboard(chapter_id)
        )
        return SELECT_LESSON
    
    elif data == "back_to_grade_selection_admin":
        query.edit_message_text(
            "اختر المرحلة الدراسية:",
            reply_markup=get_grade_levels_keyboard()
        )
        return SELECT_GRADE_LEVEL
    
    elif data == "back_to_chapter_selection_admin":
        grade_level_id = context.user_data.get("selected_grade_level_id")
        if grade_level_id:
            query.edit_message_text(
                "اختر الفصل:",
                reply_markup=get_chapters_keyboard(grade_level_id)
            )
            return SELECT_CHAPTER
        else:
            query.edit_message_text(
                "اختر المرحلة الدراسية:",
                reply_markup=get_grade_levels_keyboard()
            )
            return SELECT_GRADE_LEVEL
    
    elif data == "back_to_structure":
        return show_structure_menu(update, context)
    
    # معالجة الإجابة على سؤال في الاختبار
    elif data.startswith("answer_"):
        return process_quiz_answer(update, context)
    
    # معالجة نهاية الاختبار
    elif data == "end_quiz":
        return end_quiz(update, context)
    elif data == "quiz_details":
        return show_quiz_details(update, context)
    
    # معالجة إضافة صورة للسؤال أو الخيارات
    elif data.startswith("add_question_image_"):
        return process_question_image_choice(update, context)
    elif data.startswith("add_option_images_"):
        return process_option_images_choice(update, context)
    
    # إذا لم يتم التعرف على البيانات
    query.edit_message_text(f"عذراً، حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى أو استخدام /start للبدء من جديد.")
    return MAIN_MENU

# وظائف قائمة الإدارة
def show_admin_menu(update: Update, context: CallbackContext):
    """عرض قائمة الإدارة."""
    query = update.callback_query
    query.edit_message_text("قائمة الإدارة:", reply_markup=get_admin_menu_keyboard())
    return ADMIN_MENU

def show_structure_menu(update: Update, context: CallbackContext):
    """عرض قائمة إدارة الهيكل التعليمي."""
    query = update.callback_query
    query.edit_message_text("إدارة الهيكل التعليمي:", reply_markup=get_structure_menu_keyboard())
    return MANAGE_STRUCTURE

def view_structure(update: Update, context: CallbackContext):
    """عرض الهيكل التعليمي الحالي."""
    query = update.callback_query
    
    # الحصول على المراحل الدراسية
    grade_levels = QUIZ_DB.get_grade_levels()
    
    if not grade_levels:
        query.edit_message_text(
            "لا توجد مراحل دراسية مضافة بعد.\n\n"
            "استخدم 'إضافة مرحلة دراسية' لإضافة مرحلة جديدة.",
            reply_markup=get_structure_menu_keyboard()
        )
        return MANAGE_STRUCTURE
    
    # بناء نص الهيكل
    structure_text = "📚 *الهيكل التعليمي الحالي:*\n\n"
    
    for grade_id, grade_name in grade_levels:
        structure_text += f"*{grade_name}*\n"
        
        # الحصول على الفصول لهذه المرحلة
        chapters = QUIZ_DB.get_chapters_by_grade(grade_id)
        
        if not chapters:
            structure_text += "   ├── (لا توجد فصول)\n"
        else:
            for i, (chapter_id, chapter_name) in enumerate(chapters):
                is_last_chapter = i == len(chapters) - 1
                
                if is_last_chapter:
                    structure_text += f"   └── {chapter_name}\n"
                else:
                    structure_text += f"   ├── {chapter_name}\n"
                
                # الحصول على الدروس لهذا الفصل
                lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
                
                if not lessons:
                    if is_last_chapter:
                        structure_text += "        └── (لا توجد دروس)\n"
                    else:
                        structure_text += "        ├── (لا توجد دروس)\n"
                else:
                    for j, (lesson_id, lesson_name) in enumerate(lessons):
                        is_last_lesson = j == len(lessons) - 1
                        
                        if is_last_chapter:
                            prefix = "        "
                        else:
                            prefix = "   |    "
                        
                        if is_last_lesson:
                            structure_text += f"{prefix}└── {lesson_name}\n"
                        else:
                            structure_text += f"{prefix}├── {lesson_name}\n"
        
        structure_text += "\n"
    
    query.edit_message_text(
        structure_text,
        reply_markup=get_structure_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return MANAGE_STRUCTURE

def start_add_grade_level(update: Update, context: CallbackContext):
    """بدء عملية إضافة مرحلة دراسية جديدة."""
    query = update.callback_query
    
    query.edit_message_text(
        "🏫 *إضافة مرحلة دراسية جديدة*\n\n"
        "أرسل اسم المرحلة الدراسية الجديدة:",
        parse_mode=ParseMode.MARKDOWN
    )
    return ADD_GRADE_LEVEL

def add_grade_level(update: Update, context: CallbackContext):
    """إضافة مرحلة دراسية جديدة."""
    grade_level_name = update.message.text.strip()
    
    if not grade_level_name:
        update.message.reply_text(
            "⚠️ الاسم لا يمكن أن يكون فارغاً. الرجاء إرسال اسم صحيح للمرحلة الدراسية:"
        )
        return ADD_GRADE_LEVEL
    
    # إضافة المرحلة الدراسية إلى قاعدة البيانات
    grade_level_id = QUIZ_DB.add_grade_level(grade_level_name)
    
    if grade_level_id:
        update.message.reply_text(
            f"✅ تمت إضافة المرحلة الدراسية '{grade_level_name}' بنجاح!",
            reply_markup=get_structure_menu_keyboard()
        )
    else:
        update.message.reply_text(
            "❌ حدث خطأ أثناء إضافة المرحلة الدراسية. الرجاء المحاولة مرة أخرى.",
            reply_markup=get_structure_menu_keyboard()
        )
    
    return MANAGE_STRUCTURE

def start_add_chapter(update: Update, context: CallbackContext):
    """بدء عملية إضافة فصل جديد."""
    query = update.callback_query
    
    # الحصول على المراحل الدراسية
    grade_levels = QUIZ_DB.get_grade_levels()
    
    if not grade_levels:
        query.edit_message_text(
            "⚠️ لا توجد مراحل دراسية مضافة بعد.\n\n"
            "يجب إضافة مرحلة دراسية أولاً قبل إضافة فصل.",
            reply_markup=get_structure_menu_keyboard()
        )
        return MANAGE_STRUCTURE
    
    query.edit_message_text(
        "📚 *إضافة فصل جديد*\n\n"
        "اختر المرحلة الدراسية التي تريد إضافة الفصل إليها:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_grade_levels_keyboard()
    )
    
    context.user_data["adding_chapter"] = True
    return SELECT_GRADE_LEVEL

def add_chapter(update: Update, context: CallbackContext):
    """إضافة فصل جديد."""
    chapter_name = update.message.text.strip()
    grade_level_id = context.user_data.get("selected_grade_level_id")
    
    if not chapter_name:
        update.message.reply_text(
            "⚠️ الاسم لا يمكن أن يكون فارغاً. الرجاء إرسال اسم صحيح للفصل:"
        )
        return ADD_CHAPTER
    
    if not grade_level_id:
        update.message.reply_text(
            "⚠️ لم يتم تحديد المرحلة الدراسية. الرجاء بدء العملية من جديد.",
            reply_markup=get_structure_menu_keyboard()
        )
        return MANAGE_STRUCTURE
    
    # إضافة الفصل إلى قاعدة البيانات
    chapter_id = QUIZ_DB.add_chapter(grade_level_id, chapter_name)
    
    if chapter_id:
        # الحصول على اسم المرحلة الدراسية
        grade_levels = QUIZ_DB.get_grade_levels()
        grade_name = next((name for id, name in grade_levels if id == grade_level_id), "غير معروف")
        
        update.message.reply_text(
            f"✅ تمت إضافة الفصل '{chapter_name}' إلى المرحلة '{grade_name}' بنجاح!",
            reply_markup=get_structure_menu_keyboard()
        )
    else:
        update.message.reply_text(
            "❌ حدث خطأ أثناء إضافة الفصل. الرجاء المحاولة مرة أخرى.",
            reply_markup=get_structure_menu_keyboard()
        )
    
    # تنظيف بيانات المستخدم
    if "selected_grade_level_id" in context.user_data:
        del context.user_data["selected_grade_level_id"]
    if "adding_chapter" in context.user_data:
        del context.user_data["adding_chapter"]
    
    return MANAGE_STRUCTURE

def start_add_lesson(update: Update, context: CallbackContext):
    """بدء عملية إضافة درس جديد."""
    query = update.callback_query
    
    # الحصول على المراحل الدراسية
    grade_levels = QUIZ_DB.get_grade_levels()
    
    if not grade_levels:
        query.edit_message_text(
            "⚠️ لا توجد مراحل دراسية مضافة بعد.\n\n"
            "يجب إضافة مرحلة دراسية وفصل أولاً قبل إضافة درس.",
            reply_markup=get_structure_menu_keyboard()
        )
        return MANAGE_STRUCTURE
    
    query.edit_message_text(
        "📖 *إضافة درس جديد*\n\n"
        "اختر المرحلة الدراسية أولاً:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_grade_levels_keyboard()
    )
    
    context.user_data["adding_lesson"] = True
    return SELECT_GRADE_LEVEL

def process_grade_selection_for_lesson(update: Update, context: CallbackContext):
    """معالجة اختيار المرحلة الدراسية عند إضافة درس."""
    query = update.callback_query
    grade_level_id = int(query.data.split("_")[-1])
    context.user_data["selected_grade_level_id"] = grade_level_id
    
    # الحصول على الفصول لهذه المرحلة
    chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    
    if not chapters:
        query.edit_message_text(
            "⚠️ لا توجد فصول مضافة لهذه المرحلة الدراسية بعد.\n\n"
            "يجب إضافة فصل أولاً قبل إضافة درس.",
            reply_markup=get_structure_menu_keyboard()
        )
        return MANAGE_STRUCTURE
    
    query.edit_message_text(
        "📖 *إضافة درس جديد*\n\n"
        "اختر الفصل الذي تريد إضافة الدرس إليه:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_chapters_keyboard(grade_level_id)
    )
    
    return SELECT_CHAPTER

def add_lesson(update: Update, context: CallbackContext):
    """إضافة درس جديد."""
    lesson_name = update.message.text.strip()
    chapter_id = context.user_data.get("selected_chapter_id")
    
    if not lesson_name:
        update.message.reply_text(
            "⚠️ الاسم لا يمكن أن يكون فارغاً. الرجاء إرسال اسم صحيح للدرس:"
        )
        return ADD_LESSON
    
    if not chapter_id:
        update.message.reply_text(
            "⚠️ لم يتم تحديد الفصل. الرجاء بدء العملية من جديد.",
            reply_markup=get_structure_menu_keyboard()
        )
        return MANAGE_STRUCTURE
    
    # إضافة الدرس إلى قاعدة البيانات
    lesson_id = QUIZ_DB.add_lesson(chapter_id, lesson_name)
    
    if lesson_id:
        update.message.reply_text(
            f"✅ تمت إضافة الدرس '{lesson_name}' بنجاح!",
            reply_markup=get_structure_menu_keyboard()
        )
    else:
        update.message.reply_text(
            "❌ حدث خطأ أثناء إضافة الدرس. الرجاء المحاولة مرة أخرى.",
            reply_markup=get_structure_menu_keyboard()
        )
    
    # تنظيف بيانات المستخدم
    if "selected_grade_level_id" in context.user_data:
        del context.user_data["selected_grade_level_id"]
    if "selected_chapter_id" in context.user_data:
        del context.user_data["selected_chapter_id"]
    if "adding_lesson" in context.user_data:
        del context.user_data["adding_lesson"]
    
    return MANAGE_STRUCTURE

def process_chapter_selection_for_lesson(update: Update, context: CallbackContext):
    """معالجة اختيار الفصل عند إضافة درس."""
    query = update.callback_query
    chapter_id = int(query.data.split("_")[-1])
    context.user_data["selected_chapter_id"] = chapter_id
    
    query.edit_message_text(
        "📖 *إضافة درس جديد*\n\n"
        "أرسل اسم الدرس الجديد:",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return ADD_LESSON

# وظائف إضافة الأسئلة
def start_add_question(update: Update, context: CallbackContext):
    """بدء عملية إضافة سؤال جديد."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # تهيئة بيانات السؤال الجديد
    context.user_data["new_question"] = {}
    
    query.edit_message_text(
        "➕ *إضافة سؤال جديد*\n\n"
        "أرسل نص السؤال:",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return ADD_QUESTION

def add_question_text(update: Update, context: CallbackContext):
    """إضافة نص السؤال."""
    question_text = update.message.text.strip()
    
    if not question_text:
        update.message.reply_text("⚠️ نص السؤال لا يمكن أن يكون فارغاً. الرجاء إرسال نص السؤال:")
        return ADD_QUESTION
    
    # حفظ نص السؤال
    context.user_data["new_question"]["text"] = question_text
    
    # سؤال المستخدم عن المرحلة الدراسية
    grade_levels = QUIZ_DB.get_grade_levels()
    
    if not grade_levels:
        update.message.reply_text(
            "⚠️ لا توجد مراحل دراسية مضافة بعد.\n\n"
            "سيتم إضافة السؤال بدون تحديد المرحلة الدراسية.\n\n"
            "الآن، أرسل خيارات الإجابة، كل خيار في سطر منفصل:"
        )
        return ADD_QUESTION_OPTIONS
    
    keyboard = []
    for grade_id, grade_name in grade_levels:
        keyboard.append([InlineKeyboardButton(grade_name, callback_data=f"add_q_grade_{grade_id}")])
    
    keyboard.append([InlineKeyboardButton("تخطي", callback_data="add_q_grade_skip")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        "اختر المرحلة الدراسية للسؤال:",
        reply_markup=reply_markup
    )
    
    return ADD_QUESTION_GRADE_LEVEL

def add_question_grade_level(update: Update, context: CallbackContext):
    """إضافة المرحلة الدراسية للسؤال."""
    query = update.callback_query
    data = query.data
    
    if data == "add_q_grade_skip":
        context.user_data["new_question"]["grade_level_id"] = None
        context.user_data["new_question"]["chapter_id"] = None
        context.user_data["new_question"]["lesson_id"] = None
        
        query.edit_message_text(
            "تم تخطي تحديد المرحلة الدراسية.\n\n"
            "الآن، أرسل خيارات الإجابة، كل خيار في سطر منفصل:"
        )
        return ADD_QUESTION_OPTIONS
    
    grade_level_id = int(data.split("_")[-1])
    context.user_data["new_question"]["grade_level_id"] = grade_level_id
    
    # الحصول على الفصول لهذه المرحلة
    chapters = QUIZ_DB.get_chapters_by_grade(grade_level_id)
    
    if not chapters:
        context.user_data["new_question"]["chapter_id"] = None
        context.user_data["new_question"]["lesson_id"] = None
        
        query.edit_message_text(
            "لا توجد فصول مضافة لهذه المرحلة الدراسية بعد.\n\n"
            "سيتم إضافة السؤال بدون تحديد الفصل والدرس.\n\n"
            "الآن، أرسل خيارات الإجابة، كل خيار في سطر منفصل:"
        )
        return ADD_QUESTION_OPTIONS
    
    keyboard = []
    for chapter_id, chapter_name in chapters:
        keyboard.append([InlineKeyboardButton(chapter_name, callback_data=f"add_q_chapter_{chapter_id}")])
    
    keyboard.append([InlineKeyboardButton("تخطي", callback_data="add_q_chapter_skip")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        "اختر الفصل للسؤال:",
        reply_markup=reply_markup
    )
    
    return ADD_QUESTION_CHAPTER

def add_question_chapter(update: Update, context: CallbackContext):
    """إضافة الفصل للسؤال."""
    query = update.callback_query
    data = query.data
    
    if data == "add_q_chapter_skip":
        context.user_data["new_question"]["chapter_id"] = None
        context.user_data["new_question"]["lesson_id"] = None
        
        query.edit_message_text(
            "تم تخطي تحديد الفصل.\n\n"
            "الآن، أرسل خيارات الإجابة، كل خيار في سطر منفصل:"
        )
        return ADD_QUESTION_OPTIONS
    
    chapter_id = int(data.split("_")[-1])
    context.user_data["new_question"]["chapter_id"] = chapter_id
    
    # الحصول على الدروس لهذا الفصل
    lessons = QUIZ_DB.get_lessons_by_chapter(chapter_id)
    
    if not lessons:
        context.user_data["new_question"]["lesson_id"] = None
        
        query.edit_message_text(
            "لا توجد دروس مضافة لهذا الفصل بعد.\n\n"
            "سيتم إضافة السؤال بدون تحديد الدرس.\n\n"
            "الآن، أرسل خيارات الإجابة، كل خيار في سطر منفصل:"
        )
        return ADD_QUESTION_OPTIONS
    
    keyboard = []
    for lesson_id, lesson_name in lessons:
        keyboard.append([InlineKeyboardButton(lesson_name, callback_data=f"add_q_lesson_{lesson_id}")])
    
    keyboard.append([InlineKeyboardButton("تخطي", callback_data="add_q_lesson_skip")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        "اختر الدرس للسؤال:",
        reply_markup=reply_markup
    )
    
    return ADD_QUESTION_LESSON

def add_question_lesson(update: Update, context: CallbackContext):
    """إضافة الدرس للسؤال."""
    query = update.callback_query
    data = query.data
    
    if data == "add_q_lesson_skip":
        context.user_data["new_question"]["lesson_id"] = None
    else:
        lesson_id = int(data.split("_")[-1])
        context.user_data["new_question"]["lesson_id"] = lesson_id
    
    query.edit_message_text(
        "الآن، أرسل خيارات الإجابة، كل خيار في سطر منفصل:"
    )
    
    return ADD_QUESTION_OPTIONS

def add_question_options(update: Update, context: CallbackContext):
    """إضافة خيارات الإجابة."""
    options_text = update.message.text.strip()
    options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
    
    if len(options) < 2:
        update.message.reply_text(
            "⚠️ يجب إرسال خيارين على الأقل. الرجاء إرسال خيارات الإجابة، كل خيار في سطر منفصل:"
        )
        return ADD_QUESTION_OPTIONS
    
    # حفظ خيارات الإجابة
    context.user_data["new_question"]["options"] = options
    
    # إنشاء لوحة مفاتيح لاختيار الإجابة الصحيحة
    keyboard = []
    for i, option in enumerate(options):
        display_text = option[:30] + "..." if len(option) > 30 else option
        keyboard.append([InlineKeyboardButton(f"{i+1}. {display_text}", callback_data=f"correct_{i}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        "اختر الإجابة الصحيحة:",
        reply_markup=reply_markup
    )
    
    return ADD_QUESTION_CORRECT

def add_question_correct(update: Update, context: CallbackContext):
    """إضافة الإجابة الصحيحة."""
    query = update.callback_query
    correct_index = int(query.data.split("_")[1])
    
    # حفظ مؤشر الإجابة الصحيحة
    context.user_data["new_question"]["correct_answer_index"] = correct_index
    
    query.edit_message_text(
        "أرسل شرح الإجابة (اختياري، يمكنك إرسال 'تخطي' للتخطي):"
    )
    
    return ADD_QUESTION_EXPLANATION

def add_question_explanation(update: Update, context: CallbackContext):
    """إضافة شرح الإجابة."""
    explanation = update.message.text.strip()
    
    # حفظ شرح الإجابة (أو None إذا تم التخطي)
    if explanation.lower() == "تخطي":
        context.user_data["new_question"]["explanation"] = None
    else:
        context.user_data["new_question"]["explanation"] = explanation
    
    # سؤال المستخدم عما إذا كان يريد إضافة صورة للسؤال
    update.message.reply_text(
        "هل تريد إضافة صورة للسؤال؟",
        reply_markup=get_yes_no_keyboard("add_question_image")
    )
    
    return ADD_QUESTION_IMAGE

def process_question_image_choice(update: Update, context: CallbackContext):
    """معالجة اختيار إضافة صورة للسؤال."""
    query = update.callback_query
    choice = query.data.split("_")[-1]
    
    if choice == "yes":
        query.edit_message_text(
            "أرسل الصورة التي تريد إضافتها للسؤال:"
        )
        context.user_data["waiting_for_question_image"] = True
        return ADD_QUESTION_IMAGE
    else:
        # لا توجد صورة للسؤال
        context.user_data["new_question"]["question_image_id"] = None
        
        # سؤال المستخدم عما إذا كان يريد إضافة صور للخيارات
        query.edit_message_text(
            "هل تريد إضافة صور للخيارات؟",
            reply_markup=get_yes_no_keyboard("add_option_images")
        )
        
        return ADD_OPTION_IMAGES

def add_question_image(update: Update, context: CallbackContext):
    """إضافة صورة للسؤال."""
    if not update.message.photo:
        update.message.reply_text(
            "⚠️ الرجاء إرسال صورة فقط. أرسل الصورة التي تريد إضافتها للسؤال:"
        )
        return ADD_QUESTION_IMAGE
    
    # الحصول على معرف الصورة من أكبر حجم متاح
    photo_id = update.message.photo[-1].file_id
    
    # حفظ معرف صورة السؤال
    context.user_data["new_question"]["question_image_id"] = photo_id
    
    # تنظيف حالة الانتظار
    if "waiting_for_question_image" in context.user_data:
        del context.user_data["waiting_for_question_image"]
    
    # سؤال المستخدم عما إذا كان يريد إضافة صور للخيارات
    update.message.reply_text(
        "هل تريد إضافة صور للخيارات؟",
        reply_markup=get_yes_no_keyboard("add_option_images")
    )
    
    return ADD_OPTION_IMAGES

def process_option_images_choice(update: Update, context: CallbackContext):
    """معالجة اختيار إضافة صور للخيارات."""
    query = update.callback_query
    choice = query.data.split("_")[-1]
    
    if choice == "yes":
        options = context.user_data["new_question"]["options"]
        
        # تهيئة قائمة لتخزين معرفات صور الخيارات
        context.user_data["new_question"]["option_image_ids"] = [None] * len(options)
        context.user_data["option_index"] = 0
        
        query.edit_message_text(
            f"أرسل صورة للخيار الأول: {options[0]}"
        )
        
        return ADD_OPTION_IMAGES
    else:
        # لا توجد صور للخيارات
        context.user_data["new_question"]["option_image_ids"] = None
        
        # حفظ السؤال في قاعدة البيانات
        return save_question(update, context)

def add_option_image(update: Update, context: CallbackContext):
    """إضافة صورة لخيار."""
    if not update.message.photo and update.message.text != "تخطي":
        update.message.reply_text(
            "⚠️ الرجاء إرسال صورة فقط أو كتابة 'تخطي' لتخطي هذا الخيار. أرسل الصورة:"
        )
        return ADD_OPTION_IMAGES
    
    options = context.user_data["new_question"]["options"]
    option_index = context.user_data["option_index"]
    
    # حفظ معرف صورة الخيار الحالي (أو None إذا تم التخطي)
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
        context.user_data["new_question"]["option_image_ids"][option_index] = photo_id
    
    # الانتقال إلى الخيار التالي أو حفظ السؤال
    option_index += 1
    if option_index < len(options):
        context.user_data["option_index"] = option_index
        update.message.reply_text(
            f"أرسل صورة للخيار {option_index + 1}: {options[option_index]}\n\n"
            "(أرسل 'تخطي' لتخطي هذا الخيار)"
        )
        return ADD_OPTION_IMAGES
    else:
        # تم الانتهاء من إضافة صور الخيارات
        return save_question(update, context)

def save_question(update: Update, context: CallbackContext):
    """حفظ السؤال في قاعدة البيانات."""
    new_question = context.user_data["new_question"]
    
    # استخراج بيانات السؤال
    question_text = new_question["text"]
    options = new_question["options"]
    correct_answer_index = new_question["correct_answer_index"]
    explanation = new_question.get("explanation")
    grade_level_id = new_question.get("grade_level_id")
    chapter_id = new_question.get("chapter_id")
    lesson_id = new_question.get("lesson_id")
    question_image_id = new_question.get("question_image_id")
    option_image_ids = new_question.get("option_image_ids")
    
    # إضافة السؤال إلى قاعدة البيانات
    question_id = QUIZ_DB.add_question(
        question_text, options, correct_answer_index, explanation,
        grade_level_id, chapter_id, lesson_id,
        question_image_id, option_image_ids
    )
    
    if question_id:
        # تحديد نوع الرسالة (نص أو صورة)
        if "callback_query" in update:
            query = update.callback_query
            query.edit_message_text(
                "✅ تم حفظ السؤال بنجاح!\n\n"
                "هل تريد إضافة سؤال آخر؟",
                reply_markup=get_yes_no_keyboard("add_another_question")
            )
        else:
            update.message.reply_text(
                "✅ تم حفظ السؤال بنجاح!\n\n"
                "هل تريد إضافة سؤال آخر؟",
                reply_markup=get_yes_no_keyboard("add_another_question")
            )
    else:
        # تحديد نوع الرسالة (نص أو صورة)
        if "callback_query" in update:
            query = update.callback_query
            query.edit_message_text(
                "❌ حدث خطأ أثناء حفظ السؤال. الرجاء المحاولة مرة أخرى.",
                reply_markup=get_admin_menu_keyboard()
            )
        else:
            update.message.reply_text(
                "❌ حدث خطأ أثناء حفظ السؤال. الرجاء المحاولة مرة أخرى.",
                reply_markup=get_admin_menu_keyboard()
            )
    
    # تنظيف بيانات المستخدم
    if "new_question" in context.user_data:
        del context.user_data["new_question"]
    if "option_index" in context.user_data:
        del context.user_data["option_index"]
    
    return ADMIN_MENU

# وظائف الاختبارات
def show_quiz_types(update: Update, context: CallbackContext):
    """عرض أنواع الاختبارات المتاحة."""
    query = update.callback_query
    
    query.edit_message_text(
        "📚 *اختر نوع الاختبار:*\n\n"
        "• اختر المرحلة الدراسية للاختبار\n"
        "• أو اختر 'تحصيلي عام' لاختبار من جميع المراحل\n"
        "• أو اختر 'مراجعة الأخطاء' لمراجعة الأسئلة التي أخطأت فيها سابقاً",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_quiz_type_keyboard()
    )
    
    return QUIZ_TYPE

def select_quiz_timer(update: Update, context: CallbackContext):
    """اختيار مدة الاختبار."""
    query = update.callback_query
    
    query.edit_message_text(
        "⏱️ *اختر مدة الاختبار:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_timer_keyboard()
    )
    
    return QUIZ_TIMER

def start_comprehensive_quiz(update: Update, context: CallbackContext):
    """بدء اختبار تحصيلي عام (من جميع المراحل)."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # تهيئة بيانات الاختبار
    quiz_data[user_id] = {
        "questions": [],
        "current_index": 0,
        "correct_count": 0,
        "quiz_id": None,
        "timer_minutes": context.user_data.get("timer_minutes", 0)
    }
    
    # إنشاء اختبار جديد في قاعدة البيانات
    quiz_id = QUIZ_DB.start_quiz(user_id, "comprehensive")
    quiz_data[user_id]["quiz_id"] = quiz_id
    
    # تعيين المؤقت إذا كان مطلوباً
    if quiz_data[user_id]["timer_minutes"] > 0:
        end_time = datetime.now() + timedelta(minutes=quiz_data[user_id]["timer_minutes"])
        quiz_data[user_id]["end_time"] = end_time
    
    # الحصول على 10 أسئلة عشوائية
    for _ in range(10):
        question = QUIZ_DB.get_random_question(exclude_ids=[q["id"] for q in quiz_data[user_id]["questions"]])
        if question:
            quiz_data[user_id]["questions"].append(question)
    
    if not quiz_data[user_id]["questions"]:
        query.edit_message_text(
            "⚠️ لا توجد أسئلة متاحة حالياً. الرجاء إضافة أسئلة أولاً.",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU
    
    # عرض السؤال الأول
    return show_quiz_question(update, context)

def start_review_quiz(update: Update, context: CallbackContext):
    """بدء اختبار مراجعة الأسئلة التي أخطأ فيها المستخدم سابقاً."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # الحصول على الأسئلة التي أخطأ فيها المستخدم
    incorrect_questions = QUIZ_DB.get_incorrect_questions(user_id)
    
    if not incorrect_questions:
        query.edit_message_text(
            "لا توجد أسئلة سابقة أخطأت فيها. جرب نوعاً آخر من الاختبارات.",
            reply_markup=get_quiz_type_keyboard()
        )
        return QUIZ_TYPE
    
    # تهيئة بيانات الاختبار
    quiz_data[user_id] = {
        "questions": incorrect_questions[:10],  # أخذ أول 10 أسئلة كحد أقصى
        "current_index": 0,
        "correct_count": 0,
        "quiz_id": None,
        "timer_minutes": context.user_data.get("timer_minutes", 0)
    }
    
    # إنشاء اختبار جديد في قاعدة البيانات
    quiz_id = QUIZ_DB.start_quiz(user_id, "review", total_questions=len(quiz_data[user_id]["questions"]))
    quiz_data[user_id]["quiz_id"] = quiz_id
    
    # تعيين المؤقت إذا كان مطلوباً
    if quiz_data[user_id]["timer_minutes"] > 0:
        end_time = datetime.now() + timedelta(minutes=quiz_data[user_id]["timer_minutes"])
        quiz_data[user_id]["end_time"] = end_time
    
    # عرض السؤال الأول
    return show_quiz_question(update, context)

def start_quiz_by_lesson(update: Update, context: CallbackContext):
    """بدء اختبار حسب درس محدد."""
    query = update.callback_query
    user_id = query.from_user.id
    
    lesson_id = context.user_data.get("selected_lesson_id")
    chapter_id = context.user_data.get("selected_chapter_id")
    grade_level_id = context.user_data.get("selected_grade_level_id")
    
    # الحصول على الأسئلة حسب الدرس
    questions = QUIZ_DB.get_questions_by_lesson(lesson_id)
    
    if not questions:
        query.edit_message_text(
            "⚠️ لا توجد أسئلة متاحة لهذا الدرس. الرجاء إضافة أسئلة أولاً.",
            reply_markup=get_quiz_type_keyboard()
        )
        return QUIZ_TYPE
    
    # خلط الأسئلة وأخذ 10 كحد أقصى
    random.shuffle(questions)
    questions = questions[:10]
    
    # تهيئة بيانات الاختبار
    quiz_data[user_id] = {
        "questions": questions,
        "current_index": 0,
        "correct_count": 0,
        "quiz_id": None,
        "timer_minutes": context.user_data.get("timer_minutes", 0)
    }
    
    # إنشاء اختبار جديد في قاعدة البيانات
    quiz_id = QUIZ_DB.start_quiz(
        user_id, "lesson",
        grade_level_id=grade_level_id,
        chapter_id=chapter_id,
        lesson_id=lesson_id,
        total_questions=len(questions)
    )
    quiz_data[user_id]["quiz_id"] = quiz_id
    
    # تعيين المؤقت إذا كان مطلوباً
    if quiz_data[user_id]["timer_minutes"] > 0:
        end_time = datetime.now() + timedelta(minutes=quiz_data[user_id]["timer_minutes"])
        quiz_data[user_id]["end_time"] = end_time
    
    # عرض السؤال الأول
    return show_quiz_question(update, context)

def show_quiz_question(update: Update, context: CallbackContext):
    """عرض سؤال في الاختبار."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in quiz_data:
        query.edit_message_text(
            "⚠️ حدث خطأ في الاختبار. الرجاء المحاولة مرة أخرى.",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU
    
    # التحقق من انتهاء المؤقت
    if "end_time" in quiz_data[user_id] and datetime.now() >= quiz_data[user_id]["end_time"]:
        return end_quiz_by_timeout(update, context)
    
    current_index = quiz_data[user_id]["current_index"]
    questions = quiz_data[user_id]["questions"]
    
    if current_index >= len(questions):
        return end_quiz(update, context)
    
    question = questions[current_index]
    options = question["options"]
    
    # إنشاء لوحة مفاتيح للخيارات
    keyboard = []
    for i, option in enumerate(options):
        keyboard.append([InlineKeyboardButton(f"{i+1}. {option}", callback_data=f"answer_{i}")])
    
    # إضافة زر لإنهاء الاختبار
    keyboard.append([InlineKeyboardButton("🛑 إنهاء الاختبار", callback_data="end_quiz")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # إعداد نص السؤال
    question_text = (
        f"*السؤال {current_index + 1} من {len(questions)}*\n\n"
        f"{question['question']}"
    )
    
    # إضافة المؤقت إذا كان مطلوباً
    if "end_time" in quiz_data[user_id]:
        remaining_seconds = int((quiz_data[user_id]["end_time"] - datetime.now()).total_seconds())
        if remaining_seconds > 0:
            question_text += f"\n\n⏱️ الوقت المتبقي: {format_time(remaining_seconds)}"
    
    # عرض السؤال مع أو بدون صورة
    if question.get("question_image_id"):
        # حذف الرسالة السابقة إذا كانت موجودة
        if "last_message_id" in quiz_data[user_id]:
            try:
                context.bot.delete_message(
                    chat_id=query.message.chat_id,
                    message_id=quiz_data[user_id]["last_message_id"]
                )
            except:
                pass
        
        # إرسال صورة السؤال مع النص
        message = context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=question["question_image_id"],
            caption=question_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        quiz_data[user_id]["last_message_id"] = message.message_id
        
        # حذف رسالة الاستعلام الأصلية
        try:
            query.delete_message()
        except:
            pass
    else:
        # تحديث الرسالة الحالية بالسؤال الجديد
        query.edit_message_text(
            question_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    return QUIZ_QUESTION

def process_quiz_answer(update: Update, context: CallbackContext):
    """معالجة إجابة المستخدم على سؤال في الاختبار."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in quiz_data:
        query.edit_message_text(
            "⚠️ حدث خطأ في الاختبار. الرجاء المحاولة مرة أخرى.",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU
    
    # التحقق من انتهاء المؤقت
    if "end_time" in quiz_data[user_id] and datetime.now() >= quiz_data[user_id]["end_time"]:
        return end_quiz_by_timeout(update, context)
    
    # استخراج مؤشر الإجابة المختارة
    answer_index = int(query.data.split("_")[1])
    
    current_index = quiz_data[user_id]["current_index"]
    question = quiz_data[user_id]["questions"][current_index]
    
    # التحقق من صحة الإجابة
    is_correct = (answer_index == question["correct_answer"])
    
    # تسجيل الإجابة في قاعدة البيانات
    if quiz_data[user_id]["quiz_id"]:
        QUIZ_DB.record_answer(
            quiz_data[user_id]["quiz_id"],
            question["id"],
            answer_index,
            is_correct
        )
    
    # تحديث عدد الإجابات الصحيحة
    if is_correct:
        quiz_data[user_id]["correct_count"] += 1
    
    # الانتقال إلى السؤال التالي
    quiz_data[user_id]["current_index"] += 1
    
    # عرض نتيجة الإجابة
    correct_answer_index = question["correct_answer"]
    correct_answer = question["options"][correct_answer_index]
    
    result_text = (
        f"{'✅ إجابة صحيحة!' if is_correct else '❌ إجابة خاطئة!'}\n\n"
        f"السؤال: {question['question']}\n\n"
        f"إجابتك: {question['options'][answer_index]}\n"
        f"الإجابة الصحيحة: {correct_answer}"
    )
    
    # إضافة الشرح إذا كان متاحاً
    if question.get("explanation"):
        result_text += f"\n\nالشرح: {question['explanation']}"
    
    # إضافة المؤقت إذا كان مطلوباً
    if "end_time" in quiz_data[user_id]:
        remaining_seconds = int((quiz_data[user_id]["end_time"] - datetime.now()).total_seconds())
        if remaining_seconds > 0:
            result_text += f"\n\n⏱️ الوقت المتبقي: {format_time(remaining_seconds)}"
    
    # إنشاء لوحة مفاتيح للانتقال إلى السؤال التالي
    keyboard = [[InlineKeyboardButton("التالي ⬅️", callback_data="next_question")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # عرض النتيجة
    if question.get("question_image_id"):
        # حذف الرسالة السابقة إذا كانت موجودة
        if "last_message_id" in quiz_data[user_id]:
            try:
                context.bot.delete_message(
                    chat_id=query.message.chat_id,
                    message_id=quiz_data[user_id]["last_message_id"]
                )
            except:
                pass
        
        # إرسال صورة السؤال مع نتيجة الإجابة
        message = context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=question["question_image_id"],
            caption=result_text,
            reply_markup=reply_markup
        )
        quiz_data[user_id]["last_message_id"] = message.message_id
        
        # حذف رسالة الاستعلام الأصلية
        try:
            query.delete_message()
        except:
            pass
    else:
        # تحديث الرسالة الحالية بنتيجة الإجابة
        query.edit_message_text(
            result_text,
            reply_markup=reply_markup
        )
    
    # إذا كان هذا هو السؤال الأخير، سيتم إنهاء الاختبار عند الضغط على "التالي"
    if quiz_data[user_id]["current_index"] >= len(quiz_data[user_id]["questions"]):
        return QUIZ_RESULT
    
    return QUIZ_QUESTION

def end_quiz_by_timeout(update: Update, context: CallbackContext):
    """إنهاء الاختبار بسبب انتهاء الوقت."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # تسجيل نتيجة الاختبار في قاعدة البيانات
    if quiz_data[user_id]["quiz_id"]:
        QUIZ_DB.end_quiz(
            quiz_data[user_id]["quiz_id"],
            quiz_data[user_id]["correct_count"]
        )
    
    # حساب النتيجة
    correct_count = quiz_data[user_id]["correct_count"]
    total_questions = len(quiz_data[user_id]["questions"])
    answered_questions = quiz_data[user_id]["current_index"]
    percentage = (correct_count / total_questions) * 100 if total_questions > 0 else 0
    
    # إعداد نص النتيجة
    result_text = (
        "⏱️ *انتهى الوقت!*\n\n"
        f"أجبت على {answered_questions} من {total_questions} سؤال\n"
        f"الإجابات الصحيحة: {correct_count} ({percentage:.1f}%)\n\n"
    )
    
    # إضافة تقييم الأداء
    if percentage >= 90:
        result_text += "🌟 ممتاز! أداء رائع!"
    elif percentage >= 75:
        result_text += "👍 جيد جداً! استمر في التحسن!"
    elif percentage >= 50:
        result_text += "👌 جيد! يمكنك تحسين أدائك بمزيد من الممارسة."
    else:
        result_text += "📚 تحتاج إلى مزيد من المراجعة. لا تستسلم!"
    
    # إنشاء لوحة مفاتيح للعودة إلى القائمة الرئيسية أو عرض تفاصيل الاختبار
    keyboard = [
        [InlineKeyboardButton("📊 عرض التقرير المفصل", callback_data="quiz_details")],
        [InlineKeyboardButton("🔙 العودة إلى القائمة الرئيسية", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # عرض النتيجة
    query.edit_message_text(
        result_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    return QUIZ_RESULT

def end_quiz(update: Update, context: CallbackContext):
    """إنهاء الاختبار وعرض النتيجة."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in quiz_data:
        query.edit_message_text(
            "⚠️ حدث خطأ في الاختبار. الرجاء المحاولة مرة أخرى.",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU
    
    # تسجيل نتيجة الاختبار في قاعدة البيانات
    if quiz_data[user_id]["quiz_id"]:
        QUIZ_DB.end_quiz(
            quiz_data[user_id]["quiz_id"],
            quiz_data[user_id]["correct_count"]
        )
    
    # حساب النتيجة
    correct_count = quiz_data[user_id]["correct_count"]
    total_questions = len(quiz_data[user_id]["questions"])
    percentage = (correct_count / total_questions) * 100 if total_questions > 0 else 0
    
    # حساب الوقت المستغرق إذا كان هناك مؤقت
    time_text = ""
    if "end_time" in quiz_data[user_id]:
        if datetime.now() < quiz_data[user_id]["end_time"]:
            time_taken = quiz_data[user_id]["timer_minutes"] * 60 - int((quiz_data[user_id]["end_time"] - datetime.now()).total_seconds())
            time_text = f"الوقت المستغرق: {format_time(time_taken)}\n"
    
    # إعداد نص النتيجة
    result_text = (
        "🏁 *انتهى الاختبار!*\n\n"
        f"الإجابات الصحيحة: {correct_count} من {total_questions}\n"
        f"النسبة المئوية: {percentage:.1f}%\n"
        f"{time_text}\n"
    )
    
    # إضافة تقييم الأداء
    if percentage >= 90:
        result_text += "🌟 ممتاز! أداء رائع!"
    elif percentage >= 75:
        result_text += "👍 جيد جداً! استمر في التحسن!"
    elif percentage >= 50:
        result_text += "👌 جيد! يمكنك تحسين أدائك بمزيد من الممارسة."
    else:
        result_text += "📚 تحتاج إلى مزيد من المراجعة. لا تستسلم!"
    
    # إنشاء لوحة مفاتيح للعودة إلى القائمة الرئيسية أو عرض تفاصيل الاختبار
    keyboard = [
        [InlineKeyboardButton("📊 عرض التقرير المفصل", callback_data="quiz_details")],
        [InlineKeyboardButton("🔙 العودة إلى القائمة الرئيسية", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # عرض النتيجة
    query.edit_message_text(
        result_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    return QUIZ_RESULT

def show_quiz_details(update: Update, context: CallbackContext):
    """عرض تفاصيل الاختبار."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in quiz_data or not quiz_data[user_id]["quiz_id"]:
        query.edit_message_text(
            "⚠️ لا توجد تفاصيل متاحة لهذا الاختبار.",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU
    
    # الحصول على تفاصيل الاختبار
    quiz_id = quiz_data[user_id]["quiz_id"]
    quiz_details = QUIZ_DB.get_quiz_details(quiz_id)
    
    if not quiz_details:
        query.edit_message_text(
            "⚠️ لا توجد تفاصيل متاحة لهذا الاختبار.",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU
    
    # استخراج بيانات الاختبار
    quiz_type = quiz_details[1]
    grade_level_name = quiz_details[10] or "غير محدد"
    chapter_name = quiz_details[11] or "غير محدد"
    lesson_name = quiz_details[12] or "غير محدد"
    start_time = quiz_details[5]
    end_time = quiz_details[6]
    total_questions = quiz_details[7]
    correct_answers = quiz_details[8] or 0
    time_taken = quiz_details[9] or 0
    
    # تنسيق نوع الاختبار
    quiz_type_text = {
        "random": "عشوائي",
        "chapter": "حسب الفصل",
        "lesson": "حسب الدرس",
        "review": "مراجعة الأخطاء",
        "comprehensive": "تحصيلي عام",
        "grade_level": "حسب المرحلة الدراسية"
    }.get(quiz_type, quiz_type)
    
    # حساب النسبة المئوية
    percentage = (correct_answers / total_questions) * 100 if total_questions > 0 else 0
    
    # إعداد نص التفاصيل
    details_text = (
        "📊 *تقرير الاختبار المفصل*\n\n"
        f"نوع الاختبار: {quiz_type_text}\n"
        f"المرحلة الدراسية: {grade_level_name}\n"
    )
    
    if quiz_type in ["chapter", "lesson"]:
        details_text += f"الفصل: {chapter_name}\n"
    
    if quiz_type == "lesson":
        details_text += f"الدرس: {lesson_name}\n"
    
    details_text += (
        f"\nتاريخ الاختبار: {start_time.strftime('%Y-%m-%d %H:%M')}\n"
        f"الوقت المستغرق: {format_time(time_taken)}\n\n"
        f"عدد الأسئلة: {total_questions}\n"
        f"الإجابات الصحيحة: {correct_answers}\n"
        f"النسبة المئوية: {percentage:.1f}%\n\n"
    )
    
    # إضافة تقييم الأداء
    if percentage >= 90:
        details_text += "🌟 ممتاز! أداء رائع!"
    elif percentage >= 75:
        details_text += "👍 جيد جداً! استمر في التحسن!"
    elif percentage >= 50:
        details_text += "👌 جيد! يمكنك تحسين أدائك بمزيد من الممارسة."
    else:
        details_text += "📚 تحتاج إلى مزيد من المراجعة. لا تستسلم!"
    
    # الحصول على إجابات الاختبار
    quiz_answers = QUIZ_DB.get_quiz_answers(quiz_id)
    
    if quiz_answers:
        details_text += "\n\n*تفاصيل الإجابات:*\n"
        
        for i, answer in enumerate(quiz_answers):
            question_id = answer[0]
            user_answer_index = answer[1]
            is_correct = answer[2]
            question_text = answer[4]
            options = answer[5]
            correct_answer_index = answer[6]
            
            # تقصير نص السؤال إذا كان طويلاً
            short_question = question_text[:50] + "..." if len(question_text) > 50 else question_text
            
            details_text += (
                f"\n{i+1}. {short_question}\n"
                f"   {'✅' if is_correct else '❌'} إجابتك: {options[user_answer_index]}\n"
            )
            
            if not is_correct:
                details_text += f"   ✓ الإجابة الصحيحة: {options[correct_answer_index]}\n"
    
    # إنشاء لوحة مفاتيح للعودة إلى القائمة الرئيسية
    keyboard = [[InlineKeyboardButton("🔙 العودة إلى القائمة الرئيسية", callback_data="back_to_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # عرض التفاصيل
    query.edit_message_text(
        details_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    return QUIZ_RESULT

def show_quiz_history(update: Update, context: CallbackContext):
    """عرض سجل الاختبارات السابقة."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # الحصول على سجل الاختبارات
    quiz_history = QUIZ_DB.get_quiz_history(user_id)
    
    if not quiz_history:
        query.edit_message_text(
            "لا توجد اختبارات سابقة. جرب بدء اختبار جديد!",
            reply_markup=get_main_menu_keyboard()
        )
        return MAIN_MENU
    
    # إعداد نص السجل
    history_text = "📚 *سجل الاختبارات السابقة*\n\n"
    
    for i, quiz in enumerate(quiz_history):
        quiz_id = quiz[0]
        quiz_type = quiz[1]
        grade_level_id = quiz[2]
        chapter_id = quiz[3]
        lesson_id = quiz[4]
        start_time = quiz[5]
        total_questions = quiz[7]
        correct_answers = quiz[8] or 0
        
        # تنسيق نوع الاختبار
        quiz_type_text = {
            "random": "عشوائي",
            "chapter": "حسب الفصل",
            "lesson": "حسب الدرس",
            "review": "مراجعة الأخطاء",
            "comprehensive": "تحصيلي عام",
            "grade_level": "حسب المرحلة الدراسية"
        }.get(quiz_type, quiz_type)
        
        # حساب النسبة المئوية
        percentage = (correct_answers / total_questions) * 100 if total_questions > 0 else 0
        
        # إضافة معلومات الاختبار
        history_text += (
            f"{i+1}. *{quiz_type_text}* ({start_time.strftime('%Y-%m-%d %H:%M')})\n"
            f"   النتيجة: {correct_answers}/{total_questions} ({percentage:.1f}%)\n\n"
        )
    
    # إنشاء لوحة مفاتيح للعودة إلى القائمة الرئيسية
    keyboard = [[InlineKeyboardButton("🔙 العودة إلى القائمة الرئيسية", callback_data="back_to_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # عرض السجل
    query.edit_message_text(
        history_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    return QUIZ_HISTORY

# وظائف عرض وإدارة الأسئلة
def view_questions(update: Update, context: CallbackContext):
    """عرض الأسئلة المضافة."""
    query = update.callback_query
    
    # الحصول على المراحل الدراسية
    grade_levels = QUIZ_DB.get_grade_levels()
    
    if not grade_levels:
        # عرض جميع الأسئلة إذا لم تكن هناك مراحل دراسية
        questions = QUIZ_DB.get_all_questions()
        
        if not questions:
            query.edit_message_text(
                "لا توجد أسئلة مضافة بعد.",
                reply_markup=get_admin_menu_keyboard()
            )
            return ADMIN_MENU
        
        # عرض قائمة الأسئلة
        return show_question_list(update, context, questions)
    
    # عرض قائمة المراحل الدراسية للاختيار
    query.edit_message_text(
        "اختر المرحلة الدراسية لعرض الأسئلة:",
        reply_markup=get_grade_levels_keyboard()
    )
    
    return SELECT_GRADE_LEVEL

def show_question_list(update: Update, context: CallbackContext, questions):
    """عرض قائمة الأسئلة."""
    query = update.callback_query
    
    # إعداد نص قائمة الأسئلة
    questions_text = "📝 *قائمة الأسئلة*\n\n"
    
    for i, question in enumerate(questions):
        # تقصير نص السؤال إذا كان طويلاً
        short_question = question["question"][:50] + "..." if len(question["question"]) > 50 else question["question"]
        
        # إضافة رموز للإشارة إلى وجود صور
        has_image = "🖼️ " if question.get("question_image_id") else ""
        has_option_images = "🔢 " if question.get("option_image_ids") else ""
        
        questions_text += f"{i+1}. {has_image}{has_option_images}{short_question}\n"
    
    # إنشاء لوحة مفاتيح للعودة إلى قائمة الإدارة
    keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="back_to_admin")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # عرض القائمة
    query.edit_message_text(
        questions_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    return ADMIN_MENU

# وظيفة المعالجة الرئيسية
def main():
    """الوظيفة الرئيسية لتشغيل البوت."""
    # التحقق من وجود التوكن
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("يرجى تعيين TOKEN الخاص بك في ملف البوت.")
        return
    
    # إنشاء Updater
    updater = Updater(TOKEN)
    
    # الحصول على Dispatcher
    dp = updater.dispatcher
    
    # إنشاء محادثة للبوت
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(button_handler),
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(button_handler),
            ],
            MANAGE_STRUCTURE: [
                CallbackQueryHandler(button_handler),
            ],
            ADD_GRADE_LEVEL: [
                MessageHandler(Filters.text & ~Filters.command, add_grade_level),
            ],
            ADD_CHAPTER: [
                MessageHandler(Filters.text & ~Filters.command, add_chapter),
            ],
            ADD_LESSON: [
                MessageHandler(Filters.text & ~Filters.command, add_lesson),
            ],
            SELECT_GRADE_LEVEL: [
                CallbackQueryHandler(lambda u, c: process_grade_selection_for_lesson(u, c) if c.user_data.get("adding_lesson") else button_handler(u, c)),
            ],
            SELECT_CHAPTER: [
                CallbackQueryHandler(lambda u, c: process_chapter_selection_for_lesson(u, c) if c.user_data.get("adding_lesson") else button_handler(u, c)),
            ],
            SELECT_LESSON: [
                CallbackQueryHandler(button_handler),
            ],
            ADD_QUESTION: [
                MessageHandler(Filters.text & ~Filters.command, add_question_text),
            ],
            ADD_QUESTION_GRADE_LEVEL: [
                CallbackQueryHandler(add_question_grade_level, pattern=r"^add_q_grade_"),
            ],
            ADD_QUESTION_CHAPTER: [
                CallbackQueryHandler(add_question_chapter, pattern=r"^add_q_chapter_"),
            ],
            ADD_QUESTION_LESSON: [
                CallbackQueryHandler(add_question_lesson, pattern=r"^add_q_lesson_"),
            ],
            ADD_QUESTION_OPTIONS: [
                MessageHandler(Filters.text & ~Filters.command, add_question_options),
            ],
            ADD_QUESTION_CORRECT: [
                CallbackQueryHandler(add_question_correct, pattern=r"^correct_"),
            ],
            ADD_QUESTION_EXPLANATION: [
                MessageHandler(Filters.text & ~Filters.command, add_question_explanation),
            ],
            ADD_QUESTION_IMAGE: [
                CallbackQueryHandler(process_question_image_choice, pattern=r"^add_question_image_"),
                MessageHandler(Filters.photo, add_question_image),
            ],
            ADD_OPTION_IMAGES: [
                CallbackQueryHandler(process_option_images_choice, pattern=r"^add_option_images_"),
                MessageHandler(Filters.photo | (Filters.text & Filters.regex(r"^تخطي$")), add_option_image),
            ],
            VIEW_QUESTIONS: [
                CallbackQueryHandler(button_handler),
            ],
            QUIZ_TYPE: [
                CallbackQueryHandler(button_handler),
            ],
            QUIZ_TIMER: [
                CallbackQueryHandler(button_handler),
            ],
            QUIZ_CHAPTER: [
                CallbackQueryHandler(button_handler),
            ],
            QUIZ_LESSON: [
                CallbackQueryHandler(button_handler),
            ],
            QUIZ_QUESTION: [
                CallbackQueryHandler(process_quiz_answer, pattern=r"^answer_"),
                CallbackQueryHandler(show_quiz_question, pattern=r"^next_question$"),
                CallbackQueryHandler(end_quiz, pattern=r"^end_quiz$"),
            ],
            QUIZ_RESULT: [
                CallbackQueryHandler(show_quiz_details, pattern=r"^quiz_details$"),
                CallbackQueryHandler(button_handler, pattern=r"^back_to_main$"),
            ],
            QUIZ_HISTORY: [
                CallbackQueryHandler(button_handler),
            ],
            QUIZ_DETAILS: [
                CallbackQueryHandler(button_handler),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("help", help_command),
        ],
        allow_reentry=True,
    )
    
    dp.add_handler(conv_handler)
    
    # بدء البوت
    updater.start_polling()
    logger.info("Bot started polling...")
    
    # الانتظار حتى يتم إيقاف البوت
    updater.idle()

if __name__ == "__main__":
    main()
