# -*- coding: utf-8 -*-
# handlers/quiz_logic.py

import asyncio
import logging
import time
import uuid # لإنشاء معرّف فريد للاختبار
import telegram # For telegram.error types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup # Added Update and keyboard types
from telegram.ext import ConversationHandler, CallbackContext, JobQueue # Corrected and added CallbackContext, JobQueue
from config import logger, TAKING_QUIZ # Assuming logger and TAKING_QUIZ are in your config.py
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
        self.answers = []
        self.question_start_time = None
        self.last_question_message_id = None
        self.question_time_limit = question_time_limit
        self.last_question_is_image = False # Added to track if the last question was an image
        logger.debug(f"[QuizLogic] Initialized for quiz {self.quiz_id}, user {self.user_id if self.user_id else 'UNKNOWN'}")

    def create_options_keyboard(self, options_data):
        keyboard = []
        for i, option in enumerate(options_data):
            option_id = option.get("option_id", i)
            option_text_original = option.get("option_text", "")

            button_text = ""
            if not option_text_original or option_text_original.strip() == "":
                button_text = f"خيار {i + 1}"
                logger.warning(f"Option text was empty for option_id {option_id} in quiz {self.quiz_id}. Using default: '{button_text}'")
            elif option_text_original.startswith("http://")  or option_text_original.startswith("https://") :
                button_text = f"خيار {i + 1} (صورة)"
                logger.info(f"Option text for option_id {option_id} in quiz {self.quiz_id} was a URL. Using placeholder: '{button_text}'")
            else:
                button_text = str(option_text_original)
            
            if len(button_text.encode('utf-8')) > 60:
                button_text = button_text[:20] + "..."
                logger.warning(f"Option text was too long for option_id {option_id} in quiz {self.quiz_id}. Truncated to: '{button_text}'")

            if not button_text:
                 button_text = f"خيار {i + 1}"
                 logger.error(f"Critical: Button text became empty after processing for option_id {option_id}. Final fallback to: '{button_text}'")

            callback_data = f"ans_{self.current_question_index}_{option_id}"
            keyboard.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
        return InlineKeyboardMarkup(keyboard)

    async def send_question(self, chat_id: int, user_id: int):
        if self.current_question_index >= self.total_questions:
            logger.info(f"Quiz {self.quiz_id} completed for user {user_id}. Showing results.")
            await self.show_results(chat_id, user_id)
            return ConversationHandler.END

        current_question_data = self.questions_data[self.current_question_index]
        options = current_question_data.get("options", [])
        options_keyboard = self.create_options_keyboard(options)
        
        header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"

        image_url = current_question_data.get("image_url")
        question_text_from_data = current_question_data.get("question_text")

        sent_message = None
        self.last_question_is_image = False # Reset before sending new question

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
                self.last_question_is_image = True # Set flag if image sent successfully
            except telegram.error.BadRequest as e:
                logger.error(f"Failed to send photo (BadRequest) for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e}. URL: {image_url}")
                if "BUTTON_TEXT_EMPTY" in str(e) or "text is empty" in str(e).lower():
                    logger.error(f"Error sending photo for q_id {current_question_data.get('question_id', 'UNKNOWN')} was due to empty button text. This should have been caught by create_options_keyboard.")
                
                if question_text_from_data: # Fallback to text if photo fails
                    logger.info(f"Photo send failed for q_id {current_question_data.get('question_id', 'UNKNOWN')}, attempting to send as text.")
                    full_question_text = header + str(question_text_from_data)
                    sent_message = await safe_send_message(
                        self.bot,
                        chat_id=chat_id,
                        text=full_question_text,
                        reply_markup=options_keyboard,
                        parse_mode="HTML"
                    )
                    # self.last_question_is_image remains False
                else:
                    logger.error(f"Photo send failed for q_id {current_question_data.get('question_id', 'UNKNOWN')} and no fallback text available.")
            except Exception as e:
                logger.error(f"Unexpected error sending photo for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e}. URL: {image_url}", exc_info=True)

        else: # Text question
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
                # self.last_question_is_image remains False
            except telegram.error.BadRequest as e:
                logger.error(f"Failed to send text question (BadRequest) for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e}.")
                if "BUTTON_TEXT_EMPTY" in str(e) or "text is empty" in str(e).lower():
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
                        "question_was_image": self.last_question_is_image # Pass if question was image
                    }
                )
                 logger.info(f"Question timer ({self.question_time_limit}s) started for q:{self.current_question_index} quiz:{self.quiz_id} user:{user_id} (Job: {timer_job_name})")
            else:
                logger.error(f"JobQueue not found in context for quiz {self.quiz_id}, user {user_id}. Timer not started.")
        else:
            logger.error(f"Failed to send question {self.current_question_index} (text or image) for quiz {self.quiz_id} to user {user_id}. No message object returned.")
            try:
                await safe_send_message(self.bot, chat_id, "عذراً، حدث خطأ أثناء إرسال السؤال الحالي. سيتم إنهاء الاختبار. يرجى المحاولة لاحقاً.")
            except Exception as e_msg_err:
                logger.error(f"Failed to send error message to user {user_id} after question send failure: {e_msg_err}")
            user_data = self.context.user_data
            if user_data:
                user_data.pop('current_quiz_logic', None)
                user_data.pop('quiz_type', None)
                user_data.pop('quiz_scope', None)
                user_data.pop('question_count', None)
            return ConversationHandler.END

    async def handle_answer(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        
        if not hasattr(self, 'quiz_id') or not self.quiz_id:
            logger.warning(f"handle_answer called for user {user_id} but quiz_id is not set in QuizLogic instance. Ignoring.")
            return

        timer_job_name = f"qtimer_{user_id}_{chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)

        try:
            _, question_idx_str, option_id_str = query.data.split("_")
            question_idx = int(question_idx_str)
        except ValueError:
            logger.error(f"Error parsing callback_data: {query.data} for quiz {self.quiz_id}")
            await safe_send_message(self.bot, chat_id, "حدث خطأ في معالجة إجابتك. يرجى المحاولة مرة أخرى.")
            return

        if question_idx != self.current_question_index:
            logger.warning(f"Received answer for q_idx {question_idx} but current is {self.current_question_index} for quiz {self.quiz_id}. Ignoring.")
            return

        current_question_data = self.questions_data[self.current_question_index]
        selected_option_id_str = option_id_str
        is_correct = False
        selected_option_text_for_display = "غير محدد"

        for opt_idx, opt in enumerate(current_question_data.get("options", [])):
            if str(opt.get("option_id", -1)) == selected_option_id_str:
                is_correct = opt.get("is_correct", False)
                original_opt_text = opt.get("option_text", "")
                
                if (original_opt_text.startswith("http://")  or original_opt_text.startswith("https://") ) and not original_opt_text.strip() == "":
                    selected_option_text_for_display = f"خيار {opt_idx + 1} (صورة)" 
                elif not original_opt_text or original_opt_text.strip() == "":
                    selected_option_text_for_display = f"خيار {opt_idx + 1}"
                else:
                    selected_option_text_for_display = original_opt_text
                break
        
        time_taken = time.time() - self.question_start_time

        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": current_question_data.get("question_text", "N/A"),
            "selected_option_id": selected_option_id_str,
            "selected_option_text": selected_option_text_for_display, 
            "is_correct": is_correct,
            "time_taken": time_taken
        })

        if is_correct:
            self.score += 1
            feedback_text = "✅ إجابة صحيحة!"
        else:
            feedback_text = "❌ إجابة خاطئة."
        
        header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
        q_text_from_data = current_question_data.get("question_text")
        # If it was an image and had no specific question_text, original_question_content for caption should be empty or just the header.
        # Otherwise, it includes the question_text.
        original_question_content_for_feedback = str(q_text_from_data if q_text_from_data is not None else "")
        if self.last_question_is_image and not q_text_from_data:
             original_question_content_for_feedback = "" # Avoids repeating 'None' or empty string if image had no specific text beyond header
        
        # Construct the feedback part that will be appended or set as caption
        feedback_part = f"\n\n<i>إجابتك: {selected_option_text_for_display}</i>\n<b>{feedback_text}</b>"

        if self.last_question_is_image:
            # For images, the caption is header + original_question_content_for_feedback + feedback_part
            final_caption = header + original_question_content_for_feedback + feedback_part
            try:
                await self.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=self.last_question_message_id,
                    caption=final_caption,
                    reply_markup=None, 
                    parse_mode="HTML"
                )
            except telegram.error.BadRequest as e:
                logger.error(f"Failed to edit image caption for quiz {self.quiz_id} (q_idx {self.current_question_index}): {e}. Sending feedback as new message.")
                # Fallback: send feedback as a new message if editing caption fails
                await safe_send_message(self.bot, chat_id, feedback_part.strip(), parse_mode="HTML")
            except Exception as e:
                logger.error(f"Unexpected error editing image caption for quiz {self.quiz_id} (q_idx {self.current_question_index}): {e}", exc_info=True)
                await safe_send_message(self.bot, chat_id, feedback_part.strip(), parse_mode="HTML")
        else:
            # For text messages, the text is header + original_question_content_for_feedback + feedback_part
            final_text = header + original_question_content_for_feedback + feedback_part
            await safe_edit_message_text(
                bot=self.bot,
                chat_id=chat_id,
                message_id=self.last_question_message_id,
                text=final_text,
                reply_markup=None, 
                parse_mode="HTML"
            )

        self.current_question_index += 1
        await asyncio.sleep(1.5) # Give user time to read feedback
        await self.send_question(chat_id, user_id)

    async def question_timeout_callback(self, context: CallbackContext):
        job_data = context.job.data
        quiz_id = job_data["quiz_id"]
        question_idx = job_data["question_index"]
        user_id = job_data["user_id"]
        chat_id = job_data["chat_id"]
        message_id = job_data["message_id"]
        question_was_image = job_data.get("question_was_image", False) # Retrieve the flag

        if not hasattr(self, 'quiz_id') or self.quiz_id != quiz_id or self.current_question_index != question_idx:
            logger.info(f"Timeout job for old quiz/question ({quiz_id}, q_idx {question_idx}) ignored. Current: ({getattr(self, 'quiz_id', 'N/A')}, q_idx {self.current_question_index})")
            return

        logger.info(f"Question {question_idx} timed out for user {user_id} in quiz {quiz_id}.")
        
        self.answers.append({
            "question_id": self.questions_data[question_idx].get("question_id"),
            "question_text": self.questions_data[question_idx].get("question_text", "N/A"),
            "selected_option_id": None,
            "selected_option_text": "انتهى الوقت",
            "is_correct": False,
            "time_taken": self.question_time_limit
        })
        
        timed_out_question_data = self.questions_data[question_idx]
        header = f"<b>السؤال {question_idx + 1} من {self.total_questions}:</b>\n"
        q_text_from_data = timed_out_question_data.get("question_text")
        original_question_content_for_feedback = str(q_text_from_data if q_text_from_data is not None else "")
        if question_was_image and not q_text_from_data:
            original_question_content_for_feedback = ""

        timeout_feedback_part = "\n\n<i>انتهى الوقت المخصص للسؤال.</i>"

        if question_was_image:
            final_caption = header + original_question_content_for_feedback + timeout_feedback_part
            try:
                await self.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=final_caption,
                    reply_markup=None,
                    parse_mode="HTML"
                )
            except telegram.error.BadRequest as e:
                logger.error(f"Failed to edit image caption on timeout for quiz {quiz_id} (q_idx {question_idx}): {e}. Sending feedback as new message.")
                await safe_send_message(self.bot, chat_id, timeout_feedback_part.strip(), parse_mode="HTML")
            except Exception as e:
                logger.error(f"Unexpected error editing image caption on timeout for quiz {quiz_id} (q_idx {question_idx}): {e}", exc_info=True)
                await safe_send_message(self.bot, chat_id, timeout_feedback_part.strip(), parse_mode="HTML")
        else:
            final_text = header + original_question_content_for_feedback + timeout_feedback_part
            await safe_edit_message_text(
                bot=self.bot,
                chat_id=chat_id,
                message_id=message_id,
                text=final_text,
                reply_markup=None,
                parse_mode="HTML"
            )
        
        self.current_question_index += 1
        await asyncio.sleep(1.5)
        await self.send_question(chat_id, user_id)

    async def show_results(self, chat_id: int, user_id: int):
        total_answered = len(self.answers)
        correct_answers = self.score
        percentage = (correct_answers / self.total_questions) * 100 if self.total_questions > 0 else 0

        results_text = f"🏁 <b>نتائج الاختبار (معرف: {self.quiz_id})</b> 🏁\n\n"
        results_text += f"عدد الأسئلة الكلي: {self.total_questions}\n"
        results_text += f"عدد الإجابات الصحيحة: {correct_answers}\n"
        results_text += f"النسبة المئوية: {percentage:.2f}%\n\n"
        results_text += "<b>تفاصيل الإجابات:</b>\n"
        for i, ans in enumerate(self.answers):
            q_text_display = ans.get("question_text", "سؤال غير متوفر")
            if len(q_text_display) > 50: q_text_display = q_text_display[:47] + "..."
            results_text += f"<b>{i+1}.</b> {q_text_display} -> إجابتك: {ans.get('selected_option_text', 'لا توجد إجابة')} ({'صحيحة' if ans.get('is_correct') else 'خاطئة'})
