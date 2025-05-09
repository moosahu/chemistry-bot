#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Conversation handler for the quiz selection and execution flow (PARAM & SYNTAX FIXES APPLIED).
(CONV_HANDLER_FIX for TAKING_QUIZ state)
(HANDLE_ANSWER_FIX for TypeError)
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
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي (صفحة أخرى):", reply_markup=keyboard)
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing course page from callback: {callback_data}. Error: {e}")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في التنقل بين الصفحات. يرجى المحاولة مرة أخرى.", reply_markup=create_course_selection_keyboard(courses, current_page))
        return SELECT_COURSE_FOR_UNIT_QUIZ

    elif callback_data.startswith("quiz_course_select_"):
        selected_course_id = callback_data.replace("quiz_course_select_", "", 1)
        context.user_data["selected_course_id_for_unit_quiz"] = selected_course_id
        selected_course = next((c for c in courses if str(c.get("id")) == str(selected_course_id)), None)
        context.user_data["selected_course_name_for_unit_quiz"] = selected_course.get("name", "مقرر غير مسمى") if selected_course else "مقرر غير مسمى"
        
        units = fetch_from_api(f"api/v1/courses/{selected_course_id}/units")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        if units == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
            
        if not units or not isinstance(units, list) or not units:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لا توجد وحدات دراسية متاحة لهذا المقرر أو حدث خطأ في جلبها.", reply_markup=create_course_selection_keyboard(courses, current_page))
            return SELECT_COURSE_FOR_UNIT_QUIZ
        
        context.user_data["available_units_for_course"] = units
        context.user_data["current_unit_page_for_course"] = 0
        keyboard = create_unit_selection_keyboard(units, selected_course_id, 0)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{context.user_data['selected_course_name_for_unit_quiz']}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    
    return SELECT_COURSE_FOR_UNIT_QUIZ 

async def select_unit_for_course(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data
    
    selected_course_id = context.user_data.get("selected_course_id_for_unit_quiz")
    units = context.user_data.get("available_units_for_course", [])
    current_page = context.user_data.get("current_unit_page_for_course", 0)

    if callback_data == "quiz_unit_back_to_course_selection":
        all_courses = context.user_data.get("available_courses_for_unit_quiz", []) 
        course_page_to_return_to = context.user_data.get("current_course_page_for_unit_quiz", 0)
        keyboard = create_course_selection_keyboard(all_courses, course_page_to_return_to)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="اختر المقرر الدراسي أولاً:", reply_markup=keyboard)
        return SELECT_COURSE_FOR_UNIT_QUIZ

    if callback_data.startswith("quiz_unit_page_"):
        try:
            parts = callback_data.split("_")
            # Expected format: quiz_unit_page_COURSEID_PAGENUM
            course_id_from_cb = parts[-2] # Should be course_id
            new_page = int(parts[-1]) # Should be page number
            if str(course_id_from_cb) != str(selected_course_id):
                logger.warning(f"Mismatched course_id in unit pagination. CB: {course_id_from_cb}, Context: {selected_course_id}. Reverting to course selection.")
                # Fallback to course selection if course_id mismatch
                all_courses = context.user_data.get("available_courses_for_unit_quiz", []) 
                course_page_to_return_to = context.user_data.get("current_course_page_for_unit_quiz", 0)
                keyboard = create_course_selection_keyboard(all_courses, course_page_to_return_to)
                await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ، يرجى اختيار المقرر مرة أخرى.", reply_markup=keyboard)
                return SELECT_COURSE_FOR_UNIT_QUIZ
            
            context.user_data["current_unit_page_for_course"] = new_page
            keyboard = create_unit_selection_keyboard(units, selected_course_id, new_page)
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية (صفحة أخرى) من مقرر \"{context.user_data['selected_course_name_for_unit_quiz']}\":", reply_markup=keyboard)
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing unit page from callback: {callback_data}. Error: {e}")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في التنقل بين صفحات الوحدات. يرجى المحاولة مرة أخرى.", reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
        return SELECT_UNIT_FOR_COURSE

    elif callback_data.startswith("quiz_unit_select_"):
        parts = callback_data.split("_")
        # Expected: quiz_unit_select_COURSEID_UNITID
        try:
            course_id_from_cb = parts[-2]
            selected_unit_id = parts[-1]
            if str(course_id_from_cb) != str(selected_course_id):
                 logger.warning(f"Mismatched course_id in unit selection. CB: {course_id_from_cb}, Context: {selected_course_id}. Reverting to course selection.")
                 all_courses = context.user_data.get("available_courses_for_unit_quiz", []) 
                 course_page_to_return_to = context.user_data.get("current_course_page_for_unit_quiz", 0)
                 keyboard = create_course_selection_keyboard(all_courses, course_page_to_return_to)
                 await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ، يرجى اختيار المقرر مرة أخرى.", reply_markup=keyboard)
                 return SELECT_COURSE_FOR_UNIT_QUIZ
        except IndexError:
            logger.error(f"Malformed callback data for unit selection: {callback_data}")
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في اختيار الوحدة. يرجى المحاولة مرة أخرى.", reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
            return SELECT_UNIT_FOR_COURSE

        context.user_data["selected_unit_id"] = selected_unit_id
        selected_unit = next((u for u in units if str(u.get("id")) == str(selected_unit_id)), None)
        selected_unit_name = selected_unit.get("name", "وحدة غير مسماة") if selected_unit else "وحدة غير مسماة"
        context.user_data["selected_unit_name"] = selected_unit_name
        
        unit_questions_pool = fetch_from_api(f"api/v1/units/{selected_unit_id}/questions")
        api_timeout_message = "انتهت مهلة الاتصال بخادم الأسئلة. يرجى المحاولة مرة أخرى لاحقاً."
        if unit_questions_pool == "TIMEOUT":
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=api_timeout_message, reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
            return SELECT_UNIT_FOR_COURSE

        if not unit_questions_pool or not isinstance(unit_questions_pool, list) or not unit_questions_pool:
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"عذراً، لا توجد أسئلة متاحة حالياً لوحدة \"{selected_unit_name}\".", reply_markup=create_unit_selection_keyboard(units, selected_course_id, current_page))
            return SELECT_UNIT_FOR_COURSE
        
        context.user_data[f"quiz_setup_{context.user_data['selected_quiz_type_key']}_{selected_unit_id}"] = {
            "questions": unit_questions_pool,
            "quiz_name": f"{context.user_data['selected_course_name_for_unit_quiz']} - {selected_unit_name}",
            "scope_id": selected_unit_id
        }
        max_questions = len(unit_questions_pool)
        keyboard = create_question_count_keyboard(max_questions, context.user_data['selected_quiz_type_key'], unit_id=selected_unit_id, course_id_for_unit=selected_course_id)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر عدد الأسئلة لاختبار وحدة \"{selected_unit_name}\":", reply_markup=keyboard)
        return ENTER_QUESTION_COUNT
    
    return SELECT_UNIT_FOR_COURSE

