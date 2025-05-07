# -*- coding: utf-8 -*-
# handlers/quiz_logic.py (v26 - Lettering Final Fix)

import asyncio
import logging
import time
import uuid # لإنشاء معرّف فريد للاختبار
import telegram # For telegram.error types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot # Added Bot
from telegram.ext import ConversationHandler, CallbackContext, JobQueue 
from config import logger, TAKING_QUIZ, END, MAIN_MENU # Assuming logger and states are in your config.py
from utils.helpers import safe_send_message, safe_edit_message_text, remove_job_if_exists # Ensure this path is correct

class QuizLogic:
    # Corrected list for Arabic choice lettering
    ARABIC_CHOICE_LETTERS = ["أ", "ب", "ت", "ث", "ج", "ح", "خ", "د", "ذ", "ر", "ز", "س", "ش", "ص", "ض", "ط", "ظ", "ع", "غ", "ف", "ق", "ك", "ل", "م", "ن", "ه", "و", "ي"]

    def __init__(self, user_id=None, quiz_type=None, questions_data=None, total_questions=0, question_time_limit=60, quiz_id=None):
        self.user_id = user_id
        self.quiz_id = quiz_id if quiz_id else str(uuid.uuid4()) # Unique ID for this quiz instance
        self.quiz_type = quiz_type
        self.questions_data = questions_data if questions_data is not None else []
        self.total_questions = total_questions if self.questions_data else 0 # Ensure total_questions reflects actual data
        self.current_question_index = 0
        self.score = 0
        self.answers = [] # Stores dicts with answer details
        self.question_start_time = None
        self.last_question_message_id = None
        self.question_time_limit = question_time_limit
        self.last_question_is_image = False
        self.active = True # Flag to indicate if this quiz instance is currently active
        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized (data-only) for user {self.user_id if self.user_id else 'UNKNOWN'}. Questions: {self.total_questions}")

    async def start_quiz(self, bot: Bot, context: CallbackContext, update: Update, chat_id: int, user_id: int) -> int:
        logger.info(f"[QuizLogic {self.quiz_id}] start_quiz called for user {user_id}, chat {chat_id}")
        self.active = True # Mark as active
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
                    logger.warning(f"[QuizLogic {self.quiz_id}] Image option missing display label in create_options_keyboard. Option: {option_id}. Assigning fallback button text.")
                    button_text = f"خيار صورة {i + 1}" 
                else:
                    button_text = f"اختر: {image_display_char}"
            elif isinstance(option_text_original, str) and not option_text_original.strip():
                button_text = f"خيار {i + 1}" 
            elif isinstance(option_text_original, str) and (option_text_original.startswith("http://") or option_text_original.startswith("https://") ):
                logger.warning(f"[QuizLogic {self.quiz_id}] Option text looks like a URL but not marked as image option: {option_text_original[:50]}")
                button_text = f"خيار {i + 1} (رابط)"
            elif isinstance(option_text_original, str):
                button_text = option_text_original
            else: 
                button_text = f"خيار {i + 1} (بيانات غير نصية)"
            
            button_text_str = str(button_text).strip()
            if not button_text_str: 
                 button_text_str = f"خيار {i + 1}"
            
            if len(button_text_str.encode('utf-8')) > 64:
                temp_bytes = button_text_str.encode('utf-8')[:60]
                button_text_str = temp_bytes.decode('utf-8', 'ignore') + "..."

            callback_data = f"ans_{self.quiz_id}_{self.current_question_index}_{option_id}"
            keyboard.append([InlineKeyboardButton(text=button_text_str, callback_data=callback_data)])
        return InlineKeyboardMarkup(keyboard)

    async def send_question(self, bot: Bot, context: CallbackContext, chat_id: int, user_id: int):
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] send_question called but quiz is inactive. User {user_id}. Aborting.")
            return END 

        if self.current_question_index >= self.total_questions:
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz completed for user {user_id}. Showing results.")
            return await self.show_results(bot, context, chat_id, user_id)

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        options = current_question_data.get("options", [])
        processed_options = []
        option_image_counter = 0 # Reset for each question, used for lettering image options

        for i, option_data_original in enumerate(options):
            current_option_proc = option_data_original.copy()
            option_text_original = option_data_original.get("option_text", "")
            is_image_url = isinstance(option_text_original, str) and \
                           (option_text_original.startswith("http://")  or option_text_original.startswith("https://") ) and \
                           any(option_text_original.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif"])

            if is_image_url:
                try:
                    # Use the corrected ARABIC_CHOICE_LETTERS list for display_label
                    display_label = self.ARABIC_CHOICE_LETTERS[option_image_counter] if option_image_counter < len(self.ARABIC_CHOICE_LETTERS) else f"صورة {option_image_counter + 1}"
                    logger.info(f"[QuizLogic {self.quiz_id}] Sending image for option {i} (caption: {display_label}), q_id {q_id_log}. URL: {option_text_original}")
                    await bot.send_photo(chat_id=chat_id, photo=option_text_original, caption=display_label)
                    current_option_proc['is_image_option'] = True
                    current_option_proc['image_option_display_label'] = display_label 
                    option_image_counter += 1 
                    await asyncio.sleep(0.3) 
                except Exception as e_img_opt:
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to send image for option {i} (URL: {option_text_original}), q_id {q_id_log}: {e_img_opt}", exc_info=True)
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
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to send photo for q_id {q_id_log}: {e}. URL: {image_url}", exc_info=True)
                if question_text_from_data or header: 
                    full_question_text = header + question_text_from_data
                    try:
                        sent_message = await safe_send_message(bot, chat_id=chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                    except Exception as e_fallback_text:
                        logger.error(f"[QuizLogic {self.quiz_id}] Fallback to text also failed for q_id {q_id_log}: {e_fallback_text}", exc_info=True)
        else:
            if not question_text_from_data.strip():
                question_text_from_data = "نص السؤال غير متوفر حالياً."
            full_question_text = header + question_text_from_data
            try:
                sent_message = await safe_send_message(bot, chat_id=chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
            except Exception as e:
                 logger.error(f"[QuizLogic {self.quiz_id}] Unexpected error sending text question for q_id {q_id_log}: {e}.", exc_info=True)

        if sent_message:
            self.last_question_message_id = sent_message.message_id
            self.question_start_time = time.time()
            timer_job_name = f"qtimer_{user_id}_{chat_id}_{self.quiz_id}_{self.current_question_index}"
            remove_job_if_exists(timer_job_name, context) 

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
                logger.error(f"[QuizLogic {self.quiz_id}] JobQueue not available. Cannot schedule timer for user {user_id}.")
            return TAKING_QUIZ
        else:
            logger.error(f"[QuizLogic {self.quiz_id}] Failed to send question (q_id: {q_id_log}). Ending quiz.")
            await safe_send_message(bot, chat_id=chat_id, text="حدث خطأ أثناء إرسال السؤال. تم إنهاء الاختبار.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]])) 
            await self.cleanup_quiz_data(context, user_id, "send_question_failure")
            return END

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
                raise ValueError("Callback data does not match expected ans_QUIZID_QIDX_OPTID format")
            cb_quiz_id, cb_q_idx_str, cb_chosen_option_id_str = parts[1], parts[2], parts[3]
            q_idx_answered = int(cb_q_idx_str)
        except ValueError as e:
            logger.error(f"[QuizLogic {self.quiz_id}] Invalid callback data: {query.data}. Error: {e}")
            await query.answer("خطأ في بيانات الإجابة.")
            try:
                await bot.edit_message_reply_markup(chat_id=query.message.chat_id, message_id=query.message.message_id, reply_markup=None)
            except Exception as e_rem_markup:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to remove markup on invalid callback: {e_rem_markup}")
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
                logger.warning(f"[QuizLogic {self.quiz_id}] Could not edit feedback for question {self.current_question_index} as original message type was unexpected or content missing.")
                await safe_send_message(bot, chat_id=query.message.chat_id, text=full_feedback_message, parse_mode='HTML') # Send as new if edit fails
        except telegram.error.BadRequest as e_bad_req:
            if "message is not modified" in str(e_bad_req).lower():
                logger.info(f"[QuizLogic {self.quiz_id}] Feedback message for question {self.current_question_index} was not modified.")
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] BadRequest error editing feedback for question {self.current_question_index}: {e_bad_req}")
                await safe_send_message(bot, chat_id=query.message.chat_id, text=full_feedback_message, parse_mode='HTML')
        except Exception as e_feedback:
            logger.error(f"[QuizLogic {self.quiz_id}] Error sending feedback for question {self.current_question_index}: {e_feedback}")
            await safe_send_message(bot, chat_id=query.message.chat_id, text=full_feedback_message, parse_mode='HTML')

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await asyncio.sleep(2) # Delay before next question
            return await self.send_question(bot, context, query.message.chat_id, user_id)
        else:
            await asyncio.sleep(2) 
            return await self.show_results(bot, context, query.message.chat_id, user_id)

    async def show_results(self, bot: Bot, context: CallbackContext, chat_id: int, user_id: int):
        logger.info(f"[QuizLogic {self.quiz_id}] Showing results for user {user_id}.")
        if not self.answers and self.total_questions > 0:
            results_text = f"🏁 انتهى الاختبار!\n\nلم يتم الإجابة على أي أسئلة.\nالنتيجة: {self.score} من {self.total_questions}"
        elif not self.answers and self.total_questions == 0:
            results_text = "🏁 انتهى الاختبار!\n\nلم تكن هناك أسئلة في هذا الاختبار."
        else:
            results_text = f"🏁 انتهى الاختبار!\n\nنتيجتك: {self.score} من {self.total_questions}\n\nتفاصيل إجاباتك:"
            for i, ans in enumerate(self.answers):
                q_text_short = ans.get("question_text", "سؤال غير متوفر")
                if len(q_text_short) > 50: q_text_short = q_text_short[:47] + "..."
                chosen_opt_text = ans.get("chosen_option_text", "لم تختر")
                correct_opt_text = ans.get("correct_option_text", "غير محددة")
                status_emoji = "✅" if ans.get("is_correct") else "❌"
                if ans.get("time_taken", -1) == -999: # Timeout
                    results_text += f"\n\n{i+1}. {q_text_short}\n{status_emoji} ⏰ انتهى الوقت! الإجابة الصحيحة كانت: {correct_opt_text}"
                else:
                    results_text += f"\n\n{i+1}. {q_text_short}\n{status_emoji} اخترت: {chosen_opt_text}"
                    if not ans.get("is_correct"):
                        results_text += f" (الصحيحة: {correct_opt_text})"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("ابدأ اختبار جديد", callback_data="start_quiz")],
            [InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]
        ])
        await safe_send_message(bot, chat_id=chat_id, text=results_text, reply_markup=keyboard)
        await self.cleanup_quiz_data(context, user_id, "quiz_completed_normally")
        return END 

    async def handle_timeout(self, bot: Bot, context: CallbackContext, chat_id: int, user_id: int, message_id: int, question_was_image: bool):
        logger.info(f"[QuizLogic {self.quiz_id}] Timeout for question {self.current_question_index} for user {user_id}.")
        if not self.active or str(user_id) != str(self.user_id):
            logger.warning(f"[QuizLogic {self.quiz_id}] Timeout received for inactive/mismatched user. User in job: {user_id}, quiz user: {self.user_id}")
            return TAKING_QUIZ

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
            "time_taken": -999 # Special value for timeout
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
                logger.info(f"[QuizLogic {self.quiz_id}] Timeout feedback message for question {self.current_question_index} was not modified.")
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] BadRequest error editing timeout feedback for question {self.current_question_index}: {e_bad_req}")
                await safe_send_message(bot, chat_id=chat_id, text=full_feedback_message, parse_mode='HTML')
        except Exception as e_timeout_feedback:
            logger.error(f"[QuizLogic {self.quiz_id}] Error sending timeout feedback for question {self.current_question_index}: {e_timeout_feedback}")
            await safe_send_message(bot, chat_id=chat_id, text=full_feedback_message, parse_mode='HTML')

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await asyncio.sleep(2) 
            return await self.send_question(bot, context, chat_id, user_id)
        else:
            await asyncio.sleep(2)
            return await self.show_results(bot, context, chat_id, user_id)

    async def end_quiz(self, bot: Bot, context: CallbackContext, update: Update, manual_end: bool = False, reason_suffix: str = "unknown"):
        user_id = self.user_id if self.user_id else (update.effective_user.id if update and update.effective_user else "UNKNOWN_USER")
        chat_id = update.effective_chat.id if update and update.effective_chat else "UNKNOWN_CHAT"
        logger.info(f"[QuizLogic {self.quiz_id}] end_quiz called for user {user_id}. Manual: {manual_end}. Reason suffix: {reason_suffix}")
        self.active = False
        timer_job_name = f"qtimer_{user_id}_{chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        
        if manual_end and self.last_question_message_id:
            try:
                await bot.edit_message_reply_markup(chat_id=chat_id, message_id=self.last_question_message_id, reply_markup=None)
                logger.info(f"[QuizLogic {self.quiz_id}] Removed keyboard from last question message {self.last_question_message_id} due to manual quiz end.")
            except Exception as e_rem_kb:
                logger.warning(f"[QuizLogic {self.quiz_id}] Could not remove keyboard on manual end: {e_rem_kb}")
        
        await self.cleanup_quiz_data(context, user_id, f"manual_end_{reason_suffix}" if manual_end else f"auto_end_{reason_suffix}")

    async def cleanup_quiz_data(self, context: CallbackContext, user_id_to_clean, reason: str):
        logger.debug(f"[QuizLogic {self.quiz_id}] cleanup_quiz_data called for user {user_id_to_clean}. Reason: {reason}")
        self.active = False 
        if "quiz_sessions" in context.user_data and self.quiz_id in context.user_data["quiz_sessions"]:
            del context.user_data["quiz_sessions"][self.quiz_id]
            logger.info(f"[QuizLogic {self.quiz_id}] Removed quiz instance from quiz_sessions for user {user_id_to_clean}.")
            if not context.user_data["quiz_sessions"]: 
                del context.user_data["quiz_sessions"]
                logger.info(f"[QuizLogic {self.quiz_id}] quiz_sessions dict is now empty, removed from user_data for {user_id_to_clean}.")
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] cleanup_quiz_data: Quiz instance {self.quiz_id} not found in quiz_sessions for user {user_id_to_clean}.")

