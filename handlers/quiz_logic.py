# -*- coding: utf-8 -*-
# handlers/quiz_logic.py (v30 - Final Merge with Enhanced Results)

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

    def __init__(self, user_id=None, quiz_type=None, questions_data=None, total_questions=0, question_time_limit=60, quiz_id=None):
        self.user_id = user_id
        self.quiz_id = quiz_id if quiz_id else str(uuid.uuid4()) 
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
        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized for user {self.user_id if self.user_id else 'UNKNOWN'}. Questions: {self.total_questions}")

    async def start_quiz(self, bot: Bot, context: CallbackContext, update: Update, chat_id: int, user_id: int) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] start_quiz called for user {user_id}, chat {chat_id}")
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
                await safe_edit_message_text(bot, chat_id=chat_id, message_id=message_to_edit_id, text=text_no_questions, reply_markup=keyboard_to_main)
            else:
                await safe_send_message(bot, chat_id=chat_id, text=text_no_questions, reply_markup=keyboard_to_main)
            await self.cleanup_quiz_data(context, user_id, "no_questions_on_start") 
            return END 
        
        return await self.send_question(bot, context, chat_id, user_id)
    
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

    async def send_question(self, bot: Bot, context: CallbackContext, chat_id: int, user_id: int):
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
                        await bot.send_photo(chat_id=chat_id, photo=option_text_original, caption=f"الخيار: {display_label}")
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
                    sent_message = await bot.send_photo(chat_id=chat_id, photo=image_url, caption=caption_text, reply_markup=options_keyboard, parse_mode="HTML")
                    self.last_question_is_image = True
                except Exception as e:
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to send photo q_id {q_id_log}: {e}. URL: {image_url}", exc_info=True)
                    if question_text_from_data or header: 
                        full_question_text = header + question_text_from_data
                        try:
                            sent_message = await safe_send_message(bot, chat_id=chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                        except Exception as e_fallback_text:
                            logger.error(f"[QuizLogic {self.quiz_id}] Fallback text failed q_id {q_id_log}: {e_fallback_text}", exc_info=True)
            else:
                if not question_text_from_data.strip():
                    question_text_from_data = "نص السؤال غير متوفر حالياً."
                full_question_text = header + question_text_from_data
                try:
                    sent_message = await safe_send_message(bot, chat_id=chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                except Exception as e:
                     logger.error(f"[QuizLogic {self.quiz_id}] Error sending text question q_id {q_id_log}: {e}.", exc_info=True)

            if sent_message:
                self.last_question_message_id = sent_message.message_id
                self.question_start_time = time.time()
                timer_job_name = f"qtimer_{user_id}_{chat_id}_{self.quiz_id}_{self.current_question_index}"
                remove_job_if_exists(timer_job_name, context) 

                if not hasattr(context, 'bot_data') or context.bot_data is None: context.bot_data = {}
                context.bot_data[f"msg_cache_{chat_id}_{sent_message.message_id}"] = sent_message

                if context.job_queue:
                     context.job_queue.run_once(
                        question_timeout_callback_wrapper, 
                        self.question_time_limit,
                        chat_id=chat_id,
                        user_id=user_id,
                        name=timer_job_name,
                        data={"quiz_id": self.quiz_id, "question_index": self.current_question_index, "user_id": user_id, "chat_id": chat_id, "message_id": sent_message.message_id, "question_was_image": self.last_question_is_image}
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
        return await self.show_results(bot, context, chat_id, user_id)

    async def handle_answer(self, bot: Bot, context: CallbackContext, update: Update):
        query = update.callback_query
        user_id = query.from_user.id

        if not self.active or str(user_id) != str(self.user_id):
            await query.answer(text="هذا الاختبار ليس لك أو لم يعد نشطاً.", show_alert=True)
            return TAKING_QUIZ 

        time_taken = time.time() - self.question_start_time if self.question_start_time else -1
        
        try:
            parts = query.data.split("_", 3) 
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
            
            if opt_id_current == correct_option_id:
                correct_option_text = opt_text_current_val

        if is_correct:
            self.score += 1
            feedback_text = "✅ إجابة صحيحة!"
        else:
            feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة كانت: {correct_option_text}"
        
        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": q_text_for_ans,
            "chosen_option_id": cb_chosen_option_id_str,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text,
            "is_correct": is_correct,
            "time_taken": time_taken
        })

        header_part = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
        original_content_for_feedback = ""
        if self.last_question_is_image and query.message.caption:
            original_content_for_feedback = query.message.caption
        elif not self.last_question_is_image and query.message.text:
            original_content_for_feedback = query.message.text
        else: 
            original_content_for_feedback = header_part + q_text_for_ans

        if original_content_for_feedback.startswith(header_part):
             text_content_for_feedback = original_content_for_feedback[len(header_part):]
        else:
             text_content_for_feedback = original_content_for_feedback

        full_feedback_message = f"{header_part}{text_content_for_feedback}\n\nاخترت: {chosen_option_text}\n{feedback_text}"

        try:
            if self.last_question_is_image and query.message.caption is not None:
                await bot.edit_message_caption(chat_id=query.message.chat_id, message_id=query.message.message_id, caption=full_feedback_message, parse_mode='HTML')
            elif not self.last_question_is_image and query.message.text is not None:
                await bot.edit_message_text(text=full_feedback_message, chat_id=query.message.chat_id, message_id=query.message.message_id, parse_mode='HTML', reply_markup=None)
            else:
                logger.warning(f"[QuizLogic {self.quiz_id}] Cannot edit feedback q_idx {self.current_question_index}, unexpected original msg type.")
                await safe_send_message(bot, chat_id=query.message.chat_id, text=full_feedback_message, parse_mode='HTML')
        except telegram.error.BadRequest as e_bad_req:
            if "message is not modified" in str(e_bad_req).lower():
                logger.info(f"[QuizLogic {self.quiz_id}] Feedback msg q_idx {self.current_question_index} not modified.")
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] BadRequest editing feedback q_idx {self.current_question_index}: {e_bad_req}", exc_info=True)
                await safe_send_message(bot, chat_id=query.message.chat_id, text=full_feedback_message, parse_mode='HTML')
        except Exception as e_feedback:
            logger.error(f"[QuizLogic {self.quiz_id}] Error sending feedback q_idx {self.current_question_index}: {e_feedback}", exc_info=True)
            await safe_send_message(bot, chat_id=query.message.chat_id, text=full_feedback_message, parse_mode='HTML')

        self.current_question_index += 1
        await asyncio.sleep(2) 
        return await self.send_question(bot, context, query.message.chat_id, user_id)
        
    async def show_results(self, bot: Bot, context: CallbackContext, chat_id: int, user_id: int):
        logger.info(f"[QuizLogic {self.quiz_id}] Showing results for user {user_id}.")
        
        results_text = f"🏁 <b>نتائج الاختبار</b> 🏁\n\n"
        
        actual_questions_attempted_or_skipped = len(self.answers)
        denominator_for_percentage = self.total_questions if self.total_questions > 0 else actual_questions_attempted_or_skipped
        
        results_text += f"✨ لقد حصلت على: <b>{self.score} من {self.total_questions}</b>\n"
        
        percentage = (self.score / denominator_for_percentage) * 100 if denominator_for_percentage > 0 else 0
        results_text += f"🎯 النسبة المئوية: <b>{percentage:.2f}%</b>\n\n"

        if percentage >= 80:
            results_text += "🎉 ممتاز! أداء رائع! 🎉\n"
        elif percentage >= 60:
            results_text += "👍 جيد جداً! استمر في التقدم! 👍\n"
        elif percentage >= 40:
            results_text += "💪 لا بأس! يمكنك فعل ما هو أفضل في المرة القادمة! 💪\n"
        else:
            results_text += "😔 حظ أوفر في المرة القادمة. المزيد من المذاكرة قد يساعد. 😔\n"

        if not self.answers and self.total_questions > 0 :
            results_text += "\n\nلم يتم تسجيل أي إجابات أو تم تخطي جميع الأسئلة."
        elif self.total_questions == 0 and not self.answers: 
             results_text += "\n\nلم تكن هناك أسئلة في هذا الاختبار."
        elif self.answers: 
            results_text += "\n--- <b>تفاصيل إجاباتك</b> ---\n"
            for i, ans in enumerate(self.answers):
                q_text_short = ans.get("question_text", "سؤال غير متوفر")
                if len(q_text_short) > 50: q_text_short = q_text_short[:47] + "..."
                
                chosen_opt_text = ans.get("chosen_option_text", "لم تختر")
                correct_opt_text = ans.get("correct_option_text", "غير محددة")
                status_emoji = ""
                
                time_taken_code = ans.get("time_taken", 0) 

                if time_taken_code == -999: 
                    status_emoji = "⏰"
                    chosen_opt_text = "انتهى الوقت"
                    results_text += f"\n\n{i+1}. {q_text_short}\n   {status_emoji} {chosen_opt_text}! الإجابة الصحيحة كانت: {correct_opt_text}"
                elif time_taken_code == -998: 
                     results_text += f"\n\n{i+1}. {q_text_short}\n   ⚠️ تم تخطي السؤال (خيارات غير كافية)."
                elif time_taken_code == -997: 
                     results_text += f"\n\n{i+1}. {q_text_short}\n   ⚠️ تم تخطي السؤال (خطأ في الإرسال)."
                else: 
                    status_emoji = "✅" if ans.get("is_correct") else "❌"
                    results_text += f"\n\n{i+1}. {q_text_short}\n   {status_emoji} إجابتك: {chosen_opt_text}"
                    if not ans.get("is_correct"):
                        results_text += f"\n   الصحيحة: {correct_opt_text}"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("ابدأ اختبار جديد", callback_data="start_quiz_new")], 
            [InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]
        ])
        await safe_send_message(bot, chat_id=chat_id, text=results_text, reply_markup=keyboard, parse_mode='HTML')
        await self.cleanup_quiz_data(context, user_id, "quiz_completed_normally")
        return END 

    async def handle_timeout(self, bot: Bot, context: CallbackContext, chat_id: int, user_id: int, message_id: int, question_was_image: bool):
        logger.info(f"[QuizLogic {self.quiz_id}] Timeout q_idx {self.current_question_index} user {user_id}.")
        if not self.active or str(user_id) != str(self.user_id):
            logger.warning(f"[QuizLogic {self.quiz_id}] Timeout for inactive/mismatched user. Job user: {user_id}, quiz user: {self.user_id}")
            return 

        current_question_data = self.questions_data[self.current_question_index]
        q_text_for_ans = current_question_data.get("question_text", "نص السؤال غير متوفر")
        if not isinstance(q_text_for_ans, str) or not q_text_for_ans.strip(): q_text_for_ans = "نص السؤال غير متوفر"
        
        correct_option_id = str(current_question_data.get("correct_option_id"))
        options = current_question_data.get("options", [])
        correct_option_text = "غير محدد"
        for opt in options:
            opt_id_current = str(opt.get("option_id"))
            opt_text_current_val = opt.get("option_text", f"خيار {opt_id_current}")
            if opt.get("is_image_option"):
                 opt_text_current_val = f"صورة ({opt.get('image_option_display_label', opt_id_current)})"
            elif not isinstance(opt_text_current_val, str) or not opt_text_current_val.strip():
                 opt_text_current_val = f"خيار {opt_id_current}"
            if opt_id_current == correct_option_id:
                correct_option_text = opt_text_current_val
                break

        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": q_text_for_ans,
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text,
            "is_correct": False,
            "time_taken": -999 
        })

        feedback_text = f"⏰ انتهى الوقت للسؤال! الإجابة الصحيحة كانت: {correct_option_text}"
        header_part = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
        
        original_message = context.bot_data.get(f"msg_cache_{chat_id}_{message_id}") 
        original_content_for_feedback = ""

        if question_was_image:
            if original_message and original_message.caption:
                original_content_for_feedback = original_message.caption
            else: 
                original_content_for_feedback = header_part + q_text_for_ans 
        else:
            if original_message and original_message.text:
                original_content_for_feedback = original_message.text
            else: 
                original_content_for_feedback = header_part + q_text_for_ans

        if original_content_for_feedback.startswith(header_part):
             text_content_for_feedback = original_content_for_feedback[len(header_part):]
        else:
             text_content_for_feedback = original_content_for_feedback

        full_feedback_message = f"{header_part}{text_content_for_feedback}\n\n{feedback_text}"

        try:
            if question_was_image:
                await bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=full_feedback_message, parse_mode='HTML')
            else:
                await bot.edit_message_text(text=full_feedback_message, chat_id=chat_id, message_id=message_id, parse_mode='HTML', reply_markup=None)
        except telegram.error.BadRequest as e_bad_req:
            if "message is not modified" in str(e_bad_req).lower():
                logger.info(f"[QuizLogic {self.quiz_id}] Timeout feedback q_idx {self.current_question_index} not modified.")
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] BadRequest editing timeout feedback q_idx {self.current_question_index}: {e_bad_req}", exc_info=True)
                await safe_send_message(bot, chat_id=chat_id, text=full_feedback_message, parse_mode='HTML')
        except Exception as e_timeout_feedback:
            logger.error(f"[QuizLogic {self.quiz_id}] Error sending timeout feedback q_idx {self.current_question_index}: {e_timeout_feedback}", exc_info=True)
            await safe_send_message(bot, chat_id=chat_id, text=full_feedback_message, parse_mode='HTML')

        self.current_question_index += 1
        await asyncio.sleep(2) 
        next_state = await self.send_question(bot, context, chat_id, user_id)
        if next_state == END:
            logger.info(f"[QuizLogic {self.quiz_id}] Timeout led to quiz end for user {user_id}.")

    async def end_quiz(self, bot: Bot, context: CallbackContext, update: Update, manual_end: bool = False, reason_suffix: str = "unknown"):
        user_id_eff = self.user_id if self.user_id else (update.effective_user.id if update and update.effective_user else "UNKNOWN_USER")
        chat_id_eff = update.effective_chat.id if update and update.effective_chat else "UNKNOWN_CHAT"
        logger.info(f"[QuizLogic {self.quiz_id}] end_quiz called for user {user_id_eff}. Manual: {manual_end}. Reason: {reason_suffix}")
        self.active = False
        timer_job_name = f"qtimer_{user_id_eff}_{chat_id_eff}_{self.quiz_id}_{self.current_question_index}" 
        remove_job_if_exists(timer_job_name, context)
        
        if self.current_question_index > 0:
            timer_job_name_prev = f"qtimer_{user_id_eff}_{chat_id_eff}_{self.quiz_id}_{self.current_question_index -1}"
            remove_job_if_exists(timer_job_name_prev, context)

        if manual_end and self.last_question_message_id and chat_id_eff != "UNKNOWN_CHAT":
            try:
                await bot.edit_message_reply_markup(chat_id=chat_id_eff, message_id=self.last_question_message_id, reply_markup=None)
                logger.info(f"[QuizLogic {self.quiz_id}] Removed keyboard from msg {self.last_question_message_id} on manual end.")
            except Exception as e_rem_kb:
                logger.warning(f"[QuizLogic {self.quiz_id}] Could not remove keyboard on manual end: {e_rem_kb}", exc_info=True)
        
        await self.cleanup_quiz_data(context, user_id_eff, f"manual_end_{reason_suffix}" if manual_end else f"auto_end_{reason_suffix}")

    async def cleanup_quiz_data(self, context: CallbackContext, user_id_to_clean, reason: str):
        logger.info(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user: {user_id_to_clean}, quiz_id: {self.quiz_id}, reason: {reason}")
        self.active = False 
        self.questions_data = []
        self.answers = []
        self.score = 0
        self.current_question_index = 0
        self.last_question_message_id = None
        self.question_start_time = None
        
        if context.user_data and user_id_to_clean in context.user_data and 'active_quiz_instance' in context.user_data[user_id_to_clean]:
            if hasattr(context.user_data[user_id_to_clean]['active_quiz_instance'], 'quiz_id') and \
               context.user_data[user_id_to_clean]['active_quiz_instance'].quiz_id == self.quiz_id:
                del context.user_data[user_id_to_clean]['active_quiz_instance']
                logger.info(f"[QuizLogic {self.quiz_id}] Instance removed from context.user_data for user {user_id_to_clean}.")
            else:
                logger.warning(f"[QuizLogic {self.quiz_id}] Instance in context.user_data for {user_id_to_clean} is different or lacks quiz_id. Not removing.")
        else:
            logger.info(f"[QuizLogic {self.quiz_id}] No active_quiz_instance found in context.user_data for user {user_id_to_clean} to remove.")
        logger.info(f"[QuizLogic {self.quiz_id}] Quiz instance data has been reset internally.")

async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    quiz_id = job_data.get("quiz_id")
    user_id = job_data.get("user_id")
    chat_id = job_data.get("chat_id")
    question_index_at_timeout = job_data.get("question_index")
    message_id = job_data.get("message_id")
    question_was_image = job_data.get("question_was_image", False)

    logger.debug(f"Timeout wrapper called for quiz {quiz_id}, user {user_id}, q_idx {question_index_at_timeout}")

    quiz_instance = None
    if context.user_data and user_id in context.user_data and 'active_quiz_instance' in context.user_data[user_id]:
        instance_candidate = context.user_data[user_id]['active_quiz_instance']
        if hasattr(instance_candidate, 'quiz_id') and instance_candidate.quiz_id == quiz_id and instance_candidate.active:
            if instance_candidate.current_question_index == question_index_at_timeout: 
                quiz_instance = instance_candidate
            else:
                logger.warning(f"Timeout wrapper: Quiz {quiz_id} q_idx mismatch. Job for {question_index_at_timeout}, instance at {instance_candidate.current_question_index}. Ignoring job.")
                return
        else:
            logger.warning(f"Timeout wrapper: Quiz {quiz_id} not active or ID mismatch for user {user_id}. Ignoring job.")
            return 
    else:
        logger.warning(f"Timeout wrapper: No active quiz instance found for user {user_id}, quiz {quiz_id}. Ignoring job.")
        return

    if quiz_instance:
        await quiz_instance.handle_timeout(context.bot, context, chat_id, user_id, message_id, question_was_image)
    else:
        logger.error(f"Timeout wrapper: Could not retrieve quiz_instance for quiz {quiz_id}, user {user_id} despite checks.")

