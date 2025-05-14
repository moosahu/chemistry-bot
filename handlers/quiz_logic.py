"""Manages the logic for conducting a quiz, including sending questions, handling answers, and calculating results."""
# handlers/quiz_logic.py (Modified to import DB_MANAGER directly)
# v2: Fixes for filter_id in DB session and NoneType error in show_results
# v3: Enhanced support for image questions and image options
# vMANUS_FIX_RESULTS_BUTTONS: Changed callback_data for results screen buttons

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
from utils.helpers import safe_send_message, safe_edit_message_text, safe_edit_message_caption, remove_job_if_exists

# +++ MODIFICATION: Import DB_MANAGER directly +++
from database.manager import DB_MANAGER
# +++++++++++++++++++++++++++++++++++++++++++++++

MIN_OPTIONS_PER_QUESTION = 2
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif")

def is_image_url(url_string: str) -> bool:
    if not isinstance(url_string, str):
        return False
    return (url_string.startswith("http://") or url_string.startswith("https://")) and \
           any(url_string.lower().endswith(ext) for ext in IMAGE_EXTENSIONS)

class QuizLogic:
    ARABIC_CHOICE_LETTERS = ["أ", "ب", "ج", "د", "هـ", "و", "ز", "ح"]

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
        
        self.db_manager = DB_MANAGER
        
        self.current_question_index = 0
        self.score = 0
        self.answers = [] 
        self.question_start_time = None
        self.quiz_actual_start_time_dt = None
        self.last_question_message_id = None # ID of the main question text/image message
        self.sent_option_image_message_ids = [] # IDs of messages sent for image options
        self.active = False
        self.db_quiz_session_id = None

        if not self.db_manager:
            logger.critical(f"[QuizLogic {self.quiz_id}] CRITICAL: Imported DB_MANAGER is None! DB ops will fail.")
        
        self.total_questions = len(self.questions_data)
        if self.total_questions != self.total_questions_for_db:
             logger.warning(f"[QuizLogic {self.quiz_id}] Mismatch: total_questions_for_db ({self.total_questions_for_db}) vs actual len(questions_data) ({self.total_questions}).")

        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized. User: {self.user_id}, QuizName: 	'{self.quiz_name}	', ActualNumQs: {self.total_questions}.")

    async def start_quiz(self, bot: Bot, context: CallbackContext, update: Update) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] start_quiz called for user {self.user_id}")
        self.active = True 
        self.quiz_actual_start_time_dt = datetime.now(timezone.utc)
        self.total_questions = len(self.questions_data)

        if self.db_manager:
            try:
                scope_id_for_db_call = self.quiz_scope_id_for_db
                if isinstance(scope_id_for_db_call, str) and scope_id_for_db_call.lower() == "all":
                    scope_id_for_db_call = None 
                elif isinstance(scope_id_for_db_call, str):
                    try: scope_id_for_db_call = int(scope_id_for_db_call)
                    except ValueError: 
                        logger.error(f"[QuizLogic {self.quiz_id}] Invalid quiz_scope_id_for_db 	'{self.quiz_scope_id_for_db}	'. Setting to None.")
                        scope_id_for_db_call = None
                
                self.db_quiz_session_id = self.db_manager.start_quiz_session_and_get_id(
                    user_id=self.user_id, quiz_type=self.quiz_type_for_db, 
                    quiz_scope_id=scope_id_for_db_call, quiz_name=self.quiz_name,
                    total_questions=self.total_questions_for_db, start_time=self.quiz_actual_start_time_dt,
                    score=0, initial_percentage=0.0, initial_time_taken_seconds=0) # Added initial score, percentage and time_taken_seconds
                if self.db_quiz_session_id: logger.info(f"[QuizLogic {self.quiz_id}] Quiz session logged to DB: {self.db_quiz_session_id}")
                else: logger.error(f"[QuizLogic {self.quiz_id}] Failed to log quiz start to DB.")
            except Exception as e: logger.error(f"[QuizLogic {self.quiz_id}] DB exception on quiz start: {e}", exc_info=True)
        else: logger.warning(f"[QuizLogic {self.quiz_id}] db_manager unavailable. Cannot log quiz start.")

        if not self.questions_data or self.total_questions == 0:
            logger.warning(f"[QuizLogic {self.quiz_id}] No questions. Ending quiz.")
            msg_id = update.callback_query.message.message_id if update and update.callback_query else None
            text = "عذراً، لا توجد أسئلة لبدء هذا الاختبار."
            kbd = InlineKeyboardMarkup([[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]])
            if msg_id: await safe_edit_message_text(bot, self.chat_id, msg_id, text, kbd)
            else: await safe_send_message(bot, self.chat_id, text, kbd)
            await self.cleanup_quiz_data(context, self.user_id, "no_questions_on_start", preserve_current_logic_in_userdata=False) 
            return END 
        
        return await self.send_question(bot, context, update)
    
    def _create_display_options_and_keyboard(self, options_from_api: list):
        keyboard_buttons = []
        displayable_options = [] # For storing how options were presented (text or label for image)
        option_image_counter = 0

        for i, option_data in enumerate(options_from_api):
            option_id = option_data.get("option_id") # Should be present from api_client transform
            option_content = option_data.get("option_text") # This is text OR image URL
            
            button_text_for_keyboard = ""
            display_text_for_answer_log = ""
            is_image_option_flag = False

            if is_image_url(option_content):
                is_image_option_flag = True
                display_label = self.ARABIC_CHOICE_LETTERS[option_image_counter] if option_image_counter < len(self.ARABIC_CHOICE_LETTERS) else f"صورة {option_image_counter + 1}"
                button_text_for_keyboard = f"اختر الخيار المصور: {display_label}"
                display_text_for_answer_log = f"صورة ({display_label})"
                option_image_counter += 1
            elif isinstance(option_content, str):
                button_text_for_keyboard = option_content
                display_text_for_answer_log = option_content
            else:
                logger.warning(f"[QuizLogic {self.quiz_id}] Option content is not string/URL: {option_content}. Using placeholder.")
                button_text_for_keyboard = f"خيار {i+1} (بيانات غير صالحة)"
                display_text_for_answer_log = button_text_for_keyboard
            
            # Truncate button text if too long for Telegram
            button_text_final = button_text_for_keyboard.strip()
            if not button_text_final: button_text_final = f"خيار {i+1}"
            if len(button_text_final.encode('utf-8')) > 60:
                temp_bytes = button_text_final.encode('utf-8')[:57]
                button_text_final = temp_bytes.decode('utf-8', 'ignore') + "..."
            
            callback_data = f"answer_{self.quiz_id}_{self.current_question_index}_{option_id}"
            keyboard_buttons.append([InlineKeyboardButton(text=button_text_final, callback_data=callback_data)])
            
            displayable_options.append({
                "option_id": option_id,
                "original_content": option_content, # Text or URL
                "is_image_option": is_image_option_flag,
                "display_text_for_log": display_text_for_answer_log,
                "is_correct": option_data.get("is_correct", False)
            })
            
        return InlineKeyboardMarkup(keyboard_buttons), displayable_options

    async def send_question(self, bot: Bot, context: CallbackContext, update: Update = None):
        if not self.active: return END 

        # Clear previous option image messages
        for msg_id in self.sent_option_image_message_ids:
            try: await bot.delete_message(chat_id=self.chat_id, message_id=msg_id)
            except Exception: pass # Ignore if already deleted or error
        self.sent_option_image_message_ids = []

        while self.current_question_index < self.total_questions:
            current_question_data = self.questions_data[self.current_question_index]
            q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
            api_options = current_question_data.get("options", [])

            if len(api_options) < MIN_OPTIONS_PER_QUESTION:
                logger.warning(f"[QuizLogic {self.quiz_id}] Q {q_id_log} (idx {self.current_question_index}) has {len(api_options)} opts. Skipping.")
                q_text_skip = current_question_data.get("question_text") or "سؤال غير صالح (خيارات قليلة)"
                self.answers.append({"question_id": q_id_log, "question_text": q_text_skip, "chosen_option_id": None, "chosen_option_text": "تم تخطي السؤال (خيارات غير كافية)", "correct_option_id": None, "correct_option_text": self._get_correct_option_display_text(current_question_data, for_skip=True), "is_correct": False, "time_taken": -998, "status": "skipped_auto"})
                self.current_question_index += 1
                continue 
            
            # Create keyboard and get displayable option details (handles image option labeling)
            options_keyboard, displayable_options_for_q = self._create_display_options_and_keyboard(api_options)
            # Store these processed options for use in handle_answer and timeout
            current_question_data['_displayable_options'] = displayable_options_for_q

            # Send image options first if any
            option_image_counter_for_labeling = 0 # Reset for this question's options
            for option_detail in displayable_options_for_q:
                if option_detail["is_image_option"]:
                    try:
                        display_label = self.ARABIC_CHOICE_LETTERS[option_image_counter_for_labeling] if option_image_counter_for_labeling < len(self.ARABIC_CHOICE_LETTERS) else f"صورة {option_image_counter_for_labeling + 1}"
                        sent_opt_img_msg = await bot.send_photo(chat_id=self.chat_id, photo=option_detail["original_content"], caption=f"الخيار: {display_label}")
                        self.sent_option_image_message_ids.append(sent_opt_img_msg.message_id)
                        option_image_counter_for_labeling += 1
                        await asyncio.sleep(0.2) # Small delay between image options
                    except Exception as e_img_opt:
                        logger.error(f"[QuizLogic {self.quiz_id}] Failed to send image option (URL: {option_detail['original_content']}), q_id {q_id_log}: {e_img_opt}")
            
            header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
            main_q_image_url = current_question_data.get("image_url")
            main_q_text_from_data = current_question_data.get("question_text") or ""
            main_q_text_from_data = str(main_q_text_from_data).strip()

            question_display_text = main_q_text_from_data
            if not main_q_text_from_data and main_q_image_url: question_display_text = "السؤال معروض في الصورة أعلاه."
            elif not main_q_text_from_data and not main_q_image_url: question_display_text = "نص السؤال غير متوفر حالياً."
            
            sent_main_q_message = None
            try:
                if main_q_image_url:
                    sent_main_q_message = await bot.send_photo(chat_id=self.chat_id, photo=main_q_image_url, caption=header + question_display_text, reply_markup=options_keyboard, parse_mode="HTML")
                else:
                    sent_main_q_message = await safe_send_message(bot, chat_id=self.chat_id, text=header + question_display_text, reply_markup=options_keyboard, parse_mode="HTML")
            except Exception as e_send_q:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to send main question q_id {q_id_log}: {e_send_q}", exc_info=True)
                q_text_err = main_q_text_from_data or "سؤال غير متوفر (خطأ إرسال)"
                self.answers.append({"question_id": q_id_log, "question_text": q_text_err, "chosen_option_id": None, "chosen_option_text": "خطأ في إرسال السؤال", "correct_option_id": None, "correct_option_text": self._get_correct_option_display_text(current_question_data, for_skip=True), "is_correct": False, "time_taken": -997, "status": "error_sending"})
                self.current_question_index += 1
                await asyncio.sleep(0.1)
                continue
            
            if sent_main_q_message:
                self.last_question_message_id = sent_main_q_message.message_id
                if context and hasattr(context, 'user_data'): context.user_data[f"last_quiz_interaction_message_id_{self.chat_id}"] = sent_main_q_message.message_id
                self.question_start_time = time.time()
                job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
                remove_job_if_exists(job_name, context)
                context.job_queue.run_once(self.question_timeout_callback, self.question_time_limit, 
                    data={"chat_id": self.chat_id, "user_id": self.user_id, "quiz_id": self.quiz_id, "question_index_at_timeout": self.current_question_index, "main_question_message_id": self.last_question_message_id, "option_image_ids": list(self.sent_option_image_message_ids)}, name=job_name)
                logger.info(f"[QuizLogic {self.quiz_id}] Timer set for Q{self.current_question_index}, job: {job_name}")
                return TAKING_QUIZ 
            else: # Should have been caught by exception block
                logger.error(f"[QuizLogic {self.quiz_id}] sent_main_q_message was None for q_idx {self.current_question_index}. Error in logic.")
                # Fallback to prevent infinite loop, though this indicates a deeper issue
                self.current_question_index += 1 
                if self.current_question_index >= self.total_questions: break # Exit loop
                continue # Try next question
        
        logger.info(f"[QuizLogic {self.quiz_id}] All questions processed/skipped. Showing results. User {self.user_id}")
        return await self.show_results(bot, context, update)

    async def handle_answer(self, update: Update, context: CallbackContext, answer_data: str) -> int:
        query = update.callback_query
        await query.answer()
        
        parts = answer_data.split("_")
        if len(parts) < 4: logger.warning(f"[QuizLogic {self.quiz_id}] Invalid answer callback: {answer_data}"); return TAKING_QUIZ

        ans_quiz_id, ans_q_idx_str = parts[1], parts[2]
        chosen_option_id_from_callback = "_".join(parts[3:])
        ans_q_idx = int(ans_q_idx_str)

        if not self.active or ans_quiz_id != self.quiz_id or ans_q_idx != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Stale/mismatched answer. Active:{self.active}({self.quiz_id} vs {ans_quiz_id}), Q_idx:{self.current_question_index} vs {ans_q_idx}. Ignoring.")
            # Do not change state, let current question timeout or be answered correctly.
            return TAKING_QUIZ 

        time_taken = time.time() - self.question_start_time
        job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        if remove_job_if_exists(job_name, context):
            logger.info(f"[QuizLogic {self.quiz_id}] Timer job 	'{job_name}	' removed after answer.")
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] Timer job 	'{job_name}	' not found or already removed when handling answer.")

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        
        chosen_option_text = "غير متوفر"
        correct_option_text = "غير متوفر"
        is_correct = False
        correct_option_id = None

        # Use the processed _displayable_options for consistency
        processed_options = current_question_data.get('_displayable_options', [])
        if not processed_options: # Fallback if _displayable_options somehow not set
            logger.error(f"[QuizLogic {self.quiz_id}] _displayable_options not found for Q{q_id_log}. This is an error.")
            # Attempt to reconstruct, but this indicates a flaw in send_question
            _, processed_options = self._create_display_options_and_keyboard(current_question_data.get("options", []))

        for opt in processed_options:
            if str(opt["option_id"]) == str(chosen_option_id_from_callback):
                chosen_option_text = opt["display_text_for_log"]
                is_correct = opt.get("is_correct", False)
            if opt.get("is_correct", False):
                correct_option_id = opt["option_id"]
                correct_option_text = opt["display_text_for_log"]
        
        if is_correct: self.score += 1

        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text") or (current_question_data.get("image_url") and "سؤال مصور") or "نص السؤال غير متوفر",
            "chosen_option_id": chosen_option_id_from_callback,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text,
            "is_correct": is_correct,
            "time_taken": time_taken,
            "status": "answered"
        })

        # Edit the question message to remove keyboard (indicate answered)
        if self.last_question_message_id:
            try:
                header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b> (تمت الإجابة)\n"
                q_text = current_question_data.get("question_text") or ""
                if current_question_data.get("image_url"):
                    await safe_edit_message_caption(query.bot, self.chat_id, self.last_question_message_id, caption=header + q_text, reply_markup=None, parse_mode="HTML")
                else:
                    await safe_edit_message_text(query.bot, self.chat_id, self.last_question_message_id, text=header + q_text, reply_markup=None, parse_mode="HTML")
            except telegram.error.BadRequest as e_edit:
                if "message is not modified" not in str(e_edit).lower():
                    logger.warning(f"[QuizLogic {self.quiz_id}] Error editing question message {self.last_question_message_id} after answer: {e_edit}")
            except Exception as e_gen_edit:
                 logger.warning(f"[QuizLogic {self.quiz_id}] General error editing question message {self.last_question_message_id}: {e_gen_edit}")

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            return await self.send_question(query.bot, context, update) # Pass update for consistency
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz finished. User {self.user_id}. Score: {self.score}/{self.total_questions}")
            return await self.show_results(query.bot, context, update)

    async def question_timeout_callback(self, context: CallbackContext):
        job_data = context.job.data
        chat_id = job_data["chat_id"]
        user_id = job_data["user_id"]
        quiz_id_from_job = job_data["quiz_id"]
        q_idx_at_timeout = job_data["question_index_at_timeout"]
        main_q_msg_id = job_data.get("main_question_message_id")
        option_img_ids = job_data.get("option_image_ids", [])

        logger.info(f"[QuizLogic {quiz_id_from_job}] Timeout for Q{q_idx_at_timeout}, user {user_id}")

        # Verify this timeout is for the current QuizLogic instance and question
        if not self.active or self.quiz_id != quiz_id_from_job or self.current_question_index != q_idx_at_timeout:
            logger.warning(f"[QuizLogic {self.quiz_id}] Stale timeout received for Q{q_idx_at_timeout} (current Q{self.current_question_index}, job_quiz_id {quiz_id_from_job}). Ignoring.")
            return

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        
        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text") or (current_question_data.get("image_url") and "سؤال مصور") or "نص السؤال غير متوفر",
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": self._get_correct_option_id(current_question_data),
            "correct_option_text": self._get_correct_option_display_text(current_question_data),
            "is_correct": False,
            "time_taken": self.question_time_limit, # Or -1 to indicate timeout
            "status": "timeout"
        })

        # Clean up the timed-out question's message (remove keyboard, indicate timeout)
        if main_q_msg_id:
            try:
                header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b> (انتهى الوقت)\n"
                q_text = current_question_data.get("question_text") or ""
                if current_question_data.get("image_url"):
                    await safe_edit_message_caption(context.bot, chat_id, main_q_msg_id, caption=header + q_text, reply_markup=None, parse_mode="HTML")
                else:
                    await safe_edit_message_text(context.bot, chat_id, main_q_msg_id, text=header + q_text, reply_markup=None, parse_mode="HTML")
            except telegram.error.BadRequest as e_edit_timeout:
                if "message is not modified" not in str(e_edit_timeout).lower():
                     logger.warning(f"[QuizLogic {self.quiz_id}] Error editing timed-out question message {main_q_msg_id}: {e_edit_timeout}")
            except Exception as e_gen_edit_timeout:
                 logger.warning(f"[QuizLogic {self.quiz_id}] General error editing timed-out question message {main_q_msg_id}: {e_gen_edit_timeout}")
        
        # Delete any image options sent for this question
        for opt_img_id in option_img_ids:
            try: await context.bot.delete_message(chat_id=chat_id, message_id=opt_img_id)
            except Exception: pass
        self.sent_option_image_message_ids = [] # Clear for next question

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await self.send_question(context.bot, context) # No update object here
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz finished after timeout on last Q. User {self.user_id}. Score: {self.score}/{self.total_questions}")
            await self.show_results(context.bot, context) # No update object here

    def _get_correct_option_id(self, question_data):
        for opt in question_data.get("options", []):
            if opt.get("is_correct"): return opt.get("option_id")
        return None

    def _get_correct_option_display_text(self, question_data, for_skip=False):
        # Use _displayable_options if available and not for skip, otherwise reconstruct for safety
        processed_options = []
        if not for_skip and '_displayable_options' in question_data:
            processed_options = question_data['_displayable_options']
        else: # Fallback or for skip where _displayable_options might not be relevant/set
            _, processed_options = self._create_display_options_and_keyboard(question_data.get("options", []))
            
        for opt in processed_options:
            if opt.get("is_correct"): return opt["display_text_for_log"]
        return "غير متوفرة"

    async def show_results(self, bot: Bot, context: CallbackContext, update: Update = None, timed_out_question_index: int = -1) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] show_results. Score: {self.score}/{self.total_questions}")
        
        # Ensure any pending timer for a potential next question is removed if quiz ends abruptly
        # (e.g. if show_results is called before all questions are processed due to an error)
        job_name_next_q = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        if remove_job_if_exists(job_name_next_q, context):
            logger.debug(f"[QuizLogic {self.quiz_id}] Ensured timer job 	'{job_name_next_q}	' removed at show_results.")

        percentage = (self.score / self.total_questions * 100) if self.total_questions > 0 else 0
        quiz_duration_seconds = (datetime.now(timezone.utc) - self.quiz_actual_start_time_dt).total_seconds() if self.quiz_actual_start_time_dt else 0

        if self.db_manager and self.db_quiz_session_id:
            try:
                self.db_manager.end_quiz_session(
                    db_quiz_session_id=self.db_quiz_session_id,
                    user_id=self.user_id, # Added for potential cross-check
                    score=self.score,
                    percentage=percentage,
                    answers_details=self.answers,
                    end_time=datetime.now(timezone.utc),
                    time_taken_seconds=quiz_duration_seconds
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Quiz results logged to DB for session {self.db_quiz_session_id}.")
            except Exception as e_db_end:
                logger.error(f"[QuizLogic {self.quiz_id}] DB exception on quiz end for session {self.db_quiz_session_id}: {e_db_end}", exc_info=True)
        elif not self.db_quiz_session_id:
             logger.error(f"[QuizLogic {self.quiz_id}] db_quiz_session_id was not set. Cannot log quiz end to DB.")
        else: # db_manager is None
            logger.warning(f"[QuizLogic {self.quiz_id}] db_manager unavailable. Cannot log quiz results.")

        results_text = f"🎉 <b>نتائج الاختبار: {self.quiz_name}</b> 🎉\n\n"
        results_text += f"<b>النتيجة:</b> {self.score} من {self.total_questions} ({percentage:.2f}%)\n"
        results_text += f"<b>الوقت المستغرق:</b> {int(quiz_duration_seconds // 60)} دقيقة و {int(quiz_duration_seconds % 60)} ثانية\n\n"
        results_text += "<b>تفاصيل الإجابات:</b>\n"
        for i, ans in enumerate(self.answers):
            status_emoji = "✅" if ans.get("is_correct") else ("❌" if ans.get("status") == "answered" else ("⏰" if ans.get("status") == "timeout" else "❔"))
            q_text_short = (ans.get("question_text", "سؤال غير معروف")[:30] + "...") if len(ans.get("question_text", "")) > 30 else ans.get("question_text", "سؤال غير معروف")
            results_text += f"{i+1}. {status_emoji} {q_text_short} - إجابتك: {ans.get('chosen_option_text', 'لم تجب')}\n"
            if not ans.get("is_correct") and ans.get("status") != "skipped_auto": # Show correct if wrong or timed out, but not if auto-skipped
                results_text += f"   <i>الصحيحة: {ans.get('correct_option_text', 'غير متوفرة')}</i>\n"
        
        # MANUS_FIX_RESULTS_BUTTONS: Updated callback_data
        keyboard_buttons = [
            [InlineKeyboardButton("✨ ابدأ اختباراً جديداً", callback_data="quiz_action_restart_quiz_cb")],
            [InlineKeyboardButton("📊 عرض الإحصائيات", callback_data="menu_stats")], 
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="quiz_action_main_menu")]
        ]
        results_keyboard = InlineKeyboardMarkup(keyboard_buttons)

        # Determine the message to edit or send anew
        message_to_edit_id = None
        if update and update.callback_query and update.callback_query.message:
            message_to_edit_id = update.callback_query.message.message_id
        elif self.last_question_message_id: # Fallback to last question message if no callback query (e.g. timeout on last q)
            message_to_edit_id = self.last_question_message_id
        
        # Store message_id for potential cleanup if user navigates away without using buttons
        # This might be better handled by the main quiz.py ConversationHandler's cleanup logic
        if context and hasattr(context, 'user_data') and message_to_edit_id:
             context.user_data[f"last_quiz_interaction_message_id_{self.chat_id}"] = message_to_edit_id

        if message_to_edit_id:
            logger.debug(f"[QuizLogic {self.quiz_id}] Attempting to update results message {message_to_edit_id}.")
            # Try editing caption first (if original was photo), then text.
            edited_successfully = False
            try:
                # Check if the original message might have been a photo (e.g. last question was an image)
                # This is a heuristic; a more robust way would be to store the type of self.last_question_message_id
                if update and update.callback_query and update.callback_query.message and update.callback_query.message.photo:
                    logger.debug(f"[QuizLogic {self.quiz_id}] Attempting to edit caption of message {message_to_edit_id} for results.")
                    await safe_edit_message_caption(bot, self.chat_id, message_to_edit_id, caption=results_text, reply_markup=results_keyboard, parse_mode="HTML")
                    edited_successfully = True
                    logger.info(f"[QuizLogic {self.quiz_id}] Successfully edited caption of message {message_to_edit_id} for results.")
            except telegram.error.BadRequest as e_caption:
                if "message is not modified" not in str(e_caption).lower() and "there is no caption in the message to edit" not in str(e_caption).lower() :
                    logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit caption of message {message_to_edit_id}: {e_caption}")
                else:
                    logger.info(f"[QuizLogic {self.quiz_id}] Editing caption for results message {message_to_edit_id} failed or was not applicable. Will try editing as text.")
            except Exception as e_gen_caption:
                logger.error(f"[QuizLogic {self.quiz_id}] General error editing caption for results message {message_to_edit_id}: {e_gen_caption}")

            if not edited_successfully:
                try:
                    logger.debug(f"[QuizLogic {self.quiz_id}] Attempting to edit text of message {message_to_edit_id} for results (caption edit failed or not applicable).")
                    await safe_edit_message_text(bot, self.chat_id, message_to_edit_id, text=results_text, reply_markup=results_keyboard, parse_mode="HTML")
                    logger.info(f"[QuizLogic {self.quiz_id}] Successfully edited text of message {message_to_edit_id} for results.")
                except telegram.error.BadRequest as e_text:
                    if "message is not modified" not in str(e_text).lower():
                        logger.error(f"[QuizLogic {self.quiz_id}] Failed to edit text of message {message_to_edit_id} for results: {e_text}. Sending new message.")
                        await safe_send_message(bot, self.chat_id, results_text, results_keyboard, parse_mode="HTML")
                    else: # Message not modified, means it's already showing the results text (e.g. from a previous attempt)
                        logger.info(f"[QuizLogic {self.quiz_id}] Text of message {message_to_edit_id} was not modified.")
                except Exception as e_gen_text:
                    logger.error(f"[QuizLogic {self.quiz_id}] General error editing text for results message {message_to_edit_id}: {e_gen_text}. Sending new message.")
                    await safe_send_message(bot, self.chat_id, results_text, results_keyboard, parse_mode="HTML")
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] No message to edit for results. Sending new message.")
            await safe_send_message(bot, self.chat_id, results_text, results_keyboard, parse_mode="HTML")

        # Call internal cleanup for this QuizLogic instance. 
        # preserve_current_logic_in_userdata=False because the quiz is definitively over from QuizLogic's perspective.
        await self.cleanup_quiz_data(context, self.user_id, "quiz_completed_results_shown", preserve_current_logic_in_userdata=False)
        return SHOWING_RESULTS

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str, preserve_current_logic_in_userdata: bool = False):
        """Cleans up data associated with this specific quiz instance."""
        logger.info(f"[QuizLogic {self.quiz_id}] Internal cleanup. User {user_id}. Reason: {reason}. Active: {self.active}")
        self.active = False # Mark this instance as inactive

        # Remove any timers set by this specific QuizLogic instance
        # Timers are named: f"question_timer_{self.chat_id}_{self.quiz_id}_{q_idx}"
        # We need to iterate up to self.total_questions or a reasonable limit if total_questions is dynamic/large
        # However, timers should ideally be removed when answered or timed out individually.
        # This is a safeguard.
        if hasattr(context, 'job_queue') and isinstance(context.job_queue, JobQueue):
            for i in range(self.total_questions + 1): # +1 to catch any lingering timer for a potential next question
                job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{i}"
                if remove_job_if_exists(job_name, context):
                    logger.debug(f"[QuizLogic {self.quiz_id}] Safeguard cleanup: Removed timer job {job_name}.")
        
        # Clear sensitive/large data from the instance itself
        self.questions_data = [] 
        self.answers = []

        # Regarding context.user_data: The main quiz.py's _cleanup_quiz_session_data
        # is responsible for removing the f"quiz_logic_instance_{user_id}" key.
        # This internal cleanup should not pop itself from user_data, as quiz.py might still need it
        # for a brief moment (e.g., to get the quiz_id for logging before popping).
        # If preserve_current_logic_in_userdata is True, it means the Quiz Conversation Handler in quiz.py
        # might still need access to this instance (e.g. if cleanup is called but quiz is not fully ending from PTB's perspective)
        # However, for results shown, it should be False.

        logger.info(f"[QuizLogic {self.quiz_id}] Internal cleanup finished for user {user_id}.")

