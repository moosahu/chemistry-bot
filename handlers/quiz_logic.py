# -*- coding: utf-8 -*-
"""Core logic for handling quizzes in the Chemistry Telegram Bot."""

import random
import time
import uuid
import re # Added for parsing callback data
from datetime import datetime # For saving results timing

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import CallbackContext
from telegram.error import BadRequest

# Import necessary components from other modules
try:
    from config import (
        logger,
        MAIN_MENU, TAKING_QUIZ, SHOWING_RESULTS, # States
        QUESTION_TIMER_SECONDS, FEEDBACK_DELAY, ENABLE_QUESTION_TIMER, # Quiz settings
        NUM_OPTIONS # General config
    )
    from utils.helpers import (
        safe_send_message, safe_edit_message_text,
        remove_job_if_exists
    )
    # Import the specific keyboard creation function from common handler
    from handlers.common import create_main_menu_keyboard
    from utils.api_client import fetch_from_api, transform_api_question
    from database.manager import DB_MANAGER # Import the initialized DB_MANAGER instance
except ImportError as e:
    # Fallback for potential import issues during development/restructuring
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing modules in handlers.quiz_logic: {e}. Using placeholders.")
    # Define placeholders
    MAIN_MENU, TAKING_QUIZ, SHOWING_RESULTS = 0, 5, 6 # Match config.py
    QUESTION_TIMER_SECONDS, FEEDBACK_DELAY, ENABLE_QUESTION_TIMER = 60, 1.5, True
    NUM_OPTIONS = 4
    async def safe_send_message(*args, **kwargs): logger.error("Placeholder safe_send_message called!")
    async def safe_edit_message_text(*args, **kwargs): logger.error("Placeholder safe_edit_message_text called!")
    def remove_job_if_exists(*args, **kwargs): logger.warning("Placeholder remove_job_if_exists called!"); return False
    def create_main_menu_keyboard(*args, **kwargs): logger.error("Placeholder create_main_menu_keyboard called!"); return None
    async def fetch_from_api(*args, **kwargs): logger.error("Placeholder fetch_from_api called!"); return None
    def transform_api_question(q): logger.error("Placeholder transform_api_question called!"); return q # Passthrough
    # Dummy DB_MANAGER
    class DummyDBManager:
        async def save_quiz_result(*args, **kwargs): logger.warning("Dummy DB_MANAGER.save_quiz_result called"); return True
    DB_MANAGER = DummyDBManager()

# --- Timer Callback --- 

async def question_timer_callback(context: CallbackContext):
    """Handles the timeout for a single question."""
    job_context = context.job.context
    chat_id = job_context["chat_id"]
    user_id = job_context["user_id"]
    quiz_id = job_context["quiz_id"]
    question_index = job_context["question_index"]
    logger.info(f"[TIMER] Question timer expired for q:{question_index} quiz:{quiz_id} user:{user_id}.")

    # Access user_data via dispatcher
    if not hasattr(context, "dispatcher"):
         logger.error("[TIMER] Dispatcher not found in context for question_timer_callback.")
         return
    user_data = context.dispatcher.user_data.get(user_id, {})
    quiz_data = user_data.get("current_quiz")

    # Check if the quiz is still active and the timed-out question is the current one
    if (quiz_data and quiz_data.get("quiz_id") == quiz_id and
            quiz_data.get("current_question_index") == question_index and
            not quiz_data.get("finished")):

        logger.info(f"[QUIZ LOGIC] Question {question_index + 1} timed out for user {user_id}.")
        await safe_send_message(context.bot, chat_id, text=f"⏰ انتهى وقت السؤال {question_index + 1}! سيتم اعتباره متخطى.")

        # Call the skip handler, marking it as timed out
        # Pass the bot object explicitly if needed by handle_quiz_skip
        await skip_question_callback(context.bot, chat_id, user_id, quiz_id, question_index, context, timed_out=True)
    else:
        logger.info(f"[TIMER] Quiz {quiz_id} ended or question {question_index} already handled, ignoring timer.")

# --- Quiz Core Functions --- 

