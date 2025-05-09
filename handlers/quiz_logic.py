"""Manages the logic for conducting a quiz, including sending questions, handling answers, and calculating results."""
# handlers/quiz_logic.py (DBMANAGER_PASS_FIX & INDENT_FIX)

import asyncio
import logging
import time
import uuid # Not strictly needed if quiz_instance_id_for_logging is always provided
import telegram # For telegram.error types
from datetime import datetime, timezone # Ensure timezone is imported
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot 
from telegram.ext import ConversationHandler, CallbackContext, JobQueue 
from config import logger, TAKING_QUIZ, END, MAIN_MENU, SHOWING_RESULTS # SHOWING_RESULTS needed for return states
from utils.helpers import safe_send_message, safe_edit_message_text, remove_job_if_exists
# Removed: from database.data_logger import log_quiz_results # DB ops now via self.db_manager

MIN_OPTIONS_PER_QUESTION = 2

class QuizLogic:
    ARABIC_CHOICE_LETTERS = ["أ", "ب", "ج", "د"]

    def __init__(self, user_id, chat_id, questions, quiz_name,
                 quiz_type_for_db_log, quiz_scope_id, total_questions_for_db_log,
                 time_limit_per_question, quiz_instance_id_for_logging, # This will be self.quiz_id
                 db_manager_instance):
        
        self.user_id = user_id
        self.chat_id = chat_id
        self.questions_data = questions if questions is not None else []
        self.quiz_name = quiz_name if quiz_name else "اختبار غير مسمى"
        
        # Parameters for DB logging, passed from quiz.py
        self.quiz_type_for_db = quiz_type_for_db_log
        self.quiz_scope_id_for_db = quiz_scope_id 
        self.total_questions_for_db = total_questions_for_db_log

        self.question_time_limit = time_limit_per_question
        self.quiz_id = quiz_instance_id_for_logging # Use this as the main identifier for logging within QuizLogic
        
        self.db_manager = db_manager_instance # Store the passed DB Manager instance
        
        # Internal state variables
        self.current_question_index = 0
        self.score = 0
        self.answers = [] 
        self.question_start_time = None
        self.quiz_actual_start_time_dt = None # datetime object for quiz start
        self.last_question_message_id = None
        self.last_question_is_image = False
        self.active = False # Will be set to True in start_quiz
        self.db_quiz_session_id = None # Stores the UUID from DB after logging quiz start

        if not self.db_manager:
            logger.critical(f"[QuizLogic {self.quiz_id}] CRITICAL: db_manager_instance was None at __init__! Database operations will fail.")
        
        # Calculate actual total questions from the provided list for internal quiz flow
        self.total_questions = len(self.questions_data)
        if self.total_questions != self.total_questions_for_db:
             logger.warning(f"[QuizLogic {self.quiz_id}] Mismatch: total_questions_for_db ({self.total_questions_for_db}) vs actual len(questions_data) ({self.total_questions}). Using actual len for quiz flow, but total_questions_for_db for initial DB log.")

        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized. User: {self.user_id}, Chat: {self.chat_id}, QuizName: '{self.quiz_name}', DBQuizType: {self.quiz_type_for_db}, DBScopeID: {self.quiz_scope_id_for_db}, NumQsForDB: {self.total_questions_for_db}, ActualNumQs: {self.total_questions}. DB Manager Present: {bool(self.db_manager)}")

    async def start_quiz(self, bot: Bot, context: CallbackContext, update: Update) -> int: # user_id param removed, use self.user_id
        logger.info(f"[QuizLogic {self.quiz_id}] start_quiz called for user {self.user_id}, chat {self.chat_id}")
        self.active = True 
        self.quiz_actual_start_time_dt = datetime.now(timezone.utc) # Use timezone.utc for consistency
        
        # Ensure self.total_questions is based on the actual data for the quiz flow
        self.total_questions = len(self.questions_data)

        # Log quiz start to DB using self.db_manager
        if self.db_manager:
            try:
                self.db_quiz_session_id = self.db_manager.start_quiz_session_and_get_id(
                    user_id=self.user_id,
                    quiz_type=self.quiz_type_for_db, 
                    quiz_scope_id=self.quiz_scope_id_for_db,
                    quiz_name=self.quiz_name,
                    total_questions=self.total_questions_for_db, # Use the count intended for DB logging
                    start_time=self.quiz_actual_start_time_dt 
                )
                if self.db_quiz_session_id:
                    logger.info(f"[QuizLogic {self.quiz_id}] Quiz session started and logged to DB with session_uuid: {self.db_quiz_session_id}")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to log quiz start to DB (db_manager.start_quiz_session_and_get_id returned None). Quiz stats might be incomplete.")
            except Exception as e:
                logger.error(f"[QuizLogic {self.quiz_id}] Exception while logging quiz start to DB: {e}", exc_info=True)
                self.db_quiz_session_id = None # Ensure it's None on failure
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] db_manager is not available. Cannot log quiz start to DB.")
            self.db_quiz_session_id = None

        if not self.questions_data or self.total_questions == 0:
            logger.warning(f"[QuizLogic {self.quiz_id}] No questions available. Ending quiz.")
            message_to_edit_id = None
            if update and update.callback_query and update.callback_query.message:
                message_to_edit_id = update.callback_query.message.message_id
            
            text_no_questions = "عذراً، لا توجد أسئلة لبدء هذا الاختبار. يرجى المحاولة مرة أخرى."
            keyboard_to_main = InlineKeyboardMarkup([[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]])
            if message_to_edit_id:
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_to_edit_id, text=text_no_questions, reply_markup=keyboard_to_main)
            else:
                await safe_send_message(bot, chat_id=self.chat_id, text=text_no_questions, reply_markup=keyboard_to_main)
            await self.cleanup_quiz_data(context, self.user_id, "no_questions_on_start") 
            return END 
        
        return await self.send_question(bot, context)
    
    def create_options_keyboard(self, options_data):
        keyboard = []
        for i, option in enumerate(options_data):
            option_id = option.get("option_id", f"gen_opt_{i}") 
            option_text_original = option.get("option_text", "")
            button_text = ""

            if option.get("is_image_option"):
                image_display_char = option.get("image_option_display_label")
                if not image_display_char: 
                    logger.warning(f"[QuizLogic {self.quiz_id}] Image option missing display label. Opt: {option_id}. Fallback to index.")
                    button_text = f"اختر صورة {i + 1}" 
                else:
                    button_text = f"الخيار المصور: {image_display_char}" 
            elif isinstance(option_text_original, str) and not option_text_original.strip():
                button_text = f"خيار {i + 1}" 
            elif isinstance(option_text_original, str) and (option_text_original.startswith("http://") or option_text_original.startswith("https://") ):
                logger.warning(f"[QuizLogic {self.quiz_id}] URL-like text not marked as image in create_options_keyboard: {option_text_original[:50]}")
                button_text = f"خيار {i + 1} (رابط)"
            elif isinstance(option_text_original, str):
                button_text = option_text_original
            else: 
                button_text = f"خيار {i + 1} (بيانات غير نصية)"
            
            button_text_str = str(button_text).strip()
            if not button_text_str: 
                 button_text_str = f"خيار {i + 1}" 
            
            if len(button_text_str.encode('utf-8')) > 60: 
                temp_bytes = button_text_str.encode('utf-8')[:57] 
                button_text_str = temp_bytes.decode('utf-8', 'ignore') + "..."

            callback_data = f"ans_{self.quiz_id}_{self.current_question_index}_{option_id}"
            keyboard.append([InlineKeyboardButton(text=button_text_str, callback_data=callback_data)])
        return InlineKeyboardMarkup(keyboard)

    async def send_question(self, bot: Bot, context: CallbackContext):
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] send_question: inactive. User {self.user_id}. Aborting.")
            return END 

        # self.total_questions is already set based on len(self.questions_data)

        while self.current_question_index < self.total_questions:
            current_question_data = self.questions_data[self.current_question_index]
            q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
            options = current_question_data.get("options", [])

            if len(options) < MIN_OPTIONS_PER_QUESTION:
                logger.warning(f"[QuizLogic {self.quiz_id}] Question {q_id_log} (idx {self.current_question_index}) has only {len(options)} options (min: {MIN_OPTIONS_PER_QUESTION}). Skipping.")
                self.answers.append({
                    "question_id": q_id_log,
                    "question_text": current_question_data.get("question_text", "سؤال غير صالح (خيارات قليلة)"),
                    "chosen_option_id": None,
                    "chosen_option_text": "تم تخطي السؤال (خيارات غير كافية)",
                    "correct_option_id": None, # Attempt to get it if available
                    "correct_option_text": self._get_correct_option_text_robust(current_question_data, for_skip=True),
                    "is_correct": False,
                    "time_taken": -998, 
                    "status": "skipped_auto" # ADDED status
                })
                self.current_question_index += 1
                continue 
            
            processed_options = []
            option_image_counter = 0 

            for i, option_data_original in enumerate(options):
                current_option_proc = option_data_original.copy()
                option_text_original = option_data_original.get("option_text", "")
                is_image_url = isinstance(option_text_original, str) and \
                               (option_text_original.startswith("http://")  or option_text_original.startswith("https://") ) and \
                               any(option_text_original.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif"])

                if is_image_url:
                    try:
                        display_label = self.ARABIC_CHOICE_LETTERS[option_image_counter] if option_image_counter < len(self.ARABIC_CHOICE_LETTERS) else f"صورة {option_image_counter + 1}"
                        logger.info(f"[QuizLogic {self.quiz_id}] Sending image option {i} (caption: {display_label}), q_id {q_id_log}. URL: {option_text_original}")
                        await bot.send_photo(chat_id=self.chat_id, photo=option_text_original, caption=f"الخيار: {display_label}")
                        current_option_proc['is_image_option'] = True
                        current_option_proc['image_option_display_label'] = display_label 
                        option_image_counter += 1 
                        await asyncio.sleep(0.3) 
                    except Exception as e_img_opt:
                        logger.error(f"[QuizLogic {self.quiz_id}] Failed to send image option {i} (URL: {option_text_original}), q_id {q_id_log}: {e_img_opt}", exc_info=True)
                        current_option_proc['is_image_option'] = False
                        current_option_proc['image_option_display_label'] = None 
                else:
                    current_option_proc['is_image_option'] = False 
                    current_option_proc['image_option_display_label'] = None
                processed_options.append(current_option_proc)
            
            current_question_data['options'] = processed_options 
            options_keyboard = self.create_options_keyboard(processed_options)
            header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
            image_url = current_question_data.get("image_url")
            question_text_from_data = current_question_data.get("question_text")

            if question_text_from_data is None:
                question_text_from_data = ""
            if not isinstance(question_text_from_data, str):
                 question_text_from_data = str(question_text_from_data)
            question_text_from_data = question_text_from_data.strip()

            if not question_text_from_data and image_url:
                question_text_display = "السؤال معروض في الصورة أعلاه."
            elif not question_text_from_data and not image_url:
                question_text_display = "نص السؤال غير متوفر حالياً."
            else:
                question_text_display = question_text_from_data
            
            sent_message = None
            self.last_question_is_image = False # Reset before sending new question

            if image_url:
                caption_text = header + question_text_display
                try:
                    sent_message = await bot.send_photo(chat_id=self.chat_id, photo=image_url, caption=caption_text, reply_markup=options_keyboard, parse_mode="HTML")
                    self.last_question_is_image = True
                except Exception as e:
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to send photo q_id {q_id_log}: {e}. URL: {image_url}", exc_info=True)
                    full_question_text = header + question_text_display + "\n(تعذر تحميل صورة السؤال)"
                    try:
                        sent_message = await safe_send_message(bot, chat_id=self.chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                    except Exception as e_fallback_text:
                        logger.error(f"[QuizLogic {self.quiz_id}] Fallback text failed q_id {q_id_log}: {e_fallback_text}", exc_info=True)
                        # If fallback also fails, we might have a bigger issue, but we'll try to skip the question
                        self.answers.append({
                            "question_id": q_id_log,
                            "question_text": question_text_display,
                            "chosen_option_id": None,
                            "chosen_option_text": "خطأ في إرسال السؤال",
                            "correct_option_id": None,
                            "correct_option_text": self._get_correct_option_text_robust(current_question_data, for_skip=True),
                            "is_correct": False,
                            "time_taken": -997, # Error sending question
                            "status": "error_sending"
                        })
                        self.current_question_index += 1
                        await asyncio.sleep(0.1) # Brief pause before next attempt or ending
                        continue # Try next question or end
            else:
                full_question_text = header + question_text_display
                try:
                    sent_message = await safe_send_message(bot, chat_id=self.chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                except Exception as e:
                     logger.error(f"[QuizLogic {self.quiz_id}] Error sending text question q_id {q_id_log}: {e}.", exc_info=True)
                     self.answers.append({
                        "question_id": q_id_log,
                        "question_text": question_text_display,
                        "chosen_option_id": None,
                        "chosen_option_text": "خطأ في إرسال السؤال",
                        "correct_option_id": None,
                        "correct_option_text": self._get_correct_option_text_robust(current_question_data, for_skip=True),
                        "is_correct": False,
                        "time_taken": -997, # Error sending question
                        "status": "error_sending"
                    })
                     self.current_question_index += 1
                     await asyncio.sleep(0.1)
                     continue # Try next question or end

            if sent_message:
                self.last_question_message_id = sent_message.message_id
                self.question_start_time = time.time()
                timer_job_name = f"qtimer_{self.user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
                remove_job_if_exists(timer_job_name, context) 

                if not hasattr(context, 'bot_data') or context.bot_data is None: context.bot_data = {}
                context.bot_data[f"msg_cache_{self.chat_id}_{sent_message.message_id}"] = sent_message

                if context.job_queue:
                     context.job_queue.run_once(
                        question_timeout_callback_wrapper, 
                        self.question_time_limit,
                        chat_id=self.chat_id, 
                        user_id=self.user_id,
                        name=timer_job_name,
                        data={"quiz_id": self.quiz_id, "question_index": self.current_question_index, "user_id": self.user_id, "chat_id": self.chat_id, "message_id": sent_message.message_id, "question_was_image": self.last_question_is_image}
                    )
                else:
                    logger.warning(f"[QuizLogic {self.quiz_id}] JobQueue not available in context. Timer for question {self.current_question_index} will not be set.")
                return TAKING_QUIZ # Wait for answer
            else: # Failed to send question (either image or text)
                logger.error(f"[QuizLogic {self.quiz_id}] Critical error: sent_message is None after attempting to send question {q_id_log}. Skipping question.")
                # This case should ideally be caught by the specific error handlers above, but as a fallback:
                self.answers.append({
                    "question_id": q_id_log,
                    "question_text": question_text_display,
                    "chosen_option_id": None,
                    "chosen_option_text": "خطأ فادح في إرسال السؤال",
                    "correct_option_id": None,
                    "correct_option_text": self._get_correct_option_text_robust(current_question_data, for_skip=True),
                    "is_correct": False,
                    "time_taken": -999, 
                    "status": "skipped_error" # ADDED status
                })
                self.current_question_index += 1
                # No sleep here, loop to next or end
        
        # If loop finishes (all questions skipped or failed to send)
        logger.info(f"[QuizLogic {self.quiz_id}] All questions processed or skipped. Showing results.")
        return await self.show_results(bot, context)

    async def handle_answer(self, bot: Bot, context: CallbackContext, update: Update, answer_data_parts: list, **kwargs) -> int:
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] handle_answer: inactive. User {self.user_id}. Aborting.")
            # Try to remove the keyboard if possible from the original message
            if update.callback_query and update.callback_query.message:
                try:
                    await bot.edit_message_reply_markup(chat_id=self.chat_id, message_id=update.callback_query.message.message_id, reply_markup=None)
                except Exception as e_edit_inactive:
                    logger.debug(f"[QuizLogic {self.quiz_id}] Failed to remove keyboard on inactive answer: {e_edit_inactive}")
            return END 

        # answer_data_parts: ["ans", quiz_id, question_idx, chosen_option_id]
        try:
            answered_quiz_id = answer_data_parts[1]
            answered_question_index = int(answer_data_parts[2])
            chosen_option_id = str(answer_data_parts[3]) # Ensure it's a string for comparison
        except (IndexError, ValueError) as e_parse:
            logger.error(f"[QuizLogic {self.quiz_id}] Error parsing answer_data: {answer_data_parts}. Error: {e_parse}", exc_info=True)
            # Attempt to inform user of error without breaking flow if possible
            if update.callback_query:
                await safe_send_message(bot, chat_id=self.chat_id, text="حدث خطأ أثناء معالجة إجابتك. يرجى المحاولة مرة أخرى أو الاتصال بالدعم.")
            return TAKING_QUIZ # Stay in the same state, or consider END if unrecoverable

        if answered_quiz_id != self.quiz_id:
            logger.warning(f"[QuizLogic {self.quiz_id}] Mismatched quiz_id in answer. Expected {self.quiz_id}, got {answered_quiz_id}. Ignoring.")
            if update.callback_query: await update.callback_query.answer(text="إجابة لاختبار مختلف أو قديم.")
            return TAKING_QUIZ

        if answered_question_index != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Answer for wrong question. Expected {self.current_question_index}, got {answered_question_index}. Ignoring.")
            if update.callback_query: await update.callback_query.answer(text="إجابة لسؤال مختلف.")
            return TAKING_QUIZ

        # Stop the timer for the current question
        timer_job_name = f"qtimer_{self.user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        time_taken = time.time() - self.question_start_time if self.question_start_time else -1 # -1 if start_time was not set

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        
        chosen_option_text = "نص الخيار المختار غير متوفر"
        is_correct = False
        correct_option_id_actual = None
        correct_option_text_actual = "نص الخيار الصحيح غير متوفر"

        # Find chosen option text and determine correctness
        for option in current_question_data.get("options", []):
            opt_id_from_data = str(option.get("option_id")) # Ensure comparison is str to str
            
            if opt_id_from_data == chosen_option_id:
                if option.get("is_image_option"):
                    chosen_option_text = f"الخيار المصور: {option.get('image_option_display_label', chosen_option_id)}"
                else:
                    chosen_option_text = option.get("option_text", f"خيار {chosen_option_id}")
                
                is_correct = bool(option.get("is_correct", False))
                if is_correct:
                    self.score += 1
                break # Found chosen option
        
        # Find correct option text (even if not chosen)
        for option in current_question_data.get("options", []):
            if bool(option.get("is_correct", False)):
                correct_option_id_actual = str(option.get("option_id"))
                if option.get("is_image_option"):
                    correct_option_text_actual = f"الخيار المصور الصحيح: {option.get('image_option_display_label', correct_option_id_actual)}"
                else:
                    correct_option_text_actual = option.get("option_text", f"الخيار الصحيح {correct_option_id_actual}")
                break # Found correct option

        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": chosen_option_id,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id_actual,
            "correct_option_text": correct_option_text_actual,
            "is_correct": is_correct,
            "time_taken": round(time_taken, 2),
            "status": "answered" # ADDED status
        })

        # Remove keyboard from the question message
        message_id_to_edit = self.last_question_message_id
        if update.callback_query and update.callback_query.message:
             message_id_to_edit = update.callback_query.message.message_id
        
        if message_id_to_edit:
            try:
                # If it was an image question, edit caption's reply_markup. Otherwise, edit_message_reply_markup.
                # However, TG API often allows edit_message_reply_markup for photos too.
                # Simpler to just use edit_message_reply_markup and let it fail if it must.
                await bot.edit_message_reply_markup(chat_id=self.chat_id, message_id=message_id_to_edit, reply_markup=None)
            except telegram.error.BadRequest as e_bad_req:
                if "message is not modified" in str(e_bad_req).lower():
                    logger.debug(f"[QuizLogic {self.quiz_id}] Keyboard already removed or message unchanged for msg {message_id_to_edit}.")
                else:
                    logger.warning(f"[QuizLogic {self.quiz_id}] Failed to remove keyboard from msg {message_id_to_edit} (user {self.user_id}): {e_bad_req}")
            except Exception as e_edit_kbd:
                logger.warning(f"[QuizLogic {self.quiz_id}] Generic error removing kbd from msg {message_id_to_edit}: {e_edit_kbd}", exc_info=True)
        
        if update.callback_query: # Acknowledge the button press
            await update.callback_query.answer()

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            return await self.send_question(bot, context)
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] All questions answered. User {self.user_id}. Showing results.")
            return await self.show_results(bot, context)

    async def handle_timeout(self, bot: Bot, context: CallbackContext, job_data: dict):
        quiz_id_from_job = job_data.get("quiz_id")
        timed_out_question_index = job_data.get("question_index")
        message_id_for_timeout_q = job_data.get("message_id")
        question_was_image = job_data.get("question_was_image", False)

        if not self.active or quiz_id_from_job != self.quiz_id or timed_out_question_index != self.current_question_index:
            logger.info(f"[QuizLogic {self.quiz_id}] Stale timeout job ignored. Job QuizID: {quiz_id_from_job}, JobQIdx: {timed_out_question_index}. Current QuizID: {self.quiz_id}, CurrentQIdx: {self.current_question_index}. Active: {self.active}")
            return

        logger.info(f"[QuizLogic {self.quiz_id}] Timeout for question {self.current_question_index}. User {self.user_id}")
        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        correct_option_text = self._get_correct_option_text_robust(current_question_data)
        
        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": self._get_correct_option_id_robust(current_question_data),
            "correct_option_text": correct_option_text,
            "is_correct": False,
            "time_taken": self.question_time_limit, # Or actual time if slightly over
            "status": "timeout" # ADDED status
        })

        timeout_message = f"انتهى الوقت للسؤال الحالي. الإجابة الصحيحة هي: {correct_option_text}"
        
        # Try to edit the timed-out question message to remove keyboard and show timeout info
        if message_id_for_timeout_q:
            try:
                if question_was_image:
                    await bot.edit_message_caption(chat_id=self.chat_id, message_id=message_id_for_timeout_q, caption=timeout_message, reply_markup=None)
                else:
                    await bot.edit_message_text(text=timeout_message, chat_id=self.chat_id, message_id=message_id_for_timeout_q, reply_markup=None)
            except telegram.error.BadRequest as e_bad_req_timeout:
                 if "message is not modified" not in str(e_bad_req_timeout).lower() and "message to edit not found" not in str(e_bad_req_timeout).lower() :
                    logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message on timeout (q_idx {self.current_question_index}, msg_id {message_id_for_timeout_q}): {e_bad_req_timeout}. Sending new message instead.")
                    await safe_send_message(bot, chat_id=self.chat_id, text=timeout_message) # Fallback to new message
                 else:
                    logger.debug(f"[QuizLogic {self.quiz_id}] Message not modified or not found on timeout edit: {e_bad_req_timeout}")
            except Exception as e_edit_timeout:
                logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message on timeout (q_idx {self.current_question_index}, msg_id {message_id_for_timeout_q}): {e_edit_timeout}", exc_info=True)
                await safe_send_message(bot, chat_id=self.chat_id, text=timeout_message) # Fallback to new message
        else:
            await safe_send_message(bot, chat_id=self.chat_id, text=timeout_message)

        await asyncio.sleep(1) # Give user a moment to read timeout message

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await self.send_question(bot, context) # This will return TAKING_QUIZ if successful
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] All questions processed (last one timed out). User {self.user_id}. Showing results.")
            await self.show_results(bot, context) # This will return SHOWING_RESULTS or END
            # The state transition is handled by the return value of send_question/show_results

    def _get_correct_option_text_robust(self, question_data, for_skip=False):
        # Helper to safely get correct option text
        default_text = "غير متوفرة بسبب خطأ" if not for_skip else "غير متوفرة (سؤال تم تخطيه)"
        try:
            for option in question_data.get("options", []):
                if bool(option.get("is_correct")):
                    if option.get("is_image_option"):
                        return f"الخيار المصور: {option.get('image_option_display_label', 'ID: '+str(option.get('option_id')))}"
                    return option.get("option_text", default_text)
            return "لم يتم تحديد إجابة صحيحة"
        except Exception as e_get_text:
            logger.error(f"[QuizLogic {self.quiz_id}] Error in _get_correct_option_text_robust: {e_get_text}")
            return default_text

    def _get_correct_option_id_robust(self, question_data):
        try:
            for option in question_data.get("options", []):
                if bool(option.get("is_correct")):
                    return str(option.get("option_id"))
            return None
        except Exception as e_get_id:
            logger.error(f"[QuizLogic {self.quiz_id}] Error in _get_correct_option_id_robust: {e_get_id}")
            return None

    async def show_results(self, bot: Bot, context: CallbackContext, original_message_id_to_edit: int = None) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] show_results called for user {self.user_id}. Score: {self.score}/{self.total_questions}")
        self.active = False # Quiz is no longer active once results are shown

        summary = f"<b>نتائج الاختبار: {self.quiz_name}</b>\n"
        summary += f"النتيجة: {self.score} من {self.total_questions}\n\n"
        summary += "<b>ملخص إجاباتك:</b>\n"

        for i, ans_data in enumerate(self.answers):
            q_text = ans_data.get("question_text")
            chosen_opt_text = ans_data.get("chosen_option_text")
            correct_opt_text = ans_data.get("correct_option_text")
            is_corr = ans_data.get("is_correct")
            status = ans_data.get("status", "answered") # Default to answered if status missing

            # Handle None for text fields (SHOW_RESULTS_FIX)
            q_text_display = q_text if q_text is not None else "(نص السؤال غير متوفر أو سؤال مصور)"
            chosen_opt_display = chosen_opt_text if chosen_opt_text is not None else "(لم يتم اختيار إجابة أو خيار مصور)"
            correct_opt_display = correct_opt_text if correct_opt_text is not None else "(الإجابة الصحيحة غير متوفرة أو خيار مصور)"

            summary += f"\n<b>السؤال {i+1}:</b> {q_text_display}\n"
            if status == "answered":
                summary += f"إجابتك: {chosen_opt_display} ({'صحيحة' if is_corr else 'خاطئة'})
