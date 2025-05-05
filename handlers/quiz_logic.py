# -*- coding: utf-8 -*-
"""Core logic for handling quizzes in the Chemistry Telegram Bot (Corrected v6 - Fixed Helper Imports)."""

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
            if transformed_q and transformed_q.get("correct_option") is not None:
                valid_api_questions.append(transformed_q)
            else:
                logger.warning(f"[QUIZ LOGIC] Skipping invalid question data (missing/null correct_option or other issues) received from API ({questions_endpoint}): {q_data}")
        
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

    # --- Prepare Question Text and Media --- 
    question_text = f"*السؤال {question_index + 1} من {quiz_data['total_questions']}*\n\n"
    if question.get("question_text"):
        question_text += question["question_text"]
    
    question_image = question.get("question_image")

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
    for i in range(NUM_OPTIONS):
        opt_text = options_texts[i]
        opt_image = options_images[i]
        button_text = ""
        
        if opt_text:
            button_text = opt_text
        elif opt_image:
            button_text = f"(صورة الخيار {i+1})" # Placeholder text for image option
        else:
            continue # Skip if both text and image are missing for this option
            
        callback_data = f"quiz_{quiz_id}_ans_{question_index}_{i}"
        row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
        
        if len(row) == 2:
            keyboard_buttons.append(row)
            row = []
            
    if row:
        keyboard_buttons.append(row)

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
        send_error = e
        logger.error(f"[QUIZ LOGIC] BadRequest sending question {question_index} (quiz:{quiz_id}): {e}. Image: {question_image}")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(bot, chat_id, text=f"⚠️ حدث خطأ أثناء إرسال السؤال {question_index + 1} (قد تكون الصورة غير صالحة). سيتم تخطي هذا السؤال.")
    except TelegramError as e:
        send_error = e
        logger.error(f"[QUIZ LOGIC] TelegramError sending question {question_index} (quiz:{quiz_id}): {e}")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(bot, chat_id, text=f"⚠️ حدث خطأ غير متوقع أثناء إرسال السؤال {question_index + 1}. سيتم تخطي هذا السؤال.")
    except Exception as e:
        send_error = e
        logger.exception(f"[QUIZ LOGIC] Unexpected Exception sending question {question_index} (quiz:{quiz_id}): {e}")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(bot, chat_id, text=f"⚠️ حدث خطأ فادح أثناء إرسال السؤال {question_index + 1}. سيتم تخطي هذا السؤال.")

    # --- Handle Send Result --- 
    if sent_message:
        quiz_data["last_question_message_id"] = sent_message.message_id
        logger.debug(f"[QUIZ LOGIC] Stored message ID {sent_message.message_id} for question {question_index}")

        # --- Start Timer --- 
        if ENABLE_QUESTION_TIMER and context.job_queue:
            job_name = f"qtimer_{chat_id}_{user_id}_{quiz_id}_{question_index}"
            remove_job_if_exists(job_name, context)
            
            timer_context = {
                "chat_id": chat_id,
                "user_id": user_id,
                "quiz_id": quiz_id,
                "question_index": question_index
            }
            context.job_queue.run_once(question_timer_callback, QUESTION_TIMER_SECONDS, context=timer_context, name=job_name)
            quiz_data["question_timer_job_name"] = job_name
            logger.info(f"[QUIZ LOGIC] Started timer ({QUESTION_TIMER_SECONDS}s) for question {question_index}, job: {job_name}")
        elif ENABLE_QUESTION_TIMER:
            logger.warning("[QUIZ LOGIC] JobQueue not available in context. Cannot start timer.")
            
    else: # If sending failed
        logger.error(f"[QUIZ LOGIC] Failed to send question {question_index} for quiz {quiz_id}. Triggering skip.")
        await skip_question_callback(bot, chat_id, user_id, quiz_id, question_index, context, timed_out=False, error_occurred=True)

