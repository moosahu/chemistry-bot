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
                        "time_taken": -997, 
                        "status": "error_sending"
                    })
                     self.current_question_index += 1
                     await asyncio.sleep(0.1)
                     continue # Try next question or end
            
            if sent_message:
                self.last_question_message_id = sent_message.message_id
                self.question_start_time = time.time()
                # Schedule timeout job
                if self.question_time_limit > 0:
                    timer_job_name = f"question_timer_{self.quiz_id}_{self.current_question_index}"
                    remove_job_if_exists(timer_job_name, context) # Remove old job if any
                    context.job_queue.run_once(
                        question_timeout_callback_wrapper, 
                        self.question_time_limit, 
                        data={
                            "quiz_id": self.quiz_id,
                            "user_id": self.user_id, 
                            "chat_id": self.chat_id, 
                            "question_index": self.current_question_index,
                            "message_id": self.last_question_message_id,
                            "question_was_image": self.last_question_is_image
                        }, 
                        name=timer_job_name
                    )
                    logger.debug(f"[QuizLogic {self.quiz_id}] Timeout job '{timer_job_name}' scheduled for {self.question_time_limit}s for q_idx {self.current_question_index}")
                return TAKING_QUIZ 
            else: # sent_message is None, meaning sending failed and we continued
                logger.error(f"[QuizLogic {self.quiz_id}] sent_message was None after attempting to send q_idx {self.current_question_index}. This shouldn't happen if continue was hit.")
                # This case should ideally be unreachable if the error handling for send failures (with continue) is correct.
                # If we reach here, it implies a logic flaw. We'll try to end the quiz gracefully.
                await safe_send_message(bot, self.chat_id, "حدث خطأ غير متوقع أثناء محاولة عرض السؤال التالي. سيتم إنهاء الاختبار.")
                await self.cleanup_quiz_data(context, self.user_id, "send_question_critical_failure")
                return END

        # If loop finishes, all questions are done
        logger.info(f"[QuizLogic {self.quiz_id}] All questions sent for user {self.user_id}.")
        return await self.show_results(bot, context, update) # Pass bot, context, and update

    async def handle_answer(self, update: Update, context: CallbackContext, **kwargs): # Added **kwargs
        if not self.active:
            logger.warning(f"[QuizLogic N/A] handle_answer: inactive quiz instance for user {self.user_id}. Callback: {update.callback_query.data if update.callback_query else 'NoCallback'}. Aborting.")
            if update.callback_query:
                try:
                    await update.callback_query.answer(text="هذا الاختبار لم يعد نشطاً.")
                except Exception as e_ans_inactive:
                    logger.error(f"[QuizLogic N/A] Error sending inactive answer confirmation: {e_ans_inactive}")
            return TAKING_QUIZ # Or END, but TAKING_QUIZ might prevent handler from breaking chain

        query = update.callback_query
        await query.answer() # Acknowledge callback

        # Extract info from callback_data: "ans_QUIZID_QINDEX_OPTID"
        try:
            _, quiz_id_from_cb, q_index_str, chosen_option_id = query.data.split("_")
            q_index_from_cb = int(q_index_str)
        except ValueError as e:
            logger.error(f"[QuizLogic {self.quiz_id if hasattr(self, 'quiz_id') else 'CB_PARSE_FAIL'}] Invalid callback_data format: {query.data}. Error: {e}")
            await safe_edit_message_text(context.bot, self.chat_id, query.message.message_id, "حدث خطأ في معالجة إجابتك (بيانات خاطئة).", reply_markup=None)
            return TAKING_QUIZ

        # Verify quiz_id and question_index match the current state of this instance
        if not hasattr(self, 'quiz_id') or self.quiz_id != quiz_id_from_cb:
            logger.warning(f"[QuizLogic {self.quiz_id if hasattr(self, 'quiz_id') else 'N/A'}] Mismatched quiz_id in callback. Instance: {self.quiz_id}, CB: {quiz_id_from_cb}. User {self.user_id}. Ignoring.")
            # Potentially an answer for an old quiz instance
            try:
                await query.edit_message_text(text=query.message.text + "\n\n(إجابة من اختبار سابق أو غير صالح)", reply_markup=None)
            except Exception as e_edit_old:
                logger.debug(f"[QuizLogic {self.quiz_id if hasattr(self, 'quiz_id') else 'N/A'}] Failed to edit message for old/mismatched quiz answer: {e_edit_old}")
            return TAKING_QUIZ 

        if self.current_question_index != q_index_from_cb:
            logger.warning(f"[QuizLogic {self.quiz_id}] Mismatched question_index in callback. Current: {self.current_question_index}, CB: {q_index_from_cb}. User {self.user_id}. Ignoring (likely late answer).")
            # User might have answered an old question after a new one was sent or after timeout handled it.
            try:
                await query.edit_message_text(text=query.message.text + "\n\n(إجابة متأخرة لسؤال سابق)", reply_markup=None)
            except Exception as e_edit_late:
                logger.debug(f"[QuizLogic {self.quiz_id}] Failed to edit message for late answer: {e_edit_late}")
            return TAKING_QUIZ

        # Process the answer
        time_taken = -1
        if self.question_start_time:
            time_taken = time.time() - self.question_start_time
        
        # Remove the timer job for the current question as it has been answered
        timer_job_name = f"question_timer_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        logger.debug(f"[QuizLogic {self.quiz_id}] Answer received for q_idx {self.current_question_index}. Timer job '{timer_job_name}' removed if it existed.")

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        options = current_question_data.get("options", [])
        correct_option_id = current_question_data.get("correct_option_id")
        
        chosen_option_text = "N/A"
        is_correct = False

        for option_data in options: # options here should be the processed_options with image labels
            if option_data.get("option_id") == chosen_option_id:
                if option_data.get('is_image_option'):
                    chosen_option_text = f"الخيار المصور: {option_data.get('image_option_display_label', chosen_option_id)}"
                else:
                    chosen_option_text = option_data.get("option_text", chosen_option_id)
                
                if correct_option_id is not None and chosen_option_id == correct_option_id:
                    self.score += 1
                    is_correct = True
                elif correct_option_id is None: # No correct answer defined (e.g. survey)
                    is_correct = None # Mark as neither correct nor incorrect
                break
        
        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", ""),
            "chosen_option_id": chosen_option_id,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id,
            "correct_option_text": self._get_correct_option_text_robust(current_question_data),
            "is_correct": is_correct,
            "time_taken": time_taken,
            "status": "answered"
        })

        # Edit the question message to show it's answered (optional, or remove keyboard)
        try:
            text_after_answer = query.message.text_html if query.message.text_html else query.message.text
            if query.message.caption_html:
                 text_after_answer = query.message.caption_html
            
            # Append a small confirmation, or just remove keyboard
            # For simplicity, just remove keyboard by setting reply_markup=None
            if query.message.photo: # If it was a photo question
                await query.edit_message_caption(caption=text_after_answer + f"\n<i><b>إجابتك ({chosen_option_text}) تم تسجيلها.</b></i>", reply_markup=None, parse_mode='HTML')
            else: # Text question
                await query.edit_message_text(text=text_after_answer + f"\n<i><b>إجابتك ({chosen_option_text}) تم تسجيلها.</b></i>", reply_markup=None, parse_mode='HTML')
            logger.debug(f"[QuizLogic {self.quiz_id}] Edited message for q_idx {self.current_question_index} after answer.")
        except telegram.error.BadRequest as e:
            if "message is not modified" in str(e).lower():
                logger.debug(f"[QuizLogic {self.quiz_id}] Message for q_idx {self.current_question_index} not modified, or already changed: {e}")
            else:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message for q_idx {self.current_question_index} after answer: {e}")
        except Exception as e_edit:
            logger.warning(f"[QuizLogic {self.quiz_id}] Generic fail to edit message for q_idx {self.current_question_index} after answer: {e_edit}")

        self.current_question_index += 1
        return await self.send_question(context.bot, context) # Pass bot and context

    async def handle_timeout(self, bot: Bot, context: CallbackContext): # Added bot, context
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] handle_timeout: inactive. User {self.user_id}. Aborting.")
            return TAKING_QUIZ # Or END

        logger.info(f"[QuizLogic {self.quiz_id}] Timeout for q_idx {self.current_question_index}, user {self.user_id}")
        
        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')

        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", ""),
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": current_question_data.get("correct_option_id"),
            "correct_option_text": self._get_correct_option_text_robust(current_question_data),
            "is_correct": False,
            "time_taken": self.question_time_limit, # Or actual time if timer was more precise
            "status": "timeout"
        })
        
        # Message editing to indicate timeout is now handled in question_timeout_callback_wrapper
        # However, we might want to send a follow-up message or proceed to next question directly.
        # For now, let's ensure the next question is triggered or results are shown.

        self.current_question_index += 1
        return await self.send_question(bot, context) # Pass bot and context

    async def show_results(self, bot: Bot, context: CallbackContext, update: Update = None): # Added bot, context, update (optional)
        logger.info(f"[QuizLogic {self.quiz_id}] show_results called for user {self.user_id}. Score: {self.score}/{self.total_questions}")
        if not self.active and not self.answers: # If not active and no answers, probably ended prematurely without starting
            logger.warning(f"[QuizLogic {self.quiz_id}] show_results called but quiz was not active and no answers recorded. Sending generic end message.")
            # Try to get the original message to edit if available from update
            message_to_edit_id = None
            if update and update.callback_query and update.callback_query.message:
                message_to_edit_id = update.callback_query.message.message_id
            elif self.last_question_message_id: # Fallback to stored last_question_message_id
                message_to_edit_id = self.last_question_message_id

            final_text = "انتهى الاختبار. لم يتم تسجيل أي إجابات."
            keyboard = [[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if message_to_edit_id:
                try:
                    await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_to_edit_id, text=final_text, reply_markup=reply_markup)
                except Exception as e_edit_no_ans:
                    logger.error(f"[QuizLogic {self.quiz_id}] Error editing message in show_results (no answers): {e_edit_no_ans}. Sending new.")
                    await safe_send_message(bot, chat_id=self.chat_id, text=final_text, reply_markup=reply_markup)
            else:
                await safe_send_message(bot, chat_id=self.chat_id, text=final_text, reply_markup=reply_markup)
            
            await self.cleanup_quiz_data(context, self.user_id, "show_results_no_answers_or_inactive")
            return END

        summary = f"<b>ملخص اختبار '{self.quiz_name}' الخاص بك:</b>\n"
        summary += f"مجموع النقاط: {self.score} من {self.total_questions}\n\n"

        for i, ans_data in enumerate(self.answers):
            q_text = ans_data.get("question_text", f"سؤال {i+1}")
            chosen_opt_text = ans_data.get("chosen_option_text", "لم تتم الإجابة")
            correct_opt_text = ans_data.get("correct_option_text", "(غير محدد)")
            is_corr = ans_data.get("is_correct")
            status = ans_data.get("status", "unknown")

            summary += f"<b>السؤال {i+1}:</b> {q_text}\n"
            
            chosen_opt_display = chosen_opt_text
            if chosen_opt_text is None or str(chosen_opt_text).strip() == "":
                chosen_opt_display = "(فارغ)"
            
            correct_opt_display = correct_opt_text
            if correct_opt_text is None or str(correct_opt_text).strip() == "":
                correct_opt_display = "(الإجابة الصحيحة غير متوفرة)"

            if status == "answered":
                corr_status_text = ""
                if is_corr is True:
                    corr_status_text = "صحيحة"
                elif is_corr is False:
                    corr_status_text = "خاطئة"
                else: # is_corr is None (e.g. survey question)
                    corr_status_text = "(لا يوجد تصحيح)"
                summary += f"إجابتك: {chosen_opt_display} ({corr_status_text})\n"
                if is_corr is False and correct_option_id is not None: # Only show correct if answer was wrong and there IS a correct answer
                    summary += f"الإجابة الصحيحة: {correct_opt_display}\n"
            elif status == "timeout":
                summary += f"إجابتك: {chosen_opt_display} (انتهى الوقت)\n"
                summary += f"الإجابة الصحيحة: {correct_opt_display}\n"
            elif status == "skipped_manual": # Assuming you might add this status
                summary += f"إجابتك: {chosen_opt_display} (تم تخطي السؤال يدوياً)\n"
                summary += f"الإجابة الصحيحة: {correct_opt_display}\n" 
            elif status == "skipped_auto":
                summary += f"إجابتك: {chosen_opt_display} (تم تخطي السؤال تلقائياً - خيارات غير كافية)\n"
            elif status == "skipped_error" or status == "error_sending":
                 summary += f"إجابتك: {chosen_opt_display} (حدث خطأ متعلق بالسؤال)\n"
            else: # Generic fallback for other statuses
                 summary += f"حالة السؤال: {status}. إجابتك: {chosen_opt_display}\n"
                 summary += f"الإجابة الصحيحة: {correct_opt_display}\n"
            summary += "\n" # Add a blank line for better readability between questions

        # Save results to DB
        await self._save_results_to_db(context)

        # Send summary
        keyboard = [[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Try to edit the last question message if it exists, otherwise send a new one.
        message_to_edit_id = None
        if update and update.callback_query and update.callback_query.message:
            message_to_edit_id = update.callback_query.message.message_id
        elif self.last_question_message_id: # Fallback to stored last_question_message_id
            message_to_edit_id = self.last_question_message_id

        if message_to_edit_id:
            logger.debug(f"[QuizLogic {self.quiz_id}] Attempting to edit message {message_to_edit_id} with results.")
            try:
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_to_edit_id, text=summary, reply_markup=reply_markup, parse_mode="HTML")
            except telegram.error.BadRequest as e:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message {message_to_edit_id} with results (BadRequest: {e}). Sending new message.")
                await safe_send_message(bot, chat_id=self.chat_id, text=summary, reply_markup=reply_markup, parse_mode="HTML") # Fallback to send
            except Exception as e:
                logger.error(f"[QuizLogic {self.quiz_id}] Unexpected error editing message {message_to_edit_id} with results: {e}. Sending new message.", exc_info=True)
                await safe_send_message(bot, chat_id=self.chat_id, text=summary, reply_markup=reply_markup, parse_mode="HTML") # Fallback to send
        else:
            logger.debug(f"[QuizLogic {self.quiz_id}] No message to edit. Sending new message with results.")
            await safe_send_message(bot, chat_id=self.chat_id, text=summary, reply_markup=reply_markup, parse_mode="HTML")

        await self.cleanup_quiz_data(context, self.user_id, "quiz_completed_show_results")
        return END # Or SHOWING_RESULTS if you have a specific state for it

    def _get_correct_option_text_robust(self, question_data, for_skip=False):
        """Robustly tries to get the text of the correct option."""
        if not question_data or not isinstance(question_data, dict):
            return "(بيانات السؤال غير متوفرة)"
        
        options = question_data.get("options", [])
        correct_option_id_from_q = question_data.get("correct_option_id")
        
        if correct_option_id_from_q is None and not for_skip:
            # If not skipping, and no correct_option_id, it might be an issue or an info-only question
            logger.warning(f"[QuizLogic {self.quiz_id}] _get_correct_option_text_robust: Question (ID: {question_data.get('question_id')}) has no correct_option_id specified.")
            return "(لم يتم تحديد إجابة صحيحة لهذا السؤال)"
        elif correct_option_id_from_q is None and for_skip:
             return "(لم يتم تحديد إجابة صحيحة - تم التخطي)" # More specific for skipped questions

        for opt in options:
            if isinstance(opt, dict) and opt.get("option_id") == correct_option_id_from_q:
                opt_text = opt.get("option_text")
                if opt.get("is_image_option"):
                    label = opt.get("image_option_display_label", "صورة")
                    return f"(خيار مصور: {label})"
                return opt_text if opt_text is not None else "(نص الخيار الصحيح فارغ)"
        logger.warning(
            f"""[QuizLogic {self.quiz_id}] _get_correct_option_text_robust: Correct option ID \
               {correct_option_id_from_q} not found in options for Q: {question_data.get("question_id")}"""
        )
        return "(تعذر العثور على نص الإجابة الصحيحة)"

    async def _save_results_to_db(self, context: CallbackContext):
        logger.info(f"[QuizLogic {self.quiz_id}] Attempting to save quiz results to DB. Session UUID: {self.db_quiz_session_id}")
        if not self.db_manager:
            logger.error(f"[QuizLogic {self.quiz_id}] db_manager is None. Cannot save results to DB.")
            return

        if not self.db_quiz_session_id:
            logger.error(f"[QuizLogic {self.quiz_id}] db_quiz_session_id is None. Cannot save detailed answers or finalize quiz session in DB.")
            return

        quiz_end_time_dt = datetime.now(timezone.utc)
        
        # Log each answer
        for ans_data in self.answers:
            try:
                self.db_manager.log_answer(
                    quiz_session_uuid=self.db_quiz_session_id, 
                    question_id=ans_data.get("question_id"),
                    question_text=ans_data.get("question_text"),
                    chosen_option_id=ans_data.get("chosen_option_id"),
                    chosen_option_text=ans_data.get("chosen_option_text"),
                    is_correct=ans_data.get("is_correct", False),
                    time_taken_ms=int(ans_data.get("time_taken", -1) * 1000) if ans_data.get("time_taken", -1) is not None else -1, # Convert s to ms, handle None
                    answer_timestamp=quiz_end_time_dt, # Approximate with quiz end time, or get more granular if available
                    status=ans_data.get("status", "unknown")
                )
            except Exception as e:
                q_id_log = ans_data.get("question_id", "N/A")
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to log answer for q_id {q_id_log} to DB: {e}", exc_info=True)

        # Finalize quiz session (update score, end time, etc.)
        try:
            self.db_manager.end_quiz_session(
                quiz_session_uuid=self.db_quiz_session_id,
                final_score=self.score,
                end_time=quiz_end_time_dt,
                total_answered=sum(1 for ans in self.answers if ans.get("status") == "answered"),
                total_correct=self.score, # Assuming score is number of correct answers
                total_timedout=sum(1 for ans in self.answers if ans.get("status") == "timeout"),
                total_skipped_auto=sum(1 for ans in self.answers if ans.get("status") == "skipped_auto"),
                total_skipped_error=sum(1 for ans in self.answers if ans.get("status") == "skipped_error" or ans.get("status") == "error_sending")
            )
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz session {self.db_quiz_session_id} finalized in DB.")
        except Exception as e:
            logger.error(f"[QuizLogic {self.quiz_id}] Failed to finalize quiz session {self.db_quiz_session_id} in DB: {e}", exc_info=True)

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.info(f"[QuizLogic quiz_id_unknown_at_cleanup] cleanup_quiz_data called for user {user_id}. Reason: {reason}. Quiz ID was: {self.quiz_id if hasattr(self, 'quiz_id') else 'N/A'}")
        self.active = False 
        # Remove any pending timer job for this quiz instance
        timer_job_name = f"question_timer_{self.quiz_id}_{self.current_question_index}" 
        remove_job_if_exists(timer_job_name, context)
        
        # Clear user_data for this specific quiz instance
        if context.user_data and self.quiz_id in context.user_data.get("active_quizzes", {}):
            del context.user_data["active_quizzes"][self.quiz_id]
            logger.debug(f"[QuizLogic {self.quiz_id}] Removed quiz instance from context.user_data.active_quizzes for user {user_id}")
        elif context.user_data and "active_quizzes" not in context.user_data:
             logger.debug(f"[QuizLogic {self.quiz_id}] context.user_data.active_quizzes not found for user {user_id}. No cleanup needed there.")
        elif context.user_data and self.quiz_id not in context.user_data.get("active_quizzes", {}):
            logger.debug(f"[QuizLogic {self.quiz_id}] Quiz instance ID not found in context.user_data.active_quizzes for user {user_id}. No cleanup needed there.")
        else: # context.user_data is None or other issue
            logger.warning(f"[QuizLogic {self.quiz_id}] context.user_data not available or issue during cleanup for user {user_id}")

        # Reset internal state variables (optional, as instance might be discarded)
        self.questions_data = []
        self.answers = []
        self.current_question_index = 0
        self.score = 0
        self.last_question_message_id = None
        # Do not reset self.db_manager or self.quiz_id if they might be needed for final logging outside this instance lifecycle
        logger.info(f"[QuizLogic {self.quiz_id if hasattr(self, 'quiz_id') else 'N/A'}] Quiz data cleanup completed for user {user_id}.")

# Timeout handler logic
async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    quiz_id = job_data.get("quiz_id")
    question_idx_timed_out = job_data.get("question_index")
    user_id = job_data.get("user_id")
    chat_id = job_data.get("chat_id")
    message_id_to_edit = job_data.get("message_id")
    question_was_image = job_data.get("question_was_image", False)

    logger.info(f"[TimeoutCallback quiz_id={quiz_id}] Timeout for user {user_id}, q_idx {question_idx_timed_out}")

    # Retrieve the QuizLogic instance from context.user_data
    active_quizzes = context.user_data.get("active_quizzes", {})
    quiz_logic_instance = active_quizzes.get(quiz_id)

    if quiz_logic_instance and quiz_logic_instance.active and quiz_logic_instance.current_question_index == question_idx_timed_out:
        logger.info(f"[TimeoutCallback quiz_id={quiz_id}] Instance found and active. Processing timeout.")
        
        # Edit the timed-out question message to remove buttons and indicate timeout
        timeout_text = "انتهى الوقت المخصص لهذا السؤال."
        try:
            if message_id_to_edit:
                # If it was an image, we can't edit the caption's reply_markup directly to remove buttons in a way that works universally
                # Best to send a new message or edit text if it wasn't an image.
                # For simplicity, let's try to edit the text/caption. If it was an image, the caption will be replaced.
                # If it was a text message, the text will be replaced.
                await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=message_id_to_edit, text=timeout_text, reply_markup=None, parse_mode="HTML") 
                logger.debug(f"[TimeoutCallback quiz_id={quiz_id}] Edited message {message_id_to_edit} to show timeout.")
            else:
                logger.warning(f"[TimeoutCallback quiz_id={quiz_id}] No message_id to edit for timeout message.")
        except telegram.error.BadRequest as e:
            if "message is not modified" in str(e).lower():
                logger.debug(f"[TimeoutCallback quiz_id={quiz_id}] Message {message_id_to_edit} was already as intended or uneditable (not modified). {e}")
            else:
                logger.error(f"[TimeoutCallback quiz_id={quiz_id}] Error editing message {message_id_to_edit} for timeout: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[TimeoutCallback quiz_id={quiz_id}] Generic error editing message {message_id_to_edit} for timeout: {e}", exc_info=True)

        # Call handle_timeout on the instance
        await quiz_logic_instance.handle_timeout(context.bot, context) # Pass bot and context
    elif not quiz_logic_instance:
        logger.warning(f"[TimeoutCallback quiz_id={quiz_id}] QuizLogic instance NOT FOUND for user {user_id}. Quiz might have ended or data cleaned up.")
    elif not quiz_logic_instance.active:
        logger.info(f"[TimeoutCallback quiz_id={quiz_id}] QuizLogic instance found but NOT ACTIVE for user {user_id}. Timeout likely for an already handled question or ended quiz.")
    elif quiz_logic_instance.current_question_index != question_idx_timed_out:
        logger.info(f"[TimeoutCallback quiz_id={quiz_id}] QuizLogic instance found, active, but current_q_idx ({quiz_logic_instance.current_question_index}) != timed_out_q_idx ({question_idx_timed_out}). Timeout for an old question.")
    else:
        logger.error(f"[TimeoutCallback quiz_id={quiz_id}] Unhandled case for user {user_id}. Instance: {bool(quiz_logic_instance)}, Active: {quiz_logic_instance.active if quiz_logic_instance else 'N/A'}, CurrentQ: {quiz_logic_instance.current_question_index if quiz_logic_instance else 'N/A'}, TimedOutQ: {question_idx_timed_out}")


