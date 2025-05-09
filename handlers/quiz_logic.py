#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Manages the logic for conducting a quiz, including sending questions, handling answers, and calculating results."""
# handlers/quiz_logic.py (v40 - IMAGE_HANDLING_FIX)

import asyncio
import logging
import time
import uuid # لإنشاء معرّف فريد للاختبار
import telegram # For telegram.error types
from datetime import datetime, timezone # Ensure timezone is imported
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot 
from telegram.ext import ConversationHandler, CallbackContext, JobQueue 
from config import logger, TAKING_QUIZ, END, MAIN_MENU 
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
        self.last_question_is_image = False
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

            # --- IMAGE_HANDLING_FIX: Start ---
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
            # --- IMAGE_HANDLING_FIX: End ---
            
            sent_message = None
            self.last_question_is_image = False

            if image_url:
                caption_text = header + question_text_display # Use display text
                try:
                    sent_message = await bot.send_photo(chat_id=self.chat_id, photo=image_url, caption=caption_text, reply_markup=options_keyboard, parse_mode="HTML")
                    self.last_question_is_image = True
                except Exception as e:
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to send photo q_id {q_id_log}: {e}. URL: {image_url}", exc_info=True)
                    full_question_text = header + question_text_display + "\n(تعذر تحميل صورة السؤال)" # Use display text
                    try:
                        sent_message = await safe_send_message(bot, chat_id=self.chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                    except Exception as e_fallback_text:
                        logger.error(f"[QuizLogic {self.quiz_id}] Fallback text failed q_id {q_id_log}: {e_fallback_text}", exc_info=True)
            else:
                full_question_text = header + question_text_display # Use display text
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
                    "question_text": question_text_display, # Use display text
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

    async def handle_answer(self, bot: Bot, context: CallbackContext, update: Update):
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        
        callback_data_parts = query.data.split("_")
        # ans_QUIZID_QINDEX_OPTIONID
        if len(callback_data_parts) < 4:
            logger.error(f"[QuizLogic {self.quiz_id}] Invalid answer callback data: {query.data}. User {user_id}")
            await safe_send_message(bot, chat_id=self.chat_id, text="حدث خطأ في معالجة إجابتك. يرجى المحاولة مرة أخرى.")
            return TAKING_QUIZ 

        try:
            cb_quiz_id = callback_data_parts[1]
            cb_q_index = int(callback_data_parts[2])
            chosen_option_id = callback_data_parts[3]
        except (IndexError, ValueError) as e_parse:
            logger.error(f"[QuizLogic {self.quiz_id}] Error parsing answer callback data 	'{query.data}	': {e_parse}. User {user_id}")
            await safe_send_message(bot, chat_id=self.chat_id, text="حدث خطأ في معالجة إجابتك (بيانات غير صالحة). يرجى المحاولة مرة أخرى.")
            return TAKING_QUIZ

        if cb_quiz_id != self.quiz_id:
            logger.warning(f"[QuizLogic {self.quiz_id}] Mismatched quiz_id in answer. Expected {self.quiz_id}, got {cb_quiz_id}. User {user_id}. Ignoring.")
            # Don't send message to user, might be an old button from a previous quiz instance
            return TAKING_QUIZ 

        if cb_q_index != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Answer for wrong question index. Expected {self.current_question_index}, got {cb_q_index}. User {user_id}. Ignoring.")
            await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=query.message.message_id, text="لقد أجبت بالفعل على هذا السؤال أو انتهى وقته.", reply_markup=None)
            return TAKING_QUIZ

        time_taken = time.time() - self.question_start_time if self.question_start_time else -1
        timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)

        current_question_data = self.questions_data[self.current_question_index]
        # --- IMAGE_HANDLING_FIX: Ensure question_text is a string for logging/results ---
        q_text_for_log = current_question_data.get("question_text")
        if q_text_for_log is None:
            q_text_for_log = "سؤال (صورة)" if current_question_data.get("image_url") else "سؤال بدون نص"
        elif not isinstance(q_text_for_log, str):
            q_text_for_log = str(q_text_for_log)
        # --- IMAGE_HANDLING_FIX: End ---

        correct_option_id = str(current_question_data.get("correct_option_id"))
        is_correct = (str(chosen_option_id) == correct_option_id)
        if is_correct:
            self.score += 1

        chosen_option_text = "خيار غير معروف"
        for option in current_question_data.get("options", []):
            if str(option.get("option_id")) == str(chosen_option_id):
                if option.get("is_image_option"):
                    chosen_option_text = f"صورة ({option.get('image_option_display_label', chosen_option_id)})"
                else:
                    chosen_option_text = option.get("option_text", f"خيار {chosen_option_id}")
                break
        
        correct_option_text_display = self._get_correct_option_text_robust(current_question_data)

        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": q_text_for_log, # Use prepared text
            "chosen_option_id": chosen_option_id,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text_display,
            "is_correct": is_correct,
            "time_taken": round(time_taken, 2)
        })

        feedback_text = "✅ إجابة صحيحة!" if is_correct else f"❌ إجابة خاطئة. الصحيحة: {correct_option_text_display}"
        
        message_id_to_edit = self.last_question_message_id
        if query.message and query.message.message_id == message_id_to_edit:
            if self.last_question_is_image:
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_id_to_edit, text=query.message.caption + "\n\n" + feedback_text, reply_markup=None, parse_mode="HTML")
            else:
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_id_to_edit, text=query.message.text + "\n\n" + feedback_text, reply_markup=None, parse_mode="HTML")
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] Message ID mismatch for feedback. Expected {message_id_to_edit}, got {query.message.message_id if query.message else 'None'}. Sending new message.")
            await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text)

        self.current_question_index += 1
        await asyncio.sleep(1.5) 

        if self.current_question_index < self.total_questions:
            return await self.send_question(bot, context, user_id)
        else:
            return await self.show_results(bot, context, user_id)

    async def handle_timeout(self, bot: Bot, context: CallbackContext, user_id: int, question_index_timed_out: int):
        if not self.active or question_index_timed_out != self.current_question_index:
            logger.info(f"[QuizLogic {self.quiz_id}] Timeout for q_idx {question_index_timed_out} (current: {self.current_question_index}). Quiz inactive or already moved on. User {user_id}. Ignoring.")
            return

        logger.info(f"[QuizLogic {self.quiz_id}] Question {self.current_question_index} timed out for user {user_id}.")
        current_question_data = self.questions_data[self.current_question_index]
        # --- IMAGE_HANDLING_FIX: Ensure question_text is a string for logging/results ---
        q_text_for_log = current_question_data.get("question_text")
        if q_text_for_log is None:
            q_text_for_log = "سؤال (صورة)" if current_question_data.get("image_url") else "سؤال بدون نص"
        elif not isinstance(q_text_for_log, str):
            q_text_for_log = str(q_text_for_log)
        # --- IMAGE_HANDLING_FIX: End ---

        correct_option_text_display = self._get_correct_option_text_robust(current_question_data)

        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": q_text_for_log, # Use prepared text
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": current_question_data.get("correct_option_id"),
            "correct_option_text": correct_option_text_display,
            "is_correct": False,
            "time_taken": self.question_time_limit 
        })

        feedback_text = f"⏰ انتهى الوقت! الإجابة الصحيحة كانت: {correct_option_text_display}"
        message_id_to_edit = self.last_question_message_id
        
        # Try to retrieve the message from bot_data cache if direct edit fails
        cached_message = context.bot_data.pop(f"msg_cache_{self.chat_id}_{message_id_to_edit}", None)

        try:
            if self.last_question_is_image:
                original_caption = cached_message.caption if cached_message else "السؤال (صورة)"
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_id_to_edit, text=original_caption + "\n\n" + feedback_text, reply_markup=None, parse_mode="HTML")
            else:
                original_text = cached_message.text if cached_message else "السؤال"
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_id_to_edit, text=original_text + "\n\n" + feedback_text, reply_markup=None, parse_mode="HTML")
        except telegram.error.BadRequest as e_edit_timeout:
            if "message to edit not found" in str(e_edit_timeout).lower() or "message can't be edited" in str(e_edit_timeout).lower():
                logger.warning(f"[QuizLogic {self.quiz_id}] Message {message_id_to_edit} not found or can't be edited on timeout. Sending new message. Error: {e_edit_timeout}")
                await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text)
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] Error editing message on timeout: {e_edit_timeout}")
                await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text) # Fallback
        except Exception as e_gen_timeout_edit:
            logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message on timeout: {e_gen_timeout_edit}")
            await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text) # Fallback

        self.current_question_index += 1
        await asyncio.sleep(1.5)

        if self.current_question_index < self.total_questions:
            await self.send_question(bot, context, user_id)
        else:
            await self.show_results(bot, context, user_id)

    async def show_results(self, bot: Bot, context: CallbackContext, user_id: int):
        logger.info(f"[QuizLogic {self.quiz_id}] Showing results for user {user_id}. Score: {self.score}/{self.total_questions}")
        self.active = False 
        results_text = f"🏁 <b>نتائج اختبار '{self.quiz_name}'</b> 🏁\n\n"
        results_text += f"✨ نتيجتك: {self.score} من {self.total_questions} ({((self.score / self.total_questions) * 100) if self.total_questions > 0 else 0:.1f}%)\n"
        
        total_time_taken = sum(ans.get("time_taken", 0) for ans in self.answers if ans.get("time_taken", 0) > 0)
        avg_time_per_q = (total_time_taken / len([a for a in self.answers if a.get("time_taken",0) > 0])) if len([a for a in self.answers if a.get("time_taken",0) > 0]) > 0 else 0
        results_text += f"⏱️ متوسط وقت الإجابة: {avg_time_per_q:.1f} ثانية للسؤال\n\n"
        results_text += "<b>تفاصيل إجاباتك:</b>\n"

        for i, ans in enumerate(self.answers):
            # --- IMAGE_HANDLING_FIX: Ensure question_text is a string for results summary ---
            q_text = ans.get('question_text')
            if q_text is None or not str(q_text).strip():
                q_text_short = "سؤال (صورة أو بدون نص)" 
            else:
                q_text_str = str(q_text) # Ensure it's a string
                q_text_short = q_text_str[:50] + ("..." if len(q_text_str) > 50 else "")
            # --- IMAGE_HANDLING_FIX: End ---

            chosen_ans_text = ans.get('chosen_option_text', 'لم يتم الاختيار')
            correct_ans_text = ans.get('correct_option_text', 'غير محدد')
            status_emoji = "✅" if ans.get('is_correct') else ("❌" if chosen_ans_text != "انتهى الوقت" else "⏰")
            results_text += f"\n{status_emoji} <b>سؤال {i+1}:</b> {q_text_short}\n"
            results_text += f"   - إجابتك: {chosen_ans_text}\n"
            if not ans.get('is_correct') and chosen_ans_text != "انتهى الوقت":
                results_text += f"   - الصحيحة: {correct_ans_text}\n"
        
        results_text += "\n------------------------------------\n"
        results_text += "شكراً لك على المشاركة! 🎉"

        keyboard = [
            [InlineKeyboardButton("🔁 ابدأ اختبار جديد", callback_data="start_new_quiz")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Log results to database
        if self.db_quiz_session_id:
            try:
                log_quiz_results(
                    db_quiz_session_id=self.db_quiz_session_id,
                    user_id=self.user_id,
                    score=self.score,
                    total_questions_answered=len(self.answers),
                    quiz_duration_seconds= (datetime.now(timezone.utc) - self.quiz_actual_start_time_dt).total_seconds() if self.quiz_actual_start_time_dt else -1,
                    answers_details=json.dumps(self.answers, ensure_ascii=False) # Store detailed answers as JSON
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Results logged to DB for session {self.db_quiz_session_id}")
            except Exception as e_log_results:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to log quiz results to DB for session {self.db_quiz_session_id}: {e_log_results}", exc_info=True)
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] No DB session ID. Quiz results not logged to DB for user {self.user_id}.")

        # Try to edit the last question message first, then send new if fails
        message_to_edit_id = self.last_question_message_id
        edited_successfully = False
        if message_to_edit_id:
            try:
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_to_edit_id, text=results_text, reply_markup=reply_markup, parse_mode="HTML")
                edited_successfully = True
            except telegram.error.BadRequest as e_edit_results:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit last question message ({message_to_edit_id}) with results: {e_edit_results}. Sending new message.")
            except Exception as e_gen_edit_results:
                 logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message with results: {e_gen_edit_results}. Sending new message.")
        
        if not edited_successfully:
            await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=reply_markup, parse_mode="HTML")

        await self.cleanup_quiz_data(context, user_id, "quiz_completed_normally")
        return SHOWING_RESULTS # Transition to a state where user can choose next action

    async def end_quiz(self, bot: Bot, context: CallbackContext, update: Update, manual_end: bool = False, reason_suffix: str = "unknown_reason", called_from_fallback: bool = False):
        user_id = self.user_id if self.user_id else (update.effective_user.id if update and update.effective_user else "UNKNOWN_USER")
        logger.info(f"[QuizLogic {self.quiz_id}] end_quiz called for user {user_id}. Manual: {manual_end}. Reason: {reason_suffix}. Active: {self.active}")
        if not self.active and not manual_end: # If already inactive and not a forced manual end, do nothing
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz already inactive. No action needed for user {user_id}.")
            return
        
        self.active = False 
        timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)

        if manual_end:
            # If ended manually (e.g., by /start or main_menu), don't show full results unless some answers exist
            if self.answers: # If some answers were given, maybe show partial results or a summary
                # For now, just log that it was ended manually
                logger.info(f"[QuizLogic {self.quiz_id}] Quiz for user {user_id} ended manually with {len(self.answers)} answers. Reason: {reason_suffix}")
                # Optionally, could call show_results here if desired, but current flow is to go to main menu
                # If called from a fallback that already sends a menu, we might not want to send another message here.
                if not called_from_fallback: # Avoid double messaging if fallback handles it
                    try:
                        # Attempt to edit the last question message to indicate quiz ended
                        if self.last_question_message_id:
                            await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=self.last_question_message_id, text="تم إنهاء الاختبار يدوياً.", reply_markup=None)
                        else: # If no last message ID, send a new one
                            await safe_send_message(bot, chat_id=self.chat_id, text="تم إنهاء الاختبار يدوياً.")
                    except Exception as e_manual_end_edit:
                        logger.error(f"[QuizLogic {self.quiz_id}] Error editing/sending manual end message: {e_manual_end_edit}")
            else:
                logger.info(f"[QuizLogic {self.quiz_id}] Quiz for user {user_id} ended manually before any answers. Reason: {reason_suffix}")
                if not called_from_fallback and self.last_question_message_id: # If quiz started but no answers
                     try:
                        await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=self.last_question_message_id, text="تم إلغاء الاختبار.", reply_markup=None)
                     except Exception as e_cancel_edit:
                        logger.error(f"[QuizLogic {self.quiz_id}] Error editing message on cancel: {e_cancel_edit}")
        
        await self.cleanup_quiz_data(context, user_id, f"ended_manually_{reason_suffix}")
        # The calling handler (e.g., start_command_fallback) should return the next state (e.g., END or MAIN_MENU)

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.debug(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user {user_id}. Reason: {reason}")
        # Remove this specific quiz instance from context.user_data
        if self.quiz_id in context.user_data: # Check if this instance ID is a key
            context.user_data.pop(self.quiz_id, None)
        
        # Also remove the reference via current_quiz_instance_id if it matches this instance
        current_quiz_ref = context.user_data.get("current_quiz_instance_id")
        if current_quiz_ref == self.quiz_id:
            context.user_data.pop("current_quiz_instance_id", None)
        
        # General cleanup of other keys that might be set by the quiz.py handlers
        # This is a bit broad, but helps ensure no stale data if quiz ends unexpectedly
        # More targeted cleanup could be done if specific keys are known.
        # For now, this instance-specific cleanup is the most important.
        logger.info(f"[QuizLogic {self.quiz_id}] Quiz instance {self.quiz_id} data cleaned up for user {user_id}.")


# Wrapper for job queue callback
async def question_timeout_callback_wrapper(context: CallbackContext):
    job = context.job
    user_id = job.data["user_id"]
    chat_id = job.data["chat_id"]
    quiz_id_from_job = job.data["quiz_id"]
    question_index_from_job = job.data["question_index"]
    # message_id_from_job = job.data["message_id"]
    # question_was_image_from_job = job.data["question_was_image"]

    logger.info(f"Timeout job triggered for user {user_id}, quiz {quiz_id_from_job}, q_idx {question_index_from_job}")

    # Retrieve the specific QuizLogic instance using quiz_id_from_job
    # This assumes quiz_id_from_job is the key for the QuizLogic instance in user_data
    # However, the current storage pattern is quiz_instance_id = f"quiz_{user_id}_{chat_id}_{timestamp}"
    # And this quiz_instance_id is stored in context.user_data["current_quiz_instance_id"]
    # So, we need to get the current_quiz_instance_id first, then get the instance.

    current_quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if not current_quiz_instance_id:
        logger.error(f"Timeout callback: No current_quiz_instance_id for user {user_id}. Cannot process timeout.")
        return

    quiz_instance = context.user_data.get(current_quiz_instance_id)

    if isinstance(quiz_instance, QuizLogic) and quiz_instance.quiz_id == quiz_id_from_job:
        if quiz_instance.active and quiz_instance.current_question_index == question_index_from_job:
            logger.info(f"[QuizLogic {quiz_instance.quiz_id}] Timeout job valid. Calling handle_timeout for q_idx {question_index_from_job}.")
            await quiz_instance.handle_timeout(context.bot, context, user_id, question_index_from_job)
        else:
            logger.info(f"[QuizLogic {quiz_instance.quiz_id}] Timeout job for q_idx {question_index_from_job} but quiz state is different (active: {quiz_instance.active}, current_q: {quiz_instance.current_question_index}). Ignoring.")
    else:
        logger.warning(f"Timeout callback: Quiz instance {current_quiz_instance_id} (expected internal id {quiz_id_from_job}) not found, not QuizLogic, or ID mismatch for user {user_id}. Instance: {quiz_instance}")

logger.info("QuizLogic (quiz_logic.py) loaded with IMAGE_HANDLING_FIX.")