async def handle_answer(update: Update, context: CallbackContext) -> int:
    """Handles user's answer selection from inline keyboard."""
    query = update.callback_query
    await query.answer() # Acknowledge callback

    user_id = query.from_user.id
    chat_id = query.message.chat_id
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    # --- Parse Callback Data --- 
    match = re.match(r"quiz_([^_]+)_ans_(\\d+)_(\\d+)", query.data)
    if not match:
        logger.warning(f"[QUIZ LOGIC] Invalid answer callback data format: {query.data}")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text="حدث خطأ في بيانات الإجابة.")
        return TAKING_QUIZ

    quiz_id_from_callback = match.group(1)
    question_index = int(match.group(2))
    selected_option_index = int(match.group(3))

    # --- Validate Quiz State --- 
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id_from_callback or quiz_data.get("finished"):
        logger.warning(f"[QUIZ LOGIC] Answer received for inactive/mismatched quiz {quiz_id_from_callback} from user {user_id}.")
        # **FIX**: Use the actual safe_edit_message_text function
        await safe_edit_message_text(query, text="انتهى هذا الاختبار أو أنك في اختبار آخر.")
        return TAKING_QUIZ

    if question_index != quiz_data.get("current_question_index"):
        logger.warning(f"[QUIZ LOGIC] Answer received for non-current question (q:{question_index}, current:{quiz_data.get('current_question_index')}) in quiz {quiz_id_from_callback}.")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text="لقد أجبت على سؤال مختلف عن السؤال الحالي.")
        return TAKING_QUIZ

    if quiz_data["answers"][question_index] is not None:
        logger.info(f"[QUIZ LOGIC] Question {question_index} already answered/skipped for quiz {quiz_id_from_callback}. Ignoring duplicate answer.")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text="لقد أجبت على هذا السؤال بالفعل.")
        return TAKING_QUIZ

    # --- Stop Timer --- 
    if ENABLE_QUESTION_TIMER and context.job_queue:
        job_name = quiz_data.get("question_timer_job_name")
        if remove_job_if_exists(job_name, context):
            logger.info(f"[QUIZ LOGIC] Removed timer job {job_name} for question {question_index}.")
        quiz_data["question_timer_job_name"] = None

    # --- Process Answer --- 
    question = quiz_data["questions"][question_index]
    quiz_data["answers"][question_index] = selected_option_index

    correct_option_index = question.get("correct_option")
    is_correct = False
    if correct_option_index is not None and isinstance(correct_option_index, int) and 0 <= correct_option_index < NUM_OPTIONS:
        is_correct = (selected_option_index == correct_option_index)
    else:
        logger.error(f"[QUIZ LOGIC] Invalid or missing 'correct_option' ({correct_option_index}) for q_id {question.get('id', 'N/A')} in quiz {quiz_id_from_callback}. Marking as wrong.")
        correct_option_index = -99

    feedback_text = ""
    if is_correct:
        quiz_data["correct_count"] += 1
        feedback_text = "✅ إجابة صحيحة!"
        logger.info(f"[QUIZ LOGIC] User {user_id} answered q:{question_index} quiz:{quiz_id_from_callback}. Correct: True. UserAns:{selected_option_index}, CorrectAns:{correct_option_index}")
    else:
        quiz_data["wrong_count"] += 1
        feedback_text = "❌ إجابة خاطئة."
        if correct_option_index != -99:
             correct_option_text = question.get(f"option{correct_option_index + 1}")
             if correct_option_text:
                 feedback_text += f" الإجابة الصحيحة: {correct_option_text}"
        logger.info(f"[QUIZ LOGIC] User {user_id} answered q:{question_index} quiz:{quiz_id_from_callback}. Correct: False. UserAns:{selected_option_index}, CorrectAns:{correct_option_index}")

    # --- Edit Original Message (Remove Keyboard) & Send Feedback --- 
    original_message_id = quiz_data.get("last_question_message_id")
    if original_message_id:
        try:
            # **FIX**: Use the actual safe_edit_message_text/caption functions
            current_text = query.message.caption if query.message.photo else query.message.text
            new_text = current_text + f"\n\n*{feedback_text}*"
            
            if query.message.photo:
                 await context.bot.edit_message_caption(
                     chat_id=chat_id,
                     message_id=original_message_id,
                     caption=new_text,
                     reply_markup=None,
                     parse_mode='Markdown'
                 )
            else:
                await context.bot.edit_message_text(
                    text=new_text,
                    chat_id=chat_id,
                    message_id=original_message_id,
                    reply_markup=None,
                    parse_mode='Markdown'
                )
            logger.debug(f"[QUIZ LOGIC] Edited message {original_message_id} and sent feedback for q:{question_index}")
        except BadRequest as e:
            logger.warning(f"[QUIZ LOGIC] Failed to edit message {original_message_id} for feedback: {e}. Sending feedback separately.")
            # **FIX**: Use the actual safe_send_message function
            await safe_send_message(context.bot, chat_id, text=feedback_text)
        except TelegramError as e:
            logger.error(f"[QUIZ LOGIC] Error editing message {original_message_id} for feedback: {e}. Sending feedback separately.")
            # **FIX**: Use the actual safe_send_message function
            await safe_send_message(context.bot, chat_id, text=feedback_text)
    else:
        logger.warning(f"[QUIZ LOGIC] last_question_message_id not found for q:{question_index}. Sending feedback separately.")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(context.bot, chat_id, text=feedback_text)

    # --- Delay and Move to Next Question or Results --- 
    await asyncio.sleep(FEEDBACK_DELAY)

    next_question_index = question_index + 1
    if next_question_index < quiz_data["total_questions"]:
        await send_question(context.bot, chat_id, user_id, quiz_id_from_callback, next_question_index, context)
        return TAKING_QUIZ
    else:
        logger.info(f"[QUIZ LOGIC] Quiz {quiz_id_from_callback} finished for user {user_id}. Showing results.")
        return await show_quiz_results(context.bot, chat_id, user_id, quiz_id_from_callback, context)

