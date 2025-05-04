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
        await handle_quiz_skip(context.bot, chat_id, user_id, quiz_id, question_index, context, timed_out=True)
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
                 await end_quiz(bot, chat_id, user_id, quiz_id, context, error=True)
                 return
        else:
             # Other BadRequest (e.g., invalid image URL)
             await safe_send_message(bot, chat_id, text="حدث خطأ أثناء إرسال السؤال (قد يكون رابط الصورة غير صالح). سيتم تخطي هذا السؤال.")
             # Skip this question automatically
             await handle_quiz_skip(bot, chat_id, user_id, quiz_id, question_index, context, timed_out=False, error_skip=True)
             return # Stop further processing for this question
    except Exception as e:
        logger.exception(f"[QUIZ LOGIC] Unexpected error sending question {question_index} to {chat_id}: {e}")
        await safe_send_message(bot, chat_id, text="حدث خطأ غير متوقع أثناء إرسال السؤال. سيتم إنهاء الاختبار.")
        await end_quiz(bot, chat_id, user_id, quiz_id, context, error=True)
        return

    if sent_message:
        quiz_data["last_question_message_id"] = sent_message.message_id
        # --- Start Question Timer --- 
        if ENABLE_QUESTION_TIMER and QUESTION_TIMER_SECONDS > 0:
            job_name = f"qtimer_{chat_id}_{quiz_id}_{question_index}"
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
            logger.info(f"[QUIZ LOGIC] Started timer ({QUESTION_TIMER_SECONDS}s) for question {question_index}, job: {job_name}")
    else:
        logger.error(f"[QUIZ LOGIC] Failed to get message_id after sending question {question_index}. Timer not started.")

