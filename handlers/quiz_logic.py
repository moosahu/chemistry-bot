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
            elif isinstance(option_text_original, str) and (option_text_original.startswith("http://") or option_text_original.startswith("https://")):
                button_text = f"خيار {i + 1} (صورة)"
                logger.info(f"Option text for option_id {option_id} in quiz {self.quiz_id} appears to be a URL. Using placeholder: '{button_text}'")
            elif isinstance(option_text_original, str):
                button_text = option_text_original
            else: # Not a string, or None
                button_text = f"خيار {i + 1} (بيانات غير نصية)"
                logger.warning(f"Option text for option_id {option_id} in quiz {self.quiz_id} was not a string (type: {type(option_text_original)}). Using default: '{button_text}'")
            
            # Ensure button_text is a string before encoding
            button_text_str = str(button_text)
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
                           (option_text_original.startswith("http://") or option_text_original.startswith("https://")) and \
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
                 logger.info(f"Question timer ({self.question_time_limit}s) started for q:{self.current_question_index} quiz:{self.quiz_id} user:{user_id} (Job: {timer_job_name})")
            else:
                logger.error(f"JobQueue not found in context for quiz {self.quiz_id}, user {user_id}. Timer not started.")
        else:
            # DEBUG ENHANCEMENT: More detailed critical failure message and logging
            logger.error(f"CRITICAL FAILURE IN SEND_QUESTION: 'sent_message' is None for q_idx {self.current_question_index}, quiz {self.quiz_id}, user {user_id}. This means all attempts to send the question (image or text) failed. Please review preceding log entries for specific exceptions (e.g., from send_photo, safe_send_message, or option image processing). Data for current question: {current_question_data}", exc_info=True)
            try:
                await safe_send_message(self.bot, chat_id, "عذراً، حدث خطأ فادح أثناء محاولة إرسال السؤال. تم تسجيل تفاصيل الخطأ. سيتم إنهاء الاختبار. يرجى المحاولة لاحقاً.")
            except Exception as e_msg_err:
                logger.error(f"Failed to send the CRITICAL FAILURE message to user {user_id}: {e_msg_err}")
            # Clear quiz state from user_data to allow starting a new quiz
            user_data = self.context.user_data
            if user_data:
                user_data.pop('current_quiz_logic', None)
                user_data.pop('quiz_type', None)
                user_data.pop('quiz_scope', None)
                user_data.pop('question_count', None)
                logger.info(f"Cleared quiz-related user_data for user {user_id} after CRITICAL send_question failure.")
            return END # Use END from config

    async def handle_answer(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer() # Acknowledge callback query
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        
        # Ensure quiz_id is set, otherwise this instance is not properly initialized for this user
        if not hasattr(self, 'quiz_id') or not self.quiz_id:
            logger.warning(f"handle_answer called for user {user_id} but quiz_id is not set in QuizLogic instance. Current quiz index: {self.current_question_index}. Ignoring.")
            # Optionally, send a message to the user if this state is unexpected
            # await safe_send_message(self.bot, chat_id, "حدث خطأ ما، يرجى محاولة بدء اختبار جديد.")
            return

        timer_job_name = f"qtimer_{user_id}_{chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, context)

        try:
            _, question_idx_str, option_id_str = query.data.split("_")
            question_idx = int(question_idx_str)
        except ValueError:
            logger.error(f"Error parsing callback_data: {query.data} for quiz {self.quiz_id}", exc_info=True) # DEBUG ENHANCEMENT
            await safe_send_message(self.bot, chat_id, "حدث خطأ في معالجة إجابتك. يرجى المحاولة مرة أخرى.")
            return

        # Check if the answer is for the current question
        if question_idx != self.current_question_index:
            logger.warning(f"Received answer for q_idx {question_idx} but current is {self.current_question_index} for quiz {self.quiz_id}. Ignoring.")
            # await safe_send_message(self.bot, chat_id, "لقد استلمت إجابة لسؤال سابق. يتم عرض السؤال الحالي.") # Avoid spamming user
            return

        current_question_data = self.questions_data[self.current_question_index]
        selected_option_id_str = option_id_str # This is the ID from the button callback
        is_correct = False
        selected_option_text_for_display = "غير محدد"
        # ADDED: Flag for storing if the original selected option was an image URL (for self.answers)
        original_selected_option_text_is_url = False

        # Find the selected option and determine if it's correct
        # MODIFIED: Iterate through processed_options (which has 'is_image_option' and 'image_option_display_label')
        # This requires that processed_options is available here or that the original options list is augmented similarly.
        # For simplicity, we'll re-check based on original options and the 'is_image_option' flag from current_question_data's options if it was set by send_question.
        # A cleaner way would be to pass processed_options or ensure current_question_data.options is the processed list.
        # Assuming current_question_data.get("options") now contains the processed options with 'is_image_option' and 'image_option_display_label'
        
        options_list_for_answer_check = current_question_data.get("options", []) # This should be the processed list if send_question modified it in place, or we need to access processed_options if it was stored in self.
        # To ensure this works, let's assume `send_question` updates `self.questions_data[self.current_question_index]["options"]` to be `processed_options` or we fetch `processed_options` if stored in `self`.
        # For this iteration, we will assume `current_question_data.get("options")` has the necessary flags if they were added.
        # The most robust way is to ensure `self.questions_data[self.current_question_index]["options"]` becomes `processed_options` in `send_question`.
        # Let's refine `send_question` to update `self.questions_data[self.current_question_index]['options'] = processed_options`

        for opt_idx, opt in enumerate(options_list_for_answer_check): # Use the (potentially) processed options list
            if str(opt.get("option_id", -1)) == selected_option_id_str:
                is_correct = opt.get("is_correct", False)
                original_opt_text = opt.get("option_text", "")
                
                # ADDED: Determine display text for feedback, considering pre-sent images
                if opt.get("is_image_option"):
                    selected_option_text_for_display = opt.get("image_option_display_label", f"خيار {opt_idx + 1}") # Use the letter/fallback
                    original_selected_option_text_is_url = True 
                # ORIGINAL LOGIC (KEPT AS IS)
                elif isinstance(original_opt_text, str) and (original_opt_text.startswith("http://") or original_opt_text.startswith("https://")) and original_opt_text.strip():
                    selected_option_text_for_display = f"خيار {opt_idx + 1} (صورة)" 
                    original_selected_option_text_is_url = True # Also a URL
                elif isinstance(original_opt_text, str) and not original_opt_text.strip():
                    selected_option_text_for_display = f"خيار {opt_idx + 1}"
                elif isinstance(original_opt_text, str):
                    selected_option_text_for_display = original_opt_text
                else: # Not a string or None
                    selected_option_text_for_display = f"خيار {opt_idx + 1} (بيانات غير نصية)"
                break
        
        time_taken = time.time() - self.question_start_time

        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": current_question_data.get("question_text", "N/A"),
            "selected_option_id": selected_option_id_str,
            "selected_option_text": selected_option_text_for_display, # Use the processed text for display
            "is_correct": is_correct,
            "time_taken": time_taken,
            # ADDED: Store if original was URL (image or not)
            "original_selected_option_text_is_url": original_selected_option_text_is_url
        })

        if is_correct:
            self.score += 1
            feedback_text = "✅ إجابة صحيحة!"
        else:
            feedback_text = "❌ إجابة خاطئة."
        
        header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
        q_text_from_data = current_question_data.get("question_text")
        
        original_question_content_for_feedback = str(q_text_from_data if q_text_from_data is not None else "")
        if self.last_question_is_image and not q_text_from_data: # If it was an image question and had no specific text
             original_question_content_for_feedback = "" # Avoids repeating 'None' or empty string
        
        feedback_part = f"\n\n<i>إجابتك: {selected_option_text_for_display}</i>\n<b>{feedback_text}</b>"

        # MODIFIED: Display correct answer if wrong, considering image options
        if not is_correct:
            correct_answer_text = ""
            # Iterate through the same options list used for checking the answer
            for opt_correct in options_list_for_answer_check:
                if opt_correct.get("is_correct"):
                    if opt_correct.get("is_image_option"):
                        correct_answer_text = opt_correct.get("image_option_display_label", "الخيار المصور الصحيح")
                    elif isinstance(opt_correct.get("option_text"), str) and opt_correct.get("option_text").strip():
                        correct_answer_text = opt_correct.get("option_text")
                    else:
                        correct_answer_text = f"الخيار الصحيح (بيانات غير نصية أو صورة لم ترسل)"
                    break
            if correct_answer_text:
                feedback_part += f"\n<i>الإجابة الصحيحة: {correct_answer_text}</i>"

        if self.last_question_is_image:
            final_caption = header + original_question_content_for_feedback + feedback_part
            await safe_edit_message_text(bot=self.bot, chat_id=chat_id, message_id=self.last_question_message_id, text=final_caption, reply_markup=None, parse_mode="HTML", is_caption=True)
        else:
            final_text = header + original_question_content_for_feedback + feedback_part
            await safe_edit_message_text(bot=self.bot, chat_id=chat_id, message_id=self.last_question_message_id, text=final_text, reply_markup=None, parse_mode="HTML")

        self.current_question_index += 1
        # ADDED: Small delay (good practice)
        await asyncio.sleep(1.5) 
        await self.send_question(chat_id, user_id)

    async def question_timeout_callback(self, context: CallbackContext):
        job_data = context.job.data
        quiz_id_from_job = job_data["quiz_id"]
        question_idx = job_data["question_index"]
        user_id = job_data["user_id"]
        chat_id = job_data["chat_id"]
        message_id = job_data["message_id"]
        question_was_image = job_data.get("question_was_image", False)

        # Ensure quiz_id is set, otherwise this instance is not properly initialized for this user
        if not hasattr(self, 'quiz_id') or self.quiz_id != quiz_id_from_job:
            logger.warning(f"Timeout for quiz {quiz_id_from_job}, q_idx {question_idx} but current quiz is {getattr(self, 'quiz_id', 'None')}. User {user_id}. Sending message.")
            await safe_send_message(self.bot, chat_id, "انتهى وقت هذا السؤال، وربما تم إيقاف الاختبار أو بدء اختبار جديد.")
            return

        if question_idx != self.current_question_index:
            logger.warning(f"Timeout for q_idx {question_idx} but current is {self.current_question_index}. Quiz {self.quiz_id}. Ignoring.")
            return

        logger.info(f"Question {question_idx} timed out for user {user_id}, quiz {self.quiz_id}.")
        current_question_data = self.questions_data[question_idx]
        
        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": current_question_data.get("question_text", "N/A"),
            "selected_option_id": None,
            "selected_option_text": "مهلة",
            "is_correct": False,
            "time_taken": self.question_time_limit,
            "original_selected_option_text_is_url": False # Unlikely to be URL on timeout, but kept for consistency
        })

        feedback_text = "⌛️ انتهى الوقت!"
        correct_answer_text_on_timeout = ""
        # Use the same options list that would have been used for answering (i.e., potentially processed)
        options_list_for_timeout_check = current_question_data.get("options", [])

        for opt_timeout in options_list_for_timeout_check:
            if opt_timeout.get("is_correct"):
                if opt_timeout.get("is_image_option"):
                    correct_answer_text_on_timeout = opt_timeout.get("image_option_display_label", "الخيار المصور الصحيح")
                elif isinstance(opt_timeout.get("option_text"), str) and opt_timeout.get("option_text").strip():
                    correct_answer_text_on_timeout = opt_timeout.get("option_text")
                else:
                    correct_answer_text_on_timeout = f"الخيار الصحيح (بيانات غير نصية أو صورة لم ترسل)"
                break
        if correct_answer_text_on_timeout:
            feedback_text += f"\n<i>الإجابة الصحيحة: {correct_answer_text_on_timeout}</i>"

        header = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
        q_text_from_data = current_question_data.get("question_text")
        
        original_question_content_for_feedback = str(q_text_from_data if q_text_from_data is not None else "")
        if question_was_image and not q_text_from_data: # If it was an image question and had no specific text
             original_question_content_for_feedback = ""

        final_feedback_message = header + original_question_content_for_feedback + "\n\n" + feedback_text

        if question_was_image:
            await safe_edit_message_text(bot=self.bot, chat_id=chat_id, message_id=message_id, text=final_feedback_message, reply_markup=None, parse_mode="HTML", is_caption=True)
        else:
            await safe_edit_message_text(bot=self.bot, chat_id=chat_id, message_id=message_id, text=final_feedback_message, reply_markup=None, parse_mode="HTML")

        self.current_question_index += 1
        # ADDED: Small delay (good practice)
        await asyncio.sleep(1.5) 
        await self.send_question(chat_id, user_id)

    async def show_results(self, chat_id: int, user_id: int):
        logger.info(f"Showing results for quiz {self.quiz_id} to user {user_id}. Score: {self.score}/{self.total_questions}")
        if self.total_questions == 0:
            results_text = "لم يتم العثور على أسئلة لهذا الاختبار."
        else:
            percentage = (self.score / self.total_questions) * 100 if self.total_questions > 0 else 0
            results_text = f"🎉 **نتائج الاختبار** 🎉\n\n"
            results_text += f"✨ لقد أكملت الاختبار بنجاح! ✨\n"
            results_text += f"🔢 إجمالي الأسئلة: {self.total_questions}\n"
            results_text += f"✅ الإجابات الصحيحة: {self.score}\n"
            results_text += f"❌ الإجابات الخاطئة: {self.total_questions - self.score}\n"
            results_text += f"📊 النسبة المئوية: {percentage:.2f}%\n\n"
            
            if percentage >= 80:
                results_text += "🥳 ممتاز! أداء رائع!"
            elif percentage >= 60:
                results_text += "👍 جيد جداً! استمر في التقدم!"
            elif percentage >= 40:
                results_text += "😐 لا بأس، يمكنك التحسن في المرة القادمة."
            else:
                results_text += "😔 حظ أوفر في المرة القادمة. حاول مرة أخرى!"

        await safe_send_message(self.bot, chat_id, results_text, parse_mode="Markdown")
        
        # Clear quiz state from user_data to allow starting a new quiz
        user_data = self.context.user_data
        if user_data:
            user_data.pop('current_quiz_logic', None)
            user_data.pop('quiz_type', None)
            user_data.pop('quiz_scope', None) # Ensure this is cleared if it was set
            user_data.pop('question_count', None)
            logger.info(f"Cleared quiz-related user_data for user {user_id} after showing results.")