"
        
        # Clean up quiz state from user_data
        if self.context.user_data.get("current_quiz_logic") == self:
            self.context.user_data.pop("current_quiz_logic", None)
            logger.info(f"Quiz data cleaned from user_data for user {user_id} after quiz {self.quiz_id}")

        # Send results
        # Check if the last message was an image or text to decide how to send results
        # However, results are usually best sent as a new message.
        await safe_send_message(self.bot, chat_id, results_text, parse_mode="HTML")
        
        # Optionally, offer to go back to the main menu or start a new quiz
        # For now, we just end the conversation here implicitly by returning ConversationHandler.END in calling functions
        logger.info(f"Results for quiz {self.quiz_id} shown to user {user_id}. Score: {correct_answers}/{self.total_questions}")

    async def start_quiz(self, update: Update) -> int:
        """Starts the quiz by sending the first question."""
        query = update.callback_query # Assuming start_quiz is called from a callback
        chat_id = query.message.chat_id
        user_id = query.from_user.id

        if not self.questions_data or self.total_questions == 0:
            logger.warning(f"Attempted to start quiz {self.quiz_id} for user {user_id} with no questions.")
            await safe_edit_message_text(self.bot, chat_id, query.message.message_id, "عذراً، لا توجد أسئلة متاحة لهذا الاختبار أو لم يتم تحديد عدد الأسئلة. يرجى المحاولة مرة أخرى.")
            return ConversationHandler.END

        logger.info(f"Quiz {self.quiz_id} starting for user {user_id} with {self.total_questions} questions of type {self.quiz_type}.")
        await self.send_question(chat_id, user_id)
        return TAKING_QUIZ # Return the state for the conversation handler

    async def end_quiz(self, reason: str = "ended"):
        """Ends the quiz prematurely if needed and cleans up."""
        logger.info(f"Quiz {self.quiz_id} for user {self.user_id} is being ended. Reason: {reason}")
        # Clean up any running timers for this quiz instance
        timer_job_name = f"qtimer_{self.user_id}_{self.context.chat_data.get('chat_id', self.user_id)}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, self.context)
        
        # Clean up quiz state from user_data
        if self.context.user_data.get("current_quiz_logic") == self:
            self.context.user_data.pop("current_quiz_logic", None)
            logger.info(f"Quiz data cleaned from user_data for user {self.user_id} due to quiz end ({reason}).")
        # No return value needed if called internally, or return ConversationHandler.END if called by a handler

