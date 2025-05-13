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
            await self.cleanup_quiz_data(context, self.user_id, "no_questions_on_start") 
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
            logger.warning(f"[QuizLogic {self.quiz_id}] Stale/mismatched answer. Active:{self.active}({self.quiz_id} vs {ans_quiz_id}), QIdx:{self.current_question_index} vs {ans_q_idx}")
            if self.active: await safe_edit_message_text(context.bot, self.chat_id, query.message.message_id, "إجابة لسؤال قديم أو اختبار مختلف. تم تجاهلها.", reply_markup=None)
            else: await safe_edit_message_text(context.bot, self.chat_id, query.message.message_id, "الاختبار لم يعد نشطاً.", reply_markup=None)
            return TAKING_QUIZ

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        displayable_options_for_q = current_question_data.get('_displayable_options', [])
        
        chosen_option_display_text = "غير محدد"
        is_correct_answer = False
        correct_option_id_internal = None
        correct_option_display_text_internal = "-"

        found_chosen_opt_detail = None
        for opt_detail in displayable_options_for_q:
            if str(opt_detail.get("option_id")) == str(chosen_option_id_from_callback):
                found_chosen_opt_detail = opt_detail
                chosen_option_display_text = opt_detail.get("display_text_for_log", "خيار غير معروف")
                is_correct_answer = bool(opt_detail.get("is_correct"))
                break
        
        if found_chosen_opt_detail is None:
            logger.error(f"[QuizLogic {self.quiz_id}] Chosen option_id 	'{chosen_option_id_from_callback}	' not found in processed _displayable_options for Q {q_id_log}. This is unexpected.")
            chosen_option_display_text = "خيار غير صالح (لم يتم العثور عليه)"
            is_correct_answer = False
        
        # Find correct option display text for logging
        for opt_detail in displayable_options_for_q:
            if bool(opt_detail.get("is_correct")):
                correct_option_id_internal = opt_detail.get("option_id")
                correct_option_display_text_internal = opt_detail.get("display_text_for_log", "-")
                break

        time_taken = time.time() - self.question_start_time if self.question_start_time else -1
        job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(job_name, context)
        logger.info(f"[QuizLogic {self.quiz_id}] Timer job 	'{job_name}	' removed after answer.")

        if is_correct_answer: self.score += 1

        q_text_main = current_question_data.get("question_text") or (f"سؤال مصور (ID: {q_id_log})" if current_question_data.get("image_url") else "سؤال غير متوفر")
        self.answers.append({
            "question_id": q_id_log, "question_text": q_text_main,
            "chosen_option_id": chosen_option_id_from_callback, "chosen_option_text": chosen_option_display_text,
            "is_correct": is_correct_answer, "correct_option_id": correct_option_id_internal,
            "correct_option_text": correct_option_display_text_internal, "time_taken": time_taken, "status": "answered"
        })

        # Edit the main question message to remove buttons
        if self.last_question_message_id:
            try: 
                # Determine if original message had caption or text
                original_message = query.message # The message with the buttons
                feedback_text = original_message.caption if original_message.caption else original_message.text
                feedback_text = (feedback_text or "") + f"\n\n✅ تم استلام إجابتك."
                if original_message.photo: # If it was a photo question
                    await safe_edit_message_caption(context.bot, self.chat_id, self.last_question_message_id, caption=feedback_text, reply_markup=None, parse_mode="HTML")
                else:
                    await safe_edit_message_text(context.bot, self.chat_id, self.last_question_message_id, text=feedback_text, reply_markup=None, parse_mode="HTML")
            except Exception as e_edit: logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit last main question message: {e_edit}")
        
        # Option image messages are cleared at the start of the next send_question or cleanup

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            return await self.send_question(context.bot, context, update)
        else:
            return await self.show_results(context.bot, context, update)

    async def question_timeout_callback(self, context: CallbackContext):
        job_data = context.job.data
        quiz_id_from_job, q_idx_at_timeout = job_data["quiz_id"], job_data["question_index_at_timeout"]
        main_q_msg_id, option_img_ids = job_data["main_question_message_id"], job_data.get("option_image_ids", [])

        logger.info(f"[QuizLogic Timeout] User {job_data['user_id']}, quiz {quiz_id_from_job}, q_idx {q_idx_at_timeout}")
        if not self.active or self.quiz_id != quiz_id_from_job or self.current_question_index != q_idx_at_timeout:
            logger.warning(f"[QuizLogic Timeout] Stale timeout. Ignoring."); return

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        q_text_main = current_question_data.get("question_text") or (f"سؤال مصور (ID: {q_id_log})" if current_question_data.get("image_url") else "سؤال غير متوفر")
        
        self.answers.append({
            "question_id": q_id_log, "question_text": q_text_main,
            "chosen_option_id": None, "chosen_option_text": "انتهى الوقت", "is_correct": False,
            "correct_option_id": self._get_correct_option_id_robust(current_question_data),
            "correct_option_text": self._get_correct_option_display_text(current_question_data, for_skip=False),
            "time_taken": self.question_time_limit + 1, "status": "timeout"
        })

        if main_q_msg_id:
            try:
                # Attempt to get original message to append timeout notice
                original_message = await context.bot.edit_message_reply_markup(chat_id=self.chat_id, message_id=main_q_msg_id, reply_markup=None) # First remove kbd
                feedback_text = original_message.caption if original_message.caption else original_message.text
                feedback_text = (feedback_text or "") + "\n\n⌛ انتهى الوقت لهذا السؤال."
                if original_message.photo:
                    await safe_edit_message_caption(context.bot, self.chat_id, main_q_msg_id, caption=feedback_text, parse_mode="HTML")
                else:
                    await safe_edit_message_text(context.bot, self.chat_id, main_q_msg_id, text=feedback_text, parse_mode="HTML")
            except Exception as e_edit_timeout: logger.warning(f"[QuizLogic Timeout] Failed to edit main question message on timeout: {e_edit_timeout}")
        
        # Option image messages are cleared at the start of the next send_question or cleanup

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await self.send_question(context.bot, context) 
        else:
            await self.show_results(context.bot, context)

    def _get_correct_option_id_robust(self, question_data):
        displayable_options = question_data.get('_displayable_options', [])
        for opt_detail in displayable_options:
            if bool(opt_detail.get("is_correct")):
                return opt_detail.get("option_id")
        return None

    def _get_correct_option_display_text(self, question_data, for_skip=False):
        displayable_options = question_data.get('_displayable_options', [])
        if not displayable_options and not for_skip: return "غير متوفر (بيانات خاطئة)"
        if not displayable_options and for_skip: return "-"
        
        for opt_detail in displayable_options:
            if bool(opt_detail.get("is_correct")):
                return opt_detail.get("display_text_for_log", "-")
        return "-" # No correct option marked or found

    async def show_results(self, bot: Bot, context: CallbackContext, update: Update = None) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] show_results. Score: {self.score}/{self.total_questions}")
        self.active = False
        job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}" 
        remove_job_if_exists(job_name, context)
        logger.debug(f"[QuizLogic {self.quiz_id}] Ensured timer job 	'{job_name}	' removed at show_results.")

        summary_parts = [f"🏁 <b>نتائج اختبار 	'{self.quiz_name}	'</b> 🏁", f"🎯 نتيجتك: {self.score} من {self.total_questions}"]
        correct_answers, wrong_answers, skipped_answers, answered_count, total_time_taken_for_answered = self.score, 0, 0, 0, 0

        for ans in self.answers:
            if ans.get("status") == "answered":
                answered_count += 1; total_time_taken_for_answered += ans.get("time_taken", 0)
                if not ans.get("is_correct"): wrong_answers += 1
            else: skipped_answers +=1
        
        summary_parts.extend([
            f"✅ الإجابات الصحيحة: {correct_answers}", f"❌ الإجابات الخاطئة: {wrong_answers}",
            f"⏭️ الأسئلة المتخطاة/المهملة: {skipped_answers}"])
        percentage = (self.score / self.total_questions * 100) if self.total_questions > 0 else 0
        summary_parts.append(f"📊 النسبة المئوية: {percentage:.2f}%")
        if answered_count > 0: summary_parts.append(f"⏱️ متوسط وقت الإجابة للسؤال: {total_time_taken_for_answered / answered_count:.2f} ثانية")

        detailed_results_parts = ["\n📜 <b>تفاصيل الإجابات:</b>"] 
        for i, ans in enumerate(self.answers):
            q_text = ans.get("question_text") or "سؤال غير متوفر"
            q_text_short = q_text[:50] + ("..." if len(q_text) > 50 else "")
            chosen_opt = ans.get("chosen_option_text", "لم يتم الاختيار")
            correct_opt = ans.get("correct_option_text", "-")
            status_emoji = "✅" if ans.get("is_correct") else ("❌" if ans.get("status") == "answered" else ("⏳" if ans.get("status") == "timeout" else "⚠️"))
            part = f"\n{status_emoji} <b>سؤال {i+1}:</b> \"{q_text_short}\"\n   - اخترت: {chosen_opt}"
            if not ans.get("is_correct") and ans.get("status") not in ["skipped_auto", "error_sending"]: part += f"\n   - الصحيح: {correct_opt}"
            detailed_results_parts.append(part)

        full_results_text = "\n".join(summary_parts) + "\n" + "\n".join(detailed_results_parts)
        quiz_end_time_dt = datetime.now(timezone.utc)
        time_taken_total_seconds = (quiz_end_time_dt - self.quiz_actual_start_time_dt).total_seconds() if self.quiz_actual_start_time_dt else -1

        if self.db_manager and self.db_quiz_session_id:
            try:
                self.db_manager.end_quiz_session(quiz_session_uuid=self.db_quiz_session_id, score=self.score, wrong_answers=wrong_answers, skipped_answers=skipped_answers, score_percentage=percentage, completed_at=quiz_end_time_dt, time_taken_seconds=time_taken_total_seconds, answers_details_json=json.dumps(self.answers, ensure_ascii=False))
                logger.info(f"[QuizLogic {self.quiz_id}] Quiz results logged to DB for session {self.db_quiz_session_id}.")
            except Exception as e_db_end: logger.error(f"[QuizLogic {self.quiz_id}] DB exception on quiz end for session {self.db_quiz_session_id}: {e_db_end}", exc_info=True)
        elif not self.db_quiz_session_id: logger.warning(f"[QuizLogic {self.quiz_id}] Cannot log quiz end to DB, db_quiz_session_id not set.")
        else: logger.warning(f"[QuizLogic {self.quiz_id}] db_manager unavailable. Cannot log quiz end.")

        msg_to_edit_id = context.user_data.get(f"last_quiz_interaction_message_id_{self.chat_id}")
        kbd_after_results = InlineKeyboardMarkup([ [InlineKeyboardButton("📊 عرض الإحصائيات", callback_data="stats_menu")], [InlineKeyboardButton("✨ ابدأ اختباراً جديداً", callback_data="quiz_menu")], [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")] ])

        if msg_to_edit_id:
            edited_successfully = False
            logger.debug(f"[QuizLogic {self.quiz_id}] Attempting to update results message {msg_to_edit_id}.")

            # Attempt 1: Try to edit caption. This is generally safer for media messages or messages where text presence is uncertain.
            logger.debug(f"[QuizLogic {self.quiz_id}] Attempting to edit caption of message {msg_to_edit_id} for results.")
            caption_edit_result = await safe_edit_message_caption(
                bot=bot, chat_id=self.chat_id, message_id=msg_to_edit_id,
                caption=full_results_text, reply_markup=kbd_after_results, parse_mode="HTML"
            )
            if caption_edit_result is True:
                edited_successfully = True
                logger.info(f"[QuizLogic {self.quiz_id}] Successfully edited caption of message {msg_to_edit_id} for results.")
            else: # caption_edit_result is False (could be "no caption to edit", "not modified", or other errors)
                logger.info(f"[QuizLogic {self.quiz_id}] Editing caption for results message {msg_to_edit_id} failed or was not applicable. Will try editing as text.")

                # Attempt 2: If caption edit failed or was not applicable, try editing as text.
                logger.debug(f"[QuizLogic {self.quiz_id}] Attempting to edit text of message {msg_to_edit_id} for results (caption edit failed or not applicable).")
                text_edit_result = await safe_edit_message_text(
                    bot=bot, chat_id=self.chat_id, message_id=msg_to_edit_id,
                    text=full_results_text, reply_markup=kbd_after_results, parse_mode="HTML"
                )
                if text_edit_result is True:
                    edited_successfully = True
                    logger.info(f"[QuizLogic {self.quiz_id}] Successfully edited text of message {msg_to_edit_id} for results.")
                elif text_edit_result == "NO_TEXT_IN_MESSAGE":
                    logger.info(f"[QuizLogic {self.quiz_id}] Cannot edit message {msg_to_edit_id} as text (it has no text body). Will send new message for results.")
                    # edited_successfully remains False, new message will be sent
                else: # text_edit_result is False for other errors
                    logger.info(f"[QuizLogic {self.quiz_id}] Failed to edit message {msg_to_edit_id} as text for other reasons. Will send new message for results.")
                    # edited_successfully remains False, new message will be sent
            
            if not edited_successfully:
                logger.info(f"[QuizLogic {self.quiz_id}] All edit attempts failed for message {msg_to_edit_id}. Sending new message for results.")
                new_msg = await safe_send_message(bot, self.chat_id, full_results_text, kbd_after_results, parse_mode="HTML")
                if new_msg: context.user_data[f"last_quiz_interaction_message_id_{self.chat_id}"] = new_msg.message_id
        else: # No msg_to_edit_id found
            logger.warning(f"[QuizLogic {self.quiz_id}] No last_quiz_interaction_message_id to edit. Sending results as new message.")
            new_msg = await safe_send_message(bot, self.chat_id, full_results_text, kbd_after_results, parse_mode="HTML")
            if new_msg: context.user_data[f"last_quiz_interaction_message_id_{self.chat_id}"] = new_msg.message_id
        
        await self.cleanup_quiz_data(context, self.user_id, "quiz_completed_results_shown")
        return SHOWING_RESULTS

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.info(f"[QuizLogic {self.quiz_id}] Internal cleanup. User {user_id}. Reason: {reason}. Active: {self.active}")
        self.active = False
        # Clear any sent option image messages for this quiz instance
        for msg_id in self.sent_option_image_message_ids:
            try: await context.bot.delete_message(chat_id=self.chat_id, message_id=msg_id)
            except Exception: pass # Ignore if already deleted or error
        self.sent_option_image_message_ids = []
        # Rely on specific timer removals and the one in show_results.
        logger.info(f"[QuizLogic {self.quiz_id}] Internal cleanup finished for user {user_id}.")

    async def quiz_logic_error_handler(self, bot: Bot, context: CallbackContext, update: Update, error_message: str="حدث خطأ غير متوقع في منطق الاختبار.") -> int:
        logger.error(f"[QuizLogic {self.quiz_id}] quiz_logic_error_handler. User: {self.user_id}. Msg: {error_message}")
        self.active = False
        error_text = f"{error_message} نعتذر. تم إنهاء الاختبار. حاول بدء اختبار جديد."
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]])
        msg_to_edit_id = context.user_data.get(f"last_quiz_interaction_message_id_{self.chat_id}")
        if msg_to_edit_id: await safe_edit_message_text(bot, self.chat_id, msg_to_edit_id, error_text, kbd)
        else: await safe_send_message(bot, self.chat_id, error_text, kbd)
        await self.cleanup_quiz_data(context, self.user_id, "quiz_logic_internal_error")
        return END