async def question_timeout_callback_wrapper(context: CallbackContext):
    job = context.job
    quiz_id = job.data.get("quiz_id")
    question_index_from_job = job.data.get("question_index")
    user_id_from_job = job.data.get("user_id")
    chat_id_from_job = job.data.get("chat_id")
    message_id_from_job = job.data.get("message_id")
    question_was_image = job.data.get("question_was_image", False)

    logger.info(f"Timeout wrapper called for quiz {quiz_id}, q_idx {question_index_from_job}, user {user_id_from_job}")

    quiz_logic_instance = None
    if "quiz_sessions" in context.user_data and quiz_id in context.user_data["quiz_sessions"]:
        quiz_logic_instance = context.user_data["quiz_sessions"][quiz_id]
    
    if not quiz_logic_instance or not isinstance(quiz_logic_instance, QuizLogic):
        logger.error(f"Timeout wrapper: QuizLogic instance {quiz_id} not found or invalid for user {user_id_from_job}.")
        return

    if not quiz_logic_instance.active:
        logger.info(f"Timeout wrapper: Quiz {quiz_id} is no longer active for user {user_id_from_job}. Job was for q_idx {question_index_from_job}, current is {quiz_logic_instance.current_question_index}. Ignoring timeout.")
        return

    if quiz_logic_instance.current_question_index != question_index_from_job:
        logger.info(f"Timeout wrapper: Stale timeout for quiz {quiz_id}, user {user_id_from_job}. Job was for q_idx {question_index_from_job}, current is {quiz_logic_instance.current_question_index}. Ignoring.")
        return
    
    try:
        original_message = await context.bot.forward_message(chat_id=context.bot.id, from_chat_id=chat_id_from_job, message_id=message_id_from_job) 
        context.bot_data[f"msg_cache_{chat_id_from_job}_{message_id_from_job}"] = original_message
        await context.bot.delete_message(chat_id=context.bot.id, message_id=original_message.message_id) 
    except Exception as e_cache_msg:
        logger.warning(f"Timeout wrapper: Could not cache original message for quiz {quiz_id}, user {user_id_from_job}: {e_cache_msg}")

    await quiz_logic_instance.handle_timeout(context.bot, context, chat_id_from_job, user_id_from_job, message_id_from_job, question_was_image)


