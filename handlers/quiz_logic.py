# -*- coding: utf-8 -*-
"""Core logic for handling quizzes in the Chemistry Telegram Bot (Corrected v7 - Added detailed logging for question data)."""

import random
import time
import uuid
import re
import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import CallbackContext
from telegram.error import BadRequest, TelegramError

# --- Corrected Imports --- 
# Assuming bot.py adds the project root to sys.path
from config import (
    logger,
    MAIN_MENU, TAKING_QUIZ, SHOWING_RESULTS,
    FEEDBACK_DELAY, ENABLE_QUESTION_TIMER,
    NUM_OPTIONS
)
# **FIX**: Import helpers directly from the utils module
from utils.helpers import (
    safe_send_message, safe_edit_message_text,
    remove_job_if_exists
)
# **FIX**: Import common keyboard function directly from handlers.common
from handlers.common import create_main_menu_keyboard
from utils.api_client import fetch_from_api, transform_api_question
from database.manager import DB_MANAGER

# --- Constants --- 
QUESTION_TIMER_SECONDS = 180 # 3 minutes

# --- Timer Callback --- 

async def question_timer_callback(context: CallbackContext):
    """Handles the timeout for a single question. Calls skip handler marking as timed out."""
    job_context = context.job.context
    chat_id = job_context.get("chat_id")
    user_id = job_context.get("user_id")
    quiz_id = job_context.get("quiz_id")
    question_index = job_context.get("question_index")
    
    if None in [chat_id, user_id, quiz_id, question_index]:
        logger.error(f"[TIMER] Missing context in question_timer_callback: {job_context}")
        return
        
    logger.info(f"[TIMER] Question timer expired for q:{question_index} quiz:{quiz_id} user:{user_id}.")

    # Access user_data via dispatcher (Important for jobs)
    if not hasattr(context, "dispatcher") or not context.dispatcher:
         logger.error("[TIMER] Dispatcher not found in context for question_timer_callback.")
         return
    user_data = context.dispatcher.user_data.get(user_id, {})
    quiz_data = user_data.get("current_quiz")

    # Check if the quiz is still active and the timed-out question is the current one
    if (quiz_data and quiz_data.get("quiz_id") == quiz_id and
            quiz_data.get("current_question_index") == question_index and
            not quiz_data.get("finished") and
            quiz_data["answers"][question_index] is None): # Ensure not already answered/skipped

        logger.info(f"[QUIZ LOGIC] Question {question_index + 1} timed out for user {user_id}. Marking as WRONG.")
        # Send message indicating timeout and wrong answer
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text=f"⏰ انتهى وقت السؤال {question_index + 1}! سيتم اعتباره إجابة خاطئة.")

        # Call the skip handler, marking it as timed out (which now means wrong)
        await skip_question_callback(context.bot, chat_id, user_id, quiz_id, question_index, context, timed_out=True, error_occurred=False)
    else:
        logger.info(f"[TIMER] Quiz {quiz_id} ended or question {question_index} already handled, ignoring timer.")

# --- Quiz Core Functions --- 

