# -*- coding: utf-8 -*-
# handlers/quiz_logic.py

import asyncio
import logging
import time
import uuid # لإنشاء معرّف فريد للاختبار
import telegram # For telegram.error types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup # Added Update and keyboard types
from telegram.ext import ConversationHandler, CallbackContext, JobQueue # Corrected and added CallbackContext, JobQueue
from config import logger, TAKING_QUIZ, END # Assuming logger and TAKING_QUIZ are in your config.py
from utils.helpers import safe_send_message, safe_edit_message_text, remove_job_if_exists # Ensure this path is correct

class QuizLogic:
    def __init__(self, context: CallbackContext, bot_instance=None, user_id=None, quiz_type=None, questions_data=None, total_questions=0, question_time_limit=60):
        self.context = context
        self.bot = bot_instance if bot_instance else context.bot
        self.user_id = user_id
        self.quiz_id = str(uuid.uuid4())
        self.quiz_type = quiz_type
        self.questions_data = questions_data if questions_data is not None else []
        self.total_questions = total_questions
        self.current_question_index = 0
        self.score = 0
        self.answers = [] # Stores dicts with answer details
        self.question_start_time = None
        self.last_question_message_id = None
        self.question_time_limit = question_time_limit
        self.last_question_is_image = False # Added to track if the last question was an image
        logger.debug(f"[QuizLogic] Initialized for quiz {self.quiz_id}, user {self.user_id if self.user_id else 'UNKNOWN'}")

    async def start_quiz(self, update: Update, chat_id: int, user_id: int) -> int:
        """Starts the quiz by sending the first question."""
        logger.info(f"[QuizLogic] start_quiz called for quiz {self.quiz_id}, user {user_id}, chat {chat_id}")
        if not self.questions_data or self.total_questions == 0:
            logger.warning(f"[QuizLogic] start_quiz called for quiz {self.quiz_id} but no questions available. Ending quiz.")
            message_to_edit_id = None
            if update and update.callback_query and update.callback_query.message: # Check if update and its attributes exist
                message_to_edit_id = update.callback_query.message.message_id
            
            if message_to_edit_id:
                await safe_edit_message_text(self.bot, chat_id=chat_id, message_id=message_to_edit_id, text="عذراً، لا توجد أسئلة لبدء هذا الاختبار. يرجى المحاولة مرة أخرى.")
            else:
                await safe_send_message(self.bot, chat_id=chat_id, text="عذراً، لا توجد أسئلة لبدء هذا الاختبار. يرجى المحاولة مرة أخرى.")
            return END 
        
        return await self.send_question(chat_id, user_id)
    
    def create_options_keyboard(self, options_data):
        keyboard = []
        arabic_alphabet_for_buttons = [chr(code) for code in range(0x0623, 0x0623 + 28)] 

        for i, option in enumerate(options_data):
            option_id = option.get("option_id", i)
            option_text_original = option.get("option_text", "")
            button_text = ""

            if option.get("is_image_option"):
                image_display_char = option.get("image_option_display_label")
                if not image_display_char:
                    if i < len(arabic_alphabet_for_buttons):
                        image_display_char = arabic_alphabet_for_buttons[i]
                    else:
                        image_display_char = f"{i + 1}"
                    logger.warning(f"image_option_display_label was missing for option_id {option_id}. Fallback to: {image_display_char}")
                button_text = f"اختر: {image_display_char}"
            elif isinstance(option_text_original, str) and not option_text_original.strip():
                button_text = f"خيار {i + 1}"
                logger.warning(f"Option text was empty for option_id {option_id} in quiz {self.quiz_id}. Using default: '{button_text}'")
            elif isinstance(option_text_original, str) and (option_text_original.startswith("http://")  or option_text_original.startswith("https://") ):
                button_text = f"خيار {i + 1} (صورة)"
                logger.info(f"Option text for option_id {option_id} in quiz {self.quiz_id} appears to be a URL. Using placeholder: '{button_text}'")
            elif isinstance(option_text_original, str):
                button_text = option_text_original
            else:
                button_text = f"خيار {i + 1} (بيانات غير نصية)"
                logger.warning(f"Option text for option_id {option_id} in quiz {self.quiz_id} was not a string (type: {type(option_text_original)}). Using default: '{button_text}'")
            
            button_text_str = str(button_text)
            if len(button_text_str.encode('utf-8')) > 64:
                temp_bytes = button_text_str.encode('utf-8')[:60]
                button_text = temp_bytes.decode('utf-8', 'ignore') + "..."
                logger.warning(f"Option text was too long for option_id {option_id} in quiz {self.quiz_id}. Truncated to: '{button_text}'")

            if not button_text_str.strip():
                 button_text = f"خيار {i + 1}"
                 logger.error(f"Critical: Button text became empty after processing for option_id {option_id}. Final fallback to: '{button_text}'")

            callback_data = f"ans_{self.current_question_index}_{option_id}"
            keyboard.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
        return InlineKeyboardMarkup(keyboard)

    async def send_question(self, chat_id: int, user_id: int):
        if self.current_question_index >= self.total_questions:
            logger.info(f"Quiz {self.quiz_id} completed for user {user_id}. Showing results.")
            await self.show_results(chat_id, user_id)
            return END

        current_question_data = self.questions_data[self.current_question_index]
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
                    display_label = ""
                    if option_image_counter < len(arabic_alphabet):
                        display_label = arabic_alphabet[option_image_counter]
                    else:
                        display_label = f"{option_image_counter + 1}"
                    
                    logger.info(f"Sending image for option {i} (caption: {display_label}) for quiz {self.quiz_id}. URL: {option_text_original}")
                    await self.bot.send_photo(
                        chat_id=chat_id,
                        photo=option_text_original,
                        caption=display_label
                    )
                    current_option_proc['is_image_option'] = True
                    current_option_proc['image_option_display_label'] = display_label
                    option_image_counter += 1
                    await asyncio.sleep(0.2)
                except Exception as e_img_opt:
                    logger.error(f"Failed to send image for option {i} (URL: {option_text_original}): {e_img_opt}", exc_info=True)
                    current_option_proc['is_image_option'] = False
            processed_options.append(current_option_proc)
        
        current_question_data['options'] = processed_options
        options_keyboard = self.create_options_keyboard(processed_options)
        header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
        image_url = current_question_data.get("image_url")
        question_text_from_data = current_question_data.get("question_text")
        sent_message = None
        self.last_question_is_image = False

        if image_url:
            caption_text = header
            if question_text_from_data:
                caption_text += str(question_text_from_data)
            
            logger.info(f"Attempting to send image question for quiz {self.quiz_id}, q_idx {self.current_question_index}. URL: {image_url}")
            try:
                sent_message = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=image_url,
                    caption=caption_text,
                    reply_markup=options_keyboard,
                    parse_mode="HTML"
                )
                self.last_question_is_image = True
            except telegram.error.BadRequest as e:
                logger.error(f"Failed to send photo (BadRequest) for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e}. URL: {image_url}", exc_info=True)
                if "BUTTON_TEXT_EMPTY" in str(e).upper() or "TEXT IS EMPTY" in str(e).upper():
                    logger.error(f"Error sending photo for q_id {current_question_data.get('question_id', 'UNKNOWN')} was due to empty button text. This should have been caught by create_options_keyboard.")
                
                if question_text_from_data:
                    logger.info(f"Photo send failed for q_id {current_question_data.get('question_id', 'UNKNOWN')}, attempting to send as text.")
                    full_question_text = header + str(question_text_from_data)
                    try:
                        sent_message = await safe_send_message(
                            self.bot,
                            chat_id=chat_id,
                            text=full_question_text,
                            reply_markup=options_keyboard,
                            parse_mode="HTML"
                        )
                    except Exception as e_fallback_text:
                        logger.error(f"Fallback to text also failed for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e_fallback_text}", exc_info=True)
                else:
                    logger.error(f"Photo send failed for q_id {current_question_data.get('question_id', 'UNKNOWN')} and no fallback text available.")
            except Exception as e:
                logger.error(f"Unexpected error sending photo for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e}. URL: {image_url}", exc_info=True)
                if question_text_from_data: 
                    logger.info(f"Photo send failed (general error), sending as text for q_id {current_question_data.get('question_id', 'UNKNOWN')}.")
                    try:
                        full_question_text = header + str(question_text_from_data)
                        sent_message = await safe_send_message(self.bot, chat_id=chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                    except Exception as e_fallback_general_text:
                         logger.error(f"Fallback to text (after general photo error) also failed for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e_fallback_general_text}", exc_info=True)

        else:
            question_text_main = str(question_text_from_data if question_text_from_data is not None else "")
            if not question_text_from_data:
                logger.warning(f"Question text is None/empty for TEXT q_id: {current_question_data.get('question_id', 'UNKNOWN')}. Sending header or minimal text.")

            full_question_text = header + question_text_main
            logger.info(f"Attempting to send text question for quiz {self.quiz_id}, q_idx {self.current_question_index}: {full_question_text[:100]}...")
            try:
                sent_message = await safe_send_message(
                    self.bot,
                    chat_id=chat_id,
                    text=full_question_text,
                    reply_markup=options_keyboard,
                    parse_mode="HTML"
                )
            except telegram.error.BadRequest as e:
                logger.error(f"Failed to send text question (BadRequest) for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e}.", exc_info=True)
                if "BUTTON_TEXT_EMPTY" in str(e).upper() or "TEXT IS EMPTY" in str(e).upper():
                    logger.error(f"Error sending text question for q_id {current_question_data.get('question_id', 'UNKNOWN')} was due to empty button text. This should have been caught by create_options_keyboard.")
            except Exception as e:
                 logger.error(f"Unexpected error sending text question for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e}.", exc_info=True)

        if sent_message:
            self.last_question_message_id = sent_message.message_id
            self.question_start_time = time.time()
            logger.info(f"Question {self.current_question_index} sent (msg_id: {self.last_question_message_id}, is_image: {self.last_question_is_image}) for quiz {self.quiz_id}, user {user_id}.")
            
            timer_job_name = f"qtimer_{user_id}_{chat_id}_{self.quiz_id}_{self.current_question_index}"
            remove_job_if_exists(timer_job_name, self.context)

            if self.context.job_queue:
                 self.context.job_queue.run_once(
                    self.question_timeout_callback,
                    self.question_time_limit,
                    chat_id=chat_id,
                    user_id=user_id,
                    name=timer_job_name,
                    data={
                        "quiz_id": self.quiz_id,
                        "question_index": self.current_question_index,
                        "user_id": user_id,
                        "chat_id": chat_id,
                        "message_id": sent_message.message_id,
                        "attempt_start_time": self.question_start_time,
                        "question_was_image": self.last_question_is_image
                    }
                )
                 logger.info(f"Question timer job '{timer_job_name}' scheduled for {self.question_time_limit}s for quiz {self.quiz_id}.")
            else:
                logger.error(f"JobQueue not available in context for quiz {self.quiz_id}. Cannot schedule question timer for user {user_id}.")
            return TAKING_QUIZ
        else:
            logger.error(f"Failed to send question (q_id: {current_question_data.get('question_id', 'UNKNOWN')}, index: {self.current_question_index}) for quiz {self.quiz_id}, user {user_id}. No message object returned. Ending quiz.")
            await safe_send_message(self.bot, chat_id=chat_id, text="حدث خطأ أثناء إرسال السؤال. تم إنهاء الاختبار.")
            await self.cleanup_quiz_data(user_id, "send_question_failure")
            return END

    async def handle_answer(self, update: Update, context: CallbackContext):
        query = update.callback_query
        user_id = query.from_user.id

        if str(user_id) != str(self.user_id):
            logger.warning(f"[QuizLogic {self.quiz_id}] Answer received from user {user_id}, but quiz belongs to {self.user_id}. Ignoring.")
            await query.answer(text="هذا الاختبار ليس لك.", show_alert=True)
            return TAKING_QUIZ

        time_taken = time.time() - self.question_start_time if self.question_start_time else -1
        timer_job_name = f"qtimer_{user_id}_{query.message.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        logger.info(f"Removed timer job '{timer_job_name}' because question {self.current_question_index} was answered for quiz {self.quiz_id}.")

        try:
            _, q_idx_str, chosen_option_id_str = query.data.split("_", 2)
            q_idx_answered = int(q_idx_str)
        except ValueError as e:
            logger.error(f"Invalid callback data format: {query.data} for quiz {self.quiz_id}. Error: {e}")
            await safe_edit_message_text(self.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في معالجة إجابتك. يرجى المحاولة مرة أخرى أو إنهاء الاختبار.")
            return TAKING_QUIZ

        if q_idx_answered != self.current_question_index:
            logger.warning(f"Answer received for question {q_idx_answered}, but current is {self.current_question_index} for quiz {self.quiz_id}. Ignoring old/duplicate callback.")
            await query.answer(text="لقد أجبت على هذا السؤال بالفعل أو انتهى وقته.")
            return TAKING_QUIZ

        current_question_data = self.questions_data[self.current_question_index]
        options = current_question_data.get("options", [])
        correct_option_id = current_question_data.get("correct_option_id")
        is_correct = False
        chosen_option_text = "غير محدد"
        correct_option_text = "غير محدد"

        for opt in options:
            opt_id_current = str(opt.get("option_id"))
            opt_text_current = opt.get("option_text", f"خيار {opt_id_current}")
            if opt.get("is_image_option"):
                 opt_text_current = f"صورة ({opt.get('image_option_display_label', opt_id_current)})"

            if opt_id_current == chosen_option_id_str:
                chosen_option_text = opt_text_current
                if opt_id_current == str(correct_option_id):
                    is_correct = True
            
            if opt_id_current == str(correct_option_id):
                correct_option_text = opt_text_current

        if is_correct:
            self.score += 1
            feedback_text = "✅ إجابة صحيحة!"
        else:
            feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة كانت: {correct_option_text}"
        
        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": chosen_option_id_str,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text,
            "is_correct": is_correct,
            "time_taken": time_taken
        })

        original_question_text_for_feedback = ""
        if self.last_question_is_image:
            original_question_text_for_feedback = query.message.caption if query.message.caption else f"<b>السؤال {self.current_question_index + 1}</b>"
        else:
            original_question_text_for_feedback = query.message.text if query.message.text else f"<b>السؤال {self.current_question_index + 1}</b>"
        
        header_to_check = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
        if original_question_text_for_feedback.startswith(header_to_check):
             text_content_for_feedback = original_question_text_for_feedback[len(header_to_check):]
        else:
             text_content_for_feedback = original_question_text_for_feedback

        full_feedback_message = f"{header_to_check}{text_content_for_feedback}\n\nChosen: {chosen_option_text}\n{feedback_text}"

        try:
            if self.last_question_is_image and query.message.caption is not None:
                await self.bot.edit_message_caption(
                    chat_id=query.message.chat_id,
                    message_id=self.last_question_message_id,
                    caption=full_feedback_message,
                    reply_markup=None,
                    parse_mode='HTML'
                )
            elif not self.last_question_is_image and query.message.text is not None:
                await self.bot.edit_message_text(
                    text=full_feedback_message,
                    chat_id=query.message.chat_id,
                    message_id=self.last_question_message_id,
                    reply_markup=None,
                    parse_mode='HTML'
                )
            else:
                 logger.warning(f"Could not edit message for feedback (q_idx {self.current_question_index}, quiz {self.quiz_id}) as it was neither an image with caption nor a text message as expected.")
                 await safe_send_message(self.bot, chat_id=query.message.chat_id, text=feedback_text)

        except telegram.error.BadRequest as e:
            if "MESSAGE_NOT_MODIFIED" in str(e).upper():
                logger.info(f"Message not modified for feedback (q_idx {self.current_question_index}, quiz {self.quiz_id}): {e}")
            else:
                logger.error(f"Error editing message for feedback (q_idx {self.current_question_index}, quiz {self.quiz_id}): {e}. Feedback: {feedback_text}", exc_info=True)
                await safe_send_message(self.bot, chat_id=query.message.chat_id, text=feedback_text)
        except Exception as e_edit:
            logger.error(f"General error editing message for feedback (q_idx {self.current_question_index}, quiz {self.quiz_id}): {e_edit}. Feedback: {feedback_text}", exc_info=True)
            await safe_send_message(self.bot, chat_id=query.message.chat_id, text=feedback_text)

        self.current_question_index += 1
        await asyncio.sleep(1)
        return await self.send_question(query.message.chat_id, user_id)

    async def question_timeout_callback(self, context: CallbackContext):
        job_data = context.job.data
        user_id = job_data["user_id"]
        chat_id = job_data["chat_id"]
        quiz_id_from_job = job_data["quiz_id"]
        question_index_from_job = job_data["question_index"]
        message_id_from_job = job_data["message_id"]
        question_was_image = job_data.get("question_was_image", False)

        logger.info(f"Timeout for question {question_index_from_job} of quiz {quiz_id_from_job} for user {user_id}.")

        if quiz_id_from_job != self.quiz_id or question_index_from_job != self.current_question_index or str(user_id) != str(self.user_id):
            logger.warning(f"Stale timeout job executed for quiz {quiz_id_from_job}, q_idx {question_index_from_job}, user {user_id}. Current quiz: {self.quiz_id}, q_idx: {self.current_question_index}, user: {self.user_id}. Ignoring.")
            return

        current_question_data = self.questions_data[self.current_question_index]
        correct_option_id = current_question_data.get("correct_option_id")
        correct_option_text = "غير محدد"
        options = current_question_data.get("options", [])
        for opt in options:
            if str(opt.get("option_id")) == str(correct_option_id):
                correct_option_text = opt.get("option_text", f"خيار {correct_option_id}")
                if opt.get("is_image_option"):
                    correct_option_text = f"صورة ({opt.get('image_option_display_label', correct_option_id)})"
                break
        
        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text,
            "is_correct": False,
            "time_taken": self.question_time_limit
        })

        feedback_text = f"⏰ انتهى الوقت للسؤال! الإجابة الصحيحة كانت: {correct_option_text}"
        
        try:
            original_message = await self.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id_from_job,
                reply_markup=None
            )
            if question_was_image and original_message.caption is not None:
                header_to_check = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
                caption_content = original_message.caption
                if caption_content.startswith(header_to_check):
                    caption_content = caption_content[len(header_to_check):]
                
                full_feedback_message = f"{header_to_check}{caption_content}\n\n{feedback_text}"
                await self.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id_from_job,
                    caption=full_feedback_message,
                    parse_mode='HTML'
                )
            elif not question_was_image and original_message.text is not None:
                header_to_check = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
                text_content = original_message.text
                if text_content.startswith(header_to_check):
                    text_content = text_content[len(header_to_check):]
                
                full_feedback_message = f"{header_to_check}{text_content}\n\n{feedback_text}"
                await self.bot.edit_message_text(
                    text=full_feedback_message,
                    chat_id=chat_id,
                    message_id=message_id_from_job,
                    parse_mode='HTML'
                )
            else:
                logger.warning(f"Timeout: Could not determine original message type (q_idx {self.current_question_index}, quiz {self.quiz_id}) to append feedback. Sending as new message.")
                await safe_send_message(self.bot, chat_id=chat_id, text=feedback_text)

        except telegram.error.BadRequest as e:
            if "MESSAGE_NOT_MODIFIED" in str(e).upper():
                logger.info(f"Timeout: Message not modified for feedback (q_idx {self.current_question_index}, quiz {self.quiz_id}): {e}")
            else:
                logger.error(f"Timeout: Error editing message for feedback (q_idx {self.current_question_index}, quiz {self.quiz_id}): {e}. Feedback: {feedback_text}", exc_info=True)
                await safe_send_message(self.bot, chat_id=chat_id, text=feedback_text)
        except Exception as e_timeout_edit:
            logger.error(f"Timeout: General error editing message for feedback (q_idx {self.current_question_index}, quiz {self.quiz_id}): {e_timeout_edit}. Feedback: {feedback_text}", exc_info=True)
            await safe_send_message(self.bot, chat_id=chat_id, text=feedback_text)

        self.current_question_index += 1
        await asyncio.sleep(1)
        current_state_after_timeout = await self.send_question(chat_id, user_id)

        if current_state_after_timeout == END:
            logger.info(f"Timeout callback for quiz {self.quiz_id} resulted in quiz end. Main handler should reflect this.")

    async def show_results(self, chat_id: int, user_id: int):
        logger.info(f"Showing results for quiz {self.quiz_id}, user {user_id}. Score: {self.score}/{self.total_questions}")
        results_text = f"🏁 انتهى الاختبار! 🏁\n\nنتيجتك: {self.score} من {self.total_questions} إجابات صحيحة.\n"
        results_text += "\n<b>تفاصيل إجاباتك:</b>\n"
        for i, ans in enumerate(self.answers):
            q_text = ans.get("question_text", "نص السؤال غير متوفر")
            chosen = ans.get("chosen_option_text", "لم يتم الاختيار")
            correct = ans.get("correct_option_text", "غير محددة")
            status = "✅" if ans.get("is_correct") else ("❌" if ans.get("chosen_option_id") is not None else "⏰")
            results_text += f"\n{i+1}. {q_text}\n   {status} اخترت: {chosen}\n" 
            if not ans.get("is_correct") and ans.get("chosen_option_id") is not None:
                results_text += f"   الصحيحة: {correct}\n"
            elif ans.get("chosen_option_id") is None: # Timeout
                 results_text += f"   الصحيحة كانت: {correct}\n"

        keyboard = [
            [InlineKeyboardButton("ابدأ اختبار جديد", callback_data="quiz_menu")],
            [InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message_to_send_results_to = self.last_question_message_id
        edited_successfully = False

        if message_to_send_results_to:
            try:
                await self.bot.edit_message_text(
                    text=results_text,
                    chat_id=chat_id,
                    message_id=message_to_send_results_to,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
                edited_successfully = True
                logger.info(f"Results for quiz {self.quiz_id} edited into message_id {message_to_send_results_to}.")
            except telegram.error.BadRequest as e_edit_results:
                logger.warning(f"Failed to edit results into message_id {message_to_send_results_to} for quiz {self.quiz_id}: {e_edit_results}. Sending as new message.")
            except Exception as e_gen_edit_results:
                 logger.error(f"Generic error editing results into message_id {message_to_send_results_to} for quiz {self.quiz_id}: {e_gen_edit_results}. Sending as new message.")
        
        if not edited_successfully:
            await safe_send_message(self.bot, chat_id=chat_id, text=results_text, reply_markup=reply_markup, parse_mode='HTML')
            logger.info(f"Results for quiz {self.quiz_id} sent as a new message.")

        await self.cleanup_quiz_data(user_id, "quiz_completed")
        return END

    async def end_quiz(self, update: Update, context: CallbackContext, manual_end: bool = False):
        user_id = update.effective_user.id if update.effective_user else self.user_id
        chat_id = update.effective_chat.id if update.effective_chat else None
        
        reason = "manual_end" if manual_end else "unknown_end_quiz_call"
        logger.info(f"end_quiz called for quiz {self.quiz_id} for user {user_id}. Reason: {reason}")

        timer_job_name = f"qtimer_{user_id}_{chat_id if chat_id else 'unknown_chat'}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        logger.info(f"Removed timer job '{timer_job_name}' during end_quiz for quiz {self.quiz_id}.")

        if manual_end and chat_id:
            if self.answers:
                results_text = f"تم إنهاء الاختبار يدوياً. 🏁\n\nنتيجتك حتى الآن: {self.score} من {self.current_question_index} أسئلة تمت الإجابة عليها (أو انتهى وقتها).\n"
                if self.total_questions > 0:
                     results_text = f"تم إنهاء الاختبار يدوياً. 🏁\n\nنتيجتك حتى الآن: {self.score} من {self.total_questions} (تم الوصول للسؤال {self.current_question_index}).\n"
                
                results_text += "\n<b>تفاصيل إجاباتك:</b>\n"
                for i, ans in enumerate(self.answers):
                    q_text = ans.get("question_text", "نص السؤال غير متوفر")
                    chosen = ans.get("chosen_option_text", "لم يتم الاختيار")
                    correct = ans.get("correct_option_text", "غير محددة")
                    status = "✅" if ans.get("is_correct") else ("❌" if ans.get("chosen_option_id") is not None else "⏰")
                    results_text += f"\n{i+1}. {q_text}\n   {status} اخترت: {chosen}\n" 
                    if not ans.get("is_correct") and ans.get("chosen_option_id") is not None:
                        results_text += f"   الصحيحة: {correct}\n"
                    elif ans.get("chosen_option_id") is None: # Timeout
                        results_text += f"   الصحيحة كانت: {correct}\n"
                
                keyboard = [
                    [InlineKeyboardButton("ابدأ اختبار جديد", callback_data="quiz_menu")],
                    [InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await safe_send_message(self.bot, chat_id=chat_id, text=results_text, reply_markup=reply_markup, parse_mode='HTML')
            else:
                if self.last_question_message_id:
                    try:
                        await self.bot.edit_message_reply_markup(chat_id=chat_id, message_id=self.last_question_message_id, reply_markup=None)
                    except Exception as e_rem_markup:
                        logger.warning(f"Failed to remove markup from last question message {self.last_question_message_id} on manual end: {e_rem_markup}")

        await self.cleanup_quiz_data(user_id, reason)
        return END

    async def cleanup_quiz_data(self, user_id, reason: str):
        logger.info(f"Cleaning up quiz data for quiz_id: {self.quiz_id}, user: {user_id}, reason: {reason}")
        self.questions_data = []
        self.answers = []
        self.score = 0
        self.current_question_index = 0
        self.last_question_message_id = None
        self.question_start_time = None
        logger.info(f"Quiz instance {self.quiz_id} data has been reset internally.")


