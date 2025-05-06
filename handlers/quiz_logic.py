# -*- coding: utf-8 -*-
"""Core logic for handling quizzes in the Chemistry Telegram Bot (Corrected v8 - Fixed options handling based on API structure)."""

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
from config import (
    logger,
    MAIN_MENU, TAKING_QUIZ, SHOWING_RESULTS,
    FEEDBACK_DELAY, ENABLE_QUESTION_TIMER,
    NUM_OPTIONS # Keep NUM_OPTIONS if used elsewhere, but options loop is now dynamic
)
from utils.helpers import (
    safe_send_message, safe_edit_message_text,
    remove_job_if_exists
)
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
        await safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء بدء الاختبار (لم يتم تحديد نوع أو عدد الأسئلة أو نقطة النهاية). يرجى المحاولة مرة أخرى.")
        kb = create_main_menu_keyboard(user_id)
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
        await safe_send_message(context.bot, chat_id, text=f"عدد الأسئلة غير صالح ({num_questions}). يرجى المحاولة مرة أخرى.")
        kb = create_main_menu_keyboard(user_id)
        await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    # Ensure num_questions doesn't exceed max available
    num_questions = min(num_questions, max_available)
    if num_questions <= 0:
         logger.error(f"[QUIZ LOGIC] No questions available ({max_available}) for user {user_id}. Aborting quiz start.")
         await safe_send_message(context.bot, chat_id, text="لا توجد أسئلة متاحة لهذا الاختيار. لا يمكن بدء الاختبار.")
         kb = create_main_menu_keyboard(user_id)
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
            await safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء تحميل الأسئلة العشوائية المجمعة. يرجى المحاولة مرة أخرى.")
            kb = create_main_menu_keyboard(user_id)
            await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
            return MAIN_MENU
        
        # **FIX**: Transform pre-fetched random questions to ensure consistent structure
        transformed_random_questions = []
        for q_data in all_random_questions:
            transformed_q = transform_api_question(q_data)
            if transformed_q:
                transformed_random_questions.append(transformed_q)
            else:
                 logger.warning(f"[QUIZ LOGIC] Skipping invalid random question data during transformation: {q_data}")
        all_random_questions = transformed_random_questions # Use transformed list

        if len(all_random_questions) < num_questions:
            logger.warning(f"[QUIZ LOGIC] Requested {num_questions} random questions, but only {len(all_random_questions)} valid available. Using all available.")
            num_questions = len(all_random_questions)
            quiz_questions = all_random_questions # Use all if requested more than available
        elif num_questions > 0:
            logger.info(f"[QUIZ LOGIC] Sampling {num_questions} questions from {len(all_random_questions)} pre-fetched random questions.")
            quiz_questions = random.sample(all_random_questions, num_questions)
        else: # num_questions became 0
             quiz_questions = []
            
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
            await safe_send_message(context.bot, chat_id, text="⏳ تعذر تحميل أسئلة الاختبار (مهلة الاتصال). يرجى المحاولة مرة أخرى لاحقاً.")
            kb = create_main_menu_keyboard(user_id)
            await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
            return MAIN_MENU
        elif not isinstance(api_questions_response, list):
            logger.error(f"[API] Failed to fetch questions or invalid format from {questions_endpoint} (user {user_id}). Response: {api_questions_response}")
            await safe_send_message(context.bot, chat_id, text="⚠️ تعذر تحميل أسئلة الاختبار أو أن التنسيق غير صالح. يرجى المحاولة مرة أخرى لاحقاً.")
            kb = create_main_menu_keyboard(user_id)
            await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
            return MAIN_MENU

        # Transform and Validate Questions from API
        valid_api_questions = []
        for q_data in api_questions_response:
            transformed_q = transform_api_question(q_data)
            # **FIX**: Validation should check for 'options' list and its content
            if transformed_q and isinstance(transformed_q.get("options"), list) and len(transformed_q["options"]) > 0:
                # Further check if at least one option has text or image
                has_valid_option = any(opt.get("option_text") or opt.get("image_url") for opt in transformed_q["options"])
                # Further check if exactly one option is marked correct
                correct_count = sum(1 for opt in transformed_q["options"] if opt.get("is_correct"))
                
                if has_valid_option and correct_count == 1:
                    valid_api_questions.append(transformed_q)
                else:
                     logger.warning(f"[QUIZ LOGIC] Skipping invalid question data (no valid options or incorrect number of correct answers [{correct_count}]) received from API ({questions_endpoint}): {q_data}")
            else:
                logger.warning(f"[QUIZ LOGIC] Skipping invalid question data (missing/empty 'options' list or transformation failed) received from API ({questions_endpoint}): {q_data}")
        
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
        await safe_send_message(context.bot, chat_id, text="لم يتم العثور على أسئلة صالحة لهذا الاختبار. يرجى المحاولة مرة أخرى أو اختيار موضوع آخر.")
        kb = create_main_menu_keyboard(user_id)
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
    
    question_image = question.get("image_url")

    # --- Prepare Options and Keyboard (FIXED LOGIC) --- 
    options_list = question.get("options", []) # Get the list of options
    keyboard_buttons = []
    
    if not isinstance(options_list, list):
        logger.error(f"[QUIZ LOGIC] Question {question_index} (ID: {question.get('question_id')}) has invalid 'options' format: {options_list}. Skipping keyboard.")
        options_list = [] # Prevent error below

    row = []
    for i, option_data in enumerate(options_list):
        if not isinstance(option_data, dict):
            logger.warning(f"[QUIZ LOGIC] Skipping invalid option item (not a dict) at index {i} for question {question_index}: {option_data}")
            continue
            
        opt_text = option_data.get("option_text")
        opt_image = option_data.get("image_url") # Check for image per option
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
            
        # Use index 'i' as the answer index in callback data
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

    # Add Skip button only if there were options to show
    if keyboard_buttons: # Only add skip if options were actually added
        keyboard_buttons.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f"quiz_{quiz_id}_skip_{question_index}")])
        reply_markup = InlineKeyboardMarkup(keyboard_buttons)
    else:
        # If no valid options were found, don't show the options keyboard, maybe just send text/image?
        # Or potentially skip the question entirely if options are mandatory?
        # For now, send without keyboard, but log an error.
        logger.error(f"[QUIZ LOGIC] No valid options found to build keyboard for question {question_index} (ID: {question.get('question_id')}). Sending without options.")
        reply_markup = None # Send without keyboard
        # Consider automatically skipping this question if options are essential
        # await skip_question_callback(bot, chat_id, user_id, quiz_id, question_index, context, error_occurred=True)
        # return

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
                reply_markup=reply_markup, # Might be None if no options
                parse_mode='Markdown'
            )
        else:
            # Ensure there's text to send if no image
            if not question_text.strip():
                 logger.error(f"[QUIZ LOGIC] Question {question_index} (ID: {question.get('question_id')}) has no image and no text. Skipping.")
                 await skip_question_callback(bot, chat_id, user_id, quiz_id, question_index, context, error_occurred=True)
                 return
            logger.debug(f"[QUIZ LOGIC] Sending question {question_index} as text.")
            sent_message = await bot.send_message(
                chat_id=chat_id,
                text=question_text,
                reply_markup=reply_markup, # Might be None if no options
                parse_mode='Markdown'
            )
    except BadRequest as e:
        # Handle potential errors like invalid image URL or Markdown issues
        logger.error(f"[QUIZ LOGIC] BadRequest sending question {question_index} (quiz {quiz_id}): {e}. Question data: {question}")
        send_error = e
        await safe_send_message(context.bot, chat_id, text=f"⚠️ حدث خطأ أثناء إرسال السؤال {question_index + 1}. سيتم تخطيه تلقائياً.")
        await skip_question_callback(bot, chat_id, user_id, quiz_id, question_index, context, timed_out=False, error_occurred=True)
        return # Stop further processing for this question
    except TelegramError as e:
        logger.error(f"[QUIZ LOGIC] TelegramError sending question {question_index} (quiz {quiz_id}): {e}. Question data: {question}")
        send_error = e
        await safe_send_message(context.bot, chat_id, text=f"⚠️ حدث خطأ غير متوقع أثناء إرسال السؤال {question_index + 1}. سيتم تخطيه تلقائياً.")
        await skip_question_callback(bot, chat_id, user_id, quiz_id, question_index, context, timed_out=False, error_occurred=True)
        return # Stop further processing for this question

    if sent_message:
        quiz_data["last_question_message_id"] = sent_message.message_id
        logger.debug(f"[QUIZ LOGIC] Stored message ID {sent_message.message_id} for question {question_index}")

        # --- Start Question Timer (Only if options were shown) --- 
        if reply_markup and ENABLE_QUESTION_TIMER and hasattr(context, 'job_queue') and context.job_queue:
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
        elif ENABLE_QUESTION_TIMER and reply_markup:
             logger.warning("[QUIZ LOGIC] ENABLE_QUESTION_TIMER is True, but JobQueue not available in context. Timer not started.")
        elif not reply_markup:
             logger.info(f"[QUIZ LOGIC] No options shown for question {question_index}, timer not started.")

    else:
        logger.error(f"[QUIZ LOGIC] Failed to get sent_message object after sending question {question_index} (quiz {quiz_id}). Send error was: {send_error}")
        # If sending failed earlier, skip_question_callback was already called.
        if not send_error:
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
        await safe_edit_message_text(query.message, text="حدث خطأ في بيانات الزر. يرجى المحاولة مرة أخرى.")
        return TAKING_QUIZ # Stay in the same state

    quiz_id, question_index_str, selected_answer_index_str = match.groups()
    question_index = int(question_index_str)
    selected_answer_index = int(selected_answer_index_str) # This is the index 'i' from the loop

    # --- Validate Quiz State --- 
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ LOGIC] handle_answer called for inactive/mismatched quiz {quiz_id} user {user_id}")
        await safe_edit_message_text(query.message, text="يبدو أن هذا الاختبار قد انتهى أو لم يعد صالحاً.")
        return TAKING_QUIZ
    if question_index != quiz_data.get("current_question_index"):
        logger.warning(f"[QUIZ LOGIC] User {user_id} answered question {question_index} but current is {quiz_data.get('current_question_index')}. Ignoring.")
        await safe_edit_message_text(query.message, text="لقد أجبت على سؤال سابق. يرجى الإجابة على السؤال الحالي.")
        return TAKING_QUIZ
    if quiz_data["answers"][question_index] is not None:
        logger.info(f"[QUIZ LOGIC] User {user_id} tried to answer question {question_index} again. Ignoring.")
        await safe_edit_message_text(query.message, text="لقد أجبت على هذا السؤال بالفعل.")
        return TAKING_QUIZ

    # --- Stop Timer --- 
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        remove_job_if_exists(timer_job_name, context)
        logger.info(f"[QUIZ LOGIC] Removed timer job {timer_job_name} for question {question_index}.")
        quiz_data["question_timer_job_name"] = None # Clear the job name

    # --- Check Answer (FIXED LOGIC) --- 
    question = quiz_data["questions"][question_index]
    options_list = question.get("options", [])
    correct_answer_index = -1 # Default to -1 (not found)
    
    if not isinstance(options_list, list):
         logger.error(f"[QUIZ LOGIC] Question {question_index} (ID: {question.get('question_id')}) has invalid 'options' format during answer check. Skipping.")
         await safe_edit_message_text(query.message, text="⚠️ حدث خطأ في بيانات خيارات هذا السؤال. سيتم تخطيه.")
         await skip_question_callback(context.bot, chat_id, user_id, quiz_id, question_index, context, timed_out=False, error_occurred=True)
         return TAKING_QUIZ

    # Find the index of the correct answer
    for i, option_data in enumerate(options_list):
        if isinstance(option_data, dict) and option_data.get("is_correct") is True:
            correct_answer_index = i
            break # Found the correct answer

    if correct_answer_index == -1:
         logger.error(f"[QUIZ LOGIC] Question {question_index} (ID: {question.get('question_id')}) in quiz {quiz_id} has no correct answer marked in 'options'! Skipping.")
         await safe_edit_message_text(query.message, text="⚠️ حدث خطأ في بيانات هذا السؤال (لا توجد إجابة صحيحة محددة). سيتم تخطيه.")
         await skip_question_callback(context.bot, chat_id, user_id, quiz_id, question_index, context, timed_out=False, error_occurred=True)
         return TAKING_QUIZ

    is_correct = (selected_answer_index == correct_answer_index)
    quiz_data["answers"][question_index] = selected_answer_index # Store user's choice index

    feedback_text = ""
    if is_correct:
        quiz_data["correct_count"] += 1
        feedback_text = "✅ إجابة صحيحة!"
        logger.info(f"[QUIZ LOGIC] User {user_id} answered question {question_index} CORRECTLY (Selected index: {selected_answer_index}, Correct index: {correct_answer_index}).")
    else:
        quiz_data["wrong_count"] += 1
        # Try to get the text of the correct option for feedback
        correct_option_text = "غير متوفر"
        if 0 <= correct_answer_index < len(options_list):
             correct_option_data = options_list[correct_answer_index]
             if isinstance(correct_option_data, dict):
                  correct_option_text = correct_option_data.get("option_text", correct_option_text)
                  if not correct_option_text and correct_option_data.get("image_url"):
                       correct_option_text = f"(صورة الخيار {correct_answer_index + 1})"
        
        feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة هي: {correct_option_text}"
        logger.info(f"[QUIZ LOGIC] User {user_id} answered question {question_index} INCORRECTLY (Selected index: {selected_answer_index}, Correct index: {correct_answer_index}).")

    # Add explanation if available
    explanation = question.get("explanation")
    if explanation:
        feedback_text += f"\n\n*الشرح:* {explanation}"

    # --- Edit Message to Show Feedback (FIXED LOGIC) --- 
    feedback_keyboard_buttons = []
    row = []
    for i, option_data in enumerate(options_list):
        if not isinstance(option_data, dict):
             continue # Skip invalid option data
             
        opt_text = option_data.get("option_text")
        opt_image = option_data.get("image_url")
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

    feedback_reply_markup = InlineKeyboardMarkup(feedback_keyboard_buttons) if feedback_keyboard_buttons else None

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
            await safe_send_message(context.bot, chat_id, text=feedback_text, reply_markup=feedback_reply_markup)
        except TelegramError as e:
            logger.error(f"[QUIZ LOGIC] TelegramError editing message {original_message_id} with feedback: {e}")
            # Fallback: Send feedback as a new message
            await safe_send_message(context.bot, chat_id, text=feedback_text, reply_markup=feedback_reply_markup)
    else:
        logger.error(f"[QUIZ LOGIC] Cannot edit message for feedback - last_question_message_id not found for quiz {quiz_id}")
        # Send feedback as a new message if original ID is missing
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
        await safe_edit_message_text(query.message, text="حدث خطأ في بيانات زر التخطي.")
        return TAKING_QUIZ

    quiz_id, question_index_str = match.groups()
    question_index = int(question_index_str)

    # Call the shared skip logic
    await skip_question_callback(context.bot, chat_id, user_id, quiz_id, question_index, context, timed_out=False, error_occurred=False, query=query)

    return TAKING_QUIZ

