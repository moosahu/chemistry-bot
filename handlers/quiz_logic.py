import inspect


# -*- coding: utf-8 -*-
# handlers/quiz_logic.py (v33 - Added is_finished method)
import inspect
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
        caller_frame = inspect.currentframe().f_back
        caller_function_name = caller_frame.f_code.co_name
        caller_lineno = caller_frame.f_lineno
        logger.info(f"[QuizLogic {self.quiz_id}] send_question CALLED for user {user_id}, q_idx {self.current_question_index}. Called from: {caller_function_name} at line {caller_lineno}")

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
            # New parsing logic
            temp_parts = query.data.split("_", 1)
            if len(temp_parts) < 2 or not temp_parts[0] == "ans":
                logger.error(f"[QuizLogic {self.quiz_id}] Invalid callback prefix or structure: {query.data}. temp_parts: {temp_parts}")
                raise ValueError("Callback data format error - prefix")
            
            rest_of_data = temp_parts[1]
            quiz_id_parts = rest_of_data.rsplit("_", 2)

            if len(quiz_id_parts) < 3:
                logger.error(f"[QuizLogic {self.quiz_id}] Invalid callback structure after prefix: {rest_of_data}. quiz_id_parts: {quiz_id_parts}")
                raise ValueError("Callback data format error - suffix")

            cb_quiz_id = quiz_id_parts[0]
            cb_q_idx_str = quiz_id_parts[1]
            cb_chosen_option_id_str = quiz_id_parts[2]
            # End of new parsing logic
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
        chosen_option_id = str(cb_chosen_option_id_str)
        is_correct = (chosen_option_id == correct_option_id)

        chosen_option_text = "غير محدد"
        correct_option_text = "غير محدد"
        options_for_lookup = current_question_data.get("options", []) 
        for opt in options_for_lookup:
            opt_id_str = str(opt.get("option_id"))
            if opt_id_str == chosen_option_id:
                if opt.get("is_image_option"):
                    chosen_option_text = f"الخيار المصور: {opt.get('image_option_display_label', 'غير مسمى')}"
                else:
                    chosen_option_text = opt.get("option_text", "نص الخيار المختار غير متوفر")
            if opt_id_str == correct_option_id:
                if opt.get("is_image_option"):
                    correct_option_text = f"الخيار المصور: {opt.get('image_option_display_label', 'غير مسمى')}"
                else:
                    correct_option_text = opt.get("option_text", "نص الخيار الصحيح غير متوفر")

        if is_correct:
            self.score += 1
            feedback_text = "<emoji document_id=\"5373103086790313136\">✅</emoji> <b>إجابة صحيحة!</b>"
        else:
            feedback_text = f"<emoji document_id=\"5373103086790313136\">❌</emoji> <b>إجابة خاطئة.</b> الإجابة الصحيحة: {correct_option_text}"
        
        self.answers.append({
            "question_id": current_question_data.get("question_id", f"q_idx_{self.current_question_index}"),
            "question_text": q_text_for_ans,
            "chosen_option_id": chosen_option_id,
            "chosen_option_text": chosen_option_text,
            "correct_option_id": correct_option_id,
            "correct_option_text": correct_option_text,
            "is_correct": is_correct,
            "time_taken": round(time_taken, 2)
        })

        message_id_to_edit = self.last_question_message_id
        if query.message and query.message.message_id:
            message_id_to_edit = query.message.message_id
        
        if message_id_to_edit:
            original_caption = ""
            if self.last_question_is_image and query.message and query.message.caption:
                original_caption = query.message.caption + "\n\n"
            elif not self.last_question_is_image and query.message and query.message.text:
                original_caption = query.message.text + "\n\n"
            else: # Fallback if original text/caption is somehow lost or not accessible
                original_caption = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n{q_text_for_ans}\n\n"

            new_text_or_caption = original_caption + feedback_text
            
            try:
                if self.last_question_is_image:
                    await bot.edit_message_caption(chat_id=query.message.chat_id, message_id=message_id_to_edit, caption=new_text_or_caption, reply_markup=None, parse_mode='HTML')
                else:
                    await bot.edit_message_text(text=new_text_or_caption, chat_id=query.message.chat_id, message_id=message_id_to_edit, reply_markup=None, parse_mode='HTML')
                logger.debug(f"[QuizLogic {self.quiz_id}] Edited message {message_id_to_edit} with feedback.")
            except telegram.error.BadRequest as e:
                if "message is not modified" in str(e).lower():
                    logger.warning(f"[QuizLogic {self.quiz_id}] Message {message_id_to_edit} not modified: {e}. This might happen with rapid answers.")
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Error editing message {message_id_to_edit}: {e}", exc_info=True)
                    # Attempt to send feedback as a new message if edit fails for other reasons
                    await safe_send_message(bot, chat_id=query.message.chat_id, text=feedback_text, parse_mode='HTML')
            except Exception as e_edit:
                logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message {message_id_to_edit}: {e_edit}", exc_info=True)
                await safe_send_message(bot, chat_id=query.message.chat_id, text=feedback_text, parse_mode='HTML')
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] No message_id_to_edit found. Sending feedback as new message.")
            await safe_send_message(bot, chat_id=query.message.chat_id, text=feedback_text, parse_mode='HTML')

        self.current_question_index += 1
        if self.current_question_index < self.total_questions:
            await asyncio.sleep(1) # Short delay before sending next question
            return await self.send_question(bot, context, user_id) # Removed chat_id from here
        else:
            return await self.show_results(bot, context, user_id) # Removed chat_id from here

    async def show_results(self, bot: Bot, context: CallbackContext, user_id: int): # Removed chat_id from here
        logger.info(f"[QuizLogic {self.quiz_id}] Showing results for user {user_id}, chat {self.chat_id}. Score: {self.score}/{self.total_questions}")
        if not self.active and not self.answers: # Quiz was never really active or no answers recorded
             logger.warning(f"[QuizLogic {self.quiz_id}] show_results called but quiz seems inactive or has no answers. User {user_id}")
             # Optionally send a message that results cannot be shown or quiz was not completed.
             # For now, just clean up and return END.
             await self.cleanup_quiz_data(context, user_id, "show_results_inactive_no_answers")
             return END

        results_text = f"<emoji document_id=\"5373103086790313136\">🎉</emoji> <b>نتائج الاختبار ({self.quiz_name}):</b>\n"
        results_text += f"<emoji document_id=\"5373103086790313136\">🎯</emoji> نتيجتك: {self.score} من {self.total_questions}\n\n"
        results_text += "<b>تفاصيل الإجابات:</b>\n"
        for i, ans in enumerate(self.answers):
            q_num = i + 1
            status_emoji = "<emoji document_id=\"5373103086790313136\">✅</emoji>" if ans["is_correct"] else "<emoji document_id=\"5373103086790313136\">❌</emoji>"
            q_text_short = ans.get("question_text", "سؤال غير معروف")
            if len(q_text_short) > 50: q_text_short = q_text_short[:47] + "..."
            results_text += f"{q_num}. {status_emoji} {q_text_short} (اخترت: {ans.get('chosen_option_text', 'لم تختر')})\n"
            if not ans["is_correct"]:
                results_text += f"   <emoji document_id=\"5373103086790313136\">💡</emoji> الصحيحة: {ans.get('correct_option_text', 'غير محددة')}\n"
        
        results_text += "\nشكراً لك على المشاركة!"

        keyboard = [[InlineKeyboardButton("ابدأ اختباراً جديداً", callback_data="start_new_quiz"),
                     InlineKeyboardButton("القائمة الرئيسية", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Try to edit the last question message if it exists, otherwise send a new one.
        last_msg_id_to_use = self.last_question_message_id
        if context.user_data.get(f"quiz_last_feedback_message_id_{self.quiz_id}"):
             last_msg_id_to_use = context.user_data.get(f"quiz_last_feedback_message_id_{self.quiz_id}")

        if last_msg_id_to_use:
            try:
                # Determine if the last message was an image to use edit_message_caption or edit_message_text
                # This is a bit tricky as we don't store if the *feedback* message itself was an image.
                # We'll assume if the *last question* was an image, its feedback might have been a caption edit.
                # However, it's safer to just try editing text, and if it fails, send new.
                # A more robust way would be to store the type of the feedback message.
                
                # Let's try to retrieve the message from cache to check its type if possible
                cached_message = context.bot_data.get(f"msg_cache_{self.chat_id}_{last_msg_id_to_use}")
                
                if cached_message and cached_message.photo: # If it was a photo message
                    await bot.edit_message_caption(chat_id=self.chat_id, message_id=last_msg_id_to_use, caption=results_text, reply_markup=reply_markup, parse_mode='HTML')
                else: # Assume it was a text message or we don't know
                    await bot.edit_message_text(text=results_text, chat_id=self.chat_id, message_id=last_msg_id_to_use, reply_markup=reply_markup, parse_mode='HTML')
                logger.info(f"[QuizLogic {self.quiz_id}] Edited last message {last_msg_id_to_use} with results.")
            except telegram.error.BadRequest as e:
                if "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower() or "message is not modified" in str(e).lower():
                    logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit message {last_msg_id_to_use} for results, sending new: {e}")
                    await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=reply_markup, parse_mode='HTML')
                else:
                    logger.error(f"[QuizLogic {self.quiz_id}] Error editing message {last_msg_id_to_use} for results: {e}", exc_info=True)
                    await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=reply_markup, parse_mode='HTML') # Fallback
            except Exception as e_edit_results:
                logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message {last_msg_id_to_use} for results: {e_edit_results}", exc_info=True)
                await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=reply_markup, parse_mode='HTML') # Fallback
        else:
            await safe_send_message(bot, chat_id=self.chat_id, text=results_text, reply_markup=reply_markup, parse_mode='HTML')

        await self.cleanup_quiz_data(context, user_id, "quiz_completed_show_results")
        return END 

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.info(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user {user_id}. Reason: {reason}")
        self.active = False
        quiz_instance_key = f"quiz_instance_{user_id}_{self.chat_id}"
        if quiz_instance_key in context.user_data:
            del context.user_data[quiz_instance_key]
            logger.debug(f"[QuizLogic {self.quiz_id}] Removed {quiz_instance_key} from user_data.")
        
        # Clean up any cached messages related to this quiz if we stored them by quiz_id
        # This part is illustrative; actual implementation depends on how messages are cached.
        # For example, if messages were cached like context.bot_data[f"quiz_{self.quiz_id}_q_{idx}_msg_id"]
        # you would iterate and delete them here.
        # For now, we are caching the last question message ID in self.last_question_message_id
        # and also in context.bot_data[f"msg_cache_{self.chat_id}_{sent_message.message_id}"]
        # We might need a more systematic way to clean up bot_data cache if it grows too large.

        # Remove any pending timer for this quiz
        # Note: Timers are named like f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{q_idx}"
        # We need to find and remove any such job. This is tricky without knowing the exact q_idx.
        # A simpler approach is to ensure timers are always removed when an answer is handled or timeout occurs.
        # The remove_job_if_exists in handle_answer and timeout_callback should cover most cases.
        # For a full cleanup, one might iterate through all jobs and check the name pattern.
        logger.debug(f"[QuizLogic {self.quiz_id}] Quiz data cleanup finished for user {user_id}.")

    def is_finished(self):
        """Checks if the quiz has no more questions to ask or is inactive."""
        return not self.active or self.current_question_index >= self.total_questions

async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    quiz_id = job_data["quiz_id"]
    question_index_timed_out = job_data["question_index"]
    user_id = job_data["user_id"]
    chat_id = job_data["chat_id"]
    message_id = job_data["message_id"]
    question_was_image = job_data.get("question_was_image", False) # Get from job_data

    logger.info(f"[TimeoutCallback] Timeout for quiz {quiz_id}, q_idx {question_index_timed_out}, user {user_id}, chat {chat_id}")

    quiz_instance_key = f"quiz_instance_{user_id}_{chat_id}"
    quiz_logic = context.user_data.get(quiz_instance_key)

    if quiz_logic and quiz_logic.active and quiz_logic.quiz_id == quiz_id and quiz_logic.current_question_index == question_index_timed_out:
        logger.info(f"[TimeoutCallback] Quiz {quiz_id} is active and current. Processing timeout.")
        
        current_question_data = quiz_logic.questions_data[question_index_timed_out]
        q_text_timeout = current_question_data.get("question_text", "نص السؤال غير متوفر")
        if not isinstance(q_text_timeout, str) or not q_text_timeout.strip(): q_text_timeout = "نص السؤال غير متوفر"
        correct_option_id_timeout = str(current_question_data.get("correct_option_id"))
        correct_option_text_timeout = "غير محدد"
        options_for_timeout_lookup = current_question_data.get("options", [])
        for opt_timeout in options_for_timeout_lookup:
            if str(opt_timeout.get("option_id")) == correct_option_id_timeout:
                if opt_timeout.get("is_image_option"):
                    correct_option_text_timeout = f"الخيار المصور: {opt_timeout.get('image_option_display_label', 'غير مسمى')}"
                else:
                    correct_option_text_timeout = opt_timeout.get("option_text", "نص الخيار الصحيح غير متوفر")
                break

        quiz_logic.answers.append({
            "question_id": current_question_data.get("question_id", f"q_idx_{question_index_timed_out}"),
            "question_text": q_text_timeout,
            "chosen_option_id": None, 
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": correct_option_id_timeout,
            "correct_option_text": correct_option_text_timeout,
            "is_correct": False,
            "time_taken": quiz_logic.question_time_limit 
        })

        feedback_on_timeout = f"<emoji document_id=\"5373103086790313136\">⌛</emoji> <b>انتهى الوقت!</b> الإجابة الصحيحة كانت: {correct_option_text_timeout}"
        
        original_caption_timeout = ""
        # We need to fetch the original message text/caption to append to it.
        # The message_id is available in job_data.
        # We assume the message is still accessible and its content hasn't changed drastically.
        cached_message_timeout = context.bot_data.get(f"msg_cache_{chat_id}_{message_id}")

        if cached_message_timeout:
            if question_was_image and cached_message_timeout.caption:
                 original_caption_timeout = cached_message_timeout.caption + "\n\n"
            elif not question_was_image and cached_message_timeout.text:
                 original_caption_timeout = cached_message_timeout.text + "\n\n"
            else: # Fallback if text/caption not found in cached message
                 original_caption_timeout = f"<b>السؤال {question_index_timed_out + 1} من {quiz_logic.total_questions}:</b>\n{q_text_timeout}\n\n"
        else: # Fallback if message not in cache
            logger.warning(f"[TimeoutCallback] Message {message_id} not found in cache for quiz {quiz_id}, q_idx {question_index_timed_out}. Using generic header.")
            original_caption_timeout = f"<b>السؤال {question_index_timed_out + 1} من {quiz_logic.total_questions}:</b>\n{q_text_timeout}\n\n"

        new_text_or_caption_timeout = original_caption_timeout + feedback_on_timeout

        try:
            if question_was_image:
                await context.bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=new_text_or_caption_timeout, reply_markup=None, parse_mode='HTML')
            else:
                await context.bot.edit_message_text(text=new_text_or_caption_timeout, chat_id=chat_id, message_id=message_id, reply_markup=None, parse_mode='HTML')
            logger.debug(f"[TimeoutCallback] Edited message {message_id} with timeout feedback for quiz {quiz_id}.")
            context.user_data[f"quiz_last_feedback_message_id_{quiz_id}"] = message_id # Store for potential results edit
        except telegram.error.BadRequest as e_timeout_edit:
            if "message is not modified" in str(e_timeout_edit).lower():
                 logger.warning(f"[TimeoutCallback] Message {message_id} not modified on timeout: {e_timeout_edit}.")
            else:
                logger.error(f"[TimeoutCallback] Error editing message {message_id} on timeout for quiz {quiz_id}: {e_timeout_edit}", exc_info=True)
                await safe_send_message(context.bot, chat_id=chat_id, text=feedback_on_timeout, parse_mode='HTML') # Fallback
        except Exception as e_timeout_generic:
            logger.error(f"[TimeoutCallback] Generic error editing message {message_id} on timeout for quiz {quiz_id}: {e_timeout_generic}", exc_info=True)
            await safe_send_message(context.bot, chat_id=chat_id, text=feedback_on_timeout, parse_mode='HTML') # Fallback

        quiz_logic.current_question_index += 1
        if quiz_logic.current_question_index < quiz_logic.total_questions:
            await asyncio.sleep(1) # Short delay
            await quiz_logic.send_question(context.bot, context, user_id) # Pass user_id
        else:
            await quiz_logic.show_results(context.bot, context, user_id) # Pass user_id
    else:
        logger.warning(f"[TimeoutCallback] Quiz {quiz_id} (q_idx {question_index_timed_out}) not found, inactive, or index mismatch for user {user_id}. Timer job will not proceed.")

