# -*- coding: utf-8 -*-
"""Core logic for handling quizzes in the Chemistry Telegram Bot (Corrected v2 - Random logic fix)."""

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
    async def fetch_from_api(*args, **kwargs): logger.error("Placeholder fetch_from_api called!"); return None # Make it async
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
        await skip_question_callback(context.bot, chat_id, user_id, quiz_id, question_index, context, timed_out=True)
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
        api_questions_response = await fetch_from_api(questions_endpoint, params=params)

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
            if transformed_q:
                valid_api_questions.append(transformed_q)
            else:
                logger.warning(f"[QUIZ LOGIC] Skipping invalid question data received from API ({questions_endpoint}): {q_data}")
        
        # Adjust num_questions if API returned fewer valid questions or didn't respect limit
        if len(valid_api_questions) > num_questions:
            logger.info(f"[QUIZ LOGIC] API ({questions_endpoint}) returned {len(valid_api_questions)} questions, sampling {num_questions}.")
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
    
    # Create text buttons, indicating if an option is image-based.
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
        if "Can't parse entities" in str(e):
            try:
                plain_text = re.sub(r"[*_`[\]()~>#+-=|{}.!]", r"\\\1", question_text) # Escape markdown chars
                if main_image_url:
                     sent_message = await bot.send_photo(chat_id=chat_id, photo=main_image_url, caption=plain_text, reply_markup=reply_markup)
                else:
                     sent_message = await safe_send_message(bot, chat_id=chat_id, text=plain_text, reply_markup=reply_markup)
            except Exception as fallback_e:
                 logger.error(f"[QUIZ LOGIC] Failed to send question {question_index} even as plain text: {fallback_e}")
                 await safe_send_message(bot, chat_id, text="حدث خطأ فادح أثناء إرسال السؤال. سيتم إنهاء الاختبار.")
                 await end_quiz(bot, chat_id, user_id, quiz_id, context, error=True)
                 return # Stop processing
        else:
            # Other BadRequest errors
            await safe_send_message(bot, chat_id, text="حدث خطأ غير متوقع أثناء إرسال السؤال. سيتم إنهاء الاختبار.")
            await end_quiz(bot, chat_id, user_id, quiz_id, context, error=True)
            return # Stop processing
    except Exception as e:
        logger.error(f"[QUIZ LOGIC] Unexpected error sending question {question_index} to {chat_id}: {e}")
        await safe_send_message(bot, chat_id, text="حدث خطأ غير متوقع أثناء إرسال السؤال. سيتم إنهاء الاختبار.")
        await end_quiz(bot, chat_id, user_id, quiz_id, context, error=True)
        return # Stop processing

    if sent_message:
        quiz_data["last_question_message_id"] = sent_message.message_id
        # --- Start Question Timer --- 
        if ENABLE_QUESTION_TIMER and QUESTION_TIMER_SECONDS > 0:
            job_name = f"qtimer_{chat_id}_{user_id}_{quiz_id}_{question_index}"
            # Remove previous timer job if exists
            remove_job_if_exists(job_name, context)
            # Schedule new timer
            timer_context = {
                "chat_id": chat_id,
                "user_id": user_id,
                "quiz_id": quiz_id,
                "question_index": question_index
            }
            context.job_queue.run_once(
                question_timer_callback,
                QUESTION_TIMER_SECONDS,
                context=timer_context,
                name=job_name
            )
            quiz_data["question_timer_job_name"] = job_name
            logger.debug(f"[QUIZ LOGIC] Started timer ({QUESTION_TIMER_SECONDS}s) job: {job_name}")
    else:
        logger.error(f"[QUIZ LOGIC] Failed to send question {question_index} message to user {user_id}.")
        # Attempt to end quiz gracefully if message sending failed
        await safe_send_message(bot, chat_id, text="حدث خطأ فادح أثناء إرسال السؤال. سيتم إنهاء الاختبار.")
        await end_quiz(bot, chat_id, user_id, quiz_id, context, error=True)

