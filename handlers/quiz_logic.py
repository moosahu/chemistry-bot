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
    def safe_send_message(*args, **kwargs): logger.error("Placeholder safe_send_message called!")
    def safe_edit_message_text(*args, **kwargs): logger.error("Placeholder safe_edit_message_text called!")
    def remove_job_if_exists(*args, **kwargs): logger.warning("Placeholder remove_job_if_exists called!"); return False
    def create_main_menu_keyboard(*args, **kwargs): logger.error("Placeholder create_main_menu_keyboard called!"); return None
    def fetch_from_api(*args, **kwargs): logger.error("Placeholder fetch_from_api called!"); return None
    def transform_api_question(q): logger.error("Placeholder transform_api_question called!"); return q # Passthrough
    # Dummy DB_MANAGER
    class DummyDBManager:
        def save_quiz_result(*args, **kwargs): logger.warning("Dummy DB_MANAGER.save_quiz_result called"); return True
    DB_MANAGER = DummyDBManager()

# --- Timer Callback --- 

def question_timer_callback(context: CallbackContext):
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
        safe_send_message(context.bot, chat_id, text=f"⏰ انتهى وقت السؤال {question_index + 1}! سيتم اعتباره متخطى.")

        # Call the skip handler, marking it as timed out
        # Pass the bot object explicitly if needed by handle_quiz_skip
        handle_quiz_skip(context.bot, chat_id, user_id, quiz_id, question_index, context, timed_out=True)
    else:
        logger.info(f"[TIMER] Quiz {quiz_id} ended or question {question_index} already handled, ignoring timer.")

# --- Quiz Core Functions --- 

