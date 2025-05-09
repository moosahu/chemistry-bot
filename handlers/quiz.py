#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Conversation handler for the quiz selection and execution flow.
(DB_MANAGER_PASS_FIX: Passes db_manager instance directly to QuizLogic)
"""

import logging
import math # Not used, consider removing
import random
import re # Not used, consider removing
from datetime import datetime
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
from handlers.common import main_menu_callback, start_command 
# Assuming quiz_logic.py will be updated with the content of quiz_logic_DBMANAGER_PASS_FIX.py
from .quiz_logic import QuizLogic, question_timeout_callback_wrapper 

# Removed direct DB logger imports as QuizLogic now handles its DB interactions via injected db_manager
# try:
#     from database.data_logger import log_user_activity, log_quiz_start
# except ImportError as e:
#     logger.error(f"CRITICAL: Could not import from database.data_logger: {e}.")
#     def log_user_activity(*args, **kwargs): logger.error("Dummy log_user_activity called."); pass
#     def log_quiz_start(*args, **kwargs): logger.error("Dummy log_quiz_start called."); return None

ITEMS_PER_PAGE = 6

async def start_command_fallback_for_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} sent /start during quiz_conv. Ending quiz_conv, showing main menu.")
    
    current_quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if current_quiz_instance_id and current_quiz_instance_id in context.user_data:
        quiz_instance = context.user_data.get(current_quiz_instance_id) # Get the instance itself
        if isinstance(quiz_instance, QuizLogic) and quiz_instance.active:
            # Pass bot, context, and update to end_quiz
            await quiz_instance.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="start_fallback_quiz_handler", called_from_fallback=True)
        context.user_data.pop(current_quiz_instance_id, None)
    context.user_data.pop("current_quiz_instance_id", None)

    keys_to_pop = [
        "selected_quiz_type_key", "selected_quiz_type_display_name", "questions_for_quiz",
        "selected_course_id_for_unit_quiz", "available_courses_for_unit_quiz",
        "current_course_page_for_unit_quiz", "selected_course_name_for_unit_quiz",
        "available_units_for_course", "current_unit_page_for_course",
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz"
        # "db_quiz_session_id" # This was managed by QuizLogic internally now
    ]
    for key in keys_to_pop:
        context.user_data.pop(key, None)
    for key_ud in list(context.user_data.keys()): # Iterate over a copy of keys
        if key_ud.startswith("quiz_setup_") or key_ud.startswith("qtimer_"):
            context.user_data.pop(key_ud, None)

    await start_command(update, context) # This is from common.py
    return ConversationHandler.END

async def go_to_main_menu_from_quiz(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} chose to go to main menu from quiz conversation ({update.callback_query.data if update.callback_query else 'N/A'}). Ending quiz_conv.")
    
    current_quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if current_quiz_instance_id and current_quiz_instance_id in context.user_data:
        quiz_instance = context.user_data.get(current_quiz_instance_id)
        if isinstance(quiz_instance, QuizLogic) and quiz_instance.active:
            await quiz_instance.end_quiz(context.bot, context, update, manual_end=True, reason_suffix="main_menu_fallback_quiz_handler", called_from_fallback=True)
        context.user_data.pop(current_quiz_instance_id, None)
    context.user_data.pop("current_quiz_instance_id", None)
    
    keys_to_pop = [
        "selected_quiz_type_key", "selected_quiz_type_display_name", "questions_for_quiz",
        "selected_course_id_for_unit_quiz", "available_courses_for_unit_quiz",
        "current_course_page_for_unit_quiz", "selected_course_name_for_unit_quiz",
        "available_units_for_course", "current_unit_page_for_course",
        "selected_unit_id", "selected_unit_name", "question_count_for_quiz"
    ]
    for key in keys_to_pop:
        context.user_data.pop(key, None)
    for key_ud in list(context.user_data.keys()): 
        if key_ud.startswith("quiz_setup_") or key_ud.startswith("qtimer_"):
            context.user_data.pop(key_ud, None)
            
    await main_menu_callback(update, context) # This is from common.py
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
    logger.debug("[QUIZ_DEBUG] quiz_menu_entry called!") # ADDED FOR DEBUGGING BUTTON PRESS
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
        "current_quiz_instance_id"
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
            course_id_from_cb = parts[-2] 
            new_page = int(parts[-1]) 
            if str(course_id_from_cb) != str(selected_course_id):
                logger.warning(f"Mismatched course_id in unit pagination. CB: {course_id_from_cb}, Context: {selected_course_id}. Reverting to course selection.")
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
    unit_id = context.user_data.get("selected_unit_id") 
    course_id_for_unit_quiz = context.user_data.get("selected_course_id_for_unit_quiz")

    if callback_data.startswith("quiz_count_back_to_unit_selection_"):
        course_id_from_cb = callback_data.replace("quiz_count_back_to_unit_selection_", "", 1)
        if str(course_id_from_cb) != str(course_id_for_unit_quiz):
            logger.warning(f"Mismatched course_id in count back. CB: {course_id_from_cb}, Context: {course_id_for_unit_quiz}. Reverting to type selection.")
            keyboard = create_quiz_type_keyboard()
            await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ، يرجى اختيار نوع الاختبار مرة أخرى.", reply_markup=keyboard)
            return SELECT_QUIZ_TYPE
        
        units_for_course = context.user_data.get("available_units_for_course", [])
        current_unit_page = context.user_data.get("current_unit_page_for_course", 0)
        keyboard = create_unit_selection_keyboard(units_for_course, course_id_for_unit_quiz, current_unit_page)
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text=f"اختر الوحدة الدراسية من مقرر \"{context.user_data['selected_course_name_for_unit_quiz']}\":", reply_markup=keyboard)
        return SELECT_UNIT_FOR_COURSE

    elif callback_data == "quiz_type_back_to_type_selection":
        keyboard = create_quiz_type_keyboard()
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="🧠 اختر نوع الاختبار:", reply_markup=keyboard)
        return SELECT_QUIZ_TYPE

    quiz_setup_key = f"quiz_setup_{quiz_type}_{unit_id}"
    quiz_data = context.user_data.get(quiz_setup_key)

    if not quiz_data or "questions" not in quiz_data:
        logger.error(f"Quiz data or questions not found in user_data for key {quiz_setup_key}. User: {user_id}")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="عذراً، حدث خطأ في إعداد الاختبار. يرجى المحاولة من البداية.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    all_questions = quiz_data["questions"]
    max_questions = len(all_questions)

    if callback_data == "num_questions_all":
        num_questions = max_questions
    elif callback_data.startswith("num_questions_"):
        try:
            num_questions = int(callback_data.replace("num_questions_", ""))
            if not (0 < num_questions <= max_questions):
                logger.warning(f"User {user_id} selected invalid number of questions: {num_questions}. Max was {max_questions}. Defaulting to max.")
                num_questions = max_questions
        except ValueError:
            logger.error(f"Invalid number of questions in callback: {callback_data}. Defaulting to max.")
            num_questions = max_questions
    else:
        logger.error(f"Unknown callback for question count: {callback_data}. Defaulting to max.")
        num_questions = max_questions

    context.user_data["question_count_for_quiz"] = num_questions
    
    return await start_actual_quiz(update, context) 


async def start_actual_quiz(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer() 

    quiz_type = context.user_data.get("selected_quiz_type_key")
    unit_id = context.user_data.get("selected_unit_id") 
    num_questions_to_ask = context.user_data.get("question_count_for_quiz")

    quiz_setup_key = f"quiz_setup_{quiz_type}_{unit_id}"
    quiz_data = context.user_data.get(quiz_setup_key)

    if not quiz_data or "questions" not in quiz_data or not num_questions_to_ask:
        logger.error(f"Missing critical quiz setup data for user {user_id} at start_actual_quiz. Key: {quiz_setup_key}, NumQ: {num_questions_to_ask}")
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="حدث خطأ فادح أثناء بدء الاختبار. يرجى المحاولة من جديد.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    all_questions_for_scope = quiz_data["questions"]
    quiz_name_for_display = quiz_data.get("quiz_name", "اختبار")
    quiz_scope_id_for_db = quiz_data.get("scope_id") 

    if num_questions_to_ask > len(all_questions_for_scope):
        logger.warning(f"Requested {num_questions_to_ask} questions, but only {len(all_questions_for_scope)} available for {quiz_setup_key}. Using all available.")
        num_questions_to_ask = len(all_questions_for_scope)
    
    if num_questions_to_ask == 0:
        logger.warning(f"No questions to ask for {quiz_setup_key} (num_questions_to_ask is 0). User {user_id}")
        await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=query.message.message_id, text="لا توجد أسئلة لبدء هذا الاختبار. يرجى اختيار نطاق آخر.", reply_markup=create_quiz_type_keyboard())
        return SELECT_QUIZ_TYPE

    questions_for_this_quiz = random.sample(all_questions_for_scope, num_questions_to_ask)
    
    db_m_instance = context.bot_data.get("db_manager")
    if not db_m_instance:
        logger.critical(f"CRITICAL: db_manager NOT FOUND in context.bot_data at start_actual_quiz for user {user_id}. Quiz stats will NOT be saved.")

    quiz_instance_id = f"quiz_{user_id}_{chat_id}_{datetime.now().timestamp()}"
    context.user_data["current_quiz_instance_id"] = quiz_instance_id

    logger.info(f"Starting quiz instance {quiz_instance_id} for user {user_id}. Type: {quiz_type}, Scope: {unit_id}, Name: '{quiz_name_for_display}', Questions: {num_questions_to_ask}")

    quiz_logic_instance = QuizLogic(
        user_id=user_id,
        chat_id=chat_id,
        questions=questions_for_this_quiz,
        quiz_name=quiz_name_for_display,
        quiz_type_for_db_log=quiz_type,
        quiz_scope_id=quiz_scope_id_for_db,
        total_questions_for_db_log=num_questions_to_ask,
        time_limit_per_question=DEFAULT_QUESTION_TIME_LIMIT, 
        quiz_instance_id_for_logging=quiz_instance_id,
        db_manager_instance=db_m_instance 
    )
    
    context.user_data[quiz_instance_id] = quiz_logic_instance
    context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = query.message.message_id # Store for potential edit on results

    # Pass bot, context, and update to start_quiz
    await quiz_logic_instance.start_quiz(context.bot, context, update) 
    return TAKING_QUIZ


async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        parts = query.data.split("_")
        # Callback format: ans_QUIZINSTANCEID_QINDEX_OPTIONID
        # QUIZINSTANCEID can contain underscores if chat_id or user_id had them (unlikely for numeric IDs but good to be safe)
        # Example: ans_quiz_123_456_1622547850.123_0_789
        # parts[0] = "ans"
        # parts[1:-2] = quiz_instance_id parts
        # parts[-2] = question_index
        # parts[-1] = option_id
        quiz_instance_id_from_cb = "_".join(parts[1:-2]) 
        question_idx_str = parts[-2]
        chosen_option_id_str = parts[-1]
        
        question_index = int(question_idx_str)
        # chosen_option_id can be string or int from API, QuizLogic expects int for its internal logic if it converts
        # For callback, it's usually an ID (string or int). Let's assume QuizLogic handles conversion if needed.
        # The original QuizLogic took chosen_option_id as int. Let's keep it that way.
        chosen_option_id = int(chosen_option_id_str) 
    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing quiz answer callback data: '{query.data}'. Error: {e}. User: {user_id}")
        return TAKING_QUIZ 

    logger.debug(f"handle_quiz_answer called for user {user_id} with data: {query.data}. Parsed: quiz_id={quiz_instance_id_from_cb}, q_idx={question_index}, opt_id={chosen_option_id}")

    current_quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    
    if quiz_instance_id_from_cb != current_quiz_instance_id:
        logger.warning(f"User {user_id} answered for an old/mismatched quiz instance. CB: {quiz_instance_id_from_cb}, Active: {current_quiz_instance_id}. Ignoring.")
        return TAKING_QUIZ

    quiz_instance = context.user_data.get(current_quiz_instance_id)

    if not quiz_instance or not isinstance(quiz_instance, QuizLogic):
        logger.error(f"No active QuizLogic instance found for {current_quiz_instance_id} (user {user_id}) in handle_quiz_answer.")
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ أثناء معالجة إجابتك. سنحاول إعادتك للقائمة.")
        return await go_to_main_menu_from_quiz(update, context) 

    logger.debug(f"Found active QuizLogic instance {current_quiz_instance_id} for user {user_id}. Delegating to its handle_answer.")
    
    context.user_data[f"last_quiz_interaction_message_id_{query.message.chat_id}"] = query.message.message_id

    next_state = await quiz_instance.handle_answer(
        bot=context.bot, 
        context=context, 
        update_for_message_edit=update, 
        question_index=question_index, 
        chosen_option_id=chosen_option_id,
        user_id_from_handler=user_id # Pass user_id, QuizLogic's param is user_id_from_handler
    )
    
    if next_state == SHOWING_RESULTS:
        context.user_data.pop(current_quiz_instance_id, None)
        context.user_data.pop("current_quiz_instance_id", None)
        logger.info(f"Quiz {current_quiz_instance_id} ended for user {user_id}. Instance removed from user_data.")
        return SHOWING_RESULTS 
    elif next_state == END: 
        logger.warning(f"QuizLogic returned END directly from handle_answer for {current_quiz_instance_id}.")
        context.user_data.pop(current_quiz_instance_id, None)
        context.user_data.pop("current_quiz_instance_id", None)
        return await go_to_main_menu_from_quiz(update, context)
        
    return TAKING_QUIZ 


async def quiz_timeout_global_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("انتهى وقت هذا السؤال.")
    logger.info(f"Global quiz timeout handler triggered for user {user_id} via callback: {query.data}")

    try:
        parts = query.data.split("_")
        # Expected callback_data: timeout_QUIZINSTANCEID_QINDEX
        quiz_instance_id_from_cb = "_".join(parts[1:-1])
        question_idx_str = parts[-1]
        question_index = int(question_idx_str)
    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing quiz timeout callback data: '{query.data}'. Error: {e}. User: {user_id}")
        return TAKING_QUIZ

    current_quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if quiz_instance_id_from_cb != current_quiz_instance_id:
        logger.warning(f"User {user_id} timeout for an old/mismatched quiz instance. CB: {quiz_instance_id_from_cb}, Active: {current_quiz_instance_id}. Ignoring.")
        return TAKING_QUIZ

    quiz_instance = context.user_data.get(current_quiz_instance_id)
    if not quiz_instance or not isinstance(quiz_instance, QuizLogic):
        logger.error(f"No active QuizLogic instance found for {current_quiz_instance_id} (user {user_id}) in quiz_timeout_global_handler.")
        return await go_to_main_menu_from_quiz(update, context)
    
    # The job data for timeout should contain message_id and question_was_image
    # This handler is triggered by a button press from timeout, not directly from job.
    # The button's callback_data (query.data) is what we parse.
    # We need to retrieve the original message_id and question_was_image from context if they were stored by the job.
    # However, the QuizLogic.handle_timeout expects these. This global handler might be redundant if the job directly calls QuizLogic.handle_timeout.
    # The current QuizLogic.question_timeout_callback_wrapper calls quiz_instance.handle_timeout directly.
    # This quiz_timeout_global_handler seems to be for a button press with callback like "timeout_..."
    # Let's assume this button is NOT used and timeout is handled by the job queue calling question_timeout_callback_wrapper.
    # If this handler IS used, it needs to get message_id and question_was_image from somewhere.
    # For now, I will assume it's not the primary path for timeouts and leave it as is, but it's a potential issue.
    # The QuizLogic.handle_timeout expects: bot, context, update_for_message_edit, question_index, user_id_from_job, message_id_from_job, question_was_image
    # This handler doesn't have message_id_from_job or question_was_image easily.
    # This indicates a potential design flaw if this handler is still active for timeouts.
    # Given the wrapper calls QuizLogic.handle_timeout, this might be dead code or for a different timeout mechanism.
    # For safety, let's log a warning if it's ever hit.
    logger.warning(f"[quiz_timeout_global_handler] - This handler was called for {current_quiz_instance_id}. Review if this is expected, as timeouts should be handled by JobQueue -> question_timeout_callback_wrapper -> QuizLogic.handle_timeout.")
    
    # To make it somewhat work, we'd need to fetch the message_id from the query object if it's an edit of the question message
    message_id_for_edit = query.message.message_id if query and query.message else None

    next_state = await quiz_instance.handle_timeout(
        bot=context.bot, 
        context=context, 
        update_for_message_edit=update, # Pass the update from the button press
        question_index=question_index,
        user_id_from_job=user_id, # User who pressed the button
        message_id_from_job=message_id_for_edit, # Message that had the timeout button
        question_was_image=quiz_instance.last_question_is_image # Best guess for question_was_image
    )
    
    if next_state == SHOWING_RESULTS:
        context.user_data.pop(current_quiz_instance_id, None)
        context.user_data.pop("current_quiz_instance_id", None)
        return SHOWING_RESULTS
    elif next_state == END:
        context.user_data.pop(current_quiz_instance_id, None)
        context.user_data.pop("current_quiz_instance_id", None)
        return await go_to_main_menu_from_quiz(update, context)
        
    return TAKING_QUIZ


async def show_quiz_results_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    callback_data = query.data

    logger.info(f"User {user_id} in SHOWING_RESULTS state, callback: {callback_data}")

    if callback_data == "quiz_show_my_stats":
        logger.info(f"User {user_id} requested to see their stats from quiz results. This should ideally transition to a stats handler.")
        # This button's callback should ideally be handled by a global stats handler or stats_conv_handler entry point.
        # For now, sending to main menu, user can navigate to stats.
        # A text message could guide the user.
        await safe_edit_message_text(context.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="لعرض إحصائياتك، يرجى الذهاب إلى القائمة الرئيسية ثم اختيار قسم الإحصائيات.", reply_markup=None)
        # await query.message.reply_text("لعرض إحصائياتك، يرجى الذهاب إلى القائمة الرئيسية ثم اختيار قسم الإحصائيات.")
        # return ConversationHandler.END # Or return to a specific stats state if integrated
        # For now, let's make it go to main_menu to be consistent with other end paths
        return await go_to_main_menu_from_quiz(update, context) # This cleans up and shows main menu

    elif callback_data == "quiz_menu_entry": # Start new quiz
        return await quiz_menu_entry(update, context)
    
    elif callback_data == "main_menu": # Go to main menu
        return await go_to_main_menu_from_quiz(update, context)

    logger.warning(f"Unhandled callback '{callback_data}' in show_quiz_results_entry for user {user_id}.")
    return SHOWING_RESULTS # Stay in this state if callback is not recognized


# Conversation Handler Setup
print("[QUIZ_PY_DEBUG] About to define quiz_conv_handler...")
quiz_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(quiz_menu_entry, pattern='^start_quiz$')],
    states={
        SELECT_QUIZ_TYPE: [
            CallbackQueryHandler(select_quiz_type, pattern='^quiz_type_.*$'),
            CallbackQueryHandler(go_to_main_menu_from_quiz, pattern='^main_menu$')
        ],
        SELECT_COURSE_FOR_UNIT_QUIZ: [
            CallbackQueryHandler(select_course_for_unit_quiz, pattern='^quiz_course_select_.*$'),
            CallbackQueryHandler(select_course_for_unit_quiz, pattern='^quiz_course_page_.*$'),
            CallbackQueryHandler(select_quiz_type, pattern='^quiz_type_back_to_type_selection$') # Back to type selection
        ],
        SELECT_UNIT_FOR_COURSE: [
            CallbackQueryHandler(select_unit_for_course, pattern='^quiz_unit_select_.*$'),
            CallbackQueryHandler(select_unit_for_course, pattern='^quiz_unit_page_.*$'),
            CallbackQueryHandler(select_course_for_unit_quiz, pattern='^quiz_unit_back_to_course_selection$') # Back to course selection
        ],
        ENTER_QUESTION_COUNT: [
            CallbackQueryHandler(select_question_count, pattern='^num_questions_.*$'),
            CallbackQueryHandler(select_question_count, pattern='^quiz_count_back_to_unit_selection_.*$'), # Back to unit selection
            CallbackQueryHandler(select_quiz_type, pattern='^quiz_type_back_to_type_selection$') # Back to type selection (general)
        ],
        TAKING_QUIZ: [
            CallbackQueryHandler(handle_quiz_answer, pattern='^ans_.*$'),
            # Timeout is primarily handled by job_queue calling question_timeout_callback_wrapper.
            # The button based timeout_global_handler is a fallback or for different mechanism.
            CallbackQueryHandler(quiz_timeout_global_handler, pattern='^timeout_.*$') 
        ],
        SHOWING_RESULTS: [
            CallbackQueryHandler(show_quiz_results_entry, pattern='^quiz_show_my_stats$'),
            CallbackQueryHandler(quiz_menu_entry, pattern='^quiz_menu_entry$'), # For starting a new quiz
            CallbackQueryHandler(go_to_main_menu_from_quiz, pattern='^main_menu$')  # Go to main menu
        ]
    },
    fallbacks=[
        CommandHandler('start', start_command_fallback_for_quiz), # Fallback for /start during quiz
        CallbackQueryHandler(go_to_main_menu_from_quiz, pattern='^main_menu$') # General fallback to main menu
    ],
    map_to_parent={
        END: MAIN_MENU 
    },
    name="quiz_conversation", 
     persistent=True
)
print("[QUIZ_PY_DEBUG] quiz_conv_handler defined successfully.")