async def start_quiz_logic(update: Update, context: CallbackContext) -> int:
    """Fetches questions, initializes quiz state, and sends the first question.
       Handles both API fetching and using pre-fetched random questions.
    """
    query = update.callback_query # Might be called from callback
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id

    # Retrieve selections made in previous conversation steps
    quiz_selection = context.user_data.get("quiz_selection")
    if not quiz_selection or "type" not in quiz_selection or "count" not in quiz_selection or "endpoint" not in quiz_selection:
        logger.error(f"[QUIZ LOGIC] start_quiz called for user {user_id} without complete quiz_selection (missing type, count, or endpoint). Selection: {quiz_selection}")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء بدء الاختبار (لم يتم تحديد نوع أو عدد الأسئلة أو نقطة النهاية). يرجى المحاولة مرة أخرى.")
        kb = create_main_menu_keyboard(user_id)
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    quiz_type = quiz_selection["type"]
    quiz_scope_id = quiz_selection.get("scope_id")
    num_questions = quiz_selection["count"]
    max_available = quiz_selection.get("max_questions", num_questions)
    questions_endpoint = quiz_selection["endpoint"] # Can be API path or "random_local"

    # Validate num_questions
    if not isinstance(num_questions, int) or num_questions <= 0:
        logger.error(f"[QUIZ LOGIC] Invalid number of questions ({num_questions}) for user {user_id}. Aborting quiz start.")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text=f"عدد الأسئلة غير صالح ({num_questions}). يرجى المحاولة مرة أخرى.")
        kb = create_main_menu_keyboard(user_id)
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    # Ensure num_questions doesn't exceed max available
    num_questions = min(num_questions, max_available)
    if num_questions <= 0:
         logger.error(f"[QUIZ LOGIC] No questions available ({max_available}) for user {user_id}. Aborting quiz start.")
         # **FIX**: Use the actual safe_send_message function
         await safe_send_message(context.bot, chat_id, text="لا توجد أسئلة متاحة لهذا الاختيار. لا يمكن بدء الاختبار.")
         kb = create_main_menu_keyboard(user_id)
         # **FIX**: Use the actual safe_send_message function
         await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
         return MAIN_MENU

    logger.info(f"[QUIZ LOGIC] Starting quiz for user {user_id}: type={quiz_type}, scope={quiz_scope_id}, count={num_questions}, source={questions_endpoint}")

    quiz_questions = []

    # --- Get Questions (API or Local Random) --- 
    if questions_endpoint == "random_local":
        # Use pre-fetched questions stored in user_data
        all_random_questions = context.user_data.get("all_random_questions")
        if not all_random_questions or not isinstance(all_random_questions, list):
            logger.error(f"[QUIZ LOGIC] Random quiz requested but 'all_random_questions' missing or invalid in user_data for user {user_id}.")
            # **FIX**: Use the actual safe_send_message function
            await safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء تحميل الأسئلة العشوائية المجمعة. يرجى المحاولة مرة أخرى.")
            kb = create_main_menu_keyboard(user_id)
            # **FIX**: Use the actual safe_send_message function
            await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
            return MAIN_MENU
        
        if len(all_random_questions) < num_questions:
            logger.warning(f"[QUIZ LOGIC] Requested {num_questions} random questions, but only {len(all_random_questions)} available in total. Using all available.")
            num_questions = len(all_random_questions)
            quiz_questions = all_random_questions # Use all if requested more than available
        else:
            logger.info(f"[QUIZ LOGIC] Sampling {num_questions} questions from {len(all_random_questions)} pre-fetched random questions.")
            quiz_questions = random.sample(all_random_questions, num_questions)
            
        # Clear the cached questions after sampling
        context.user_data.pop("all_random_questions", None)
        logger.debug("[QUIZ LOGIC] Cleared 'all_random_questions' from user_data.")

    else: # Fetch from specific API endpoint
        params = {"limit": num_questions}
        logger.info(f"[API] Fetching {num_questions} questions from {questions_endpoint} with params {params}")
        api_questions_response = fetch_from_api(questions_endpoint, params=params)

        # Handle API Response
        if api_questions_response == "TIMEOUT":
            logger.error(f"[API] Timeout fetching questions from {questions_endpoint} (user {user_id}).")
            # **FIX**: Use the actual safe_send_message function
            await safe_send_message(context.bot, chat_id, text="⏳ تعذر تحميل أسئلة الاختبار (مهلة الاتصال). يرجى المحاولة مرة أخرى لاحقاً.")
            kb = create_main_menu_keyboard(user_id)
            # **FIX**: Use the actual safe_send_message function
            await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
            return MAIN_MENU
        elif not isinstance(api_questions_response, list):
            logger.error(f"[API] Failed to fetch questions or invalid format from {questions_endpoint} (user {user_id}). Response: {api_questions_response}")
            # **FIX**: Use the actual safe_send_message function
            await safe_send_message(context.bot, chat_id, text="⚠️ تعذر تحميل أسئلة الاختبار أو أن التنسيق غير صالح. يرجى المحاولة مرة أخرى لاحقاً.")
            kb = create_main_menu_keyboard(user_id)
            # **FIX**: Use the actual safe_send_message function
            await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
            return MAIN_MENU

        # Transform and Validate Questions from API
        valid_api_questions = []
        for q_data in api_questions_response:
            transformed_q = transform_api_question(q_data)
            if transformed_q and transformed_q.get("correct_answer") is not None: # Check for correct_answer index
                valid_api_questions.append(transformed_q)
            else:
                logger.warning(f"[QUIZ LOGIC] Skipping invalid question data (missing/null correct_answer or other issues) received from API ({questions_endpoint}): {q_data}")
        
        # Adjust num_questions if API returned fewer valid questions or didn't respect limit
        if len(valid_api_questions) > num_questions:
            logger.info(f"[QUIZ LOGIC] API ({questions_endpoint}) returned {len(valid_api_questions)} valid questions, sampling {num_questions}.")
            quiz_questions = random.sample(valid_api_questions, num_questions)
        elif len(valid_api_questions) < num_questions:
            logger.warning(f"[QUIZ LOGIC] Requested {num_questions} questions from {questions_endpoint}, but only got {len(valid_api_questions)} valid ones.")
            num_questions = len(valid_api_questions) # Adjust count to actual number
            quiz_questions = valid_api_questions
        else:
             quiz_questions = valid_api_questions # Use all fetched and valid questions

    # Final check if we have any questions to proceed with
    if num_questions == 0 or not quiz_questions:
        logger.error(f"[QUIZ LOGIC] No valid questions found for user {user_id} after processing source '{questions_endpoint}'. Aborting.")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text="لم يتم العثور على أسئلة صالحة لهذا الاختبار. يرجى المحاولة مرة أخرى أو اختيار موضوع آخر.")
        kb = create_main_menu_keyboard(user_id)
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    # --- Initialize Quiz State in user_data --- 
    quiz_id = str(uuid.uuid4()) # Unique ID for this quiz instance
    start_time = datetime.now() # Record start time
    context.user_data["current_quiz"] = {
        "quiz_id": quiz_id,
        "questions": quiz_questions,
        "total_questions": num_questions,
        "current_question_index": 0,
        "answers": [None] * num_questions, # Store user answer index (or -1 for skip, -2 for timeout-wrong, -3 for error)
        "correct_count": 0,
        "wrong_count": 0,
        "skipped_count": 0,
        "start_time": start_time, # Store start time object
        "quiz_type": quiz_type, # Store type (random, lesson, unit, course)
        "quiz_scope_id": quiz_scope_id, # Store associated ID
        "finished": False,
        "last_question_message_id": None,
        "question_timer_job_name": None
    }
    logger.info(f"[QUIZ LOGIC] Initialized quiz {quiz_id} for user {user_id} with {num_questions} questions.")

    # --- Send the First Question --- 
    await send_question(context.bot, chat_id, user_id, quiz_id, 0, context)

    return TAKING_QUIZ # Transition to the quiz-taking state

