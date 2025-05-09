"""Manages the logic for conducting a quiz, including sending questions, handling answers, and calculating results."""
# handlers/quiz_logic.py (DBMANAGER_PASS_FIX)

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
            else:
                full_question_text = header + question_text_display
                try:
                    sent_message = await safe_send_message(bot, chat_id=self.chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                except Exception as e:
                     logger.error(f"[QuizLogic {self.quiz_id}] Error sending text question q_id {q_id_log}: {e}.", exc_info=True)

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
                    logger.error(f"[QuizLogic {self.quiz_id}] context.job_queue is None. Cannot schedule timeout for question {self.current_question_index}.")
                return TAKING_QUIZ # Wait for answer or timeout
            else: # Failed to send question
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to send question {self.current_question_index} (q_id {q_id_log}). Skipping.")
                self.answers.append({
                    "question_id": q_id_log,
                    "question_text": current_question_data.get("question_text", "سؤال غير صالح (فشل الإرسال)"),
                    "chosen_option_id": None,
                    "chosen_option_text": "تم تخطي السؤال (فشل الإرسال)",
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

    async def handle_answer(self, bot: Bot, context: CallbackContext, update: Update, answer_data_parts: list) -> int:
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
            logger.error(f"[QuizLogic {self.quiz_id}] Invalid answer callback data format: {answer_data_parts}. Error: {e_parse}")
            await safe_send_message(bot, chat_id=self.chat_id, text="حدث خطأ في معالجة إجابتك. يرجى المحاولة لاحقاً.")
            return TAKING_QUIZ # Stay in current state or decide to end

        if answered_quiz_id != self.quiz_id:
            logger.warning(f"[QuizLogic {self.quiz_id}] Mismatched quiz_id in answer. Expected {self.quiz_id}, got {answered_quiz_id}. Ignoring.")
            # User might be clicking on an old quiz message. Acknowledge and do nothing or inform.
            try:
                await update.callback_query.answer(text="هذا الاختبار قديم أو غير نشط.", show_alert=True)
            except Exception as e_ans_old:
                logger.debug(f"[QuizLogic {self.quiz_id}] Failed to send 'old quiz' answer to callback: {e_ans_old}")
            return TAKING_QUIZ 

        if answered_question_index != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Answer for wrong question index. Expected {self.current_question_index}, got {answered_question_index}. Ignoring.")
            try:
                await update.callback_query.answer(text="لقد أجبت على هذا السؤال بالفعل أو أنه سؤال مختلف.", show_alert=False)
            except Exception as e_ans_wrong_idx:
                logger.debug(f"[QuizLogic {self.quiz_id}] Failed to send 'wrong index' answer to callback: {e_ans_wrong_idx}")
            return TAKING_QUIZ

        # Remove timer for the current question
        timer_job_name = f"qtimer_{self.user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        correct_option_id = str(current_question_data.get("correct_option_id"))
        is_correct = (chosen_option_id == correct_option_id)
        time_taken = time.time() - self.question_start_time if self.question_start_time else -1

        chosen_option_text_val = "(خيار مصور)" # Default for image options
        for opt in current_question_data.get("options", []):
            if str(opt.get("option_id")) == chosen_option_id:
                if not opt.get("is_image_option"):
                    chosen_option_text_val = opt.get("option_text", "نص الخيار المختار غير متوفر")
                break
        
        correct_option_text_val = self._get_correct_option_text_robust(current_question_data)

        if is_correct:
            self.score += 1
            feedback_text = f"✅ إجابة صحيحة!"
        else:
            feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة كانت: {correct_option_text_val}"
        
        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text"), # Can be None for image questions
            "chosen_option_id": chosen_option_id,
            "chosen_option_text": chosen_option_text_val,
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text_val,
            "is_correct": is_correct,
            "time_taken": time_taken,
            "status": "answered" # ADDED status
        })

        # Edit the question message to show feedback and remove keyboard
        if update.callback_query and update.callback_query.message:
            message_to_edit = update.callback_query.message
            context.bot_data.pop(f"msg_cache_{self.chat_id}_{message_to_edit.message_id}", None) # Clean cache if used
            
            question_text_display = current_question_data.get("question_text", "السؤال السابق")
            if not isinstance(question_text_display, str) or not question_text_display.strip():
                if current_question_data.get("image_url"):
                    question_text_display = "السؤال المصور السابق"
                else:
                    question_text_display = "السؤال السابق"

            header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n{question_text_display}\n\nاخترت: {chosen_option_text_val}\n{feedback_text}"
            try:
                if self.last_question_is_image: # If the question itself was an image
                    await bot.edit_message_caption(chat_id=self.chat_id, message_id=message_to_edit.message_id, caption=header, reply_markup=None, parse_mode='HTML')
                else:
                    await bot.edit_message_text(text=header, chat_id=self.chat_id, message_id=message_to_edit.message_id, reply_markup=None, parse_mode='HTML')
            except telegram.error.BadRequest as e:
                if "message is not modified" in str(e).lower():
                    logger.debug(f"[QuizLogic {self.quiz_id}] Message not modified, skipping edit. MsgId: {message_to_edit.message_id}")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Error editing message: {e}. MsgId: {message_to_edit.message_id}", exc_info=True)
                    await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text) # Send feedback as new message
            except Exception as e_edit_ans:
                 logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message: {e_edit_ans}. MsgId: {message_to_edit.message_id}", exc_info=True)
                 await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text) # Send feedback as new message
        else:
            await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text)

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await asyncio.sleep(1.5) # Pause before next question
            return await self.send_question(bot, context)
        else:
            await asyncio.sleep(1) # Pause before showing results
            return await self.show_results(bot, context)

    async def handle_timeout(self, bot: Bot, context: CallbackContext, update_for_message_edit: Update, question_index: int, user_id_from_job: int, message_id_from_job: int, question_was_image: bool):
        if not self.active or question_index != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] handle_timeout: inactive or mismatched index (q_idx:{question_index}, current:{self.current_question_index}). User {self.user_id}. Ignoring job.")
            return TAKING_QUIZ

        logger.info(f"[QuizLogic {self.quiz_id}] Timeout for question {self.current_question_index} for user {self.user_id}")
        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        correct_option_id = str(current_question_data.get("correct_option_id"))
        correct_option_text_val = self._get_correct_option_text_robust(current_question_data)
        feedback_text = f"⏰ انتهى الوقت! الإجابة الصحيحة كانت: {correct_option_text_val}"

        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text_val,
            "is_correct": False,
            "time_taken": self.question_time_limit, 
            "status": "timeout" # ADDED status
        })

        if message_id_from_job:
            try:
                context.bot_data.pop(f"msg_cache_{self.chat_id}_{message_id_from_job}", None) # Clean cache if used
                question_text_display = current_question_data.get("question_text", "السؤال السابق")
                if not isinstance(question_text_display, str) or not question_text_display.strip():
                    if current_question_data.get("image_url"):
                        question_text_display = "السؤال المصور السابق"
                    else:
                        question_text_display = "السؤال السابق"

                header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions} (انتهى الوقت):</b>\n{question_text_display}\n\n{feedback_text}"

                if question_was_image:
                    await bot.edit_message_caption(chat_id=self.chat_id, message_id=message_id_from_job, caption=header, reply_markup=None, parse_mode='HTML')
                else:
                    await bot.edit_message_text(text=header, chat_id=self.chat_id, message_id=message_id_from_job, reply_markup=None, parse_mode='HTML')
            except telegram.error.BadRequest as e:
                if "message is not modified" in str(e).lower():
                    logger.debug(f"[QuizLogic {self.quiz_id}] Message not modified, skipping edit for timeout. MsgId: {message_id_from_job}")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Error editing message for timeout: {e}. MsgId: {message_id_from_job}", exc_info=True)
                    await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text) # Send feedback as new message
            except Exception as e_edit:
                logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message for timeout: {e_edit}. MsgId: {message_id_from_job}", exc_info=True)
                await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text) # Send feedback as new message
        else:
            await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text)

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await asyncio.sleep(1.5) # Pause before next question
            return await self.send_question(bot, context)
        else:
            await asyncio.sleep(1)
            return await self.show_results(bot, context)

    async def _save_results_to_db(self, final_score: int, score_percentage: float, end_time_dt: datetime):
        logger.info(f"[QuizLogic {self.quiz_id}] Attempting to save results to DB for user {self.user_id}. Session UUID: {self.db_quiz_session_id}")

        if not self.db_manager:
            logger.error(f"[QuizLogic {self.quiz_id}] db_manager is not available. Cannot save quiz results to DB.")
            return

        if not self.db_quiz_session_id:
            logger.error(f"[QuizLogic {self.quiz_id}] db_quiz_session_id is None. Cannot update quiz results in DB. Quiz might not have been logged at start.")
            return

        recalculated_correct = 0
        recalculated_wrong = 0
        recalculated_skipped = 0 

        for ans_detail in self.answers:
            if ans_detail.get("status") == "skipped_auto" or ans_detail.get("status") == "skipped_error" or ans_detail.get("status") == "timeout":
                recalculated_skipped += 1
            elif ans_detail.get("is_correct"):
                recalculated_correct += 1
            else: 
                recalculated_wrong += 1
        
        # Ensure total_questions_for_db is used if there's a discrepancy, or log it.
        # The DB schema expects total_questions which was logged at the start.
        # The sum of C/W/S should ideally match total_questions_for_db.
        if (recalculated_correct + recalculated_wrong + recalculated_skipped) != self.total_questions_for_db:
             logger.warning(f"[QuizLogic {self.quiz_id}] Discrepancy in answer counts for DB save. "
                           f"DB Total: {self.total_questions_for_db}, Recalculated (C/W/S): {recalculated_correct}/{recalculated_wrong}/{recalculated_skipped} from {len(self.answers)} answers. Using recalculated for DB fields.")

        time_taken_seconds_val = None
        if self.quiz_actual_start_time_dt and end_time_dt:
            time_taken_seconds_val = int((end_time_dt - self.quiz_actual_start_time_dt).total_seconds())

        try:
            success = self.db_manager.save_quiz_result(
                quiz_id_uuid=self.db_quiz_session_id,
                user_id=self.user_id,
                correct_count=recalculated_correct, 
                wrong_count=recalculated_wrong,    
                skipped_count=recalculated_skipped, 
                score_percentage_calculated=score_percentage, 
                start_time_original=self.quiz_actual_start_time_dt,
                end_time=end_time_dt, 
                answers_details_list=self.answers, 
                quiz_type_for_log=self.quiz_type_for_db 
            )
            if success:
                logger.info(f"[QuizLogic {self.quiz_id}] Successfully saved/updated quiz results to DB for session {self.db_quiz_session_id}.")
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to save/update quiz results to DB for session {self.db_quiz_session_id} (db_manager.save_quiz_result returned False/None).")
        except Exception as e:
            logger.error(f"[QuizLogic {self.quiz_id}] Exception while saving quiz results to DB: {e}", exc_info=True)

    async def show_results(self, bot: Bot, context: CallbackContext):
        logger.info(f"[QuizLogic {self.quiz_id}] Quiz ended for user {self.user_id}. Calculating and showing results.")
        self.active = False 
        end_time_dt = datetime.now(timezone.utc)

        # Remove any pending timer for the last question, if any (should be already handled by answer/timeout)
        timer_job_name = f"qtimer_{self.user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index -1 }" # -1 as index already incremented
        remove_job_if_exists(timer_job_name, context)

        total_answered_or_timedout = len(self.answers)
        # self.total_questions is the number of questions presented in the quiz flow.
        # self.total_questions_for_db was the number intended at the start.

        if self.total_questions == 0: # Should use self.total_questions_for_db if that's the reference for percentage
            score_percentage = 0.0
            logger.warning(f"[QuizLogic {self.quiz_id}] Total questions is 0 at show_results. Percentage set to 0.")
        else:
            # Percentage should be based on the number of questions the quiz was *supposed* to have, i.e., self.total_questions_for_db
            # Or, if based on actual questions *attempted/processed*, use self.total_questions (len(self.questions_data))
            # Let's use self.total_questions (actual questions in flow) for percentage calculation for user display
            # but ensure DB save uses counts that align with total_questions_for_db
            score_percentage = (self.score / self.total_questions) * 100 if self.total_questions > 0 else 0.0

        summary_parts = [f"🎉 انتهى الاختبار: {self.quiz_name}! 🎉"]
        summary_parts.append(f"النتيجة: {self.score} من {self.total_questions} ({score_percentage:.2f}%) صحيح") # Hindi word "सही" (sahī) means correct/true.
        
        time_taken_val = None
        if self.quiz_actual_start_time_dt:
            time_taken_delta = end_time_dt - self.quiz_actual_start_time_dt
            time_taken_val = int(time_taken_delta.total_seconds())
            summary_parts.append(f"الوقت المستغرق: {time_taken_val // 60} دقيقة و {time_taken_val % 60} ثانية")
        
        # Save results to DB before cleaning up user_data specific to this quiz instance
        await self._save_results_to_db(self.score, score_percentage, end_time_dt)

        detailed_answers_summary = []
        for i, ans in enumerate(self.answers):
            q_text = ans.get("question_text") 
            if q_text is None: 
                q_text = "(سؤال مصور أو بدون نص)"

            chosen_option_text_val = ans.get("chosen_option_text")
            # Determine chosen_display based on status first
            if ans.get("status") == "timeout":
                chosen_display = "انتهى الوقت"
            elif ans.get("status", "").startswith("skipped"):
                # Use the specific skip message if available, otherwise a generic one
                chosen_display = chosen_option_text_val if chosen_option_text_val and ("تخطي" in chosen_option_text_val or "Skipped" in chosen_option_text_val) else "تم تخطيه"
            elif chosen_option_text_val is None:
                chosen_display = "(خيار مصور)" 
            elif not str(chosen_option_text_val).strip():
                 chosen_display = "(إجابة فارغة)"
            else:
                chosen_display = str(chosen_option_text_val)

            correct_option_text_val = ans.get("correct_option_text")
            if correct_option_text_val is None:
                correct_display = "(خيار مصور أو غير محدد)"
            elif not str(correct_option_text_val).strip(): 
                 correct_display = "(إجابة صحيحة فارغة/غير محددة)"
            else:
                correct_display = str(correct_option_text_val)
            
            status_icon = "✅" if ans.get("is_correct") else "❌"
            if ans.get("status") == "timeout": status_icon = "⏰"
            elif ans.get("status", "").startswith("skipped"): status_icon = "⏭️"
            
            # Now q_text is guaranteed to be a string.
            max_q_len = 70
            display_q_text = q_text if len(q_text) <= max_q_len else q_text[:max_q_len-3] + "..."
            
            # Truncate display_chosen and display_correct as well
            max_opt_len = 50 
            display_chosen_final = chosen_display if len(chosen_display) <= max_opt_len else chosen_display[:max_opt_len-3] + "..."
            display_correct_final = correct_display if len(correct_display) <= max_opt_len else correct_display[:max_opt_len-3] + "..."

            detailed_answers_summary.append(f"{status_icon} {i+1}. {display_q_text}\n   اخترت: {display_chosen_final} | الصحيحة: {display_correct_final}")

        if detailed_answers_summary:
            summary_parts.append("\n📝 ملخص الإجابات:")
            summary_parts.extend(detailed_answers_summary)
        
        full_summary = "\n".join(summary_parts)
        if len(full_summary.encode('utf-8')) > 4000: # Check byte length for Telegram limit (4096 bytes)
            # Simple truncation strategy: take a portion of summary_parts
            # This needs a more sophisticated way to truncate to respect UTF-8 character boundaries
            # For now, a simpler character-based truncation for the string itself
            max_char_limit = 3800 # Leave some room
            if len(full_summary) > max_char_limit:
                full_summary = full_summary[:max_char_limit] + "\n... (الملخص طويل جداً لعرضه بالكامل)"
            logger.warning(f"[QuizLogic {self.quiz_id}] Quiz summary potentially too long, truncated to approx {max_char_limit} chars.")

        keyboard_buttons = [
            [InlineKeyboardButton("📊 عرض إحصائياتي", callback_data="quiz_show_my_stats")],
            [InlineKeyboardButton("🔁 ابدأ اختباراً جديداً", callback_data="start_quiz")], # Corrected callback_data to match common.py
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard_buttons)
        
        edited_successfully = False
        last_interaction_msg_id_key = f"last_quiz_interaction_message_id_{self.chat_id}"
        if context.user_data.get(last_interaction_msg_id_key):
            last_interaction_msg_id = context.user_data.pop(last_interaction_msg_id_key)
            try:
                await bot.edit_message_text(text=full_summary, chat_id=self.chat_id, message_id=last_interaction_msg_id, reply_markup=reply_markup, parse_mode='HTML')
                edited_successfully = True
            except telegram.error.BadRequest as e_edit_last_interaction:
                if "message to edit not found" in str(e_edit_last_interaction).lower() or \
                   "message can't be edited" in str(e_edit_last_interaction).lower() or \
                   "message is not modified" in str(e_edit_last_interaction).lower():
                    logger.debug(f"[QuizLogic {self.quiz_id}] Non-critical error editing last quiz interaction message ({last_interaction_msg_id}) for results: {e_edit_last_interaction}. Sending new message.")
                else:
                    logger.warning(f"[QuizLogic {self.quiz_id}] Could not edit last quiz interaction message ({last_interaction_msg_id}) for results: {e_edit_last_interaction}. Sending new message.")
            except Exception as e_generic_edit:
                 logger.warning(f"[QuizLogic {self.quiz_id}] Generic error editing last quiz interaction message ({last_interaction_msg_id}) for results: {e_generic_edit}. Sending new message.")

        if not edited_successfully:
            await safe_send_message(bot, chat_id=self.chat_id, text=full_summary, reply_markup=reply_markup, parse_mode='HTML')

        await self.cleanup_quiz_data(context, self.user_id, "quiz_completed")
        return SHOWING_RESULTS 

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.info(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user {user_id}. Reason: {reason}")
        self.active = False
        if self.quiz_id in context.user_data:
             if context.user_data[self.quiz_id] == self: 
                 context.user_data.pop(self.quiz_id, None)
                 logger.debug(f"[QuizLogic {self.quiz_id}] Removed self from context.user_data[{self.quiz_id}].")
             else:
                 logger.warning(f"[QuizLogic {self.quiz_id}] Found an object in context.user_data[{self.quiz_id}] but it's not this instance. Not removing.")
        
        for i in range(self.total_questions + 2): # Iterate a bit beyond to be safe, including index -1 potentially used
            timer_job_name = f"qtimer_{self.user_id}_{self.chat_id}_{self.quiz_id}_{i-1}" # Covering potential -1 index from current_question_index -1
            remove_job_if_exists(timer_job_name, context)
        logger.debug(f"[QuizLogic {self.quiz_id}] Attempted removal of related timer jobs.")

    async def end_quiz(self, bot: Bot, context: CallbackContext, update: Update, manual_end: bool = False, reason_suffix: str = "manual", called_from_fallback:bool=False) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] end_quiz called. Manual: {manual_end}, Reason: {reason_suffix}")
        self.active = False
        end_time_dt = datetime.now(timezone.utc)

        timer_job_name = f"qtimer_{self.user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)

        if manual_end:
            if self.answers: 
                score_percentage = (self.score / self.total_questions) * 100 if self.total_questions > 0 else 0.0
                await self._save_results_to_db(self.score, score_percentage, end_time_dt)
            else:
                logger.info(f"[QuizLogic {self.quiz_id}] Manual end with no answers recorded. Not saving to DB.")
            
            end_message_text = "تم إنهاء الاختبار يدوياً."
            if called_from_fallback:
                pass
            elif update and update.callback_query and update.callback_query.message:
                try:
                    await bot.edit_message_text(text=end_message_text, chat_id=self.chat_id, message_id=update.callback_query.message.message_id, reply_markup=None)
                except Exception as e_edit_manual_end:
                    logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message on manual end: {e_edit_manual_end}. Sending new message.")
                    await safe_send_message(bot, chat_id=self.chat_id, text=end_message_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]])) # Add main menu button
            else: # No callback_query (e.g. command end)
                await safe_send_message(bot, chat_id=self.chat_id, text=end_message_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]])) # Add main menu button
        
        await self.cleanup_quiz_data(context, self.user_id, f"ended_{reason_suffix}")
        # If ended manually, and not from fallback, transition to main menu state or a specific end state.
        # If called from fallback, the fallback handler will return its state.
        if called_from_fallback:
            return END # Or whatever state fallback expects
        return MAIN_MENU 

    def _get_correct_option_text_robust(self, question_data, for_skip=False):
        """Safely gets the text of the correct option, handling missing keys or image options."""
        correct_option_id = str(question_data.get("correct_option_id"))
        options = question_data.get("options", [])
        for opt in options:
            if str(opt.get("option_id")) == correct_option_id:
                if opt.get("is_image_option"):
                    return opt.get("image_option_display_label", "(الخيار الصحيح صورة)")
                return opt.get("option_text", "(نص الخيار الصحيح غير متوفر)")
        if for_skip:
             return "(غير محدد بسبب تخطي السؤال)"
        return "(الخيار الصحيح غير محدد أو غير موجود)"