async def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    """Handles user's answer selection from the inline keyboard."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # --- Parse Callback Data --- 
    # Format: quiz_{quiz_id}_ans_{question_index}_{selected_option_index}
    try:
        _, quiz_id, _, question_index_str, selected_option_index_str = query.data.split("_")
        question_index = int(question_index_str)
        selected_option_index = int(selected_option_index_str)
    except (ValueError, IndexError) as e:
        logger.error(f"[QUIZ LOGIC] Invalid callback data format received: {query.data}. Error: {e}")
        await safe_edit_message_text(query, text="حدث خطأ في معالجة إجابتك. يرجى المحاولة مرة أخرى.")
        return TAKING_QUIZ # Stay in the same state

    # --- Validate Quiz State --- 
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ LOGIC] Answer received for inactive/mismatched quiz {quiz_id} user {user_id}")
        await safe_edit_message_text(query, text="هذا الاختبار لم يعد نشطاً.", reply_markup=None)
        return TAKING_QUIZ # Or potentially end state
    if question_index != quiz_data.get("current_question_index"):
        logger.warning(f"[QUIZ LOGIC] Answer received for non-current question (q:{question_index}, current:{quiz_data.get('current_question_index')}) quiz {quiz_id}")
        await safe_edit_message_text(query, text="لقد أجبت بالفعل على هذا السؤال أو تم تخطيه.", reply_markup=None)
        return TAKING_QUIZ

    # --- Stop Timer --- 
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        if remove_job_if_exists(timer_job_name, context):
            logger.debug(f"[QUIZ LOGIC] Removed timer job {timer_job_name} for q:{question_index}")
        quiz_data["question_timer_job_name"] = None # Clear job name

    # --- Process Answer --- 
    question = quiz_data["questions"][question_index]
    correct_option_index = question.get("correct_option_index")
    is_correct = (selected_option_index == correct_option_index)

    quiz_data["answers"][question_index] = selected_option_index # Store user's choice
    feedback_text = ""
    if is_correct:
        quiz_data["correct_count"] += 1
        feedback_text = "✅ إجابة صحيحة!"
        logger.info(f"[QUIZ LOGIC] User {user_id} answered q:{question_index} correctly (option {selected_option_index}).")
    else:
        quiz_data["wrong_count"] += 1
        feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة هي الخيار {correct_option_index + 1}."
        logger.info(f"[QUIZ LOGIC] User {user_id} answered q:{question_index} incorrectly (chose {selected_option_index}, correct was {correct_option_index}).")

    # --- Provide Feedback --- 
    try:
        # Edit the original question message to show feedback and remove buttons
        await safe_edit_message_text(query, text=f"{query.message.text or query.message.caption}\n\n{feedback_text}", reply_markup=None, parse_mode="Markdown")
    except BadRequest as e:
         logger.warning(f"[QUIZ LOGIC] BadRequest editing message for feedback (q:{question_index}, user:{user_id}): {e}")
         # Send feedback as a new message if editing fails
         await safe_send_message(context.bot, chat_id, text=feedback_text)
    except Exception as e:
         logger.error(f"[QUIZ LOGIC] Unexpected error editing message for feedback (q:{question_index}, user:{user_id}): {e}")
         await safe_send_message(context.bot, chat_id, text=feedback_text)

    # --- Move to Next Question or End Quiz --- 
    next_question_index = question_index + 1
    if next_question_index < quiz_data["total_questions"]:
        # Wait briefly before sending the next question
        if FEEDBACK_DELAY > 0:
            time.sleep(FEEDBACK_DELAY)
        await send_question(context.bot, chat_id, user_id, quiz_id, next_question_index, context)
        return TAKING_QUIZ
    else:
        # Quiz finished
        logger.info(f"[QUIZ LOGIC] Quiz {quiz_id} finished for user {user_id}.")
        quiz_data["finished"] = True
        return await show_results(context.bot, chat_id, user_id, quiz_id, context)

async def skip_question_callback(bot_or_query, chat_id: int, user_id: int, quiz_id: str, question_index: int, context: CallbackContext, timed_out: bool = False):
    """Handles skipping a question, either by user action or timer.
       Can be called directly (timer) or via CallbackQueryHandler.
    """
    is_callback = isinstance(bot_or_query, Update) or isinstance(bot_or_query, CallbackContext) # Check if called from handler
    query = None
    bot = None
    if is_callback:
        # Called from CallbackQueryHandler
        update = bot_or_query # Rename for clarity
        query = update.callback_query
        await query.answer()
        bot = context.bot
        # Parse data if called via callback
        try:
            _, parsed_quiz_id, _, parsed_q_index_str = query.data.split("_")
            quiz_id = parsed_quiz_id
            question_index = int(parsed_q_index_str)
        except (ValueError, IndexError) as e:
            logger.error(f"[QUIZ SKIP] Invalid callback data format: {query.data}. Error: {e}")
            await safe_edit_message_text(query, text="حدث خطأ في معالجة طلب التخطي.")
            return TAKING_QUIZ
    else:
        # Called directly (e.g., from timer)
        bot = bot_or_query # First argument is the bot object

    # --- Validate Quiz State --- 
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ SKIP] Skip called for inactive/mismatched quiz {quiz_id} user {user_id}")
        if query: await safe_edit_message_text(query, text="هذا الاختبار لم يعد نشطاً.", reply_markup=None)
        return TAKING_QUIZ
    if question_index != quiz_data.get("current_question_index"):
        logger.warning(f"[QUIZ SKIP] Skip called for non-current question (q:{question_index}, current:{quiz_data.get('current_question_index')}) quiz {quiz_id}")
        if query: await safe_edit_message_text(query, text="لا يمكنك تخطي هذا السؤال الآن.", reply_markup=None)
        return TAKING_QUIZ

    # --- Stop Timer --- 
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        if remove_job_if_exists(timer_job_name, context):
            logger.debug(f"[QUIZ SKIP] Removed timer job {timer_job_name} for q:{question_index}")
        quiz_data["question_timer_job_name"] = None

    # --- Process Skip --- 
    quiz_data["answers"][question_index] = -1 # Mark as skipped
    quiz_data["skipped_count"] += 1
    skip_reason = "تخطيت" if not timed_out else "انتهى وقت"
    logger.info(f"[QUIZ LOGIC] User {user_id} skipped q:{question_index} (reason: {'timeout' if timed_out else 'user'}).")

    feedback_text = f"↩️ تم تخطي السؤال {question_index + 1}."
    if timed_out:
        # Feedback already sent by timer callback, just edit message if possible
        last_msg_id = quiz_data.get("last_question_message_id")
        if last_msg_id:
            try:
                # Fetch the message object to get its text/caption
                message = await bot.edit_message_reply_markup(chat_id=chat_id, message_id=last_msg_id, reply_markup=None)
                # Can't easily append text here without knowing original text/caption
                # Just removing the keyboard might be sufficient
                logger.debug(f"[QUIZ SKIP] Removed keyboard from message {last_msg_id} after timeout.")
            except Exception as e:
                logger.warning(f"[QUIZ SKIP] Error removing keyboard after timeout skip: {e}")
    else:
        # User initiated skip, edit message with feedback
        if query:
            try:
                # Determine original text/caption
                original_content = query.message.text or query.message.caption
                if original_content:
                    await safe_edit_message_text(query, text=f"{original_content}\n\n{feedback_text}", reply_markup=None, parse_mode="Markdown")
                else: # If original content is missing, just send feedback
                     await safe_send_message(bot, chat_id, text=feedback_text)
            except BadRequest as e:
                logger.warning(f"[QUIZ SKIP] BadRequest editing message for skip feedback: {e}")
                await safe_send_message(bot, chat_id, text=feedback_text)
            except Exception as e:
                logger.error(f"[QUIZ SKIP] Unexpected error editing message for skip feedback: {e}")
                await safe_send_message(bot, chat_id, text=feedback_text)
        else:
             # Should not happen if user initiated skip
             logger.error("[QUIZ SKIP] User skip processed without a query object!")
             await safe_send_message(bot, chat_id, text=feedback_text)

    # --- Move to Next Question or End Quiz --- 
    next_question_index = question_index + 1
    if next_question_index < quiz_data["total_questions"]:
        if FEEDBACK_DELAY > 0 and not timed_out: # Add delay only if user skipped
            time.sleep(FEEDBACK_DELAY)
        await send_question(bot, chat_id, user_id, quiz_id, next_question_index, context)
        return TAKING_QUIZ
    else:
        logger.info(f"[QUIZ LOGIC] Quiz {quiz_id} finished after skip for user {user_id}.")
        quiz_data["finished"] = True
        return await show_results(bot, chat_id, user_id, quiz_id, context)

async def end_quiz(update_or_bot, chat_id: int, user_id: int, quiz_id: str, context: CallbackContext, error: bool = False):
    """Ends the current quiz prematurely, either by user request or error."""
    is_update = isinstance(update_or_bot, Update)
    bot = context.bot if is_update else update_or_bot
    query = update_or_bot.callback_query if is_update else None

    if query:
        await query.answer()

    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ END] Attempt to end inactive/mismatched quiz {quiz_id} user {user_id}")
        if query: await safe_edit_message_text(query, text="لا يوجد اختبار نشط لإنهاءه.", reply_markup=None)
        # Go to main menu if no active quiz or if called from outside quiz context
        kb = create_main_menu_keyboard(user_id)
        await safe_send_message(bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU 

    # --- Stop Timer --- 
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        remove_job_if_exists(timer_job_name, context)

    quiz_data["finished"] = True
    end_reason = "بسبب خطأ" if error else "بناءً على طلبك"
    logger.info(f"[QUIZ LOGIC] Quiz {quiz_id} ended prematurely for user {user_id} ({end_reason}).")

    # Show partial results if ended by user, otherwise just go to main menu on error
    if not error:
        await safe_send_message(bot, chat_id, text=f"🛑 تم إنهاء الاختبار {end_reason}. عرض النتائج حتى الآن...")
        return await show_results(bot, chat_id, user_id, quiz_id, context)
    else:
        # Error occurred, message already sent by caller
        kb = create_main_menu_keyboard(user_id)
        await safe_send_message(bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

async def show_results(bot, chat_id: int, user_id: int, quiz_id: str, context: CallbackContext) -> int:
    """Calculates and displays the quiz results, saves them, and provides options."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    if not quiz_data or quiz_data.get("quiz_id") != quiz_id:
        logger.error(f"[RESULTS] show_results called for inactive/mismatched quiz {quiz_id} user {user_id}")
        await safe_send_message(bot, chat_id, text="لا يمكن عرض نتائج اختبار غير موجود أو غير متطابق.")
        kb = create_main_menu_keyboard(user_id)
        await safe_send_message(bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    # Ensure quiz is marked finished
    quiz_data["finished"] = True

    # --- Calculate Results --- 
    total_questions = quiz_data["total_questions"]
    correct = quiz_data["correct_count"]
    wrong = quiz_data["wrong_count"]
    skipped = quiz_data["skipped_count"]
    answered = correct + wrong
    # Calculate score only based on answered questions if any were skipped
    score_percentage = (correct / answered * 100) if answered > 0 else 0.0
    # Calculate duration
    end_time = datetime.now()
    start_time = quiz_data.get("start_time", end_time) # Use end_time if start_time missing
    duration_seconds = (end_time - start_time).total_seconds()
    duration_str = time.strftime("%M:%S", time.gmtime(duration_seconds))

    logger.info(f"[RESULTS] Quiz {quiz_id} results for user {user_id}: Correct={correct}, Wrong={wrong}, Skipped={skipped}, Score={score_percentage:.1f}%, Duration={duration_str}")

    # --- Format Results Message --- 
    results_text = f"🎉 *نتائج الاختبار* 🎉\n\n"
    results_text += f"📊 الأسئلة الكلية: {total_questions}\n"
    results_text += f"✅ الإجابات الصحيحة: {correct}\n"
    results_text += f"❌ الإجابات الخاطئة: {wrong}\n"
    results_text += f"↩️ الأسئلة المتخطاة: {skipped}\n"
    results_text += f"⏱️ الوقت المستغرق: {duration_str}\n\n"
    results_text += f"🏆 *النتيجة النهائية: {score_percentage:.1f}%*\n"

    # --- Save Results to Database --- 
    if DB_MANAGER:
        try:
            # Assuming save_quiz_result is async
            await DB_MANAGER.save_quiz_result(
                user_id=user_id,
                quiz_type=quiz_data.get("quiz_type", "unknown"),
                quiz_scope_id=quiz_data.get("quiz_scope_id"),
                score=score_percentage,
                correct_count=correct,
                wrong_count=wrong,
                skipped_count=skipped,
                total_questions=total_questions,
                duration_seconds=int(duration_seconds),
                quiz_timestamp=start_time # Use start time as the timestamp
            )
            logger.info(f"[DB] Successfully saved quiz {quiz_id} results for user {user_id}.")
        except Exception as db_exc:
            logger.error(f"[DB] Failed to save quiz {quiz_id} results for user {user_id}: {db_exc}")
            results_text += "\n\n⚠️ تعذر حفظ نتيجتك في قاعدة البيانات."
    else:
        logger.warning("[DB] DB_MANAGER not available, skipping result saving.")
        results_text += "\n\n⚠️ لم يتم حفظ النتيجة (مشكلة في الاتصال بقاعدة البيانات)."

    # --- Send Results and Options --- 
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧠 اختبار جديد", callback_data="quiz_menu")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ])
    await safe_send_message(bot, chat_id, text=results_text, reply_markup=keyboard, parse_mode="Markdown")

    # --- Clean up quiz data --- 
    context.user_data.pop("current_quiz", None)
    logger.debug(f"[QUIZ LOGIC] Cleaned up quiz data for user {user_id}.")

    return SHOWING_RESULTS # Stay in results state until user chooses next action