async def send_question(bot, chat_id: int, user_id: int, quiz_id: str, question_index: int, context: CallbackContext):
    """Sends a specific question to the user, including text, image, and options."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    # Validate quiz state
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ LOGIC] send_question called for inactive/mismatched quiz {quiz_id} user {user_id}")
        return
    if question_index >= quiz_data["total_questions"]:
        logger.error(f"[QUIZ LOGIC] send_question index out of bounds ({question_index}) for quiz {quiz_id}")
        await show_quiz_results(bot, chat_id, user_id, quiz_id, context)
        return

    question = quiz_data["questions"][question_index]
    quiz_data["current_question_index"] = question_index # Update current index

    # *** ADDED LOGGING ***
    logger.debug(f"[QUIZ LOGIC] Preparing question {question_index} (ID: {question.get('question_id')}) for quiz {quiz_id}. Data: {question}")

    # --- Prepare Question Text and Media --- 
    question_text = f"*السؤال {question_index + 1} من {quiz_data['total_questions']}*\n\n"
    if question.get("question_text"):
        question_text += question["question_text"]
    
    question_image = question.get("image_url") # Corrected key based on transform_api_question

    # --- Prepare Options and Keyboard --- 
    options_texts = [
        question.get("option1"), question.get("option2"),
        question.get("option3"), question.get("option4")
    ]
    options_images = [
        question.get("option1_image"), question.get("option2_image"),
        question.get("option3_image"), question.get("option4_image")
    ]
    
    keyboard_buttons = []
    has_image_options = any(img for img in options_images if img)
    
    row = []
    for i in range(NUM_OPTIONS): # NUM_OPTIONS is likely 4
        opt_text = options_texts[i]
        opt_image = options_images[i]
        button_text = ""
        
        # *** ADDED LOGGING ***
        logger.debug(f"[QUIZ LOGIC] Processing option {i}: Text='{opt_text}', Image='{opt_image}'")

        if opt_text:
            button_text = opt_text
        elif opt_image:
            button_text = f"(صورة الخيار {i+1})" # Placeholder text for image option
        else:
            # *** ADDED LOGGING ***
            logger.debug(f"[QUIZ LOGIC] Skipping option {i} as both text and image are missing.")
            continue # Skip if both text and image are missing for this option
            
        callback_data = f"quiz_{quiz_id}_ans_{question_index}_{i}"
        row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
        
        # Arrange buttons in rows of 2
        if len(row) == 2:
            keyboard_buttons.append(row)
            row = []
            
    if row: # Add remaining buttons if odd number
        keyboard_buttons.append(row)

    # *** ADDED LOGGING ***
    logger.debug(f"[QUIZ LOGIC] Built options keyboard rows (before adding skip): {keyboard_buttons}")

    # Add Skip button
    keyboard_buttons.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f"quiz_{quiz_id}_skip_{question_index}")])
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)

    # --- Send Message (Text or Photo) --- 
    sent_message = None
    send_error = None
    try:
        if question_image:
            logger.debug(f"[QUIZ LOGIC] Sending question {question_index} with image: {question_image}")
            sent_message = await bot.send_photo(
                chat_id=chat_id,
                photo=question_image,
                caption=question_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            logger.debug(f"[QUIZ LOGIC] Sending question {question_index} as text.")
            sent_message = await bot.send_message(
                chat_id=chat_id,
                text=question_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    except BadRequest as e:
        # Handle potential errors like invalid image URL or Markdown issues
        logger.error(f"[QUIZ LOGIC] BadRequest sending question {question_index} (quiz {quiz_id}): {e}. Question data: {question}")
        send_error = e
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text=f"⚠️ حدث خطأ أثناء إرسال السؤال {question_index + 1}. سيتم تخطيه تلقائياً.")
        # Call skip handler marking as error
        await skip_question_callback(bot, chat_id, user_id, quiz_id, question_index, context, timed_out=False, error_occurred=True)
        return # Stop further processing for this question
    except TelegramError as e:
        logger.error(f"[QUIZ LOGIC] TelegramError sending question {question_index} (quiz {quiz_id}): {e}. Question data: {question}")
        send_error = e
        # Attempt to notify user, but might fail if bot is blocked etc.
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text=f"⚠️ حدث خطأ غير متوقع أثناء إرسال السؤال {question_index + 1}. سيتم تخطيه تلقائياً.")
        # Call skip handler marking as error
        await skip_question_callback(bot, chat_id, user_id, quiz_id, question_index, context, timed_out=False, error_occurred=True)
        return # Stop further processing for this question

    if sent_message:
        quiz_data["last_question_message_id"] = sent_message.message_id
        logger.debug(f"[QUIZ LOGIC] Stored message ID {sent_message.message_id} for question {question_index}")

        # --- Start Question Timer --- 
        if ENABLE_QUESTION_TIMER and hasattr(context, 'job_queue') and context.job_queue:
            job_name = f"quiz_{quiz_id}_q_{question_index}_timer"
            # Remove previous timer if exists
            remove_job_if_exists(job_name, context)
            
            timer_context = {
                "chat_id": chat_id,
                "user_id": user_id,
                "quiz_id": quiz_id,
                "question_index": question_index
            }
            context.job_queue.run_once(
                question_timer_callback,
                QUESTION_TIMER_SECONDS,
                name=job_name,
                chat_id=chat_id, # Pass chat_id for job queue context
                user_id=user_id, # Pass user_id for job queue context
                context=timer_context
            )
            quiz_data["question_timer_job_name"] = job_name
            logger.info(f"[QUIZ LOGIC] Started timer ({QUESTION_TIMER_SECONDS}s) for question {question_index}, job: {job_name}")
        elif ENABLE_QUESTION_TIMER:
             logger.warning("[QUIZ LOGIC] ENABLE_QUESTION_TIMER is True, but JobQueue not available in context. Timer not started.")

    else:
        logger.error(f"[QUIZ LOGIC] Failed to get sent_message object after sending question {question_index} (quiz {quiz_id}). Send error was: {send_error}")
        # If sending failed earlier, skip_question_callback was already called.
        # If sending succeeded but message object is None (unlikely), we might need to handle it.
        # For now, assume skip was called if send_error exists.
        if not send_error:
             # **FIX**: Use the actual safe_send_message function
             await safe_send_message(context.bot, chat_id, text=f"⚠️ حدث خطأ غير معروف بعد إرسال السؤال {question_index + 1}. سيتم تخطيه تلقائياً.")
             await skip_question_callback(bot, chat_id, user_id, quiz_id, question_index, context, timed_out=False, error_occurred=True)

async def handle_answer(update: Update, context: CallbackContext) -> int:
    """Handles user's answer selection from inline keyboard."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    user_id = query.from_user.id
    chat_id = query.message.chat_id
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    # --- Extract data from callback_data --- 
    # Format: quiz_{quiz_id}_ans_{question_index}_{answer_index}
    match = re.match(r"quiz_(.+)_ans_(\d+)_(\d+)", query.data)
    if not match:
        logger.error(f"[QUIZ LOGIC] Invalid callback data format for answer: {query.data}")
        # **FIX**: Use the actual safe_edit_message_text function
        await safe_edit_message_text(query.message, text="حدث خطأ في بيانات الزر. يرجى المحاولة مرة أخرى.")
        return TAKING_QUIZ # Stay in the same state

    quiz_id, question_index_str, answer_index_str = match.groups()
    question_index = int(question_index_str)
    selected_answer_index = int(answer_index_str)

    # --- Validate Quiz State --- 
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ LOGIC] handle_answer called for inactive/mismatched quiz {quiz_id} user {user_id}")
        # **FIX**: Use the actual safe_edit_message_text function
        await safe_edit_message_text(query.message, text="يبدو أن هذا الاختبار قد انتهى أو لم يعد صالحاً.")
        return TAKING_QUIZ
    if question_index != quiz_data.get("current_question_index"):
        logger.warning(f"[QUIZ LOGIC] User {user_id} answered question {question_index} but current is {quiz_data.get('current_question_index')}. Ignoring.")
        # **FIX**: Use the actual safe_edit_message_text function
        await safe_edit_message_text(query.message, text="لقد أجبت على سؤال سابق. يرجى الإجابة على السؤال الحالي.")
        return TAKING_QUIZ
    if quiz_data["answers"][question_index] is not None:
        logger.info(f"[QUIZ LOGIC] User {user_id} tried to answer question {question_index} again. Ignoring.")
        # **FIX**: Use the actual safe_edit_message_text function
        await safe_edit_message_text(query.message, text="لقد أجبت على هذا السؤال بالفعل.")
        return TAKING_QUIZ

    # --- Stop Timer --- 
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        remove_job_if_exists(timer_job_name, context)
        logger.info(f"[QUIZ LOGIC] Removed timer job {timer_job_name} for question {question_index}.")
        quiz_data["question_timer_job_name"] = None # Clear the job name

    # --- Check Answer --- 
    question = quiz_data["questions"][question_index]
    correct_answer_index = question.get("correct_answer") # This is the 0-based index

    if correct_answer_index is None:
         logger.error(f"[QUIZ LOGIC] Question {question_index} (ID: {question.get('question_id')}) in quiz {quiz_id} has no correct_answer index! Skipping.")
         # **FIX**: Use the actual safe_edit_message_text function
         await safe_edit_message_text(query.message, text="⚠️ حدث خطأ في بيانات هذا السؤال (لا توجد إجابة صحيحة محددة). سيتم تخطيه.")
         await skip_question_callback(context.bot, chat_id, user_id, quiz_id, question_index, context, timed_out=False, error_occurred=True)
         return TAKING_QUIZ

    is_correct = (selected_answer_index == correct_answer_index)
    quiz_data["answers"][question_index] = selected_answer_index # Store user's choice index

    feedback_text = ""
    if is_correct:
        quiz_data["correct_count"] += 1
        feedback_text = "✅ إجابة صحيحة!"
        logger.info(f"[QUIZ LOGIC] User {user_id} answered question {question_index} CORRECTLY (Selected: {selected_answer_index}, Correct: {correct_answer_index}).")
    else:
        quiz_data["wrong_count"] += 1
        feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة هي الخيار رقم {correct_answer_index + 1}."
        logger.info(f"[QUIZ LOGIC] User {user_id} answered question {question_index} INCORRECTLY (Selected: {selected_answer_index}, Correct: {correct_answer_index}).")

    # Add explanation if available
    explanation = question.get("explanation")
    if explanation:
        feedback_text += f"\n\n*الشرح:* {explanation}"

    # --- Edit Message to Show Feedback --- 
    # Rebuild keyboard showing only the correct answer highlighted (or user's wrong choice)
    options_texts = [
        question.get("option1"), question.get("option2"),
        question.get("option3"), question.get("option4")
    ]
    options_images = [
        question.get("option1_image"), question.get("option2_image"),
        question.get("option3_image"), question.get("option4_image")
    ]
    feedback_keyboard_buttons = []
    row = []
    for i in range(NUM_OPTIONS):
        opt_text = options_texts[i]
        opt_image = options_images[i]
        button_text = ""
        prefix = ""

        if opt_text:
            button_text = opt_text
        elif opt_image:
            button_text = f"(صورة الخيار {i+1})"
        else:
            continue # Skip missing options

        if i == correct_answer_index:
            prefix = "✅ "
        elif i == selected_answer_index: # User chose this wrong answer
            prefix = "❌ "
        else:
             prefix = "➖ " # Other wrong options

        # Use a dummy callback to make buttons unclickable after answer
        row.append(InlineKeyboardButton(prefix + button_text, callback_data=f"quiz_{quiz_id}_done_{question_index}_{i}"))
        if len(row) == 2:
            feedback_keyboard_buttons.append(row)
            row = []
    if row:
        feedback_keyboard_buttons.append(row)

    feedback_reply_markup = InlineKeyboardMarkup(feedback_keyboard_buttons)

    # Edit the original question message
    original_message_id = quiz_data.get("last_question_message_id")
    if original_message_id:
        try:
            # Reconstruct the original question text/caption
            original_question_full_text = f"*السؤال {question_index + 1} من {quiz_data['total_questions']}*\n\n"
            if question.get("question_text"):
                original_question_full_text += question["question_text"]
            
            # Append feedback to the original text/caption
            final_text_with_feedback = f"{original_question_full_text}\n\n---\n{feedback_text}"

            if query.message.photo: # If original was a photo
                 await query.edit_message_caption(
                     caption=final_text_with_feedback,
                     reply_markup=feedback_reply_markup,
                     parse_mode='Markdown'
                 )
            else: # If original was text
                 await query.edit_message_text(
                     text=final_text_with_feedback,
                     reply_markup=feedback_reply_markup,
                     parse_mode='Markdown'
                 )
            logger.debug(f"[QUIZ LOGIC] Edited message {original_message_id} with feedback for question {question_index}.")
        except BadRequest as e:
            logger.error(f"[QUIZ LOGIC] BadRequest editing message {original_message_id} with feedback: {e}")
            # Fallback: Send feedback as a new message if editing fails
            # **FIX**: Use the actual safe_send_message function
            await safe_send_message(context.bot, chat_id, text=feedback_text, reply_markup=feedback_reply_markup)
        except TelegramError as e:
            logger.error(f"[QUIZ LOGIC] TelegramError editing message {original_message_id} with feedback: {e}")
            # Fallback: Send feedback as a new message
            # **FIX**: Use the actual safe_send_message function
            await safe_send_message(context.bot, chat_id, text=feedback_text, reply_markup=feedback_reply_markup)
    else:
        logger.error(f"[QUIZ LOGIC] Cannot edit message for feedback - last_question_message_id not found for quiz {quiz_id}")
        # Send feedback as a new message if original ID is missing
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text=feedback_text, reply_markup=feedback_reply_markup)

    # --- Delay and Move to Next Question or Results --- 
    await asyncio.sleep(FEEDBACK_DELAY)

    next_question_index = question_index + 1
    if next_question_index < quiz_data["total_questions"]:
        await send_question(context.bot, chat_id, user_id, quiz_id, next_question_index, context)
    else:
        await show_quiz_results(context.bot, chat_id, user_id, quiz_id, context)

    return TAKING_QUIZ # Remain in this state

