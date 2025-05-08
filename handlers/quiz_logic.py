# -*- coding: utf-8 -*-
# handlers/quiz_logic.py (v35 - Added saving results to DB)

import asyncio
import logging
import time
import uuid # لإنشاء معرّف فريد للاختبار
import telegram # For telegram.error types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot 
from telegram.ext import ConversationHandler, CallbackContext, JobQueue 
from config import logger, TAKING_QUIZ, END, MAIN_MENU 
from utils.helpers import safe_send_message, safe_edit_message_text, remove_job_if_exists
from database.data_logger import log_quiz_results # افتراض وجود هذه الدالة

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
        self.db_quiz_session_id = db_quiz_session_id # لتمرير معرّف جلسة الاختبار من قاعدة البيانات
        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized for user {self.user_id if self.user_id else 'UNKNOWN'} in chat {self.chat_id if self.chat_id else 'UNKNOWN'}. Quiz: {self.quiz_name}. Questions: {self.total_questions}. DB Session ID: {self.db_quiz_session_id}")

    async def start_quiz(self, bot: Bot, context: CallbackContext, update: Update, user_id: int) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] start_quiz called for user {user_id}, chat {self.chat_id}")
        self.active = True 
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
                    if question_text_from_data or header: 
                        full_question_text = header + question_text_from_data
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
        try:
            temp_parts = query.data.split("_", 1)
            if len(temp_parts) < 2 or not temp_parts[0] == "ans":
                raise ValueError("Callback data format error - prefix")
            rest_of_data = temp_parts[1]
            quiz_id_parts = rest_of_data.rsplit("_", 2)
            if len(quiz_id_parts) < 3:
                raise ValueError("Callback data format error - suffix")
            cb_quiz_id = quiz_id_parts[0]
            cb_q_idx_str = quiz_id_parts[1]
            cb_chosen_option_id_str = quiz_id_parts[2]
            q_idx_answered = int(cb_q_idx_str)
        except ValueError as e:
            logger.error(f"[QuizLogic {self.quiz_id}] Invalid callback: {query.data}. Error: {e}", exc_info=True)
            await query.answer("خطأ في بيانات الإجابة.")
            try:
                await bot.edit_message_reply_markup(chat_id=query.message.chat_id, message_id=query.message.message_id, reply_markup=None)
            except Exception as e_rem_markup:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to remove markup on invalid cb: {e_rem_markup}")
            return TAKING_QUIZ 
        if cb_quiz_id != self.quiz_id:
            await query.answer(text="هذه الإجابة لاختبار مختلف.")
            return TAKING_QUIZ
        if q_idx_answered != self.current_question_index:
            await query.answer(text="لقد أجبت على هذا السؤال بالفعل أو انتهى وقته.")
            return TAKING_QUIZ
        timer_job_name = f"qtimer_{user_id}_{query.message.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        await query.answer() 
        current_question_data = self.questions_data[self.current_question_index]
        q_text_for_ans = current_question_data.get("question_text", "نص السؤال غير متوفر")
        if not isinstance(q_text_for_ans, str) or not q_text_for_ans.strip(): q_text_for_ans = "نص السؤال غير متوفر"
        correct_option_id_str = str(current_question_data.get("correct_option_id"))
        options = current_question_data.get("options", [])
        is_correct = False
        chosen_option_text = "غير محدد"
        for opt in options:
            opt_id_current = str(opt.get("option_id"))
            if opt_id_current == cb_chosen_option_id_str:
                if opt.get("is_image_option"):
                    chosen_option_text = f"صورة ({opt.get('image_option_display_label', opt_id_current)})"
                else:
                    chosen_option_text = opt.get("option_text", f"خيار {opt_id_current}")
                    if not isinstance(chosen_option_text, str) or not chosen_option_text.strip():
                        chosen_option_text = f"خيار {opt_id_current}"
                if opt_id_current == correct_option_id_str:
                    is_correct = True
                    self.score += 1
                break
        retrieved_correct_option_text = self._get_correct_option_text_robust(current_question_data)
        self.answers.append({
            "question_id": current_question_data.get("question_id", f"q_idx_{self.current_question_index}"),
            "question_text": q_text_for_ans,
            "chosen_option_id": cb_chosen_option_id_str,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id_str,
            "correct_option_text": retrieved_correct_option_text, 
            "is_correct": is_correct,
            "time_taken": round(time_taken, 2)
        })
        feedback_text = "✅ إجابة صحيحة!" if is_correct else f"❌ إجابة خاطئة. الإجابة الصحيحة: {retrieved_correct_option_text}"
        if self.last_question_message_id and query.message.message_id == self.last_question_message_id:
            try:
                current_msg_text_or_caption = query.message.caption if self.last_question_is_image else query.message.text
                new_content = f"{current_msg_text_or_caption}\n\n{feedback_text}"
                if self.last_question_is_image:
                    await bot.edit_message_caption(chat_id=query.message.chat_id, message_id=self.last_question_message_id, caption=new_content, reply_markup=None, parse_mode='HTML')
                else:
                    await bot.edit_message_text(text=new_content, chat_id=query.message.chat_id, message_id=self.last_question_message_id, reply_markup=None, parse_mode='HTML')
            except telegram.error.BadRequest as e_edit:
                logger.warning(f"[QuizLogic {self.quiz_id}] Error editing message after answer: {e_edit}. Sending new message for feedback.")
                await safe_send_message(bot, chat_id=query.message.chat_id, text=feedback_text)
            except Exception as e_edit_generic:
                 logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing msg after answer: {e_edit_generic}", exc_info=True)
                 await safe_send_message(bot, chat_id=query.message.chat_id, text=feedback_text)
        else:
            await safe_send_message(bot, chat_id=query.message.chat_id, text=feedback_text)
        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            return await self.send_question(bot, context, user_id)
        else:
            self.active = False 
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz finished for user {user_id}. Total questions: {self.total_questions}, Score: {self.score}")
            return await self.show_results(bot, context, user_id)

    def is_finished(self) -> bool:
        if not self.active:
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz is_finished: True (inactive by self.active=False).")
            return True
        finished_by_index = self.current_question_index >= self.total_questions
        if finished_by_index:
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz is_finished: True (index {self.current_question_index} >= total {self.total_questions}).")
        return finished_by_index

    async def show_results(self, bot: Bot, context: CallbackContext, user_id: int):
        logger.info(f"[QuizLogic {self.quiz_id}] Showing results for user {user_id}, chat {self.chat_id}")
        
        # --- BEGIN: Save quiz results to database ---
        if self.db_quiz_session_id: # Ensure we have a session ID from the database
            try:
                percentage = (self.score / self.total_questions) * 100 if self.total_questions > 0 else 0
                # Assuming log_quiz_results takes these parameters. Adjust if different.
                log_quiz_results(
                    db_quiz_session_id=self.db_quiz_session_id,
                    user_id=self.user_id,
                    quiz_id_uuid=self.quiz_id, # This is the QuizLogic's internal UUID for the quiz instance
                    quiz_name=self.quiz_name,
                    quiz_type=self.quiz_type,
                    score=self.score,
                    total_questions=self.total_questions,
                    percentage=percentage,
                    answers_details=self.answers # Pass the detailed answers list
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Successfully logged quiz results to DB for session {self.db_quiz_session_id}")
            except Exception as e_log_results:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to log quiz results to DB for session {self.db_quiz_session_id}: {e_log_results}", exc_info=True)
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] Cannot log quiz results to DB: db_quiz_session_id is missing.")
        # --- END: Save quiz results to database ---

        if not self.answers:
            results_text = "لم يتم الإجابة على أي أسئلة."
        else:
            results_text = f"🎉 <b>نتائج اختبار {self.quiz_name}</b> 🎉\n\n"
            results_text += f"✨ لقد أجبت بشكل صحيح على <b>{self.score}</b> من <b>{self.total_questions}</b> أسئلة ✨\n"
            percentage_display = (self.score / self.total_questions) * 100 if self.total_questions > 0 else 0 # Recalculate for display if needed
            results_text += f"🎯 نسبتك: <b>{percentage_display:.2f}%</b>\n\n"
            results_text += "<b>تفاصيل إجاباتك:</b>\n"
            for i, ans in enumerate(self.answers):
                q_text_short = ans.get("question_text", "سؤال غير معروف")
                if len(q_text_short) > 70: q_text_short = q_text_short[:67] + "..."
                chosen_ans_text = ans.get("chosen_option_text", "لم تختر")
                if len(chosen_ans_text) > 50: chosen_ans_text = chosen_ans_text[:47] + "..."
                correct_ans_text = ans.get("correct_option_text", "خطأ في عرض الإجابة الصحيحة")
                if len(correct_ans_text) > 50: correct_ans_text = correct_ans_text[:47] + "..."
                status_emoji = "✅" if ans.get("is_correct") else "❌"
                time_taken_str = f"{ans.get('time_taken', 0):.1f} ث" if ans.get('time_taken', 0) >= 0 else "-"
                if ans.get('time_taken') == -999: time_taken_str = "مهلة"
                elif ans.get('time_taken') == -998: time_taken_str = "تخطي (قليل الخيارات)"
                elif ans.get('time_taken') == -997: time_taken_str = "تخطي (خطأ إرسال)"
                results_text += f"\n{i+1}. {q_text_short}\n"
                results_text += f"   {status_emoji} اختيارك: {chosen_ans_text}\n"
                if not ans.get("is_correct") or ans.get("chosen_option_id") is None:
                    results_text += f"   💡 الصحيح: {correct_ans_text}\n"
                results_text += f"   ⏱️ الوقت: {time_taken_str}\n"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("ابدأ اختبار جديد", callback_data="quiz_menu_entry")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]
        ])
        message_to_edit_id = self.last_question_message_id
        if not message_to_edit_id and context.user_data.get(f"quiz_start_message_id_{self.quiz_id}"):
             message_to_edit_id = context.user_data.pop(f"quiz_start_message_id_{self.quiz_id}", None)
        if message_to_edit_id:
            try:
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=message_to_edit_id, text=results_text, reply_markup=keyboard, parse_mode='HTML')
            except Exception as e_edit_results:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message for results (msg_id: {message_to_edit_id}): {e_edit_results}. Sending new message.")
                await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=keyboard, parse_mode='HTML')
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] No specific message to edit for results. Sending new message.")
            await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=keyboard, parse_mode='HTML')
        await self.cleanup_quiz_data(context, user_id, "results_shown")
        return END 

    async def handle_timeout(self, bot: Bot, context: CallbackContext, user_id: int, question_index: int, message_id: int, question_was_image: bool):
        logger.info(f"[QuizLogic {self.quiz_id}] Handling timeout for user {user_id}, q_idx {question_index}, msg_id {message_id}")
        if not self.active or str(user_id) != str(self.user_id) or question_index != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Timeout for inactive/mismatched quiz/user/question. User: {user_id}, Q_idx: {question_index}. Current Q_idx: {self.current_question_index}. Active: {self.active}")
            return
        current_question_data = self.questions_data[self.current_question_index]
        q_text_for_ans = current_question_data.get("question_text", "نص السؤال غير متوفر")
        if not isinstance(q_text_for_ans, str) or not q_text_for_ans.strip(): q_text_for_ans = "نص السؤال غير متوفر"
        correct_option_id_str = str(current_question_data.get("correct_option_id"))
        retrieved_correct_option_text = self._get_correct_option_text_robust(current_question_data)
        self.answers.append({
            "question_id": current_question_data.get("question_id", f"q_idx_{self.current_question_index}"),
            "question_text": q_text_for_ans,
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": correct_option_id_str,
            "correct_option_text": retrieved_correct_option_text, 
            "is_correct": False,
            "time_taken": -999 
        })
        timeout_feedback = f"⌛ انتهى الوقت! الإجابة الصحيحة كانت: {retrieved_correct_option_text}"
        cached_message = context.bot_data.pop(f"msg_cache_{self.chat_id}_{message_id}", None)
        original_content = ""
        if cached_message:
            original_content = cached_message.caption if question_was_image else cached_message.text
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] Timeout: Original message {message_id} not found in cache for q_id {current_question_data.get('question_id')}.")
        new_content_on_timeout = f"{original_content}\n\n{timeout_feedback}" if original_content else timeout_feedback
        try:
            if question_was_image:
                await bot.edit_message_caption(chat_id=self.chat_id, message_id=message_id, caption=new_content_on_timeout, reply_markup=None, parse_mode='HTML')
            else:
                await bot.edit_message_text(text=new_content_on_timeout, chat_id=self.chat_id, message_id=message_id, reply_markup=None, parse_mode='HTML')
        except telegram.error.BadRequest as e_timeout_edit:
            if "message is not modified" not in str(e_timeout_edit).lower():
                logger.warning(f"[QuizLogic {self.quiz_id}] Error editing message on timeout (msg_id {message_id}): {e_timeout_edit}. Sending new message for feedback.")
                await safe_send_message(bot, chat_id=self.chat_id, text=timeout_feedback)
        except Exception as e_timeout_generic:
            logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing msg on timeout (msg_id {message_id}): {e_timeout_generic}", exc_info=True)
            await safe_send_message(bot, chat_id=self.chat_id, text=timeout_feedback)
        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await self.send_question(bot, context, user_id)
        else:
            self.active = False 
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz ended due to timeout on last question. User {user_id}")
            await self.show_results(bot, context, user_id)

    async def end_quiz(self, bot: Bot, context: CallbackContext, update: Update, manual_end: bool = False, reason_suffix: str = "ended") -> None:
        user_id = self.user_id
        logger.info(f"[QuizLogic {self.quiz_id}] end_quiz called for user {user_id}. Manual: {manual_end}. Reason: {reason_suffix}")
        self.active = False
        timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        if manual_end:
            end_message = "تم إنهاء الاختبار يدوياً."
            message_to_edit_id = self.last_question_message_id
            if not message_to_edit_id and update and update.callback_query and update.callback_query.message:
                 message_to_edit_id = update.callback_query.message.message_id
            if message_to_edit_id:
                try:
                    await bot.edit_message_reply_markup(chat_id=self.chat_id, message_id=message_to_edit_id, reply_markup=None)
                    await safe_send_message(bot, chat_id=self.chat_id, text=end_message)
                except Exception as e_edit_manual_end:
                    logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit markup on manual end (msg_id {message_to_edit_id}): {e_edit_manual_end}. Sending new message.")
                    await safe_send_message(bot, chat_id=self.chat_id, text=end_message)
            else:
                await safe_send_message(bot, chat_id=self.chat_id, text=end_message)
        await self.cleanup_quiz_data(context, user_id, reason_suffix)

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str = "unknown"):
        logger.debug(f"[QuizLogic {self.quiz_id}] cleanup_quiz_data called for user {user_id}. Reason: {reason}")
        self.active = False 
        if context.user_data and f"quiz_logic_{user_id}" in context.user_data:
            if self.quiz_id in context.user_data[f"quiz_logic_{user_id}"]:
                del context.user_data[f"quiz_logic_{user_id}"][self.quiz_id]
                logger.info(f"[QuizLogic {self.quiz_id}] Removed quiz session {self.quiz_id} from user_data for user {user_id}.")
                if not context.user_data[f"quiz_logic_{user_id}"]:
                    del context.user_data[f"quiz_logic_{user_id}"]
                    logger.info(f"[QuizLogic {self.quiz_id}] quiz_sessions dict is now empty for user {user_id}, removed from user_data.")
            else:
                logger.warning(f"[QuizLogic {self.quiz_id}] Quiz ID {self.quiz_id} not found in user_data[{f'quiz_logic_{user_id}'}] for cleanup.")
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] 'quiz_logic_{user_id}' not found in user_data for cleanup.")

async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    quiz_id = job_data["quiz_id"]
    question_index = job_data["question_index"]
    user_id = job_data["user_id"]
    chat_id = job_data["chat_id"]
    message_id = job_data["message_id"]
    question_was_image = job_data["question_was_image"]
    logger.info(f"Timeout job triggered for user {user_id}, quiz {quiz_id}, q_idx {question_index}")
    quiz_logic_instance = None
    if context.user_data and f"quiz_logic_{user_id}" in context.user_data and quiz_id in context.user_data[f"quiz_logic_{user_id}"]:
        quiz_logic_instance = context.user_data[f"quiz_logic_{user_id}"][quiz_id]
    if quiz_logic_instance and quiz_logic_instance.active and quiz_logic_instance.current_question_index == question_index:
        await quiz_logic_instance.handle_timeout(context.bot, context, user_id, question_index, message_id, question_was_image)
    else:
        logger.warning(f"Timeout job for user {user_id}, quiz {quiz_id}, q_idx {question_index}: Quiz instance not found, inactive, or question already answered/skipped.")

