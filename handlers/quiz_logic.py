# -*- coding: utf-8 -*-
# handlers/quiz_logic.py (FULLY COMPATIBLE - PostgreSQL Logging & Original UI Preservation)

import asyncio
import logging
import time
import uuid # لإنشاء معرّف فريد للاختبار
import telegram # For telegram.error types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot 
from telegram.ext import ConversationHandler, CallbackContext, JobQueue 
from config import logger, TAKING_QUIZ, END, MAIN_MENU, SHOWING_RESULTS # SHOWING_RESULTS is used for return state
from utils.helpers import safe_send_message, safe_edit_message_text, remove_job_if_exists

# --- POSTGRESQL DATABASE LOGGING ---
# Ensure this path is correct for your project structure
try:
    from database.data_logger import log_question_interaction, log_quiz_end
except ImportError as e:
    logger.error(f"CRITICAL: Could not import from database.data_logger in quiz_logic.py: {e}. Ensure it is in the correct path. Admin stats will not work.")
    # Define dummy functions to prevent crashes if import fails
    def log_question_interaction(*args, **kwargs): logger.error("Dummy log_question_interaction called due to import error."); pass
    def log_quiz_end(*args, **kwargs): logger.error("Dummy log_quiz_end called due to import error."); pass
# -----------------------------------------------

MIN_OPTIONS_PER_QUESTION = 2