async def handle_skip_question(update: Update, context: CallbackContext) -> int:
    """Handles user pressing the 'Skip Question' button."""
    query = update.callback_query
    await query.answer() # Acknowledge button press

    user_id = query.from_user.id
    chat_id = query.message.chat_id

    # --- Extract data from callback_data --- 
    # Format: quiz_{quiz_id}_skip_{question_index}
    match = re.match(r"quiz_(.+)_skip_(\d+)", query.data)
    if not match:
        logger.error(f"[QUIZ LOGIC] Invalid callback data format for skip: {query.data}")
        # **FIX**: Use the actual safe_edit_message_text function
        await safe_edit_message_text(query.message, text="حدث خطأ في بيانات زر التخطي.")
        return TAKING_QUIZ

    quiz_id, question_index_str = match.groups()
    question_index = int(question_index_str)

    # Call the shared skip logic
    await skip_question_callback(context.bot, chat_id, user_id, quiz_id, question_index, context, timed_out=False, error_occurred=False, query=query)

    return TAKING_QUIZ

async def skip_question_callback(bot, chat_id: int, user_id: int, quiz_id: str, question_index: int, context: CallbackContext, timed_out: bool = False, error_occurred: bool = False, query: Update = None):
    """Shared logic to handle skipping a question (manual, timeout, or error)."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    # --- Validate Quiz State --- 
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ LOGIC] skip_question_callback called for inactive/mismatched quiz {quiz_id} user {user_id}")
        if query: # Only edit message if called from button press
            # **FIX**: Use the actual safe_edit_message_text function
            await safe_edit_message_text(query.message, text="يبدو أن هذا الاختبار قد انتهى أو لم يعد صالحاً.")
        return
    # Allow skipping even if not current question index in case of race conditions/errors
    # if question_index != quiz_data.get("current_question_index"):
    #     logger.warning(f"[QUIZ LOGIC] Skip requested for question {question_index} but current is {quiz_data.get('current_question_index')}. Ignoring.")
    #     if query:
    #         await safe_edit_message_text(query.message, text="لقد تم تخطي هذا السؤال بالفعل أو انتقلت لسؤال آخر.")
    #     return
    if quiz_data["answers"][question_index] is not None:
        logger.info(f"[QUIZ LOGIC] Question {question_index} already answered/skipped for quiz {quiz_id}. Ignoring skip request.")
        if query: # Only edit message if called from button press
            # **FIX**: Use the actual safe_edit_message_text function
            await safe_edit_message_text(query.message, text="لقد أجبت أو تخطيت هذا السؤال بالفعل.")
        return

    # --- Stop Timer --- 
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        remove_job_if_exists(timer_job_name, context)
        logger.info(f"[QUIZ LOGIC] Removed timer job {timer_job_name} for skipped question {question_index}.")
        quiz_data["question_timer_job_name"] = None

    # --- Update Quiz State --- 
    skip_reason = "skipped manually"
    if timed_out:
        quiz_data["answers"][question_index] = -2 # Mark as timed out (wrong)
        quiz_data["wrong_count"] += 1 # Count timeout as wrong
        skip_reason = "timed out (marked wrong)"
    elif error_occurred:
        quiz_data["answers"][question_index] = -3 # Mark as error
        quiz_data["skipped_count"] += 1 # Count error as skipped for stats
        skip_reason = "skipped due to error"
    else: # Manual skip
        quiz_data["answers"][question_index] = -1 # Mark as skipped
        quiz_data["skipped_count"] += 1
        skip_reason = "skipped manually"
        
    logger.info(f"[QUIZ LOGIC] User {user_id} {skip_reason} question {question_index} in quiz {quiz_id}.")

    # --- Edit Message (if called from button) --- 
    if query:
        original_message_id = quiz_data.get("last_question_message_id")
        if original_message_id == query.message.message_id:
            try:
                # Remove keyboard and indicate skip
                if query.message.photo:
                    await query.edit_message_caption(caption=query.message.caption + "\n\n---\n⏩ تم تخطي السؤال.", reply_markup=None)
                else:
                    await query.edit_message_text(text=query.message.text + "\n\n---\n⏩ تم تخطي السؤال.", reply_markup=None)
                logger.debug(f"[QUIZ LOGIC] Edited message {original_message_id} to indicate skip for question {question_index}.")
            except (BadRequest, TelegramError) as e:
                logger.error(f"[QUIZ LOGIC] Error editing message {original_message_id} on skip: {e}")
                # Send new message if editing fails
                # **FIX**: Use the actual safe_send_message function
                await safe_send_message(bot, chat_id, text="⏩ تم تخطي السؤال.")
        else:
             logger.warning(f"[QUIZ LOGIC] Skip button message ID {query.message.message_id} doesn't match last question message ID {original_message_id}. Cannot edit.")
             # Send new message if IDs don't match
             # **FIX**: Use the actual safe_send_message function
             await safe_send_message(bot, chat_id, text="⏩ تم تخطي السؤال.")

    # --- Move to Next Question or Results --- 
    next_question_index = question_index + 1
    if next_question_index < quiz_data["total_questions"]:
        await send_question(bot, chat_id, user_id, quiz_id, next_question_index, context)
    else:
        await show_quiz_results(bot, chat_id, user_id, quiz_id, context)

async def show_quiz_results(bot, chat_id: int, user_id: int, quiz_id: str, context: CallbackContext) -> int:
    """Calculates and displays the quiz results to the user."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    if not quiz_data or quiz_data.get("quiz_id") != quiz_id:
        logger.warning(f"[QUIZ LOGIC] show_quiz_results called for inactive/mismatched quiz {quiz_id} user {user_id}")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(bot, chat_id, text="لا يمكن عرض نتائج اختبار غير صالح أو منتهي.")
        kb = create_main_menu_keyboard(user_id)
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    # Ensure quiz is marked as finished
    quiz_data["finished"] = True
    
    # --- Calculate Results --- 
    total_questions = quiz_data["total_questions"]
    correct_count = quiz_data["correct_count"]
    wrong_count = quiz_data["wrong_count"]
    skipped_count = quiz_data["skipped_count"]
    answered_count = correct_count + wrong_count
    
    # Calculate score percentage (avoid division by zero)
    score_percentage = 0
    if total_questions > 0:
        score_percentage = round((correct_count / total_questions) * 100)
        
    # Calculate duration
    start_time = quiz_data.get("start_time")
    duration_str = "غير معروفة"
    if start_time:
        end_time = datetime.now()
        duration = end_time - start_time
        total_seconds = int(duration.total_seconds())
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        duration_str = f"{minutes} دقيقة و {seconds} ثانية"

    # --- Prepare Results Message --- 
    results_text = f"🏁 *نتائج الاختبار (ID: ...{quiz_id[-6:]})* 🏁\n\n"
    results_text += f"🔢 إجمالي الأسئلة: {total_questions}\n"
    results_text += f"✅ الإجابات الصحيحة: {correct_count}\n"
    results_text += f"❌ الإجابات الخاطئة: {wrong_count} (بما في ذلك انتهاء الوقت)\n"
    results_text += f"⏩ الأسئلة المتخطاة: {skipped_count} (بما في ذلك الأخطاء)\n"
    results_text += f"⏱️ مدة الاختبار: {duration_str}\n\n"
    results_text += f"📊 *النتيجة النهائية: {score_percentage}%*\n\n"

    # Add performance feedback
    if score_percentage >= 90:
        results_text += "🎉 أداء ممتاز! استمر في التألق!"
    elif score_percentage >= 75:
        results_text += "👍 جيد جداً! أنت على الطريق الصحيح."
    elif score_percentage >= 50:
        results_text += "💪 لا بأس! تحتاج إلى المزيد من المراجعة."
    else:
        results_text += "😔 تحتاج إلى مراجعة شاملة. لا تيأس!"

    # --- Save Results to Database --- 
    try:
        await DB_MANAGER.save_quiz_result(
            user_id=user_id,
            quiz_type=quiz_data.get("quiz_type", "unknown"),
            scope_id=quiz_data.get("quiz_scope_id"),
            total_questions=total_questions,
            correct_answers=correct_count,
            wrong_answers=wrong_count,
            skipped_answers=skipped_count,
            score_percentage=score_percentage,
            duration_seconds=total_seconds if start_time else None,
            quiz_timestamp=start_time # Use the start time as the timestamp
        )
        logger.info(f"[DB Quiz] Successfully saved quiz results for user {user_id}, quiz {quiz_id}.")
    except Exception as e:
        logger.exception(f"[DB Quiz] Failed to save quiz results for user {user_id}, quiz {quiz_id}: {e}")
        results_text += "\n\n⚠️ تعذر حفظ نتيجة هذا الاختبار في قاعدة البيانات."

    # --- Send Results and Main Menu --- 
    # **FIX**: Use the actual safe_send_message function
    await safe_send_message(bot, chat_id, text=results_text, parse_mode='Markdown')

    # Clean up quiz data from user_data
    context.user_data.pop("current_quiz", None)
    context.user_data.pop("quiz_selection", None)
    logger.info(f"[QUIZ LOGIC] Quiz {quiz_id} finished for user {user_id}. Cleaned up user_data.")

    # Send main menu again
    kb = create_main_menu_keyboard(user_id)
    # **FIX**: Use the actual safe_send_message function
    await safe_send_message(bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)

    return MAIN_MENU # Transition back to the main menu state

async def handle_invalid_state(update: Update, context: CallbackContext) -> int:
    """Handles messages received while in the TAKING_QUIZ state that are not answers/skips."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    quiz_data = context.user_data.get("current_quiz")

    if quiz_data and not quiz_data.get("finished"):
        logger.warning(f"User {user_id} sent unexpected input during quiz: {update.message.text if update.message else 'CallbackData'}")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text="يرجى استخدام الأزرار للإجابة على السؤال أو تخطيه.")
        # Resend the current question? Maybe too complex, just remind them.
    else:
        # If quiz finished or no quiz data, maybe send main menu?
        logger.warning(f"User {user_id} sent unexpected input but no active quiz found. Sending main menu.")
        kb = create_main_menu_keyboard(user_id)
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    return TAKING_QUIZ # Stay in the quiz state

