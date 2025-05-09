#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Manages the logic for conducting a quiz, including sending questions, handling answers, and calculating results."""
# handlers/quiz_logic.py (v39 - Fix for scope_id and quiz_start_time_obj)

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

    def __init__(self, user_id=None, chat_id=None, quiz_type=None, questions_data=None, total_questions=0, question_time_limit=60, quiz_id=None, quiz_name=None, db_quiz_session_id=None, quiz_scope_id=None): # Added quiz_scope_id
        self.user_id = user_id
        self.chat_id = chat_id
        self.quiz_id = quiz_id if quiz_id else str(uuid.uuid4()) 
        self.quiz_name = quiz_name if quiz_name else "اختبار غير مسمى"
        self.quiz_type = quiz_type
        self.scope_id = quiz_scope_id # Store quiz_scope_id
        self.questions_data = questions_data if questions_data is not None else []
        self.total_questions = len(self.questions_data) 
        self.current_question_index = 0
        self.score = 0
        self.answers = [] 
        self.question_start_time = None # This is for individual question timing
        self.quiz_actual_start_time_dt = None # For overall quiz start time as datetime object
        self.last_question_message_id = None
        self.question_time_limit = question_time_limit
        self.last_question_is_image = False
        self.active = True 
        self.db_quiz_session_id = db_quiz_session_id
        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized for user {self.user_id if self.user_id else 'UNKNOWN'} in chat {self.chat_id if self.chat_id else 'UNKNOWN'}. Quiz: {self.quiz_name}. ScopeID: {self.scope_id}. Questions: {self.total_questions}. DB Session ID: {self.db_quiz_session_id}")

    async def start_quiz(self, bot: Bot, context: CallbackContext, update: Update, user_id: int) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] start_quiz called for user {user_id}, chat {self.chat_id}")
        self.active = True 
        self.quiz_actual_start_time_dt = datetime.now(timezone.utc) # Set overall quiz start time
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
            question_text_from_data = current_question_data.get("question_text") # Get original value

            # Convert to string and handle None or empty string for question text
            if question_text_from_data is None or not str(question_text_from_data).strip():
                question_text_from_data = "نص السؤال غير متوفر حالياً."
            elif not isinstance(question_text_from_data, str):
                 question_text_from_data = str(question_text_from_data)
            
            sent_message = None
            self.last_question_is_image = False

            if image_url:
                caption_text = header + question_text_from_data
                try:
                    sent_message = await bot.send_photo(chat_id=self.chat_id, photo=image_url, caption=caption_text, reply_markup=options_keyboard, parse_mode="HTML")
                    self.last_question_is_image = True
                except Exception as e:
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to send photo q_id {q_id_log}: {e}. URL: {image_url}", exc_info=True)
                    full_question_text = header + question_text_from_data + "\n(تعذر تحميل صورة السؤال)"
                    try:
                        sent_message = await safe_send_message(bot, chat_id=self.chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                    except Exception as e_fallback_text:
                        logger.error(f"[QuizLogic {self.quiz_id}] Fallback text failed q_id {q_id_log}: {e_fallback_text}", exc_info=True)
            else:
                # This 'else' implies question_text_from_data should already be prepared and not empty
                full_question_text = header + question_text_from_data
                try:
                    sent_message = await safe_send_message(bot, chat_id=self.chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                except Exception as e:
                     logger.error(f"[QuizLogic {self.quiz_id}] Error sending text question q_id {q_id_log}: {e}.", exc_info=True)

            if sent_message:
                self.last_question_message_id = sent_message.message_id
                self.question_start_time = time.time() # For individual question
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
                    "question_text": question_text_from_data if question_text_from_data else "سؤال فشل إرساله",
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
            retrieved_correct_option_text = f"خطأ: الإجابة الصحيحة (معرف: {correct_option_id_from_data}) غير موجودة ضمن الخيارات"
        return retrieved_correct_option_text

    async def handle_answer(self, bot: Bot, context: CallbackContext, update: Update):
        query = update.callback_query
        if not query: # Should not happen if called from CallbackQueryHandler
            logger.error(f"[QuizLogic {self.quiz_id}] handle_answer called without a query object.")
            return TAKING_QUIZ # Or some error state
        
        await query.answer() # Acknowledge the button press
        user_id = query.from_user.id
        
        # Defensive check: Ensure quiz is still active and matches the user
        if not self.active or self.user_id != user_id:
            logger.warning(f"[QuizLogic {self.quiz_id}] handle_answer called for inactive quiz or mismatched user. Quiz active: {self.active}, Quiz user: {self.user_id}, Query user: {user_id}")
            # Consider sending a message that the quiz session is invalid
            if query.message:
                 await safe_edit_message_text(bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="جلسة الاختبار هذه لم تعد صالحة.", reply_markup=None)
            return END 

        callback_data_str = query.data
        
        try:
            _, quiz_id_from_cb, q_idx_str, chosen_option_id = callback_data_str.split("_")
            q_idx = int(q_idx_str)
        except ValueError as e_val:
            logger.error(f"[QuizLogic {self.quiz_id}] Invalid callback_data format in handle_answer: {callback_data_str}. Error: {e_val}")
            # Potentially edit message to inform user of an error and ask to try again or restart quiz
            return TAKING_QUIZ # Stay in the current state, or move to an error state

        if quiz_id_from_cb != self.quiz_id:
            logger.warning(f"[QuizLogic {self.quiz_id}] Mismatched quiz_id in callback. Expected {self.quiz_id}, got {quiz_id_from_cb}. Ignoring.")
            return TAKING_QUIZ 

        if q_idx != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Answer for wrong question index. Expected {self.current_question_index}, got {q_idx}. Ignoring.")
            # This could happen with rapid clicks or old messages. Usually, just ignoring is fine.
            return TAKING_QUIZ

        time_taken = time.time() - self.question_start_time if self.question_start_time else -1
        timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)

        current_question_data = self.questions_data[self.current_question_index]
        correct_option_id = str(current_question_data.get("correct_option_id"))
        is_correct = (str(chosen_option_id) == correct_option_id)
        if is_correct:
            self.score += 1

        chosen_option_text = "نص الخيار المختار غير متوفر"
        for opt in current_question_data.get("options", []):
            if str(opt.get("option_id")) == str(chosen_option_id):
                if opt.get("is_image_option"):
                    chosen_option_text = f"صورة ({opt.get('image_option_display_label', 'بدون عنوان')})"
                else:
                    chosen_option_text = opt.get("option_text", f"خيار نصي (معرف: {chosen_option_id})")
                break
        
        correct_option_text_val = self._get_correct_option_text_robust(current_question_data)

        self.answers.append({
            "question_id": current_question_data.get("question_id", f"q_idx_{self.current_question_index}"),
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": chosen_option_id,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text_val,
            "is_correct": is_correct,
            "time_taken": round(time_taken, 2)
        })

        # Edit the last question message to remove buttons and show feedback (optional)
        if self.last_question_message_id and query.message.message_id == self.last_question_message_id:
            feedback_text = " ✅ إجابة صحيحة!" if is_correct else f" ❌ إجابة خاطئة. الصحيح: {correct_option_text_val}"
            original_caption = query.message.caption if self.last_question_is_image else query.message.text
            new_text_or_caption = original_caption + "\n\n" + feedback_text
            try:
                if self.last_question_is_image:
                    await bot.edit_message_caption(chat_id=self.chat_id, message_id=self.last_question_message_id, caption=new_text_or_caption, reply_markup=None)
                else:
                    await bot.edit_message_text(text=new_text_or_caption, chat_id=self.chat_id, message_id=self.last_question_message_id, reply_markup=None, parse_mode="HTML") # Ensure parse_mode if original had it
            except telegram.error.BadRequest as e_edit:
                if "message is not modified" in str(e_edit).lower():
                    logger.debug(f"[QuizLogic {self.quiz_id}] Message not modified for feedback, skipping edit. User {user_id}")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Error editing message for feedback: {e_edit}. User {user_id}")
            except Exception as e_gen_edit:
                 logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message for feedback: {e_gen_edit}. User {user_id}")
        
        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            return await self.send_question(bot, context, user_id)
        else:
            return await self.show_results(bot, context, user_id)

    async def show_results(self, bot: Bot, context: CallbackContext, user_id: int):
        if not self.active: # Should ideally not be called if not active, but as a safeguard
            logger.warning(f"[QuizLogic {self.quiz_id}] show_results called for an inactive quiz. User {user_id}")
            # Maybe send a generic error or redirect to main menu
            return END 
            
        self.active = False # Mark quiz as inactive once results are shown
        logger.info(f"[QuizLogic {self.quiz_id}] Showing results for user {user_id}. Score: {self.score}/{self.total_questions}")
        
        # Calculate percentage and other stats
        percentage = (self.score / self.total_questions * 100) if self.total_questions > 0 else 0
        wrong_answers = self.total_questions - self.score # Assuming no skipped questions for now in this basic count
        skipped_count = 0 # Placeholder, needs proper tracking if timeout auto-skips

        results_text = f"🎉 <b>نتائج الاختبار: {self.quiz_name}</b> 🎉\n\n"
        results_text += f"✨ نتيجتك: {self.score} من {self.total_questions} ({percentage:.1f}%)\n"
        results_text += f"✅ الإجابات الصحيحة: {self.score}\n"
        results_text += f"❌ الإجابات الخاطئة: {wrong_answers}\n"
        # results_text += f"⏭️ الأسئلة التي تم تخطيها: {skipped_count}\n" # If implementing skip
        
        total_time_taken_seconds = 0
        valid_times = [ans.get('time_taken', 0) for ans in self.answers if ans.get('time_taken', -1) >= 0]
        if valid_times:
            total_time_taken_seconds = sum(valid_times)
            avg_time_per_q = total_time_taken_seconds / len(valid_times)
            results_text += f"⏱️ متوسط وقت الإجابة: {avg_time_per_q:.1f} ثانية/سؤال\n"
            results_text += f"⏳ إجمالي وقت الاختبار: {total_time_taken_seconds:.1f} ثانية\n"
        
        results_text += "\n📜 <b>تفاصيل الإجابات:</b>\n"
        for i, ans in enumerate(self.answers):
            q_text_short = ans.get('question_text', 'سؤال غير معروف')[:50] + ("..." if len(ans.get('question_text', '')) > 50 else "")
            chosen_short = ans.get('chosen_option_text', 'لم يتم الاختيار')[:30] + ("..." if len(ans.get('chosen_option_text', '')) > 30 else "")
            correct_short = ans.get('correct_option_text', 'غير محدد')[:30] + ("..." if len(ans.get('correct_option_text', '')) > 30 else "")
            status_emoji = "✅" if ans.get('is_correct') else ("❌" if ans.get('chosen_option_id') is not None else "⏭️")
            time_info = f" ({ans.get('time_taken', 'N/A')} ث)" if ans.get('time_taken', -1) >=0 else ""
            results_text += f"{i+1}. {q_text_short} {status_emoji}\n    اخترت: {chosen_short} | الصحيح: {correct_short}{time_info}\n"
            if len(results_text) > 3800: # Telegram message limit is 4096, leave buffer
                results_text += "\n... (تم اختصار التفاصيل لطول الرسالة)"
                break
        
        keyboard = [
            [InlineKeyboardButton("ابدأ اختبار جديد", callback_data="start_new_quiz")],
            [InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Log results to database
        quiz_end_time_dt = datetime.now(timezone.utc)
        if self.quiz_actual_start_time_dt is None:
            logger.warning(f"[QuizLogic {self.quiz_id}] quiz_actual_start_time_dt was None. Using quiz_end_time_dt as placeholder for duration calculation.")
            self.quiz_actual_start_time_dt = quiz_end_time_dt # Avoid None error, though duration will be 0
        
        time_taken_for_db_seconds = int((quiz_end_time_dt - self.quiz_actual_start_time_dt).total_seconds()) if self.quiz_actual_start_time_dt else None

        try:
            log_quiz_results(
                user_id=self.user_id,
                db_quiz_session_id=self.db_quiz_session_id, # Pass the DB session ID
                quiz_id_uuid=self.quiz_id, 
                quiz_name=self.quiz_name,
                quiz_type=self.quiz_type,
                quiz_scope_id=self.scope_id, 
                total_questions=self.total_questions,
                score=self.score, 
                wrong_answers=wrong_answers,
                skipped_answers=skipped_count,
                percentage=percentage,
                start_time=self.quiz_actual_start_time_dt, 
                end_time=quiz_end_time_dt, 
                time_taken_seconds=time_taken_for_db_seconds, 
                answers_details=self.answers 
            )
        except Exception as e_log_results:
            logger.error(f"[QuizLogic {self.quiz_id}] Failed to log quiz results to DB: {e_log_results}", exc_info=True)

        # Attempt to edit the last question message if it exists, otherwise send a new one.
        if self.last_question_message_id:
            try:
                await bot.edit_message_reply_markup(chat_id=self.chat_id, message_id=self.last_question_message_id, reply_markup=None)
                await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=reply_markup, parse_mode="HTML")
            except Exception as e_edit_last:
                logger.warning(f"[QuizLogic {self.quiz_id}] Could not edit last question message_id {self.last_question_message_id} before sending results: {e_edit_last}. Sending as new message.")
                await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=reply_markup, parse_mode="HTML")
        else: # Should ideally not happen if questions were sent
            await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=reply_markup, parse_mode="HTML")
        
        await self.cleanup_quiz_data(context, user_id, "quiz_completed_show_results")
        return SHOWING_RESULTS 

    async def handle_timeout(self, bot: Bot, context: CallbackContext, user_id: int, question_index_from_job: int, message_id_from_job: int, question_was_image: bool):
        if not self.active or self.user_id != user_id or self.current_question_index != question_index_from_job:
            logger.info(f"[QuizLogic {self.quiz_id}] Timeout for an old/inactive question (idx {question_index_from_job}, current {self.current_question_index}) or different user. Ignoring.")
            return TAKING_QUIZ # Or END if quiz should terminate on any such mismatch

        logger.info(f"[QuizLogic {self.quiz_id}] Question {self.current_question_index + 1} timed out for user {user_id}.")
        current_question_data = self.questions_data[self.current_question_index]
        correct_option_text_val = self._get_correct_option_text_robust(current_question_data)
        
        self.answers.append({
            "question_id": current_question_data.get("question_id", f"q_idx_{self.current_question_index}"),
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": None, # No option chosen
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": str(current_question_data.get("correct_option_id")),
            "correct_option_text": correct_option_text_val,
            "is_correct": False, # Timed out, so not correct
            "time_taken": self.question_time_limit 
        })
        
        # Edit the timed-out question message to remove buttons and show it timed out
        if message_id_from_job:
            timeout_feedback = f"⌛ انتهى الوقت! الإجابة الصحيحة: {correct_option_text_val}"
            try:
                # Fetch the original message from cache or context if needed to get its text/caption
                original_message = context.bot_data.get(f"msg_cache_{self.chat_id}_{message_id_from_job}")
                original_text_or_caption = ""
                if original_message:
                    original_text_or_caption = original_message.caption if question_was_image else original_message.text
                else: # Fallback if message not in cache
                    logger.warning(f"[QuizLogic {self.quiz_id}] Original message for timeout edit not found in cache: msg_id {message_id_from_job}")
                    original_text_or_caption = f"السؤال {self.current_question_index + 1}"
                
                new_text_or_caption = original_text_or_caption + "\n\n" + timeout_feedback

                if question_was_image:
                    await bot.edit_message_caption(chat_id=self.chat_id, message_id=message_id_from_job, caption=new_text_or_caption, reply_markup=None)
                else:
                    await bot.edit_message_text(text=new_text_or_caption, chat_id=self.chat_id, message_id=message_id_from_job, reply_markup=None, parse_mode="HTML")
            except telegram.error.BadRequest as e_edit_timeout:
                if "message is not modified" in str(e_edit_timeout).lower():
                    logger.debug(f"[QuizLogic {self.quiz_id}] Message not modified for timeout feedback, skipping edit. User {user_id}")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Error editing message for timeout: {e_edit_timeout}. User {user_id}")
            except Exception as e_gen_timeout_edit:
                logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message for timeout: {e_gen_timeout_edit}. User {user_id}")

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            return await self.send_question(bot, context, user_id)
        else:
            return await self.show_results(bot, context, user_id)

    async def end_quiz(self, bot: Bot, context: CallbackContext, update: Update, manual_end: bool = False, reason_suffix: str = "ended", called_from_fallback:bool = False) -> int:
        user_id = self.user_id # Assuming self.user_id is set correctly
        if not self.active:
            logger.info(f"[QuizLogic {self.quiz_id}] end_quiz called but quiz already inactive for user {user_id}. Suffix: {reason_suffix}")
            if called_from_fallback: return END # If called from a fallback, just end.
            return SHOWING_RESULTS # Or END, depending on desired flow if already inactive

        self.active = False
        logger.info(f"[QuizLogic {self.quiz_id}] Quiz manually ended for user {user_id}. Reason suffix: {reason_suffix}")
        
        # Remove any pending timer for the current question
        timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)

        # If quiz ended manually before completion, show partial results or a message
        if manual_end and self.current_question_index < self.total_questions:
            # Log partial results if any answers were given
            if self.answers: # Only log if there's something to log
                percentage = (self.score / self.current_question_index * 100) if self.current_question_index > 0 else 0
                wrong_answers = self.current_question_index - self.score 
                quiz_end_time_dt = datetime.now(timezone.utc)
                time_taken_for_db_seconds = int((quiz_end_time_dt - self.quiz_actual_start_time_dt).total_seconds()) if self.quiz_actual_start_time_dt else None
                try:
                    log_quiz_results(
                        user_id=self.user_id,
                        db_quiz_session_id=self.db_quiz_session_id,
                        quiz_id_uuid=self.quiz_id, 
                        quiz_name=f"{self.quiz_name} (غير مكتمل - {reason_suffix})",
                        quiz_type=self.quiz_type,
                        quiz_scope_id=self.scope_id,
                        total_questions=self.total_questions, # Original total
                        score=self.score, 
                        wrong_answers=wrong_answers, # Based on answered
                        skipped_answers=self.total_questions - self.current_question_index, # All remaining are skipped
                        percentage=percentage, # Based on answered
                        start_time=self.quiz_actual_start_time_dt,
                        end_time=quiz_end_time_dt, 
                        time_taken_seconds=time_taken_for_db_seconds,
                        answers_details=self.answers 
                    )
                except Exception as e_log_manual_end:
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to log manually ended quiz results: {e_log_manual_end}", exc_info=True)
            
            # Inform the user
            end_message_text = "تم إنهاء الاختبار بناءً على طلبك."
            if update and update.callback_query and update.callback_query.message and not called_from_fallback:
                # Try to edit the message where the quiz was active if not from a global fallback
                try:
                    await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=update.callback_query.message.message_id, text=end_message_text, reply_markup=None)
                except Exception as e_edit_manual_end:
                    logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message on manual end: {e_edit_manual_end}. Sending new.")
                    await safe_send_message(bot, chat_id=self.chat_id, text=end_message_text)
            elif not called_from_fallback: # If no query or from fallback, send new message if not from fallback
                await safe_send_message(bot, chat_id=self.chat_id, text=end_message_text)
            # If called_from_fallback, the fallback handler (e.g., start_command_fallback_for_quiz) will handle the main menu message.

        await self.cleanup_quiz_data(context, user_id, f"manual_end_{reason_suffix}")
        return END # Always END for manual termination that isn't showing full results

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.debug(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user {user_id}. Reason: {reason}")
        # Remove the specific quiz instance from context.user_data
        # The key used to store the instance was current_quiz_instance_id
        # current_quiz_instance_id = context.user_data.get("current_quiz_instance_id")
        # if current_quiz_instance_id and current_quiz_instance_id == f"quiz_{user_id}_{self.chat_id}_{self.quiz_id}": # Construct the key as it was stored
        #     context.user_data.pop(current_quiz_instance_id, None)
        # else: # More general pop if the key format varies or quiz_id is the main part
        #     # This part needs to be robust. The instance is stored using its unique quiz_id as part of the key. 
        #     # Let's assume the key is exactly self.quiz_id if it's unique enough, or reconstruct it if a pattern is used.
        #     # For now, we assume the calling handler (quiz.py) manages popping the current_quiz_instance_id key itself.
        #     pass 
        # The QuizLogic instance itself doesn't know its key in context.user_data, so the handler in quiz.py should pop it.
        # This method is more for internal state cleanup if needed, but PTB context cleanup is usually done by the handler.
        self.active = False # Ensure it's marked inactive

async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    user_id = job_data.get("user_id")
    chat_id = job_data.get("chat_id")
    quiz_id_from_job = job_data.get("quiz_id")
    question_index_from_job = job_data.get("question_index")
    message_id_from_job = job_data.get("message_id")
    question_was_image = job_data.get("question_was_image", False)

    logger.info(f"Timeout job triggered for user {user_id}, quiz {quiz_id_from_job}, q_idx {question_index_from_job}")

    # Retrieve the QuizLogic instance
    # The instance is stored in context.user_data using a key like "quiz_USERID_CHATID_TIMESTAMP" or current_quiz_instance_id
    current_quiz_instance_id = context.user_data.get("current_quiz_instance_id")
    if not current_quiz_instance_id:
        logger.error(f"Timeout: No current_quiz_instance_id for user {user_id}. Cannot process timeout.")
        return

    quiz_instance = context.user_data.get(current_quiz_instance_id)

    if isinstance(quiz_instance, QuizLogic) and quiz_instance.quiz_id == quiz_id_from_job:
        next_state = await quiz_instance.handle_timeout(context.bot, context, user_id, question_index_from_job, message_id_from_job, question_was_image)
        # Note: ConversationHandler state transitions are not directly managed from job callbacks.
        # The handle_timeout method will send the next question or results if the quiz continues/ends.
        # If a state change is strictly needed here, it's more complex and might involve sending a dummy update.
        if next_state == END or next_state == SHOWING_RESULTS:
            logger.info(f"Timeout led to quiz end/results for user {user_id}, quiz {quiz_id_from_job}.")
            # The quiz_instance.show_results or quiz_instance.end_quiz would have been called.
    else:
        logger.warning(f"Timeout: Quiz instance not found or quiz_id mismatch for user {user_id}. Expected quiz_id {quiz_id_from_job}, instance: {quiz_instance}")

