"""Manages the logic for conducting a quiz, including sending questions, handling answers, and calculating results."""
# handlers/quiz_logic.py (Modified to import DB_MANAGER directly)
# v2: Fixes for filter_id in DB session and NoneType error in show_results
# v3: Enhanced support for image questions and image options

import asyncio
import logging
import time
import uuid 
import telegram # For telegram.error types
from datetime import datetime, timezone 
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot 
from telegram.ext import ConversationHandler, CallbackContext, JobQueue 

from config import logger, TAKING_QUIZ, END, MAIN_MENU, SHOWING_RESULTS # SHOWING_RESULTS is used by this module
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

        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized. User: {self.user_id}, QuizName: \t'{self.quiz_name}'\t, ActualNumQs: {self.total_questions}.")

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
                        logger.error(f"[QuizLogic {self.quiz_id}] Invalid quiz_scope_id_for_db \t'{self.quiz_scope_id_for_db}'\t. Setting to None.")
                        scope_id_for_db_call = None
                
                self.db_quiz_session_id = self.db_manager.start_quiz_session_and_get_id(
                    user_id=self.user_id, quiz_type=self.quiz_type_for_db, 
                    quiz_scope_id=scope_id_for_db_call, quiz_name=self.quiz_name,
                    total_questions=self.total_questions_for_db, start_time=self.quiz_actual_start_time_dt,
                    score=0, initial_percentage=0.0, initial_time_taken_seconds=0)
                if self.db_quiz_session_id: logger.info(f"[QuizLogic {self.quiz_id}] Quiz session logged to DB: {self.db_quiz_session_id}")
                else: logger.error(f"[QuizLogic {self.quiz_id}] Failed to log quiz start to DB.")
            except Exception as e: logger.error(f"[QuizLogic {self.quiz_id}] DB exception on quiz start: {e}", exc_info=True)
        else: logger.warning(f"[QuizLogic {self.quiz_id}] db_manager unavailable. Cannot log quiz start.")

        if not self.questions_data or self.total_questions == 0:
            logger.warning(f"[QuizLogic {self.quiz_id}] No questions. Ending quiz.")
            msg_id = update.callback_query.message.message_id if update and update.callback_query else None
            text = "عذراً، لا توجد أسئلة لبدء هذا الاختبار."
            kbd = InlineKeyboardMarkup([[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]]) # This should be handled by quiz.py to end conv
            if msg_id: await safe_edit_message_text(bot, self.chat_id, msg_id, text, kbd)
            else: await safe_send_message(bot, self.chat_id, text, kbd)
            await self.cleanup_quiz_data(context, self.user_id, "no_questions_on_start") 
            return END # Signal to quiz.py that conversation should end or go to a fallback
        
        return await self.send_question(bot, context, update)
    
    def _create_display_options_and_keyboard(self, options_from_api: list):
        keyboard_buttons = []
        displayable_options = [] 
        option_image_counter = 0

        for i, option_data in enumerate(options_from_api):
            option_id = option_data.get("option_id") 
            option_content = option_data.get("option_text")
            
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
            
            button_text_final = button_text_for_keyboard.strip()
            if not button_text_final: button_text_final = f"خيار {i+1}"
            if len(button_text_final.encode('utf-8')) > 60:
                temp_bytes = button_text_final.encode('utf-8')[:57]
                button_text_final = temp_bytes.decode('utf-8', 'ignore') + "..."
            
            callback_data = f"answer_{self.quiz_id}_{self.current_question_index}_{option_id}"
            keyboard_buttons.append([InlineKeyboardButton(text=button_text_final, callback_data=callback_data)])
            
            displayable_options.append({
                "option_id": option_id,
                "original_content": option_content, 
                "is_image_option": is_image_option_flag,
                "display_text_for_log": display_text_for_answer_log,
                "is_correct": option_data.get("is_correct", False)
            })
            
        return InlineKeyboardMarkup(keyboard_buttons), displayable_options

    async def send_question(self, bot: Bot, context: CallbackContext, update: Update = None):
        if not self.active: return END 

        for msg_id in self.sent_option_image_message_ids:
            try: await bot.delete_message(chat_id=self.chat_id, message_id=msg_id)
            except Exception: pass 
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
            
            options_keyboard, displayable_options_for_q = self._create_display_options_and_keyboard(api_options)
            current_question_data['_displayable_options'] = displayable_options_for_q

            option_image_counter_for_labeling = 0
            for option_detail in displayable_options_for_q:
                if option_detail["is_image_option"]:
                    try:
                        display_label = self.ARABIC_CHOICE_LETTERS[option_image_counter_for_labeling] if option_image_counter_for_labeling < len(self.ARABIC_CHOICE_LETTERS) else f"صورة {option_image_counter_for_labeling + 1}"
                        sent_opt_img_msg = await bot.send_photo(chat_id=self.chat_id, photo=option_detail["original_content"], caption=f"الخيار: {display_label}")
                        self.sent_option_image_message_ids.append(sent_opt_img_msg.message_id)
                        option_image_counter_for_labeling += 1
                        await asyncio.sleep(0.2) 
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
            else: 
                logger.error(f"[QuizLogic {self.quiz_id}] sent_main_q_message was None for q_idx {self.current_question_index}. Error in logic.")
                self.current_question_index += 1 
                if self.current_question_index >= self.total_questions: break 
                continue 
        
        logger.info(f"[QuizLogic {self.quiz_id}] All questions processed/skipped. Showing results. User {self.user_id}")
        # Use context.bot here as self.bot is not an attribute of QuizLogic
        return await self.show_results(context.bot, context, update)

    async def handle_answer(self, update: Update, context: CallbackContext, answer_data: str) -> int:
        query = update.callback_query
        await query.answer()
        
        parts = answer_data.split("_")
        if len(parts) < 4: logger.warning(f"[QuizLogic {self.quiz_id}] Invalid answer callback: {answer_data}"); return TAKING_QUIZ

        ans_quiz_id, ans_q_idx_str = parts[1], parts[2]
        chosen_option_id_from_callback = "_".join(parts[3:])
        ans_q_idx = int(ans_q_idx_str)

        if not self.active or ans_quiz_id != self.quiz_id or ans_q_idx != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Stale/mismatched answer. Active:{self.active}({self.quiz_id} vs {ans_quiz_id}), Qidx:{self.current_question_index} vs {ans_q_idx}. Ignoring.")
            return TAKING_QUIZ 

        time_taken = time.time() - self.question_start_time
        job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(job_name, context)

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        
        chosen_option_text_for_log = "غير محدد"
        is_correct_answer = False
        correct_option_id_for_log = None
        correct_option_text_for_log = self._get_correct_option_display_text(current_question_data)

        processed_options = current_question_data.get('_displayable_options', [])
        if not processed_options: # Fallback if _displayable_options somehow not set
            logger.error(f"[QuizLogic {self.quiz_id}] _displayable_options not found for Q {q_id_log}. This is a bug.")
            # Attempt to rebuild or use raw options, but this indicates an issue
            _, processed_options = self._create_display_options_and_keyboard(current_question_data.get("options", []))

        for option_detail in processed_options:
            if str(option_detail["option_id"]) == str(chosen_option_id_from_callback):
                chosen_option_text_for_log = option_detail["display_text_for_log"]
                is_correct_answer = option_detail["is_correct"]
                break
        
        if is_correct_answer: self.score += 1

        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": chosen_option_id_from_callback,
            "chosen_option_text": chosen_option_text_for_log,
            "correct_option_id": self._get_correct_option_id(current_question_data), # Get actual ID
            "correct_option_text": correct_option_text_for_log,
            "is_correct": is_correct_answer,
            "time_taken": round(time_taken, 2),
            "status": "answered"
        })
        
        if self.last_question_message_id:
            try:
                q_text_answered = f"<s>{current_question_data.get('question_text', '')}</s>\n<b>تمت الإجابة.</b>"
                # Use context.bot here
                if current_question_data.get("image_url"):
                    await safe_edit_message_caption(context.bot, self.chat_id, self.last_question_message_id, caption=q_text_answered, parse_mode="HTML")
                else:
                    await safe_edit_message_text(context.bot, self.chat_id, self.last_question_message_id, text=q_text_answered, parse_mode="HTML")
            except Exception as e_edit_answered:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit answered Q msg: {e_edit_answered}")

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            # Use context.bot here
            return await self.send_question(context.bot, context, update)
        else:
            # Use context.bot here
            return await self.show_results(context.bot, context, update)

    async def question_timeout_callback(self, context: CallbackContext):
        job_data = context.job.data
        chat_id = job_data["chat_id"]
        user_id = job_data["user_id"]
        quiz_id_from_job = job_data["quiz_id"]
        q_idx_at_timeout = job_data["question_index_at_timeout"]
        main_q_msg_id = job_data["main_question_message_id"]
        option_img_ids_from_job = job_data.get("option_image_ids", [])

        logger.info(f"[QuizLogic {quiz_id_from_job}] Timeout for Q{q_idx_at_timeout}, user {user_id}")

        if not self.active or quiz_id_from_job != self.quiz_id or q_idx_at_timeout != self.current_question_index:
            logger.info(f"[QuizLogic {quiz_id_from_job}] Stale timeout for Q{q_idx_at_timeout}. Current Q_idx: {self.current_question_index}. Ignoring.")
            return

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')

        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": self._get_correct_option_id(current_question_data),
            "correct_option_text": self._get_correct_option_display_text(current_question_data),
            "is_correct": False,
            "time_taken": self.question_time_limit, 
            "status": "timed_out"
        })

        if main_q_msg_id:
            try:
                q_text_timeout = f"<s>{current_question_data.get('question_text', '')}</s>\n<b>انتهى الوقت!</b>"
                if current_question_data.get("image_url"):
                    await safe_edit_message_caption(context.bot, chat_id, main_q_msg_id, caption=q_text_timeout, parse_mode="HTML")
                else:
                    await safe_edit_message_text(context.bot, chat_id, main_q_msg_id, text=q_text_timeout, parse_mode="HTML")
            except Exception as e_edit_timeout:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit timed-out Q msg: {e_edit_timeout}")
        
        for opt_img_id in option_img_ids_from_job:
            try: await context.bot.delete_message(chat_id=chat_id, message_id=opt_img_id)
            except Exception: pass
        if main_q_msg_id in self.sent_option_image_message_ids: 
             self.sent_option_image_message_ids.remove(main_q_msg_id) 

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await self.send_question(context.bot, context) 
        else:
            await self.show_results(context.bot, context) 

    def _get_correct_option_id(self, question_data):
        options = question_data.get("options", [])
        for opt in options:
            if opt.get("is_correct"): return opt.get("option_id")
        return None

    def _get_correct_option_display_text(self, question_data, for_skip=False):
        processed_options = question_data.get('_displayable_options')
        raw_options_api = question_data.get("options", [])
        
        target_options_list = processed_options if processed_options else raw_options_api
        key_for_text = "display_text_for_log" if processed_options else "option_text"

        for opt_detail in target_options_list:
            if opt_detail.get("is_correct"): 
                text = opt_detail.get(key_for_text, "غير متوفر")
                if processed_options and opt_detail.get("is_image_option") and not for_skip:
                    # For displayable options that are images, we already have a good label
                    return opt_detail.get("display_text_for_log", "صورة (غير محددة)")
                elif not processed_options and is_image_url(str(text)) and not for_skip:
                    # If using raw options and it's an image URL, just indicate it's an image
                    return "صورة (الإجابة الصحيحة)"
                return str(text)
        return "غير متوفر"

    async def show_results(self, bot: Bot, context: CallbackContext, update: Update = None):
        logger.info(f"[QuizLogic {self.quiz_id}] Showing results for user {self.user_id}")
        self.active = False 
        
        # Cleanup timers and any lingering question messages if not already handled
        job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index -1}" # Last active question
        remove_job_if_exists(job_name, context)
        if self.last_question_message_id:
            try: 
                # Attempt to remove keyboard from the very last question message if it's still there
                # This might have been done by handle_answer or timeout, but as a fallback
                current_q_data_for_edit = self.questions_data[self.current_question_index -1] if self.current_question_index > 0 else None
                if current_q_data_for_edit:
                    q_text_final = f"<s>{current_q_data_for_edit.get('question_text', '')}</s>\n<b>انتهى الاختبار.</b>"
                    if current_q_data_for_edit.get("image_url"):
                        await safe_edit_message_caption(bot, self.chat_id, self.last_question_message_id, caption=q_text_final, parse_mode="HTML", reply_markup=None)
                    else:
                        await safe_edit_message_text(bot, self.chat_id, self.last_question_message_id, text=q_text_final, parse_mode="HTML", reply_markup=None)
            except Exception: pass # Best effort
        for msg_id in self.sent_option_image_message_ids:
            try: await bot.delete_message(chat_id=self.chat_id, message_id=msg_id)
            except Exception: pass
        self.sent_option_image_message_ids = []

        total_answered = sum(1 for ans in self.answers if ans["status"] == "answered")
        total_skipped_auto = sum(1 for ans in self.answers if ans["status"] == "skipped_auto")
        total_timed_out = sum(1 for ans in self.answers if ans["status"] == "timed_out")
        total_error_sending = sum(1 for ans in self.answers if ans["status"] == "error_sending")
        
        total_processed_questions = len(self.answers)
        percentage = (self.score / total_processed_questions * 100) if total_processed_questions > 0 else 0
        
        total_time_taken_seconds = sum(ans["time_taken"] for ans in self.answers if ans["time_taken"] > 0) # Only positive times
        avg_time_per_q_seconds = (total_time_taken_seconds / total_answered) if total_answered > 0 else 0

        # Update DB with final results
        if self.db_manager and self.db_quiz_session_id:
            try:
                self.db_manager.end_quiz_session(
                    session_id=self.db_quiz_session_id, 
                    end_time=datetime.now(timezone.utc),
                    final_score=self.score, 
                    final_percentage=round(percentage, 2),
                    total_time_taken_seconds=round(total_time_taken_seconds, 2),
                    answers_details=json.dumps(self.answers, ensure_ascii=False) 
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Quiz session {self.db_quiz_session_id} updated in DB with final results.")
            except Exception as e_db_end: logger.error(f"[QuizLogic {self.quiz_id}] DB exception on quiz end update: {e_db_end}", exc_info=True)
        else: logger.warning(f"[QuizLogic {self.quiz_id}] db_manager or session_id unavailable. Cannot log quiz end results.")

        results_text = f"🏁 <b>نتائج اختبار '{self.quiz_name}'</b> 🏁\n\n"
        results_text += f"🎯 نتيجتك: {self.score} من {total_processed_questions}\n"
        results_text += f"✅ الإجابات الصحيحة: {self.score}\n"
        results_text += f"❌ الإجابات الخاطئة: {total_answered - self.score}\n" 
        results_text += f"⏭️ الأسئلة المتخطاة/المهملة: {total_skipped_auto + total_timed_out + total_error_sending}\n"
        results_text += f"📊 النسبة المئوية: {percentage:.2f}%\n"
        if avg_time_per_q_seconds > 0:
            results_text += f"⏱️ متوسط وقت الإجابة للسؤال: {avg_time_per_q_seconds:.2f} ثانية\n"
        results_text += "\n📜 <b>تفاصيل الإجابات:</b>\n"

        for i, ans in enumerate(self.answers):
            q_text_short = ans['question_text'][:50] + ("..." if len(ans['question_text']) > 50 else "")
            results_text += f"\n<b>سؤال {i+1}:</b> \"{q_text_short}\"\n"
            if ans['status'] == 'answered':
                chosen_text_short = ans['chosen_option_text'][:50] + ("..." if len(ans['chosen_option_text']) > 50 else "")
                correct_text_short = ans['correct_option_text'][:50] + ("..." if len(ans['correct_option_text']) > 50 else "")
                results_text += f" - اخترت: {chosen_text_short} ({'صحيح ✅' if ans['is_correct'] else 'خطأ ❌'})\n"
                if not ans['is_correct']:
                    results_text += f" - الصحيح: {correct_text_short}\n"
            elif ans['status'] == 'timed_out':
                results_text += " - الحالة: انتهى الوقت ⌛\n"
            elif ans['status'] == 'skipped_auto':
                results_text += " - الحالة: تم التخطي (خيارات غير كافية) ⏭️\n"
            elif ans['status'] == 'error_sending':
                results_text += " - الحالة: خطأ في إرسال السؤال ⚠️\n"
            else:
                results_text += f" - الحالة: {ans['status']}\n"

        # Determine the message to edit or send
        target_message_id = None
        if update and update.callback_query and update.callback_query.message:
            target_message_id = update.callback_query.message.message_id
        elif self.last_question_message_id: # Fallback to last question message ID
            target_message_id = self.last_question_message_id
        
        # Fallback if context.user_data doesn't have the specific message ID
        if not target_message_id and context and hasattr(context, 'user_data'):
            target_message_id = context.user_data.get(f"last_quiz_interaction_message_id_{self.chat_id}")

        keyboard = [
            [InlineKeyboardButton("✨ ابدأ اختباراً جديداً", callback_data="quiz_action_restart_quiz_cb")],
            [InlineKeyboardButton("📊 عرض الإحصائيات", callback_data="menu_stats")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="quiz_action_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if target_message_id:
            try:
                await safe_edit_message_text(bot, self.chat_id, target_message_id, results_text, reply_markup, parse_mode="HTML")
            except telegram.error.BadRequest as e_edit_results:
                if "message is not modified" in str(e_edit_results).lower():
                    logger.info(f"[QuizLogic {self.quiz_id}] Results message not modified. Sending new one.")
                    await safe_send_message(bot, self.chat_id, results_text, reply_markup, parse_mode="HTML")
                elif "message to edit not found" in str(e_edit_results).lower():
                    logger.warning(f"[QuizLogic {self.quiz_id}] Message to edit results not found ({target_message_id}). Sending new one. Error: {e_edit_results}")
                    await safe_send_message(bot, self.chat_id, results_text, reply_markup, parse_mode="HTML")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Error editing results message ({target_message_id}): {e_edit_results}. Sending new one.")
                    await safe_send_message(bot, self.chat_id, results_text, reply_markup, parse_mode="HTML")
            except Exception as e_other_edit_results:
                logger.error(f"[QuizLogic {self.quiz_id}] Unexpected error editing results message ({target_message_id}): {e_other_edit_results}. Sending new one.")
                await safe_send_message(bot, self.chat_id, results_text, reply_markup, parse_mode="HTML")
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] No target_message_id for results. Sending new message.")
            await safe_send_message(bot, self.chat_id, results_text, reply_markup, parse_mode="HTML")

        # Cleanup quiz data from context.user_data
        await self.cleanup_quiz_data(context, self.user_id, "quiz_completed_show_results")
        return SHOWING_RESULTS # Signal to quiz.py that results are shown

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str = "unknown"):
        logger.info(f"[QuizLogic {self.quiz_id if hasattr(self, 'quiz_id') else 'N/A'}] cleanup_quiz_data called for user {user_id}. Reason: {reason}")
        self.active = False
        
        # Stop any running timers for this quiz instance
        if hasattr(self, 'quiz_id') and hasattr(self, 'current_question_index'):
            job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
            remove_job_if_exists(job_name, context)
            # Also try to remove for previous index in case cleanup is called after increment but before new timer
            job_name_prev = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index -1}"
            remove_job_if_exists(job_name_prev, context)

        # Clear quiz-specific data from user_data if it exists
        if context and hasattr(context, 'user_data'):
            if f"quiz_logic_instance_{user_id}" in context.user_data:
                del context.user_data[f"quiz_logic_instance_{user_id}"]
                logger.debug(f"[QuizLogic Cleanup] Removed quiz_logic_instance_{user_id} from user_data.")
            if f"last_quiz_interaction_message_id_{user_id}" in context.user_data: # Assuming chat_id is same as user_id for PMs
                del context.user_data[f"last_quiz_interaction_message_id_{user_id}"]
                logger.debug(f"[QuizLogic Cleanup] Removed last_quiz_interaction_message_id_{user_id} from user_data.")
        
        # Reset internal state (optional, as instance should be discarded)
        self.questions_data = []
        self.answers = []
        self.score = 0
        self.current_question_index = 0
        self.last_question_message_id = None
        self.sent_option_image_message_ids = []
        logger.info(f"[QuizLogic {self.quiz_id if hasattr(self, 'quiz_id') else 'N/A'}] Quiz data cleaned up for user {user_id}.")

    @staticmethod
    async def get_active_quiz_instance(context: CallbackContext, user_id: int):
        if context and hasattr(context, 'user_data'):
            instance = context.user_data.get(f"quiz_logic_instance_{user_id}")
            if instance and isinstance(instance, QuizLogic) and instance.active:
                return instance
        return None

    @staticmethod
    async def store_quiz_instance(context: CallbackContext, user_id: int, instance):
        if context and hasattr(context, 'user_data'):
            context.user_data[f"quiz_logic_instance_{user_id}"] = instance
            logger.debug(f"[QuizLogic Store] Stored quiz_logic_instance for user {user_id}")

    @staticmethod
    async def clear_quiz_instance_from_context(context: CallbackContext, user_id: int, reason: str = "unknown"):
        # This is a more direct way to call cleanup if the instance is known to be in context
        # It also calls the instance's own cleanup method.
        logger.info(f"[QuizLogic StaticClear] clear_quiz_instance_from_context called for user {user_id}. Reason: {reason}")
        instance = await QuizLogic.get_active_quiz_instance(context, user_id)
        if instance:
            await instance.cleanup_quiz_data(context, user_id, f"static_clear_wrapper: {reason}")
        elif context and hasattr(context, 'user_data') and f"quiz_logic_instance_{user_id}" in context.user_data:
            # If instance wasn't active but still in user_data, remove it.
            del context.user_data[f"quiz_logic_instance_{user_id}"]
            logger.debug(f"[QuizLogic StaticClear] Removed inactive quiz_logic_instance_{user_id} from user_data.")

