# -*- coding: utf-8 -*-
# handlers/quiz_logic.py (v33 - Added is_finished method)

import asyncio
import logging
import time
import uuid # لإنشاء معرّف فريد للاختبار
import telegram # For telegram.error types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot 
from telegram.ext import ConversationHandler, CallbackContext, JobQueue 
from config import logger, TAKING_QUIZ, END, MAIN_MENU 
from utils.helpers import safe_send_message, safe_edit_message_text, remove_job_if_exists

MIN_OPTIONS_PER_QUESTION = 2

class QuizLogic:
    ARABIC_CHOICE_LETTERS = ["أ", "ب", "ج", "د"]

    def __init__(self, user_id=None, chat_id=None, quiz_type=None, questions_data=None, total_questions=0, question_time_limit=60, quiz_id=None, quiz_name=None):
        self.user_id = user_id
        self.chat_id = chat_id # Added chat_id
        self.quiz_id = quiz_id if quiz_id else str(uuid.uuid4()) 
        self.quiz_name = quiz_name if quiz_name else "اختبار غير مسمى" # Added quiz_name
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
        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized for user {self.user_id if self.user_id else 'UNKNOWN'} in chat {self.chat_id if self.chat_id else 'UNKNOWN'}. Quiz: {self.quiz_name}. Questions: {self.total_questions}")

    async def start_quiz(self, bot: Bot, context: CallbackContext, update: Update, user_id: int) -> int: # Removed chat_id from here as it's now in self
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
        
        return await self.send_question(bot, context, user_id) # Removed chat_id from here
    
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

    async def send_question(self, bot: Bot, context: CallbackContext, user_id: int): # Removed chat_id from here
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
                    "correct_option_text": "غير محدد",
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
                        chat_id=self.chat_id, # Use self.chat_id
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
                    "correct_option_text": "غير محدد",
                    "is_correct": False,
                    "time_taken": -997 
                })
                self.current_question_index += 1
        
        logger.info(f"[QuizLogic {self.quiz_id}] No more valid questions to send or quiz ended. User {user_id}. Showing results.")
        return await self.show_results(bot, context, user_id) # Removed chat_id from here

    async def handle_answer(self, bot: Bot, context: CallbackContext, update: Update):
        query = update.callback_query
        user_id = query.from_user.id

        if not self.active or str(user_id) != str(self.user_id):
            await query.answer(text="هذا الاختبار ليس لك أو لم يعد نشطاً.", show_alert=True)
            return TAKING_QUIZ 

        time_taken = time.time() - self.question_start_time if self.question_start_time else -1
        
        try:
            parts = query.data.rsplit("_", 3) # Corrected to use rsplit
            if len(parts) < 4 or parts[0] != 'ans':
                raise ValueError("Callback data format error")
            cb_quiz_id, cb_q_idx_str, cb_chosen_option_id_str = parts[1], parts[2], parts[3]
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

        correct_option_id = str(current_question_data.get("correct_option_id"))
        options = current_question_data.get("options", [])
        is_correct = False
        chosen_option_text = "غير محدد"
        correct_option_text = "غير محدد"

        for opt in options:
            opt_id_current = str(opt.get("option_id"))
            opt_text_current_val = opt.get("option_text", f"خيار {opt_id_current}")
            if opt.get("is_image_option"):
                 opt_text_current_val = f"صورة ({opt.get('image_option_display_label', opt_id_current)})"
            elif not isinstance(opt_text_current_val, str) or not opt_text_current_val.strip():
                opt_text_current_val = f"خيار {opt_id_current}"

            if opt_id_current == cb_chosen_option_id_str:
                chosen_option_text = opt_text_current_val
                if opt_id_current == correct_option_id:
                    is_correct = True
                    self.score += 1
            if opt_id_current == correct_option_id:
                correct_option_text = opt_text_current_val
        
        self.answers.append({
            "question_id": current_question_data.get("question_id", f"q_idx_{self.current_question_index}"),
            "question_text": q_text_for_ans,
            "chosen_option_id": cb_chosen_option_id_str,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text,
            "is_correct": is_correct,
            "time_taken": round(time_taken, 2)
        })

        feedback_text = "✅ إجابة صحيحة!" if is_correct else f"❌ إجابة خاطئة. الإجابة الصحيحة: {correct_option_text}"
        if self.last_question_message_id and query.message.message_id == self.last_question_message_id:
            try:
                if self.last_question_is_image:
                    await bot.edit_message_caption(chat_id=query.message.chat_id, message_id=self.last_question_message_id, caption=f"{query.message.caption}\n\n{feedback_text}", reply_markup=None, parse_mode='HTML')
                else:
                    await bot.edit_message_text(text=f"{query.message.text}\n\n{feedback_text}", chat_id=query.message.chat_id, message_id=self.last_question_message_id, reply_markup=None, parse_mode='HTML')
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
            return await self.send_question(bot, context, user_id) # Removed chat_id
        else:
            self.active = False 
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz finished for user {user_id}. Total questions: {self.total_questions}, Score: {self.score}")
            return await self.show_results(bot, context, user_id) # Removed chat_id

    def is_finished(self) -> bool:
        """Checks if the quiz is finished or inactive."""
        if not self.active:
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz is_finished: True (inactive by self.active=False).")
            return True
        finished_by_index = self.current_question_index >= self.total_questions
        if finished_by_index:
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz is_finished: True (index {self.current_question_index} >= total {self.total_questions}).")
        return finished_by_index

    async def show_results(self, bot: Bot, context: CallbackContext, user_id: int): # Removed chat_id
        logger.info(f"[QuizLogic {self.quiz_id}] Showing results for user {user_id}, chat {self.chat_id}")
        if not self.answers:
            results_text = "لم يتم الإجابة على أي أسئلة."
        else:
            results_text = f"🎉 <b>نتائج اختبار {self.quiz_name}</b> 🎉\n\n"
            results_text += f"✨ لقد أجبت بشكل صحيح على <b>{self.score}</b> من <b>{self.total_questions}</b> أسئلة ✨\n"
            percentage = (self.score / self.total_questions) * 100 if self.total_questions > 0 else 0
            results_text += f"🎯 نسبتك: <b>{percentage:.2f}%</b>\n\n"
            
            results_text += "<b>تفاصيل إجاباتك:</b>\n"
            for i, ans in enumerate(self.answers):
                q_text_short = ans.get("question_text", "سؤال غير معروف")
                if len(q_text_short) > 70: q_text_short = q_text_short[:67] + "..."
                chosen_ans_text = ans.get("chosen_option_text", "لم تختر")
                if len(chosen_ans_text) > 50: chosen_ans_text = chosen_ans_text[:47] + "..."
                correct_ans_text = ans.get("correct_option_text", "غير محدد")
                if len(correct_ans_text) > 50: correct_ans_text = correct_ans_text[:47] + "..."
                status_emoji = "✅" if ans.get("is_correct") else "❌"
                time_taken_str = f"{ans.get('time_taken', 0):.1f} ث" if ans.get('time_taken', 0) >= 0 else "-"
                if ans.get('time_taken') == -999: time_taken_str = "مهلة"
                elif ans.get('time_taken') == -998: time_taken_str = "تخطي"
                elif ans.get('time_taken') == -997: time_taken_str = "خطأ"

                results_text += f"\n{i+1}. {q_text_short}\n"
                results_text += f"   {status_emoji} اختيارك: {chosen_ans_text}\n"
                if not ans.get("is_correct") and ans.get("chosen_option_id") is not None:
                    results_text += f"   💡 الصحيح: {correct_ans_text}\n"
                elif ans.get("chosen_option_id") is None and ans.get('time_taken') == -999: # Timeout
                     results_text += f"   💡 الصحيح: {correct_ans_text}\n"
                results_text += f"   ⏱️ الوقت: {time_taken_str}\n"

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]])
        
        if self.last_question_message_id:
            try:
                await safe_edit_message_text(bot, chat_id=self.chat_id, message_id=self.last_question_message_id, text=results_text, reply_markup=keyboard, parse_mode='HTML')
            except Exception as e_edit_results:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit last question message for results: {e_edit_results}. Sending new message.")
                await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=keyboard, parse_mode='HTML')
        else:
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
        correct_option_id = str(current_question_data.get("correct_option_id"))
        correct_option_text = "غير محدد"
        options = current_question_data.get("options", [])
        for opt in options:
            if str(opt.get("option_id")) == correct_option_id:
                correct_option_text = opt.get("option_text", "غير محدد")
                if opt.get("is_image_option"):
                    correct_option_text = f"صورة ({opt.get('image_option_display_label', correct_option_id)})"
                elif not isinstance(correct_option_text, str) or not correct_option_text.strip():
                     correct_option_text = f"خيار {correct_option_id}"
                break
        
        self.answers.append({
            "question_id": current_question_data.get("question_id", f"q_idx_{self.current_question_index}"),
            "question_text": q_text_for_ans,
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text,
            "is_correct": False,
            "time_taken": -999 
        })

        timeout_feedback = f"⌛ انتهى الوقت! الإجابة الصحيحة كانت: {correct_option_text}"
        
        cached_message = context.bot_data.pop(f"msg_cache_{self.chat_id}_{message_id}", None)
        
        try:
            if cached_message:
                if question_was_image:
                    await bot.edit_message_caption(chat_id=self.chat_id, message_id=message_id, caption=f"{cached_message.caption}\n\n{timeout_feedback}", reply_markup=None, parse_mode='HTML')
                else:
                    await bot.edit_message_text(text=f"{cached_message.text}\n\n{timeout_feedback}", chat_id=self.chat_id, message_id=message_id, reply_markup=None, parse_mode='HTML')
            else: 
                logger.warning(f"[QuizLogic {self.quiz_id}] Timeout: Original message {message_id} not found in cache. Sending new message for feedback.")
                await safe_send_message(bot, chat_id=self.chat_id, text=timeout_feedback)
        except telegram.error.BadRequest as e_timeout_edit:
            logger.warning(f"[QuizLogic {self.quiz_id}] Error editing message on timeout: {e_timeout_edit}. Sending new message for feedback.")
            await safe_send_message(bot, chat_id=self.chat_id, text=timeout_feedback)
        except Exception as e_timeout_generic:
            logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing msg on timeout: {e_timeout_generic}", exc_info=True)
            await safe_send_message(bot, chat_id=self.chat_id, text=timeout_feedback)

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await self.send_question(bot, context, user_id) # Removed chat_id
        else:
            self.active = False 
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz ended due to timeout on last question. User {user_id}")
            await self.show_results(bot, context, user_id) # Removed chat_id

    async def end_quiz(self, bot: Bot, context: CallbackContext, update: Update, manual_end: bool = False, reason_suffix: str = "ended") -> None:
        user_id = self.user_id
        logger.info(f"[QuizLogic {self.quiz_id}] end_quiz called for user {user_id}. Manual: {manual_end}. Reason: {reason_suffix}")
        self.active = False
        timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        
        if manual_end:
            end_message = "تم إنهاء الاختبار يدوياً."
            if self.last_question_message_id:
                try:
                    await bot.edit_message_reply_markup(chat_id=self.chat_id, message_id=self.last_question_message_id, reply_markup=None)
                    await safe_send_message(bot, chat_id=self.chat_id, text=end_message, reply_to_message_id=self.last_question_message_id)
                except Exception as e_edit_manual_end:
                    logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit last q msg on manual end: {e_edit_manual_end}. Sending new msg.")
                    await safe_send_message(bot, chat_id=self.chat_id, text=end_message)
            else:
                 await safe_send_message(bot, chat_id=self.chat_id, text=end_message)
        
        await self.cleanup_quiz_data(context, user_id, reason_suffix)
        logger.info(f"[QuizLogic {self.quiz_id}] Quiz instance {self.quiz_id} for user {user_id} has been marked inactive and data cleaned.")

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str = "unknown") -> None:
        logger.debug(f"[QuizLogic {self.quiz_id}] cleanup_quiz_data called for user {user_id}. Reason: {reason}")
        self.active = False 
        if 'quiz_sessions' in context.user_data and self.quiz_id in context.user_data['quiz_sessions']:
            del context.user_data['quiz_sessions'][self.quiz_id]
            logger.info(f"[QuizLogic {self.quiz_id}] Removed quiz session {self.quiz_id} from user_data for user {user_id}.")
        if not context.user_data.get('quiz_sessions'): 
            context.user_data.pop('quiz_sessions', None)
            logger.info(f"[QuizLogic {self.quiz_id}] quiz_sessions dict is now empty for user {user_id}, removed from user_data.")

