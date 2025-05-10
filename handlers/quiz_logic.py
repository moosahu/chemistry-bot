"""Manages the logic for conducting a quiz, including sending questions, handling answers, and calculating results."""
# handlers/quiz_logic.py (Modified to import DB_MANAGER directly)
# v2: Fixes for filter_id in DB session and NoneType error in show_results

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
                # FIX for filter_id type error: Convert "all" to None for DB insertion
                scope_id_for_db_call = self.quiz_scope_id_for_db
                if isinstance(scope_id_for_db_call, str) and scope_id_for_db_call.lower() == "all":
                    scope_id_for_db_call = None 
                elif isinstance(scope_id_for_db_call, str):
                    try:
                        # Attempt to cast to int if it's a string representation of an int
                        scope_id_for_db_call = int(scope_id_for_db_call)
                    except ValueError:
                        logger.error(f"[QuizLogic {self.quiz_id}] quiz_scope_id_for_db ('{self.quiz_scope_id_for_db}') is a string but not 'all' and not a valid integer. Setting to None for DB.")
                        scope_id_for_db_call = None
                
                self.db_quiz_session_id = self.db_manager.start_quiz_session_and_get_id(
                    user_id=self.user_id,
                    quiz_type=self.quiz_type_for_db, 
                    quiz_scope_id=scope_id_for_db_call, # Use the potentially modified scope_id
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
            if len(button_text_str.encode('utf-8')) > 60:
                temp_bytes = button_text_str.encode('utf-8')[:57]
                button_text_str = temp_bytes.decode('utf-8', 'ignore') + "..."
            callback_data = f"ans_{self.quiz_id}_{self.current_question_index}_{option_id}"
            keyboard.append([InlineKeyboardButton(text=button_text_str, callback_data=callback_data)])
        return InlineKeyboardMarkup(keyboard)

    async def send_question(self, bot: Bot, context: CallbackContext, update: Update = None):
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] send_question: inactive. User {self.user_id}. Aborting.")
            return END 

        while self.current_question_index < self.total_questions:
            current_question_data = self.questions_data[self.current_question_index]
            q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
            options = current_question_data.get("options", [])

            if len(options) < MIN_OPTIONS_PER_QUESTION:
                logger.warning(f"[QuizLogic {self.quiz_id}] Question {q_id_log} (idx {self.current_question_index}) has only {len(options)} options (min: {MIN_OPTIONS_PER_QUESTION}). Skipping.")
                
                # Ensure question_text is a string or default if None
                q_text_for_skipped = current_question_data.get("question_text")
                if q_text_for_skipped is None:
                    q_text_for_skipped = "سؤال غير صالح (خيارات قليلة)"

                self.answers.append({
                    "question_id": q_id_log,
                    "question_text": q_text_for_skipped,
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
                        # Ensure question_text is a string or default if None
                        q_text_for_error = question_text_display # Already processed above
                        if not q_text_for_error:
                             q_text_for_error = "سؤال غير متوفر (خطأ إرسال)"
                        self.answers.append({
                            "question_id": q_id_log,
                            "question_text": q_text_for_error,
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
                     # Ensure question_text is a string or default if None
                     q_text_for_error = question_text_display # Already processed above
                     if not q_text_for_error:
                         q_text_for_error = "سؤال غير متوفر (خطأ إرسال)"
                     self.answers.append({
                        "question_id": q_id_log,
                        "question_text": q_text_for_error,
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
                if context and hasattr(context, 'user_data'):
                     context.user_data[f"last_quiz_interaction_message_id_{self.chat_id}"] = sent_message.message_id
                self.question_start_time = time.time()
                # Start timer for this question
                job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
                remove_job_if_exists(job_name, context)
                context.job_queue.run_once(
                    self.question_timeout_callback, 
                    self.question_time_limit, 
                    data={
                        "chat_id": self.chat_id, 
                        "user_id": self.user_id, 
                        "quiz_id": self.quiz_id,
                        "question_index_at_timeout": self.current_question_index,
                        "question_message_id": self.last_question_message_id,
                        "is_image_question": self.last_question_is_image
                    },
                    name=job_name
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Timer set for question {self.current_question_index}, duration {self.question_time_limit}s. Job: {job_name}")
                return TAKING_QUIZ 
            else: # Failed to send question, already logged and answer recorded as error
                logger.error(f"[QuizLogic {self.quiz_id}] Sent_message was None for q_idx {self.current_question_index}. This should have been handled by error_sending logic.")
                # This path should ideally not be reached if error_sending logic is robust
                if self.current_question_index >= self.total_questions -1: # If it was the last question that failed
                    logger.info(f"[QuizLogic {self.quiz_id}] Last question failed to send. Proceeding to show results.")
                    return await self.show_results(bot, context, update)
                else: # Should have continued in the loop
                    logger.warning(f"[QuizLogic {self.quiz_id}] Sent_message was None, but not last question. Loop should continue.")
                    # This implies an issue in the continue logic above, but as a safeguard:
                    if self.current_question_index < self.total_questions:
                         # Try to advance, though this state is problematic
                         # self.current_question_index += 1 # Already incremented in error paths
                         # return await self.send_question(bot, context, update) # Recursive call, careful
                         pass # Let the while loop try the next iteration
                    else: # All questions somehow processed/failed
                         logger.info(f"[QuizLogic {self.quiz_id}] All questions processed or failed to send. Proceeding to show results.")
                         return await self.show_results(bot, context, update)
        
        # If loop finishes, all questions are processed
        logger.info(f"[QuizLogic {self.quiz_id}] All questions processed or skipped. Proceeding to show results. User {self.user_id}")
        return await self.show_results(bot, context, update)

    async def handle_answer(self, update: Update, context: CallbackContext, answer_data: str) -> int:
        query = update.callback_query
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        await query.answer()
        
        parts = answer_data.split("_")
        # ans_{self.quiz_id}_{self.current_question_index}_{option_id}
        if len(parts) < 4:
            logger.warning(f"[QuizLogic {self.quiz_id}] Invalid answer callback data: {answer_data}")
            return TAKING_QUIZ # Stay in current state

        ans_quiz_id = parts[1]
        ans_q_idx = int(parts[2])
        chosen_option_id = "_".join(parts[3:]) # Option ID might contain underscores

        if not self.active or ans_quiz_id != self.quiz_id:
            logger.warning(f"[QuizLogic {self.quiz_id}] Received answer for inactive/mismatched quiz. Active: {self.active}, AnsQuizID: {ans_quiz_id}, SelfQuizID: {self.quiz_id}")
            # User might have clicked an old button from a previous quiz instance. Try to be helpful.
            await safe_edit_message_text(context.bot, chat_id, query.message.message_id, "هذا الاختبار لم يعد نشطاً أو أنك تحاول الإجابة على سؤال من اختبار مختلف. يرجى بدء اختبار جديد إذا كنت ترغب بذلك.", reply_markup=None)
            return TAKING_QUIZ # Or END if we want to aggressively terminate old interactions

        if ans_q_idx != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Answer for wrong question index. Expected: {self.current_question_index}, Got: {ans_q_idx}")
            # Do not proceed with this answer, it's for a previous question or different quiz instance
            # User might have clicked an old button. We don't resend the current question here as it might be confusing.
            # We simply ignore this outdated callback.
            return TAKING_QUIZ # Stay in the current state, waiting for a valid answer to the current question

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        chosen_option_text = "غير متوفر"
        correct_option_text = "غير متوفر"
        is_correct = False
        correct_option_id_internal = None

        # Find chosen option and correct option details
        found_chosen = False
        for option in current_question_data.get("options", []):
            opt_id_current = option.get("option_id", "")
            opt_text_current = option.get("option_text", "")
            if option.get("is_image_option") and option.get("image_option_display_label"):
                 opt_text_current = f"صورة ({option.get('image_option_display_label')})"
            elif not opt_text_current:
                 opt_text_current = "خيار غير مسمى"

            if str(opt_id_current) == str(chosen_option_id):
                chosen_option_text = opt_text_current
                is_correct = bool(option.get("is_correct"))
                found_chosen = True
            if bool(option.get("is_correct")):
                correct_option_text = opt_text_current
                correct_option_id_internal = opt_id_current
        
        if not found_chosen:
            logger.error(f"[QuizLogic {self.quiz_id}] Chosen option_id 	'{chosen_option_id}	' not found in question {q_id_log} options. This is unexpected.")
            # Fallback, treat as incorrect, but log this error as it indicates a data or callback issue.
            chosen_option_text = "خيار غير صالح (لم يتم العثور عليه)"
            is_correct = False

        time_taken = time.time() - self.question_start_time if self.question_start_time else -1
        job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(job_name, context)
        logger.info(f"[QuizLogic {self.quiz_id}] Timer job 	'{job_name}	' removed after answer.")

        if is_correct:
            self.score += 1

        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "سؤال غير متوفر"), # Handled if None later
            "chosen_option_id": chosen_option_id,
            "chosen_option_text": chosen_option_text,
            "is_correct": is_correct,
            "correct_option_id": correct_option_id_internal,
            "correct_option_text": correct_option_text,
            "time_taken": time_taken,
            "status": "answered"
        })

        # Edit the question message to remove buttons and show feedback (optional)
        # For now, we will just proceed to the next question or results.
        if self.last_question_message_id:
            try:
                text_after_answer = query.message.text or query.message.caption or ""
                text_after_answer += f"\n\n✅ تم استلام إجابتك."
                if self.last_question_is_image:
                    await safe_edit_message_text(context.bot, chat_id, self.last_question_message_id, caption=text_after_answer, reply_markup=None, parse_mode="HTML")
                else:
                    await safe_edit_message_text(context.bot, chat_id, self.last_question_message_id, text=text_after_answer, reply_markup=None, parse_mode="HTML") 
            except Exception as e_edit:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit last question message after answer: {e_edit}")

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            return await self.send_question(context.bot, context, update)
        else:
            return await self.show_results(context.bot, context, update)

    async def question_timeout_callback(self, context: CallbackContext):
        job_data = context.job.data
        chat_id = job_data["chat_id"]
        user_id = job_data["user_id"]
        quiz_id_from_job = job_data["quiz_id"]
        q_idx_at_timeout = job_data["question_index_at_timeout"]
        q_msg_id = job_data["question_message_id"]
        q_is_image = job_data.get("is_image_question", False)

        logger.info(f"[QuizLogic Timeout] Timeout for user {user_id}, quiz {quiz_id_from_job}, q_idx {q_idx_at_timeout}")

        # Check if this timeout is still relevant
        if not self.active or self.quiz_id != quiz_id_from_job or self.current_question_index != q_idx_at_timeout:
            logger.warning(f"[QuizLogic Timeout] Stale timeout. Active:{self.active}({self.quiz_id}) vs Job:{quiz_id_from_job}. QIdx:{self.current_question_index} vs Job:{q_idx_at_timeout}. Ignoring.")
            return

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        
        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "سؤال غير متوفر"), # Handled if None later
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "is_correct": False,
            "correct_option_id": self._get_correct_option_text_robust(current_question_data, for_skip=False, field_name="option_id"),
            "correct_option_text": self._get_correct_option_text_robust(current_question_data, for_skip=False, field_name="option_text"),
            "time_taken": self.question_time_limit + 1, # Indicate timeout
            "status": "timeout"
        })

        # Edit the question message to indicate timeout and remove buttons
        if q_msg_id:
            try:
                timeout_feedback_text = (context.bot.get_chat(chat_id).message.text if hasattr(context.bot.get_chat(chat_id), 'message') and hasattr(context.bot.get_chat(chat_id).message, 'text') else "") \
                                     or (context.bot.get_chat(chat_id).message.caption if hasattr(context.bot.get_chat(chat_id), 'message') and hasattr(context.bot.get_chat(chat_id).message, 'caption') else "")
                timeout_feedback_text += "\n\n⌛ انتهى الوقت لهذا السؤال."
                if q_is_image:
                     await safe_edit_message_text(context.bot, chat_id, q_msg_id, caption=timeout_feedback_text, reply_markup=None, parse_mode="HTML")
                else:
                     await safe_edit_message_text(context.bot, chat_id, q_msg_id, text=timeout_feedback_text, reply_markup=None, parse_mode="HTML")
            except Exception as e_edit_timeout:
                logger.warning(f"[QuizLogic Timeout] Failed to edit question message on timeout: {e_edit_timeout}")

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await self.send_question(context.bot, context) # No update object here
        else:
            await self.show_results(context.bot, context) # No update object here

    def _get_correct_option_text_robust(self, question_data, for_skip=False, field_name="option_text"):
        if not question_data or not isinstance(question_data.get("options"), list):
            return "-" if for_skip else "غير متوفر (بيانات خاطئة)"
        for option in question_data["options"]:
            if option.get("is_correct"):
                text = option.get(field_name, "-")
                if option.get("is_image_option") and option.get("image_option_display_label") and field_name == "option_text":
                    return f"صورة ({option.get('image_option_display_label')})"
                return text if text else "-"
        return "-" # No correct option marked or found

    async def show_results(self, bot: Bot, context: CallbackContext, update: Update = None) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] show_results called for user {self.user_id}. Score: {self.score}/{self.total_questions}")
        self.active = False # Quiz is no longer active once results are shown

        # Ensure any lingering timer for the *next* potential question is cleared
        # (e.g., if all questions were skipped and loop ended quickly)
        job_name = f"question_timer_{self.chat_id}_{self.quiz_id}_{self.current_question_index}" 
        remove_job_if_exists(job_name, context)
        logger.debug(f"[QuizLogic {self.quiz_id}] Ensured timer job 	'{job_name}	' (for potential q_idx {self.current_question_index}) is removed at show_results.")

        summary_parts = [f"🏁 <b>نتائج اختبار 	'{self.quiz_name}	'</b> 🏁"]
        summary_parts.append(f"🎯 نتيجتك: {self.score} من {self.total_questions}")
        
        correct_answers = self.score
        wrong_answers = 0
        skipped_answers = 0
        answered_count = 0
        total_time_taken_for_answered = 0

        for ans in self.answers:
            if ans.get("status") == "answered":
                answered_count += 1
                total_time_taken_for_answered += ans.get("time_taken", 0)
                if not ans.get("is_correct"):
                    wrong_answers += 1
            elif ans.get("status") == "timeout" or ans.get("status") == "skipped_auto" or ans.get("status") == "error_sending":
                skipped_answers +=1
        
        summary_parts.append(f"✅ الإجابات الصحيحة: {correct_answers}")
        summary_parts.append(f"❌ الإجابات الخاطئة: {wrong_answers}")
        summary_parts.append(f"⏭️ الأسئلة المتخطاة/المهملة: {skipped_answers}")
        
        percentage = (self.score / self.total_questions * 100) if self.total_questions > 0 else 0
        summary_parts.append(f"📊 النسبة المئوية: {percentage:.2f}%")

        avg_time_per_q = (total_time_taken_for_answered / answered_count) if answered_count > 0 else 0
        if avg_time_per_q > 0:
            summary_parts.append(f"⏱️ متوسط وقت الإجابة للسؤال: {avg_time_per_q:.2f} ثانية")

        summary_text = "\n".join(summary_parts)
        detailed_results_parts = ["\n📜 <b>تفاصيل الإجابات:</b>"] 

        for i, ans in enumerate(self.answers):
            # FIX for NoneType error when question_text is None
            current_question_text = ans.get("question_text")
            if current_question_text is None:
                current_question_text = "سؤال غير متوفر" 
            
            q_text_short = current_question_text[:50] + ("..." if len(current_question_text) > 50 else "")
            
            chosen_opt = ans.get("chosen_option_text", "لم يتم الاختيار")
            correct_opt = ans.get("correct_option_text", "-")
            status_emoji = "✅" if ans.get("is_correct") else ("❌" if ans.get("status") == "answered" else ("⏳" if ans.get("status") == "timeout" else "⚠️"))
            
            part = f"\n{status_emoji} <b>سؤال {i+1}:</b> \"{q_text_short}\""
            part += f"\n   - اخترت: {chosen_opt}"
            if not ans.get("is_correct") and ans.get("status") != "skipped_auto" and ans.get("status") != "error_sending" and ans.get("status") != "error_sending_final": # Don't show correct if skipped due to bad data
                part += f"\n   - الصحيح: {correct_opt}"
            detailed_results_parts.append(part)

        full_results_text = summary_text
        if detailed_results_parts:
            full_results_text += "\n" + "\n".join(detailed_results_parts)
        
        # Log final results to DB
        quiz_end_time_dt = datetime.now(timezone.utc)
        time_taken_total_seconds = (quiz_end_time_dt - self.quiz_actual_start_time_dt).total_seconds() if self.quiz_actual_start_time_dt else -1

        if self.db_manager and self.db_quiz_session_id:
            try:
                self.db_manager.end_quiz_session(
                    quiz_session_uuid=self.db_quiz_session_id,
                    score=self.score,
                    wrong_answers=wrong_answers,
                    skipped_answers=skipped_answers,
                    score_percentage=percentage,
                    completed_at=quiz_end_time_dt,
                    time_taken_seconds=time_taken_total_seconds,
                    answers_details_json=json.dumps(self.answers, ensure_ascii=False) 
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Quiz results successfully logged to DB for session {self.db_quiz_session_id}.")
            except Exception as e_db_end:
                logger.error(f"[QuizLogic {self.quiz_id}] Exception while logging quiz end to DB for session {self.db_quiz_session_id}: {e_db_end}", exc_info=True)
        elif not self.db_quiz_session_id:
             logger.warning(f"[QuizLogic {self.quiz_id}] Cannot log quiz end to DB because db_quiz_session_id is not set (likely due to earlier DB error).")
        else: # db_manager is None
             logger.warning(f"[QuizLogic {self.quiz_id}] db_manager is not available. Cannot log quiz end to DB.")

        # Send results to user
        message_to_edit_id = context.user_data.get(f"last_quiz_interaction_message_id_{self.chat_id}")
        keyboard_after_results = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 عرض الإحصائيات", callback_data="stats_menu")],
            [InlineKeyboardButton("✨ ابدأ اختباراً جديداً", callback_data="quiz_menu")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
        ])

        if message_to_edit_id:
            await safe_edit_message_text(bot, self.chat_id, message_to_edit_id, full_results_text, keyboard_after_results, parse_mode="HTML")
        else:
            # If no message to edit (e.g., /start during quiz, or some other edge case)
            # Try to send a new message with the results.
            # This might happen if the quiz ended abruptly or the message context was lost.
            logger.warning(f"[QuizLogic {self.quiz_id}] No last_quiz_interaction_message_id found to edit for results. Sending as new message.")
            new_msg = await safe_send_message(bot, self.chat_id, full_results_text, keyboard_after_results, parse_mode="HTML")
            if new_msg: context.user_data[f"last_quiz_interaction_message_id_{self.chat_id}"] = new_msg.message_id
        
        await self.cleanup_quiz_data(context, self.user_id, "quiz_completed_results_shown")
        return SHOWING_RESULTS # Or END if results state is terminal

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.info(f"[QuizLogic {self.quiz_id}] Internal cleanup called for user {user_id}. Reason: {reason}. Active: {self.active}")
        self.active = False # Mark as inactive
        # Clear any running timers associated with this specific quiz instance and question index
        # The job name includes quiz_id and current_question_index
        # If current_question_index was incremented one last time, the timer might be for that index
        # Or it could be for the one *before* increment if timeout happened and then cleanup.
        # Robustly try to remove for current and current-1 if applicable.
        
        # current_question_index is the one *to be asked next* or *total_questions* if finished
        # The timer would have been set for self.current_question_index *before* it was last incremented
        # So, if a timer was running, it was for index current_question_index-1 (if >0) or 0.
        # However, show_results already tries to clear for current_question_index.
        # Let's ensure any job for this quiz_id is cleared.
        # A more targeted removal was done in handle_answer and timeout_callback.
        # This is a final sweep.
        
        # Example job name: f"question_timer_{self.chat_id}_{self.quiz_id}_{SOME_INDEX}"
        # We don't know SOME_INDEX here precisely without more state, but we can remove based on quiz_id prefix if needed.
        # For now, relying on specific removals and the one in show_results.
        
        # No specific data to pop from context.user_data by QuizLogic itself, as it's passed in.
        # The calling handler (quiz.py) is responsible for cleaning up its user_data entries for the quiz session.
        logger.info(f"[QuizLogic {self.quiz_id}] Internal cleanup finished for user {user_id}.")

    # Fallback for unexpected states or errors within QuizLogic's own flow
    async def quiz_logic_error_handler(self, bot: Bot, context: CallbackContext, update: Update, error_message: str="حدث خطأ غير متوقع في منطق الاختبار.") -> int:
        logger.error(f"[QuizLogic {self.quiz_id}] quiz_logic_error_handler triggered. User: {self.user_id}. Message: {error_message}")
        self.active = False # Ensure quiz is marked inactive
        
        # Try to inform the user
        error_text_to_user = f"{error_message} نعتذر عن الإزعاج. تم إنهاء الاختبار الحالي. يمكنك محاولة بدء اختبار جديد من القائمة الرئيسية."
        keyboard_to_main = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]])
        
        message_to_edit_id = context.user_data.get(f"last_quiz_interaction_message_id_{self.chat_id}")
        if message_to_edit_id:
            await safe_edit_message_text(bot, self.chat_id, message_to_edit_id, error_text_to_user, keyboard_to_main)
        else:
            await safe_send_message(bot, self.chat_id, error_text_to_user, keyboard_to_main)
            
        await self.cleanup_quiz_data(context, self.user_id, "quiz_logic_internal_error")
        # The main quiz conversation handler (quiz.py) should also perform its cleanup.
        return END # Signal to conversation handler to end