async def select_question_count(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data

    quiz_type = context.user_data.get("selected_quiz_type_key")
    unit_id = context.user_data.get("selected_unit_id") # This will be "all" for QUIZ_TYPE_ALL
    course_id_for_unit_quiz = context.user_data.get("selected_course_id_for_unit_quiz") # For back button

    if callback_data.startswith("quiz_count_back_to_unit_selection_"):
        # Expected: quiz_count_back_to_unit_selection_COURSEID
        course_id_from_cb = callback_data.replace("quiz_count_back_to_unit_selection_", "", 1)
        if str(course_id_from_cb) != str(course_id_for_unit_quiz):
            logger.warning(f"Mismatched course_id in count back. CB: {course_id_from_cb}, Context: {course_id_for_unit_quiz}. Reverting to type selection.")
            keyboard = create_quiz_type_keyboard()
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
            return SELECT_QUIZ_TYPE
        
        units_for_course = context.user_data.get("available_units_for_course", [])
        unit_page_to_return_to = context.user_data.get("current_unit_page_for_course", 0)
        keyboard = create_unit_selection_keyboard(units_for_course, course_id_for_unit_quiz, unit_page_to_return_to)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{context.user_data.get('selected_course_name_for_unit_quiz', '')}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE
    
    elif callback_data == "quiz_type_back_to_type_selection": # For QUIZ_TYPE_ALL back button
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    quiz_setup_key = f"quiz_setup_{quiz_type}_{unit_id}"
    quiz_setup_data = context.user_data.get(quiz_setup_key)

    if not quiz_setup_data or "questions" not in quiz_setup_data:
        logger.error(f"Quiz setup data not found for key {quiz_setup_key} for user {user_id}. Returning to type selection.")
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في إعداد الاختبار. يرجى المحاولة من جديد.", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    all_questions_for_scope = quiz_setup_data["questions"]
    max_q = len(all_questions_for_scope)
    
    num_questions_str = callback_data.replace("num_questions_", "", 1)
    if num_questions_str == "all":
        num_questions = max_q
    else:
        try:
            num_questions = int(num_questions_str)
            if not (0 < num_questions <= max_q):
                logger.warning(f"User {user_id} selected invalid num_questions: {num_questions} (max: {max_q}). Defaulting to max.")
                num_questions = max_q
        except ValueError:
            logger.error(f"Invalid num_questions callback: {callback_data}. Defaulting to max.")
            num_questions = max_q

    context.user_data["question_count_for_quiz"] = num_questions
    questions_to_use_in_quiz = random.sample(all_questions_for_scope, min(num_questions, max_q)) if max_q > 0 else []
    
    if not questions_to_use_in_quiz:
        logger.warning(f"No questions selected or available for quiz for user {user_id}. Type: {quiz_type}, Unit: {unit_id}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، لم يتم اختيار أسئلة أو لا توجد أسئلة كافية. يرجى المحاولة مرة أخرى.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    # Create a unique ID for this specific quiz instance
    quiz_instance_id = f"quiz_{user_id}_{query.message.chat_id}_{datetime.now().timestamp()}"
    context.user_data["current_quiz_instance_id"] = quiz_instance_id
    
    quiz_instance = QuizLogic(
        user_id=user_id,
        chat_id=query.message.chat_id,
        quiz_type=quiz_type,
        questions_data=questions_to_use_in_quiz,
        total_questions=len(questions_to_use_in_quiz),
        question_time_limit=DEFAULT_QUESTION_TIME_LIMIT, 
        quiz_id=quiz_instance_id, # Pass the unique instance ID
        quiz_name=quiz_setup_data.get("quiz_name", "اختبار"),
        quiz_scope_id=quiz_setup_data.get("scope_id")
    )
    context.user_data[quiz_instance_id] = quiz_instance

    await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"جاري إعداد اختبارك ({len(questions_to_use_in_quiz)} أسئلة)...", reply_markup=None)
    
    # Pass user_id to start_quiz
    return await quiz_instance.start_quiz(context.bot, context, update, user_id)

async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id # Get user_id from the query
    await query.answer()
    callback_data = query.data
    logger.debug(f"handle_quiz_answer called for user {user_id} with data: {callback_data}")

    quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if not quiz_instance_id or quiz_instance_id not in context.user_data:
        logger.warning(f"No active quiz instance ID found for user {user_id} in handle_quiz_answer. Callback: {callback_data}. Sending to main menu.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، يبدو أن جلسة الاختبار هذه لم تعد نشطة. يرجى بدء اختبار جديد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]]))
        return END # Or go_to_main_menu_from_quiz if you want full cleanup

    quiz_instance = context.user_data[quiz_instance_id]
    if not isinstance(quiz_instance, QuizLogic) or not quiz_instance.active:
        logger.warning(f"Quiz instance {quiz_instance_id} is not valid or not active for user {user_id}. Callback: {callback_data}. Sending to main menu.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، جلسة الاختبار الحالية غير صالحة. يرجى بدء اختبار جديد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]]))
        # Perform cleanup if needed, similar to go_to_main_menu_from_quiz
        context.user_data.pop(quiz_instance_id, None)
        context.user_data.pop("current_quiz_instance_id", None)
        return END

    # Parse chosen_option_id from callback_data
    # Expected format: ans_QUIZID_QINDEX_OPTIONID
    try:
        parts = callback_data.split("_")
        # quiz_id_from_cb = parts[1] # We can verify this if needed
        # question_index_from_cb = int(parts[2]) # We can verify this if needed
        chosen_option_id = parts[-1] # The last part is the option_id
    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing chosen_option_id from callback_data: {callback_data}. Error: {e}")
        await safe_send_message(context.bot, chat_id=query.message.chat_id, text="حدث خطأ أثناء معالجة إجابتك. يرجى المحاولة مرة أخرى.")
        return TAKING_QUIZ # Stay in the current state

    logger.debug(f"Found active QuizLogic instance {quiz_instance_id} for user {user_id}. Delegating to its handle_answer.")
    # Pass user_id and chosen_option_id to quiz_instance.handle_answer
    next_state = await quiz_instance.handle_answer(context.bot, context, update, user_id, chosen_option_id)
    
    if next_state == END or next_state == MAIN_MENU:
        logger.info(f"Quiz {quiz_instance_id} ended for user {user_id}. Cleaning up quiz instance from user_data.")
        context.user_data.pop(quiz_instance_id, None)
        context.user_data.pop("current_quiz_instance_id", None)
        # Additional cleanup for quiz-specific keys can be done here if necessary
        # For example, context.user_data.pop("db_quiz_session_id", None) - though this should be handled by QuizLogic.end_quiz ideally

    return next_state

async def quiz_timeout_external(update: Update, context: CallbackContext) -> int:
    """Handles quiz timeout if a timeout occurs outside the QuizLogic instance (e.g., user inactivity)."""
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    chat_id = update.effective_chat.id if update.effective_chat else "UnknownChat"
    logger.warning(f"Quiz conversation timed out externally for user {user_id} in chat {chat_id}.")
    
    current_quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if current_quiz_instance_id and current_quiz_instance_id in context.user_data:
        quiz_instance = context.user_data[current_quiz_instance_id]
        if isinstance(quiz_instance, QuizLogic) and quiz_instance.active:
            logger.info(f"Ending active quiz instance {current_quiz_instance_id} due to external timeout.")
            # Create a dummy update if `update` is not suitable or available for quiz_instance.end_quiz
            # For now, assume `update` can be passed or QuizLogic handles None for it gracefully in this path.
            await quiz_instance.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="external_conv_timeout", called_from_fallback=True)
        context.user_data.pop(current_quiz_instance_id, None)
    context.user_data.pop("current_quiz_instance_id", None)
    
    await safe_send_message(context.bot, chat_id, text="انتهى وقت الاختبار بسبب عدم النشاط. عدنا إلى القائمة الرئيسية.")
    # Call main_menu_callback to display the main menu
    # We need to ensure main_menu_callback can be called without a query if necessary, or construct a dummy query.
    # For simplicity, let's assume it can handle being called directly or we send a new message with the menu.
    # This might require main_menu_callback to be adapted or a new function to just show the menu.
    # For now, just ending the conversation.
    # await main_menu_callback(update, context) # This might fail if update is not a CallbackQuery
    
    # Fallback: Send a new message with the main menu options if main_menu_callback is problematic here
    from handlers.common import create_main_menu_keyboard # Assuming this exists
    try:
        main_menu_kb = create_main_menu_keyboard(user_id, context) # Assuming it takes user_id and context
        await safe_send_message(context.bot, chat_id, "القائمة الرئيسية:", reply_markup=main_menu_kb)
    except Exception as e_menu_fallback:
        logger.error(f"Failed to send main menu fallback on external timeout: {e_menu_fallback}")
        await safe_send_message(context.bot, chat_id, "حدث خطأ ما. يرجى استخدام /start للعودة.")

    return ConversationHandler.END

# Conversation Handler Definition (PARAM & SYNTAX FIXES APPLIED)
quiz_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(quiz_menu_entry, pattern="^start_quiz$"),
        CommandHandler("quiz", quiz_menu_entry) # Allow starting with /quiz command directly
    ],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern="^quiz_type_.+$"),
            CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^main_menu$")
        ],
        SELECT_COURSE_FOR_UNIT_QUIZ: [
            CallbackQueryHandler(select_course_for_unit_quiz, pattern="^quiz_course_select_.+$"),
            CallbackQueryHandler(select_course_for_unit_quiz, pattern="^quiz_course_page_.+$"),
            CallbackQueryHandler(select_course_for_unit_quiz, pattern="^quiz_type_back_to_type_selection$") # Back to type selection
        ],
        SELECT_UNIT_FOR_COURSE: [
            CallbackQueryHandler(select_unit_for_course, pattern="^quiz_unit_select_.+_.+$"), # course_id_unit_id
            CallbackQueryHandler(select_unit_for_course, pattern="^quiz_unit_page_.+_.+$"),   # course_id_page_num
            CallbackQueryHandler(select_unit_for_course, pattern="^quiz_unit_back_to_course_selection$") # Back to course selection
        ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(select_question_count, pattern="^num_questions_.+$"),
            CallbackQueryHandler(select_question_count, pattern="^quiz_count_back_to_unit_selection_.+$"), # Back to unit selection for unit quizzes
            CallbackQueryHandler(select_question_count, pattern="^quiz_type_back_to_type_selection$") # Back to type selection for "all" quizzes
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern="^ans_.+_.+_.+$") # ans_QUIZID_QINDEX_OPTIONID
        ],
        SHOWING_RESULTS: [ # This state might be implicitly handled by QuizLogic returning END or MAIN_MENU
            CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^main_menu$"), # If results show a main menu button
            CallbackQueryHandler(quiz_menu_entry, pattern="^start_another_quiz$") # If results show a start another quiz button
        ]
    },
    fallbacks=[
        CommandHandler("start", start_command_fallback_for_quiz),
        CallbackQueryHandler(go_to_main_menu_from_quiz, pattern="^main_menu$"), # General fallback to main menu
        MessageHandler(filters.COMMAND, start_command_fallback_for_quiz) # Catch any other command
    ],
    map_to_parent={
        END: MAIN_MENU, 
        MAIN_MENU: MAIN_MENU 
    },
    conversation_timeout=1800, # 30 minutes timeout for the entire conversation
    per_message=False,
    name="quiz_conversation_handler",
    persistent=False 
)

# Ensure the question_timeout_callback_wrapper is correctly defined or imported if it's elsewhere
# It seems it's already imported from .quiz_logic

logger.info("handlers/quiz.py (quiz_conv_handler) loaded with HANDLE_ANSWER_FIX.")