async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    """Handles user's answer selection via inline keyboard button."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    user_id = query.from_user.id
    chat_id = query.message.chat_id
    callback_data = query.data

    # --- Parse Callback Data --- 
    # Expected format: "quiz_{quiz_id}_ans_{question_index}_{answer_index}"
    match = re.match(r"quiz_([^_]+)_ans_(\d+)_(\d+)", callback_data)
    if not match:
        logger.warning(f"[QUIZ CB] Invalid answer callback data format: {callback_data}")
        await safe_send_message(context.bot, chat_id, text="حدث خطأ في بيانات الاستجابة. حاول مرة أخرى.")
        return TAKING_QUIZ # Stay in the same state

    quiz_id_cb = match.group(1)
    question_index_cb = int(match.group(2))
    answer_index_cb = int(match.group(3))

    # --- Validate Quiz State --- 
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id_cb or quiz_data.get("finished"):
        logger.warning(f"[QUIZ CB] Answer received for inactive/mismatched quiz {quiz_id_cb} user {user_id}")
        await safe_edit_message_text(query.message, text="انتهى هذا الاختبار أو أنك في اختبار آخر.")
        return TAKING_QUIZ # Or maybe MAIN_MENU?
    if question_index_cb != quiz_data["current_question_index"]:
        logger.warning(f"[QUIZ CB] Answer received for non-current question (cb:{question_index_cb}, current:{quiz_data["current_question_index"]}) quiz {quiz_id_cb}")
        await safe_edit_message_text(query.message, text="لقد تم الرد على هذا السؤال بالفعل أو تم تخطيه.")
        return TAKING_QUIZ

    # --- Stop Timer --- 
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        if remove_job_if_exists(timer_job_name, context):
            logger.info(f"[QUIZ CB] Removed timer job {timer_job_name} for question {question_index_cb}.")
        quiz_data["question_timer_job_name"] = None # Clear job name

    # --- Process Answer --- 
    question = quiz_data["questions"][question_index_cb]
    correct_answer_index = question.get("correct_option_index")
    is_correct = (answer_index_cb == correct_answer_index)

    quiz_data["answers"][question_index_cb] = answer_index_cb # Record user's choice
    feedback_text = ""
    if is_correct:
        quiz_data["correct_count"] += 1
        feedback_text = "✅ إجابة صحيحة!"
        logger.info(f"[QUIZ CB] User {user_id} answered q:{question_index_cb} correctly ({answer_index_cb}). Quiz: {quiz_id_cb}")
    else:
        quiz_data["wrong_count"] += 1
        feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة هي الخيار رقم {correct_answer_index + 1}."
        logger.info(f"[QUIZ CB] User {user_id} answered q:{question_index_cb} incorrectly ({answer_index_cb}, correct: {correct_answer_index}). Quiz: {quiz_id_cb}")

    # Add explanation if available
    if question.get("explanation"):
        feedback_text += f"\n\n*الشرح:* {question['explanation']}"

    # --- Update Message with Feedback --- 
    # Edit the original question message to show feedback and disable buttons
    original_message_text = query.message.caption if query.message.photo else query.message.text
    new_text = original_message_text + "\n\n" + feedback_text
    try:
        if query.message.photo:
            # Can't easily edit caption AND remove keyboard with send_photo, 
            # maybe send a new message or edit text only?
            # For simplicity, let's just edit the caption text if possible, keeping photo
            # Note: Editing media message markup might require specific handling or might not be fully supported.
            # await query.edit_message_caption(caption=new_text, parse_mode="Markdown") # Might fail to remove keyboard
            # Alternative: Send feedback as a new message
            await safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode="Markdown")
            # Try removing keyboard from original photo message (might fail)
            try: await query.edit_message_reply_markup(reply_markup=None)
            except: pass
        else:
            await safe_edit_message_text(query.message, text=new_text, reply_markup=None, parse_mode="Markdown")
    except BadRequest as e:
        logger.error(f"[QUIZ CB] BadRequest editing message for feedback q:{question_index_cb}: {e}")
        # If editing fails, send feedback as a new message
        await safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode="Markdown")
    except Exception as e:
        logger.exception(f"[QUIZ CB] Unexpected error editing message for feedback q:{question_index_cb}: {e}")
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

async def handle_quiz_skip(bot, chat_id: int, user_id: int, quiz_id: str, question_index: int, context: CallbackContext, timed_out: bool = False, error_skip: bool = False):
    """Handles skipping a question, either by user action, timeout, or error."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    # --- Validate Quiz State --- 
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ SKIP] Skip called for inactive/mismatched quiz {quiz_id} user {user_id}")
        # Don't send message if called internally from timer/error
        # if not timed_out and not error_skip: await safe_send_message(bot, chat_id, text="لا يمكنك تخطي سؤال من اختبار غير نشط.")
        return TAKING_QUIZ
    if question_index != quiz_data["current_question_index"]:
        logger.warning(f"[QUIZ SKIP] Skip called for non-current question (cb:{question_index}, current:{quiz_data["current_question_index"]}) quiz {quiz_id}")
        # Don't send message if called internally
        # if not timed_out and not error_skip: await safe_send_message(bot, chat_id, text="لا يمكنك تخطي سؤال تم الرد عليه بالفعل.")
        return TAKING_QUIZ

    # --- Stop Timer --- 
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        if remove_job_if_exists(timer_job_name, context):
            logger.info(f"[QUIZ SKIP] Removed timer job {timer_job_name} for question {question_index}.")
        quiz_data["question_timer_job_name"] = None

    # --- Process Skip --- 
    quiz_data["answers"][question_index] = -1 # Mark as skipped
    quiz_data["skipped_count"] += 1
    logger.info(f"[QUIZ SKIP] User {user_id} skipped q:{question_index}. Reason: {"Timeout" if timed_out else "User Action" if not error_skip else "Error"}. Quiz: {quiz_id}")

    feedback_text = "⏭️ تم تخطي السؤال."
    if timed_out:
        feedback_text = "⏰ انتهى وقت السؤال، تم التخطي."
    elif error_skip:
         feedback_text = "⚠️ حدث خطأ، تم تخطي السؤال."

    # --- Update Message --- 
    # Edit the original question message if possible
    message_id = quiz_data.get("last_question_message_id")
    if message_id:
        try:
            # Get the original message object (might need chat_id as well)
            # This part is tricky without the original Update/Query object
            # Let's try editing based on message_id, might fail
            # await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
            # Best approach might be to send feedback as a new message if called internally
            if not timed_out and not error_skip:
                 # If user clicked skip button, we have the query object
                 query = context.user_data.get("_last_quiz_skip_query") # Need to store this in callback handler
                 if query and query.message.message_id == message_id:
                     original_message_text = query.message.caption if query.message.photo else query.message.text
                     new_text = original_message_text + "\n\n" + feedback_text
                     if query.message.photo:
                         # await query.edit_message_caption(caption=new_text, parse_mode="Markdown")
                         await safe_send_message(bot, chat_id, text=feedback_text, parse_mode="Markdown")
                         try: await query.edit_message_reply_markup(reply_markup=None)
                         except: pass
                     else:
                         await safe_edit_message_text(query.message, text=new_text, reply_markup=None, parse_mode="Markdown")
                 else:
                      await safe_send_message(bot, chat_id, text=feedback_text) # Send as new if query mismatch
            else:
                 # If timed out or error skip, just send feedback as new message
                 await safe_send_message(bot, chat_id, text=feedback_text)
        except Exception as e:
            logger.error(f"[QUIZ SKIP] Failed to edit message {message_id} for skip feedback: {e}")
            await safe_send_message(bot, chat_id, text=feedback_text) # Send as new message on error
    else:
        # If no message_id, just send feedback
        await safe_send_message(bot, chat_id, text=feedback_text)

    # --- Delay and Move to Next Question or End Quiz --- 
    time.sleep(FEEDBACK_DELAY if not timed_out else 0.1) # Shorter delay if timed out

    next_question_index = question_index + 1
    if next_question_index < quiz_data["total_questions"]:
        await send_question(bot, chat_id, user_id, quiz_id, next_question_index, context)
        return TAKING_QUIZ
    else:
        # Quiz finished
        logger.info(f"[QUIZ SKIP] Quiz {quiz_id} finished after skip for user {user_id}.")
        return await end_quiz(bot, chat_id, user_id, quiz_id, context)