async def skip_question_callback(bot, chat_id: int, user_id: int, quiz_id: str, question_index: int, context: CallbackContext, timed_out: bool = False, error_occurred: bool = False):
    """Handles skipping a question, either by user action, timeout, or error."""
    update = context.update
    query = update.callback_query if update and hasattr(update, 'callback_query') else None
    
    if query:
        await query.answer()
        match = re.match(r"quiz_([^_]+)_skip_(\\d+)", query.data)
        if not match or match.group(1) != quiz_id or int(match.group(2)) != question_index:
             logger.warning(f"[QUIZ LOGIC] Mismatched skip callback data: {query.data} vs args ({quiz_id}, {question_index})")

    if hasattr(context, "dispatcher") and context.dispatcher:
        user_data = context.dispatcher.user_data.get(user_id, {})
    else:
        user_data = context.user_data
        
    quiz_data = user_data.get("current_quiz")

    # --- Validate Quiz State --- 
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ LOGIC] Skip called for inactive/mismatched quiz {quiz_id} from user {user_id}.")
        if query:
            # **FIX**: Use the actual safe_edit_message_text function
            await safe_edit_message_text(query, text="انتهى هذا الاختبار أو أنك في اختبار آخر.")
        return TAKING_QUIZ

    if question_index != quiz_data.get("current_question_index"):
        logger.warning(f"[QUIZ LOGIC] Skip received for non-current question (q:{question_index}, current:{quiz_data.get('current_question_index')}) in quiz {quiz_id}.")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(bot, chat_id, text="لقد حاولت تخطي سؤال مختلف عن السؤال الحالي.")
        return TAKING_QUIZ

    if quiz_data["answers"][question_index] is not None:
        logger.info(f"[QUIZ LOGIC] Question {question_index} already answered/skipped for quiz {quiz_id}. Ignoring duplicate skip.")
        if query and not timed_out and not error_occurred:
            # **FIX**: Use the actual safe_send_message function
            await safe_send_message(bot, chat_id, text="لقد أجبت أو تخطيت هذا السؤال بالفعل.")
        return TAKING_QUIZ

    # --- Stop Timer --- 
    if ENABLE_QUESTION_TIMER and context.job_queue:
        job_name = quiz_data.get("question_timer_job_name")
        if remove_job_if_exists(job_name, context):
            logger.info(f"[QUIZ LOGIC] Removed timer job {job_name} for skipped/timed-out/error question {question_index}.")
        quiz_data["question_timer_job_name"] = None

    # --- Mark as Skipped/Wrong/Error --- 
    skip_message = ""
    if timed_out:
        quiz_data["answers"][question_index] = -2 # Timed-out (wrong)
        quiz_data["wrong_count"] += 1
        skip_message = f"⏳ تم اعتبار السؤال {question_index + 1} خاطئاً لانتهاء الوقت."
        logger.info(f"[QUIZ LOGIC] User {user_id} q:{question_index} quiz:{quiz_id} marked as WRONG (Timeout).")
    elif error_occurred:
        quiz_data["answers"][question_index] = -3 # Error-skipped
        quiz_data["skipped_count"] += 1
        skip_message = f"⚠️ تم تخطي السؤال {question_index + 1} بسبب خطأ في الإرسال."
        logger.info(f"[QUIZ LOGIC] User {user_id} q:{question_index} quiz:{quiz_id} marked as SKIPPED (Error).")
    else: # User-initiated skip
        quiz_data["answers"][question_index] = -1 # Skipped by user
        quiz_data["skipped_count"] += 1
        skip_message = f"⏭️ تم تخطي السؤال {question_index + 1}."
        logger.info(f"[QUIZ LOGIC] User {user_id} skipped q:{question_index} quiz:{quiz_id}.")

    # --- Edit Original Message (Remove Keyboard) & Send Skip Feedback --- 
    original_message_id = quiz_data.get("last_question_message_id")
    if original_message_id and query:
        try:
            # **FIX**: Use the actual safe_edit_message_text/caption functions
            current_text = query.message.caption if query.message.photo else query.message.text
            new_text = current_text + f"\n\n*{skip_message}*"
            
            if query.message.photo:
                 await bot.edit_message_caption(
                     chat_id=chat_id,
                     message_id=original_message_id,
                     caption=new_text,
                     reply_markup=None,
                     parse_mode='Markdown'
                 )
            else:
                await bot.edit_message_text(
                    text=new_text,
                    chat_id=chat_id,
                    message_id=original_message_id,
                    reply_markup=None,
                    parse_mode='Markdown'
                )
            logger.debug(f"[QUIZ LOGIC] Edited message {original_message_id} for skip feedback.")
        except BadRequest as e:
            logger.warning(f"[QUIZ LOGIC] Failed to edit message {original_message_id} for skip feedback: {e}. Sending feedback separately.")
            # **FIX**: Use the actual safe_send_message function
            await safe_send_message(bot, chat_id, text=skip_message)
        except TelegramError as e:
            logger.error(f"[QUIZ LOGIC] Error editing message {original_message_id} for skip feedback: {e}. Sending feedback separately.")
            # **FIX**: Use the actual safe_send_message function
            await safe_send_message(bot, chat_id, text=skip_message)
    elif not query:
         # **FIX**: Use the actual safe_send_message function
         await safe_send_message(bot, chat_id, text=skip_message)
    else:
        logger.warning(f"[QUIZ LOGIC] last_question_message_id not found for skip q:{question_index}. Sending feedback separately.")
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(bot, chat_id, text=skip_message)

    # --- Delay and Move to Next Question or Results --- 
    await asyncio.sleep(FEEDBACK_DELAY)

    next_question_index = question_index + 1
    if next_question_index < quiz_data["total_questions"]:
        await send_question(bot, chat_id, user_id, quiz_id, next_question_index, context)
        return TAKING_QUIZ
    else:
        logger.info(f"[QUIZ LOGIC] Quiz {quiz_id} finished after skip/timeout/error for user {user_id}. Showing results.")
        return await show_quiz_results(bot, chat_id, user_id, quiz_id, context)