def start_quiz_logic(update: Update, context: CallbackContext) -> int:
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
        safe_send_message(context.bot, chat_id, text="حدث خطأ أثناء بدء الاختبار (لم يتم تحديد نوع أو عدد الأسئلة). يرجى المحاولة مرة أخرى.")
        # Go back to main menu as quiz setup failed
        kb = create_main_menu_keyboard(user_id)
        safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    quiz_type = quiz_selection["type"] # e.g., "random", "lesson", "unit", "course"
    quiz_scope_id = quiz_selection.get("scope_id") # ID of lesson/unit/course, or None for random
    num_questions = quiz_selection["count"]
    max_available = quiz_selection.get("max_questions", num_questions) # Max questions API reported

    # Validate num_questions
    if not isinstance(num_questions, int) or num_questions <= 0:
        logger.error(f"[QUIZ LOGIC] Invalid number of questions ({num_questions}) for user {user_id}. Aborting quiz start.")
        safe_send_message(context.bot, chat_id, text=f"عدد الأسئلة غير صالح ({num_questions}). يرجى المحاولة مرة أخرى.")
        kb = create_main_menu_keyboard(user_id)
        safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    # Ensure num_questions doesn't exceed max available
    num_questions = min(num_questions, max_available)
    if num_questions <= 0:
         logger.error(f"[QUIZ LOGIC] No questions available ({max_available}) for user {user_id}. Aborting quiz start.")
         safe_send_message(context.bot, chat_id, text="لا توجد أسئلة متاحة لهذا الاختيار. لا يمكن بدء الاختبار.")
         kb = create_main_menu_keyboard(user_id)
         safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
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
    api_questions_response = fetch_from_api(questions_endpoint, params=params)

    # --- Handle API Response --- 
    if api_questions_response == "TIMEOUT":
        logger.error(f"[API] Timeout fetching questions for quiz start (user {user_id}).")
        safe_send_message(context.bot, chat_id, text="⏳ تعذر تحميل أسئلة الاختبار (مهلة الاتصال). يرجى المحاولة مرة أخرى لاحقاً.")
        kb = create_main_menu_keyboard(user_id)
        safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU
    elif not isinstance(api_questions_response, list):
        logger.error(f"[API] Failed to fetch questions or invalid format for quiz start (user {user_id}). Response: {api_questions_response}")
        safe_send_message(context.bot, chat_id, text="⚠️ تعذر تحميل أسئلة الاختبار أو أن التنسيق غير صالح. يرجى المحاولة مرة أخرى لاحقاً.")
        kb = create_main_menu_keyboard(user_id)
        safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
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
        safe_send_message(context.bot, chat_id, text="لم يتم العثور على أسئلة صالحة لهذا الاختبار. يرجى المحاولة مرة أخرى أو اختيار موضوع آخر.")
        kb = create_main_menu_keyboard(user_id)
        safe_send_message(context.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
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
    send_question(context.bot, chat_id, user_id, quiz_id, 0, context)

    return TAKING_QUIZ # Transition to the quiz-taking state

def send_question(bot, chat_id: int, user_id: int, quiz_id: str, question_index: int, context: CallbackContext):
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
    question_text = f"*السؤال {question_index + 1} من {quiz_data["total_questions"]}*

" 
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
            sent_message = bot.send_photo(
                chat_id=chat_id,
                photo=main_image_url,
                caption=question_text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
            logger.debug(f"[QUIZ LOGIC] Sending question {question_index} as text.")
            sent_message = safe_send_message(
                bot,
                chat_id=chat_id,
                text=question_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    except BadRequest as e:
        logger.error(f"[QUIZ LOGIC] BadRequest sending question {question_index} to {chat_id}: {e}")
        # Try sending as plain text if Markdown fails
        if "Can\\'t parse entities" in str(e):
            try:
                plain_text = re.sub(r"[*_`[]()~>#+-=|{}.!]", "\\\\
\1", question_text) # Basic Markdown escape
                if main_image_url:
                     sent_message = bot.send_photo(chat_id=chat_id, photo=main_image_url, caption=plain_text, reply_markup=reply_markup)
                else:
                     sent_message = safe_send_message(bot, chat_id=chat_id, text=plain_text, reply_markup=reply_markup)
            except Exception as fallback_e:
                 logger.error(f"[QUIZ LOGIC] Failed to send question {question_index} even as plain text: {fallback_e}")
                 safe_send_message(bot, chat_id, text="حدث خطأ فادح أثناء إرسال السؤال. سيتم إنهاء الاختبار.")
                 end_quiz(bot, chat_id, user_id, quiz_id, context, error=True)
                 return
        else:
             # Other BadRequest (e.g., invalid image URL)
             safe_send_message(bot, chat_id, text="حدث خطأ أثناء إرسال السؤال (قد يكون بسبب الصورة). سيتم تخطي هذا السؤال.")
             handle_quiz_skip(bot, chat_id, user_id, quiz_id, question_index, context, error=True)
             return
    except Exception as e:
        logger.exception(f"[QUIZ LOGIC] Unexpected error sending question {question_index} to {chat_id}: {e}")
        safe_send_message(bot, chat_id, text="حدث خطأ غير متوقع أثناء إرسال السؤال. سيتم تخطي هذا السؤال.")
        handle_quiz_skip(bot, chat_id, user_id, quiz_id, question_index, context, error=True)
        return

    # --- Store Message ID and Set Timer --- 
    if sent_message:
        quiz_data["last_question_message_id"] = sent_message.message_id
        logger.debug(f"[QUIZ LOGIC] Question {question_index} sent (msg_id: {sent_message.message_id}).")

        if ENABLE_QUESTION_TIMER and QUESTION_TIMER_SECONDS > 0:
            job_name = f"qtimer_{chat_id}_{user_id}_{quiz_id}_{question_index}" # Unique job name
            remove_job_if_exists(job_name, context) # Remove previous timer just in case
            timer_job = context.job_queue.run_once(
                question_timer_callback,
                QUESTION_TIMER_SECONDS,
                context={"chat_id": chat_id, "user_id": user_id, "quiz_id": quiz_id, "question_index": question_index},
                name=job_name
            )
            if timer_job:
                quiz_data["question_timer_job_name"] = job_name
                logger.info(f"[TIMER] Set question timer ({QUESTION_TIMER_SECONDS}s) for q:{question_index} quiz:{quiz_id}. Job: {job_name}")
            else:
                 logger.error(f"[TIMER] Failed to set question timer job for q:{question_index} quiz:{quiz_id}")
                 quiz_data["question_timer_job_name"] = None
    else:
        logger.error(f"[QUIZ LOGIC] Failed to send question {question_index} and get message ID.")
        safe_send_message(bot, chat_id, text="فشل إرسال السؤال. سيتم تخطيه.")
        handle_quiz_skip(bot, chat_id, user_id, quiz_id, question_index, context, error=True)

def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    """Handles user's answer selection via callback query.
       Returns the next state (TAKING_QUIZ or SHOWING_RESULTS).
    """
    query = update.callback_query
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id
    query.answer() # Acknowledge callback

    # --- Parse Callback Data --- 
    match = re.match(r"quiz_([^_]+)_ans_(" + r"\d+)_(" + r"\d+)", query.data)
    if not match:
        logger.warning(f"[QUIZ LOGIC] Invalid answer callback data: {query.data}")
        return TAKING_QUIZ # Ignore invalid callback

    quiz_id = match.group(1)
    question_index = int(match.group(2))
    selected_answer_index = int(match.group(3))

    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    # --- Validations --- 
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ LOGIC] Answer received for inactive/mismatched quiz {quiz_id} from user {user_id}")
        safe_edit_message_text(query, text="هذا الاختبار لم يعد نشطاً.", reply_markup=None)
        return TAKING_QUIZ # Stay in state, but message indicates issue

    if question_index != quiz_data.get("current_question_index"):
        logger.warning(f"[QUIZ LOGIC] Answer received for non-current question (q:{question_index}, current:{quiz_data.get("current_question_index")}) quiz:{quiz_id} user:{user_id}")
        safe_send_message(context.bot, chat_id, text="لقد أجبت على سؤال سابق. لا يمكن تغيير الإجابة.")
        return TAKING_QUIZ

    if quiz_data["answers"][question_index] is not None:
        logger.warning(f"[QUIZ LOGIC] Question {question_index} already answered for quiz {quiz_id} user {user_id}. Ignoring.")
        safe_send_message(context.bot, chat_id, text="لقد أجبت على هذا السؤال بالفعل.")
        return TAKING_QUIZ

    # --- Process Answer --- 
    logger.info(f"[QUIZ LOGIC] User {user_id} answered q:{question_index} with opt:{selected_answer_index} for quiz:{quiz_id}")

    # Remove question timer
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        remove_job_if_exists(timer_job_name, context)
        quiz_data["question_timer_job_name"] = None

    question = quiz_data["questions"][question_index]
    correct_answer_index = question["correct_answer"] # This is the 0-based index from API/transform
    is_correct = (selected_answer_index == correct_answer_index)

    quiz_data["answers"][question_index] = selected_answer_index # Store user's choice index

    # --- Provide Feedback --- 
    feedback_text = ""
    if is_correct:
        quiz_data["correct_count"] += 1
        feedback_text = "✅ إجابة صحيحة!"
    else:
        quiz_data["wrong_count"] += 1
        feedback_text = f"❌ إجابة خاطئة." 
        # Provide correct answer text/image indication
        correct_option_text = question.get(f"option{correct_answer_index + 1}")
        correct_option_image = question.get(f"option{correct_answer_index + 1}_image")
        if correct_option_text:
             feedback_text += f" الإجابة الصحيحة: {correct_option_text}"
        elif correct_option_image:
             feedback_text += f" (الإجابة الصحيحة كانت خيار صورة)"
        else:
             # Fallback if correct option index is somehow invalid (shouldn't happen)
             feedback_text += f" (الإجابة الصحيحة: الخيار {correct_answer_index + 1})"
        
        # Add explanation if available
        if question.get("explanation"):
            feedback_text += f"\n\n*توضيح:* {question["explanation"]}"

    # Edit the original question message to show feedback and remove buttons
    original_message_id = quiz_data.get("last_question_message_id")
    if original_message_id:
        try:
            # Get the original caption/text to append feedback
            original_caption = query.message.caption # Might be None
            original_text_body = query.message.text # Might be None
            
            # Construct the base text (question text without the header)
            base_text = ""
            if original_caption:
                base_text = re.sub(r"^\*السؤال \d+ من \d+\*\n\n", "", original_caption, 1)
            elif original_text_body:
                base_text = re.sub(r"^\*السؤال \d+ من \d+\*\n\n", "", original_text_body, 1)
            
            # Combine base text and feedback
            new_content = f"{base_text}\n\n---\n*{feedback_text}*"
            
            if query.message.photo:
                context.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=original_message_id,
                    caption=new_content,
                    parse_mode="Markdown",
                    reply_markup=None # Remove keyboard
                )
            else:
                # Use safe_edit_message_text with bot, chat_id, message_id
                safe_edit_message_text(
                     context.bot,
                     text=new_content,
                     chat_id=chat_id,
                     message_id=original_message_id,
                     parse_mode="Markdown",
                     reply_markup=None # Remove keyboard
                 )
            logger.debug(f"[QUIZ LOGIC] Edited message {original_message_id} with feedback for q:{question_index}")
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.info(f"[QUIZ LOGIC] Feedback message for q:{question_index} not modified.")
            elif "message can\'t be edited" in str(e):
                 logger.warning(f"[QUIZ LOGIC] Message for q:{question_index} cannot be edited (likely too old). Sending feedback as new message.")
                 safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode="Markdown")
            else:
                logger.error(f"[QUIZ LOGIC] Error editing message for feedback q:{question_index}: {e}")
                safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode="Markdown") # Fallback
        except Exception as e:
            logger.exception(f"[QUIZ LOGIC] Unexpected error providing feedback for q:{question_index}: {e}")
            safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode="Markdown") # Fallback
    else:
        logger.warning(f"[QUIZ LOGIC] last_question_message_id missing for q:{question_index}. Sending feedback as new message.")
        safe_send_message(context.bot, chat_id, text=feedback_text, parse_mode="Markdown")

    # --- Proceed to Next Question or Show Results --- 
    next_question_index = question_index + 1
    if next_question_index < quiz_data["total_questions"]:
        # Schedule sending the next question after a delay
        context.job_queue.run_once(
            lambda ctx: send_question(ctx.bot, chat_id, user_id, quiz_id, next_question_index, ctx),
            FEEDBACK_DELAY,
            context=context # Pass the whole context
        )
        logger.debug(f"[QUIZ LOGIC] Scheduled next question ({next_question_index}) after {FEEDBACK_DELAY}s delay.")
        return TAKING_QUIZ # Stay in taking quiz state
    else:
        # Quiz finished
        logger.info(f"[QUIZ LOGIC] Quiz {quiz_id} finished for user {user_id}. Correct: {quiz_data['correct_count']}, Wrong: {quiz_data['wrong_count']}, Skipped: {quiz_data['skipped_count']}")
        quiz_data["finished"] = True
        # Schedule showing results after a delay
        context.job_queue.run_once(
            lambda ctx: show_results(ctx.bot, chat_id, user_id, quiz_id, ctx),
            FEEDBACK_DELAY,
            context=context
        )
        logger.debug(f"[QUIZ LOGIC] Scheduled showing results after {FEEDBACK_DELAY}s delay.")
        return SHOWING_RESULTS # Transition state