class QuizLogic:
    ARABIC_CHOICE_LETTERS = ["أ", "ب", "ج", "د"]

    def __init__(self, user_id=None, chat_id=None, quiz_type=None, questions_data=None, total_questions=0, question_time_limit=60, quiz_id=None, quiz_name=None, db_quiz_session_id=None):
        self.user_id = user_id
        self.chat_id = chat_id
        self.quiz_id = quiz_id if quiz_id else str(uuid.uuid4()) 
        self.quiz_name = quiz_name if quiz_name else "اختبار غير مسمى"
        self.quiz_type = quiz_type
        self.questions_data = questions_data if questions_data is not None else []
        self.total_questions = len(self.questions_data) 
        self.current_question_index = 0
        self.score = 0
        self.answers = [] 
        self.question_start_time = None
        self.last_question_message_id = None
        self.question_time_limit = question_time_limit
        self.last_question_is_image = False
        self.active = True 
        self.db_quiz_session_id = db_quiz_session_id # Added for PostgreSQL logging
        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized. User: {self.user_id}, Chat: {self.chat_id}, Quiz: {self.quiz_name}, Questions: {self.total_questions}, DB Session: {self.db_quiz_session_id}")

    async def start_quiz(self, bot: Bot, context: CallbackContext, update: Update, user_id: int) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] start_quiz called. User: {user_id}, Chat: {self.chat_id}, DB Session: {self.db_quiz_session_id}")
        self.active = True 
        self.total_questions = len(self.questions_data) 
        if not self.questions_data or self.total_questions == 0:
            logger.warning(f"[QuizLogic {self.quiz_id}] No questions. Ending quiz.")
            message_to_edit_id = update.callback_query.message.message_id if update and update.callback_query and update.callback_query.message else None
            text_no_questions = "عذراً، لا توجد أسئلة لبدء هذا الاختبار. يرجى المحاولة مرة أخرى."
            keyboard_to_main = InlineKeyboardMarkup([[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]]) 
            if message_to_edit_id:
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_to_edit_id, text=text_no_questions, reply_markup=keyboard_to_main)
            else:
                await safe_send_message(bot, chat_id=self.chat_id, text=text_no_questions, reply_markup=keyboard_to_main)
            
            if self.db_quiz_session_id and self.active:
                try: 
                    log_quiz_end(self.db_quiz_session_id, self.score, status="aborted_no_questions")
                    logger.info(f"[QuizLogic {self.quiz_id}] Logged quiz end (no questions) to DB. Session {self.db_quiz_session_id}")
                except Exception as e_db_log: 
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to log quiz end (no questions) to DB: {e_db_log}")
            
            self.active = False
            await self.cleanup_quiz_data(context, user_id, "no_questions_on_start") 
            return SHOWING_RESULTS 
        
        return await self.send_question(bot, context, user_id)
    
    def create_options_keyboard(self, options_data):
        keyboard = []
        for i, option in enumerate(options_data):
            option_id = option.get("option_id", f"gen_opt_{i}") 
            option_text_original = option.get("option_text", "")
            button_text = ""

            if option.get("is_image_option"):
                image_display_char = option.get("image_option_display_label")
                button_text = f"الخيار المصور: {image_display_char}" if image_display_char else f"اختر صورة {i + 1}"
            elif isinstance(option_text_original, str) and not option_text_original.strip(): 
                button_text = f"خيار {i + 1}" 
            elif isinstance(option_text_original, str):
                button_text = option_text_original
            else: 
                button_text = f"خيار {i + 1} (بيانات غير نصية)"
            
            button_text_str = str(button_text).strip()
            if not button_text_str: button_text_str = f"خيار {i + 1}" 
            # CORRECTED LINE 65 and similar lines: Removed unnecessary backslashes before quotes
            if len(button_text_str.encode('utf-8')) > 60: 
                button_text_str = button_text_str.encode('utf-8')[:57].decode('utf-8', 'ignore') + "..."

            callback_data = f"ans_{self.quiz_id}_{self.current_question_index}_{option_id}"
            keyboard.append([InlineKeyboardButton(text=button_text_str, callback_data=callback_data)])
        return InlineKeyboardMarkup(keyboard)

    async def send_question(self, bot: Bot, context: CallbackContext, user_id: int):
        if not self.active: 
            logger.warning(f"[QuizLogic {self.quiz_id}] send_question called but quiz is inactive. User {user_id}. Aborting.")
            return END 

        self.total_questions = len(self.questions_data)
        while self.current_question_index < self.total_questions:
            current_question_data = self.questions_data[self.current_question_index]
            q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
            options = current_question_data.get("options", [])

            if len(options) < MIN_OPTIONS_PER_QUESTION:
                logger.warning(f"[QuizLogic {self.quiz_id}] Question {q_id_log} (idx {self.current_question_index}) has insufficient options. Skipping.")
                self.answers.append({"question_id": q_id_log, "is_correct": False, "chosen_option_text": "تم تخطي السؤال (خيارات غير كافية)", "correct_option_text": "-", "time_taken": -998})
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
                        await bot.send_photo(chat_id=self.chat_id, photo=option_text_original, caption=f"الخيار: {display_label}")
                        current_option_proc['is_image_option'] = True
                        current_option_proc['image_option_display_label'] = display_label 
                        option_image_counter += 1 
                        await asyncio.sleep(0.3) 
                    except Exception as e_img_opt:
                        logger.error(f"[QuizLogic {self.quiz_id}] Failed to send image option {i} for q_id {q_id_log}: {e_img_opt}")
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
            question_text_from_data = str(current_question_data.get("question_text", "")) 
            sent_message = None
            self.last_question_is_image = False

            if image_url:
                caption_text = header + question_text_from_data
                try: 
                    sent_message = await bot.send_photo(chat_id=self.chat_id, photo=image_url, caption=caption_text, reply_markup=options_keyboard, parse_mode="HTML")
                    self.last_question_is_image = True
                except Exception as e: 
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to send photo for q_id {q_id_log}: {e}. Fallback to text.")
                    full_question_text = header + question_text_from_data
                    sent_message = await safe_send_message(bot, chat_id=self.chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
            else:
                full_question_text = header + (question_text_from_data if question_text_from_data.strip() else "نص السؤال غير متوفر حالياً.")
                sent_message = await safe_send_message(bot, chat_id=self.chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
            
            if sent_message:
                self.last_question_message_id = sent_message.message_id
                self.question_start_time = time.time()
                timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
                remove_job_if_exists(timer_job_name, context) 
                if not hasattr(context, 'bot_data') or context.bot_data is None: context.bot_data = {}
                context.bot_data[f"msg_cache_{self.chat_id}_{sent_message.message_id}"] = sent_message
                if context.job_queue:
                     context.job_queue.run_once(
                        question_timeout_callback_wrapper, 
                        self.question_time_limit,
                        chat_id=self.chat_id,
                        user_id=user_id,
                        name=timer_job_name,
                        data={"quiz_id": self.quiz_id, "question_index": self.current_question_index, "user_id": user_id, "chat_id": self.chat_id, "message_id": sent_message.message_id, "question_was_image": self.last_question_is_image}
                    )
                else: logger.error(f"[QuizLogic {self.quiz_id}] JobQueue not available for user {user_id}.")
                return TAKING_QUIZ 
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to send question (q_id: {q_id_log}). Skipping.")
                self.answers.append({"question_id": q_id_log, "is_correct": False, "chosen_option_text": "خطأ في إرسال السؤال", "correct_option_text": "-", "time_taken": -997})
                self.current_question_index += 1
                continue
        
        logger.info(f"[QuizLogic {self.quiz_id}] No more valid questions. User {user_id}. Showing results.")
        return await self.show_results(bot, context, user_id)

    def _get_correct_option_text_robust(self, current_question_data):
        correct_option_id_from_data = str(current_question_data.get("correct_option_id"))
        options_for_current_q = current_question_data.get("options", [])
        retrieved_correct_option_text = "نص الإجابة الصحيحة غير متوفر"
        if not correct_option_id_from_data or correct_option_id_from_data == 'None': return "لم يتم تحديد إجابة صحيحة للسؤال"
        for opt_detail in options_for_current_q:
            if str(opt_detail.get("option_id")) == correct_option_id_from_data:
                if opt_detail.get("is_image_option"):
                    retrieved_correct_option_text = f"صورة ({opt_detail.get('image_option_display_label', correct_option_id_from_data)})"
                else: retrieved_correct_option_text = opt_detail.get("option_text", f"خيار نصي ({correct_option_id_from_data})")
                return retrieved_correct_option_text
        return f"خطأ: الإجابة (معرف: {correct_option_id_from_data}) غير موجودة"

    async def handle_answer(self, bot: Bot, context: CallbackContext, update: Update) -> int:
        query = update.callback_query
        user_id = query.from_user.id
        current_q_data_for_answer = self.questions_data[self.current_question_index]
        q_id_for_answer = current_q_data_for_answer.get('question_id', f'q_idx_{self.current_question_index}')
        correct_option_id = str(current_q_data_for_answer.get("correct_option_id"))
        callback_parts = query.data.split("_")
        chosen_option_id_from_cb = callback_parts[-1]
        is_correct_ans = (str(chosen_option_id_from_cb) == correct_option_id)
        if is_correct_ans: self.score += 1
        time_taken = time.time() - self.question_start_time if self.question_start_time else -1
        chosen_option_obj = next((opt for opt in current_q_data_for_answer.get("options", []) if str(opt.get("option_id")) == str(chosen_option_id_from_cb)), None)
        chosen_option_text = chosen_option_obj.get("option_text", "N/A") if chosen_option_obj else "N/A"
        if chosen_option_obj and chosen_option_obj.get("is_image_option"): chosen_option_text = f"صورة ({chosen_option_obj.get('image_option_display_label')})"
        
        self.answers.append({
            "question_id": q_id_for_answer, "question_text": current_q_data_for_answer.get("question_text", "N/A"),
            "chosen_option_id": chosen_option_id_from_cb, "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id, "correct_option_text": self._get_correct_option_text_robust(current_q_data_for_answer),
            "is_correct": is_correct_ans, "time_taken": time_taken
        })
        
        if self.db_quiz_session_id and self.active:
            try:
                log_question_interaction(quiz_session_id=self.db_quiz_session_id, user_id=self.user_id, 
                                         question_id=str(q_id_for_answer), is_correct=is_correct_ans, 
                                         user_answer=str(chosen_option_id_from_cb), attempts=1)
                logger.info(f"[QuizLogic {self.quiz_id}] Logged Q interaction to DB. Session {self.db_quiz_session_id}, Q {q_id_for_answer}")
            except Exception as e_db_log_q: 
                logger.error(f"[QuizLogic {self.quiz_id}] DB log Q interaction failed: {e_db_log_q}", exc_info=True)

        timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        
        if self.last_question_message_id:
            try: 
                await bot.delete_message(chat_id=self.chat_id, message_id=self.last_question_message_id)
                logger.debug(f"[QuizLogic {self.quiz_id}] Deleted previous question message {self.last_question_message_id} for user {user_id}")
            except telegram.error.BadRequest as e_del_msg:
                if "message to delete not found" in str(e_del_msg).lower() or \
                   "message can't be deleted" in str(e_del_msg).lower():
                    logger.warning(f"[QuizLogic {self.quiz_id}] Previous question message {self.last_question_message_id} not found or can't be deleted for user {user_id}. It might have been deleted already or is too old.")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Error deleting previous question message {self.last_question_message_id} for user {user_id}: {e_del_msg}")
            except Exception as e_del_gen:
                 logger.error(f"[QuizLogic {self.quiz_id}] Unexpected error deleting previous question message {self.last_question_message_id} for user {user_id}: {e_del_gen}")
            self.last_question_message_id = None

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            return await self.send_question(bot, context, user_id)
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz finished for user {user_id}. Total questions: {self.total_questions}, Score: {self.score}")
            return await self.show_results(bot, context, user_id)

    async def show_results(self, bot: Bot, context: CallbackContext, user_id: int, called_from_timeout: bool = False) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] show_results. User: {user_id}, Chat: {self.chat_id}, Timeout: {called_from_timeout}, DB Session: {self.db_quiz_session_id}")
        quiz_status = 'timed_out' if called_from_timeout else 'completed'
        
        if self.db_quiz_session_id and self.active: 
            try:
                log_quiz_end(self.db_quiz_session_id, self.score, status=quiz_status)
                logger.info(f"[QuizLogic {self.quiz_id}] Logged quiz end to DB. Session {self.db_quiz_session_id}, Score: {self.score}, Status: {quiz_status}")
            except Exception as e_db_log_end: 
                logger.error(f"[QuizLogic {self.quiz_id}] DB log quiz end failed: {e_db_log_end}", exc_info=True)
        
        self.active = False 
        results_text = f"<b>نتائج الاختبار ({self.quiz_name}):</b>\n"
        results_text += f"عدد الأسئلة: {self.total_questions}\n"
        results_text += f"النتيجة: {self.score} من {self.total_questions}\n\n"
        
        for i, ans in enumerate(self.answers):
            q_text = ans.get("question_text", f"سؤال {i+1}")
            chosen_opt_text = ans.get("chosen_option_text", "لم يتم الاختيار")
            correct_opt_text = ans.get("correct_option_text", "-")
            is_corr = ans.get("is_correct", False)
            time_t = ans.get("time_taken", 0)
            status_emoji = "✅" if is_corr else ("❌" if chosen_opt_text != "تم تخطي السؤال (خيارات غير كافية)" and chosen_opt_text != "خطأ في إرسال السؤال" and chosen_opt_text != "انتهى وقت السؤال" else "⚠️")
            
            results_text += f"<b>{status_emoji} السؤال {i+1}:</b> {q_text}\n"
            results_text += f"   إجابتك: {chosen_opt_text}\n"
            if not is_corr and chosen_opt_text != "تم تخطي السؤال (خيارات غير كافية)" and chosen_opt_text != "خطأ في إرسال السؤال" and chosen_opt_text != "انتهى وقت السؤال":
                results_text += f"   الإجابة الصحيحة: {correct_opt_text}\n"
            results_text += f"   الوقت المستغرق: {time_t:.2f} ثانية\n\n"

        results_text += "شكراً لك على المشاركة!"
        
        # --- PRESERVED ORIGINAL UI BUTTONS ---
        keyboard_buttons = [
            [InlineKeyboardButton("إعادة الاختبار", callback_data=f"restart_quiz_{self.quiz_type}")], # Assuming quiz_type is suitable for restart
            [InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard_buttons)
        # -------------------------------------

        message_to_edit_id = context.user_data.pop(f"quiz_start_message_id_{self.chat_id}", None)
        if not message_to_edit_id and update and update.callback_query:
             message_to_edit_id = update.callback_query.message.message_id

        logger.debug(f"[QuizLogic {self.quiz_id}] Showing results for user {user_id}, chat {self.chat_id}. Message to edit: {message_to_edit_id}")
        if message_to_edit_id:
            try:
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_to_edit_id, text=results_text, reply_markup=reply_markup, parse_mode="HTML")
            except telegram.error.BadRequest as e:
                if "message is not modified" in str(e).lower():
                    logger.warning(f"[QuizLogic {self.quiz_id}] Message not modified for results: {e}. Content might be identical.")
                elif "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower():
                    logger.warning(f"[QuizLogic {self.quiz_id}] Message to edit for results not found or can't be edited: {e}. Sending new message.")
                    await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=reply_markup, parse_mode="HTML")
                elif "there is no text in the message to edit" in str(e).lower():
                    logger.error(f"[QuizLogic {self.quiz_id}] Attempted to edit a message with no text (e.g., photo only) for results: {e}. Sending new message.")
                    # Try deleting the photo message if it was the one we were trying to edit, then send new.
                    try: await bot.delete_message(chat_id=self.chat_id, message_id=message_to_edit_id)
                    except: pass # Ignore if deletion fails
                    await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=reply_markup, parse_mode="HTML")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to edit message {message_to_edit_id} in chat {self.chat_id} (BadRequest): {e}")
                    await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=reply_markup, parse_mode="HTML") # Fallback
            except Exception as e_edit_results:
                logger.error(f"[QuizLogic {self.quiz_id}] Unexpected error editing results message: {e_edit_results}")
                await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=reply_markup, parse_mode="HTML") # Fallback
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] No message_id to edit for results. Sending new message.")
            await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=reply_markup, parse_mode="HTML")

        await self.cleanup_quiz_data(context, user_id, "results_shown")
        return SHOWING_RESULTS 

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.debug(f"[QuizLogic {self.quiz_id}] cleanup_quiz_data called for user {user_id}. Reason: {reason}")
        self.active = False 
        # Clean up any pending timers for this quiz instance
        for i in range(self.total_questions):
            timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{i}"
            remove_job_if_exists(timer_job_name, context)
        
        # Clear specific quiz instance from user_data if it was stored there
        if context.user_data.get(f"quiz_instance_{self.chat_id}") == self:
            context.user_data.pop(f"quiz_instance_{self.chat_id}", None)
            logger.debug(f"[QuizLogic {self.quiz_id}] Removed self from user_data for chat {self.chat_id}")

    async def end_quiz_command(self, bot: Bot, context: CallbackContext, update: Update, user_id: int) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] end_quiz_command called by user {user_id}. DB Session: {self.db_quiz_session_id}")
        if self.db_quiz_session_id and self.active:
            try:
                log_quiz_end(self.db_quiz_session_id, self.score, status='cancelled_by_user')
                logger.info(f"[QuizLogic {self.quiz_id}] Logged quiz end (cancelled by user) to DB. Session {self.db_quiz_session_id}")
            except Exception as e_db_log_cancel: 
                logger.error(f"[QuizLogic {self.quiz_id}] DB log quiz end (cancelled by user) failed: {e_db_log_cancel}", exc_info=True)
        
        self.active = False
        await self.cleanup_quiz_data(context, user_id, "ended_by_command")
        
        message_text = "تم إنهاء الاختبار بناءً على طلبك."
        keyboard = [[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Try to edit the last question message, or the quiz start message, or send a new one
        message_to_edit_id = self.last_question_message_id or context.user_data.get(f"quiz_start_message_id_{self.chat_id}")
        if update and update.callback_query and update.callback_query.message: # If called from a button
             message_to_edit_id = update.callback_query.message.message_id

        if message_to_edit_id:
            await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_to_edit_id, text=message_text, reply_markup=reply_markup)
        else:
            await safe_send_message(bot, chat_id=self.chat_id, text=message_text, reply_markup=reply_markup)
        
        return END # Or MAIN_MENU depending on desired flow after cancellation

async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    quiz_id_from_job = job_data["quiz_id"]
    question_index_from_job = job_data["question_index"]
    user_id = job_data["user_id"]
    chat_id = job_data["chat_id"]
    message_id_from_job = job_data["message_id"]
    question_was_image = job_data.get("question_was_image", False)

    logger.info(f"[QuizLogic {quiz_id_from_job}] Question timeout for user {user_id}, q_idx {question_index_from_job}")
    quiz_instance = context.user_data.get(f"quiz_instance_{chat_id}")

    if quiz_instance and quiz_instance.quiz_id == quiz_id_from_job and quiz_instance.active and quiz_instance.current_question_index == question_index_from_job:
        logger.info(f"[QuizLogic {quiz_id_from_job}] Processing timeout for active question {question_index_from_job}")
        current_q_data_timeout = quiz_instance.questions_data[question_index_from_job]
        q_id_timeout = current_q_data_timeout.get('question_id', f'q_idx_{question_index_from_job}')
        
        quiz_instance.answers.append({
            "question_id": q_id_timeout, "question_text": current_q_data_timeout.get("question_text", "N/A"),
            "chosen_option_id": "TIMEOUT", "chosen_option_text": "انتهى وقت السؤال",
            "correct_option_id": str(current_q_data_timeout.get("correct_option_id")),
            "correct_option_text": quiz_instance._get_correct_option_text_robust(current_q_data_timeout),
            "is_correct": False, "time_taken": quiz_instance.question_time_limit
        })

        if quiz_instance.db_quiz_session_id and quiz_instance.active:
            try:
                log_question_interaction(quiz_session_id=quiz_instance.db_quiz_session_id, user_id=user_id, 
                                         question_id=str(q_id_timeout), is_correct=False, 
                                         user_answer="TIMEOUT", attempts=1) # attempts can be refined if needed
                logger.info(f"[QuizLogic {quiz_id_from_job}] Logged Q TIMEOUT to DB. Session {quiz_instance.db_quiz_session_id}, Q {q_id_timeout}")
            except Exception as e_db_log_q_timeout: 
                logger.error(f"[QuizLogic {quiz_id_from_job}] DB log Q TIMEOUT failed: {e_db_log_q_timeout}", exc_info=True)

        # Try to edit the timed-out question message to indicate timeout
        timeout_text = "انتهى وقت السؤال! "
        if message_id_from_job:
            try:
                if question_was_image:
                    # For image questions, we might not be able to edit the caption with a new keyboard easily.
                    # Sending a new message might be better, or just deleting the old one.
                    await context.bot.delete_message(chat_id=chat_id, message_id=message_id_from_job)
                    await safe_send_message(context.bot, chat_id=chat_id, text=timeout_text)
                else:
                    await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=message_id_from_job, text=timeout_text, reply_markup=None) # Remove keyboard
            except telegram.error.BadRequest as e_edit_timeout:
                 logger.warning(f"[QuizLogic {quiz_id_from_job}] Failed to edit timed-out question message: {e_edit_timeout}")
            except Exception as e_edit_timeout_gen:
                 logger.error(f"[QuizLogic {quiz_id_from_job}] Unexpected error editing timed-out question message: {e_edit_timeout_gen}")

        quiz_instance.current_question_index += 1
        if quiz_instance.current_question_index < quiz_instance.total_questions:
            await quiz_instance.send_question(context.bot, context, user_id)
        else:
            logger.info(f"[QuizLogic {quiz_id_from_job}] Quiz finished due to timeout on last question for user {user_id}.")
            await quiz_instance.show_results(context.bot, context, user_id, called_from_timeout=True)
    else:
        logger.warning(f"[QuizLogic {quiz_id_from_job}] Timeout callback for an old/inactive quiz or mismatched question index. User {user_id}. No action taken.")

