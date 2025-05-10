"""Manages the logic for conducting a quiz, including sending questions, handling answers, and calculating results."""
# handlers/quiz_logic.py (Modified to import DB_MANAGER directly)

import asyncio
import logging
import time
import uuid 
import telegram # For telegram.error types
from datetime import datetime, timezone 
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot 
from telegram.ext import ConversationHandler, CallbackContext, JobQueue 

from config import logger, TAKING_QUIZ, END, MAIN_MENU, SHOWING_RESULTS
from utils.helpers import safe_send_message, safe_edit_message_text, remove_job_if_exists

# +++ MODIFICATION: Import DB_MANAGER directly +++
from database.manager import DB_MANAGER
# +++++++++++++++++++++++++++++++++++++++++++++++

MIN_OPTIONS_PER_QUESTION = 2

class QuizLogic:
    ARABIC_CHOICE_LETTERS = ["أ", "ب", "ج", "د"]

    def __init__(self, user_id, chat_id, questions, quiz_name,
                 quiz_type_for_db_log, quiz_scope_id, total_questions_for_db_log,
                 time_limit_per_question, quiz_instance_id_for_logging):
        
        self.user_id = user_id
        self.chat_id = chat_id
        self.questions_data = questions if questions is not None else []
        self.quiz_name = quiz_name if quiz_name else "اختبار غير مسمى"
        
        self.quiz_type_for_db = quiz_type_for_db_log
        self.quiz_scope_id_for_db = quiz_scope_id 
        self.total_questions_for_db = total_questions_for_db_log

        self.question_time_limit = time_limit_per_question
        self.quiz_id = quiz_instance_id_for_logging 
        
        # +++ MODIFICATION: Use imported DB_MANAGER +++
        self.db_manager = DB_MANAGER
        # +++++++++++++++++++++++++++++++++++++++++++
        
        self.current_question_index = 0
        self.score = 0
        self.answers = [] 
        self.question_start_time = None
        self.quiz_actual_start_time_dt = None
        self.last_question_message_id = None
        self.last_question_is_image = False
        self.active = False
        self.db_quiz_session_id = None

        if not self.db_manager:
            # This check might still be relevant if DB_MANAGER itself could be None after import (e.g., if its own init fails)
            logger.critical(f"[QuizLogic {self.quiz_id}] CRITICAL: Imported DB_MANAGER is None or not initialized! Database operations will fail.")
        
        self.total_questions = len(self.questions_data)
        if self.total_questions != self.total_questions_for_db:
             logger.warning(f"[QuizLogic {self.quiz_id}] Mismatch: total_questions_for_db ({self.total_questions_for_db}) vs actual len(questions_data) ({self.total_questions}). Using actual len for quiz flow, but total_questions_for_db for initial DB log.")

        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized. User: {self.user_id}, Chat: {self.chat_id}, QuizName: 	'{self.quiz_name}	', DBQuizType: {self.quiz_type_for_db}, DBScopeID: {self.quiz_scope_id_for_db}, NumQsForDB: {self.total_questions_for_db}, ActualNumQs: {self.total_questions}. DB Manager Present: {bool(self.db_manager)}")

    async def start_quiz(self, bot: Bot, context: CallbackContext, update: Update) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] start_quiz called for user {self.user_id}, chat {self.chat_id}")
        self.active = True 
        self.quiz_actual_start_time_dt = datetime.now(timezone.utc)
        self.total_questions = len(self.questions_data)

        if self.db_manager:
            try:
                self.db_quiz_session_id = self.db_manager.start_quiz_session_and_get_id(
                    user_id=self.user_id,
                    quiz_type=self.quiz_type_for_db, 
                    quiz_scope_id=self.quiz_scope_id_for_db,
                    quiz_name=self.quiz_name,
                    total_questions=self.total_questions_for_db, 
                    start_time=self.quiz_actual_start_time_dt 
                )
                if self.db_quiz_session_id:
                    logger.info(f"[QuizLogic {self.quiz_id}] Quiz session started and logged to DB with session_uuid: {self.db_quiz_session_id}")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to log quiz start to DB (db_manager.start_quiz_session_and_get_id returned None). Quiz stats might be incomplete.")
            except Exception as e:
                logger.error(f"[QuizLogic {self.quiz_id}] Exception while logging quiz start to DB: {e}", exc_info=True)
                self.db_quiz_session_id = None
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
        
        return await self.send_question(bot, context, update)
    
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
            if len(button_text_str.encode(	'utf-8	')) > 60:
                temp_bytes = button_text_str.encode(	'utf-8	')[:57]
                button_text_str = temp_bytes.decode(	'utf-8	', 	'ignore	') + "..."
            callback_data = f"ans_{self.quiz_id}_{self.current_question_index}_{option_id}"
            keyboard.append([InlineKeyboardButton(text=button_text_str, callback_data=callback_data)])
        return InlineKeyboardMarkup(keyboard)

    async def send_question(self, bot: Bot, context: CallbackContext, update: Update = None):
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] send_question: inactive. User {self.user_id}. Aborting.")
            return END 

        while self.current_question_index < self.total_questions:
            current_question_data = self.questions_data[self.current_question_index]
            q_id_log = current_question_data.get(	'question_id	', f	'q_idx_{self.current_question_index}	')
            options = current_question_data.get("options", [])

            if len(options) < MIN_OPTIONS_PER_QUESTION:
                logger.warning(f"[QuizLogic {self.quiz_id}] Question {q_id_log} (idx {self.current_question_index}) has only {len(options)} options (min: {MIN_OPTIONS_PER_QUESTION}). Skipping.")
                self.answers.append({
                    "question_id": q_id_log,
                    "question_text": current_question_data.get("question_text", "سؤال غير صالح (خيارات قليلة)"),
                    "chosen_option_id": None,
                    "chosen_option_text": "تم تخطي السؤال (خيارات غير كافية)",
                    "correct_option_id": None, 
                    "correct_option_text": self._get_correct_option_text_robust(current_question_data, for_skip=True),
                    "is_correct": False,
                    "time_taken": -998, 
                    "status": "skipped_auto"
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
                        current_option_proc[	'is_image_option	'] = True
                        current_option_proc[	'image_option_display_label	'] = display_label 
                        option_image_counter += 1 
                        await asyncio.sleep(0.3) 
                    except Exception as e_img_opt:
                        logger.error(f"[QuizLogic {self.quiz_id}] Failed to send image option {i} (URL: {option_text_original}), q_id {q_id_log}: {e_img_opt}", exc_info=True)
                        current_option_proc[	'is_image_option	'] = False
                        current_option_proc[	'image_option_display_label	'] = None 
                else:
                    current_option_proc[	'is_image_option	'] = False 
                    current_option_proc[	'image_option_display_label	'] = None
                processed_options.append(current_option_proc)
            
            current_question_data[	'options	'] = processed_options 
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
            self.last_question_is_image = False

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
                        continue
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
                     continue
            
            if sent_message:
                self.last_question_message_id = sent_message.message_id
                if context and hasattr(context, 	'user_data	'):
                     context.user_data[f"last_quiz_interaction_message_id_{self.chat_id}"] = sent_message.message_id
                self.question_start_time = time.time()
                if self.question_time_limit > 0:
                    timer_job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
                    remove_job_if_exists(timer_job_name, context)
                    context.job_queue.run_once(
                        self.question_timeout_auto_skip, 
                        self.question_time_limit, 
                        chat_id=self.chat_id, 
                        name=timer_job_name,
                        data={ 	'quiz_id	': self.quiz_id, 	'question_index_at_schedule	': self.current_question_index, 	'message_id_to_edit	': sent_message.message_id, 	'is_photo_question	': self.last_question_is_image}
                    )
                    logger.info(f"[QuizLogic {self.quiz_id}] Timer job 	'{timer_job_name}	' scheduled for {self.question_time_limit}s for q_idx {self.current_question_index}")
                return TAKING_QUIZ # Wait for user's answer
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to send question {q_id_log} (idx {self.current_question_index}) after all attempts. Skipping.")
                self.answers.append({
                    "question_id": q_id_log,
                    "question_text": question_text_display,
                    "chosen_option_id": None,
                    "chosen_option_text": "خطأ فادح في إرسال السؤال",
                    "correct_option_id": None,
                    "correct_option_text": self._get_correct_option_text_robust(current_question_data, for_skip=True),
                    "is_correct": False,
                    "time_taken": -996, 
                    "status": "error_sending_final"
                })
                self.current_question_index += 1
                await asyncio.sleep(0.1) # Small delay before trying next question or ending
                # No return here, loop will continue to next question or exit if all skipped

        # If loop finishes, all questions are processed or skipped
        logger.info(f"[QuizLogic {self.quiz_id}] All questions processed or skipped. Proceeding to show results. User {self.user_id}")
        return await self.show_results(context.bot, context, update) # Pass update if available

    async def handle_answer(self, update: Update, context: CallbackContext) -> int:
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] handle_answer: inactive. User {self.user_id}. Aborting.")
            # Try to send a message to the user that the quiz is no longer active
            try:
                await safe_send_message(context.bot, chat_id=self.chat_id, text="انتهى هذا الاختبار أو لم يعد صالحاً.")
            except Exception as e:
                logger.error(f"[QuizLogic {self.quiz_id}] Error sending inactive quiz message: {e}")
            return END 

        query = update.callback_query
        await query.answer() # Acknowledge callback
        
        time_taken = -1 # Default if question_start_time is None
        if self.question_start_time:
            time_taken = round(time.time() - self.question_start_time, 2)

        # --- Cancel Timer --- 
        timer_job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        logger.debug(f"[QuizLogic {self.quiz_id}] Timer job 	'{timer_job_name}	' removed for q_idx {self.current_question_index} due to answer.")

        # --- Parse Callback Data --- 
        # Expected format: "ans_{quiz_id}_{question_index}_{option_id}"
        try:
            _, quiz_id_from_cb, q_idx_from_cb_str, chosen_option_id_from_cb = query.data.split(	'_	', 3)
            q_idx_from_cb = int(q_idx_from_cb_str)
        except ValueError as ve:
            logger.error(f"[QuizLogic {self.quiz_id}] Invalid callback_data format: {query.data}. Error: {ve}")
            # Potentially resend question or end quiz if data is corrupt
            await safe_send_message(context.bot, self.chat_id, "حدث خطأ في معالجة اختيارك. قد تحتاج لإعادة بدأ الاختبار.")
            return END # Or resend current question if possible

        # --- Validate Callback Data --- 
        if quiz_id_from_cb != self.quiz_id or q_idx_from_cb != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Mismatched callback data. Expected quiz_id 	'{self.quiz_id}	' (got 	'{quiz_id_from_cb}	'), q_idx 	'{self.current_question_index}	' (got 	'{q_idx_from_cb}	'). Ignoring old/invalid callback: {query.data}")
            # Do not proceed with this answer, it's for a previous question or different quiz instance
            # User might have clicked an old button. We don't resend the current question here as it might be confusing.
            # We simply ignore this outdated callback.
            return TAKING_QUIZ # Stay in the current state, waiting for a valid answer to the current question

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get(	'question_id	', f	'q_idx_{self.current_question_index}	')
        chosen_option_text = "غير متوفر"
        correct_option_text = "غير متوفر"
        is_correct = False
        correct_option_id_internal = None

        # Find chosen option and correct option details
        found_chosen = False
        for option in current_question_data.get("options", []):
            option_id_internal = option.get("option_id")
            option_text_internal = option.get("option_text", "")
            is_image_opt_internal = option.get("is_image_option", False)
            image_label_internal = option.get("image_option_display_label", "")

            current_opt_display_text = image_label_internal if is_image_opt_internal else option_text_internal

            if str(option_id_internal) == str(chosen_option_id_from_cb):
                chosen_option_text = current_opt_display_text
                found_chosen = True
            
            if option.get("is_correct") is True: # Assuming API provides this
                correct_option_text = current_opt_display_text
                correct_option_id_internal = option_id_internal
                if str(option_id_internal) == str(chosen_option_id_from_cb):
                    is_correct = True
        
        if not found_chosen:
            logger.warning(f"[QuizLogic {self.quiz_id}] Chosen option_id 	'{chosen_option_id_from_cb}	' not found in current question	's options (q_id {q_id_log}). This might indicate an issue with option_id generation or callback data.")
            # Fallback, consider it an invalid choice for this question
            chosen_option_text = f"اختيار غير صالح ({chosen_option_id_from_cb})"
            is_correct = False

        if correct_option_id_internal is None:
            logger.error(f"[QuizLogic {self.quiz_id}] No correct option found (is_correct: True) in question data for q_id {q_id_log}. Cannot determine correctness.")
            # This is a data integrity issue with the question itself.
            # We will record the answer but correctness might be wrongly false.

        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": chosen_option_id_from_cb,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id_internal,
            "correct_option_text": correct_option_text,
            "is_correct": is_correct,
            "time_taken": time_taken,
            "status": "answered"
        })

        if is_correct:
            self.score += 1

        # --- Edit previous question message to remove buttons and show feedback (optional) ---
        # For now, we will just remove buttons to prevent re-answering.
        # Feedback can be shown in the final results or immediately.
        message_id_to_edit = query.message.message_id
        original_question_text_for_edit = query.message.text or query.message.caption # Handle both text and photo questions
        
        feedback_text = " (تم اختيار: " + chosen_option_text + ")"
        if original_question_text_for_edit:
            new_text_for_edited_message = original_question_text_for_edit + feedback_text
        else: # Should not happen if message_id_to_edit is valid
            new_text_for_edited_message = "تم تسجيل إجابتك." + feedback_text

        try:
            if query.message.photo: # If it was a photo question
                await safe_edit_message_text(context.bot, chat_id=self.chat_id, message_id=message_id_to_edit, text=new_text_for_edited_message, parse_mode="HTML", reply_markup=None, is_caption=True)
            else: # Text question
                await safe_edit_message_text(context.bot, chat_id=self.chat_id, message_id=message_id_to_edit, text=new_text_for_edited_message, parse_mode="HTML", reply_markup=None)
            logger.debug(f"[QuizLogic {self.quiz_id}] Edited message {message_id_to_edit} for q_idx {self.current_question_index} to remove keyboard.")
        except telegram.error.BadRequest as e:
            if "message is not modified" in str(e).lower():
                logger.debug(f"[QuizLogic {self.quiz_id}] Message {message_id_to_edit} was not modified (already edited or no change). Error: {e}")
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] Error editing message {message_id_to_edit} for q_idx {self.current_question_index}: {e}", exc_info=True)
        except Exception as e_edit:
            logger.error(f"[QuizLogic {self.quiz_id}] Unexpected error editing message {message_id_to_edit} for q_idx {self.current_question_index}: {e_edit}", exc_info=True)

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            return await self.send_question(context.bot, context, update) # Pass update for potential message_id
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] All questions answered. Proceeding to show results. User {self.user_id}")
            return await self.show_results(context.bot, context, update)

    async def question_timeout_auto_skip(self, context: CallbackContext):
        job_data = context.job.data
        quiz_id_from_job = job_data.get(	'quiz_id	')
        question_index_from_job = job_data.get(	'question_index_at_schedule	')
        message_id_to_edit = job_data.get(	'message_id_to_edit	')
        is_photo_question = job_data.get(	'is_photo_question	', False)

        logger.info(f"[QuizLogic {self.quiz_id}] Timeout job triggered for quiz_id: {quiz_id_from_job}, q_idx: {question_index_from_job}")

        # --- Validate Job Data and Quiz State ---
        if not self.active or quiz_id_from_job != self.quiz_id or question_index_from_job != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Timeout job for quiz_id 	'{quiz_id_from_job}	'/q_idx 	'{question_index_from_job}	' is stale or quiz inactive. Current quiz_id: 	'{self.quiz_id}	', q_idx: 	'{self.current_question_index}	', active: {self.active}. Ignoring.")
            return

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get(	'question_id	', f	'q_idx_{self.current_question_index}	')

        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": None, # Or try to get it if available
            "correct_option_text": self._get_correct_option_text_robust(current_question_data, for_skip=True),
            "is_correct": False,
            "time_taken": self.question_time_limit, # Or slightly more to indicate timeout
            "status": "timeout"
        })

        # --- Edit message to indicate timeout and remove keyboard ---
        if message_id_to_edit:
            timeout_feedback = "\n\n⏳ *انتهى وقت هذا السؤال.*	"
            try:
                # Fetch the original message text/caption to append to it
                original_message = await context.bot.edit_message_reply_markup(chat_id=self.chat_id, message_id=message_id_to_edit, reply_markup=None) # First remove keyboard
                
                current_text_or_caption = ""
                if is_photo_question and original_message.caption:
                    current_text_or_caption = original_message.caption
                elif not is_photo_question and original_message.text:
                    current_text_or_caption = original_message.text
                else: # Fallback if text/caption is somehow None after edit_reply_markup
                    current_text_or_caption = "السؤال السابق"

                new_text_with_timeout = current_text_or_caption + timeout_feedback

                if is_photo_question:
                    await safe_edit_message_text(context.bot, chat_id=self.chat_id, message_id=message_id_to_edit, text=new_text_with_timeout, parse_mode="MarkdownV2", reply_markup=None, is_caption=True)
                else:
                    await safe_edit_message_text(context.bot, chat_id=self.chat_id, message_id=message_id_to_edit, text=new_text_with_timeout, parse_mode="MarkdownV2", reply_markup=None)
                logger.info(f"[QuizLogic {self.quiz_id}] Edited message {message_id_to_edit} for q_idx {self.current_question_index} to show timeout.")
            except telegram.error.BadRequest as e:
                if "message is not modified" in str(e).lower() or "message to edit not found" in str(e).lower():
                    logger.warning(f"[QuizLogic {self.quiz_id}] Message {message_id_to_edit} not modified or not found on timeout for q_idx {self.current_question_index}. Error: {e}")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Error editing message {message_id_to_edit} on timeout for q_idx {self.current_question_index}: {e}", exc_info=True)
            except Exception as e_timeout_edit:
                 logger.error(f"[QuizLogic {self.quiz_id}] Unexpected error editing message {message_id_to_edit} on timeout for q_idx {self.current_question_index}: {e_timeout_edit}", exc_info=True)
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] No message_id_to_edit provided in timeout job for q_idx {self.current_question_index}. Cannot update message.")

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await self.send_question(context.bot, context) # No update object here
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] All questions processed (last one timed out). Proceeding to show results. User {self.user_id}")
            await self.show_results(context.bot, context) # No update object here

    def _get_correct_option_text_robust(self, question_data, for_skip=False):
        """Safely gets the text/label of the correct option."""
        try:
            for option in question_data.get("options", []):
                if option.get("is_correct") is True:
                    if option.get("is_image_option") and option.get("image_option_display_label"):
                        return option.get("image_option_display_label")
                    elif option.get("option_text"):
                        return option.get("option_text")
                    else:
                        return "الخيار الصحيح (بدون نص/تسمية)"
            return "غير محدد (لا يوجد خيار صحيح)" if not for_skip else "-"
        except Exception as e:
            logger.error(f"[QuizLogic {self.quiz_id}] Error in _get_correct_option_text_robust: {e}")
            return "خطأ في تحديد الإجابة الصحيحة" if not for_skip else "-"

    async def show_results(self, bot: Bot, context: CallbackContext, update: Update = None) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] show_results called for user {self.user_id}. Score: {self.score}/{self.total_questions}")
        self.active = False # Quiz is no longer active for answering
        quiz_end_time_dt = datetime.now(timezone.utc)

        # --- Cancel any lingering timer (should not happen if logic is correct, but good for safety) ---
        # This would be for the *next* question if one was about to be sent, or the current if it was mid-send_question
        timer_job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        logger.debug(f"[QuizLogic {self.quiz_id}] Ensured timer job 	'{timer_job_name}	' (for potential q_idx {self.current_question_index}) is removed at show_results.")

        results_summary = f"🏁 <b>نتائج اختبار: {self.quiz_name}</b> 🏁\n\n"
        results_summary += f"✨ نتيجتك: {self.score} من {self.total_questions} ✨\n"
        percentage = (self.score / self.total_questions * 100) if self.total_questions > 0 else 0
        results_summary += f"🎯 النسبة المئوية: {percentage:.2f}%\n"
        
        # Calculate duration
        duration_seconds = (quiz_end_time_dt - self.quiz_actual_start_time_dt).total_seconds() if self.quiz_actual_start_time_dt else -1
        if duration_seconds >= 0:
            results_summary += f"⏱️ الوقت المستغرق: {int(duration_seconds // 60)} دقيقة و {int(duration_seconds % 60)} ثانية\n"
        else:
            results_summary += f"⏱️ الوقت المستغرق: غير متوفر\n"
        results_summary += "\n📝 <b>تفاصيل إجاباتك:</b>\n"

        detailed_answers_parts = []
        for i, ans in enumerate(self.answers):
            q_text_short = ans.get("question_text", "سؤال غير متوفر")[:50] + ("..." if len(ans.get("question_text", "")) > 50 else "")
            chosen_opt = ans.get("chosen_option_text", "لم يتم الاختيار")
            correct_opt = ans.get("correct_option_text", "-")
            status_emoji = "✅" if ans.get("is_correct") else ("❌" if ans.get("status") == "answered" else ("⏳" if ans.get("status") == "timeout" else "⚠️"))
            
            part = f"\n{status_emoji} <b>سؤال {i+1}:</b> \"{q_text_short}\"
            part += f"\n   - اخترت: {chosen_opt}"
            if not ans.get("is_correct") and ans.get("status") != "skipped_auto" and ans.get("status") != "error_sending" and ans.get("status") != "error_sending_final": # Don	 show correct if skipped due to bad data
                part += f"\n   - الصحيح: {correct_opt}"
            
            # Add explanation if available and answer was wrong or if always showing explanations
            # For now, let's assume we only show explanation if the question data has it and answer was not correct
            question_data_for_explanation = next((q for q_idx, q in enumerate(self.questions_data) if q_idx == i), None) # Find original question data
            if question_data_for_explanation:
                explanation = question_data_for_explanation.get("explanation")
                if explanation and (not ans.get("is_correct") or True): # Modify `or True` to control when to show
                    part += f"\n   - 💡 التوضيح: {explanation}"
            detailed_answers_parts.append(part)

        # --- Log results to DB ---
        if self.db_manager and self.db_quiz_session_id:
            try:
                # Convert answers to JSON string for DB storage
                answers_json = json.dumps(self.answers, ensure_ascii=False) 
                self.db_manager.end_quiz_session(
                    quiz_session_uuid=self.db_quiz_session_id,
                    end_time=quiz_end_time_dt,
                    score=self.score,
                    total_answered=len([a for a in self.answers if a.get("status")=="answered"]),
                    answers_details_json=answers_json,
                    duration_seconds=int(duration_seconds) if duration_seconds >=0 else None
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Quiz results for session {self.db_quiz_session_id} logged to DB successfully.")
            except Exception as e:
                logger.error(f"[QuizLogic {self.quiz_id}] Exception while logging quiz results to DB for session {self.db_quiz_session_id}: {e}", exc_info=True)
        elif not self.db_manager:
             logger.warning(f"[QuizLogic {self.quiz_id}] db_manager is not available. Cannot log quiz results to DB.")
        elif not self.db_quiz_session_id:
             logger.warning(f"[QuizLogic {self.quiz_id}] db_quiz_session_id is None. Cannot log quiz results to DB (likely quiz start failed to log).")

        # --- Send results to user --- 
        # Determine the message_id to edit or if we need to send a new message
        message_to_edit_id = None
        if context and hasattr(context, 'user_data') and f"last_quiz_interaction_message_id_{self.chat_id}" in context.user_data:
            message_to_edit_id = context.user_data.pop(f"last_quiz_interaction_message_id_{self.chat_id}", None)
            logger.debug(f"[QuizLogic {self.quiz_id}] Retrieved message_id {message_to_edit_id} from user_data for editing results.")
        elif update and update.callback_query and update.callback_query.message:
            # Fallback if the specific user_data key wasn't set, use the last callback query's message
            message_to_edit_id = update.callback_query.message.message_id
            logger.debug(f"[QuizLogic {self.quiz_id}] Using callback_query message_id {message_to_edit_id} as fallback for editing results.")
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] No message_id found in user_data or update to edit for results. Will send as new message.")

        # Split results if too long
        MAX_MSG_LENGTH = 4000 # Telegram's limit is 4096, leave some buffer
        current_message_content = results_summary
        final_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 عرض الإحصائيات", callback_data="stats_menu_entry")],
            [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")]
        ])

        for part_detail in detailed_answers_parts:
            if len(current_message_content.encode(	'utf-8	')) + len(part_detail.encode(	'utf-8	')) > MAX_MSG_LENGTH - 100: # Buffer for keyboard etc.
                # Send current part
                if message_to_edit_id:
                    await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_to_edit_id, text=current_message_content, parse_mode="HTML", reply_markup=None) # No keyboard on intermediate parts
                    message_to_edit_id = None # Subsequent parts must be new messages
                else:
                    await safe_send_message(bot, chat_id=self.chat_id, text=current_message_content, parse_mode="HTML", reply_markup=None)
                current_message_content = "(تابع تفاصيل إجاباتك...)\n" + part_detail
                await asyncio.sleep(0.2) # Small delay between messages
            else:
                current_message_content += part_detail
        
        # Send the last part (or the only part if it all fits)
        try:
            if message_to_edit_id:
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_to_edit_id, text=current_message_content, reply_markup=final_keyboard, parse_mode="HTML")
                logger.info(f"[QuizLogic {self.quiz_id}] Edited message {message_to_edit_id} with final results.")
            else:
                await safe_send_message(bot, chat_id=self.chat_id, text=current_message_content, reply_markup=final_keyboard, parse_mode="HTML")
                logger.info(f"[QuizLogic {self.quiz_id}] Sent final results as a new message.")
        except Exception as e_send_results:
            logger.error(f"[QuizLogic {self.quiz_id}] Error sending/editing final results message: {e_send_results}", exc_info=True)
            # Fallback: try sending a very simple message if the detailed one failed
            try:
                simple_fallback_text = f"انتهى الاختبار! نتيجتك: {self.score}/{self.total_questions}. حدث خطأ في عرض التفاصيل."
                await safe_send_message(bot, chat_id=self.chat_id, text=simple_fallback_text, reply_markup=final_keyboard)
            except Exception as e_fallback_simple:
                logger.error(f"[QuizLogic {self.quiz_id}] Error sending even simple fallback results: {e_fallback_simple}")

        await self.cleanup_quiz_data(context, self.user_id, "quiz_completed_normally")
        return SHOWING_RESULTS # Or END, depending on desired flow after results

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.info(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user {user_id}. Reason: {reason}")
        self.active = False
        # Remove quiz instance from user_data if it was stored there
        if context and hasattr(context, 'user_data') and f"quiz_logic_instance_{user_id}" in context.user_data:
            del context.user_data[f"quiz_logic_instance_{user_id}"]
            logger.debug(f"[QuizLogic {self.quiz_id}] Removed quiz_logic_instance_{user_id} from user_data.")
        
        # Remove any associated job (should have been done, but as a safeguard)
        # This needs to know the current_question_index at the time of cleanup, which might be tricky
        # For now, we assume timers are handled at answer/timeout/end_quiz points.
        # If a quiz is abruptly ended (e.g., by /cancel), specific timer cleanup might be missed if not handled by the cancel command itself.

        # Reset internal state for safety, though the instance should be discarded
        self.questions_data = []
        self.answers = []
        self.current_question_index = 0
        self.score = 0
        logger.info(f"[QuizLogic {self.quiz_id}] Cleanup complete for user {user_id}.")

# Example of how this might be used by the quiz handler (handlers/quiz.py)
# This is conceptual and would be in the actual handler file.

# async def start_actual_quiz(update: Update, context: CallbackContext):
#     user_id = update.effective_user.id
#     chat_id = update.effective_chat.id
#     quiz_type = context.user_data.get("selected_quiz_type")
#     num_questions = context.user_data.get("selected_num_questions")
#     quiz_name = "Some Quiz Name" # Derived from quiz_type or other logic
#     quiz_scope_id = context.user_data.get("selected_scope_id") # e.g., course_id, unit_id

#     # 1. Fetch questions using api_client.py
#     # This is a placeholder for actual API call logic
#     raw_api_questions = await some_api_fetching_function(quiz_type, num_questions, quiz_scope_id)
#     if not raw_api_questions or raw_api_questions == "TIMEOUT" or not isinstance(raw_api_questions, list):
#         await update.callback_query.edit_message_text("فشل في جلب الأسئلة من الـ API. يرجى المحاولة لاحقاً.")
#         return END

#     # 2. Transform questions
#     transformed_questions = []
#     for raw_q in raw_api_questions:
#         transformed_q = transform_api_question(raw_q) # from api_client.py
#         if transformed_q:
#             transformed_questions.append(transformed_q)
#         else:
#             logger.warning(f"Failed to transform question: {raw_q.get('id')}")
    
#     if not transformed_questions:
#         await update.callback_query.edit_message_text("فشل في معالجة الأسئلة بعد جلبها. يرجى المحاولة لاحقاً.")
#         return END

#     # 3. Create QuizLogic instance (NO db_manager passed here anymore)
#     quiz_instance_id = str(uuid.uuid4())
#     quiz_logic = QuizLogic(
#         user_id=user_id,
#         chat_id=chat_id,
#         questions=transformed_questions,
#         quiz_name=quiz_name,
#         quiz_type_for_db_log=quiz_type,
#         quiz_scope_id=quiz_scope_id,
#         total_questions_for_db_log=len(transformed_questions), # Or num_questions if API guarantees it
#         time_limit_per_question=context.user_data.get("time_limit_per_question", 30), # Default 30s
#         quiz_instance_id_for_logging=quiz_instance_id
#     )
#     context.user_data[f"quiz_logic_instance_{user_id}"] = quiz_logic
#     return await quiz_logic.start_quiz(context.bot, context, update)