def handle_quiz_skip(bot, chat_id: int, user_id: int, quiz_id: str, question_index: int, context: CallbackContext, timed_out: bool = False, error: bool = False):
    """Handles skipping a question (by user, timeout, or error). Does NOT return state."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    # --- Validations --- 
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ LOGIC] Skip called for inactive/mismatched quiz {quiz_id} user {user_id}")
        return

    # Check if already processed (e.g., answered just before timeout/skip)
    if quiz_data["answers"][question_index] is not None:
        logger.info(f"[QUIZ LOGIC] Question {question_index} already answered/skipped for quiz {quiz_id}. Ignoring skip action.")
        return

    logger.info(f"[QUIZ LOGIC] Skipping q:{question_index} for quiz:{quiz_id} user:{user_id} (TimedOut: {timed_out}, Error: {error})")

    # Remove question timer if it's still running (e.g., user skipped manually)
    timer_job_name = quiz_data.get("question_timer_job_name")
    if not timed_out and timer_job_name:
        remove_job_if_exists(timer_job_name, context)
        quiz_data["question_timer_job_name"] = None

    quiz_data["answers"][question_index] = -1 # Mark as skipped
    quiz_data["skipped_count"] += 1

    # --- Provide Feedback (Optional for skip) --- 
    # Edit the message to indicate skip, unless it was a timeout/error where message was already sent
    original_message_id = quiz_data.get("last_question_message_id")
    if not timed_out and not error and original_message_id:
        try:
            skip_feedback = f"تم تخطي السؤال {question_index + 1}."
            # Try to edit the original message - might be complex to get original text/caption here
            # Fallback: Send a new message and try removing keyboard from old one
            safe_send_message(bot, chat_id, text=skip_feedback)
            try:
                # Try removing keyboard from the question message
                bot.edit_message_reply_markup(chat_id=chat_id, message_id=original_message_id, reply_markup=None)
            except Exception as edit_e:
                logger.warning(f"[QUIZ LOGIC] Could not remove keyboard from skipped q:{question_index}: {edit_e}")
        except Exception as e:
            logger.error(f"[QUIZ LOGIC] Error providing skip feedback for q:{question_index}: {e}")
            # Ensure feedback is sent even if editing fails
            safe_send_message(bot, chat_id, text=f"تم تخطي السؤال {question_index + 1}.")
    elif not timed_out and not error: # If skip but no original message ID
         safe_send_message(bot, chat_id, text=f"تم تخطي السؤال {question_index + 1}.")

    # --- Proceed to Next Question or Show Results --- 
    next_question_index = question_index + 1
    if next_question_index < quiz_data["total_questions"]:
        # Schedule sending the next question (short delay after skip/timeout)
        context.job_queue.run_once(
            lambda ctx: send_question(ctx.bot, chat_id, user_id, quiz_id, next_question_index, ctx),
            0.5, # Short delay
            context=context
        )
        logger.debug(f"[QUIZ LOGIC] Scheduled next question ({next_question_index}) after skip/timeout.")
    else:
        # Quiz finished
        logger.info(f"[QUIZ LOGIC] Quiz {quiz_id} finished after skip/timeout on last question. User {user_id}. Correct: {quiz_data['correct_count']}, Wrong: {quiz_data['wrong_count']}, Skipped: {quiz_data['skipped_count']}")
        quiz_data["finished"] = True
        # Schedule showing results
        context.job_queue.run_once(
            lambda ctx: show_results(ctx.bot, chat_id, user_id, quiz_id, ctx),
            0.5, # Short delay
            context=context
        )
        logger.debug(f"[QUIZ LOGIC] Scheduled showing results after skip/timeout on last question.")
        # State transition happens when show_results is called

def skip_question_callback(update: Update, context: CallbackContext) -> int:
    """Handles the user pressing the 'Skip' button via callback query.
       Returns the next state (TAKING_QUIZ or SHOWING_RESULTS).
    """
    query = update.callback_query
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id
    query.answer("سيتم تخطي السؤال...") # Quick feedback

    # --- Parse Callback Data --- 
    match = re.match(r"quiz_([^_]+)_skip_(" + r"\d+)", query.data)
    if not match:
        logger.warning(f"[QUIZ LOGIC] Invalid skip callback data: {query.data}")
        return TAKING_QUIZ

    quiz_id = match.group(1)
    question_index = int(match.group(2))

    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    # --- Validations --- 
    if not quiz_data or quiz_data.get("quiz_id") != quiz_id or quiz_data.get("finished"):
        logger.warning(f"[QUIZ LOGIC] Skip received for inactive/mismatched quiz {quiz_id} from user {user_id}")
        safe_edit_message_text(query, text="هذا الاختبار لم يعد نشطاً.", reply_markup=None)
        return TAKING_QUIZ

    if question_index != quiz_data.get("current_question_index"):
        logger.warning(f"[QUIZ LOGIC] Skip received for non-current question (q:{question_index}, current:{quiz_data.get("current_question_index")}) quiz:{quiz_id} user:{user_id}")
        safe_send_message(context.bot, chat_id, text="لقد ضغطت على زر التخطي لسؤال سابق.")
        return TAKING_QUIZ

    # --- Call Shared Skip Logic --- 
    handle_quiz_skip(context.bot, chat_id, user_id, quiz_id, question_index, context, timed_out=False)

    # --- Determine Next State --- 
    # Check if the quiz finished *after* the skip was processed
    if quiz_data.get("finished"):
        return SHOWING_RESULTS
    else:
        return TAKING_QUIZ

def show_results(bot, chat_id: int, user_id: int, quiz_id: str, context: CallbackContext, timed_out: bool = False, error: bool = False):
    """Calculates, saves, and displays the quiz results. Returns MAIN_MENU state."""
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    if not quiz_data or quiz_data.get("quiz_id") != quiz_id:
        logger.warning(f"[QUIZ LOGIC] show_results called for inactive/mismatched quiz {quiz_id} user {user_id}")
        safe_send_message(bot, chat_id, text="حدث خطأ أثناء عرض النتائج (بيانات الاختبار غير موجودة).")
        if "current_quiz" in user_data: del user_data["current_quiz"]
        kb = create_main_menu_keyboard(user_id)
        safe_send_message(bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    # Ensure quiz is marked as finished if not already
    quiz_data["finished"] = True
    end_time = datetime.now()

    # --- Calculate Score --- 
    total = quiz_data["total_questions"]
    correct = quiz_data["correct_count"]
    wrong = quiz_data["wrong_count"]
    skipped = quiz_data["skipped_count"]

    # Sanity check counts
    calculated_skipped = total - correct - wrong
    if calculated_skipped != skipped:
        logger.warning(f"[QUIZ LOGIC] Result counts mismatch for quiz {quiz_id}: C:{correct}, W:{wrong}, S:{skipped}, Total:{total}. Adjusting skipped to {calculated_skipped}.")
        skipped = calculated_skipped
        quiz_data["skipped_count"] = skipped # Update data

    score_percentage = (correct / total * 100) if total > 0 else 0
    start_time = quiz_data.get("start_time", end_time) # Use end_time as fallback

    # --- Prepare Result Message --- 
    result_text = "🏁 *نتائج الاختبار* 🏁\n\n"
    if timed_out:
        result_text = "⏰ *انتهى وقت الاختبار!* ⏰\n\n"
    elif error:
         result_text = "⚠️ *انتهى الاختبار بسبب خطأ* ⚠️\n\n"

    result_text += f"🔢 إجمالي الأسئلة: {total}\n"
    result_text += f"✅ الإجابات الصحيحة: {correct}\n"
    result_text += f"❌ الإجابات الخاطئة: {wrong}\n"
    result_text += f"⏭️ الأسئلة المتخطاة/الوقت المنتهي: {skipped}\n"
    result_text += f"💯 *النتيجة النهائية: {score_percentage:.1f}%*\n\n"

    # Add encouragement
    if score_percentage >= 90:
        result_text += "🎉 ممتاز! أداء رائع!"
    elif score_percentage >= 70:
        result_text += "👍 جيد جداً! استمر في التقدم!"
    elif score_percentage >= 50:
        result_text += "🙂 لا بأس، يمكنك التحسن في المرة القادمة!"
    else:
        result_text += "💪 لا تستسلم! المعرفة تأتي بالممارسة."

    # --- Save Results to Database --- 
    if DB_MANAGER:
        try:
            # Prepare details for JSONB storage
            details_to_save = {
                "question_ids": [q.get("question_id") for q in quiz_data.get("questions", [])],
                "answers": quiz_data.get("answers"), # List of selected indices or -1
                # Add more details if needed, e.g., timestamps per question
            }
            logger.debug(f"[DB Results] Saving quiz results for user {user_id}, quiz {quiz_id}")
            success = DB_MANAGER.save_quiz_result(
                user_id=user_id,
                quiz_type=quiz_data.get("quiz_type", "unknown"),
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
            if success:
                logger.info(f"[DB Results] Successfully saved results for quiz {quiz_id}")
            else:
                logger.error(f"[DB Results] Failed to save results for quiz {quiz_id}")
        except Exception as e:
            logger.exception(f"[DB Results] Error saving quiz results for quiz {quiz_id}: {e}")
    else:
        logger.warning("[DB Results] DB_MANAGER not available, skipping saving quiz results.")

    # --- Send Results and Clean Up --- 
    keyboard = create_main_menu_keyboard(user_id)
    safe_send_message(bot, chat_id, text=result_text, reply_markup=keyboard, parse_mode="Markdown")

    # Clean up quiz data from user_data
    if "current_quiz" in user_data:
        del user_data["current_quiz"]
        logger.debug(f"[QUIZ LOGIC] Cleaned up quiz data for user {user_id}.")
    if "quiz_selection" in user_data:
         del user_data["quiz_selection"] # Clean up selection too
         logger.debug(f"[QUIZ LOGIC] Cleaned up quiz selection for user {user_id}.")

    return MAIN_MENU # Return to main menu state

def end_quiz(bot, chat_id: int, user_id: int, quiz_id: str, context: CallbackContext, timed_out: bool = False, error: bool = False):
    """Forcefully ends the quiz (e.g., due to error) and shows results. Returns MAIN_MENU state."""
    logger.info(f"[QUIZ LOGIC] Force ending quiz {quiz_id} for user {user_id}. TimedOut: {timed_out}, Error: {error}")
    user_data = context.user_data
    quiz_data = user_data.get("current_quiz")

    if not quiz_data or quiz_data.get("quiz_id") != quiz_id:
        logger.warning(f"[QUIZ LOGIC] end_quiz called for inactive/mismatched quiz {quiz_id}")
        if "current_quiz" in user_data: del user_data["current_quiz"]
        if "quiz_selection" in user_data: del user_data["quiz_selection"]
        kb = create_main_menu_keyboard(user_id)
        safe_send_message(bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

    # Mark remaining questions as skipped if not already finished
    if not quiz_data.get("finished"):
        current_index = quiz_data.get("current_question_index", 0)
        total_questions = quiz_data.get("total_questions", 0)
        for i in range(current_index, total_questions):
            if quiz_data["answers"][i] is None:
                quiz_data["answers"][i] = -1 # Mark as skipped
                quiz_data["skipped_count"] += 1
        quiz_data["finished"] = True

    # Remove any active timers
    timer_job_name = quiz_data.get("question_timer_job_name")
    if timer_job_name:
        remove_job_if_exists(timer_job_name, context)

    # Show results
    return show_results(bot, chat_id, user_id, quiz_id, context, timed_out=timed_out, error=error)