async def end_quiz(bot, chat_id: int, user_id: int, quiz_id: str, context: CallbackContext, error: bool = False) -> int:
    """Ends the current quiz, calculates results, saves them, and shows summary."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    if not quiz_data or quiz_data.get("quiz_id") != quiz_id:
        logger.warning(f"[QUIZ END] end_quiz called for inactive/mismatched quiz {quiz_id} user {user_id}")
        # Avoid sending message if called due to error during setup
        if not error:
            await safe_send_message(bot, chat_id, text="لا يوجد اختبار نشط لإنهاءه.")
        kb = create_main_menu_keyboard(user_id)
        await safe_send_message(bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    if quiz_data.get("finished"): # Prevent double ending
        logger.info(f"[QUIZ END] Quiz {quiz_id} already marked as finished for user {user_id}. Skipping end logic.")
        return SHOWING_RESULTS # Or MAIN_MENU?

    quiz_data["finished"] = True
    end_time = datetime.now()

    # --- Cancel any running timer --- 
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        remove_job_if_exists(timer_job_name, context)
        logger.info(f"[QUIZ END] Removed timer job {timer_job_name} at end of quiz {quiz_id}.")

    # --- Calculate Results --- 
    total = quiz_data["total_questions"]
    correct = quiz_data["correct_count"]
    wrong = quiz_data["wrong_count"]
    skipped = quiz_data["skipped_count"]
    # Ensure counts add up, adjust skipped if necessary (e.g., if error occurred)
    calculated_skipped = total - correct - wrong
    if calculated_skipped != skipped:
        logger.warning(f"[QUIZ END] Discrepancy in counts for quiz {quiz_id}: total={total}, c={correct}, w={wrong}, s={skipped}. Calculated_skipped={calculated_skipped}. Using calculated.")
        skipped = calculated_skipped
        quiz_data["skipped_count"] = skipped # Update data

    score_percentage = (correct / total * 100) if total > 0 else 0
    start_time = quiz_data["start_time"]
    duration = end_time - start_time

    # --- Prepare Results Summary --- 
    summary = f"🏁 *نتائج الاختبار* 🏁\n\n"
    summary += f"🔢 إجمالي الأسئلة: {total}\n"
    summary += f"✅ الإجابات الصحيحة: {correct}\n"
    summary += f"❌ الإجابات الخاطئة: {wrong}\n"
    summary += f"⏭️ الأسئلة المتخطاة: {skipped}\n"
    summary += f"📊 النسبة المئوية: {score_percentage:.2f}%\n"
    summary += f"⏱️ الوقت المستغرق: {str(duration).split('.')[0]} (س:د:ث)\n"

    # --- Save Results to Database --- 
    # Prepare details JSON (e.g., list of question IDs and user answers)
    details_to_save = {
        "questions": [q.get("question_id", None) for q in quiz_data["questions"]],
        "answers": quiz_data["answers"]
        # Add more details if needed, e.g., correct answers
    }
    try:
        save_success = await DB_MANAGER.save_quiz_result(
            user_id=user_id,
            quiz_type=quiz_data["quiz_type"],
            quiz_scope_id=quiz_data.get("quiz_scope_id"),
            total_questions=total,
            correct_count=correct,
            wrong_count=wrong,
            skipped_count=skipped,
            score_percentage=score_percentage,
            start_time=start_time,
            end_time=end_time,
            details=details_to_save
        )
        if save_success:
            logger.info(f"[DB SAVE] Successfully saved quiz results for quiz {quiz_id}, user {user_id}.")
        else:
            logger.error(f"[DB SAVE] Failed to save quiz results for quiz {quiz_id}, user {user_id}.")
            summary += "\n\n⚠️ *تعذر حفظ نتيجة هذا الاختبار في قاعدة البيانات.*"
    except Exception as db_e:
        logger.exception(f"[DB SAVE] Exception saving quiz results for quiz {quiz_id}, user {user_id}: {db_e}")
        summary += "\n\n⚠️ *حدث خطأ غير متوقع أثناء حفظ نتيجة الاختبار.*"

    # --- Send Summary and Return to Main Menu --- 
    await safe_send_message(bot, chat_id, text=summary, parse_mode="Markdown")

    # Clean up quiz data from user_data
    if "current_quiz" in context.user_data:
        del context.user_data["current_quiz"]
    if "quiz_selection" in context.user_data:
         del context.user_data["quiz_selection"]

    # Send main menu keyboard
    kb = create_main_menu_keyboard(user_id)
    await safe_send_message(bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)

    logger.info(f"[QUIZ END] Quiz {quiz_id} processing complete for user {user_id}. Returning to main menu.")
    return MAIN_MENU