async def skip_question_callback(bot, chat_id: int, user_id: int, quiz_id: str, question_index: int, context: CallbackContext, timed_out: bool = False, error_occurred: bool = False, query: Update = None):
    """Shared logic to handle skipping a question (manual, timeout, or error)."""
    # Ensure context.user_data is available, especially when called from timer
    if hasattr(context, 'dispatcher') and context.dispatcher:
         user_data = context.dispatcher.user_data.get(user_id, {})
    else:
         user_data = context.user_data # Fallback for direct calls
         
    quiz_data = user_data.get("current_quiz")

    # --- Validate Quiz State --- 
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ LOGIC] skip_question_callback called for inactive/mismatched quiz {quiz_id} user {user_id}")
        if query: # Only edit message if called from button press
            await safe_edit_message_text(query.message, text="يبدو أن هذا الاختبار قد انتهى أو لم يعد صالحاً.")
        return
        
    # Check if already handled
    if quiz_data["answers"][question_index] is not None:
        logger.info(f"[QUIZ LOGIC] Question {question_index} already answered/skipped for quiz {quiz_id}. Ignoring skip request.")
        if query: # Only edit message if called from button press
            await safe_edit_message_text(query.message, text="لقد تم التعامل مع هذا السؤال بالفعل.")
        return

    # --- Stop Timer --- 
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        remove_job_if_exists(timer_job_name, context)
        logger.info(f"[QUIZ LOGIC] Removed timer job {timer_job_name} for skipped question {question_index}.")
        quiz_data["question_timer_job_name"] = None

    # --- Update Quiz State --- 
    skip_reason = "MANUAL"
    if timed_out:
        quiz_data["wrong_count"] += 1
        quiz_data["answers"][question_index] = -2 # Mark as timed-out wrong
        skip_reason = "TIMEOUT (WRONG)"
    elif error_occurred:
        quiz_data["skipped_count"] += 1 # Count errors as skipped for now
        quiz_data["answers"][question_index] = -3 # Mark as error skip
        skip_reason = "ERROR"
    else: # Manual skip
        quiz_data["skipped_count"] += 1
        quiz_data["answers"][question_index] = -1 # Mark as manually skipped
        skip_reason = "MANUAL"
        
    logger.info(f"[QUIZ LOGIC] User {user_id} skipped question {question_index} (Reason: {skip_reason}). Counts: C={quiz_data['correct_count']}, W={quiz_data['wrong_count']}, S={quiz_data['skipped_count']}")

    # --- Edit Message (Optional - only for manual skip via button) --- 
    if query and not timed_out and not error_occurred:
        try:
            await query.edit_message_reply_markup(reply_markup=None) # Remove keyboard
            await safe_send_message(bot, chat_id, text=f"تم تخطي السؤال {question_index + 1}.")
        except TelegramError as e:
            logger.error(f"[QUIZ LOGIC] Error editing message or sending skip confirmation: {e}")

    # --- Move to Next Question or Results --- 
    next_question_index = question_index + 1
    if next_question_index < quiz_data["total_questions"]:
        await send_question(bot, chat_id, user_id, quiz_id, next_question_index, context)
    else:
        await show_quiz_results(bot, chat_id, user_id, quiz_id, context)

