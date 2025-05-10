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
        self.last_question_message_id = None # Retained for potential use, but show_results relies on user_data
        self.last_question_is_image = False
        self.active = False
        self.db_quiz_session_id = None

        if not self.db_manager:
            logger.critical(f"[QuizLogic {self.quiz_id}] CRITICAL: db_manager_instance was None at __init__! Database operations will fail.")
        
        self.total_questions = len(self.questions_data)
        if self.total_questions != self.total_questions_for_db:
             logger.warning(f"[QuizLogic {self.quiz_id}] Mismatch: total_questions_for_db ({self.total_questions_for_db}) vs actual len(questions_data) ({self.total_questions}). Using actual len for quiz flow, but total_questions_for_db for initial DB log.")

        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized. User: {self.user_id}, Chat: {self.chat_id}, QuizName: '{self.quiz_name}', DBQuizType: {self.quiz_type_for_db}, DBScopeID: {self.quiz_scope_id_for_db}, NumQsForDB: {self.total_questions_for_db}, ActualNumQs: {self.total_questions}. DB Manager Present: {bool(self.db_manager)}")

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
                # Store the message_id of the question sent in user_data for show_results
                if context and hasattr(context, 'user_data'):
                     context.user_data[f"last_quiz_interaction_message_id_{self.chat_id}"] = sent_message.message_id
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
                    logger.debug(f"[QuizLogic {self.quiz_id}] Timeout job '{timer_job_name}' scheduled for {self.question_time_limit}s for q_idx {self.current_question_index}")
                return TAKING_QUIZ 
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] sent_message was None after attempting to send q_idx {self.current_question_index}. This shouldn't happen if continue was hit.")
                await safe_send_message(bot, self.chat_id, "حدث خطأ غير متوقع أثناء محاولة عرض السؤال التالي. سيتم إنهاء الاختبار.")
                await self.cleanup_quiz_data(context, self.user_id, "send_question_critical_failure")
                return END

        logger.info(f"[QuizLogic {self.quiz_id}] All questions sent for user {self.user_id}.")
        return await self.show_results(bot, context, update)

    async def handle_answer(self, update: Update, context: CallbackContext, **kwargs):
        if not self.active:
            logger.warning(f"[QuizLogic N/A] handle_answer: inactive quiz instance for user {self.user_id}. Callback: {update.callback_query.data if update.callback_query else 'NoCallback'}. Aborting.")
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
                raise ValueError("Callback data does not match expected format 'ans_quizid_qindex_optid' or is too short.")
            
            chosen_option_id = parts[-1]
            q_index_str = parts[-2]
            quiz_id_from_cb = "_".join(parts[1:-2])
            q_index_from_cb = int(q_index_str)
        except (ValueError, IndexError) as e:
            logger.error(f"[QuizLogic {self.quiz_id if hasattr(self, 'quiz_id') else 'CB_PARSE_FAIL'}] Invalid callback_data format: {query.data}. Error: {e}")
            await safe_edit_message_text(context.bot, self.chat_id, query.message.message_id, "حدث خطأ في معالجة إجابتك (بيانات خاطئة).", reply_markup=None)
            return TAKING_QUIZ

        if not hasattr(self, 'quiz_id') or self.quiz_id != quiz_id_from_cb:
            logger.warning(f"[QuizLogic {self.quiz_id if hasattr(self, 'quiz_id') else 'N/A'}] Mismatched quiz_id in callback. Instance: {self.quiz_id}, CB: {quiz_id_from_cb}. User {self.user_id}. Ignoring.")
            try:
                await query.edit_message_text(text=query.message.text + "\n\n(إجابة من اختبار سابق أو غير صالح)", reply_markup=None)
            except Exception as e_edit_old:
                logger.debug(f"[QuizLogic {self.quiz_id if hasattr(self, 'quiz_id') else 'N/A'}] Failed to edit message for old/mismatched quiz answer: {e_edit_old}")
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
        logger.debug(f"[QuizLogic {self.quiz_id}] Answer received for q_idx {self.current_question_index}. Timer job '{timer_job_name}' removed if it existed.")

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        options = current_question_data.get("options", [])
        correct_option_id = current_question_data.get("correct_option_id")
        
        chosen_option_text = f"(خيار ID: {chosen_option_id} غير موجود)" 
        is_correct = False
        option_found = False

        for option_data in options:
            if str(option_data.get("option_id")) == str(chosen_option_id):
                option_found = True
                if option_data.get('is_image_option'):
                    img_label = option_data.get('image_option_display_label')
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

            # Store message_id of the edited confirmation message for show_results
            if context and hasattr(context, 'user_data'):
                 context.user_data[f"last_quiz_interaction_message_id_{self.chat_id}"] = query.message.message_id

            if query.message.photo:
                await query.edit_message_caption(caption=caption_or_text_to_edit + f"\n<i><b>إجابتك ({safe_chosen_opt_text}) تم تسجيلها.</b></i>", reply_markup=None, parse_mode='HTML')
            else:
                await query.edit_message_text(text=caption_or_text_to_edit + f"\n<i><b>إجابتك ({safe_chosen_opt_text}) تم تسجيلها.</b></i>", reply_markup=None, parse_mode='HTML')
            logger.debug(f"[QuizLogic {self.quiz_id}] Edited message for q_idx {self.current_question_index} after answer.")
        except telegram.error.BadRequest as e:
            if "message is not modified" in str(e).lower():
                logger.debug(f"[QuizLogic {self.quiz_id}] Message for q_idx {self.current_question_index} not modified, or already changed: {e}")
            else:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message for q_idx {self.current_question_index} after answer: {e}")
        except Exception as e_edit:
            logger.warning(f"[QuizLogic {self.quiz_id}] Generic fail to edit message for q_idx {self.current_question_index} after answer: {e_edit}")

        self.current_question_index += 1
        return await self.send_question(context.bot, context, update)

    async def handle_timeout(self, bot: Bot, context: CallbackContext):
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] handle_timeout: inactive. User {self.user_id}. Aborting.")
            return TAKING_QUIZ

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
            "time_taken": self.question_time_limit,
            "status": "timeout"
        })
        
        # Store message_id of the timed-out question message for show_results (if it was edited or a new one sent)
        # This part is tricky as handle_timeout doesn't always edit the message directly.
        # The timer job has 'message_id' of the question that timed out.
        # For now, we rely on quiz.py to set last_quiz_interaction_message_id correctly.
        # Or, if the question message itself was edited to show timeout, its ID would be relevant.
        # The current timeout logic in quiz.py calls this, then this calls send_question.
        # The message being edited for timeout is handled by question_timeout_callback_wrapper in quiz.py
        # which then calls this handle_timeout method. So the interaction message_id should be set by the wrapper.

        self.current_question_index += 1
        return await self.send_question(bot, context) 

    def _get_correct_option_text_robust(self, question_data, for_skip=False):
        correct_option_id = question_data.get("correct_option_id")
        if correct_option_id is None:
            return "(لا توجد إجابة صحيحة محددة)" if not for_skip else "(غير محدد)"

        options = question_data.get("options", [])
        for option in options:
            if str(option.get("option_id")) == str(correct_option_id):
                if option.get('is_image_option'):
                    img_label = option.get('image_option_display_label')
                    return f"الخيار المصور: {img_label}" if img_label else f"(صورة الخيار {correct_option_id})"
                
                opt_text = option.get("option_text")
                return opt_text if opt_text and str(opt_text).strip() else f"(نص الخيار الصحيح {correct_option_id} فارغ)"
        
        return f"(لم يتم العثور على نص الخيار الصحيح ID: {correct_option_id})"

    async def show_results(self, bot: Bot, context: CallbackContext, update: Update = None):
        logger.info(f"[QuizLogic {self.quiz_id}] show_results called for user {self.user_id}. Score: {self.score}/{self.total_questions}")

        summary_text = f"<b>ملخص اختبار '{self.quiz_name if self.quiz_name else 'غير مسمى'}' الخاص بك:</b>\n"
        summary_text += f"مجموع النقاط: {self.score} من {self.total_questions}\n\n"

        for i, ans_data in enumerate(self.answers):
            q_text = ans_data.get("question_text") or f"(نص السؤال {i+1} غير متوفر)"
            chosen_opt_text = ans_data.get("chosen_option_text")
            correct_opt_text = ans_data.get("correct_option_text") or "(الإجابة الصحيحة غير محددة)"
            is_corr = ans_data.get("is_correct")
            status = ans_data.get("status", "unknown")

            summary_text += f"<b>السؤال {i+1}:</b> {q_text}\n"
            
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
                summary_text += f"إجابتك: {chosen_opt_display} ({corr_status_text})\n"
                if not is_corr and is_corr is not None:
                    summary_text += f"الإجابة الصحيحة: {correct_opt_display}\n"
            elif status == "timeout":
                summary_text += f"إجابتك: {chosen_opt_display}\n"
                summary_text += f"الإجابة الصحيحة: {correct_opt_display}\n"
            elif status == "skipped_auto":
                summary_text += f"الحالة: {chosen_opt_display}\n"
            elif status == "error_sending":
                summary_text += f"الحالة: {chosen_opt_display}\n"
            else:
                summary_text += f"إجابتك: {chosen_opt_display if chosen_opt_display else '(غير مسجلة)'}\n"
                if status != "answered" or (status == "answered" and not is_corr and is_corr is not None):
                     summary_text += f"الإجابة الصحيحة: {correct_opt_display}\n"
            summary_text += "\n"
        
        summary_text += f"\n🎉 نتيجتك النهائية: {self.score} من {self.total_questions} 🎉"
        
        final_text_to_display = summary_text

        keyboard_buttons = [
            [InlineKeyboardButton("ابدأ اختباراً جديداً", callback_data="quiz_menu_entry")],
            [InlineKeyboardButton("📊 عرض إحصائياتي", callback_data="quiz_show_my_stats")],
            [InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard_buttons)

        message_id_to_edit = context.user_data.get(f"last_quiz_interaction_message_id_{self.chat_id}")
        
        edited_successfully = False
        if message_id_to_edit:
            logger.info(f"[QuizLogic {self.quiz_id}] Attempting to edit message {message_id_to_edit} for results.")
            try:
                await bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=message_id_to_edit,
                    text=final_text_to_display,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
                edited_successfully = True
                logger.info(f"[QuizLogic {self.quiz_id}] Successfully edited message {message_id_to_edit} with results.")
            except telegram.error.BadRequest as e_bad_request:
                logger.warning(f"[QuizLogic {self.quiz_id}] BadRequest when editing message {message_id_to_edit} for results: {e_bad_request}. Details: {e_bad_request.message}. Will send new message.")
            except Exception as e_generic_edit:
                logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message {message_id_to_edit} for results: {e_generic_edit}. Will send new message.", exc_info=True)
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] No 'last_quiz_interaction_message_id_{self.chat_id}' found in user_data. Will send new message for results.")

        if not edited_successfully:
            logger.info(f"[QuizLogic {self.quiz_id}] Sending new message for results as edit failed or was not possible.")
            try:
                await bot.send_message(
                    chat_id=self.chat_id,
                    text=final_text_to_display,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Successfully sent new message with results.")
            except Exception as e_send_new:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to send new message with results: {e_send_new}", exc_info=True)
                try:
                    await bot.send_message(chat_id=self.chat_id, text=f"انتهى الاختبار. نتيجتك: {self.score}/{self.total_questions}. حدث خطأ في عرض التفاصيل الكاملة.")
                except Exception as e_fallback_send:
                    logger.critical(f"[QuizLogic {self.quiz_id}] Failed even to send fallback results message: {e_fallback_send}")

        if self.db_manager and self.db_quiz_session_id:
            try:
                quiz_end_time = datetime.now(timezone.utc)
                self.db_manager.log_quiz_completion(
                    quiz_session_uuid=self.db_quiz_session_id,
                    user_id=self.user_id,
                    score=self.score,
                    total_questions_answered=len(self.answers),
                    end_time=quiz_end_time,
                    answers_details=self.answers
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Quiz completion logged to DB for session {self.db_quiz_session_id}")
            except Exception as e_db_complete:
                logger.error(f"[QuizLogic {self.quiz_id}] Error logging quiz completion to DB: {e_db_complete}", exc_info=True)
        elif not self.db_manager:
            logger.warning(f"[QuizLogic {self.quiz_id}] db_manager is not available. Cannot log quiz completion to DB.")
        elif not self.db_quiz_session_id:
            logger.warning(f"[QuizLogic {self.quiz_id}] db_quiz_session_id is None. Cannot log quiz completion to DB.")

        self.active = False 
        await self.cleanup_quiz_data(context, self.user_id, "quiz_completed_show_results")
        return SHOWING_RESULTS

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.debug(f"[QuizLogic {self.quiz_id}] cleanup_quiz_data called for user {user_id}. Reason: {reason}")
        self.active = False
        # Clean up any pending timers associated with this specific quiz instance
        if hasattr(context, 'job_queue') and context.job_queue:
            for job in context.job_queue.jobs():
                if job.name and self.quiz_id in job.name: # Check if quiz_id is part of job name
                    job.schedule_removal()
                    logger.debug(f"[QuizLogic {self.quiz_id}] Removed job: {job.name}")
        
        # Clear quiz-specific data from user_data
        if context.user_data.get("current_quiz_instance_id") == self.quiz_id:
            context.user_data.pop(self.quiz_id, None) # Remove the quiz instance itself
            context.user_data.pop("current_quiz_instance_id", None)
            logger.debug(f"[QuizLogic {self.quiz_id}] Cleared quiz instance and current_quiz_instance_id from user_data for user {user_id}.")
        else:
            # This case might happen if cleanup is called after a new quiz has already started for the user
            # or if current_quiz_instance_id was already cleared. Still attempt to remove the instance by its ID.
            context.user_data.pop(self.quiz_id, None)
            logger.debug(f"[QuizLogic {self.quiz_id}] Cleared quiz instance (by ID) from user_data for user {user_id}. 'current_quiz_instance_id' might have been different or already cleared.")

    async def end_quiz(self, bot: Bot, context: CallbackContext, update: Update, manual_end: bool = False, reason_suffix: str = "ended_manually", called_from_fallback: bool = False):
        logger.info(f"[QuizLogic {self.quiz_id}] end_quiz called for user {self.user_id}. Manual: {manual_end}. Reason suffix: {reason_suffix}. Called from fallback: {called_from_fallback}")
        self.active = False 

        end_message = "تم إنهاء الاختبار."
        if manual_end:
            end_message = "لقد أنهيت الاختبار يدوياً."
        
        # Try to edit the last known message if possible, otherwise send a new one.
        # If called from a fallback (like /start), update.callback_query might not exist.
        message_to_edit_id = None
        chat_id_for_message = self.chat_id

        if not called_from_fallback and update and update.callback_query and update.callback_query.message:
            message_to_edit_id = update.callback_query.message.message_id
            chat_id_for_message = update.callback_query.message.chat_id
        elif self.last_question_message_id: # Fallback to last question message ID if available
            message_to_edit_id = self.last_question_message_id
        # If still no message_id, we'll have to send a new one.

        keyboard_main_menu = InlineKeyboardMarkup([[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]])

        if message_to_edit_id:
            try:
                # Determine if the message to edit was a photo
                # This is tricky without knowing the exact message type. 
                # For simplicity, try editing as text. If it fails with "message can't be edited" or similar, send new.
                await safe_edit_message_text(bot, chat_id=chat_id_for_message, message_id=message_to_edit_id, text=end_message, reply_markup=keyboard_main_menu)
                logger.info(f"[QuizLogic {self.quiz_id}] Edited message {message_to_edit_id} to show quiz ended.")
            except Exception as e_edit_end:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message {message_to_edit_id} on manual end ({e_edit_end}). Sending new message.")
                await safe_send_message(bot, chat_id=chat_id_for_message, text=end_message, reply_markup=keyboard_main_menu)
        else:
            await safe_send_message(bot, chat_id=chat_id_for_message, text=end_message, reply_markup=keyboard_main_menu)

        # Log partial completion if answers exist and DB manager is available
        if self.db_manager and self.db_quiz_session_id and self.answers:
            try:
                quiz_end_time = datetime.now(timezone.utc)
                self.db_manager.log_quiz_completion(
                    quiz_session_uuid=self.db_quiz_session_id,
                    user_id=self.user_id,
                    score=self.score,
                    total_questions_answered=len(self.answers),
                    end_time=quiz_end_time,
                    answers_details=self.answers,
                    status_override="terminated_manually" if manual_end else "terminated_early"
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Quiz early termination logged to DB for session {self.db_quiz_session_id}")
            except Exception as e_db_terminate:
                logger.error(f"[QuizLogic {self.quiz_id}] Error logging quiz early termination to DB: {e_db_terminate}", exc_info=True)
        
        await self.cleanup_quiz_data(context, self.user_id, f"quiz_{reason_suffix}")
        return END

async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    quiz_id = job_data.get("quiz_id")
    user_id = job_data.get("user_id")
    chat_id = job_data.get("chat_id")
    question_index = job_data.get("question_index")
    message_id = job_data.get("message_id") # Message ID of the question that timed out
    question_was_image = job_data.get("question_was_image", False)

    logger.info(f"Timeout callback for quiz {quiz_id}, user {user_id}, q_idx {question_index}")

    quiz_instance = context.user_data.get(quiz_id)
    if isinstance(quiz_instance, QuizLogic) and quiz_instance.active and quiz_instance.current_question_index == question_index:
        logger.debug(f"[WrapperTimeout {quiz_id}] Quiz instance found and active for q_idx {question_index}. Calling handle_timeout.")
        
        # Edit the timed-out question's message to indicate timeout
        timeout_text_suffix = "\n\n<i><b>انتهى الوقت لهذا السؤال.</b></i>"
        try:
            if question_was_image:
                original_caption = ""
                # Attempt to get original caption - this is hard without the message object
                # For now, just append. If bot.edit_message_caption is used, it replaces.
                # We need to be careful. Let's assume we just append to a generic placeholder if we can't get it.
                # A better way would be for QuizLogic to store the caption/text when sending.
                # For now, we'll just try to edit the reply_markup and add a simple note.
                await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
                # And send a new message or try to append to caption if possible (hard).
                # The report's suggestion for show_results to send new message on error is a good pattern.
                # Let's try to edit the caption if it's an image message.
                # This is risky as we don't have the original caption easily.
                # Simpler: just remove buttons. User will see next q or results.
            else:
                # For text messages, try to append to existing text.
                # This also requires getting the original text, which is not directly available here.
                # await context.bot.edit_message_text(text= ??? + timeout_text_suffix, chat_id=chat_id, message_id=message_id, reply_markup=None, parse_mode='HTML')
                pass # For now, let QuizLogic handle advancing and user will see next question or results.
            # The primary job of the timeout is to advance the quiz state.
            # Editing the message here is secondary and can be complex.
            # Let's ensure last_quiz_interaction_message_id is updated if we *do* edit something successfully.
            if message_id:
                 context.user_data[f"last_quiz_interaction_message_id_{chat_id}"] = message_id

        except telegram.error.BadRequest as e:
            if "message is not modified" in str(e).lower():
                logger.debug(f"[WrapperTimeout {quiz_id}] Timed out question message {message_id} not modified (already changed or no markup). {e}")
            else:
                logger.warning(f"[WrapperTimeout {quiz_id}] Failed to edit timed out question message {message_id}: {e}")
        except Exception as e_edit_timeout:
            logger.warning(f"[WrapperTimeout {quiz_id}] Generic error editing timed out question message {message_id}: {e_edit_timeout}")

        next_state = await quiz_instance.handle_timeout(context.bot, context)
        # If next_state is SHOWING_RESULTS or END, the conversation might end here.
        # If it's TAKING_QUIZ, a new question was sent by handle_timeout -> send_question.
    elif not isinstance(quiz_instance, QuizLogic):
        logger.warning(f"[WrapperTimeout {quiz_id}] No QuizLogic instance found in user_data for quiz_id {quiz_id}. User: {user_id}")
    elif not quiz_instance.active:
        logger.info(f"[WrapperTimeout {quiz_id}] Quiz instance found but not active for q_idx {question_index}. User: {user_id}. Quiz might have ended.")
    elif quiz_instance.current_question_index != question_index:
        logger.info(f"[WrapperTimeout {quiz_id}] Mismatched question index. Instance: {quiz_instance.current_question_index}, Job: {question_index}. User: {user_id}. Likely late timeout.")

