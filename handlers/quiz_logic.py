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
                logger.warning(f"Option text was empty for option_id {option_id} in quiz {self.quiz_id}. Using default: \'{button_text}\"")
            elif isinstance(option_text_original, str) and (option_text_original.startswith("http://") or option_text_original.startswith("https://")):
                button_text = f"خيار {i + 1} (صورة)"
                logger.info(f"Option text for option_id {option_id} in quiz {self.quiz_id} appears to be a URL. Using placeholder: \'{button_text}\"")
            elif isinstance(option_text_original, str):
                button_text = option_text_original
            else: # Not a string, or None
                button_text = f"خيار {i + 1} (بيانات غير نصية)"
                logger.warning(f"Option text for option_id {option_id} in quiz {self.quiz_id} was not a string (type: {type(option_text_original)}). Using default: \'{button_text}\"")
            
            # Ensure button_text is a string before encoding
            button_text_str = str(button_text)
            if len(button_text_str.encode(\'utf-8\')) > 64: # Telegram's limit for button text
                # Truncate carefully to avoid splitting multi-byte characters
                temp_bytes = button_text_str.encode(\'utf-8\')[:60] # truncate bytes
                button_text = temp_bytes.decode(\'utf-8\', \'ignore\') + "..."
                logger.warning(f"Option text was too long for option_id {option_id} in quiz {self.quiz_id}. Truncated to: \'{button_text}\"")

            if not button_text_str.strip(): # Final check if button text became empty after processing
                 button_text = f"خيار {i + 1}" # Fallback if all else fails
                 logger.error(f"Critical: Button text became empty after processing for option_id {option_id}. Final fallback to: \'{button_text}\"")

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
                    current_option_proc[\'is_image_option\'] = True
                    current_option_proc[\'image_option_display_label\'] = display_label
                    option_image_counter += 1
                    await asyncio.sleep(0.2) # Small delay
                except Exception as e_img_opt:
                    logger.error(f"Failed to send image for option {i} (URL: {option_text_original}): {e_img_opt}", exc_info=True) # DEBUG ENHANCEMENT
                    current_option_proc[\'is_image_option\'] = False # Mark as not sent
            processed_options.append(current_option_proc)
        
        # IMPORTANT ADDITION: Update current_question_data with processed options so handle_answer and timeout can use them
        current_question_data[\'options\'] = processed_options
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
                logger.error(f"Failed to send photo (BadRequest) for q_id {current_question_data.get(\'question_id\', \'UNKNOWN\')}: {e}. URL: {image_url}", exc_info=True) # DEBUG ENHANCEMENT
                if "BUTTON_TEXT_EMPTY" in str(e).upper() or "TEXT IS EMPTY" in str(e).upper():
                    logger.error(f"Error sending photo for q_id {current_question_data.get(\'question_id\', \'UNKNOWN\')} was due to empty button text. This should have been caught by create_options_keyboard.")
                
                if question_text_from_data: # Fallback to text if photo fails
                    logger.info(f"Photo send failed for q_id {current_question_data.get(\'question_id\', \'UNKNOWN\')}, attempting to send as text.")
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
                        logger.error(f"Fallback to text also failed for q_id {current_question_data.get(\'question_id\', \'UNKNOWN\')}: {e_fallback_text}", exc_info=True) # DEBUG ENHANCEMENT
                else:
                    logger.error(f"Photo send failed for q_id {current_question_data.get(\'question_id\', \'UNKNOWN\')} and no fallback text available.")
            except Exception as e:
                logger.error(f"Unexpected error sending photo for q_id {current_question_data.get(\'question_id\', \'UNKNOWN\')}: {e}. URL: {image_url}", exc_info=True)
                # ADDED: Fallback from original if general error and text exists (was missing in one version)
                if question_text_from_data: 
                    logger.info(f"Photo send failed (general error), sending as text for q_id {current_question_data.get(\'question_id\', \'UNKNOWN\')}.")
                    try: # DEBUG ENHANCEMENT
                        full_question_text = header + str(question_text_from_data)
                        sent_message = await safe_send_message(self.bot, chat_id=chat_id, text=full_question_text, reply_markup=options_keyboard, parse_mode="HTML")
                    except Exception as e_fallback_general_text: # DEBUG ENHANCEMENT
                         logger.error(f"Fallback to text (after general photo error) also failed for q_id {current_question_data.get(\'question_id\', \'UNKNOWN\')}: {e_fallback_general_text}", exc_info=True) # DEBUG ENHANCEMENT

        else: # Text question
            question_text_main = str(question_text_from_data if question_text_from_data is not None else "")
            if not question_text_from_data:
                logger.warning(f"Question text is None/empty for TEXT q_id: {current_question_data.get(\'question_id\', \'UNKNOWN\')}. Sending header or minimal text.")

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
                logger.error(f"Failed to send text question (BadRequest) for q_id {current_question_data.get(\'question_id\', \'UNKNOWN\')}: {e}.", exc_info=True) # DEBUG ENHANCEMENT
                if "BUTTON_TEXT_EMPTY" in str(e).upper() or "TEXT IS EMPTY" in str(e).upper():
                    logger.error(f"Error sending text question for q_id {current_question_data.get(\'question_id\', \'UNKNOWN\')} was due to empty button text. This should have been caught by create_options_keyboard.")
            except Exception as e:
                 logger.error(f"Unexpected error sending text question for q_id {current_question_data.get(\'question_id\', \'UNKNOWN\')}: {e}.", exc_info=True)


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
            return TAKING_QUIZ # Return TAKING_QUIZ to stay in the quiz state
        else:
            # DEBUG ENHANCEMENT: More detailed critical failure message and logging
            logger.error(f"CRITICAL FAILURE IN SEND_QUESTION: \'sent_message\' is None for q_idx {self.current_question_index}, quiz {self.quiz_id}, user {user_id}. This means all attempts to send the question (image or text) failed. Please review preceding log entries for specific exceptions (e.g., from send_photo, safe_send_message, or option image processing). Data for current question: {current_question_data}", exc_info=True)
            try:
                await safe_send_message(self.bot, chat_id, "عذراً، حدث خطأ فادح أثناء محاولة إرسال السؤال. تم تسجيل تفاصيل الخطأ. سيتم إنهاء الاختبار. يرجى المحاولة لاحقاً.")
            except Exception as e_msg_err:
                logger.error(f"Failed to send the CRITICAL FAILURE message to user {user_id}: {e_msg_err}")
            # Clear quiz state from user_data to allow starting a new quiz
            user_data = self.context.user_data
            if \'current_quiz_logic\' in user_data:
                del user_data[\'current_quiz_logic\']
            return END # End the conversation if question sending fails critically

    async def handle_answer(self, update: Update, callback_data: str):
        query = update.callback_query # If called from callback query
        chat_id = query.message.chat_id
        user_id = query.from_user.id
        message_id_to_edit = query.message.message_id

        # Stop the timer for the current question
        timer_job_name = f"qtimer_{user_id}_{chat_id}_{self.quiz_id}_{self.current_question_index}"
        remove_job_if_exists(timer_job_name, self.context)

        parts = callback_data.split("_")
        question_idx_answered = int(parts[1])
        selected_option_id = parts[2] # This is the ID from the database/API

        if question_idx_answered != self.current_question_index:
            logger.warning(f"User {user_id} answered question {question_idx_answered} but current is {self.current_question_index}. Ignoring.")
            await query.answer("إجابة لسؤال قديم، تم تجاهلها.")
            return TAKING_QUIZ # Stay in the current state

        current_question_data = self.questions_data[self.current_question_index]
        options = current_question_data.get("options", [])
        selected_option_data = None
        correct_option_data = None

        for opt in options:
            # Compare with string representation of option_id from data
            if str(opt.get("option_id")) == str(selected_option_id):
                selected_option_data = opt
            if opt.get("is_correct"): # Assuming boolean or truthy value
                correct_option_data = opt
        
        is_correct = False
        if selected_option_data and selected_option_data.get("is_correct"):
            self.score += 1
            is_correct = True
        
        time_taken = time.time() - self.question_start_time if self.question_start_time else 0

        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": current_question_data.get("question_text", "N/A"),
            "selected_option_id": selected_option_id,
            "selected_option_text": selected_option_data.get("option_text", "N/A") if selected_option_data else "N/A",
            "is_correct": is_correct,
            "correct_option_id": correct_option_data.get("option_id", "N/A") if correct_option_data else "N/A",
            "correct_option_text": correct_option_data.get("option_text", "N/A") if correct_option_data else "N/A",
            "time_taken": time_taken
        })

        # Edit the last question message to show feedback (e.g., remove keyboard or show correct answer)
        feedback_text = "إجابتك: " + (selected_option_data.get("option_text", "غير محدد") if selected_option_data else "غير محدد")
        feedback_text += " ✅" if is_correct else " ❌"
        
        # If the question was an image, we edit the caption of that image message.
        # If it was text, we edit the text message.
        # The options keyboard should be removed.
        try:
            if self.last_question_is_image and self.last_question_message_id:
                 await self.bot.edit_message_caption(chat_id=chat_id, message_id=self.last_question_message_id, caption=feedback_text, reply_markup=None)
            elif self.last_question_message_id: # Text question
                 await self.bot.edit_message_text(text=feedback_text, chat_id=chat_id, message_id=self.last_question_message_id, reply_markup=None)
            await query.answer("تم تسجيل إجابتك!") # Acknowledge the button press
        except telegram.error.BadRequest as e_edit:
            if "MESSAGE_NOT_MODIFIED" in str(e_edit).upper():
                logger.info(f"Message not modified for feedback (q_idx {self.current_question_index}), likely already edited or no change.")
                await query.answer("تم تسجيل إجابتك!") # Still acknowledge
            else:
                logger.error(f"Error editing message for feedback (q_idx {self.current_question_index}): {e_edit}")
                await query.answer("خطأ بسيط، تم تسجيل إجابتك.") # Acknowledge with error hint
        except Exception as e_edit_gen:
            logger.error(f"Unexpected error editing message for feedback (q_idx {self.current_question_index}): {e_edit_gen}")
            await query.answer("خطأ، تم تسجيل إجابتك.")

        self.current_question_index += 1
        return await self.send_question(chat_id, user_id)

    async def question_timeout_callback(self, context: CallbackContext):
        job_data = context.job.data
        quiz_id_from_job = job_data.get("quiz_id")
        question_idx_from_job = job_data.get("question_index")
        user_id_from_job = job_data.get("user_id")
        chat_id_from_job = job_data.get("chat_id")
        message_id_to_edit = job_data.get("message_id")
        question_was_image = job_data.get("question_was_image", False)

        # Verify this timeout belongs to the current active question of this QuizLogic instance
        if self.quiz_id != quiz_id_from_job or self.current_question_index != question_idx_from_job or self.user_id != user_id_from_job:
            logger.info(f"Stale timeout job executed for quiz {quiz_id_from_job}, q_idx {question_idx_from_job}, user {user_id_from_job}. Current state: quiz {self.quiz_id}, q_idx {self.current_question_index}. Ignoring.")
            return

        logger.info(f"Timeout for user {self.user_id}, quiz {self.quiz_id}, question {self.current_question_index + 1}")
        
        current_question_data = self.questions_data[self.current_question_index]
        correct_option_data = next((opt for opt in current_question_data.get("options", []) if opt.get("is_correct")), None)

        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": current_question_data.get("question_text", "N/A"),
            "selected_option_id": "TIMEOUT",
            "selected_option_text": "انتهى الوقت",
            "is_correct": False,
            "correct_option_id": correct_option_data.get("option_id", "N/A") if correct_option_data else "N/A",
            "correct_option_text": correct_option_data.get("option_text", "N/A") if correct_option_data else "N/A",
            "time_taken": self.question_time_limit
        })

        timeout_message = "انتهى الوقت للسؤال الحالي! ⌛"
        try:
            if question_was_image and message_id_to_edit:
                await self.bot.edit_message_caption(chat_id=chat_id_from_job, message_id=message_id_to_edit, caption=timeout_message, reply_markup=None)
            elif message_id_to_edit: # Text question
                await self.bot.edit_message_text(text=timeout_message, chat_id=chat_id_from_job, message_id=message_id_to_edit, reply_markup=None)
        except telegram.error.BadRequest as e_edit_timeout:
            if "MESSAGE_NOT_MODIFIED" not in str(e_edit_timeout).upper():
                 logger.error(f"Error editing message on timeout: {e_edit_timeout}")
        except Exception as e_edit_timeout_gen:
            logger.error(f"Unexpected error editing message on timeout: {e_edit_timeout_gen}")

        self.current_question_index += 1
        # Need to call send_question within an async context, which this callback is.
        # The state transition is handled by what send_question returns.
        # We don\'t have \'update\' here, but send_question doesn\'t strictly need it if it\'s only for query.message.chat_id etc.
        # which we have from job_data.
        next_state = await self.send_question(chat_id_from_job, user_id_from_job)
        
        # If send_question returns END, we need to ensure the conversation handler is properly ended.
        # This is tricky as this callback is not directly part of the ConversationHandler flow.
        # The ConversationHandler might not know the state changed to END here.
        # For now, QuizLogic itself will manage its state. The ConversationHandler in quiz.py
        # will eventually timeout or be ended by user action if this path leads to END.
        if next_state == END:
            logger.info(f"Quiz {self.quiz_id} ended via timeout path for user {user_id_from_job}.")
            # Potentially clean up user_data if QuizLogic is responsible for it
            if \'current_quiz_logic\' in self.context.user_data and self.context.user_data[\'current_quiz_logic\'] is self:
                del self.context.user_data[\'current_quiz_logic\']
                logger.debug(f"Cleaned up current_quiz_logic from user_data for user {user_id_from_job} after quiz end via timeout.")

    async def show_results(self, chat_id: int, user_id: int):
        logger.info(f"Showing results for quiz {self.quiz_id}, user {user_id}. Score: {self.score}/{self.total_questions}")
        results_text = f"🎉 *نتائج الاختبار* 🎉\n\n"
        results_text += f"المستخدم: {user_id}\n"
        results_text += f"نوع الاختبار: {self.quiz_type}\n"
        results_text += f"النتيجة: {self.score} من {self.total_questions}\n\n"
        results_text += "*تفاصيل الإجابات:*
"
        for i, ans in enumerate(self.answers):
            q_text = ans.get("question_text", f"سؤال {i+1}")
            sel_text = ans.get("selected_option_text", "لم يتم الاختيار")
            corr_text = ans.get("correct_option_text", "غير محدد")
            status = "✅ صحيح" if ans.get("is_correct") else ("⌛ انتهى الوقت" if ans.get("selected_option_id") == "TIMEOUT" else "❌ خطأ")
            results_text += f"\n*{q_text[:50]}...*
إجابتك: {sel_text[:50]}... ({status})
" 
            if not ans.get("is_correct") and ans.get("selected_option_id") != "TIMEOUT":
                results_text += f"الإجابة الصحيحة: {corr_text[:50]}...
"

        # Clean up the quiz instance from user_data
        if \'current_quiz_logic\' in self.context.user_data and self.context.user_data[\'current_quiz_logic\'] is self:
            del self.context.user_data[\'current_quiz_logic\']
            logger.debug(f"Cleaned up current_quiz_logic from user_data for user {user_id} after showing results.")
        
        # Ensure any lingering timers for this quiz are stopped.
        # This is a safeguard; timers should be stopped per question.
        for i in range(self.total_questions):
            timer_job_name = f"qtimer_{user_id}_{chat_id}_{self.quiz_id}_{i}"
            remove_job_if_exists(timer_job_name, self.context)

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu_from_quiz_results")
        ]])
        try:
            # If the last interaction was an edit (e.g. feedback on last answer), we might need to send a new message for results.
            # Or, if called from send_question when quiz ends, it might edit the last question message.
            # For simplicity, let\'s assume we always send a new message for results to avoid complex message_id tracking here.
            await safe_send_message(self.bot, chat_id, results_text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e_results:
            logger.error(f"Failed to send quiz results for quiz {self.quiz_id} to user {user_id}: {e_results}")
            await safe_send_message(self.bot, chat_id, "حدث خطأ أثناء عرض النتائج. نتيجتك هي {self.score}/{self.total_questions}.")

    def get_final_results_text_and_markup(self):
        # This method can be called by the quiz handler if it needs to display results again
        results_text = f"🎉 *نتائج الاختبار (معادة)* 🎉\n\n"
        results_text += f"المستخدم: {self.user_id}\n"
        results_text += f"نوع الاختبار: {self.quiz_type}\n"
        results_text += f"النتيجة: {self.score} من {self.total_questions}\n\n"
        results_text += "*تفاصيل الإجابات:*
"
        for i, ans in enumerate(self.answers):
            q_text = ans.get("question_text", f"سؤال {i+1}")
            sel_text = ans.get("selected_option_text", "لم يتم الاختيار")
            corr_text = ans.get("correct_option_text", "غير محدد")
            status = "✅ صحيح" if ans.get("is_correct") else ("⌛ انتهى الوقت" if ans.get("selected_option_id") == "TIMEOUT" else "❌ خطأ")
            results_text += f"\n*{q_text[:50]}...*
إجابتك: {sel_text[:50]}... ({status})
" 
            if not ans.get("is_correct") and ans.get("selected_option_id") != "TIMEOUT":
                results_text += f"الإجابة الصحيحة: {corr_text[:50]}...
"
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu_from_quiz_results")
        ]])
        return results_text, keyboard