async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    quiz_id = job_data.get("quiz_id")
    question_index = job_data.get("question_index")
    user_id = job_data.get("user_id")
    chat_id = job_data.get("chat_id") 
    message_id = job_data.get("message_id")
    question_was_image = job_data.get("question_was_image", False)

    logger.info(f"Timeout job triggered for user {user_id}, quiz {quiz_id}, q_idx {question_index} in chat {chat_id}")

    if 'quiz_sessions' not in context.user_data or quiz_id not in context.user_data['quiz_sessions']:
        logger.warning(f"Timeout: Quiz session {quiz_id} not found for user {user_id}. Job: {context.job.name}")
        return

    quiz_instance = context.user_data['quiz_sessions'][quiz_id]

    if not isinstance(quiz_instance, QuizLogic):
        logger.error(f"Timeout: Object for quiz_id {quiz_id} is not a QuizLogic instance. Type: {type(quiz_instance)}. User: {user_id}")
        return

    if quiz_instance.is_finished():
        logger.info(f"Timeout: Quiz {quiz_id} already finished for user {user_id}. Current q_idx: {quiz_instance.current_question_index}. Job: {context.job.name}")
        return
    
    if str(quiz_instance.user_id) != str(user_id) or str(quiz_instance.chat_id) != str(chat_id):
        logger.warning(f"Timeout: Mismatch in user/chat ID for quiz {quiz_id}. Expected u:{user_id}/c:{chat_id}, got u:{quiz_instance.user_id}/c:{quiz_instance.chat_id}. Job: {context.job.name}")
        return

    if quiz_instance.current_question_index != question_index:
        logger.info(f"Timeout: Question index mismatch for quiz {quiz_id}. Expected {question_index}, got {quiz_instance.current_question_index}. User {user_id}. Job: {context.job.name}. Likely already answered.")
        return

    await quiz_instance.handle_timeout(context.bot, context, user_id, question_index, message_id, question_was_image)

