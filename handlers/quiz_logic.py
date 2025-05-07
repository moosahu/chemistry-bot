# -*- coding: utf-8 -*-
# handlers/quiz_logic.py (v23 - Enhanced error handling, state management, and results display)

import asyncio
import logging
import time
import uuid # لإنشاء معرّف فريد للاختبار
import telegram # For telegram.error types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup # Added Update and keyboard types
from telegram.ext import ConversationHandler, CallbackContext, JobQueue # Corrected and added CallbackContext, JobQueue
from config import logger, TAKING_QUIZ, END, MAIN_MENU # Assuming logger and states are in your config.py
from utils.helpers import safe_send_message, safe_edit_message_text, remove_job_if_exists # Ensure this path is correct

class QuizLogic:
    def __init__(self, context: CallbackContext, bot_instance=None, user_id=None, quiz_type=None, questions_data=None, total_questions=0, question_time_limit=60):
        self.context = context
        self.bot = bot_instance if bot_instance else context.bot
        self.user_id = user_id
        self.quiz_id = str(uuid.uuid4()) # Unique ID for this quiz instance
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
        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized for user {self.user_id if self.user_id else 'UNKNOWN'}. Questions: {self.total_questions}")

    async def start_quiz(self, update: Update, chat_id: int, user_id: int) -> int:
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
                await safe_edit_message_text(self.bot, chat_id=chat_id, message_id=message_to_edit_id, text=text_no_questions, reply_markup=keyboard_to_main)
            else:
                await safe_send_message(self.bot, chat_id=chat_id, text=text_no_questions, reply_markup=keyboard_to_main)
            await self.cleanup_quiz_data(user_id, "no_questions_on_start")
            return END 
        
        return await self.send_question(chat_id, user_id)
    
    def create_options_keyboard(self, options_data):
        keyboard = []
        arabic_alphabet_for_buttons = [chr(code) for code in range(0x0623, 0x0623 + 28)] 

        for i, option in enumerate(options_data):
            option_id = option.get("option_id", f"gen_opt_{i}") # Ensure option_id exists
            option_text_original = option.get("option_text", "")
            button_text = ""

            if option.get("is_image_option"):
                image_display_char = option.get("image_option_display_label")
                if not image_display_char:
                    image_display_char = arabic_alphabet_for_buttons[i] if i < len(arabic_alphabet_for_buttons) else f"{i + 1}"
                button_text = f"اختر: {image_display_char}"
            elif isinstance(option_text_original, str) and not option_text_original.strip():
                button_text = f"خيار {i + 1}"
                logger.warning(f"[QuizLogic {self.quiz_id}] Option text empty for opt_id {option_id}. Default: 	'{button_text}	'")
            elif isinstance(option_text_original, str) and (option_text_original.startswith("http://") or option_text_original.startswith("https://") ):
                button_text = f"خيار {i + 1} (صورة)"
            elif isinstance(option_text_original, str):
                button_text = option_text_original
            else:
                button_text = f"خيار {i + 1} (بيانات غير نصية)"
                logger.warning(f"[QuizLogic {self.quiz_id}] Option text not string (type: {type(option_text_original)}) for opt_id {option_id}. Default: 	'{button_text}	'")
            
            button_text_str = str(button_text)
            if len(button_text_str.encode('utf-8')) > 64:
                temp_bytes = button_text_str.encode('utf-8')[:60]
                button_text = temp_bytes.decode('utf-8', 'ignore') + "..."
                logger.warning(f"[QuizLogic {self.quiz_id}] Option text truncated for opt_id {option_id}. Truncated: 	'{button_text}	'")

            if not button_text_str.strip():
                 button_text = f"خيار {i + 1}"
                 logger.error(f"[QuizLogic {self.quiz_id}] Critical: Button text empty after processing for opt_id {option_id}. Fallback: 	'{button_text}	'")

            # IMPORTANT: Ensure callback_data includes quiz_id to target the correct QuizLogic instance
            callback_data = f"ans_{self.quiz_id}_{self.current_question_index}_{option_id}"
            keyboard.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
        return InlineKeyboardMarkup(keyboard)

    async def send_question(self, chat_id: int, user_id: int):
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] send_question called but quiz is inactive. User {user_id}. Aborting.")
            return END # Or a specific state indicating quiz ended prematurely

        if self.current_question_index >= self.total_questions:
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz completed for user {user_id}. Showing results.")
            return await self.show_results(chat_id, user_id)

        current_question_data = self.questions_data[self.current_question_index]
        q_id_log = current_question_data.get('question_id', f'q_idx_{self.current_question_index}')
        options = current_question_data.get("options", [])
        processed_options = []
        arabic_alphabet = [chr(code) for code in range(0x0623, 0x0623 + 28)]
        option_image_counter = 0

        for i, option_data_original in enumerate(options):
            current_option_proc = option_data_original.copy()
            option_text_original = option_data_original.get("option_text", "")
            is_image_url = isinstance(option_text_original, str) and \
                           (option_text_original.startswith("http://")  or option_text_original.startswith("https://") ) and \
                           any(option_text_original.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif"])

            if is_image_url:
                try:
                    display_label = arabic_alphabet[option_image_counter] if option_image_counter < len(arabic_alphabet) else f"{option_image_counter + 1}"
                    logger.info(f"[QuizLogic {self.quiz_id}] Sending image for option {i} (caption: {display_label}), q_id {q_id_log}. URL: {option_text_original}")
                    await self.bot.send_photo(chat_id=chat_id, photo=option_text_original, caption=display_label)
                    current_option_proc['is_image_option'] = True
                    current_option_proc['image_option_display_label'] = display_label
                    option_image_counter += 1
                    await asyncio.sleep(0.3) # Slightly increased delay
                except Exception as e_img_opt:
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to send image for option {i} (URL: {option_text_original}), q_id {q_id_log}: {e_img_opt}", exc_info=True)
                    current_option_proc['is_image_option'] = False
            processed_options.append(current_option_proc)
        
        current_question_data['options'] = processed_options
        options_keyboard = self.create_options_keyboard(processed_options)
        header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
        image_url = current_question_data.get("image_url")
        question_text_from_data = current_question_data.get("question_text", "") # Default to empty string
        sent_message = None
        self.last_question_is_image = False

        # Ensure question_text_from_data is a string
        if not isinstance(question_text_from_data, str):
            logger.warning(f"[QuizLogic {self.quiz_id}] question_text for q_id {q_id_log} is not a string (type: {type(question_text_from_data)}). Converting to string.")
            question_text_from_data = str(question_text_from_data)

        if image_url:
            caption_text = header + question_text_from_data
            logger.info(f"[QuizLogic {self.quiz_id}] Attempting to send image question q_id {q_id_log}. URL: {image_url}")
            try:
                sent_message = await self.bot.send_photo(chat_id=chat_id, photo=image_url, caption=caption_text, reply_markup=options_keyboard, parse_mode="HTML")
                self.last_question_is_image = True
            except Exception as e:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to send photo for q_id {q_id_log}: {e}. URL: {image_url}", exc_info=True)
                if question_text_from_data or header: # Fallback if there's any text
                    logger.info(f"[QuizLogic {self.quiz_id}] Photo send failed for q_id {q_id_log}, attempting to send as text.")
                    full_question_text = header + question_text_from_data
                    try:
                        sent_message = await safe_send_message(self.bot, chat_id=chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                    except Exception as e_fallback_text:
                        logger.error(f"[QuizLogic {self.quiz_id}] Fallback to text also failed for q_id {q_id_log}: {e_fallback_text}", exc_info=True)
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Photo send failed for q_id {q_id_log} and no fallback text available.")
        else:
            if not question_text_from_data.strip():
                question_text_from_data = "نص السؤال غير متوفر حالياً."
                logger.warning(f"[QuizLogic {self.quiz_id}] Question text is empty for TEXT q_id: {q_id_log}. Using placeholder.")

            full_question_text = header + question_text_from_data
            logger.info(f"[QuizLogic {self.quiz_id}] Attempting to send text question q_id {q_id_log}: {full_question_text[:100]}...")
            try:
                sent_message = await safe_send_message(self.bot, chat_id=chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
            except Exception as e:
                 logger.error(f"[QuizLogic {self.quiz_id}] Unexpected error sending text question for q_id {q_id_log}: {e}.", exc_info=True)

        if sent_message:
            self.last_question_message_id = sent_message.message_id
            self.question_start_time = time.time()
            logger.info(f"[QuizLogic {self.quiz_id}] Question {self.current_question_index} (q_id {q_id_log}) sent (msg_id: {self.last_question_message_id}, is_image: {self.last_question_is_image}).")
            
            timer_job_name = f"qtimer_{user_id}_{chat_id}_{self.quiz_id}_{self.current_question_index}"
            remove_job_if_exists(timer_job_name, self.context)

            if self.context.job_queue:
                 self.context.job_queue.run_once(
                    self.question_timeout_callback,
                    self.question_time_limit,
                    chat_id=chat_id,
                    user_id=user_id,
                    name=timer_job_name,
                    data={"quiz_id": self.quiz_id, "question_index": self.current_question_index, "user_id": user_id, "chat_id": chat_id, "message_id": sent_message.message_id, "question_was_image": self.last_question_is_image}
                )
                 logger.info(f"[QuizLogic {self.quiz_id}] Timer job 	'{timer_job_name}	' scheduled for {self.question_time_limit}s.")
            else:
                logger.error(f"[QuizLogic {self.quiz_id}] JobQueue not available. Cannot schedule timer for user {user_id}.")
            return TAKING_QUIZ
        else:
            logger.error(f"[QuizLogic {self.quiz_id}] Failed to send question (q_id: {q_id_log}). Ending quiz.")
            await safe_send_message(self.bot, chat_id=chat_id, text="حدث خطأ أثناء إرسال السؤال. تم إنهاء الاختبار.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]])) 
            await self.cleanup_quiz_data(user_id, "send_question_failure")
            return END

    async def handle_answer(self, update: Update, context: CallbackContext):
        query = update.callback_query
        user_id = query.from_user.id

        if not self.active or str(user_id) != str(self.user_id):
            logger.warning(f"[QuizLogic {self.quiz_id}] Answer from user {user_id} for inactive/mismatched quiz (owner: {self.user_id}). Ignoring.")
            await query.answer(text="هذا الاختبار ليس لك أو لم يعد نشطاً.", show_alert=True)
            return TAKING_QUIZ # Or END if quiz is truly over for this user

        time_taken = time.time() - self.question_start_time if self.question_start_time else -1
        
        try:
            # ans_QUIZID_QIDX_OPTID
            parts = query.data.split("_", 3) 
            if len(parts) < 4 or parts[0] != 'ans':
                raise ValueError("Callback data does not match expected ans_QUIZID_QIDX_OPTID format")
            
            cb_quiz_id, cb_q_idx_str, cb_chosen_option_id_str = parts[1], parts[2], parts[3]
            q_idx_answered = int(cb_q_idx_str)

        except ValueError as e:
            logger.error(f"[QuizLogic {self.quiz_id}] Invalid callback data: {query.data}. Error: {e}")
            await query.answer("خطأ في بيانات الإجابة.")
            # Potentially edit message to remove buttons if they are now invalid
            try:
                await self.bot.edit_message_reply_markup(chat_id=query.message.chat_id, message_id=query.message.message_id, reply_markup=None)
            except Exception as e_rem_markup:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to remove markup on invalid callback: {e_rem_markup}")
            return TAKING_QUIZ # Stay in quiz, user might try again if it was a glitch, or timeout will handle

        if cb_quiz_id != self.quiz_id:
            logger.warning(f"[QuizLogic {self.quiz_id}] Answer for different quiz instance ({cb_quiz_id}). Ignoring.")
            await query.answer(text="هذه الإجابة لاختبار مختلف.")
            return TAKING_QUIZ

        if q_idx_answered != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Answer for q_idx {q_idx_answered}, current is {self.current_question_index}. Ignoring old/duplicate callback.")
            await query.answer(text="لقد أجبت على هذا السؤال بالفعل أو انتهى وقته.")
            # Do not remove markup here, as the current question might still be active or a new one shown
            return TAKING_QUIZ
        
        timer_job_name = f"qtimer_{user_id}_{query.message.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        logger.info(f"[QuizLogic {self.quiz_id}] Removed timer job 	'{timer_job_name}	' (answered). Q_idx: {self.current_question_index}")

        current_question_data = self.questions_data[self.current_question_index]
        q_text_for_ans = current_question_data.get("question_text", "نص السؤال غير متوفر")
        if not isinstance(q_text_for_ans, str) or not q_text_for_ans.strip(): q_text_for_ans = "نص السؤال غير متوفر"

        options = current_question_data.get("options", [])
        correct_option_id = str(current_question_data.get("correct_option_id")) # Ensure string comparison
        is_correct = False
        chosen_option_text = "غير محدد"
        correct_option_text = "غير محدد"

        for opt in options:
            opt_id_current = str(opt.get("option_id"))
            opt_text_current = opt.get("option_text", f"خيار {opt_id_current}")
            if opt.get("is_image_option"): opt_text_current = f"صورة ({opt.get('image_option_display_label', opt_id_current)})"
            if not isinstance(opt_text_current, str) or not opt_text_current.strip(): opt_text_current = f"خيار {opt_id_current}"

            if opt_id_current == cb_chosen_option_id_str:
                chosen_option_text = opt_text_current
                if opt_id_current == correct_option_id:
                    is_correct = True
            
            if opt_id_current == correct_option_id:
                correct_option_text = opt_text_current

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

        original_content_for_feedback = ""
        header_part = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
        
        if self.last_question_is_image and query.message.caption:
            original_content_for_feedback = query.message.caption
        elif not self.last_question_is_image and query.message.text:
            original_content_for_feedback = query.message.text
        else: # Fallback if message content is unexpectedly missing
            original_content_for_feedback = header_part + q_text_for_ans

        # Strip header if present to avoid duplication
        if original_content_for_feedback.startswith(header_part):
             text_content_for_feedback = original_content_for_feedback[len(header_part):]
        else:
             text_content_for_feedback = original_content_for_feedback # Or just use the question text from data

        full_feedback_message = f"{header_part}{text_content_for_feedback}\n\nاخترت: {chosen_option_text}\n{feedback_text}"

        try:
            if self.last_question_is_image and query.message.caption is not None:
                await self.bot.edit_message_caption(chat_id=query.message.chat_id, message_id=self.last_question_message_id, caption=full_feedback_message, reply_markup=None, parse_mode='HTML')
            elif not self.last_question_is_image and query.message.text is not None:
                await self.bot.edit_message_text(text=full_feedback_message, chat_id=query.message.chat_id, message_id=self.last_question_message_id, reply_markup=None, parse_mode='HTML')
            else:
                 logger.warning(f"[QuizLogic {self.quiz_id}] Could not edit message for feedback (q_idx {self.current_question_index}). Sending as new.")
                 await safe_send_message(self.bot, chat_id=query.message.chat_id, text=feedback_text) # Send simplified feedback

        except telegram.error.BadRequest as e:
            if "MESSAGE_NOT_MODIFIED" not in str(e).upper():
                logger.error(f"[QuizLogic {self.quiz_id}] Error editing message for feedback (q_idx {self.current_question_index}): {e}. Feedback: {feedback_text}", exc_info=True)
                await safe_send_message(self.bot, chat_id=query.message.chat_id, text=feedback_text)
        except Exception as e_edit:
            logger.error(f"[QuizLogic {self.quiz_id}] General error editing message for feedback (q_idx {self.current_question_index}): {e_edit}. Feedback: {feedback_text}", exc_info=True)
            await safe_send_message(self.bot, chat_id=query.message.chat_id, text=feedback_text)

        self.current_question_index += 1
        await asyncio.sleep(1.5) # Increased delay before next question
        return await self.send_question(query.message.chat_id, user_id)

    async def question_timeout_callback(self, context: CallbackContext):
        job_data = context.job.data
        user_id = job_data["user_id"]
        chat_id = job_data["chat_id"]
        quiz_id_from_job = job_data["quiz_id"]
        question_index_from_job = job_data["question_index"]
        message_id_from_job = job_data["message_id"]
        question_was_image = job_data.get("question_was_image", False)

        logger.info(f"[QuizLogic {quiz_id_from_job}] Timeout for q_idx {question_index_from_job}, user {user_id}.")

        if not self.active or quiz_id_from_job != self.quiz_id or question_index_from_job != self.current_question_index or str(user_id) != str(self.user_id):
            logger.warning(f"[QuizLogic {self.quiz_id}] Stale/mismatched timeout job. Job: qz {quiz_id_from_job}, qidx {question_index_from_job}, usr {user_id}. Current: qz {self.quiz_id}, qidx {self.current_question_index}, usr {self.user_id}. Active: {self.active}. Ignoring.")
            return

        current_question_data = self.questions_data[self.current_question_index]
        q_text_for_ans = current_question_data.get("question_text", "نص السؤال غير متوفر")
        if not isinstance(q_text_for_ans, str) or not q_text_for_ans.strip(): q_text_for_ans = "نص السؤال غير متوفر"
        
        correct_option_id = str(current_question_data.get("correct_option_id"))
        correct_option_text = "غير محدد"
        options = current_question_data.get("options", [])
        for opt in options:
            opt_id_curr = str(opt.get("option_id"))
            if opt_id_curr == correct_option_id:
                correct_option_text = opt.get("option_text", f"خيار {correct_option_id}")
                if opt.get("is_image_option"): correct_option_text = f"صورة ({opt.get('image_option_display_label', correct_option_id)})"
                if not isinstance(correct_option_text, str) or not correct_option_text.strip(): correct_option_text = f"خيار {correct_option_id}"
                break
        
        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": q_text_for_ans,
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text,
            "is_correct": False,
            "time_taken": self.question_time_limit
        })

        feedback_text = f"⏰ انتهى الوقت للسؤال! الإجابة الصحيحة كانت: {correct_option_text}"
        
        try:
            # Try to get the original message to edit its content + remove keyboard
            original_message = None
            if question_was_image:
                # For photos, we need to edit caption and remove reply_markup separately if not possible in one go
                # First, try to edit caption with feedback, then remove markup if that fails or is separate step
                await self.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id_from_job, reply_markup=None)
                original_message_edited_markup = await self.bot.edit_message_caption(chat_id=chat_id, message_id=message_id_from_job, caption=" ", parse_mode='HTML') # Temp caption to get message object
                original_content = original_message_edited_markup.caption if original_message_edited_markup else ""
            else:
                original_message = await self.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id_from_job, reply_markup=None)
                original_content = original_message.text if original_message else ""

            header_part = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
            if original_content and original_content.startswith(header_part):
                text_content_for_feedback = original_content[len(header_part):]
            else: # Fallback to question text from data if original message content is not as expected
                text_content_for_feedback = q_text_for_ans
            
            full_feedback_message = f"{header_part}{text_content_for_feedback}\n\n{feedback_text}"

            if question_was_image:
                await self.bot.edit_message_caption(chat_id=chat_id, message_id=message_id_from_job, caption=full_feedback_message, parse_mode='HTML')
            else:
                await self.bot.edit_message_text(text=full_feedback_message, chat_id=chat_id, message_id=message_id_from_job, parse_mode='HTML')

        except telegram.error.BadRequest as e:
            if "MESSAGE_NOT_MODIFIED" not in str(e).upper():
                logger.error(f"[QuizLogic {self.quiz_id}] Timeout: Error editing message for feedback (q_idx {self.current_question_index}): {e}. Feedback: {feedback_text}", exc_info=True)
                await safe_send_message(self.bot, chat_id=chat_id, text=feedback_text) # Send simplified feedback
        except Exception as e_timeout_edit:
            logger.error(f"[QuizLogic {self.quiz_id}] Timeout: General error editing message for feedback (q_idx {self.current_question_index}): {e_timeout_edit}. Feedback: {feedback_text}", exc_info=True)
            await safe_send_message(self.bot, chat_id=chat_id, text=feedback_text)

        self.current_question_index += 1
        await asyncio.sleep(1.5) # Increased delay
        
        # This callback is part of the QuizLogic instance, so it should directly call send_question
        # The state (TAKING_QUIZ or END) will be returned by send_question and handled by the ConversationHandler
        # No need to return a state from the timeout callback itself if it's not a direct state handler for ConversationHandler
        await self.send_question(chat_id, user_id) 
        # The ConversationHandler should remain in TAKING_QUIZ or transition to END based on send_question's result.

    async def show_results(self, chat_id: int, user_id: int):
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] show_results called but quiz is inactive. User {user_id}. Aborting.")
            return END
            
        logger.info(f"[QuizLogic {self.quiz_id}] Showing results. Score: {self.score}/{self.total_questions}")
        results_text = f"🏁 انتهى الاختبار! 🏁\n\nنتيجتك: {self.score} من {self.total_questions} إجابات صحيحة.\n"
        if self.total_questions > 0:
            percentage = (self.score / self.total_questions) * 100
            results_text += f"نسبة النجاح: {percentage:.2f}%\n"
        results_text += "\n<b>تفاصيل إجاباتك:</b>\n"
        for i, ans in enumerate(self.answers):
            q_text = ans.get("question_text", "نص السؤال غير متوفر")
            if not isinstance(q_text, str) or not q_text.strip(): q_text = "نص السؤال غير متوفر"
            
            chosen = ans.get("chosen_option_text", "لم يتم الاختيار")
            if not isinstance(chosen, str) or not chosen.strip(): chosen = "لم يتم الاختيار"

            correct = ans.get("correct_option_text", "غير محددة")
            if not isinstance(correct, str) or not correct.strip(): correct = "غير محددة"

            status = "✅" if ans.get("is_correct") else ("❌" if ans.get("chosen_option_id") is not None else "⏰")
            results_text += f"\n{i+1}. {q_text}\n   {status} اخترت: {chosen}\n" 
            if not ans.get("is_correct") and ans.get("chosen_option_id") is not None:
                results_text += f"   الصحيحة: {correct}\n"
            elif ans.get("chosen_option_id") is None: # Timeout
                 results_text += f"   الصحيحة كانت: {correct}\n"

        keyboard = [
            [InlineKeyboardButton("🧠 ابدأ اختبار جديد", callback_data="start_quiz")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message_to_send_results_to = self.last_question_message_id
        edited_successfully = False

        # Try to edit the last question message with results
        # If the last question message was an image, we can't edit its text content to be this long result text.
        # So, we must send a new message for results if the last question was an image OR if editing fails.
        if message_to_send_results_to and not self.last_question_is_image: # Only attempt edit if last was text
            try:
                await self.bot.edit_message_text(
                    text=results_text, chat_id=chat_id, message_id=message_to_send_results_to,
                    reply_markup=reply_markup, parse_mode='HTML'
                )
                edited_successfully = True
                logger.info(f"[QuizLogic {self.quiz_id}] Results edited into message_id {message_to_send_results_to}.")
            except Exception as e_edit_results:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit results into msg_id {message_to_send_results_to}: {e_edit_results}. Sending new.")
        
        if not edited_successfully:
            # If last was image, or editing failed, send as new message
            # Also, if there was no last_question_message_id (e.g. quiz ended before first question)
            await safe_send_message(self.bot, chat_id=chat_id, text=results_text, reply_markup=reply_markup, parse_mode='HTML')
            logger.info(f"[QuizLogic {self.quiz_id}] Results sent as a new message.")

        await self.cleanup_quiz_data(user_id, "quiz_completed_shown_results")
        return END # Important: Signal conversation end to ConversationHandler

    async def end_quiz(self, update: Update, context: CallbackContext, manual_end: bool = False, reason_suffix: str = ""):
        user_id_effective = update.effective_user.id if update.effective_user else self.user_id
        chat_id_effective = update.effective_chat.id if update.effective_chat else None
        
        reason = f"manual_end_{reason_suffix}" if manual_end else f"auto_end_{reason_suffix}"
        logger.info(f"[QuizLogic {self.quiz_id}] end_quiz called for user {user_id_effective}. Reason: {reason}. Active: {self.active}")

        if not self.active: # If already cleaned up or ended, do nothing further
            logger.info(f"[QuizLogic {self.quiz_id}] end_quiz called but quiz already inactive. No further action.")
            return END

        timer_job_name = f"qtimer_{user_id_effective}_{chat_id_effective if chat_id_effective else 'unknown_chat'}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        logger.info(f"[QuizLogic {self.quiz_id}] Removed timer job 	'{timer_job_name}	' during end_quiz.")

        if manual_end and chat_id_effective:
            # Try to remove buttons from the last question message if it exists
            if self.last_question_message_id:
                try:
                    await self.bot.edit_message_reply_markup(chat_id=chat_id_effective, message_id=self.last_question_message_id, reply_markup=None)
                    logger.info(f"[QuizLogic {self.quiz_id}] Removed markup from msg_id {self.last_question_message_id} on manual end.")
                except Exception as e_rem_markup:
                    logger.warning(f"[QuizLogic {self.quiz_id}] Failed to remove markup from msg {self.last_question_message_id} on manual end: {e_rem_markup}")
            
            # Send a confirmation of manual end
            end_text = "تم إنهاء الاختبار يدوياً."
            if self.answers: # If some answers were given, show partial results
                end_text = f"تم إنهاء الاختبار يدوياً. 🏁\n\nنتيجتك حتى الآن: {self.score} من {self.current_question_index} أسئلة تمت معالجتها.\n"
            
            keyboard = [[InlineKeyboardButton("🧠 ابدأ اختبار جديد", callback_data="start_quiz"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]]
            await safe_send_message(self.bot, chat_id=chat_id_effective, text=end_text, reply_markup=InlineKeyboardMarkup(keyboard))
        
        await self.cleanup_quiz_data(user_id_effective, reason)
        return END # Signal conversation end

    async def cleanup_quiz_data(self, user_id_for_log, reason: str):
        if not self.active: # Avoid double cleanup or cleaning an already inactive instance
            logger.info(f"[QuizLogic {self.quiz_id}] cleanup_quiz_data called for user {user_id_for_log}, but quiz already inactive. Reason: {reason}. No action.")
            return

        logger.info(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user: {user_id_for_log}, Reason: {reason}")
        self.active = False # Mark as inactive *before* clearing context data
        self.questions_data = []
        self.answers = []
        # self.score = 0 # Score might be needed for a final display even if quiz is cleaned up
        # self.current_question_index = 0
        self.last_question_message_id = None
        self.question_start_time = None
        
        # Critical: Remove this specific quiz instance from context.user_data
        # This requires knowing how it's stored by the calling ConversationHandler (e.g., in quiz.py)
        # Assuming it's stored under a key like 'current_quiz_logic' or 'quiz_instance_id' mapped to self.quiz_id
        if 'quiz_sessions' in self.context.user_data and self.quiz_id in self.context.user_data['quiz_sessions']:
            del self.context.user_data['quiz_sessions'][self.quiz_id]
            logger.info(f"[QuizLogic {self.quiz_id}] Removed self from context.user_data['quiz_sessions'].")
        elif 'current_quiz_logic' in self.context.user_data and self.context.user_data['current_quiz_logic'] is self:
            del self.context.user_data['current_quiz_logic']
            logger.info(f"[QuizLogic {self.quiz_id}] Removed self from context.user_data['current_quiz_logic'].")
        elif 'quiz_instance_id' in self.context.user_data and self.context.user_data['quiz_instance_id'] == self.quiz_id:
            del self.context.user_data['quiz_instance_id'] # And potentially the object itself if stored separately
            if 'current_quiz_logic_object' in self.context.user_data: # Example of separate storage
                del self.context.user_data['current_quiz_logic_object']
            logger.info(f"[QuizLogic {self.quiz_id}] Removed self (via quiz_instance_id) from context.user_data.")
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] Could not find a clear reference to self in context.user_data for cleanup. Manual cleanup in ConversationHandler might be needed.")

        logger.info(f"[QuizLogic {self.quiz_id}] Quiz instance data has been reset and marked inactive.")

# It is assumed that the ConversationHandler in quiz.py (or equivalent)
# will correctly instantiate QuizLogic, store it in context.user_data (e.g., context.user_data['current_quiz_logic'] = quiz_logic_instance),
# and use its methods as state handlers. The ConversationHandler is also responsible for retrieving this instance
# based on user_id or a quiz_id passed in callback_data for subsequent interactions.
# Example callback_data for answers: f"ans_{quiz_id}_{question_index}_{option_id}"
# The main quiz handler (e.g., in quiz.py) would parse quiz_id from this, retrieve the QuizLogic instance,
# and then call instance.handle_answer().

