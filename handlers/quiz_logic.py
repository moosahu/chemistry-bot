"""Manages the logic for conducting a quiz, including sending questions, handling answers, and calculating results."""
# handlers/quiz_logic.py (NAMEERROR_FIX)

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

MIN_OPTIONS_PER_QUESTION = 2

class QuizLogic:
    ARABIC_CHOICE_LETTERS = ["أ", "ب", "ج", "د"]

    def __init__(self, user_id, chat_id, questions, quiz_name,
                 quiz_type_for_db_log, quiz_scope_id, total_questions_for_db_log,
                 time_limit_per_question, quiz_instance_id_for_logging, 
                 db_manager_instance):
        
        self.user_id = user_id
        self.chat_id = chat_id
        self.questions_data = questions if questions is not None else []
        self.quiz_name = quiz_name if quiz_name else "اختبار غير مسمى"
        
        self.quiz_type_for_db = quiz_type_for_db_log
        self.quiz_scope_id_for_db = quiz_scope_id 
        self.total_questions_for_db = total_questions_for_db_log

        self.question_time_limit = time_limit_per_question
        self.quiz_id = quiz_instance_id_for_logging 
        
        self.db_manager = db_manager_instance
        
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
            logger.critical(f"[QuizLogic {self.quiz_id}] CRITICAL: db_manager_instance was None at __init__! Database operations will fail.")
        
        self.total_questions = len(self.questions_data)
        if self.total_questions != self.total_questions_for_db:
             logger.warning(f"[QuizLogic {self.quiz_id}] Mismatch: total_questions_for_db ({self.total_questions_for_db}) vs actual len(questions_data) ({self.total_questions}). Using actual len for quiz flow, but total_questions_for_db for initial DB log.")

        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized. User: {self.user_id}, Chat: {self.chat_id}, QuizName: \'{self.quiz_name}\', DBQuizType: {self.quiz_type_for_db}, DBScopeID: {self.quiz_scope_id_for_db}, NumQsForDB: {self.total_questions_for_db}, ActualNumQs: {self.total_questions}. DB Manager Present: {bool(self.db_manager)}")

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
        
        return await self.send_question(bot, context, update) # Pass update here
    
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
            
            if len(button_text_str.encode(\'utf-8\')) > 60: 
                temp_bytes = button_text_str.encode(\'utf-8\')[:57] 
                button_text_str = temp_bytes.decode(\'utf-8\', \'ignore\') + "..."

            callback_data = f"ans_{self.quiz_id}_{self.current_question_index}_{option_id}"
            keyboard.append([InlineKeyboardButton(text=button_text_str, callback_data=callback_data)])
        return InlineKeyboardMarkup(keyboard)

    async def send_question(self, bot: Bot, context: CallbackContext, update: Update = None): # Added update: Update = None
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] send_question: inactive. User {self.user_id}. Aborting.")
            return END 

        while self.current_question_index < self.total_questions:
            current_question_data = self.questions_data[self.current_question_index]
            q_id_log = current_question_data.get(\'question_id\', f\'q_idx_{self.current_question_index}\')
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
                        current_option_proc[\'is_image_option\'] = True
                        current_option_proc[\'image_option_display_label\'] = display_label 
                        option_image_counter += 1 
                        await asyncio.sleep(0.3) 
                    except Exception as e_img_opt:
                        logger.error(f"[QuizLogic {self.quiz_id}] Failed to send image option {i} (URL: {option_text_original}), q_id {q_id_log}: {e_img_opt}", exc_info=True)
                        current_option_proc[\'is_image_option\'] = False
                        current_option_proc[\'image_option_display_label\'] = None 
                else:
                    current_option_proc[\'is_image_option\'] = False 
                    current_option_proc[\'image_option_display_label\'] = None
                processed_options.append(current_option_proc)
            
            current_question_data[\'options\'] = processed_options 
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
                self.question_start_time = time.time()
                if self.question_time_limit > 0:
                    timer_job_name = f"question_timer_{self.quiz_id}_{self.current_question_index}"
                    remove_job_if_exists(timer_job_name, context)
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
                    logger.debug(f"[QuizLogic {self.quiz_id}] Timeout job \'{timer_job_name}\' scheduled for {self.question_time_limit}s for q_idx {self.current_question_index}")
                return TAKING_QUIZ 
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] sent_message was None after attempting to send q_idx {self.current_question_index}. This shouldn\'t happen if continue was hit.")
                await safe_send_message(bot, self.chat_id, "حدث خطأ غير متوقع أثناء محاولة عرض السؤال التالي. سيتم إنهاء الاختبار.")
                await self.cleanup_quiz_data(context, self.user_id, "send_question_critical_failure")
                return END

        logger.info(f"[QuizLogic {self.quiz_id}] All questions sent for user {self.user_id}.")
        return await self.show_results(bot, context, update) # update is now passed from the caller (handle_answer or start_quiz)

    async def handle_answer(self, update: Update, context: CallbackContext, **kwargs):
        if not self.active:
            logger.warning(f"[QuizLogic N/A] handle_answer: inactive quiz instance for user {self.user_id}. Callback: {update.callback_query.data if update.callback_query else \'NoCallback\'}. Aborting.")
            if update.callback_query:
                try:
                    await update.callback_query.answer(text="هذا الاختبار لم يعد نشطاً.")
                except Exception as e_ans_inactive:
                    logger.error(f"[QuizLogic N/A] Error sending inactive answer confirmation: {e_ans_inactive}")
            return TAKING_QUIZ

        query = update.callback_query
        await query.answer()

        try:
            parts = query.data.split("_")
            if len(parts) < 4 or parts[0] != "ans":
                raise ValueError("Callback data does not match expected format \'ans_quizid_qindex_optid\' or is too short.")
            
            chosen_option_id = parts[-1]
            q_index_str = parts[-2]
            quiz_id_from_cb = "_".join(parts[1:-2])
            q_index_from_cb = int(q_index_str)
        except (ValueError, IndexError) as e:
            logger.error(f"[QuizLogic {self.quiz_id if hasattr(self, \'quiz_id\') else \'CB_PARSE_FAIL\'}] Invalid callback_data format: {query.data}. Error: {e}")
            await safe_edit_message_text(context.bot, self.chat_id, query.message.message_id, "حدث خطأ في معالجة إجابتك (بيانات خاطئة).", reply_markup=None)
            return TAKING_QUIZ

        if not hasattr(self, \'quiz_id\') or self.quiz_id != quiz_id_from_cb:
            logger.warning(f"[QuizLogic {self.quiz_id if hasattr(self, \'quiz_id\') else \'N/A\'}] Mismatched quiz_id in callback. Instance: {self.quiz_id}, CB: {quiz_id_from_cb}. User {self.user_id}. Ignoring.")
            try:
                await query.edit_message_text(text=query.message.text + "\n\n(إجابة من اختبار سابق أو غير صالح)", reply_markup=None)
            except Exception as e_edit_old:
                logger.debug(f"[QuizLogic {self.quiz_id if hasattr(self, \'quiz_id\') else \'N/A\'}] Failed to edit message for old/mismatched quiz answer: {e_edit_old}")
            return TAKING_QUIZ 

        if self.current_question_index != q_index_from_cb:
            logger.warning(f"[QuizLogic {self.quiz_id}] Mismatched question_index in callback. Current: {self.current_question_index}, CB: {q_index_from_cb}. User {self.user_id}. Ignoring (likely late answer).")
            try:
                await query.edit_message_text(text=query.message.text + "\n\n(إجابة متأخرة لسؤال سابق)", reply_markup=None)
            except Exception as e_edit_late:
                logger.debug(f"[QuizLogic {self.quiz_id}] Failed to edit message for late answer: {e_edit_late}")
            return TAKING_QUIZ

        time_taken = -1
        if self.question_start_time:
            time_taken = time.time() - self.question_start_time
        
        timer_job_name = f"question_timer_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        logger.debug(f"[QuizLogic {self.quiz_id}] Answer received for q_idx {self.current_question_index}. Timer job \'{timer_job_name}\' removed if it existed.")

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get(\'question_id\', f\'q_idx_{self.current_question_index}\')
        options = current_question_data.get("options", [])
        correct_option_id = current_question_data.get("correct_option_id")
        
        chosen_option_text = f"(خيار ID: {chosen_option_id} غير موجود)" 
        is_correct = False
        option_found = False

        for option_data in options:
            if str(option_data.get("option_id")) == str(chosen_option_id):
                option_found = True
                if option_data.get(\'is_image_option\'):
                    img_label = option_data.get(\'image_option_display_label\')
                    chosen_option_text = f"الخيار المصور: {img_label}" if img_label else f"(صورة الخيار {chosen_option_id})"
                else:
                    opt_text = option_data.get("option_text")
                    chosen_option_text = opt_text if opt_text and str(opt_text).strip() else f"(نص الخيار {chosen_option_id} فارغ)"
                
                if correct_option_id is not None and str(chosen_option_id) == str(correct_option_id):
                    self.score += 1
                    is_correct = True
                elif correct_option_id is None:
                    is_correct = None 
                break
        
        if not option_found:
            logger.warning(f"[QuizLogic {self.quiz_id}] Chosen option ID {chosen_option_id} not found in question {self.current_question_index} options.")

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

        try:
            caption_or_text_to_edit = query.message.caption_html if query.message.photo else query.message.text_html
            if not caption_or_text_to_edit: 
                caption_or_text_to_edit = query.message.caption if query.message.photo else query.message.text
            if not caption_or_text_to_edit: 
                caption_or_text_to_edit = "" 

            safe_chosen_opt_text = chosen_option_text if chosen_option_text is not None else "(خطأ في عرض الخيار)"

            if query.message.photo:
                await query.edit_message_caption(caption=caption_or_text_to_edit + f"\n<i><b>إجابتك ({safe_chosen_opt_text}) تم تسجيلها.</b></i>", reply_markup=None, parse_mode=\'HTML\')
            else:
                await query.edit_message_text(text=caption_or_text_to_edit + f"\n<i><b>إجابتك ({safe_chosen_opt_text}) تم تسجيلها.</b></i>", reply_markup=None, parse_mode=\'HTML\')
            logger.debug(f"[QuizLogic {self.quiz_id}] Edited message for q_idx {self.current_question_index} after answer.")
        except telegram.error.BadRequest as e:
            if "message is not modified" in str(e).lower():
                logger.debug(f"[QuizLogic {self.quiz_id}] Message for q_idx {self.current_question_index} not modified, or already changed: {e}")
            else:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message for q_idx {self.current_question_index} after answer: {e}")
        except Exception as e_edit:
            logger.warning(f"[QuizLogic {self.quiz_id}] Generic fail to edit message for q_idx {self.current_question_index} after answer: {e_edit}")

        self.current_question_index += 1
        return await self.send_question(context.bot, context, update) # Pass update here

    async def handle_timeout(self, bot: Bot, context: CallbackContext): # Does not have update, so send_question will get update=None
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] handle_timeout: inactive. User {self.user_id}. Aborting.")
            return TAKING_QUIZ

        logger.info(f"[QuizLogic {self.quiz_id}] Timeout for q_idx {self.current_question_index}, user {self.user_id}")
        
        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get(\'question_id\', f\'q_idx_{self.current_question_index}\')

        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", ""),
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": current_question_data.get("correct_option_id"),
            "correct_option_text": self._get_correct_option_text_robust(current_question_data),
            "is_correct": False,
            "time_taken": self.question_time_limit,
            "status": "timeout"
        })
        
        self.current_question_index += 1
        return await self.send_question(bot, context) # update will be None by default in send_question signature

    def _get_correct_option_text_robust(self, question_data, for_skip=False):
        correct_option_id = question_data.get("correct_option_id")
        if correct_option_id is None:
            return "(لا توجد إجابة صحيحة محددة)" if not for_skip else "(غير محدد)"

        options = question_data.get("options", [])
        for option in options:
            if str(option.get("option_id")) == str(correct_option_id):
                if option.get(\'is_image_option\'):
                    img_label = option.get(\'image_option_display_label\')
                    return f"الخيار المصور: {img_label}" if img_label else f"(صورة الخيار {correct_option_id})"
                
                opt_text = option.get("option_text")
                return opt_text if opt_text and str(opt_text).strip() else f"(نص الخيار الصحيح {correct_option_id} فارغ)"
        
        return f"(لم يتم العثور على نص الخيار الصحيح ID: {correct_option_id})"

    async def show_results(self, bot: Bot, context: CallbackContext, update: Update = None): # update is optional
        logger.info(f"[QuizLogic {self.quiz_id}] show_results called for user {self.user_id}. Score: {self.score}/{self.total_questions}")
        if not self.active and not self.answers:
            logger.warning(f"[QuizLogic {self.quiz_id}] show_results called but quiz was not active and no answers recorded. Sending generic end message.")
            message_to_edit_id = None
            if update and update.callback_query and update.callback_query.message: # Safely use update
                message_to_edit_id = update.callback_query.message.message_id
            elif self.last_question_message_id:
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

        summary = f"<b>ملخص اختبار \'{self.quiz_name if self.quiz_name else \'غير مسمى\'}\' الخاص بك:</b>\n"
        summary += f"مجموع النقاط: {self.score} من {self.total_questions}\n\n"

        for i, ans_data in enumerate(self.answers):
            q_text = ans_data.get("question_text") or f"(نص السؤال {i+1} غير متوفر)"
            chosen_opt_text = ans_data.get("chosen_option_text")
            correct_opt_text = ans_data.get("correct_option_text") or "(الإجابة الصحيحة غير محددة)"
            is_corr = ans_data.get("is_correct")
            status = ans_data.get("status", "unknown")

            summary += f"<b>السؤال {i+1}:</b> {q_text}\n"
            
            chosen_opt_display = chosen_opt_text
            if chosen_opt_text is None or str(chosen_opt_text).strip() == "" or str(chosen_opt_text).strip().upper() == "N/A":
                if status == "timeout":
                    chosen_opt_display = "انتهى الوقت"
                elif status == "skipped_auto":
                    chosen_opt_display = "تم تخطي السؤال (خيارات غير كافية)"
                elif status == "error_sending":
                     chosen_opt_display = "خطأ في إرسال السؤال"
                else:
                    chosen_opt_display = "(لم تتم الإجابة أو خطأ في تسجيلها)"
                    
            correct_opt_display = correct_opt_text
            if correct_opt_text is None or str(correct_opt_text).strip() == "":
                correct_opt_display = "(الإجابة الصحيحة غير متوفرة)"

            if status == "answered":
                corr_status_text = ""
                if is_corr is True:
                    corr_status_text = "صحيحة"
                elif is_corr is False:
                    corr_status_text = "خاطئة"
                else: 
                    corr_status_text = "(لا يوجد تصحيح)"
                summary += f"إجابتك: {chosen_opt_display} ({corr_status_text})\n"
                if not is_corr and is_corr is not None:
                    summary += f"الإجابة الصحيحة: {correct_opt_display}\n"
            elif status == "timeout":
                summary += f"إجابتك: {chosen_opt_display}\n"
                summary += f"الإجابة الصحيحة: {correct_opt_display}\n"
            elif status == "skipped_auto":
                summary += f"الحالة: {chosen_opt_display}\n"
            elif status == "error_sending":
                summary += f"الحالة: {chosen_opt_display}\n"
            else:
                summary += f"إجابتك: {chosen_opt_display}\n"

            summary += "\n"

        final_text = summary.strip()
        keyboard = [[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message_to_edit_id = None
        if update and update.callback_query and update.callback_query.message: # Safely use update
            message_to_edit_id = update.callback_query.message.message_id
        elif self.last_question_message_id:
            message_to_edit_id = self.last_question_message_id
            logger.info(f"[QuizLogic {self.quiz_id}] show_results: Using last_question_message_id ({message_to_edit_id}) for editing results as update was not provided or didn\'t have a message.")

        if message_to_edit_id:
            try:
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_to_edit_id, text=final_text, reply_markup=reply_markup, parse_mode="HTML")
                logger.info(f"[QuizLogic {self.quiz_id}] Successfully edited message {message_to_edit_id} with results.")
            except telegram.error.BadRequest as e_edit_results:
                logger.error(f"[QuizLogic {self.quiz_id}] Error editing message {message_to_edit_id} with results: {e_edit_results}. Sending new message instead.")
                try:
                    await safe_send_message(bot, chat_id=self.chat_id, text=final_text, reply_markup=reply_markup, parse_mode="HTML")
                    logger.info(f"[QuizLogic {self.quiz_id}] Successfully sent new message with results after edit failed.")
                except Exception as e_send_results_fallback:
                    logger.error(f"[QuizLogic {self.quiz_id}] Critical error: Failed to send new message with results: {e_send_results_fallback}", exc_info=True)
                    await safe_send_message(bot, chat_id=self.chat_id, text="انتهى الاختبار. حدث خطأ أثناء عرض النتائج التفصيلية.", reply_markup=reply_markup)
            except Exception as e_edit_results_generic:
                logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message {message_to_edit_id} with results: {e_edit_results_generic}. Sending new message instead.", exc_info=True)
                try:
                    await safe_send_message(bot, chat_id=self.chat_id, text=final_text, reply_markup=reply_markup, parse_mode="HTML")
                except Exception as e_send_results_fallback_generic:
                     logger.error(f"[QuizLogic {self.quiz_id}] Critical error: Failed to send new message with results (generic edit fail): {e_send_results_fallback_generic}", exc_info=True)
                     await safe_send_message(bot, chat_id=self.chat_id, text="انتهى الاختبار. حدث خطأ أثناء عرض النتائج التفصيلية.", reply_markup=reply_markup)
        else: 
            logger.info(f"[QuizLogic {self.quiz_id}] No message_id available to edit for results. Sending new message.")
            try:
                await safe_send_message(bot, chat_id=self.chat_id, text=final_text, reply_markup=reply_markup, parse_mode="HTML")
                logger.info(f"[QuizLogic {self.quiz_id}] Successfully sent new message with results.")
            except Exception as e_send_results_new:
                logger.error(f"[QuizLogic {self.quiz_id}] Critical error: Failed to send new message with results: {e_send_results_new}", exc_info=True)
                await safe_send_message(bot, chat_id=self.chat_id, text="انتهى الاختبار. حدث خطأ أثناء عرض النتائج التفصيلية.", reply_markup=reply_markup)

        if self.db_manager and self.db_quiz_session_id:
            try:
                self.db_manager.log_quiz_completion(
                    quiz_session_uuid=self.db_quiz_session_id,
                    user_id=self.user_id,
                    answers_details=self.answers,
                    final_score=self.score,
                    total_questions_answered=len(self.answers),
                    completion_time=datetime.now(timezone.utc)
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Quiz completion logged to DB for session {self.db_quiz_session_id}.")
            except Exception as e_db_complete:
                logger.error(f"[QuizLogic {self.quiz_id}] Exception while logging quiz completion to DB for session {self.db_quiz_session_id}: {e_db_complete}", exc_info=True)
        elif not self.db_manager:
             logger.warning(f"[QuizLogic {self.quiz_id}] db_manager is not available. Cannot log quiz completion to DB.")
        elif not self.db_quiz_session_id:
             logger.warning(f"[QuizLogic {self.quiz_id}] db_quiz_session_id is None. Cannot log quiz completion to DB (likely quiz start failed to log).")

        await self.cleanup_quiz_data(context, self.user_id, "quiz_completed_show_results")
        return END

    async def cleanup_quiz_data(self, context: CallbackContext, user_id_to_clean, reason: str):
        logger.info(f"[QuizLogic {self.quiz_id if hasattr(self, \'quiz_id\') else \'N/A\'}] Cleaning up quiz data for user {user_id_to_clean}. Reason: {reason}")
        self.active = False
        
        if context.chat_data and isinstance(context.chat_data.get(\'active_quizzes\'), dict):
            active_quiz_key = str(user_id_to_clean)
            if active_quiz_key in context.chat_data[\'active_quizzes\']:
                if hasattr(self, \'quiz_id\') and context.chat_data[\'active_quizzes\'][active_quiz_key].quiz_id == self.quiz_id:
                    del context.chat_data[\'active_quizzes\'][active_quiz_key]
                    logger.info(f"[QuizLogic {self.quiz_id}] Instance removed from chat_data for user {user_id_to_clean}.")
                elif not hasattr(self, \'quiz_id\'):
                    del context.chat_data[\'active_quizzes\'][active_quiz_key]
                    logger.info(f"[QuizLogic N/A] Instance (no specific quiz_id) removed from chat_data for user {user_id_to_clean} during cleanup.")
                else:
                    logger.warning(f"[QuizLogic {self.quiz_id}] Did not remove quiz from chat_data for user {user_id_to_clean} as quiz_id did not match instance in chat_data ({context.chat_data[\'active_quizzes\'][active_quiz_key].quiz_id}).")
            else:
                logger.info(f"[QuizLogic {self.quiz_id if hasattr(self, \'quiz_id\') else \'N/A\'}] No active quiz found in chat_data for user {user_id_to_clean} to remove.")
        elif context.chat_data and \'active_quizzes\' not in context.chat_data:
            logger.info(f"[QuizLogic {self.quiz_id if hasattr(self, \'quiz_id\') else \'N/A\'}] \'active_quizzes\' key not found in chat_data for user {user_id_to_clean}.")
        else: 
            logger.warning(f"[QuizLogic {self.quiz_id if hasattr(self, \'quiz_id\') else \'N/A\'}] chat_data or chat_data[\'active_quizzes\'] is not in the expected state for user {user_id_to_clean}.")

        self.questions_data = []
        self.answers = []
        self.score = 0
        self.current_question_index = 0

async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    quiz_id = job_data.get("quiz_id")
    user_id = job_data.get("user_id")
    chat_id = job_data.get("chat_id")
    question_index = job_data.get("question_index")
    message_id = job_data.get("message_id")
    question_was_image = job_data.get("question_was_image", False)

    logger.info(f"[TimeoutWrapper] Timeout for quiz {quiz_id}, user {user_id}, q_idx {question_index}")

    active_quiz_instance = None
    if context.chat_data and isinstance(context.chat_data.get(\'active_quizzes\'), dict):
        active_quiz_instance = context.chat_data[\'active_quizzes\'].get(str(user_id))
    
    if active_quiz_instance and active_quiz_instance.quiz_id == quiz_id and active_quiz_instance.active and active_quiz_instance.current_question_index == question_index:
        logger.info(f"[TimeoutWrapper] Found active quiz instance for {quiz_id}. Calling handle_timeout.")
        
        timeout_message_text = "انتهى الوقت لهذا السؤال."
        try:
            original_content = ""
            if question_was_image:
                # Attempt to get current caption if possible, otherwise use a generic one
                # This part is tricky as the message might have been edited by other means.
                # For simplicity, we might just append to a generic placeholder or known structure.
                # Let's assume we cannot reliably get the current caption easily here without an `update` object.
                # We will just edit the caption to indicate timeout.
                # A more robust solution might involve storing the original caption/text when the question is sent.
                await safe_edit_message_text(context.bot, chat_id, message_id, caption=timeout_message_text, reply_markup=None, parse_mode=\'HTML\', is_caption=True)
            else:
                await safe_edit_message_text(context.bot, chat_id, message_id, text=timeout_message_text, reply_markup=None, parse_mode=\'HTML\')
            logger.info(f"[TimeoutWrapper] Message {message_id} for q_idx {question_index} edited to show timeout.")
        except Exception as e_edit_timeout:
            logger.warning(f"[TimeoutWrapper] Failed to edit message {message_id} for q_idx {question_index} on timeout: {e_edit_timeout}")        
        
        next_state = await active_quiz_instance.handle_timeout(context.bot, context)
        
        if next_state == END:
            logger.info(f"[TimeoutWrapper] handle_timeout for {quiz_id} returned END. Quiz should be finished.")
        else:
            logger.info(f"[TimeoutWrapper] handle_timeout for {quiz_id} returned {next_state}. Next question likely sent.")
    else:
        logger.warning(f"[TimeoutWrapper] No matching active quiz instance found for {quiz_id}, user {user_id}, q_idx {question_index} or quiz/question state changed. Timer job will not act.")