async def start_quiz_logic(update: Update, context: CallbackContext) -> int:
    """Fetches questions, initializes quiz state, and sends the first question.
       This is the core logic called by the quiz conversation handler.
    """
    query = update.callback_query # Might be called from callback
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id

    # Retrieve selections made in previous conversation steps
    quiz_selection = context.user_data.get("quiz_selection")
    if not quiz_selection or "type" not in quiz_selection or "count" not in quiz_selection:
        logger.error(f"[QUIZ LOGIC] start_quiz called for user {user_id} without complete quiz_selection.")
        await safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء بدء الاختبار (لم يتم تحديد نوع أو عدد الأسئلة). يرجى المحاولة مرة أخرى.")
        # Go back to main menu as quiz setup failed
        kb = create_main_menu_keyboard(user_id)
        await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    quiz_type = quiz_selection["type"] # e.g., "random", "lesson", "unit", "course"
    quiz_scope_id = quiz_selection.get("scope_id") # ID of lesson/unit/course, or None for random
    num_questions = quiz_selection["count"]
    max_available = quiz_selection.get("max_questions", num_questions) # Max questions API reported

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

    logger.info(f"[QUIZ LOGIC] Starting quiz for user {user_id}: type={quiz_type}, scope={quiz_scope_id}, count={num_questions}")

    # --- Fetch questions from API --- 
    questions_endpoint = "/questions" # Default endpoint
    params = {"limit": num_questions}
    if quiz_type == "course" and quiz_scope_id:
        questions_endpoint = f"/courses/{quiz_scope_id}/questions"
    elif quiz_type == "unit" and quiz_scope_id:
        questions_endpoint = f"/units/{quiz_scope_id}/questions"
    elif quiz_type == "lesson" and quiz_scope_id:
        questions_endpoint = f"/lessons/{quiz_scope_id}/questions"
    elif quiz_type == "random":
        params["random"] = "true" # Assuming API supports random fetching
        # If API doesn't support random, fetch more and sample locally later
        # params = {"limit": num_questions * 2} 

    logger.info(f"[API] Fetching {num_questions} questions from {questions_endpoint} with params {params}")
    api_questions_response = await fetch_from_api(questions_endpoint, params=params)

    # --- Handle API Response --- 
    if api_questions_response == "TIMEOUT":
        logger.error(f"[API] Timeout fetching questions for quiz start (user {user_id}).")
        await safe_send_message(context.bot, chat_id, text="⏳ تعذر تحميل أسئلة الاختبار (مهلة الاتصال). يرجى المحاولة مرة أخرى لاحقاً.")
        kb = create_main_menu_keyboard(user_id)
        await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU
    elif not isinstance(api_questions_response, list):
        logger.error(f"[API] Failed to fetch questions or invalid format for quiz start (user {user_id}). Response: {api_questions_response}")
        await safe_send_message(context.bot, chat_id, text="⚠️ تعذر تحميل أسئلة الاختبار أو أن التنسيق غير صالح. يرجى المحاولة مرة أخرى لاحقاً.")
        kb = create_main_menu_keyboard(user_id)
        await safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    # --- Transform and Validate Questions --- 
    quiz_questions = []
    for q_data in api_questions_response:
        transformed_q = transform_api_question(q_data)
        if transformed_q:
            quiz_questions.append(transformed_q)
        else:
            logger.warning(f"[QUIZ LOGIC] Skipping invalid question data received from API: {q_data}")

    # Adjust num_questions if API returned fewer valid questions or didn't respect limit
    if len(quiz_questions) > num_questions:
        logger.info(f"[QUIZ LOGIC] API returned {len(quiz_questions)} questions, sampling {num_questions}.")
        quiz_questions = random.sample(quiz_questions, num_questions)
    elif len(quiz_questions) < num_questions:
        logger.warning(f"[QUIZ LOGIC] Requested {num_questions} questions, but only got {len(quiz_questions)} valid ones from API.")
        num_questions = len(quiz_questions) # Adjust count to actual number

    if num_questions == 0:
        logger.error(f"[QUIZ LOGIC] No valid questions found after API fetch and transformation for user {user_id}. Aborting.")
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
        "answers": [None] * num_questions, # Store user answer index (or -1 for skip/timeout)
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
        return

    question = quiz_data["questions"][question_index]
    quiz_data["current_question_index"] = question_index # Update current index

    # --- Prepare Question Text and Media --- 
    # CORRECTED LINE: Use single quotes inside the f-string expression
    question_text = f"*السؤال {question_index + 1} من {quiz_data['total_questions']}*\n\n"
    if question.get("question_text"):
        question_text += question["question_text"]
    
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
    
    # TODO: Handle image options properly. Current implementation might be basic.
    # If options have images, consider sending them separately or using a different format.
    # For now, create text buttons, indicating if an option is image-based.
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
            
        # Create button
        callback_data = f"quiz_{quiz_id}_ans_{question_index}_{i}"
        row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
        
        # Simple layout: 2 buttons per row
        if len(row) == 2:
            keyboard_buttons.append(row)
            row = []
            
    if row: # Add remaining buttons if odd number
        keyboard_buttons.append(row)

    # Add Skip button
    keyboard_buttons.append([InlineKeyboardButton("⏭️ تخطي السؤال", callback_data=f"quiz_{quiz_id}_skip_{question_index}")])
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)

    # --- Send Message (Text or Photo) --- 
    sent_message = None
    main_image_url = question.get("image_url")
    try:
        if main_image_url:
            logger.debug(f"[QUIZ LOGIC] Sending question {question_index} with image: {main_image_url}")
            sent_message = await bot.send_photo(
                chat_id=chat_id,
                photo=main_image_url,
                caption=question_text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
            logger.debug(f"[QUIZ LOGIC] Sending question {question_index} as text.")
            sent_message = await safe_send_message(
                bot,
                chat_id=chat_id,
                text=question_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    except BadRequest as e:
        logger.error(f"[QUIZ LOGIC] BadRequest sending question {question_index} to {chat_id}: {e}")
        # Try sending as plain text if Markdown fails
        if "Can't parse entities" in str(e): # Corrected error check string
            try:
                # Corrected re.sub replacement string - remove newline
                plain_text = re.sub(r"[*_`[\]()~>#+-=|{}.!]", r"\\\1", question_text) # Escape markdown chars
                if main_image_url:
                     sent_message = await bot.send_photo(chat_id=chat_id, photo=main_image_url, caption=plain_text, reply_markup=reply_markup)
                else:
                     sent_message = await safe_send_message(bot, chat_id=chat_id, text=plain_text, reply_markup=reply_markup)
            except Exception as fallback_e:
                 logger.error(f"[QUIZ LOGIC] Failed to send question {question_index} even as plain text: {fallback_e}")
                 await safe_send_message(bot, chat_id, text="حدث خطأ فادح أثناء إرسال السؤال. سيتم إنهاء الاختبار.")
                 # Consider ending the quiz gracefully here
                 await end_quiz(bot, chat_id, user_id, quiz_id, context, error=True)
                 return # Stop further processing for this question
        else:
            # Other BadRequest, maybe image URL invalid?
            await safe_send_message(bot, chat_id, text="حدث خطأ غير متوقع أثناء إرسال السؤال (قد يكون بسبب مشكلة في الصورة). سيتم إنهاء الاختبار.")
            await end_quiz(bot, chat_id, user_id, quiz_id, context, error=True)
            return # Stop further processing

    except Exception as e:
        logger.exception(f"[QUIZ LOGIC] Unexpected error sending question {question_index} to {chat_id}: {e}")
        await safe_send_message(bot, chat_id, text="حدث خطأ غير متوقع أثناء إرسال السؤال. سيتم إنهاء الاختبار.")
        await end_quiz(bot, chat_id, user_id, quiz_id, context, error=True)
        return # Stop further processing

    # --- Store Message ID and Start Timer --- 
    if sent_message:
        quiz_data["last_question_message_id"] = sent_message.message_id
        logger.debug(f"[QUIZ LOGIC] Stored message_id {sent_message.message_id} for question {question_index}")

        # Schedule timer if enabled
        if ENABLE_QUESTION_TIMER:
            job_name = f"qtimer_{chat_id}_{user_id}_{quiz_id}_{question_index}"
            # Remove previous timer if exists
            remove_job_if_exists(job_name, context)
            # Schedule new timer
            context.job_queue.run_once(
                question_timer_callback,
                QUESTION_TIMER_SECONDS,
                context={"chat_id": chat_id, "user_id": user_id, "quiz_id": quiz_id, "question_index": question_index},
                name=job_name
            )
            quiz_data["question_timer_job_name"] = job_name
            logger.info(f"[QUIZ LOGIC] Scheduled timer job '{job_name}' for question {question_index}")
    else:
        logger.error(f"[QUIZ LOGIC] Failed to get message_id after sending question {question_index}. Timer not started.")
        # Consider ending quiz if message sending failed critically
        # await end_quiz(bot, chat_id, user_id, quiz_id, context, error=True)


async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    """Handles user's answer selection via callback query."""
    query = update.callback_query
    await query.answer() # Acknowledge callback

    user_id = query.from_user.id
    chat_id = query.message.chat_id
    callback_data = query.data

    # --- Parse Callback Data --- 
    # Expected format: "quiz_{quiz_id}_ans_{question_index}_{answer_index}"
    match = re.match(r"quiz_(.+)_ans_(\\d+)_(\\d+)", callback_data)
    if not match:
        logger.warning(f"[QUIZ CB] Invalid callback data format received: {callback_data}")
        await safe_edit_message_text(query.message, text="حدث خطأ في معالجة الإجابة (بيانات غير صالحة).")
        return TAKING_QUIZ # Stay in the same state

    quiz_id_cb = match.group(1)
    question_index_cb = int(match.group(2))
    answer_index_cb = int(match.group(3))

    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    # --- Validate Quiz State --- 
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id_cb or quiz_data.get("finished"):
        logger.warning(f"[QUIZ CB] Answer received for inactive/mismatched quiz {quiz_id_cb} user {user_id}")
        await safe_edit_message_text(query.message, text="هذا الاختبار لم يعد نشطًا.")
        return MAIN_MENU # Or end conversation state if applicable
    if question_index_cb != quiz_data.get("current_question_index"):
        logger.warning(f"[QUIZ CB] Answer received for non-current question {question_index_cb} (current is {quiz_data.get('current_question_index')}) quiz {quiz_id_cb} user {user_id}")
        await safe_edit_message_text(query.message, text="لقد تم تجاوز هذا السؤال بالفعل.")
        return TAKING_QUIZ # Stay in the same state

    # --- Process Answer --- 
    question = quiz_data["questions"][question_index_cb]
    correct_answer_index = question.get("correct_option") - 1 # Assuming 1-based index from API

    # Remove timer for this question
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        remove_job_if_exists(timer_job_name, context)
        quiz_data["question_timer_job_name"] = None # Clear job name
        logger.info(f"[QUIZ CB] Removed timer job '{timer_job_name}' for question {question_index_cb}")

    # Store user's answer
    quiz_data["answers"][question_index_cb] = answer_index_cb

    # --- Provide Feedback --- 
    feedback_text = ""
    is_correct = (answer_index_cb == correct_answer_index)

    if is_correct:
        quiz_data["correct_count"] += 1
        feedback_text = "✅ إجابة صحيحة!"
        logger.info(f"[QUIZ CB] User {user_id} answered question {question_index_cb} correctly ({answer_index_cb}).")
    else:
        quiz_data["wrong_count"] += 1
        correct_option_text = question.get(f"option{correct_answer_index + 1}", f"الخيار {correct_answer_index + 1}")
        feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة هي: *{correct_option_text}*"
        logger.info(f"[QUIZ CB] User {user_id} answered question {question_index_cb} incorrectly ({answer_index_cb}). Correct was {correct_answer_index}.")

    # Add explanation if available
    explanation = question.get("explanation")
    if explanation:
        feedback_text += f"\n\n*الشرح:*\n{explanation}"

    # --- Edit Original Message to Show Feedback --- 
    try:
        # Edit the message to remove buttons and show feedback
        await safe_edit_message_text(
            query.message,
            text=query.message.caption or query.message.text, # Keep original text/caption
            reply_markup=None, # Remove keyboard
            parse_mode="Markdown" # Keep original parse mode if possible
        )
        # Send feedback as a new message
        await safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode="Markdown")
    except BadRequest as e:
        logger.error(f"[QUIZ CB] BadRequest editing message or sending feedback for q:{question_index_cb} user:{user_id}: {e}")
        # If editing fails (e.g., message too old), just send feedback as new message
        await safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode="Markdown") # Send as new message on error
    except Exception as e:
        logger.exception(f"[QUIZ CB] Unexpected error editing message or sending feedback for q:{question_index_cb} user:{user_id}: {e}")
        await safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode="Markdown") # Send as new message on error

    # --- Delay and Move to Next Question or End Quiz --- 
    time.sleep(FEEDBACK_DELAY) # Pause briefly to show feedback

    next_question_index = question_index_cb + 1
    if next_question_index < quiz_data["total_questions"]:
        await send_question(context.bot, chat_id, user_id, quiz_id_cb, next_question_index, context)
        return TAKING_QUIZ
    else:
        # Quiz finished
        logger.info(f"[QUIZ CB] Quiz {quiz_id_cb} finished for user {user_id}.")
        return await end_quiz(context.bot, chat_id, user_id, quiz_id_cb, context)

