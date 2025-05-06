# -*- coding: utf-8 -*-
# In handlers/quiz_logic.py
# Make sure these imports are at the top of your handlers/quiz_logic.py file if not already present:
import time
import telegram # For telegram.error types
from telegram.ext import ConversationHandler
from config import logger # Assuming logger is in your config.py
from utils.helpers import safe_send_message, remove_job_if_exists # Ensure this path is correct

class QuizLogic:
    # ... (your existing __init__ and other methods like create_options_keyboard, handle_answer, etc.) ...

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

        if image_url:  # This is an image-based question
            caption_text = header
            # If question_text_from_data exists for an image question (e.g., "What is in the image?"), append it.
            if question_text_from_data:
                caption_text += str(question_text_from_data) # Ensure it's a string
            
            logger.info(f"Attempting to send image question for quiz {self.quiz_id}, q_idx {self.current_question_index}. URL: {image_url}")
            try:
                sent_message = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=image_url,
                    caption=caption_text,
                    reply_markup=options_keyboard,
                    parse_mode="HTML"
                )
            except telegram.error.BadRequest as e:
                logger.error(f"Failed to send photo (BadRequest) for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e}. URL: {image_url}")
                # Fallback: if photo fails and there's text, send text only
                if question_text_from_data:
                    logger.info(f"Photo send failed for q_id {current_question_data.get('question_id', 'UNKNOWN')}, attempting to send as text.")
                    full_question_text = header + str(question_text_from_data)
                    sent_message = await safe_send_message(
                        self.bot,
                        chat_id=chat_id,
                        text=full_question_text,
                        reply_markup=options_keyboard,
                        parse_mode="HTML"
                    )
                else:
                    logger.error(f"Photo send failed for q_id {current_question_data.get('question_id', 'UNKNOWN')} and no fallback text available.")
            except Exception as e:
                logger.error(f"Unexpected error sending photo for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e}. URL: {image_url}", exc_info=True)

        else:  # This is a text-based question
            # Ensure question_text_main is a string, even if empty
            question_text_main = str(question_text_from_data if question_text_from_data is not None else "")
            if not question_text_from_data:
                logger.warning(f"Question text is None/empty for TEXT q_id: {current_question_data.get('question_id', 'UNKNOWN')}. Sending header or minimal text.")

            full_question_text = header + question_text_main
            logger.info(f"Attempting to send text question for quiz {self.quiz_id}, q_idx {self.current_question_index}: {full_question_text[:100]}...")
            sent_message = await safe_send_message(
                self.bot,
                chat_id=chat_id,
                text=full_question_text,
                reply_markup=options_keyboard,
                parse_mode="HTML"
            )

        if sent_message:
            self.last_question_message_id = sent_message.message_id
            logger.info(f"Question {self.current_question_index} sent (msg_id: {self.last_question_message_id}) for quiz {self.quiz_id}, user {user_id}.")
            
            timer_job_name = f"qtimer_{user_id}_{chat_id}_{self.quiz_id}_{self.current_question_index}"
            remove_job_if_exists(timer_job_name, self.context) # self.context should be CallbackContext

            self.context.job_queue.run_once(
                self.question_timeout_callback, # Ensure this callback is defined in QuizLogic
                self.question_time_limit, # Ensure self.question_time_limit is defined
                chat_id=chat_id,
                user_id=user_id,
                name=timer_job_name,
                data={
                    "quiz_id": self.quiz_id,
                    "question_index": self.current_question_index,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "message_id": sent_message.message_id, # Store message_id for timeout handling
                    "attempt_start_time": time.time()
                }
            )
            logger.info(f"Question timer ({self.question_time_limit}s) started for q:{self.current_question_index} quiz:{self.quiz_id} user:{user_id} (Job: {timer_job_name})")
        else:
            logger.error(f"Failed to send question {self.current_question_index} (text or image) for quiz {self.quiz_id} to user {user_id}. No message object returned.")
            try:
                await safe_send_message(self.bot, chat_id, "عذراً، حدث خطأ أثناء إرسال السؤال. سيتم إنهاء الاختبار الحالي.")
            except Exception as e_msg_err:
                logger.error(f"Failed to send error message to user {user_id} after question send failure: {e_msg_err}")
            return ConversationHandler.END # End the quiz due to this critical error

    # ... (your existing show_results, question_timeout_callback, etc.) ...