async def show_quiz_results(bot, chat_id: int, user_id: int, quiz_id: str, context: CallbackContext):
    """Calculates and displays the quiz results, saves them, and cleans up."""
    # Ensure context.user_data is available, especially when called from timer/skip
    if hasattr(context, 'dispatcher') and context.dispatcher:
         user_data = context.dispatcher.user_data.get(user_id, {})
    else:
         user_data = context.user_data # Fallback for direct calls
         
    quiz_data = user_data.get("current_quiz")

    if not quiz_data or quiz_data.get("quiz_id") != quiz_id:
        logger.error(f"[QUIZ LOGIC] show_quiz_results called for inactive/mismatched quiz {quiz_id} user {user_id}")
        # Attempt to send a generic message if possible
        await safe_send_message(bot, chat_id, text="حدث خطأ أثناء عرض النتائج. قد يكون الاختبار غير صالح.")
        kb = create_main_menu_keyboard(user_id)
        await safe_send_message(bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        # Clear potentially corrupted data
        user_data.pop("current_quiz", None)
        return MAIN_MENU
        
    if quiz_data.get("finished"): # Prevent showing results multiple times
        logger.info(f"[QUIZ LOGIC] Results for quiz {quiz_id} already shown. Ignoring.")
        return TAKING_QUIZ # Or MAIN_MENU? Stay safe.

    quiz_data["finished"] = True
    end_time = datetime.now()
    duration = end_time - quiz_data.get("start_time", end_time) # Calculate duration
    duration_seconds = int(duration.total_seconds())
    duration_str = time.strftime('%M:%S', time.gmtime(duration_seconds)) # Format as MM:SS

    total_questions = quiz_data["total_questions"]
    correct_count = quiz_data["correct_count"]
    wrong_count = quiz_data["wrong_count"]
    skipped_count = quiz_data["skipped_count"]
    # Recalculate skipped if some were marked as error/timeout
    actual_answered = sum(1 for ans in quiz_data["answers"] if ans is not None and ans >= 0)
    actual_skipped = total_questions - actual_answered
    # Ensure counts add up, prioritize correct/wrong over calculated skipped
    final_skipped = total_questions - correct_count - wrong_count 
    if final_skipped < 0: final_skipped = 0 # Should not happen

    score_percentage = (correct_count / total_questions * 100) if total_questions > 0 else 0

    results_text = f"🏁 *نتائج الاختبار* 🏁\n\n"
    results_text += f"📝 نوع الاختبار: {quiz_data.get('quiz_type', 'غير محدد')}\n"
    # Add scope details if available
    # scope_id = quiz_data.get('quiz_scope_id')
    # if scope_id:
    #     results_text += f"🎯 النطاق: {scope_id}\n" 
    results_text += f"🔢 إجمالي الأسئلة: {total_questions}\n"
    results_text += f"✅ الإجابات الصحيحة: {correct_count}\n"
    results_text += f"❌ الإجابات الخاطئة: {wrong_count}\n"
    results_text += f"⏭️ الأسئلة المتخطاة: {final_skipped}\n"
    results_text += f"⏱️ الوقت المستغرق: {duration_str}\n\n"
    results_text += f"🏆 *النتيجة النهائية: {score_percentage:.1f}%*\n"

    # --- Save Results to Database --- 
    try:
        db_manager = DB_MANAGER # Get global instance
        await db_manager.save_quiz_result(
            user_id=user_id,
            quiz_type=quiz_data.get('quiz_type', 'unknown'),
            scope_id=quiz_data.get('quiz_scope_id'),
            total_questions=total_questions,
            correct_answers=correct_count,
            wrong_answers=wrong_count,
            skipped_answers=final_skipped,
            score_percentage=score_percentage,
            duration_seconds=duration_seconds,
            quiz_timestamp=quiz_data.get("start_time", datetime.now()) # Use start time
        )
        logger.info(f"[DB] Successfully saved quiz results for user {user_id}, quiz {quiz_id}.")
    except Exception as e:
        logger.error(f"[DB] Failed to save quiz results for user {user_id}, quiz {quiz_id}: {e}")
        results_text += "\n\n⚠️ تعذر حفظ هذه النتيجة في سجلاتك."

    # --- Send Results and Cleanup --- 
    kb = create_main_menu_keyboard(user_id)
    await safe_send_message(bot, chat_id, text=results_text, reply_markup=kb, parse_mode='Markdown')

    # Clean up quiz data from user_data
    user_data.pop("current_quiz", None)
    logger.info(f"[QUIZ LOGIC] Quiz {quiz_id} finished for user {user_id}. Cleaned up user_data.")

    return MAIN_MENU # Return to main menu state after showing results

# --- Utility to find correct answer index --- 
# (This logic is now integrated into handle_answer)
# def find_correct_answer_index(question_data):
#     options = question_data.get("options", [])
#     if not isinstance(options, list):
#         return None
#     for i, option in enumerate(options):
#         if isinstance(option, dict) and option.get("is_correct") is True:
#             return i
#     return None