async def show_quiz_results(bot, chat_id: int, user_id: int, quiz_id: str, context: CallbackContext) -> int:
    """Calculates and displays the quiz results, saves them, and returns to the main menu."""
    if hasattr(context, "dispatcher") and context.dispatcher:
        user_data = context.dispatcher.user_data.get(user_id, {})
    else:
        user_data = context.user_data
        
    quiz_data = user_data.get("current_quiz")

    if not quiz_data or quiz_data.get("quiz_id") != quiz_id:
        logger.warning(f"[QUIZ LOGIC] show_quiz_results called for inactive/mismatched quiz {quiz_id} user {user_id}.")
        kb = create_main_menu_keyboard(user_id)
        # **FIX**: Use the actual safe_send_message function
        await safe_send_message(bot, chat_id, text="لا يمكن عرض نتائج اختبار غير نشط أو مكتمل.", reply_markup=kb)
        return MAIN_MENU

    quiz_data["finished"] = True

    # --- Calculate Results --- 
    total_questions = quiz_data["total_questions"]
    correct_count = quiz_data["correct_count"]
    wrong_count = quiz_data["wrong_count"]
    skipped_count = quiz_data["skipped_count"]
    
    score_percentage = (correct_count / total_questions * 100) if total_questions > 0 else 0
    end_time = datetime.now()
    duration = end_time - quiz_data["start_time"]
    duration_str = str(duration).split('.')[0]

    # --- Prepare Results Message --- 
    results_text = f"🏁 *نتائج الاختبار* 🏁\n\n"
    results_text += f"📝 إجمالي الأسئلة: {total_questions}\n"
    results_text += f"✅ الإجابات الصحيحة: {correct_count}\n"
    results_text += f"❌ الإجابات الخاطئة: {wrong_count}\n"
    results_text += f"⏭️ الأسئلة المتخطاة: {skipped_count}\n"
    results_text += f"⏱️ الوقت المستغرق: {duration_str}\n\n"
    results_text += f"🎯 *النتيجة النهائية: {score_percentage:.2f}%*\n\n"

    if score_percentage >= 90:
        results_text += "🎉 ممتاز! أداء رائع!"
    elif score_percentage >= 70:
        results_text += "👍 جيد جداً! استمر في التقدم!"
    elif score_percentage >= 50:
        results_text += "🙂 لا بأس! يمكنك التحسن في المرة القادمة."
    else:
        results_text += "💪 لا تستسلم! حاول مرة أخرى لتحسين نتيجتك."

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
            start_time=quiz_data["start_time"],
            end_time=end_time
        )
        logger.info(f"[DB] Successfully saved quiz results for user {user_id}, quiz {quiz_id}.")
    except Exception as db_exc:
        logger.error(f"[DB] Failed to save quiz results for user {user_id}, quiz {quiz_id}: {db_exc}")

    # --- Send Results and Return to Main Menu --- 
    kb = create_main_menu_keyboard(user_id)
    # **FIX**: Use the actual safe_send_message function
    await safe_send_message(bot, chat_id, text=results_text, reply_markup=kb, parse_mode='Markdown')

    # Clean up quiz data from user_data
    user_data.pop("current_quiz", None)
    user_data.pop("quiz_selection", None)
    logger.info(f"[QUIZ LOGIC] Cleaned up quiz data for user {user_id}.")

    return MAIN_MENU

# --- Callback Query Handler for Skip Button --- 
async def skip_question_button_handler(update: Update, context: CallbackContext) -> int:
    """Handles the skip button press from the inline keyboard."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    
    match = re.match(r"quiz_([^_]+)_skip_(\\d+)", query.data)
    if not match:
        logger.warning(f"[QUIZ LOGIC] Invalid skip callback data format: {query.data}")
        await query.answer("خطأ في بيانات التخطي.")
        return TAKING_QUIZ
        
    quiz_id = match.group(1)
    question_index = int(match.group(2))
    
    return await skip_question_callback(
        context.bot, chat_id, user_id, quiz_id, question_index, context, 
        timed_out=False, error_occurred=False
    )