async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    quiz_id = job_data.get("quiz_id")
    question_idx = job_data.get("question_index")
    user_id = job_data.get("user_id")
    chat_id = job_data.get("chat_id")
    message_id = job_data.get("message_id")
    question_was_image = job_data.get("question_was_image", False)

    logger.debug(f"Timeout job triggered for quiz {quiz_id}, q_idx {question_idx}, user {user_id}")

    # Create a dummy Update object if needed for message editing context
    # This is a bit of a hack. Ideally, the bot instance and necessary IDs are passed directly.
    # For now, we assume the bot instance is available via context.bot.
    dummy_update = Update(update_id=0) # Minimal update object
    # If message_id is available, we can try to construct a message-like object for editing
    # However, bot.edit_message_text/caption only needs chat_id and message_id.

    if quiz_id and user_id is not None and chat_id is not None and question_idx is not None and message_id is not None:
        quiz_logic_instance = context.user_data.get(quiz_id)
        if quiz_logic_instance and isinstance(quiz_logic_instance, QuizLogic) and quiz_logic_instance.active:
            if quiz_logic_instance.user_id == user_id and quiz_logic_instance.chat_id == chat_id:
                # Pass the bot instance from context.bot
                await quiz_logic_instance.handle_timeout(context.bot, context, dummy_update, question_idx, user_id, message_id, question_was_image)
            else:
                logger.warning(f"Timeout job: User/Chat ID mismatch for quiz {quiz_id}. Job: u{user_id}/c{chat_id}, Instance: u{quiz_logic_instance.user_id}/c{quiz_logic_instance.chat_id}")
        else:
            logger.warning(f"Timeout job: Quiz instance {quiz_id} not found, not active, or not QuizLogic type for user {user_id}.")
    else:
        logger.error(f"Timeout job: Missing critical data in job_data: {job_data}")