"
                if not is_corr:
                    summary += f"الإجابة الصحيحة: {correct_opt_display}\n"
            elif status == "timeout":
                summary += f"إجابتك: {chosen_opt_display} (انتهى الوقت)
"
                summary += f"الإجابة الصحيحة: {correct_opt_display}\n"
            elif status == "skipped_auto":
                summary += f"إجابتك: {chosen_opt_display} (تم تخطي السؤال تلقائياً - خيارات غير كافية)
"
            elif status == "skipped_error" or status == "error_sending":
                 summary += f"إجابتك: {chosen_opt_display} (حدث خطأ متعلق بالسؤال)
"
            else: # Generic fallback for other statuses
                 summary += f"حالة السؤال: {status}. إجابتك: {chosen_opt_display}
"
                 summary += f"الإجابة الصحيحة: {correct_opt_display}\n"

        # Save results to DB
        await self._save_results_to_db(context)

        keyboard = [
            [InlineKeyboardButton("📊 عرض إحصائياتي", callback_data="show_my_stats")],
            [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Try to edit the message that initiated the quiz if an ID was passed
        # Or, if not, use the last question message ID if available
        message_to_edit = original_message_id_to_edit
        if not message_to_edit and self.last_question_message_id:
            # Check if the last question message is still in cache (might have been deleted by timeout handler)
            cached_msg = context.bot_data.pop(f"msg_cache_{self.chat_id}_{self.last_question_message_id}", None)
            if cached_msg: 
                message_to_edit = self.last_question_message_id
            else:
                logger.info(f"[QuizLogic {self.quiz_id}] Last question message {self.last_question_message_id} not in cache for results edit. Sending new message.")

        if message_to_edit:
            try:
                # Determine if it was an image caption or regular text message
                # This is tricky without knowing the original message type. 
                # We'll try edit_message_text first, as it's more common for results displays.
                # If self.last_question_is_image was true for the *very last* question, 
                # it's more likely a caption, but the quiz might have ended before that.
                # A robust solution might need to store the type of the *initiating* message if that's what we want to edit.
                # For now, let's assume we are editing the last question's message or a similar text message.
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_to_edit, text=summary, reply_markup=reply_markup, parse_mode="HTML")
                logger.info(f"[QuizLogic {self.quiz_id}] Results displayed by editing message {message_to_edit}.")
            except telegram.error.BadRequest as e_edit_results:
                if "message to edit not found" in str(e_edit_results).lower() or "message can't be edited" in str(e_edit_results).lower():
                    logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message {message_to_edit} for results (not found/can't be edited): {e_edit_results}. Sending new message.")
                    await safe_send_message(bot, chat_id=self.chat_id, text=summary, reply_markup=reply_markup, parse_mode="HTML")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] BadRequest editing message {message_to_edit} for results: {e_edit_results}. Sending new message.", exc_info=True)
                    await safe_send_message(bot, chat_id=self.chat_id, text=summary, reply_markup=reply_markup, parse_mode="HTML") # Fallback
            except Exception as e_gen_edit_results:
                logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message {message_to_edit} for results: {e_gen_edit_results}. Sending new message.", exc_info=True)
                await safe_send_message(bot, chat_id=self.chat_id, text=summary, reply_markup=reply_markup, parse_mode="HTML") # Fallback
        else:
            await safe_send_message(bot, chat_id=self.chat_id, text=summary, reply_markup=reply_markup, parse_mode="HTML")
            logger.info(f"[QuizLogic {self.quiz_id}] Results displayed by sending a new message.")
        
        await self.cleanup_quiz_data(context, self.user_id, "quiz_completed")
        return END # Or SHOWING_RESULTS if you want a different state after results.
                   # END is typical if the conversation should terminate here.

    async def _save_results_to_db(self, context: CallbackContext):
        if not self.db_manager:
            logger.error(f"[QuizLogic {self.quiz_id}] db_manager is missing. Cannot save quiz results to DB for user {self.user_id}.")
            return
        
        if not self.db_quiz_session_id:
            logger.error(f"[QuizLogic {self.quiz_id}] db_quiz_session_id is missing. Cannot accurately save quiz results to DB for user {self.user_id}.")
            # Optionally, could try a generic save without session ID, but less ideal.
            return

        quiz_end_time = datetime.now(timezone.utc)
        
        # Calculate total time taken for the quiz if start time is available
        total_duration_seconds = -1 # Default if start time is missing
        if self.quiz_actual_start_time_dt:
            total_duration_seconds = (quiz_end_time - self.quiz_actual_start_time_dt).total_seconds()

        try:
            self.db_manager.save_quiz_results(
                quiz_session_uuid=self.db_quiz_session_id, 
                user_id=self.user_id,
                score=self.score,
                total_questions_answered=len(self.answers), # This reflects how many were processed, including timeouts/skips
                # total_questions_in_quiz=self.total_questions, # Already in quiz_sessions table via start_quiz_session
                end_time=quiz_end_time,
                answers_details=json.dumps(self.answers, ensure_ascii=False), # Store detailed answers as JSON
                quiz_name=self.quiz_name, # Pass quiz_name again for potential denormalization or easier querying on results
                total_duration_seconds=round(total_duration_seconds, 2)
            )
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz results for session {self.db_quiz_session_id} (User {self.user_id}) saved to DB successfully.")
        except Exception as e:
            logger.error(f"[QuizLogic {self.quiz_id}] Failed to save quiz results for session {self.db_quiz_session_id} (User {self.user_id}) to DB: {e}", exc_info=True)

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.debug(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user {user_id}. Reason: {reason}")
        # Remove any pending timers for this quiz instance
        timer_job_name_pattern = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_*"
        # Note: JobQueue.get_jobs_by_name() might not support wildcards directly in all versions or implementations.
        # A more robust way is to iterate if many timers, or ensure specific names are removed when known.
        # For now, we assume the current_question_index timer is the primary one to remove if quiz ends prematurely.
        current_timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(current_timer_job_name, context)

        # Clear sensitive data from context.user_data if it was stored there for this quiz instance
        # Example: if context.user_data.get('current_quiz_instance_id') == self.quiz_id:
        # context.user_data.pop('current_quiz_instance_id', None)
        # context.user_data.pop(f'quiz_logic_{self.quiz_id}', None) # If the instance itself was stored
        
        # Reset internal state variables to prevent reuse issues if the same QuizLogic object were somehow reused (though typically new one is made)
        self.active = False
        self.current_question_index = 0
        self.score = 0
        self.answers = []
        self.question_start_time = None
        # self.db_quiz_session_id should persist for logging, but other dynamic states reset.

        # Remove any cached messages related to this quiz instance from bot_data if stored there
        # This is more complex if message IDs are not systematically tracked.
        # Example: if self.last_question_message_id:
        #     context.bot_data.pop(f"msg_cache_{self.chat_id}_{self.last_question_message_id}", None)

        logger.info(f"[QuizLogic {self.quiz_id}] Quiz data cleanup for user {user_id} (reason: {reason}) completed.")

# This is a global function, must be defined outside the class
async def question_timeout_callback_wrapper(context: CallbackContext):
    job = context.job
    if not job or not job.data:
        logger.error("question_timeout_callback_wrapper: Job or job.data is missing.")
        return

    quiz_id = job.data.get("quiz_id")
    user_id = job.data.get("user_id")
    # chat_id = job.data.get("chat_id") # Not directly used by QuizLogic.handle_timeout but good for logging

    if not quiz_id or not user_id:
        logger.error(f"question_timeout_callback_wrapper: quiz_id ({quiz_id}) or user_id ({user_id}) missing in job data.")
        return

    # Retrieve the QuizLogic instance from context.user_data
    # This assumes quiz_logic_instance is stored in context.user_data[f'quiz_logic_{quiz_id}']
    # or context.chat_data or context.bot_data, depending on how it's managed by the handler
    # For this example, we'll assume it's in user_data, which is common for per-user conversation state.
    
    # IMPORTANT: The way QuizLogic instance is retrieved here MUST match how it's stored by the ConversationHandler
    # or whatever mechanism is managing active quizzes.
    # If quiz_logic instances are stored in context.chat_data keyed by user_id (if multiple users in one chat can take quizzes)
    # or directly in context.user_data if one user = one quiz at a time.
    
    # Let's assume it's stored in context.bot_data for simplicity of this example, keyed by quiz_id
    # This is a common pattern if quiz_id is globally unique for active quizzes.
    quiz_logic_instance = context.bot_data.get(f"quiz_logic_instance_{quiz_id}")

    if quiz_logic_instance and isinstance(quiz_logic_instance, QuizLogic):
        logger.info(f"[QuizLogic {quiz_id}] Timeout job triggered for user {user_id}. Calling handle_timeout.")
        await quiz_logic_instance.handle_timeout(bot=context.bot, context=context, job_data=job.data)
    else:
        logger.warning(f"question_timeout_callback_wrapper: QuizLogic instance not found or invalid for quiz_id {quiz_id} and user {user_id}. Quiz may have already ended or data cleaned up.")

