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
        
        # Call send_question to send the first question and get the next state
        return await self.send_question(chat_id, user_id)
    
    def create_options_keyboard(self, options_data):
        keyboard = []
        # ADDED: Arabic alphabet for fallback if image_option_display_label is somehow not set
        arabic_alphabet_for_buttons = [chr(code) for code in range(0x0623, 0x0623 + 28)] 

        for i, option in enumerate(options_data):
            option_id = option.get("option_id", i) # Use provided option_id or index
            option_text_original = option.get("option_text", "")

            button_text = ""
            # ADDED: Check for pre-sent image options (from processed_options)
            if option.get("is_image_option"):
                image_display_char = option.get("image_option_display_label")
                if not image_display_char: # Fallback, should ideally not happen
                    if i < len(arabic_alphabet_for_buttons):
                        image_display_char = arabic_alphabet_for_buttons[i]
                    else:
                        image_display_char = f"{i + 1}"
                    logger.warning(f"image_option_display_label was missing for option_id {option_id}. Fallback to: {image_display_char}")
                button_text = f"اختر: {image_display_char}"
            # ORIGINAL LOGIC BELOW (KEPT AS IS)
            elif isinstance(option_text_original, str) and not option_text_original.strip():
                button_text = f"خيار {i + 1}"
                logger.warning(f"Option text was empty for option_id {option_id} in quiz {self.quiz_id}. Using default: '{button_text}'")
            elif isinstance(option_text_original, str) and (option_text_original.startswith("http://")  or option_text_original.startswith("https://") ):
                button_text = f"خيار {i + 1} (صورة)"
                logger.info(f"Option text for option_id {option_id} in quiz {self.quiz_id} appears to be a URL. Using placeholder: '{button_text}'")
            elif isinstance(option_text_original, str):
                button_text = option_text_original
            else: # Not a string, or None
                button_text = f"خيار {i + 1} (بيانات غير نصية)"
                logger.warning(f"Option text for option_id {option_id} in quiz {self.quiz_id} was not a string (type: {type(option_text_original)}). Using default: '{button_text}'")
            
            # Ensure button_text is a string before encoding
            button_text_str = str(button_text)
            # CORRECTED LINE 85 and similar lines
            if len(button_text_str.encode('utf-8')) > 64: # Telegram's limit for button text
                # Truncate carefully to avoid splitting multi-byte characters
                temp_bytes = button_text_str.encode('utf-8')[:60] # truncate bytes
                button_text = temp_bytes.decode('utf-8', 'ignore') + "..."
                logger.warning(f"Option text was too long for option_id {option_id} in quiz {self.quiz_id}. Truncated to: '{button_text}'")

            if not button_text_str.strip(): # Final check if button text became empty after processing
                 button_text = f"خيار {i + 1}" # Fallback if all else fails
                 logger.error(f"Critical: Button text became empty after processing for option_id {option_id}. Final fallback to: '{button_text}'")

            callback_data = f"ans_{self.current_question_index}_{option_id}"
            keyboard.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
        return InlineKeyboardMarkup(keyboard)

    async def send_question(self, chat_id: int, user_id: int):
        if self.current_question_index >= self.total_questions:
            logger.info(f"Quiz {self.quiz_id} completed for user {user_id}. Showing results.")
            await self.show_results(chat_id, user_id)
            return END # Use END from config

        current_question_data = self.questions_data[self.current_question_index]
        options = current_question_data.get("options", [])

        # ADDED: Pre-send image options and prepare processed_options
        processed_options = []
        arabic_alphabet = [chr(code) for code in range(0x0623, 0x0623 + 28)] # أ to ي
        option_image_counter = 0

        for i, option_data_original in enumerate(options):
            current_option_proc = option_data_original.copy() # Work on a copy
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
                        display_label = f"{option_image_counter + 1}" # Fallback to number
                    
                    logger.info(f"Sending image for option {i} (caption: {display_label}) for quiz {self.quiz_id}. URL: {option_text_original}")
                    await self.bot.send_photo(
                        chat_id=chat_id,
                        photo=option_text_original,
                        caption=display_label
                    )
                    current_option_proc['is_image_option'] = True
                    current_option_proc['image_option_display_label'] = display_label
                    option_image_counter += 1
                    await asyncio.sleep(0.2) # Small delay
                except Exception as e_img_opt:
                    logger.error(f"Failed to send image for option {i} (URL: {option_text_original}): {e_img_opt}", exc_info=True) # DEBUG ENHANCEMENT
                    current_option_proc['is_image_option'] = False # Mark as not sent
            processed_options.append(current_option_proc)
        
        # IMPORTANT ADDITION: Update current_question_data with processed options so handle_answer and timeout can use them
        current_question_data['options'] = processed_options
        # END OF ADDED SECTION FOR IMAGE OPTIONS PRE-SENDING
        
        options_keyboard = self.create_options_keyboard(processed_options)
        
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
                logger.error(f"Failed to send photo (BadRequest) for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e}. URL: {image_url}", exc_info=True) # DEBUG ENHANCEMENT
                if "BUTTON_TEXT_EMPTY" in str(e).upper() or "TEXT IS EMPTY" in str(e).upper():
                    logger.error(f"Error sending photo for q_id {current_question_data.get('question_id', 'UNKNOWN')} was due to empty button text. This should have been caught by create_options_keyboard.")
                
                if question_text_from_data: # Fallback to text if photo fails
                    logger.info(f"Photo send failed for q_id {current_question_data.get('question_id', 'UNKNOWN')}, attempting to send as text.")
                    full_question_text = header + str(question_text_from_data)
                    try: # DEBUG ENHANCEMENT
                        sent_message = await safe_send_message(
                            self.bot,
                            chat_id=chat_id,
                            text=full_question_text,
                            reply_markup=options_keyboard,
                            parse_mode="HTML"
                        )
                    except Exception as e_fallback_text: # DEBUG ENHANCEMENT
                        logger.error(f"Fallback to text also failed for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e_fallback_text}", exc_info=True) # DEBUG ENHANCEMENT
                else:
                    logger.error(f"Photo send failed for q_id {current_question_data.get('question_id', 'UNKNOWN')} and no fallback text available.")
            except Exception as e:
                logger.error(f"Unexpected error sending photo for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e}. URL: {image_url}", exc_info=True)
                # ADDED: Fallback from original if general error and text exists (was missing in one version)
                if question_text_from_data: 
                    logger.info(f"Photo send failed (general error), sending as text for q_id {current_question_data.get('question_id', 'UNKNOWN')}.")
                    try: # DEBUG ENHANCEMENT
                        full_question_text = header + str(question_text_from_data)
                        sent_message = await safe_send_message(self.bot, chat_id=chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                    except Exception as e_fallback_general_text: # DEBUG ENHANCEMENT
                         logger.error(f"Fallback to text (after general photo error) also failed for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e_fallback_general_text}", exc_info=True) # DEBUG ENHANCEMENT

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
            except telegram.error.BadRequest as e:
                logger.error(f"Failed to send text question (BadRequest) for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e}.", exc_info=True) # DEBUG ENHANCEMENT
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
                        "question_was_image": self.last_question_is_image # Pass if question was image
                    }
                )
                 logger.info(f"Question timer job '{timer_job_name}' scheduled for {self.question_time_limit}s for quiz {self.quiz_id}.")
            else:
                logger.error(f"JobQueue not available in context for quiz {self.quiz_id}. Cannot schedule question timer for user {user_id}.")
            return TAKING_QUIZ # Use TAKING_QUIZ from config
        else:
            logger.error(f"Failed to send question (q_id: {current_question_data.get('question_id', 'UNKNOWN')}, index: {self.current_question_index}) for quiz {self.quiz_id}, user {user_id}. No message object returned. Ending quiz.")
            await safe_send_message(self.bot, chat_id=chat_id, text="حدث خطأ أثناء إرسال السؤال. تم إنهاء الاختبار.")
            await self.cleanup_quiz_data(user_id, "send_question_failure")
            return END

    async def handle_answer(self, update: Update, context: CallbackContext):
        query = update.callback_query
        # await query.answer() # Answered by main handler
        user_id = query.from_user.id

        if str(user_id) != str(self.user_id):
            logger.warning(f"[QuizLogic {self.quiz_id}] Answer received from user {user_id}, but quiz belongs to {self.user_id}. Ignoring.")
            await query.answer(text="هذا الاختبار ليس لك.", show_alert=True)
            return TAKING_QUIZ # Stay in the same state

        # Check if this answer is for the current quiz_id and question_index
        # This is a basic check; more robust validation might be needed if multiple quizzes can run concurrently for a user (not typical for ConversationHandler)
        # For now, we assume context.user_data["current_quiz_logic"] points to the active quiz.

        time_taken = time.time() - self.question_start_time if self.question_start_time else -1
        
        # Remove the timer job for the current question as it's been answered
        timer_job_name = f"qtimer_{user_id}_{query.message.chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        logger.info(f"Removed timer job '{timer_job_name}' because question {self.current_question_index} was answered for quiz {self.quiz_id}.")

        # Parse callback_data: e.g., "ans_0_option1" -> question_idx=0, chosen_option_id="option1"
        try:
            _, q_idx_str, chosen_option_id_str = query.data.split("_", 2)
            q_idx_answered = int(q_idx_str)
            # chosen_option_id can be numeric string or actual string ID, handle appropriately
        except ValueError as e:
            logger.error(f"Invalid callback data format: {query.data} for quiz {self.quiz_id}. Error: {e}")
            await safe_edit_message_text(self.bot, chat_id=query.message.chat_id, message_id=query.message.message_id, text="حدث خطأ في معالجة إجابتك. يرجى المحاولة مرة أخرى أو إنهاء الاختبار.")
            return TAKING_QUIZ # Or consider ending if this is critical

        if q_idx_answered != self.current_question_index:
            logger.warning(f"Answer received for question {q_idx_answered}, but current is {self.current_question_index} for quiz {self.quiz_id}. Ignoring old/duplicate callback.")
            await query.answer(text="لقد أجبت على هذا السؤال بالفعل أو انتهى وقته.") # Inform user
            return TAKING_QUIZ

        current_question_data = self.questions_data[self.current_question_index]
        options = current_question_data.get("options", [])
        correct_option_id = current_question_data.get("correct_option_id")
        
        is_correct = False
        chosen_option_text = "غير محدد"
        correct_option_text = "غير محدد"

        # Find chosen and correct option details
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

        # Edit the question message to show feedback and remove buttons
        # If the question was an image, we need to edit the caption
        original_question_text_for_feedback = ""
        if self.last_question_is_image:
            original_question_text_for_feedback = query.message.caption if query.message.caption else f"<b>السؤال {self.current_question_index + 1}</b>"
        else:
            original_question_text_for_feedback = query.message.text if query.message.text else f"<b>السؤال {self.current_question_index + 1}</b>"
        
        # Remove the question number header if it's already there to avoid duplication
        header_to_check = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
        if original_question_text_for_feedback.startswith(header_to_check):
             text_content_for_feedback = original_question_text_for_feedback[len(header_to_check):]
        else: # If header not found, maybe it's just the question text or image caption
             text_content_for_feedback = original_question_text_for_feedback

        # Construct the feedback message, ensuring the original question text/caption is preserved
        # And then add the feedback about the answer.
        full_feedback_message = f"{header_to_check}{text_content_for_feedback}\n\nChosen: {chosen_option_text}\n{feedback_text}"

        try:
            if self.last_question_is_image and query.message.caption is not None:
                await self.bot.edit_message_caption(
                    chat_id=query.message.chat_id,
                    message_id=self.last_question_message_id, # Use the stored message_id
                    caption=full_feedback_message,
                    reply_markup=None, # Remove buttons
                    parse_mode='HTML'
                )
            elif not self.last_question_is_image and query.message.text is not None:
                await self.bot.edit_message_text(
                    text=full_feedback_message,
                    chat_id=query.message.chat_id,
                    message_id=self.last_question_message_id, # Use the stored message_id
                    reply_markup=None, # Remove buttons
                    parse_mode='HTML'
                )
            else: # Fallback if message type is unexpected or no text/caption (should not happen)
                 logger.warning(f"Could not edit message for feedback (q_idx {self.current_question_index}, quiz {self.quiz_id}) as it was neither an image with caption nor a text message as expected.")
                 await safe_send_message(self.bot, chat_id=query.message.chat_id, text=feedback_text) # Send feedback as new message

        except telegram.error.BadRequest as e:
            if "MESSAGE_NOT_MODIFIED" in str(e).upper():
                logger.info(f"Message not modified for feedback (q_idx {self.current_question_index}, quiz {self.quiz_id}): {e}")
            else:
                logger.error(f"Error editing message for feedback (q_idx {self.current_question_index}, quiz {self.quiz_id}): {e}. Feedback: {feedback_text}", exc_info=True)
                await safe_send_message(self.bot, chat_id=query.message.chat_id, text=feedback_text) # Send feedback as new message if edit fails
        except Exception as e_edit:
            logger.error(f"General error editing message for feedback (q_idx {self.current_question_index}, quiz {self.quiz_id}): {e_edit}. Feedback: {feedback_text}", exc_info=True)
            await safe_send_message(self.bot, chat_id=query.message.chat_id, text=feedback_text)

        self.current_question_index += 1
        
        # Send next question or show results after a short delay
        await asyncio.sleep(1) # Short delay before next question or results
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

        # Ensure this timeout belongs to the currently active quiz and question for this QuizLogic instance
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
            "chosen_option_id": None, # Timeout means no option chosen
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text,
            "is_correct": False,
            "time_taken": self.question_time_limit
        })

        feedback_text = f"⏰ انتهى الوقت للسؤال! الإجابة الصحيحة كانت: {correct_option_text}"
        
        # Retrieve the original question message to edit it
        # We need to fetch the message again as its content might not be in query.message for a job
        try:
            # Try to get the message from context if possible, or fetch if necessary (less ideal)
            # For now, we assume the message_id is sufficient for editing.
            original_message = await self.bot.edit_message_reply_markup( # Try removing markup first
                chat_id=chat_id,
                message_id=message_id_from_job,
                reply_markup=None
            )
            # Now edit the text/caption
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
                await safe_send_message(self.bot, chat_id=chat_id, text=feedback_text) # Send feedback as new message if edit fails
        except Exception as e_timeout_edit:
            logger.error(f"Timeout: General error editing message for feedback (q_idx {self.current_question_index}, quiz {self.quiz_id}): {e_timeout_edit}. Feedback: {feedback_text}", exc_info=True)
            await safe_send_message(self.bot, chat_id=chat_id, text=feedback_text)

        self.current_question_index += 1
        await asyncio.sleep(1) # Delay before next action
        # This will call send_question, which will either send the next or show results
        # No need to directly manage state here, send_question handles it.
        current_state_after_timeout = await self.send_question(chat_id, user_id)
        
        # If send_question returns END, it means the quiz finished. The main handler needs to know this.
        # However, jobs run outside the ConversationHandler's direct flow for returning states.
        # The state change for the user is managed by the messages sent.
        # If the quiz ends, show_results would have been called by send_question.
        # We need to ensure the ConversationHandler also transitions if needed.
        # This is tricky. For now, the user sees the end message. The handler might need an explicit /endquiz or similar if it gets stuck.
        # A better approach might be for the job to set a flag in user_data that the main handler checks on any interaction.
        if current_state_after_timeout == END:
            logger.info(f"Quiz {self.quiz_id} ended after timeout processing for user {user_id}. Main handler should eventually reflect this.")
            # The ConversationHandler itself won't immediately transition to END from a job.
            # It will transition on the *next* interaction from the user if TAKING_QUIZ handlers don't match.
            # Or if show_results sends buttons that lead to END or another state.
            pass # No direct return of state from job to handler

    async def show_results(self, chat_id: int, user_id: int, called_by_end_command=False):
        logger.info(f"Showing results for quiz {self.quiz_id}, user {user_id}. Score: {self.score}/{self.total_questions}")
        
        # Ensure any pending question timer is cancelled if results are shown prematurely (e.g. by /endquiz)
        if called_by_end_command:
            timer_job_name = f"qtimer_{user_id}_{chat_id}_{self.quiz_id}_{self.current_question_index}"
            remove_job_if_exists(timer_job_name, self.context)
            logger.info(f"Results shown by command: Removed timer job '{timer_job_name}' if it existed for quiz {self.quiz_id}.")

        result_summary = f"🏁 <b>نتائج الاختبار</b> 🏁\n\n"
        result_summary += f"✨ لقد حصلت على: <b>{self.score} من {self.total_questions}</b>\n"
        percentage = (self.score / self.total_questions) * 100 if self.total_questions > 0 else 0
        result_summary += f"🎯 النسبة المئوية: <b>{percentage:.2f}%</b>\n\n"

        if percentage >= 80:
            result_summary += "🎉 ممتاز! أداء رائع! 🎉\n"
        elif percentage >= 60:
            result_summary += "👍 جيد جداً! استمر في التقدم! 👍\n"
        elif percentage >= 40:
            result_summary += "💪 لا بأس! يمكنك فعل ما هو أفضل في المرة القادمة! 💪\n"
        else:
            result_summary += "😔 حظ أوفر في المرة القادمة. المزيد من المذاكرة قد يساعد. 😔\n"
        
        result_summary += "\n--- تفاصيل إجاباتك ---\n"
        for i, ans in enumerate(self.answers):
            q_text_short = ans.get("question_text", "سؤال غير معروف")[:50] + "..." # Shorten for summary
            chosen = ans.get("chosen_option_text", "لم يتم الاختيار")
            correct_ans_text = ans.get("correct_option_text", "غير محدد")
            status = "✅" if ans.get("is_correct") else "❌"
            if ans.get("chosen_option_id") is None: # Timeout case
                status = "⏰"
                chosen = "انتهى الوقت"
            
            result_summary += f"\n{i+1}. {q_text_short}\n   {status} إجابتك: {chosen}\n" 
            if not ans.get("is_correct") and ans.get("chosen_option_id") is not None : # Don't show correct if timeout or already correct
                result_summary += f"   الصحيحة: {correct_ans_text}\n"
        
        result_summary += "\n---------------------\n"

        keyboard = [
            [InlineKeyboardButton("بدء اختبار جديد", callback_data="quiz_menu")],
            [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # If the last interaction was a question, try to edit that message.
        # Otherwise, send a new message.
        message_to_edit_id = self.last_question_message_id if self.last_question_message_id and not called_by_end_command else None 
        
        if message_to_edit_id:
            try:
                # Determine if it was an image or text to call the correct edit method
                if self.last_question_is_image: # Check the flag for the *last sent question*
                    await self.bot.edit_message_caption(
                        chat_id=chat_id, 
                        message_id=message_to_edit_id, 
                        caption=result_summary, 
                        reply_markup=reply_markup,
                        parse_mode='HTML'
                    )
                else:
                    await self.bot.edit_message_text(
                        text=result_summary, 
                        chat_id=chat_id, 
                        message_id=message_to_edit_id, 
                        reply_markup=reply_markup,
                        parse_mode='HTML'
                    )
                logger.info(f"Results for quiz {self.quiz_id} edited into message {message_to_edit_id} for user {user_id}.")
            except telegram.error.BadRequest as e:
                if "MESSAGE_ID_INVALID" in str(e).upper() or "MESSAGE_TO_EDIT_NOT_FOUND" in str(e).upper():
                    logger.warning(f"Failed to edit message {message_to_edit_id} for results (quiz {self.quiz_id}, user {user_id}), sending as new: {e}")
                    await safe_send_message(self.bot, chat_id=chat_id, text=result_summary, reply_markup=reply_markup, parse_mode='HTML')
                elif "MESSAGE_NOT_MODIFIED" in str(e).upper():
                     logger.info(f"Results message {message_to_edit_id} not modified (quiz {self.quiz_id}, user {user_id}): {e}")
                else:
                    logger.error(f"Error editing message {message_to_edit_id} for results (quiz {self.quiz_id}, user {user_id}): {e}. Sending as new.", exc_info=True)
                    await safe_send_message(self.bot, chat_id=chat_id, text=result_summary, reply_markup=reply_markup, parse_mode='HTML')
            except Exception as e_edit_results:
                 logger.error(f"General error editing message {message_to_edit_id} for results (quiz {self.quiz_id}, user {user_id}): {e_edit_results}. Sending as new.", exc_info=True)
                 await safe_send_message(self.bot, chat_id=chat_id, text=result_summary, reply_markup=reply_markup, parse_mode='HTML')
        else:
            logger.info(f"Sending results for quiz {self.quiz_id} as a new message for user {user_id} (no last_question_message_id or called by command).")
            await safe_send_message(self.bot, chat_id=chat_id, text=result_summary, reply_markup=reply_markup, parse_mode='HTML')

        await self.cleanup_quiz_data(user_id, "quiz_completed_normally")
        # The state transition to SHOWING_RESULTS or END should be handled by the main conversation handler
        # based on the callback data from the buttons sent with the results.
        # This function itself doesn't return a state for ConversationHandler.

    async def end_quiz(self, update: Update, context: CallbackContext, manual_end: bool = False, reason: str = "ended_by_user_or_error") -> int:
        """Ends the quiz, cleans up, and shows results if applicable."""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        logger.info(f"[QuizLogic {self.quiz_id}] end_quiz called for user {user_id}. Manual: {manual_end}, Reason: {reason}")

        # Cancel any running timer for the current question
        timer_job_name = f"qtimer_{user_id}_{chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)
        logger.info(f"[QuizLogic {self.quiz_id}] Removed timer job '{timer_job_name}' during end_quiz.")

        if self.current_question_index < self.total_questions and self.total_questions > 0 and manual_end:
            # Quiz ended prematurely by user, mark remaining questions if any or add a note
            # For simplicity, we'll just note it in the log. Results will show answers up to this point.
            logger.info(f"[QuizLogic {self.quiz_id}] Quiz ended manually by user {user_id} at question {self.current_question_index + 1} of {self.total_questions}.")
            # If it was a manual /endquiz command, the main handler might send a message.
            # If QuizLogic is ending it due to an internal error, it should send a message.
            if reason not in ["quiz_completed_normally", "ended_by_user_or_error"] : # Avoid double message if main handler also sends one
                 await safe_send_message(self.bot, chat_id=chat_id, text=f"تم إنهاء الاختبار. ({reason})")
        
        # Show results based on answers collected so far
        # The show_results method now handles cleanup_quiz_data internally
        await self.show_results(chat_id, user_id, called_by_end_command=manual_end)
        
        # The main handler (quiz.py) is responsible for popping 'current_quiz_logic'
        # and other general quiz setup keys from context.user_data.
        # This QuizLogic instance will be garbage collected once no longer referenced.
        logger.info(f"[QuizLogic {self.quiz_id}] Quiz logic processing finished for user {user_id}.")
        return END # Signal to ConversationHandler to end or transition as per its fallbacks/map_to_parent

    async def cleanup_quiz_data(self, user_id, reason_for_cleanup):
        """Cleans up quiz-specific data from context.user_data that this instance managed."""
        logger.info(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user {user_id}. Reason: {reason_for_cleanup}")
        # This instance of QuizLogic might have set specific keys related to its quiz_id.
        # However, the primary 'current_quiz_logic' and broader setup keys are managed by the main handler.
        # This method is more for internal state cleanup if this instance held specific user_data keys itself.
        # For now, most quiz state is within the instance or managed by the main handler.
        # Example of a key this instance *might* have set (hypothetical):
        # self.context.user_data.pop(f"quiz_details_{self.quiz_id}", None)
        pass # No specific keys managed by QuizLogic instance in user_data currently