async def skip_question_callback(bot, chat_id: int, user_id: int, quiz_id: str, question_index: int, context: CallbackContext, timed_out: bool = False, error_skip: bool = False):
    """Handles skipping a question, either by user action, timeout, or error."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    # --- Validate Quiz State --- 
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ SKIP] Skip called for inactive/mismatched quiz {quiz_id} user {user_id}")
        # Don't send message if called for inactive quiz
        return TAKING_QUIZ # Or appropriate state

    if question_index != quiz_data.get("current_question_index"):
        logger.warning(f"[QUIZ SKIP] Skip called for non-current question {question_index} (current is {quiz_data.get('current_question_index')}) quiz {quiz_id} user {user_id}")
        # Avoid double skipping if timer and user skip concurrently
        return TAKING_QUIZ

    # --- Process Skip --- 
    logger.info(f"[QUIZ SKIP] Processing skip for question {question_index} quiz {quiz_id} user {user_id}. Timed out: {timed_out}, Error: {error_skip}")

    # Remove timer if it exists and wasn't the cause
    if not timed_out:
        timer_job_name = quiz_data.get("question_timer_job_name")
        if timer_job_name:
            remove_job_if_exists(timer_job_name, context)
            quiz_data["question_timer_job_name"] = None
            logger.info(f"[QUIZ SKIP] Removed timer job '{timer_job_name}' due to user skip.")

    # Mark question as skipped (-1)
    quiz_data["answers"][question_index] = -1
    quiz_data["skipped_count"] += 1

    # --- Provide Feedback (Optional, only if not timed out/error) --- 
    if not timed_out and not error_skip:
        # Edit the original message to remove buttons
        last_msg_id = quiz_data.get("last_question_message_id")
        if last_msg_id:
            try:
                # Find the message object (might need query if only ID is stored)
                # Assuming context.bot can access the message via chat_id and message_id
                # This part might need adjustment based on how message objects are handled
                message_to_edit = await context.bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=last_msg_id,
                    reply_markup=None # Remove keyboard
                )
                logger.debug(f"[QUIZ SKIP] Removed keyboard from message {last_msg_id}")
            except BadRequest as e:
                 logger.warning(f"[QUIZ SKIP] BadRequest removing keyboard from msg {last_msg_id}: {e}")
            except Exception as e:
                 logger.error(f"[QUIZ SKIP] Error removing keyboard from msg {last_msg_id}: {e}")
        # Send confirmation message for user skip
        await safe_send_message(context.bot, chat_id, text=f"تم تخطي السؤال {question_index + 1}.")

    # --- Move to Next Question or End Quiz --- 
    time.sleep(0.5) # Short delay after skip

    next_question_index = question_index + 1
    if next_question_index < quiz_data["total_questions"]:
        await send_question(context.bot, chat_id, user_id, quiz_id, next_question_index, context)
        return TAKING_QUIZ
    else:
        # Quiz finished
        logger.info(f"[QUIZ SKIP] Quiz {quiz_id} finished after skipping last question {question_index} for user {user_id}.")
        return await end_quiz(context.bot, chat_id, user_id, quiz_id, context)


async def handle_quiz_skip_callback_query(update: Update, context: CallbackContext) -> int:
    """Handles the 'Skip Question' button press via callback query."""
    query = update.callback_query
    await query.answer() # Acknowledge callback

    user_id = query.from_user.id
    chat_id = query.message.chat_id
    callback_data = query.data

    # --- Parse Callback Data --- 
    # Expected format: "quiz_{quiz_id}_skip_{question_index}"
    match = re.match(r"quiz_(.+)_skip_(\\d+)", callback_data)
    if not match:
        logger.warning(f"[QUIZ SKIP CB] Invalid callback data format received: {callback_data}")
        await safe_edit_message_text(query.message, text="حدث خطأ في معالجة التخطي (بيانات غير صالحة).")
        return TAKING_QUIZ # Stay in the same state

    quiz_id_cb = match.group(1)
    question_index_cb = int(match.group(2))

    # Call the main skip logic
    return await skip_question_callback(context.bot, chat_id, user_id, quiz_id_cb, question_index_cb, context, timed_out=False)


async def end_quiz(bot, chat_id: int, user_id: int, quiz_id: str, context: CallbackContext, error: bool = False) -> int:
    """Finalizes the quiz, calculates results, saves them, and shows summary."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    # --- Validate Quiz State --- 
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id:
        logger.warning(f"[QUIZ END] end_quiz called for inactive/mismatched quiz {quiz_id} user {user_id}")
        # Send generic message if quiz data is missing
        kb = create_main_menu_keyboard(user_id)
        await safe_send_message(bot, chat_id, text="انتهى الاختبار أو حدث خطأ. العودة إلى القائمة الرئيسية.", reply_markup=kb)
        if "current_quiz" in user_data: del user_data["current_quiz"] # Clean up
        return MAIN_MENU

    # Mark quiz as finished to prevent concurrent operations
    quiz_data["finished"] = True

    # --- Clean Up Timer --- 
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        remove_job_if_exists(timer_job_name, context)
        logger.info(f"[QUIZ END] Removed final timer job '{timer_job_name}' for quiz {quiz_id}")

    # --- Handle Error Case --- 
    if error:
        logger.error(f"[QUIZ END] Ending quiz {quiz_id} for user {user_id} due to an error.")
        kb = create_main_menu_keyboard(user_id)
        await safe_send_message(bot, chat_id, text="⚠️ تم إنهاء الاختبار بسبب خطأ غير متوقع.", reply_markup=kb)
        if "current_quiz" in user_data: del user_data["current_quiz"] # Clean up
        return MAIN_MENU

    # --- Calculate Results --- 
    total_questions = quiz_data["total_questions"]
    correct_count = quiz_data["correct_count"]
    wrong_count = quiz_data["wrong_count"]
    skipped_count = quiz_data["skipped_count"]
    answered_count = correct_count + wrong_count
    score = (correct_count / total_questions) * 100 if total_questions > 0 else 0
    end_time = datetime.now()
    duration = end_time - quiz_data["start_time"] # Calculate duration

    logger.info(f"[QUIZ END] Quiz {quiz_id} results for user {user_id}: Correct={correct_count}, Wrong={wrong_count}, Skipped={skipped_count}, Total={total_questions}, Score={score:.2f}%, Duration={duration}")

    # --- Save Results to Database --- 
    try:
        success = await DB_MANAGER.save_quiz_result(
            user_id=user_id,
            quiz_type=quiz_data.get("quiz_type", "unknown"),
            scope_id=quiz_data.get("quiz_scope_id"), # Can be None
            score=score,
            correct_count=correct_count,
            wrong_count=wrong_count,
            skipped_count=skipped_count,
            total_questions=total_questions,
            duration_seconds=duration.total_seconds(),
            quiz_timestamp=quiz_data["start_time"] # Use start time as timestamp
        )
        if success:
            logger.info(f"[DB SAVE] Successfully saved quiz {quiz_id} results for user {user_id}.")
        else:
            logger.error(f"[DB SAVE] Failed to save quiz {quiz_id} results for user {user_id}.")
            # Don't block user, just log the error
    except Exception as e:
        logger.exception(f"[DB SAVE] Exception saving quiz {quiz_id} results for user {user_id}: {e}")
        # Don't block user

    # --- Prepare Results Summary Message --- 
    summary_text = f"🎉 *نتائج الاختبار* 🎉\n\n"
    summary_text += f"🔢 إجمالي الأسئلة: {total_questions}\n"
    summary_text += f"✅ الإجابات الصحيحة: {correct_count}\n"
    summary_text += f"❌ الإجابات الخاطئة: {wrong_count}\n"
    summary_text += f"⏭️ الأسئلة المتخطاة: {skipped_count}\n"
    summary_text += f"⏱️ الوقت المستغرق: {str(duration).split('.')[0]} (تقريباً)\n\n" # Show H:MM:SS
    summary_text += f"🏆 *النتيجة النهائية: {score:.1f}%*\n\n"

    # Add encouragement based on score
    if score >= 90:
        summary_text += "ممتاز! أداء رائع! ✨"
    elif score >= 70:
        summary_text += "جيد جداً! استمر في التقدم! 👍"
    elif score >= 50:
        summary_text += "لا بأس! يمكنك التحسن مع المزيد من المراجعة. 💪"
    else:
        summary_text += "تحتاج إلى المزيد من المراجعة. لا تستسلم! 📚"

    # --- Send Results and Clean Up --- 
    kb = create_main_menu_keyboard(user_id) # Get main menu keyboard
    await safe_send_message(bot, chat_id, text=summary_text, parse_mode="Markdown", reply_markup=kb)

    # Clean up quiz data from user_data
    if "current_quiz" in user_data:
        del user_data["current_quiz"]
    if "quiz_selection" in user_data:
        del user_data["quiz_selection"] # Clean up selection as well
    logger.info(f"[QUIZ END] Cleaned up quiz data for user {user_id}.")

    return MAIN_MENU # Return to main menu state

