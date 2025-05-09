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
                    logger.error(f"[QuizLogic {self.quiz_id}] JobQueue not available. Timer not set for user {self.user_id}.")
                return TAKING_QUIZ 
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to send question (q_id: {q_id_log}). Skipping.")
                self.answers.append({
                    "question_id": q_id_log,
                    "question_text": question_text_display,
                    "chosen_option_id": None,
                    "chosen_option_text": "خطأ في إرسال السؤال",
                    "correct_option_id": None,
                    "correct_option_text": self._get_correct_option_text_robust(current_question_data, for_skip=True),
                    "is_correct": False,
                    "time_taken": -997, 
                    "status": "skipped_error" # ADDED status
                })
                self.current_question_index += 1
        
        logger.info(f"[QuizLogic {self.quiz_id}] No more valid questions to send or quiz ended. User {self.user_id}. Showing results.")
        return await self.show_results(bot, context)

    def _get_correct_option_text_robust(self, current_question_data, for_skip=False):
        correct_option_id_from_data = str(current_question_data.get("correct_option_id"))
        options_for_current_q = current_question_data.get("options", [])
        retrieved_correct_option_text = "نص الإجابة الصحيحة غير متوفر"
        found_correct_option_details = False
        if not correct_option_id_from_data or correct_option_id_from_data == 'None':
            logger.warning(f"[QuizLogic {self.quiz_id}] Correct option ID is missing or None in question data for q_id 	'{current_question_data.get('question_id')}'")
            return "لم يتم تحديد إجابة صحيحة للسؤال" if not for_skip else "غير محدد"
        for opt_detail in options_for_current_q:
            if str(opt_detail.get("option_id")) == correct_option_id_from_data:
                if opt_detail.get("is_image_option"):
                    img_label = opt_detail.get('image_option_display_label')
                    if img_label and img_label.strip():
                        retrieved_correct_option_text = f"صورة ({img_label})"
                    else:
                        retrieved_correct_option_text = f"صورة (معرف: {correct_option_id_from_data})"
                else:
                    text_val = opt_detail.get("option_text")
                    if isinstance(text_val, str) and text_val.strip():
                        retrieved_correct_option_text = text_val
                    else:
                        retrieved_correct_option_text = f"خيار نصي (معرف: {correct_option_id_from_data})"
                found_correct_option_details = True
                break
        if not found_correct_option_details:
            logger.error(f"[QuizLogic {self.quiz_id}] Critical: Correct option ID '{correct_option_id_from_data}' not found in processed options for q_id '{current_question_data.get('question_id')}'. Options: {options_for_current_q}")
            return "خطأ في تحديد نص الإجابة الصحيحة" if not for_skip else "غير محدد"
        return retrieved_correct_option_text

    async def handle_answer(self, bot: Bot, context: CallbackContext, update_for_message_edit: Update, question_index: int, chosen_option_id: int, user_id_from_handler: int):
        if not self.active or question_index != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] handle_answer: inactive or mismatched index (q_idx:{question_index}, current:{self.current_question_index}). User {self.user_id}. Ignoring.")
            if update_for_message_edit and update_for_message_edit.callback_query:
                 await update_for_message_edit.callback_query.answer("تم الرد على هذا السؤال بالفعل أو انتهى وقته.")
            return TAKING_QUIZ 

        time_taken = time.time() - self.question_start_time
        timer_job_name = f"qtimer_{self.user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        correct_option_id = str(current_question_data.get("correct_option_id"))
        is_correct = (str(chosen_option_id) == correct_option_id)

        chosen_option_text = "نص الخيار المختار غير متوفر"
        options_for_current_q = current_question_data.get("options", [])
        for opt_detail in options_for_current_q:
            if str(opt_detail.get("option_id")) == str(chosen_option_id):
                if opt_detail.get("is_image_option"):
                    img_label = opt_detail.get('image_option_display_label')
                    chosen_option_text = f"صورة ({img_label})" if img_label and img_label.strip() else f"صورة (معرف: {chosen_option_id})"
                else:
                    text_val = opt_detail.get("option_text")
                    chosen_option_text = text_val if isinstance(text_val, str) and text_val.strip() else f"خيار نصي (معرف: {chosen_option_id})"
                break
        
        correct_option_text_val = self._get_correct_option_text_robust(current_question_data)

        if is_correct:
            self.score += 1
            feedback_text = "✅ إجابة صحيحة!"
        else:
            feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة: {correct_option_text_val}"
        
        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": str(chosen_option_id),
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text_val,
            "is_correct": is_correct,
            "time_taken": round(time_taken, 2),
            "status": "answered" # ADDED status
        })

        if self.last_question_message_id:
            try:
                original_message = context.bot_data.pop(f"msg_cache_{self.chat_id}_{self.last_question_message_id}", None)
                new_caption = None
                new_text = None
                
                question_text_display = current_question_data.get("question_text", "السؤال السابق")
                if not isinstance(question_text_display, str) or not question_text_display.strip():
                    if current_question_data.get("image_url"):
                        question_text_display = "السؤال المصور السابق"
                    else:
                        question_text_display = "السؤال السابق"
                
                header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions} (تم الرد):</b>\n{question_text_display}\n\n<i>اخترت: {chosen_option_text}</i>\n{feedback_text}"

                if self.last_question_is_image and original_message and original_message.photo:
                    new_caption = header
                    await bot.edit_message_caption(chat_id=self.chat_id, message_id=self.last_question_message_id, caption=new_caption, reply_markup=None, parse_mode='HTML')
                elif original_message and original_message.text:
                    new_text = header
                    await bot.edit_message_text(text=new_text, chat_id=self.chat_id, message_id=self.last_question_message_id, reply_markup=None, parse_mode='HTML')
                else: # Fallback if original message not found or type mismatch
                    await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text) 

            except telegram.error.BadRequest as e:
                if "message is not modified" in str(e).lower():
                    logger.debug(f"[QuizLogic {self.quiz_id}] Message not modified, skipping edit for feedback. MsgId: {self.last_question_message_id}")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Error editing message for feedback: {e}. MsgId: {self.last_question_message_id}", exc_info=True)
                    await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text) # Send feedback as new message
            except Exception as e_edit:
                logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message for feedback: {e_edit}. MsgId: {self.last_question_message_id}", exc_info=True)
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
        summary_parts.append(f"النتيجة: {self.score} من {self.total_questions} ({score_percentage:.2f}%) सही") # Placeholder for Hindi word
        
        time_taken_val = None
        if self.quiz_actual_start_time_dt:
            time_taken_delta = end_time_dt - self.quiz_actual_start_time_dt
            time_taken_val = int(time_taken_delta.total_seconds())
            summary_parts.append(f"الوقت المستغرق: {time_taken_val // 60} دقيقة و {time_taken_val % 60} ثانية")
        
        # Save results to DB before cleaning up user_data specific to this quiz instance
        await self._save_results_to_db(self.score, score_percentage, end_time_dt)

        detailed_answers_summary = []
        for i, ans in enumerate(self.answers):
            q_text = ans.get("question_text", f"سؤال {i+1}")
            chosen = ans.get("chosen_option_text", "لم يتم الاختيار")
            correct_ans_text = ans.get("correct_option_text", "-")
            status_icon = "✅" if ans.get("is_correct") else "❌"
            if ans.get("status") == "timeout": status_icon = "⏰"
            elif ans.get("status", "").startswith("skipped"): status_icon = "⏭️"
            
            # Truncate long question texts for summary
            max_q_len = 70
            display_q_text = q_text if len(q_text) <= max_q_len else q_text[:max_q_len-3] + "..."
            
            detailed_answers_summary.append(f"{status_icon} {i+1}. {display_q_text}\n   اخترت: {chosen} | الصحيحة: {correct_ans_text}")

        if detailed_answers_summary:
            summary_parts.append("\n📝 ملخص الإجابات:")
            summary_parts.extend(detailed_answers_summary)
        
        full_summary = "\n".join(summary_parts)
        if len(full_summary) > 4000: # Telegram message limit is 4096
            full_summary = "\n".join(summary_parts[:(len(summary_parts)//2)]) + "\n... (الملخص طويل جداً لعرضه بالكامل)"
            logger.warning(f"[QuizLogic {self.quiz_id}] Quiz summary too long, truncated.")

        keyboard_buttons = [
            [InlineKeyboardButton("📊 عرض إحصائياتي", callback_data="quiz_show_my_stats")],
            [InlineKeyboardButton("🔁 ابدأ اختباراً جديداً", callback_data="quiz_menu_entry")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard_buttons)
        
        # Try to edit the last quiz message if it was a question, otherwise send new.
        # This logic might be tricky if the last interaction was an image option sent separately.
        # For simplicity, always send a new message for results.
        # However, the user experience might be better if the last question message is edited.
        # Let's try to edit the callback_query message that triggered the end of the quiz (if available)
        # or send a new one.
        
        edited_successfully = False
        if context.user_data.get(f"last_quiz_interaction_message_id_{self.chat_id}"):
            last_interaction_msg_id = context.user_data.pop(f"last_quiz_interaction_message_id_{self.chat_id}")
            try:
                await bot.edit_message_text(text=full_summary, chat_id=self.chat_id, message_id=last_interaction_msg_id, reply_markup=reply_markup, parse_mode='HTML')
                edited_successfully = True
            except Exception as e_edit_last_interaction:
                logger.warning(f"[QuizLogic {self.quiz_id}] Could not edit last quiz interaction message ({last_interaction_msg_id}) for results: {e_edit_last_interaction}")

        if not edited_successfully:
            await safe_send_message(bot, chat_id=self.chat_id, text=full_summary, reply_markup=reply_markup, parse_mode='HTML')

        await self.cleanup_quiz_data(context, self.user_id, "quiz_completed")
        return SHOWING_RESULTS # Transition to a state that handles the results menu

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.info(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user {user_id}. Reason: {reason}")
        self.active = False
        # Specific quiz instance data is within self. Remove from context.user_data if this instance was stored there by quiz_instance_id.
        if self.quiz_id in context.user_data:
             if context.user_data[self.quiz_id] == self: # Ensure it's the same instance
                 context.user_data.pop(self.quiz_id, None)
                 logger.debug(f"[QuizLogic {self.quiz_id}] Removed self from context.user_data[{self.quiz_id}].")
             else:
                 logger.warning(f"[QuizLogic {self.quiz_id}] Found an object in context.user_data[{self.quiz_id}] but it's not this instance. Not removing.")
        
        # Remove any associated job queue timers that might be lingering
        # This requires a more robust way to find all jobs for this quiz_id if multiple questions could have timers
        # For now, assuming the current_question_index based timer is the main one.
        for i in range(self.total_questions + 1): # Iterate a bit beyond to be safe
            timer_job_name = f"qtimer_{self.user_id}_{self.chat_id}_{self.quiz_id}_{i}"
            remove_job_if_exists(timer_job_name, context)
        logger.debug(f"[QuizLogic {self.quiz_id}] Attempted removal of related timer jobs.")

    async def end_quiz(self, bot: Bot, context: CallbackContext, update: Update, manual_end: bool = False, reason_suffix: str = "manual", called_from_fallback:bool=False) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] end_quiz called. Manual: {manual_end}, Reason: {reason_suffix}")
        self.active = False
        end_time_dt = datetime.now(timezone.utc)

        # Remove any pending timer
        timer_job_name = f"qtimer_{self.user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)

        if manual_end:
            # Log partial results if any questions were answered
            if self.answers: # Only save if there's something to save
                score_percentage = (self.score / self.total_questions) * 100 if self.total_questions > 0 else 0.0
                await self._save_results_to_db(self.score, score_percentage, end_time_dt)
            else:
                logger.info(f"[QuizLogic {self.quiz_id}] Manual end with no answers recorded. Not saving to DB.")
            
            end_message_text = "تم إنهاء الاختبار يدوياً."
            if called_from_fallback:
                # No message needed if called from fallback, as fallback handler sends its own message
                pass
            elif update and update.callback_query and update.callback_query.message:
                try:
                    await bot.edit_message_text(text=end_message_text, chat_id=self.chat_id, message_id=update.callback_query.message.message_id, reply_markup=None)
                except Exception as e_edit_manual_end:
                    logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message on manual end: {e_edit_manual_end}. Sending new.")
                    await safe_send_message(bot, chat_id=self.chat_id, text=end_message_text)
            else:
                 await safe_send_message(bot, chat_id=self.chat_id, text=end_message_text)
        
        await self.cleanup_quiz_data(context, self.user_id, f"ended_{reason_suffix}")
        # If not called from fallback, which handles its own state transition, decide where to go.
        # Typically, manual end should lead to a clear state, like main menu or allowing new quiz start.
        # The ConversationHandler will manage the state transition based on what this returns.
        # Returning END is usually safe for manual termination by user action.
        return END # Or MAIN_MENU if that's more appropriate for the flow

# This wrapper is defined in quiz_logic.py and used by quiz.py for job_queue
async def question_timeout_callback_wrapper(context: CallbackContext):
    job = context.job
    bot = context.bot
    
    quiz_id = job.data.get("quiz_id")
    question_index = job.data.get("question_index")
    user_id = job.data.get("user_id")
    chat_id = job.data.get("chat_id")
    message_id = job.data.get("message_id") # Message ID of the question
    question_was_image = job.data.get("question_was_image", False)

    logger.info(f"Timeout job triggered for quiz {quiz_id}, q_idx {question_index}, user {user_id}, chat {chat_id}")

    # Retrieve the QuizLogic instance from context.user_data using quiz_id
    # quiz_id here is the quiz_instance_id_for_logging
    quiz_instance = context.user_data.get(quiz_id) 

    if quiz_instance and isinstance(quiz_instance, QuizLogic) and quiz_instance.active:
        # Pass a dummy Update object or None if update_for_message_edit is not critical for timeout message editing
        # However, to edit the specific message, we need its ID, which we have.
        # The QuizLogic.handle_timeout can use bot.edit_message_text/caption directly with message_id.
        # We don't have an `update` object here from a user interaction.
        await quiz_instance.handle_timeout(bot, context, update_for_message_edit=None, question_index=question_index, user_id_from_job=user_id, message_id_from_job=message_id, question_was_image=question_was_image)
    else:
        logger.warning(f"Timeout job: Quiz instance {quiz_id} not found, not active, or not QuizLogic type for user {user_id}. Quiz may have already ended.")


