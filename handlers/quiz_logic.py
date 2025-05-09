"""Manages the logic for conducting a quiz, including sending questions, handling answers, and calculating results."""
# -*- coding: utf-8 -*-
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
            question_text_from_data = current_question_data.get("question_text", "") 
            sent_message = None
            self.last_question_is_image = False

            if not isinstance(question_text_from_data, str):
                question_text_from_data = str(question_text_from_data)

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
                if not question_text_from_data.strip():
                    question_text_from_data = "نص السؤال غير متوفر حالياً."
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
                    "question_text": question_text_from_data,
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
        user_id = query.from_user.id
        if not self.active or str(user_id) != str(self.user_id):
            await query.answer(text="هذا الاختبار ليس لك أو لم يعد نشطاً.", show_alert=True)
            return TAKING_QUIZ 
        
        time_taken = time.time() - self.question_start_time if self.question_start_time else -1
        timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)

        try:
            await query.answer() 
        except telegram.error.BadRequest as e_ans:
            if "message is not modified" in str(e_ans).lower():
                logger.debug(f"[QuizLogic {self.quiz_id}] Answer already processed or message not modified for user {user_id}.")
            else:
                logger.warning(f"[QuizLogic {self.quiz_id}] BadRequest on query.answer() for user {user_id}: {e_ans}")
        except Exception as e_ans_other:
            logger.error(f"[QuizLogic {self.quiz_id}] Unexpected error on query.answer() for user {user_id}: {e_ans_other}", exc_info=True)

        data_parts = query.data.split('_')
        chosen_option_id_str = data_parts[-1]
        
        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        options_for_current_q = current_question_data.get("options", [])
        correct_option_id_from_data = str(current_question_data.get("correct_option_id"))
        
        is_correct = (chosen_option_id_str == correct_option_id_from_data)
        if is_correct:
            self.score += 1

        chosen_option_text = ""
        for option in options_for_current_q:
            if str(option.get("option_id")) == chosen_option_id_str:
                if option.get("is_image_option"):
                    img_label = option.get('image_option_display_label')
                    chosen_option_text = f"صورة ({img_label})" if img_label and img_label.strip() else f"صورة (معرف: {chosen_option_id_str})"
                else:
                    chosen_option_text = option.get("option_text", f"خيار نصي (معرف: {chosen_option_id_str})")
                break
        if not chosen_option_text:
             chosen_option_text = f"خيار غير معروف (معرف: {chosen_option_id_str})"

        correct_option_text_for_log = self._get_correct_option_text_robust(current_question_data)

        self.answers.append({
            "question_id": q_id_log,
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": chosen_option_id_str,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id_from_data,
            "correct_option_text": correct_option_text_for_log,
            "is_correct": is_correct,
            "time_taken": round(time_taken, 2)
        })

        result_text = "✅ إجابة صحيحة!" if is_correct else "❌ إجابة خاطئة."
        detailed_feedback = f"{result_text}\n"
        if not is_correct:
            detailed_feedback += f"الإجابة الصحيحة: {correct_option_text_for_log}\n"
        
        explanation = current_question_data.get("explanation")
        if explanation and isinstance(explanation, str) and explanation.strip():
            detailed_feedback += f"\n<b>الشرح:</b>\n{explanation}"

        if self.last_question_message_id:
            try:
                original_message = context.bot_data.get(f"msg_cache_{self.chat_id}_{self.last_question_message_id}")
                new_reply_markup = None # Remove buttons after answer
                
                if self.last_question_is_image and original_message and hasattr(original_message, 'caption') and original_message.caption is not None:
                    logger.debug(f"[QuizLogic {self.quiz_id}] Editing caption for image question result (q_idx {self.current_question_index}). MsgID: {self.last_question_message_id}")
                    new_caption = original_message.caption + "\n\n" + detailed_feedback
                    await bot.edit_message_caption(chat_id=self.chat_id, message_id=self.last_question_message_id, caption=new_caption, reply_markup=new_reply_markup, parse_mode='HTML')
                elif original_message and hasattr(original_message, 'text') and original_message.text is not None: # Text question
                    logger.debug(f"[QuizLogic {self.quiz_id}] Editing text for text question result (q_idx {self.current_question_index}). MsgID: {self.last_question_message_id}")
                    new_text = original_message.text + "\n\n" + detailed_feedback
                    await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=self.last_question_message_id, text=new_text, reply_markup=new_reply_markup, parse_mode='HTML')
                else:
                    logger.warning(f"[QuizLogic {self.quiz_id}] Could not determine original message type or content for editing feedback (q_idx {self.current_question_index}). MsgID: {self.last_question_message_id}. Sending new message.")
                    await safe_send_message(bot, chat_id=self.chat_id, text=detailed_feedback, parse_mode='HTML') # Fallback

            except telegram.error.BadRequest as e:
                if "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower() or "message is not modified" in str(e).lower():
                    logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message {self.last_question_message_id} (likely already deleted or uneditable): {e}. Sending new message with feedback.")
                    await safe_send_message(bot, chat_id=self.chat_id, text=detailed_feedback, parse_mode='HTML')
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Error editing message {self.last_question_message_id} with feedback: {e}", exc_info=True)
                    await safe_send_message(bot, chat_id=self.chat_id, text=detailed_feedback, parse_mode='HTML') # Fallback
            except Exception as e_edit:
                logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message {self.last_question_message_id} with feedback: {e_edit}", exc_info=True)
                await safe_send_message(bot, chat_id=self.chat_id, text=detailed_feedback, parse_mode='HTML') # Fallback
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] No last_question_message_id found to edit. Sending new message with feedback.")
            await safe_send_message(bot, chat_id=self.chat_id, text=detailed_feedback, parse_mode='HTML')

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await asyncio.sleep(1) # Brief pause before next question
            return await self.send_question(bot, context, user_id)
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz finished for user {user_id}. Score: {self.score}/{self.total_questions}")
            await asyncio.sleep(1) 
            return await self.show_results(bot, context, user_id)

    async def show_results(self, bot: Bot, context: CallbackContext, user_id: int):
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] show_results: inactive. User {user_id}. Aborting.")
            # Attempt to send a generic message if quiz is inactive but results are requested
            await safe_send_message(bot, chat_id=self.chat_id, text="انتهى هذا الاختبار أو لم يعد صالحاً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]])) 
            return END

        logger.info(f"[QuizLogic {self.quiz_id}] Showing results for user {user_id}. Score: {self.score}/{self.total_questions}")
        
        end_time_dt = datetime.now(timezone.utc)
        time_taken_seconds = (end_time_dt - self.quiz_actual_start_time_dt).total_seconds() if self.quiz_actual_start_time_dt else -1
        percentage = (self.score / self.total_questions * 100) if self.total_questions > 0 else 0
        
        # Calculate wrong and skipped answers
        wrong_answers_count = 0
        skipped_answers_count = 0
        for ans in self.answers:
            if not ans.get('is_correct') and ans.get('chosen_option_id') is not None and ans.get('time_taken', 0) >= 0: # Answered but wrong
                wrong_answers_count += 1
            elif ans.get('chosen_option_id') is None or ans.get('time_taken', 0) < -900 : # Skipped (includes timeout or error during send)
                skipped_answers_count += 1

        results_summary = f"🏁 <b>نتائج الاختبار ({self.quiz_name})</b> 🏁\n\n"
        results_summary += f"✨ نتيجتك: {self.score} من {self.total_questions} ({percentage:.2f}%)\n"
        results_summary += f"📉 الإجابات الخاطئة: {wrong_answers_count}\n"
        results_summary += f"⏭️ الأسئلة المتخطاة: {skipped_answers_count}\n"
        if time_taken_seconds >= 0:
            results_summary += f"⏱️ الوقت المستغرق: {int(time_taken_seconds // 60)} دقيقة و {int(time_taken_seconds % 60)} ثانية\n"
        else:
            results_summary += f"⏱️ الوقت المستغرق: غير متوفر\n"
        results_summary += "\n بالتوفيق في اختباراتك القادمة!"

        # Log results to database
        try:
            log_quiz_results(
                user_id=self.user_id,
                db_quiz_session_id=self.db_quiz_session_id, 
                quiz_id_uuid=self.quiz_id,
                quiz_name=self.quiz_name,
                quiz_type=self.quiz_type,
                quiz_scope_id=self.scope_id, # Use the stored scope_id
                total_questions=self.total_questions,
                score=self.score, # This is correct_answers_count
                wrong_answers=wrong_answers_count, # Pass calculated wrong_answers_count
                skipped_answers=skipped_answers_count, # Pass calculated skipped_answers_count
                percentage=percentage,
                start_time=self.quiz_actual_start_time_dt, # Pass the datetime object for quiz start
                end_time=end_time_dt, # Pass the datetime object for quiz end
                time_taken_seconds=int(time_taken_seconds) if time_taken_seconds >=0 else None,
                answers_details=self.answers
            )
            logger.info(f"[QuizLogic {self.quiz_id}] Successfully logged quiz results to DB for user {user_id}")
        except Exception as e_log:
            logger.error(f"[QuizLogic {self.quiz_id}] Failed to log quiz results to DB for user {user_id}: {e_log}", exc_info=True)
            # Optionally, inform the user that results couldn't be saved if critical
            # await safe_send_message(bot, chat_id=self.chat_id, text="عذرًا، حدث خطأ أثناء حفظ نتيجتك. قد لا تظهر في إحصائياتك.")

        keyboard = [[InlineKeyboardButton("📊 عرض الإحصائيات", callback_data="show_my_stats")],
                    [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_send_message(bot, chat_id=self.chat_id, text=results_summary, reply_markup=reply_markup, parse_mode='HTML')
        await self.cleanup_quiz_data(context, user_id, "quiz_completed_normally")
        return END

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.info(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user {user_id}. Reason: {reason}")
        self.active = False
        # Remove any pending timers for this quiz instance
        if self.total_questions > 0:
            for i in range(self.total_questions + 1): # Iterate up to total_questions to catch any lingering timers
                timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{i}"
                remove_job_if_exists(timer_job_name, context)
        
        # Clear from context.chat_data if this specific quiz_id is stored there
        if 'quiz_logic_instance' in context.chat_data and context.chat_data['quiz_logic_instance'].quiz_id == self.quiz_id:
            del context.chat_data['quiz_logic_instance']
            logger.debug(f"[QuizLogic {self.quiz_id}] Removed instance from context.chat_data for user {user_id}.")
        
        # Clear any message cache related to this quiz instance
        if hasattr(context, 'bot_data') and context.bot_data is not None:
            keys_to_delete = [k for k in context.bot_data if k.startswith(f"msg_cache_{self.chat_id}_")] # Simplified, might need quiz_id specific if multiple quizzes run
            for key in keys_to_delete:
                try:
                    del context.bot_data[key]
                    logger.debug(f"[QuizLogic {self.quiz_id}] Removed {key} from context.bot_data.")
                except KeyError:
                    pass # Key might have been removed by another process

        logger.info(f"[QuizLogic {self.quiz_id}] Cleanup complete for user {user_id}.")

async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    quiz_id = job_data.get("quiz_id")
    question_index = job_data.get("question_index")
    user_id = job_data.get("user_id")
    chat_id = job_data.get("chat_id")
    message_id = job_data.get("message_id")
    question_was_image = job_data.get("question_was_image", False)

    logger.info(f"[QuizLogic Timeout {quiz_id}] Question {question_index} timed out for user {user_id} in chat {chat_id}.")

    quiz_instance = None
    if 'quiz_logic_instance' in context.chat_data and context.chat_data['quiz_logic_instance'].quiz_id == quiz_id:
        quiz_instance = context.chat_data['quiz_logic_instance']
    
    if quiz_instance and quiz_instance.active and quiz_instance.current_question_index == question_index:
        logger.info(f"[QuizLogic Timeout {quiz_id}] Instance found and active. Processing timeout for q_idx {question_index}.")
        
        # Log the skipped answer due to timeout
        current_question_data_for_timeout = quiz_instance.questions_data[question_index]
        q_id_log_timeout = current_question_data_for_timeout.get('question_id', f'q_idx_{question_index}')
        correct_option_text_timeout = quiz_instance._get_correct_option_text_robust(current_question_data_for_timeout)

        quiz_instance.answers.append({
            "question_id": q_id_log_timeout,
            "question_text": current_question_data_for_timeout.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": None, # Skipped
            "chosen_option_text": "تم تخطي السؤال (نفاد الوقت)",
            "correct_option_id": str(current_question_data_for_timeout.get("correct_option_id")),
            "correct_option_text": correct_option_text_timeout,
            "is_correct": False,
            "time_taken": -999 # Indicate timeout
        })

        feedback_text = f"⌛ انتهى وقت السؤال {question_index + 1}!\nالإجابة الصحيحة: {correct_option_text_timeout}"
        explanation_timeout = current_question_data_for_timeout.get("explanation")
        if explanation_timeout and isinstance(explanation_timeout, str) and explanation_timeout.strip():
            feedback_text += f"\n\n<b>الشرح:</b>\n{explanation_timeout}"

        if message_id:
            try:
                original_message_timeout = context.bot_data.get(f"msg_cache_{chat_id}_{message_id}")
                new_reply_markup_timeout = None # Remove buttons

                if question_was_image and original_message_timeout and hasattr(original_message_timeout, 'caption') and original_message_timeout.caption is not None:
                    new_caption_timeout = original_message_timeout.caption + "\n\n" + feedback_text
                    await context.bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=new_caption_timeout, reply_markup=new_reply_markup_timeout, parse_mode='HTML')
                elif original_message_timeout and hasattr(original_message_timeout, 'text') and original_message_timeout.text is not None:
                    new_text_timeout = original_message_timeout.text + "\n\n" + feedback_text
                    await safe_edit_message_text(context.bot, chat_id=chat_id, message_id=message_id, text=new_text_timeout, reply_markup=new_reply_markup_timeout, parse_mode='HTML')
                else:
                    logger.warning(f"[QuizLogic Timeout {quiz_id}] Could not determine original message type for editing timeout feedback (q_idx {question_index}). MsgID: {message_id}. Sending new message.")
                    await safe_send_message(context.bot, chat_id=chat_id, text=feedback_text, parse_mode='HTML')
            except telegram.error.BadRequest as e_timeout_edit:
                if "message to edit not found" in str(e_timeout_edit).lower() or "message can't be edited" in str(e_timeout_edit).lower() or "message is not modified" in str(e_timeout_edit).lower():
                    logger.warning(f"[QuizLogic Timeout {quiz_id}] Failed to edit message {message_id} for timeout (likely deleted/uneditable): {e_timeout_edit}. Sending new message.")
                    await safe_send_message(context.bot, chat_id=chat_id, text=feedback_text, parse_mode='HTML')
                else:
                    logger.error(f"[QuizLogic Timeout {quiz_id}] Error editing message {message_id} for timeout: {e_timeout_edit}", exc_info=True)
                    await safe_send_message(context.bot, chat_id=chat_id, text=feedback_text, parse_mode='HTML')
            except Exception as e_timeout_generic:
                logger.error(f"[QuizLogic Timeout {quiz_id}] Generic error editing message {message_id} for timeout: {e_timeout_generic}", exc_info=True)
                await safe_send_message(context.bot, chat_id=chat_id, text=feedback_text, parse_mode='HTML')
        else:
            logger.warning(f"[QuizLogic Timeout {quiz_id}] No message_id in job_data to edit for timeout. Sending new message.")
            await safe_send_message(context.bot, chat_id=chat_id, text=feedback_text, parse_mode='HTML')

        quiz_instance.current_question_index += 1
        if quiz_instance.current_question_index < quiz_instance.total_questions:
            await asyncio.sleep(1) 
            await quiz_instance.send_question(context.bot, context, user_id)
        else:
            logger.info(f"[QuizLogic Timeout {quiz_id}] Quiz finished after timeout on last question for user {user_id}.")
            await asyncio.sleep(1)
            await quiz_instance.show_results(context.bot, context, user_id)
    elif not quiz_instance:
        logger.warning(f"[QuizLogic Timeout {quiz_id}] No active quiz instance found in chat_data for user {user_id}, chat {chat_id}. Timer job {context.job.name} might be orphaned.")
    elif not quiz_instance.active:
        logger.info(f"[QuizLogic Timeout {quiz_id}] Quiz instance found but not active for user {user_id}. Timer job {context.job.name} ignored.")
    elif quiz_instance.current_question_index != question_index:
        logger.info(f"[QuizLogic Timeout {quiz_id}] Quiz instance found, but current_question_index ({quiz_instance.current_question_index}) does not match job's question_index ({question_index}). Timer job {context.job.name} for user {user_id} ignored (likely answer was processed).")

