#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Conversation handler for the quiz selection and execution flow (PARAM & SYNTAX FIXES APPLIED).
(CONV_HANDLER_FIX for TAKING_QUIZ state)
"""

import logging
import math
import random
import re
from datetime import datetime # Added for quiz_id timestamp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CommandHandler
)

from config import (
    logger,
    MAIN_MENU, QUIZ_MENU, SELECT_QUIZ_TYPE, 
    SELECT_COURSE_FOR_UNIT_QUIZ, SELECT_UNIT_FOR_COURSE, 
    SELECT_QUIZ_SCOPE, 
    ENTER_QUESTION_COUNT, TAKING_QUIZ, SHOWING_RESULTS, END,
    QUIZ_TYPE_RANDOM, QUIZ_TYPE_CHAPTER, QUIZ_TYPE_UNIT, QUIZ_TYPE_ALL, 
    DEFAULT_QUESTION_TIME_LIMIT
)
from utils.helpers import safe_send_message, safe_edit_message_text, get_quiz_type_string, remove_job_if_exists
from utils.api_client import fetch_from_api
# Ensure correct import for main_menu_callback and start_command if they are in common.py
from handlers.common import main_menu_callback, start_command 
from .quiz_logic import QuizLogic, question_timeout_callback_wrapper 

# --- POSTGRESQL DATABASE LOGGING ---
try:
    from database.data_logger import log_user_activity, log_quiz_start
except ImportError as e:
    logger.error(f"CRITICAL: Could not import from database.data_logger: {e}.")
    def log_user_activity(*args, **kwargs): logger.error("Dummy log_user_activity called."); pass
    def log_quiz_start(*args, **kwargs): logger.error("Dummy log_quiz_start called."); return None
# -----------------------------------

ITEMS_PER_PAGE = 6

async def start_command_fallback_for_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} sent /start during quiz_conv. Ending quiz_conv, showing main menu.")
    
    current_quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if current_quiz_instance_id and current_quiz_instance_id in context.user_data:
        quiz_instance = context.user_data[current_quiz_instance_id]
        if isinstance(quiz_instance, QuizLogic) and quiz_instance.active:
            await quiz_instance.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="start_fallback_quiz_handler", called_from_fallback=True)
        context.user_data.pop(current_quiz_instance_id, None)
    context.user_data.pop("current_quiz_instance_id", None)

    keys_to_pop = [
        "selected_quiz_type_key", "selected_quiz_type_display_name", "questions_for_quiz",
        "selected_course_id_for_unit_quiz", "available_courses_for_unit_quiz",
        "current_course_page_for_unit_quiz", "selected_course_name_for_unit_quiz",
        "available_units_for_course", "current_unit_page_for_course",
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz",
        "db_quiz_session_id"
    ]
    for key in keys_to_pop:
        context.user_data.pop(key, None)
    for key in list(context.user_data.keys()):
        if key.startswith("quiz_setup_") or key.startswith("qtimer_"):
            context.user_data.pop(key, None)

    await start_command(update, context)
    return ConversationHandler.END

async def go_to_main_menu_from_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} chose to go to main menu from quiz conversation ({update.callback_query.data if update.callback_query else 'N/A'}). Ending quiz_conv.")
    
    current_quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if current_quiz_instance_id and current_quiz_instance_id in context.user_data:
        quiz_instance = context.user_data[current_quiz_instance_id]
        if isinstance(quiz_instance, QuizLogic) and quiz_instance.active:
            await quiz_instance.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="main_menu_fallback_quiz_handler", called_from_fallback=True)
        context.user_data.pop(current_quiz_instance_id, None)
    context.user_data.pop("current_quiz_instance_id", None)
    
    keys_to_pop = [
        "selected_quiz_type_key", "selected_quiz_type_display_name", "questions_for_quiz",
        "selected_course_id_for_unit_quiz", "available_courses_for_unit_quiz",
        "current_course_page_for_unit_quiz", "selected_course_name_for_unit_quiz",
        "available_units_for_course", "current_unit_page_for_course",
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz",
        "db_quiz_session_id"
    ]
    for key in keys_to_pop:
        context.user_data.pop(key, None)
    for key in list(context.user_data.keys()): 
        if key.startswith("quiz_setup_") or key.startswith("qtimer_"):
            context.user_data.pop(key, None)
            
    await main_menu_callback(update, context)
    return ConversationHandler.END

def create_quiz_type_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🎲 اختبار عشوائي شامل (كل المقررات)", callback_data=f"quiz_type_{QUIZ_TYPE_ALL}")],
        [InlineKeyboardButton("📚 حسب الوحدة الدراسية (اختر المقرر ثم الوحدة)", callback_data=f"quiz_type_{QUIZ_TYPE_UNIT}")],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")] 
    ]
    return InlineKeyboardMarkup(keyboard)

def create_course_selection_keyboard(courses: list, current_page: int = 0) -> InlineKeyboardMarkup:
    keyboard = []
    items_per_page = ITEMS_PER_PAGE
    start_index = current_page * items_per_page
    end_index = start_index + items_per_page
    for i in range(start_index, min(end_index, len(courses))):
        course = courses[i]
        keyboard.append([InlineKeyboardButton(course.get("name", f"مقرر {course.get('id')}"), callback_data=f"quiz_course_select_{course.get('id')}")])
    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"quiz_course_page_{current_page - 1}"))
    if end_index < len(courses):
        pagination_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"quiz_course_page_{current_page + 1}"))
    if pagination_buttons:
        keyboard.append(pagination_buttons)
    keyboard.append([InlineKeyboardButton("🔙 اختيار نوع الاختبار", callback_data="quiz_type_back_to_type_selection")])
    return InlineKeyboardMarkup(keyboard)

def create_unit_selection_keyboard(units: list, course_id: str, current_page: int = 0) -> InlineKeyboardMarkup:
    keyboard = []
    items_per_page = ITEMS_PER_PAGE
    start_index = current_page * items_per_page
    end_index = start_index + items_per_page
    for i in range(start_index, min(end_index, len(units))):
        unit = units[i]
        keyboard.append([InlineKeyboardButton(unit.get("name", f"وحدة {unit.get('id')}"), callback_data=f"quiz_unit_select_{course_id}_{unit.get('id')}")])
    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"quiz_unit_page_{course_id}_{current_page - 1}"))
    if end_index < len(units):
        pagination_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"quiz_unit_page_{course_id}_{current_page + 1}"))
    if pagination_buttons:
        keyboard.append(pagination_buttons)
    keyboard.append([InlineKeyboardButton("🔙 اختيار المقرر", callback_data="quiz_unit_back_to_course_selection")])
    return InlineKeyboardMarkup(keyboard)

def create_question_count_keyboard(max_questions: int, quiz_type: str, unit_id: str = None, course_id_for_unit: str = None) -> InlineKeyboardMarkup:
    counts = [1, 5, 10, 20, min(max_questions, 50)]
    if max_questions > 0 and max_questions not in counts and max_questions <= 50:
        counts.append(max_questions)
    counts = sorted(list(set(c for c in counts if c <= max_questions and c > 0)))
    keyboard = []
    row = []
    for count in counts:
        row.append(InlineKeyboardButton(str(count), callback_data=f"num_questions_{count}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    if not counts or (counts and max_questions > counts[-1] and max_questions > 0):
         keyboard.append([InlineKeyboardButton(f"الكل ({max_questions})", callback_data="num_questions_all")])
    
    if quiz_type == QUIZ_TYPE_UNIT and course_id_for_unit and unit_id:
        back_callback_data = f"quiz_count_back_to_unit_selection_{course_id_for_unit}" 
    else:
        back_callback_data = "quiz_type_back_to_type_selection"
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_callback_data)])
    return InlineKeyboardMarkup(keyboard)

async def quiz_menu_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    logger.info(f"User {user_id} entered quiz menu (quiz_menu_entry) via {query.data}.")
    keys_to_clear_on_entry = [
        "selected_quiz_type_key", "selected_quiz_type_display_name", "questions_for_quiz",
        "selected_course_id_for_unit_quiz", "available_courses_for_unit_quiz",
        "current_course_page_for_unit_quiz", "selected_course_name_for_unit_quiz",
        "available_units_for_course", "current_unit_page_for_course",
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz",
        "db_quiz_session_id", "current_quiz_instance_id"
    ]
    for key in keys_to_clear_on_entry:
        context.user_data.pop(key, None)
    logger.debug(f"Cleared preliminary quiz setup data for user {user_id} at quiz_menu_entry.")
    keyboard = create_quiz_type_keyboard()
    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
    return SELECT_QUIZ_TYPE

async def select_quiz_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data

    if callback_data == "main_menu":
        return await go_to_main_menu_from_quiz(update, context)
        
    if callback_data == "quiz_type_back_to_type_selection": 
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    quiz_type_key = callback_data.replace("quiz_type_", "", 1)
    context.user_data["selected_quiz_type_key"] = quiz_type_key
    quiz_type_display_name = get_quiz_type_string(quiz_type_key)
    context.user_data["selected_quiz_type_display_name"] = quiz_type_display_name
    error_message_to_user = "عذراً، حدث خطأ أثناء جلب البيانات. يرجى المحاولة لاحقاً أو التأكد من أن خدمة الأسئلة تعمل."
    api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."

    if quiz_type_key == QUIZ_TYPE_ALL:
        all_questions_pool = fetch_from_api("api/v1/questions/all")
        if all_questions_pool == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        if not all_questions_pool or not isinstance(all_questions_pool, list):
            courses = fetch_from_api("api/v1/courses")
            if courses == "TIMEOUT":
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
                return SELECT_QUIZ_TYPE
            if not courses or not isinstance(courses, list):
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=error_message_to_user, reply_markup=create_quiz_type_keyboard())
                return SELECT_QUIZ_TYPE
            all_questions_pool = []
            for course in courses:
                course_id_val = course.get("id")
                if not course_id_val: continue
                current_course_questions = fetch_from_api(f"api/v1/courses/{course_id_val}/questions")
                if current_course_questions == "TIMEOUT": continue 
                if isinstance(current_course_questions, list):
                    all_questions_pool.extend(current_course_questions)
        
        if not all_questions_pool: 
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لم يتم العثور على أسئلة للاختبار الشامل.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
            
        context.user_data[f"quiz_setup_{quiz_type_key}_all"] = {
            "questions": all_questions_pool,
            "quiz_name": quiz_type_display_name,
            "scope_id": "all"
        }
        context.user_data["selected_unit_id"] = "all" 
        max_questions = len(all_questions_pool)
        keyboard = create_question_count_keyboard(max_questions, quiz_type_key, unit_id="all")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار \n\"{quiz_type_display_name}\":", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT

    elif quiz_type_key == QUIZ_TYPE_UNIT:
        courses = fetch_from_api("api/v1/courses")
        if courses == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        if not courses or not isinstance(courses, list) or not courses:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد مقررات متاحة حالياً أو حدث خطأ في جلبها.", reply_markup=create_quiz_type_keyboard())
            return SELECT_QUIZ_TYPE
        context.user_data["available_courses_for_unit_quiz"] = courses
        context.user_data["current_course_page_for_unit_quiz"] = 0
        keyboard = create_course_selection_keyboard(courses, 0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي أولاً:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ
    else:
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="نوع اختبار غير معروف. يرجى الاختيار من القائمة.", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

async def select_course_for_unit_quiz(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    courses = context.user_data.get("available_courses_for_unit_quiz", [])
    current_page = context.user_data.get("current_course_page_for_unit_quiz", 0)

    if callback_data == "quiz_type_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE
    
    if callback_data.startswith("quiz_course_page_"):
        try:
            new_page = int(callback_data.split("_")[-1])
            context.user_data["current_course_page_for_unit_quiz"] = new_page
            keyboard = create_course_selection_keyboard(courses, new_page)
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي:", reply_markup=keyboard)
            return SELECT_COURSE_FOR_UNIT_QUIZ
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing course page callback data: {callback_data}, error: {e}")
            await query.message.reply_text("حدث خطأ أثناء التنقل بين الصفحات. يرجى المحاولة مرة أخرى.")
            return SELECT_COURSE_FOR_UNIT_QUIZ

    elif callback_data.startswith("quiz_course_select_"):
        course_id = callback_data.replace("quiz_course_select_", "", 1)
        selected_course = next((c for c in courses if str(c.get("id")) == course_id), None)
        if not selected_course:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="المقرر المختار غير صالح. يرجى المحاولة مرة أخرى.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        
        context.user_data["selected_course_id_for_unit_quiz"] = course_id
        context.user_data["selected_course_name_for_unit_quiz"] = selected_course.get("name", f"مقرر {course_id}")
        
        units = fetch_from_api(f"api/v1/courses/{course_id}/units")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        if units == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
            
        if not units or not isinstance(units, list) or not units:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد وحدات دراسية متاحة للمقرر \"{selected_course.get('name')}\" أو حدث خطأ في جلبها.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        
        context.user_data["available_units_for_course"] = units
        context.user_data["current_unit_page_for_course"] = 0
        keyboard = create_unit_selection_keyboard(units, course_id, 0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{selected_course.get('name')}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    
    return SELECT_COURSE_FOR_UNIT_QUIZ # Fallback

async def select_unit_for_course(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz")
    selected_course_name = context.user_data.get("selected_course_name_for_unit_quiz", "المقرر المختار")
    units = context.user_data.get("available_units_for_course", [])
    current_page = context.user_data.get("current_unit_page_for_course", 0)

    if callback_data == "quiz_unit_back_to_course_selection":
        all_courses = context.user_data.get("available_courses_for_unit_quiz", []) # Should have been stored
        course_page = context.user_data.get("current_course_page_for_unit_quiz", 0)
        keyboard = create_course_selection_keyboard(all_courses, course_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    if callback_data.startswith("quiz_unit_page_"):
        try:
            parts = callback_data.split("_")
            # Expected format: quiz_unit_page_COURSEID_PAGE
            # However, the create_unit_selection_keyboard uses quiz_unit_page_{course_id}_{current_page + 1}
            # So parts should be ["quiz", "unit", "page", COURSEID, PAGE]
            # Or if it's just quiz_unit_page_PAGE (if course_id is implicit from context), then simpler split
            # Let's assume course_id is correctly embedded or not needed if only page changes
            # The create_unit_selection_keyboard uses: f"quiz_unit_page_{course_id}_{current_page - 1}"
            # So the course_id is indeed in the callback_data
            page_course_id = parts[-2] # course_id should be second to last
            new_page = int(parts[-1]) # page number is last
            
            if str(page_course_id) != str(selected_course_id):
                logger.warning(f"Mismatched course_id in unit pagination. Expected {selected_course_id}, got {page_course_id}. Data: {callback_data}")
                # Potentially fall back or send error
            
            context.user_data["current_unit_page_for_course"] = new_page
            keyboard = create_unit_selection_keyboard(units, selected_course_id, new_page)
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{selected_course_name}\":", reply_markup=keyboard)
            return SELECT_UNIT_FOR_COURSE
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing unit page callback data: {callback_data}, error: {e}")
            await query.message.reply_text("حدث خطأ أثناء التنقل بين صفحات الوحدات. يرجى المحاولة مرة أخرى.")
            return SELECT_UNIT_FOR_COURSE
            
    elif callback_data.startswith("quiz_unit_select_"):
        try:
            parts = callback_data.split("_") # quiz_unit_select_COURSEID_UNITID
            unit_id = parts[-1]
            cb_course_id = parts[-2]
            if str(cb_course_id) != str(selected_course_id):
                logger.error(f"Mismatched course_id in unit selection. Expected {selected_course_id}, got {cb_course_id}. Data: {callback_data}")
                # Send error to user, ask to restart selection
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في اختيار الوحدة بسبب عدم تطابق المقرر. يرجى إعادة اختيار المقرر.", reply_markup=create_course_selection_keyboard(context.user_data.get("available_courses_for_unit_quiz", []),0) )
                return SELECT_COURSE_FOR_UNIT_QUIZ

            selected_unit = next((u for u in units if str(u.get("id")) == unit_id), None)
            if not selected_unit:
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="الوحدة المختارة غير صالحة. يرجى المحاولة مرة أخرى.", reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
                return SELECT_UNIT_FOR_COURSE
            
            context.user_data["selected_unit_id"] = unit_id
            unit_name = selected_unit.get("name", f"وحدة {unit_id}")
            context.user_data["selected_unit_name"] = unit_name
            quiz_name_for_display = f"{selected_course_name} - {unit_name}"
            
            questions_for_unit = fetch_from_api(f"api/v1/units/{unit_id}/questions")
            api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
            if questions_for_unit == "TIMEOUT":
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
                return SELECT_UNIT_FOR_COURSE

            if not questions_for_unit or not isinstance(questions_for_unit, list) or not questions_for_unit:
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد أسئلة متاحة للوحدة \"{unit_name}\" حالياً.", reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
                return SELECT_UNIT_FOR_COURSE
            
            context.user_data[f"quiz_setup_{context.user_data['selected_quiz_type_key']}_{unit_id}"] = {
                "questions": questions_for_unit,
                "quiz_name": quiz_name_for_display,
                "scope_id": unit_id 
            }
            max_questions = len(questions_for_unit)
            keyboard = create_question_count_keyboard(max_questions, context.user_data['selected_quiz_type_key'], unit_id=unit_id, course_id_for_unit=selected_course_id)
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار \n\"{quiz_name_for_display}\":", reply_markup=keyboard)
            return ENTER_QUESTION_COUNT
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing unit selection callback data: {callback_data}, error: {e}")
            await query.message.reply_text("حدث خطأ أثناء اختيار الوحدة. يرجى المحاولة مرة أخرى.")
            return SELECT_UNIT_FOR_COURSE
            
    return SELECT_UNIT_FOR_COURSE # Fallback

async def enter_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()
    callback_data = query.data

    selected_quiz_type_key = context.user_data.get("selected_quiz_type_key")
    selected_unit_id = context.user_data.get("selected_unit_id") # This will be 'all' for QUIZ_TYPE_ALL
    quiz_setup_key_suffix = selected_unit_id if selected_unit_id else "all" # Fallback for safety, though 'all' should be set
    quiz_setup_data = context.user_data.get(f"quiz_setup_{selected_quiz_type_key}_{quiz_setup_key_suffix}")

    if callback_data.startswith("quiz_count_back_to_unit_selection_"):
        course_id_from_cb = callback_data.split("_")[-1]
        # We need to re-fetch units for this course_id or retrieve from context if stored appropriately
        # For simplicity, assume selected_course_id_for_unit_quiz is still valid
        units_for_course = context.user_data.get("available_units_for_course", [])
        unit_page = context.user_data.get("current_unit_page_for_course", 0)
        keyboard = create_unit_selection_keyboard(units_for_course, course_id_from_cb, unit_page)
        course_name = context.user_data.get("selected_course_name_for_unit_quiz", f"مقرر {course_id_from_cb}")
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{course_name}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    elif callback_data == "quiz_type_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    if not quiz_setup_data or "questions" not in quiz_setup_data:
        logger.error(f"User {user_id}: Quiz setup data missing or incomplete for type {selected_quiz_type_key}, unit {selected_unit_id}.")
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="حدث خطأ في إعداد الاختبار. يرجى المحاولة من البداية.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    all_questions_for_scope = quiz_setup_data["questions"]
    quiz_name = quiz_setup_data.get("quiz_name", "اختبار")
    quiz_scope_id_for_log = quiz_setup_data.get("scope_id") # This is 'all' or unit_id
    max_questions = len(all_questions_for_scope)
    
    num_questions_str = callback_data.replace("num_questions_", "", 1)
    if num_questions_str == "all":
        actual_question_count = max_questions
    else:
        try:
            actual_question_count = int(num_questions_str)
            if not (0 < actual_question_count <= max_questions):
                logger.warning(f"User {user_id} selected invalid number of questions: {actual_question_count}. Max: {max_questions}")
                await query.message.reply_text(f"العدد المختار غير صالح. يرجى اختيار عدد بين 1 و {max_questions}.")
                # Re-show count keyboard
                keyboard = create_question_count_keyboard(max_questions, selected_quiz_type_key, unit_id=selected_unit_id, course_id_for_unit=context.user_data.get("selected_course_id_for_unit_quiz"))
                await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=query.message.text, reply_markup=keyboard)
                return ENTER_QUESTION_COUNT
        except ValueError:
            logger.error(f"User {user_id}: Could not parse num_questions: {num_questions_str}")
            await query.message.reply_text("حدث خطأ في تحديد عدد الأسئلة. يرجى المحاولة مرة أخرى.")
            return ENTER_QUESTION_COUNT # Or back to type selection

    if actual_question_count == 0:
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="لا توجد أسئلة كافية لبدء هذا الاختبار. يرجى اختيار نطاق آخر أو إضافة المزيد من الأسئلة.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    # Shuffle and select questions
    random.shuffle(all_questions_for_scope)
    questions_for_this_quiz = all_questions_for_scope[:actual_question_count]
    context.user_data["question_count_for_quiz"] = actual_question_count

    # Log quiz start attempt (before creating QuizLogic instance)
    db_session_id = None
    try:
        # Ensure log_quiz_start can handle quiz_scope_id=None if it's truly global (e.g. 'all')
        # or pass a specific string like "all_questions_global_scope"
        # For now, quiz_scope_id_for_log is 'all' or a unit_id string
        logger.info(f"[DataLogger] Logging quiz start for user {user_id}, Type: {selected_quiz_type_key}, Name: {quiz_name}, Scope: {quiz_scope_id_for_log}")
        db_session_id = log_quiz_start(
            user_id=user_id,
            quiz_name=quiz_name, 
            quiz_type=selected_quiz_type_key,
            quiz_scope_id=quiz_scope_id_for_log, # This is 'all' or unit_id
            total_questions=actual_question_count
        )
        if db_session_id:
            context.user_data["db_quiz_session_id"] = db_session_id
            logger.info(f"[DataLogger] Quiz start logged with DB session ID: {db_session_id} for user {user_id}")
        else:
            logger.warning(f"[DataLogger] log_quiz_start returned None for user {user_id}. Quiz will proceed without distinct DB session tracking.")
            context.user_data.pop("db_quiz_session_id", None) # Ensure it's not set if None
    except Exception as e_log_start:
        logger.error(f"Failed to log quiz start to DB for user {user_id}: {e_log_start}", exc_info=True)
        context.user_data.pop("db_quiz_session_id", None) # Ensure it's not set on error

    # Create and store QuizLogic instance
    quiz_instance_id = f"quiz_{user_id}_{chat_id}_{datetime.now().timestamp()}"
    quiz_logic = QuizLogic(
        user_id=user_id,
        chat_id=chat_id,
        questions_data=questions_for_this_quiz,
        quiz_type=selected_quiz_type_key,
        quiz_name=quiz_name,
        quiz_scope_id=quiz_scope_id_for_log, 
        total_questions=actual_question_count,
        question_time_limit=DEFAULT_QUESTION_TIME_LIMIT,
        db_quiz_session_id=context.user_data.get("db_quiz_session_id") # Pass the retrieved or None session ID
    )
    context.user_data[quiz_instance_id] = quiz_logic
    context.user_data["current_quiz_instance_id"] = quiz_instance_id

    # Start the quiz by sending the first question
    # The QuizLogic.send_question will return TAKING_QUIZ state
    # We need to edit the current message (which shows question count selection) before sending the new question message.
    # It's better to let QuizLogic handle the first message sending to avoid message clutter or race conditions.
    await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text=f"جاري إعداد اختبارك ({actual_question_count} أسئلة)...", reply_markup=None)
    
    # The send_question method in QuizLogic should handle sending the first question and setting up the timer.
    # It will return the next state, which should be TAKING_QUIZ.
    return await quiz_logic.send_question(context.bot, context, user_id) 


async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    logger.debug(f"handle_quiz_answer called for user {user_id} with data: {query.data}")

    current_quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if not current_quiz_instance_id:
        logger.error(f"TAKING_QUIZ (handle_quiz_answer): No current_quiz_instance_id for user {user_id}. Cannot process answer.")
        try:
            await query.answer("حدث خطأ، يرجى محاولة بدء الاختبار مرة أخرى.", show_alert=True)
        except Exception as e_ans:
            logger.error(f"Error sending answer to query in handle_quiz_answer (no instance): {e_ans}")
        return END 

    quiz_instance = context.user_data.get(current_quiz_instance_id)

    if isinstance(quiz_instance, QuizLogic) and quiz_instance.active:
        logger.debug(f"Found active QuizLogic instance {current_quiz_instance_id} for user {user_id}. Delegating to its handle_answer.")
        next_state = await quiz_instance.handle_answer(context.bot, context, update)
        return next_state
    else:
        logger.warning(f"TAKING_QUIZ (handle_quiz_answer): Quiz instance {current_quiz_instance_id} not found, inactive, or not QuizLogic for user {user_id}. Instance: {quiz_instance}")
        try:
            await query.answer("جلسة الاختبار هذه غير صالحة أو انتهت.", show_alert=True)
        except Exception as e_ans_inactive:
            logger.error(f"Error sending answer to query in handle_quiz_answer (inactive/no instance): {e_ans_inactive}")
        
        if current_quiz_instance_id:
            context.user_data.pop(current_quiz_instance_id, None)
        context.user_data.pop("current_quiz_instance_id", None)
        # Try to guide user back to main menu by editing the message if possible
        if query.message:
            try:
                await go_to_main_menu_from_quiz(update, context) # This function handles cleanup and sends main menu
                return ConversationHandler.END # go_to_main_menu_from_quiz should return END
            except Exception as e_main_menu_fallback:
                logger.error(f"Error trying to go to main menu from handle_quiz_answer fallback: {e_main_menu_fallback}")
        return END

async def showing_results_actions(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data

    if callback_data == "start_new_quiz":
        # This should effectively be the same as quiz_menu_entry
        # Clear any lingering quiz result display specific data if necessary
        logger.info(f"User {user_id} chose to start a new quiz from results screen.")
        return await quiz_menu_entry(update, context) 
    elif callback_data == "main_menu":
        logger.info(f"User {user_id} chose to go to main menu from results screen.")
        return await go_to_main_menu_from_quiz(update, context)
    else:
        logger.warning(f"Unknown callback in SHOWING_RESULTS: {callback_data} for user {user_id}")
        # Potentially resend the results message with keyboard if it got lost
        # For now, just stay in the state or end.
        return SHOWING_RESULTS

# Conversation Handler Setup
quiz_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$")
    ],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern=f"^quiz_type_({QUIZ_TYPE_ALL}|{QUIZ_TYPE_UNIT}|{QUIZ_TYPE_CHAPTER}|{QUIZ_TYPE_RANDOM})$"), # More specific pattern
            CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^main_menu$"),
            CallbackQueryHandler(quiz_menu_entry, pattern="^quiz_type_back_to_type_selection$"), # If create_quiz_type_keyboard uses this
        ],
        SELECT_COURSE_FOR_UNIT_QUIZ: [
            CallbackQueryHandler(select_course_for_unit_quiz, pattern="^quiz_course_(select_|page_)"),
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_back_to_type_selection$"),
        ],
        SELECT_UNIT_FOR_COURSE: [
            CallbackQueryHandler(select_unit_for_course, pattern="^quiz_unit_(select_|page_)"),
            CallbackQueryHandler(select_course_for_unit_quiz, pattern="^quiz_unit_back_to_course_selection$"),
        ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(enter_question_count, pattern="^num_questions_(all|[0-9]+)$"), # More specific pattern
            CallbackQueryHandler(select_unit_for_course, pattern="^quiz_count_back_to_unit_selection_"), 
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_back_to_type_selection$"),
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern="^ans_") # ADDED HANDLER FOR ANSWERS
        ],
        SHOWING_RESULTS: [
            CallbackQueryHandler(showing_results_actions, pattern="^start_new_quiz$|^main_menu$")
        ],
    },
    fallbacks=[
        CommandHandler("start", start_command_fallback_for_quiz),
        CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^main_menu$"),
        # Adding a more generic fallback for unexpected callbacks during the quiz flow
        CallbackQueryHandler(lambda u,c: quiz_menu_entry(u,c) if u.callback_query.data == "quiz_menu_entry_fallback" else go_to_main_menu_from_quiz(u,c) , pattern="^quiz_menu_entry_fallback$|^main_menu$")
    ],
    name="quiz_conversation",
    persistent=True,
    # per_message=False, # Default, generally okay for CallbackQueryHandlers
    # allow_reentry=True # Consider if needed, but usually entry_points handle re-entry logic
)

logger.info("Quiz ConversationHandler (quiz.py) loaded with TAKING_QUIZ state handler.")

