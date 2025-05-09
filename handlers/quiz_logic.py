#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Manages the logic for conducting a quiz, including sending questions, handling answers, and calculating results."""
# handlers/quiz_logic.py (v41 - CAPTION_ENDSTATE_FIX)

import asyncio
import logging
import time
import uuid # لإنشاء معرّف فريد للاختبار
import telegram # For telegram.error types
from datetime import datetime, timezone # Ensure timezone is imported
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot 
from telegram.ext import ConversationHandler, CallbackContext, JobQueue 
from config import logger, TAKING_QUIZ, END, MAIN_MENU # MAIN_MENU is used for end state
from utils.helpers import safe_send_message, safe_edit_message_text, remove_job_if_exists
from database.data_logger import log_quiz_results # افتراض وجود هذه الدالة

MIN_OPTIONS_PER_QUESTION = 2

class QuizLogic:
    ARABIC_CHOICE_LETTERS = ["أ", "ب", "ج", "د"]

    def __init__(self, user_id=None, chat_id=None, quiz_type=None, questions_data=None, total_questions=0, question_time_limit=60, quiz_id=None, quiz_name=None, db_quiz_session_id=None, quiz_scope_id=None):
        self.user_id = user_id
        self.chat_id = chat_id
        self.quiz_id = quiz_id if quiz_id else str(uuid.uuid4()) 
        self.quiz_name = quiz_name if quiz_name else "اختبار غير مسمى"
        self.quiz_type = quiz_type
        self.scope_id = quiz_scope_id
        self.questions_data = questions_data if questions_data is not None else []
        self.total_questions = len(self.questions_data) 
        self.current_question_index = 0
        self.score = 0
        self.answers = [] 
        self.question_start_time = None
        self.quiz_actual_start_time_dt = None
        self.last_question_message_id = None
        self.question_time_limit = question_time_limit
        self.last_question_is_image = False # Flag to indicate if the last question sent was an image
        self.active = True 
        self.db_quiz_session_id = db_quiz_session_id
        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized for user {self.user_id if self.user_id else 'UNKNOWN'} in chat {self.chat_id if self.chat_id else 'UNKNOWN'}. Quiz: {self.quiz_name}. ScopeID: {self.scope_id}. Questions: {self.total_questions}. DB Session ID: {self.db_quiz_session_id}")

    async def start_quiz(self, bot: Bot, context: CallbackContext, update: Update, user_id: int) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] start_quiz called for user {user_id}, chat {self.chat_id}")
        self.active = True 
        self.quiz_actual_start_time_dt = datetime.now(timezone.utc)
        self.total_questions = len(self.questions_data) 
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
            await self.cleanup_quiz_data(context, user_id, "no_questions_on_start") 
            return END 
        
        return await self.send_question(bot, context, user_id)
    
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

    async def send_question(self, bot: Bot, context: CallbackContext, user_id: int):
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] send_question: inactive. User {user_id}. Aborting.")
            return END 

        self.total_questions = len(self.questions_data)

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
                    "correct_option_text": "لا يمكن تحديده (خيارات غير كافية)",
                    "is_correct": False,
                    "time_taken": -998 
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
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] JobQueue not available. Timer not set for user {user_id}.")
                return TAKING_QUIZ 
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to send question (q_id: {q_id_log}). Skipping.")
                self.answers.append({
                    "question_id": q_id_log,
                    "question_text": question_text_display,
                    "chosen_option_id": None,
                    "chosen_option_text": "خطأ في إرسال السؤال",
                    "correct_option_id": None,
                    "correct_option_text": "لا يمكن تحديده (خطأ في الإرسال)",
                    "is_correct": False,
                    "time_taken": -997 
                })
                self.current_question_index += 1
        
        logger.info(f"[QuizLogic {self.quiz_id}] No more valid questions to send or quiz ended. User {user_id}. Showing results.")
        return await self.show_results(bot, context, user_id)

    def _get_correct_option_text_robust(self, current_question_data):
        correct_option_id_from_data = str(current_question_data.get("correct_option_id"))
        options_for_current_q = current_question_data.get("options", [])
        retrieved_correct_option_text = "نص الإجابة الصحيحة غير متوفر"
        found_correct_option_details = False
        if not correct_option_id_from_data or correct_option_id_from_data == 'None':
            logger.warning(f"[QuizLogic {self.quiz_id}] Correct option ID is missing or None in question data for q_id '{current_question_data.get('question_id')}'")
            return "لم يتم تحديد إجابة صحيحة للسؤال"
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
            logger.error(f"[QuizLogic {self.quiz_id}] Critical: Correct option ID '{correct_option_id_from_data}' not found in processed options for q_id '{current_question_data.get('question_id')}'")
        return retrieved_correct_option_text

    async def _update_message_after_answer(self, bot: Bot, context: CallbackContext, user_id: int, result_text: str, chosen_option_text: str, correct_option_text: str):
        current_question_data = self.questions_data[self.current_question_index -1] # -1 because index already incremented for next q
        original_question_text = current_question_data.get("question_text", "")
        original_image_url = current_question_data.get("image_url")

        if original_question_text is None: original_question_text = ""
        if not isinstance(original_question_text, str): original_question_text = str(original_question_text)
        original_question_text = original_question_text.strip()

        header = f"<b>السؤال {self.current_question_index} من {self.total_questions}:</b>\n" # Use current_question_index as it's already advanced
        
        question_display_for_feedback = ""
        if not original_question_text and original_image_url:
            question_display_for_feedback = "السؤال المصور أعلاه"
        elif not original_question_text and not original_image_url:
            question_display_for_feedback = "(سؤال بدون نص أو صورة)"
        else:
            question_display_for_feedback = original_question_text

        feedback_message = f"{header}{question_display_for_feedback}\n\n{result_text}\nإجابتك: {chosen_option_text}\nالإجابة الصحيحة: {correct_option_text}"
        
        if self.last_question_message_id:
            try:
                if self.last_question_is_image:
                    logger.debug(f"[QuizLogic {self.quiz_id}] Attempting to edit caption for message {self.last_question_message_id}")
                    await bot.edit_message_caption(chat_id=self.chat_id, message_id=self.last_question_message_id, caption=feedback_message, reply_markup=None, parse_mode="HTML")
                else:
                    logger.debug(f"[QuizLogic {self.quiz_id}] Attempting to edit text for message {self.last_question_message_id}")
                    await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=self.last_question_message_id, text=feedback_message, reply_markup=None, parse_mode="HTML")
            except telegram.error.BadRequest as e_bad_req:
                if "message is not modified" in str(e_bad_req).lower():
                    logger.info(f"[QuizLogic {self.quiz_id}] Message not modified (likely identical content or already deleted): {e_bad_req}")
                elif "message to edit not found" in str(e_bad_req).lower():
                     logger.warning(f"[QuizLogic {self.quiz_id}] Message to edit not found (ID: {self.last_question_message_id}): {e_bad_req}")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] BadRequest editing message {self.last_question_message_id}: {e_bad_req}", exc_info=True)
            except Exception as e:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to update message {self.last_question_message_id} after answer: {e}", exc_info=True)
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] No last_question_message_id to update for user {user_id}")

    async def handle_answer(self, bot: Bot, context: CallbackContext, update: Update):
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] handle_answer: inactive. User {self.user_id}. Aborting.")
            # Try to remove buttons from the stale message if possible
            if update.callback_query and update.callback_query.message:
                try:
                    await bot.edit_message_reply_markup(chat_id=self.chat_id, message_id=update.callback_query.message.message_id, reply_markup=None)
                except Exception as e_stale_edit:
                    logger.debug(f"[QuizLogic {self.quiz_id}] Failed to remove markup from stale message: {e_stale_edit}")
            return END 

        query = update.callback_query
        await query.answer() 
        
        data_parts = query.data.split('_')
        quiz_id_from_cb, question_idx_str, chosen_option_id_str = data_parts[1], data_parts[2], data_parts[3]

        if quiz_id_from_cb != self.quiz_id:
            logger.warning(f"[QuizLogic {self.quiz_id}] Callback quiz_id '{quiz_id_from_cb}' mismatch. User {self.user_id}. Ignoring.")
            return TAKING_QUIZ 

        try:
            question_idx_from_cb = int(question_idx_str)
        except ValueError:
            logger.error(f"[QuizLogic {self.quiz_id}] Invalid question index in callback: {question_idx_str}. User {self.user_id}")
            return TAKING_QUIZ

        if question_idx_from_cb != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Answer for wrong question index. Expected {self.current_question_index}, got {question_idx_from_cb}. User {self.user_id}. Ignoring.")
            # It's possible the user clicked an old button. We should not process this for scoring.
            # We might want to inform the user or just let the current question timer run out.
            return TAKING_QUIZ 

        time_taken = time.time() - self.question_start_time if self.question_start_time else -1
        timer_job_name = f"qtimer_{self.user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)

        current_question_data = self.questions_data[self.current_question_index]
        correct_option_id = str(current_question_data.get("correct_option_id"))
        chosen_option_id = str(chosen_option_id_str)
        
        is_correct = (chosen_option_id == correct_option_id)
        if is_correct:
            self.score += 1
            result_text = "<emoji document_id=\"5368324170671202286\">✅</emoji> <b>إجابة صحيحة!</b>"
        else:
            result_text = "<emoji document_id=\"5368819764943584729\">❌</emoji> <b>إجابة خاطئة.</b>"

        options = current_question_data.get("options", [])
        chosen_option_text = "غير محدد"
        for opt in options:
            if str(opt.get("option_id")) == chosen_option_id:
                if opt.get("is_image_option"):
                    img_label = opt.get('image_option_display_label')
                    chosen_option_text = f"صورة ({img_label})" if img_label else f"صورة (معرف: {chosen_option_id})"
                else:
                    chosen_option_text = opt.get("option_text", f"خيار {chosen_option_id}")
                break
        
        correct_option_text_display = self._get_correct_option_text_robust(current_question_data)
        
        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر عند التسجيل"), # Storing original text/placeholder
            "question_is_image": current_question_data.get("image_url") is not None,
            "chosen_option_id": chosen_option_id,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text_display, 
            "is_correct": is_correct,
            "time_taken": round(time_taken, 2)
        })
        
        # Update message with feedback (this will now use edit_message_caption for images)
        await self._update_message_after_answer(bot, context, self.user_id, result_text, chosen_option_text, correct_option_text_display)
        await asyncio.sleep(1) # Pause briefly to show feedback

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            return await self.send_question(bot, context, self.user_id)
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz completed for user {self.user_id}. Score: {self.score}/{self.total_questions}")
            return await self.show_results(bot, context, self.user_id)

    async def _handle_timeout(self, context: CallbackContext):
        job_data = context.job.data
        quiz_id_from_job = job_data.get("quiz_id")
        question_idx_from_job = job_data.get("question_index")
        user_id_from_job = job_data.get("user_id")
        message_id_from_job = job_data.get("message_id")
        # question_was_image = job_data.get("question_was_image", False) # This was passed but not used, self.last_question_is_image is more current

        if not self.active or quiz_id_from_job != self.quiz_id or question_idx_from_job != self.current_question_index:
            logger.info(f"[QuizLogic {self.quiz_id} / Job {quiz_id_from_job}] Timeout for stale/inactive quiz or wrong question index ({question_idx_from_job} vs {self.current_question_index}). User {user_id_from_job}. Ignoring.")
            return

        logger.info(f"[QuizLogic {self.quiz_id}] Question {self.current_question_index} timed out for user {self.user_id}.")
        current_question_data = self.questions_data[self.current_question_index]
        correct_option_text_display = self._get_correct_option_text_robust(current_question_data)

        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر عند التسجيل"),
            "question_is_image": current_question_data.get("image_url") is not None,
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": str(current_question_data.get("correct_option_id")),
            "correct_option_text": correct_option_text_display,
            "is_correct": False,
            "time_taken": self.question_time_limit 
        })

        result_text = "<emoji document_id=\"5810930094034586389\">⏳</emoji> <b>انتهى الوقت!</b>"
        # Update message with timeout feedback (this will now use edit_message_caption for images)
        await self._update_message_after_answer(context.bot, context, self.user_id, result_text, "لم يتم اختيار إجابة", correct_option_text_display)
        await asyncio.sleep(1) # Pause briefly to show feedback

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await self.send_question(context.bot, context, self.user_id)
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz completed (after timeout on last q) for user {self.user_id}. Score: {self.score}/{self.total_questions}")
            await self.show_results(context.bot, context, self.user_id)

    async def show_results(self, bot: Bot, context: CallbackContext, user_id: int):
        if not self.active and not self.answers: # If inactive and no answers, means it was likely cleaned up
            logger.warning(f"[QuizLogic {self.quiz_id}] show_results called on inactive/empty quiz for user {user_id}. Aborting.")
            return END # Or MAIN_MENU if appropriate

        results_summary = f"🎉 <b>نتائج اختبار '{self.quiz_name}'</b> 🎉\n\n"
        results_summary += f"مجموع النقاط: {self.score} من {self.total_questions} ({ (self.score / self.total_questions * 100) if self.total_questions > 0 else 0 :.1f}%)\n\n"
        results_summary += "<b>ملخص الإجابات:</b>\n"
        for i, ans in enumerate(self.answers):
            q_text_summary = ans.get("question_text", "سؤال غير محدد")
            if ans.get("question_is_image") and (not q_text_summary or q_text_summary == "السؤال معروض في الصورة أعلاه."):
                q_text_summary = f"السؤال المصور {i+1}"
            elif not q_text_summary or q_text_summary == "نص السؤال غير متوفر عند التسجيل":
                 q_text_summary = f"السؤال {i+1} (نص غير متاح)"
            
            # Truncate question text for summary
            q_text_display_summary = (q_text_summary[:50] + '...') if q_text_summary and len(q_text_summary) > 50 else q_text_summary
            
            chosen_ans_text = ans.get("chosen_option_text", "لم يتم الإجابة")
            correct_ans_text = ans.get("correct_option_text", "غير محددة")
            status_emoji = "✅" if ans.get("is_correct") else ("❌" if chosen_ans_text != "انتهى الوقت" and chosen_ans_text != "تم تخطي السؤال (خيارات غير كافية)" else "⏳")
            
            results_summary += f"{i+1}. {q_text_display_summary}\n"
            results_summary += f"   {status_emoji} إجابتك: {chosen_ans_text}\n"
            if not ans.get("is_correct") and chosen_ans_text != "انتهى الوقت" and chosen_ans_text != "تم تخطي السؤال (خيارات غير كافية)":
                results_summary += f"       الصحيحة: {correct_ans_text}\n"
            results_summary += f"       الوقت: {ans.get('time_taken', 'N/A')} ثانية\n\n"

        results_keyboard_buttons = [
            [InlineKeyboardButton("📊 عرض الإحصائيات", callback_data="stats_menu_from_quiz")],
            [InlineKeyboardButton("🧠 ابدأ اختباراً جديداً", callback_data="start_quiz")],
            [InlineKeyboardButton("العودة للقائمة الرئيسية", callback_data="main_menu")]
        ]
        results_keyboard = InlineKeyboardMarkup(results_keyboard_buttons)

        logger.info(f"[QuizLogic {self.quiz_id}] Showing results for user {user_id}. Score: {self.score}/{self.total_questions}")
        
        # Log results to database if db_quiz_session_id is available
        if self.db_quiz_session_id:
            try:
                # Ensure quiz_actual_start_time_dt is set
                start_time_iso = self.quiz_actual_start_time_dt.isoformat() if self.quiz_actual_start_time_dt else datetime.now(timezone.utc).isoformat()
                
                # Convert answers to JSON string for DB storage
                answers_json = json.dumps(self.answers, ensure_ascii=False) 

                await log_quiz_results(
                    db_quiz_session_id=self.db_quiz_session_id,
                    user_id=self.user_id,
                    quiz_name=self.quiz_name,
                    quiz_type=self.quiz_type,
                    scope_id=self.scope_id,
                    score=self.score,
                    total_questions=self.total_questions,
                    percentage_score=(self.score / self.total_questions * 100) if self.total_questions > 0 else 0,
                    answers_details_json=answers_json, # Pass the JSON string
                    quiz_start_time_iso=start_time_iso,
                    quiz_end_time_iso=datetime.now(timezone.utc).isoformat()
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Successfully logged results to DB for session {self.db_quiz_session_id}")
            except Exception as e_db_log:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to log quiz results to DB for session {self.db_quiz_session_id}: {e_db_log}", exc_info=True)
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] No DB session ID. Quiz results not logged to DB for user {user_id}.")

        if self.last_question_message_id:
             await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=self.last_question_message_id, text=results_summary, reply_markup=results_keyboard, parse_mode="HTML")
        else: # If last_question_message_id is somehow None, send as new message
            logger.warning(f"[QuizLogic {self.quiz_id}] last_question_message_id was None when showing results. Sending as new message.")
            await safe_send_message(bot, chat_id=self.chat_id, text=results_summary, reply_markup=results_keyboard, parse_mode="HTML")

        await self.cleanup_quiz_data(context, user_id, "quiz_completed_normally")
        return MAIN_MENU # CAPTION_ENDSTATE_FIX: Changed from SHOWING_RESULTS to MAIN_MENU

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.info(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user {user_id}. Reason: {reason}")
        self.active = False
        quiz_instance_key = f"quiz_{user_id}_{self.chat_id}_{self.quiz_id[:10]}" # Using a shortened or consistent key format
        # More robust key based on how it's stored in quiz.py
        # Assuming it's stored like: context.user_data[f"quiz_{user_id}_{chat_id}_{quiz_start_timestamp}"]
        # For now, let's try to find it if the exact key isn't known, or rely on quiz.py to clean its own reference.
        
        # Remove any pending timer job for the current question if it exists
        if self.current_question_index < self.total_questions: # If quiz ended prematurely
            timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
            remove_job_if_exists(timer_job_name, context)
        
        # Clear this specific quiz instance from context.user_data or context.chat_data if stored there
        # This part is tricky as QuizLogic itself doesn't know its exact key in user_data/chat_data
        # The calling handler (quiz.py) should ideally remove its reference to this QuizLogic instance.
        # For now, we just mark it inactive. The main quiz.py handler should check `quiz_instance.active`.
        logger.info(f"[QuizLogic {self.quiz_id}] Quiz instance {self.quiz_id} data cleaned up for user {user_id}.")

async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    user_id = job_data.get("user_id")
    chat_id = job_data.get("chat_id")
    quiz_id_from_job = job_data.get("quiz_id")
    
    # Try to find the quiz instance. This is a common pattern for job callbacks.
    # The exact key format used in quiz.py to store the instance is crucial here.
    # Assuming a pattern like context.user_data['active_quiz_instance_quiz_id'] or similar
    # This part needs to be robust or QuizLogic needs a way to be retrieved globally/per user.
    
    quiz_instance = None
    # Attempt to retrieve the quiz instance from user_data or chat_data
    # This is a placeholder for how quiz.py might store the active quiz instance
    if context.user_data and isinstance(context.user_data.get('active_quiz_instance'), QuizLogic) \
       and context.user_data['active_quiz_instance'].quiz_id == quiz_id_from_job:
        quiz_instance = context.user_data['active_quiz_instance']
    elif context.chat_data and isinstance(context.chat_data.get('active_quiz_instance'), QuizLogic) \
         and context.chat_data['active_quiz_instance'].quiz_id == quiz_id_from_job:
        quiz_instance = context.chat_data['active_quiz_instance']
    else: # Fallback: Iterate through user_data/chat_data if keys are dynamic (less efficient)
        # This is a simplified search; a more direct retrieval method is preferred.
        for key, value in list(context.user_data.items()): # Iterate over a copy
            if isinstance(value, QuizLogic) and value.quiz_id == quiz_id_from_job and value.user_id == user_id and value.chat_id == chat_id:
                quiz_instance = value
                break
        if not quiz_instance:
             for key, value in list(context.chat_data.items()): # Iterate over a copy
                if isinstance(value, QuizLogic) and value.quiz_id == quiz_id_from_job and value.user_id == user_id and value.chat_id == chat_id:
                    quiz_instance = value
                    break

    if quiz_instance and quiz_instance.active:
        logger.info(f"[TimeoutWrapper] Found active QuizLogic instance {quiz_instance.quiz_id}. Calling _handle_timeout.")
        await quiz_instance._handle_timeout(context)
    else:
        logger.warning(f"[TimeoutWrapper] No active QuizLogic instance found for quiz_id {quiz_id_from_job} / user {user_id} or instance inactive. Timer job will not proceed.")

