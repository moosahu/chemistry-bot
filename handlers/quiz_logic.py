#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Manages the logic for conducting a quiz, including sending questions, handling answers, and calculating results."""
# handlers/quiz_logic.py (v42 - USER_STATS_BTN_FIX)

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
from database.data_logger import log_quiz_results, log_quiz_start # Make sure log_quiz_start is available

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
        self.total_questions_initial = len(self.questions_data) # Initial number of questions fetched
        self.total_questions_processed = 0 # Number of questions actually processed (sent or skipped due to issues)
        self.current_question_index = 0
        self.score = 0
        self.answers = [] 
        self.question_start_time = None
        self.quiz_actual_start_time_dt = None
        self.last_question_message_id = None
        self.question_time_limit = question_time_limit
        self.last_question_is_image = False 
        self.active = True 
        self.db_quiz_session_id = db_quiz_session_id # This will be set by log_quiz_start
        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized for user {self.user_id if self.user_id else 'UNKNOWN'} in chat {self.chat_id if self.chat_id else 'UNKNOWN'}. Quiz: {self.quiz_name}. ScopeID: {self.scope_id}. Questions: {self.total_questions_initial}. DB Session ID: {self.db_quiz_session_id}")

    async def start_quiz(self, bot: Bot, context: CallbackContext, update: Update, user_id: int) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] start_quiz called for user {user_id}, chat {self.chat_id}")
        self.active = True 
        self.quiz_actual_start_time_dt = datetime.now(timezone.utc)
        self.total_questions_initial = len(self.questions_data)
        self.user_id = user_id # Ensure user_id is set

        # Log quiz start and get DB session ID
        if context.bot_data.get("db_manager"):
            self.db_quiz_session_id = await log_quiz_start(
                db_manager=context.bot_data["db_manager"],
                user_id=self.user_id,
                quiz_type=self.quiz_type,
                quiz_scope_id=self.scope_id,
                quiz_name=self.quiz_name,
                total_questions=self.total_questions_initial, # Log initial count
                start_time=self.quiz_actual_start_time_dt
            )
            if self.db_quiz_session_id:
                logger.info(f"[QuizLogic {self.quiz_id}] Quiz session started and logged with DB session ID: {self.db_quiz_session_id}")
            else:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to log quiz start to DB. Proceeding without DB session ID.")
        else:
            logger.error(f"[QuizLogic {self.quiz_id}] db_manager not found in context.bot_data. Cannot log quiz start.")

        if not self.questions_data or self.total_questions_initial == 0:
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
            
            if len(button_text_str.encode("utf-8")) > 60: 
                temp_bytes = button_text_str.encode("utf-8")[:57] 
                button_text_str = temp_bytes.decode("utf-8", "ignore") + "..."

            callback_data = f"ans_{self.quiz_id}_{self.current_question_index}_{option_id}"
            keyboard.append([InlineKeyboardButton(text=button_text_str, callback_data=callback_data)])
        return InlineKeyboardMarkup(keyboard)

    async def send_question(self, bot: Bot, context: CallbackContext, user_id: int):
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] send_question: inactive. User {user_id}. Aborting.")
            return END 

        self.total_questions_initial = len(self.questions_data)

        while self.current_question_index < self.total_questions_initial:
            current_question_data = self.questions_data[self.current_question_index]
            q_id_log = current_question_data.get("question_id", f"q_idx_{self.current_question_index}")
            options = current_question_data.get("options", [])
            self.total_questions_processed += 1 # Increment for each question attempt

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
                    "time_taken": -998,
                    "skipped_due_to_issue": True
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
                        current_option_proc["is_image_option"] = True
                        current_option_proc["image_option_display_label"] = display_label 
                        option_image_counter += 1 
                        await asyncio.sleep(0.3) 
                    except Exception as e_img_opt:
                        logger.error(f"[QuizLogic {self.quiz_id}] Failed to send image option {i} (URL: {option_text_original}), q_id {q_id_log}: {e_img_opt}", exc_info=True)
                        current_option_proc["is_image_option"] = False
                        current_option_proc["image_option_display_label"] = None 
                else:
                    current_option_proc["is_image_option"] = False 
                    current_option_proc["image_option_display_label"] = None
                processed_options.append(current_option_proc)
            
            current_question_data["options"] = processed_options 
            options_keyboard = self.create_options_keyboard(processed_options)
            header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions_initial}:</b>\n"
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

                if not hasattr(context, "bot_data") or context.bot_data is None: context.bot_data = {}
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
                    "time_taken": -997,
                    "skipped_due_to_issue": True 
                })
                self.current_question_index += 1
        
        logger.info(f"[QuizLogic {self.quiz_id}] No more valid questions to send or quiz ended. User {user_id}. Showing results.")
        return await self.show_results(bot, context, user_id)

    def _get_correct_option_text_robust(self, current_question_data):
        correct_option_id_from_data = str(current_question_data.get("correct_option_id"))
        options_for_current_q = current_question_data.get("options", [])
        retrieved_correct_option_text = "نص الإجابة الصحيحة غير متوفر"
        found_correct_option_details = False
        if not correct_option_id_from_data or correct_option_id_from_data == "None":
            logger.warning(f"[QuizLogic {self.quiz_id}] Correct option ID is missing or None in question data for q_id '{current_question_data.get('question_id')}'")
            return "لم يتم تحديد إجابة صحيحة للسؤال"
        for opt_detail in options_for_current_q:
            if str(opt_detail.get("option_id")) == correct_option_id_from_data:
                if opt_detail.get("is_image_option"):
                    img_label = opt_detail.get("image_option_display_label")
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
            retrieved_correct_option_text = f"خطأ: لم يتم العثور على نص الخيار الصحيح (المعرف: {correct_option_id_from_data})"
        return retrieved_correct_option_text

    async def handle_answer(self, bot: Bot, context: CallbackContext, update: Update, user_id: int, chosen_option_id: str):
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] handle_answer: inactive. User {user_id}. Aborting.")
            if update.callback_query:
                await update.callback_query.answer(text="انتهى هذا الاختبار أو لم يعد صالحًا.")
            return END 

        time_taken = time.time() - (self.question_start_time if self.question_start_time else time.time())
        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get("question_id", f"q_idx_{self.current_question_index}")
        options = current_question_data.get("options", [])
        correct_option_id = str(current_question_data.get("correct_option_id"))
        is_correct = (str(chosen_option_id) == correct_option_id)
        chosen_option_text = ""
        
        for option in options:
            if str(option.get("option_id")) == str(chosen_option_id):
                if option.get("is_image_option"):
                    chosen_option_text = f"صورة ({option.get('image_option_display_label', chosen_option_id)})"
                else:
                    chosen_option_text = option.get("option_text", f"خيار {chosen_option_id}")
                break

        if is_correct:
            self.score += 1
            feedback_text = "إجابة صحيحة! ✅"
        else:
            feedback_text = "إجابة خاطئة. ❌"
        
        correct_option_text_for_display = self._get_correct_option_text_robust(current_question_data)
        feedback_text += f"\nالإجابة الصحيحة: {correct_option_text_for_display}"
        
        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": chosen_option_id,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text_for_display,
            "is_correct": is_correct,
            "time_taken": round(time_taken, 2),
            "skipped_due_to_issue": False
        })

        timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)

        message_id_to_edit = self.last_question_message_id
        original_message = context.bot_data.pop(f"msg_cache_{self.chat_id}_{message_id_to_edit}", None)

        if message_id_to_edit:
            try:
                if self.last_question_is_image and original_message and original_message.caption:
                    new_caption = original_message.caption + "\n\n" + feedback_text
                    await bot.edit_message_caption(chat_id=self.chat_id, message_id=message_id_to_edit, caption=new_caption, reply_markup=None)
                elif original_message and original_message.text:
                    new_text = original_message.text + "\n\n" + feedback_text
                    await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_id_to_edit, text=new_text, reply_markup=None, parse_mode="HTML")
                else: # Fallback if original message not found or no text/caption
                    logger.warning(f"[QuizLogic {self.quiz_id}] Original message for q_id {q_id_log} not found in cache or no text/caption. Sending new message for feedback.")
                    await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text, parse_mode="HTML")
            except telegram.error.BadRequest as e:
                if "message is not modified" in str(e).lower():
                    logger.info(f"[QuizLogic {self.quiz_id}] Message not modified for q_id {q_id_log}. Skipping edit.")
                elif "there is no text in the message to edit" in str(e).lower() and self.last_question_is_image:
                     logger.warning(f"[QuizLogic {self.quiz_id}] Attempted to edit text of an image message for q_id {q_id_log}. Caption edit should have been used. Error: {e}")
                     # This case should ideally be handled by the caption edit logic above.
                     # If it still occurs, send a new message with feedback.
                     await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text, parse_mode="HTML")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to edit message for q_id {q_id_log}: {e}", exc_info=True)
                    await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text, parse_mode="HTML") # Send feedback as new message
            except Exception as e_edit:
                logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message for q_id {q_id_log}: {e_edit}", exc_info=True)
                await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text, parse_mode="HTML") # Send feedback as new message
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] No message_id to edit for q_id {q_id_log}. Feedback not shown by edit.")
            await safe_send_message(bot, chat_id=self.chat_id, text=feedback_text, parse_mode="HTML") # Send feedback as new message

        if update.callback_query:
            try:
                await update.callback_query.answer() 
            except Exception as e_ans_cb:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to answer callback query for q_id {q_id_log}: {e_ans_cb}")

        self.current_question_index += 1
        await asyncio.sleep(1) 
        return await self.send_question(bot, context, user_id)

    async def show_results(self, bot: Bot, context: CallbackContext, user_id: int):
        logger.info(f"[QuizLogic {self.quiz_id}] Showing results for user {user_id}. Score: {self.score}/{self.total_questions_processed}")
        self.active = False
        quiz_end_time_dt = datetime.now(timezone.utc)

        # Calculate actual total questions (non-skipped due to system issues)
        answered_questions_count = len([ans for ans in self.answers if not ans.get("skipped_due_to_issue", False)])
        skipped_questions_by_user = len([ans for ans in self.answers if ans.get("chosen_option_id") is None and not ans.get("skipped_due_to_issue", False)])
        wrong_answers_count = answered_questions_count - self.score - skipped_questions_by_user 
        if wrong_answers_count < 0: wrong_answers_count = 0 # Ensure non-negative

        if answered_questions_count > 0:
            score_percentage = (self.score / answered_questions_count) * 100 if answered_questions_count > 0 else 0
        else: # All questions might have been skipped due to issues
            score_percentage = 0

        results_summary = f"🏁 <b>نتائج الاختبار: {self.quiz_name}</b> 🏁\n\n"
        results_summary += f"✨ نتيجتك: {self.score} من {answered_questions_count} ({score_percentage:.2f}%)\n"
        results_summary += f"✅ الإجابات الصحيحة: {self.score}\n"
        results_summary += f"❌ الإجابات الخاطئة: {wrong_answers_count}\n"
        results_summary += f"⏭️ الأسئلة التي تم تخطيها (بواسطتك): {skipped_questions_by_user}\n"
        
        # Log results to database if db_quiz_session_id exists
        if self.db_quiz_session_id and context.bot_data.get("db_manager"):
            await log_quiz_results(
                db_manager=context.bot_data["db_manager"],
                quiz_id_uuid=self.db_quiz_session_id, # Use the session ID from start_quiz
                user_id=self.user_id,
                correct_count=self.score,
                wrong_count=wrong_answers_count,
                skipped_count=skipped_questions_by_user,
                score_percentage_calculated=score_percentage,
                start_time_original=self.quiz_actual_start_time_dt,
                end_time=quiz_end_time_dt,
                answers_details_list=self.answers,
                quiz_type_for_log=self.quiz_type # For logging consistency
            )
        elif not self.db_quiz_session_id:
            logger.warning(f"[QuizLogic {self.quiz_id}] db_quiz_session_id is missing. Cannot log detailed results to DB.")
        elif not context.bot_data.get("db_manager"):
            logger.error(f"[QuizLogic {self.quiz_id}] db_manager not found in context.bot_data. Cannot log detailed results.")

        detailed_answers_summary = "\n📜 <b>تفاصيل إجاباتك:</b>\n"
        for i, ans in enumerate(self.answers):
            q_text = ans.get("question_text", "نص السؤال غير متوفر")
            if q_text is None or not str(q_text).strip(): q_text = "سؤال (صورة أو بدون نص)"
            q_text_short = (str(q_text)[:50] + "...") if len(str(q_text)) > 50 else str(q_text)
            
            chosen_opt_text = ans.get("chosen_option_text", "لم يتم الاختيار")
            if chosen_opt_text is None or not str(chosen_opt_text).strip(): chosen_opt_text = "لم يتم الاختيار"
            chosen_opt_text_short = (str(chosen_opt_text)[:40] + "...") if len(str(chosen_opt_text)) > 40 else str(chosen_opt_text)

            correct_opt_text = ans.get("correct_option_text", "غير محدد")
            if correct_opt_text is None or not str(correct_opt_text).strip(): correct_opt_text = "غير محدد"
            correct_opt_text_short = (str(correct_opt_text)[:40] + "...") if len(str(correct_opt_text)) > 40 else str(correct_opt_text)

            status_emoji = "✅" if ans.get("is_correct") else ("❌" if ans.get("chosen_option_id") is not None else "⏭️")
            if ans.get("skipped_due_to_issue"):
                status_emoji = "⚠️"
                chosen_opt_text_short = ans.get("chosen_option_text", "خطأ في السؤال") # Display the skip reason

            detailed_answers_summary += f"{i+1}. {q_text_short}\n"
            detailed_answers_summary += f"   {status_emoji} اختيارك: {chosen_opt_text_short}\n"
            if not ans.get("is_correct") and ans.get("chosen_option_id") is not None and not ans.get("skipped_due_to_issue"):
                detailed_answers_summary += f"   💡 الصحيح: {correct_opt_text_short}\n"
            detailed_answers_summary += "---\n"
        
        full_summary = results_summary + detailed_answers_summary
        
        keyboard_buttons = [
            [InlineKeyboardButton("📊 عرض إحصائياتي", callback_data="show_my_stats")], # MODIFIED HERE
            [InlineKeyboardButton("🔄 ابدأ اختبارًا جديدًا", callback_data="start_new_quiz")],
            [InlineKeyboardButton("العودة إلى القائمة الرئيسية  મુખ્ય", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard_buttons)

        # Try to edit the last question message if it exists, otherwise send a new one.
        if self.last_question_message_id and self.chat_id:
            try:
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=self.last_question_message_id, text=full_summary, reply_markup=reply_markup, parse_mode="HTML")
            except Exception as e_edit_results:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit last question message for results: {e_edit_results}. Sending new message.")
                await safe_send_message(bot, chat_id=self.chat_id, text=full_summary, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await safe_send_message(bot, chat_id=self.chat_id, text=full_summary, reply_markup=reply_markup, parse_mode="HTML")
        
        await self.cleanup_quiz_data(context, user_id, "quiz_completed")
        return MAIN_MENU # Or END, depending on desired flow after results.

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.info(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user {user_id}. Reason: {reason}")
        self.active = False
        quiz_instance_key = f"quiz_instance_{user_id}_{self.chat_id}"
        if quiz_instance_key in context.user_data:
            del context.user_data[quiz_instance_key]
        
        # Ensure all pending timers for this quiz are removed
        if context.job_queue:
            for job in context.job_queue.jobs():
                if job.name and job.name.startswith(f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}"):
                    job.schedule_removal()
                    logger.debug(f"[QuizLogic {self.quiz_id}] Removed job: {job.name}")
        logger.info(f"[QuizLogic {self.quiz_id}] Quiz data cleanup complete for user {user_id}.")

async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    quiz_id = job_data.get("quiz_id")
    question_index = job_data.get("question_index")
    user_id = job_data.get("user_id")
    chat_id = job_data.get("chat_id")
    message_id = job_data.get("message_id")
    question_was_image = job_data.get("question_was_image", False)

    logger.info(f"[TimeoutCb {quiz_id}] Timeout for q_idx {question_index}, user {user_id}, chat {chat_id}")

    quiz_instance_key = f"quiz_instance_{user_id}_{chat_id}"
    quiz_logic_instance = context.user_data.get(quiz_instance_key)

    if quiz_logic_instance and quiz_logic_instance.active and quiz_logic_instance.quiz_id == quiz_id and quiz_logic_instance.current_question_index == question_index:
        logger.info(f"[TimeoutCb {quiz_id}] Quiz active. Handling timeout for q_idx {question_index}.")
        
        current_question_data = quiz_logic_instance.questions_data[question_index]
        q_id_log_timeout = current_question_data.get("question_id", f"q_idx_{question_index}")
        correct_option_text_timeout = quiz_logic_instance._get_correct_option_text_robust(current_question_data)

        quiz_logic_instance.answers.append({
            "question_id": q_id_log_timeout,
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": None, 
            "chosen_option_text": "تم تخطي السؤال (نفذ الوقت)",
            "correct_option_id": str(current_question_data.get("correct_option_id")),
            "correct_option_text": correct_option_text_timeout,
            "is_correct": False,
            "time_taken": quiz_logic_instance.question_time_limit, # Max time
            "skipped_due_to_issue": False # User skipped by timeout
        })
        
        feedback_timeout = f"انتهى الوقت للسؤال! ⌛\nالإجابة الصحيحة: {correct_option_text_timeout}"
        
        if message_id:
            try:
                original_message_timeout = context.bot_data.pop(f"msg_cache_{chat_id}_{message_id}", None)
                if question_was_image and original_message_timeout and original_message_timeout.caption:
                    new_caption_timeout = original_message_timeout.caption + "\n\n" + feedback_timeout
                    await context.bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=new_caption_timeout, reply_markup=None)
                elif original_message_timeout and original_message_timeout.text:
                    new_text_timeout = original_message_timeout.text + "\n\n" + feedback_timeout
                    await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=message_id, text=new_text_timeout, reply_markup=None, parse_mode="HTML")
                else:
                    await safe_send_message(context.bot, chat_id=chat_id, text=feedback_timeout, parse_mode="HTML")
            except telegram.error.BadRequest as e_timeout_br:
                if "message is not modified" in str(e_timeout_br).lower():
                    logger.info(f"[TimeoutCb {quiz_id}] Message not modified for q_idx {question_index} (timeout). Skipping edit.")
                else:
                    logger.error(f"[TimeoutCb {quiz_id}] BadRequest editing message for q_idx {question_index} (timeout): {e_timeout_br}")
                    await safe_send_message(context.bot, chat_id=chat_id, text=feedback_timeout, parse_mode="HTML")
            except Exception as e_timeout_edit:
                logger.error(f"[TimeoutCb {quiz_id}] Error editing message for q_idx {question_index} (timeout): {e_timeout_edit}")
                await safe_send_message(context.bot, chat_id=chat_id, text=feedback_timeout, parse_mode="HTML")
        else:
            await safe_send_message(context.bot, chat_id=chat_id, text=feedback_timeout, parse_mode="HTML")

        quiz_logic_instance.current_question_index += 1
        await asyncio.sleep(1) 
        await quiz_logic_instance.send_question(context.bot, context, user_id)
    elif quiz_logic_instance and quiz_logic_instance.quiz_id == quiz_id and quiz_logic_instance.current_question_index != question_index:
        logger.info(f"[TimeoutCb {quiz_id}] Timeout for q_idx {question_index}, but current is {quiz_logic_instance.current_question_index}. Ignoring old timer.")
    elif not quiz_logic_instance or not quiz_logic_instance.active:
        logger.info(f"[TimeoutCb {quiz_id}] Quiz instance not found, inactive, or different quiz_id. Timer for q_idx {question_index} ignored.")

# Example of how QuizLogic might be instantiated and used (conceptual)
async def main_example():
    # This is a conceptual example and would need a running bot, context, etc.
    # bot = Bot(token="YOUR_BOT_TOKEN")
    # user_data_dict = {}
    # context = CallbackContext.from_error(bot, user_data_dict, user_data_dict, user_data_dict)
    # update = Update(123) # Dummy update
    
    # user_id = 12345
    # chat_id = 67890
    # sample_questions = [
    #     {"question_id": "q1", "question_text": "ما هو لون السماء؟", "options": [
    #         {"option_id": "opt1_1", "option_text": "أزرق", "is_correct": True},
    #         {"option_id": "opt1_2", "option_text": "أخضر", "is_correct": False}
    #     ]},
    #     {"question_id": "q2", "image_url": "https://example.com/image.jpg", "question_text": "ما هذا الحيوان؟", "options": [
    #         {"option_id": "opt2_1", "option_text": "قطة", "is_correct": True},
    #         {"option_id": "opt2_2", "option_text": "كلب", "is_correct": False}
    #     ], "correct_option_id": "opt2_1"}
    # ]
    
    # quiz_logic = QuizLogic(user_id=user_id, chat_id=chat_id, quiz_type="general", questions_data=sample_questions, quiz_name="اختبار تجريبي")
    # context.user_data[f"quiz_instance_{user_id}_{chat_id}"] = quiz_logic
    # await quiz_logic.start_quiz(bot, context, update, user_id)
    pass

if __name__ == "__main__":
    # To run this example, you would need to set up an asyncio event loop
    # and provide mock Bot, Context, and Update objects.
    # asyncio.run(main_example())
    logger.info("quiz_logic.py executed directly. Contains QuizLogic class and helper functions.")

