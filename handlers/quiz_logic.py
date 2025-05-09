# -*- coding: utf-8 -*-
# handlers/quiz_logic.py (v36 - Triple Fix: Admin Auth, Stats DB, Image Result Display)

import asyncio
import logging
import time
import uuid # لإنشاء معرّف فريد للاختبار
import telegram # For telegram.error types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot 
from telegram.ext import ConversationHandler, CallbackContext, JobQueue 
from config import logger, TAKING_QUIZ, END, MAIN_MENU 
from utils.helpers import safe_send_message, safe_edit_message_text, remove_job_if_exists
from database.data_logger import log_quiz_results # افتراض وجود هذه الدالة

MIN_OPTIONS_PER_QUESTION = 2

class QuizLogic:
    ARABIC_CHOICE_LETTERS = ["أ", "ب", "ج", "د"]

    def __init__(self, user_id=None, chat_id=None, quiz_type=None, questions_data=None, total_questions=0, question_time_limit=60, quiz_id=None, quiz_name=None, db_quiz_session_id=None):
        self.user_id = user_id
        self.chat_id = chat_id
        self.quiz_id = quiz_id if quiz_id else str(uuid.uuid4()) 
        self.quiz_name = quiz_name if quiz_name else "اختبار غير مسمى"
        self.quiz_type = quiz_type
        self.questions_data = questions_data if questions_data is not None else []
        self.total_questions = len(self.questions_data) 
        self.current_question_index = 0
        self.score = 0
        self.answers = [] 
        self.question_start_time = None
        self.last_question_message_id = None
        self.question_time_limit = question_time_limit
        self.last_question_is_image = False # True if the question itself was sent as an image (e.g. send_photo with question text in caption)
        self.active = True 
        self.db_quiz_session_id = db_quiz_session_id
        logger.debug(f"[QuizLogic {self.quiz_id}] Initialized for user {self.user_id if self.user_id else 'UNKNOWN'} in chat {self.chat_id if self.chat_id else 'UNKNOWN'}. Quiz: {self.quiz_name}. Questions: {self.total_questions}. DB Session ID: {self.db_quiz_session_id}")

    async def start_quiz(self, bot: Bot, context: CallbackContext, update: Update, user_id: int) -> int:
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
        
        return await self.send_question(bot, context, user_id)
    
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

    async def send_question(self, bot: Bot, context: CallbackContext, user_id: int):
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
                    "correct_option_text": "لا يمكن تحديده (خيارات غير كافية)",
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
            image_url = current_question_data.get("image_url") # This is for the question image, not option image
            question_text_from_data = current_question_data.get("question_text", "") 
            sent_message = None
            self.last_question_is_image = False # Reset for current question

            if not isinstance(question_text_from_data, str):
                question_text_from_data = str(question_text_from_data)

            if image_url:
                caption_text = header + question_text_from_data
                try:
                    sent_message = await bot.send_photo(chat_id=self.chat_id, photo=image_url, caption=caption_text, reply_markup=options_keyboard, parse_mode="HTML")
                    self.last_question_is_image = True # Mark that this question was sent as a photo message
                except Exception as e:
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to send photo q_id {q_id_log}: {e}. URL: {image_url}", exc_info=True)
                    # Fallback to text if photo fails
                    full_question_text = header + question_text_from_data + "\n(تعذر تحميل صورة السؤال)"
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
                        chat_id=self.chat_id, 
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
                    "correct_option_text": "لا يمكن تحديده (خطأ في الإرسال)",
                    "is_correct": False,
                    "time_taken": -997 
                })
                self.current_question_index += 1
        
        logger.info(f"[QuizLogic {self.quiz_id}] No more valid questions to send or quiz ended. User {user_id}. Showing results.")
        return await self.show_results(bot, context, user_id)

    def _get_correct_option_text_robust(self, current_question_data):
        correct_option_id_from_data = str(current_question_data.get("correct_option_id"))
        options_for_current_q = current_question_data.get("options", [])
        retrieved_correct_option_text = "نص الإجابة الصحيحة غير متوفر"
        found_correct_option_details = False
        if not correct_option_id_from_data or correct_option_id_from_data == 'None':
            logger.warning(f"[QuizLogic {self.quiz_id}] Correct option ID is missing or None in question data for q_id '{current_question_data.get('question_id')}'")
            return "لم يتم تحديد إجابة صحيحة للسؤال"
        for opt_detail in options_for_current_q:
            if str(opt_detail.get("option_id")) == correct_option_id_from_data:
                if opt_detail.get("is_image_option"):
                    img_label = opt_detail.get('image_option_display_label')
                    if img_label and img_label.strip():
                        retrieved_correct_option_text = f"صورة ({img_label})"
                    else:
                        retrieved_correct_option_text = f"صورة (معرف: {correct_option_id_from_data})"
                else:
                    text_val = opt_detail.get("option_text")
                    if isinstance(text_val, str) and text_val.strip():
                        retrieved_correct_option_text = text_val
                    else:
                        retrieved_correct_option_text = f"خيار نصي (معرف: {correct_option_id_from_data})"
                found_correct_option_details = True
                break
        if not found_correct_option_details:
            logger.error(f"[QuizLogic {self.quiz_id}] Critical: Correct option ID '{correct_option_id_from_data}' not found in processed options for q_id '{current_question_data.get('question_id')}'")
            retrieved_correct_option_text = f"خطأ: الإجابة الصحيحة (معرف: {correct_option_id_from_data}) غير موجودة ضمن الخيارات"
        return retrieved_correct_option_text

    async def handle_answer(self, bot: Bot, context: CallbackContext, update: Update):
        query = update.callback_query
        user_id = query.from_user.id
        if not self.active or str(user_id) != str(self.user_id):
            await query.answer(text="هذا الاختبار ليس لك أو لم يعد نشطاً.", show_alert=True)
            return TAKING_QUIZ 
        time_taken = time.time() - self.question_start_time if self.question_start_time else -1
        try:
            temp_parts = query.data.split("_", 1)
            if len(temp_parts) < 2 or not temp_parts[0] == "ans":
                raise ValueError("Callback data format error - expected 'ans_QUIZID_QINDEX_OPTID'")
            
            parts = temp_parts[1].split("_") 
            if len(parts) < 3:
                raise ValueError("Callback data format error - insufficient parts after 'ans_'")

            quiz_id_from_cb = parts[0]
            question_index_from_cb = int(parts[1])
            chosen_option_id = str(parts[2])

            if quiz_id_from_cb != self.quiz_id or question_index_from_cb != self.current_question_index:
                await query.answer(text="تم الرد على سؤال قديم أو اختبار مختلف.", show_alert=True)
                return TAKING_QUIZ

            await query.answer() 
            timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{self.current_question_index}"
            remove_job_if_exists(timer_job_name, context)

            current_question_data = self.questions_data[self.current_question_index]
            correct_option_id = str(current_question_data.get("correct_option_id"))
            is_correct = (chosen_option_id == correct_option_id)
            if is_correct:
                self.score += 1
            
            chosen_option_text = ""
            options_for_q = current_question_data.get("options", [])
            for opt in options_for_q:
                if str(opt.get("option_id")) == chosen_option_id:
                    if opt.get("is_image_option"):
                        chosen_option_text = f"صورة ({opt.get('image_option_display_label', chosen_option_id)})"
                    else:
                        chosen_option_text = opt.get("option_text", f"خيار {chosen_option_id}")
                    break
            
            correct_option_text_display = self._get_correct_option_text_robust(current_question_data)

            self.answers.append({
                "question_id": current_question_data.get("question_id"),
                "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
                "chosen_option_id": chosen_option_id,
                "chosen_option_text": chosen_option_text,
                "correct_option_id": correct_option_id,
                "correct_option_text": correct_option_text_display,
                "is_correct": is_correct,
                "time_taken": round(time_taken, 2)
            })

            header_for_result = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
            question_text_display = current_question_data.get("question_text", "نص السؤال غير متوفر")
            image_url_for_q = current_question_data.get("image_url") # Question image, not option

            answer_feedback_line = "✅ إجابة صحيحة!" if is_correct else "❌ إجابة خاطئة."
            
            result_text = f"{header_for_result}{question_text_display}\n\n{answer_feedback_line}\nالإجابة الصحيحة: {correct_option_text_display}"
            if chosen_option_text: 
                result_text += f"\nإجابتك: {chosen_option_text}"
            result_text += f"\nالوقت المستغرق: {time_taken:.1f} ثانية"

            # --- MODIFICATION FOR IMAGE ANSWER DISPLAY --- START
            if self.last_question_message_id:
                try:
                    if self.last_question_is_image: # If the question was sent as a photo message
                        logger.debug(f"[QuizLogic {self.quiz_id}] Editing caption for image question result (q_idx {self.current_question_index}). MsgID: {self.last_question_message_id}")
                        await bot.edit_message_caption(
                            chat_id=self.chat_id,
                            message_id=self.last_question_message_id,
                            caption=result_text, 
                            reply_markup=None,   
                            parse_mode="HTML"
                        )
                    else: # Regular text question
                        logger.debug(f"[QuizLogic {self.quiz_id}] Editing text for text question result (q_idx {self.current_question_index}). MsgID: {self.last_question_message_id}")
                        await safe_edit_message_text( 
                            bot=bot,
                            chat_id=self.chat_id,
                            message_id=self.last_question_message_id,
                            text=result_text,
                            reply_markup=None, 
                            parse_mode="HTML"
                        )
                except telegram.error.BadRequest as e:
                    logger.error(f"[QuizLogic {self.quiz_id}] BadRequest editing message/caption for question result (q_idx {self.current_question_index}): {e}. MsgID: {self.last_question_message_id}. Attempting to send as new message.")
                    await safe_send_message(bot, chat_id=self.chat_id, text=result_text, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message/caption for question result (q_idx {self.current_question_index}): {e}", exc_info=True)
                    await safe_send_message(bot, chat_id=self.chat_id, text=result_text, parse_mode="HTML") # Fallback
            else:
                logger.warning(f"[QuizLogic {self.quiz_id}] No last_question_message_id to edit. Sending result as new message.")
                await safe_send_message(bot, chat_id=self.chat_id, text=result_text, parse_mode="HTML")
            # --- MODIFICATION FOR IMAGE ANSWER DISPLAY --- END

            self.current_question_index += 1
            if self.current_question_index < self.total_questions:
                await asyncio.sleep(2) # Pause before next question
                return await self.send_question(bot, context, user_id)
            else:
                await asyncio.sleep(2) 
                return await self.show_results(bot, context, user_id)

        except ValueError as e:
            logger.error(f"[QuizLogic {self.quiz_id}] ValueError in handle_answer: {e}. Callback data: {query.data if query else 'No query'}", exc_info=True)
            await query.answer("حدث خطأ في معالجة إجابتك. يرجى المحاولة مرة أخرى أو إبلاغ الأدمن.", show_alert=True)
            return TAKING_QUIZ 
        except Exception as e:
            logger.error(f"[QuizLogic {self.quiz_id}] Unexpected error in handle_answer: {e}. Callback data: {query.data if query else 'No query'}", exc_info=True)
            await query.answer("حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى أو إبلاغ الأدمن.", show_alert=True)
            return TAKING_QUIZ 

    async def process_timeout(self, bot: Bot, question_index: int, message_id_to_edit: int, question_was_image: bool):
        logger.info(f"[QuizLogic {self.quiz_id}] Timeout for question index {question_index}. User: {self.user_id}")
        if not self.active or question_index != self.current_question_index:
            logger.warning(f"[QuizLogic {self.quiz_id}] Timeout for inactive/old question (current: {self.current_question_index}, timeout_q: {question_index}). Ignoring.")
            return

        current_question_data = self.questions_data[question_index]
        correct_option_text_display = self._get_correct_option_text_robust(current_question_data)
        
        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": current_question_data.get("question_text", "نص السؤال غير متوفر"),
            "chosen_option_id": None,
            "chosen_option_text": "انتهى الوقت",
            "correct_option_id": current_question_data.get("correct_option_id"),
            "correct_option_text": correct_option_text_display,
            "is_correct": False,
            "time_taken": self.question_time_limit 
        })

        header_for_result = f"<b>السؤال {question_index + 1} من {self.total_questions}:</b>\n"
        question_text_display = current_question_data.get("question_text", "نص السؤال غير متوفر")
        result_text = f"{header_for_result}{question_text_display}\n\n⌛️ انتهى الوقت!\nالإجابة الصحيحة: {correct_option_text_display}"

        # --- MODIFICATION FOR IMAGE ANSWER DISPLAY (TIMEOUT) --- START
        if message_id_to_edit:
            try:
                if question_was_image: # If the question was sent as a photo message
                    logger.debug(f"[QuizLogic {self.quiz_id}] Editing caption for TIMEOUT image question (q_idx {question_index}). MsgID: {message_id_to_edit}")
                    await bot.edit_message_caption(
                        chat_id=self.chat_id, 
                        message_id=message_id_to_edit,
                        caption=result_text,
                        reply_markup=None,
                        parse_mode="HTML"
                    )
                else: # Regular text question
                    logger.debug(f"[QuizLogic {self.quiz_id}] Editing text for TIMEOUT text question (q_idx {question_index}). MsgID: {message_id_to_edit}")
                    await safe_edit_message_text( 
                        bot=bot,
                        chat_id=self.chat_id, 
                        message_id=message_id_to_edit,
                        text=result_text,
                        reply_markup=None,
                        parse_mode="HTML"
                    )
            except telegram.error.BadRequest as e:
                logger.error(f"[QuizLogic {self.quiz_id}] BadRequest editing message/caption for TIMEOUT (q_idx {question_index}): {e}. MsgID: {message_id_to_edit}. Sending as new.")
                await safe_send_message(bot, chat_id=self.chat_id, text=result_text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"[QuizLogic {self.quiz_id}] Generic error editing message/caption for TIMEOUT (q_idx {question_index}): {e}", exc_info=True)
                await safe_send_message(bot, chat_id=self.chat_id, text=result_text, parse_mode="HTML") # Fallback
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] No message_id_to_edit for timeout. Sending result as new message.")
            await safe_send_message(bot, chat_id=self.chat_id, text=result_text, parse_mode="HTML")
        # --- MODIFICATION FOR IMAGE ANSWER DISPLAY (TIMEOUT) --- END

        self.current_question_index += 1
        # Need context for the next step
        # This function is called by a job, so context might not be directly available in the same way
        # For now, we assume the calling wrapper (question_timeout_callback_wrapper) handles getting a fresh context if needed for send_question/show_results
        # However, the quiz instance itself is stateful. The wrapper should pass the bot object.
        # The wrapper should then call the next step on the quiz_instance.
        # This part is handled by the wrapper calling send_question or show_results after this. 

    async def show_results(self, bot: Bot, context: CallbackContext, user_id: int):
        logger.info(f"[QuizLogic {self.quiz_id}] Showing results for user {user_id}. Score: {self.score}/{self.total_questions}")
        if not self.active:
            logger.warning(f"[QuizLogic {self.quiz_id}] show_results called on inactive quiz. User {user_id}")
            # Maybe send a generic message or do nothing
            return END 

        if self.total_questions == 0:
            results_summary = "لم يتم إجراء أي أسئلة في هذا الاختبار."
        else:
            percentage = (self.score / self.total_questions) * 100 if self.total_questions > 0 else 0
            results_summary = f"🎉 *نتائج الاختبار ({self.quiz_name})* 🎉\n\n"
            results_summary += f"✨ لقد أكملت الاختبار! ✨\n"
            results_summary += f"🎯 نتيجتك: {self.score} من {self.total_questions} ({percentage:.2f}%)\n\n"
            # results_summary += "ملخص إجاباتك:\n"
            # for i, ans in enumerate(self.answers):
            #     q_text_short = ans.get("question_text", f"سؤال {i+1}")[:30] + "..."
            #     status = "صحيحة" if ans.get("is_correct") else ("خاطئة" if ans.get("chosen_option_id") else "تم تخطيها")
            #     results_summary += f"  - س {i+1} ({q_text_short}): {status}\n"
            results_summary += "\nشكراً لك على المشاركة!"

        keyboard = [[InlineKeyboardButton("📊 عرض إحصائياتي", callback_data="my_stats"), InlineKeyboardButton("القائمة الرئيسية 🏠", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Log results to database
        if self.db_quiz_session_id: # Ensure we have the DB session ID from quiz.py
            try:
                # Collect necessary details for logging
                # start_time and end_time for the whole quiz are not explicitly tracked in this version of QuizLogic
                # We can use approximations or pass them if available from the calling handler.
                # For now, let's assume data_logger handles missing start/end times gracefully or they are added elsewhere.
                quiz_end_time = datetime.now() # Approximation
                quiz_start_time = quiz_end_time # Placeholder, ideally this is tracked from quiz start
                
                # Try to get quiz_start_time from context if it was stored by the handler
                if context and hasattr(context, 'user_data') and context.user_data.get(f'quiz_start_time_{self.quiz_id}'):
                    quiz_start_time = context.user_data[f'quiz_start_time_{self.quiz_id}']

                log_quiz_results(
                    user_id=self.user_id,
                    quiz_session_id=self.db_quiz_session_id, # This is the crucial ID from quiz_sessions table
                    quiz_id_uuid=self.quiz_id, # This is the QuizLogic's internal UUID for the quiz instance
                    quiz_name=self.quiz_name,
                    quiz_type=self.quiz_type,
                    filter_id=None, # Or pass the actual scope_id if available and relevant for this quiz_type
                    total_questions=self.total_questions,
                    correct_answers=self.score,
                    wrong_answers=self.total_questions - self.score - sum(1 for a in self.answers if a.get("chosen_option_id") is None and a.get("time_taken") == self.question_time_limit), # Approximation of wrong
                    skipped_answers=sum(1 for a in self.answers if a.get("chosen_option_id") is None and a.get("time_taken") == self.question_time_limit), # Skipped due to timeout
                    score_percentage=percentage,
                    time_taken_seconds=sum(a.get("time_taken", 0) for a in self.answers if a.get("time_taken", 0) > 0), # Sum of time per question
                    start_timestamp=quiz_start_time.isoformat() if isinstance(quiz_start_time, datetime) else None,
                    end_timestamp=quiz_end_time.isoformat(),
                    answers_details=self.answers # Full list of answer details
                )
                logger.info(f"[QuizLogic {self.quiz_id}] Successfully logged quiz results to DB for user {self.user_id} with session ID {self.db_quiz_session_id}")
            except Exception as e_log:
                logger.error(f"[QuizLogic {self.quiz_id}] Failed to log quiz results to DB for user {self.user_id}: {e_log}", exc_info=True)
        else:
            logger.warning(f"[QuizLogic {self.quiz_id}] db_quiz_session_id is missing. Cannot log results to DB for user {self.user_id}.")

        await safe_send_message(bot, chat_id=self.chat_id, text=results_summary, reply_markup=reply_markup, parse_mode='Markdown')
        await self.cleanup_quiz_data(context, user_id, "quiz_completed_normally")
        return END 

    async def cleanup_quiz_data(self, context: CallbackContext, user_id: int, reason: str):
        logger.info(f"[QuizLogic {self.quiz_id}] Cleaning up quiz data for user {user_id}. Reason: {reason}")
        self.active = False 
        if context and hasattr(context, 'user_data') and f'quiz_logic_instance_{user_id}_{self.chat_id}' in context.user_data:
            del context.user_data[f'quiz_logic_instance_{user_id}_{self.chat_id}']
            logger.debug(f"[QuizLogic {self.quiz_id}] Removed instance from user_data for {user_id}_{self.chat_id}")
        # Ensure any pending timers for this quiz are cancelled
        # This is a bit broad, but better than leaving timers running.
        # Specific timer job names were like: f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{q_idx}"
        # We can try to remove based on a prefix if JobQueue supports it, or iterate if needed.
        # For now, remove_job_if_exists is called per question, this is a safeguard.
        if context and context.job_queue:
            for i in range(self.total_questions + 1): # Iterate through possible question indices
                timer_job_name = f"qtimer_{user_id}_{self.chat_id}_{self.quiz_id}_{i}"
                remove_job_if_exists(timer_job_name, context)
        logger.info(f"[QuizLogic {self.quiz_id}] Cleanup complete for user {user_id}.")

# This wrapper is needed because JobQueue.run_once expects a callable that takes CallbackContext as its first argument.
async def question_timeout_callback_wrapper(context: CallbackContext):
    job_data = context.job.data
    user_id = job_data["user_id"]
    chat_id = job_data["chat_id"]
    quiz_id_from_job = job_data["quiz_id"]
    question_index = job_data["question_index"]
    message_id_to_edit = job_data["message_id"]
    question_was_image = job_data.get("question_was_image", False) # Get the flag

    logger.debug(f"[TimeoutWrapper] Job triggered for user {user_id}, chat {chat_id}, quiz {quiz_id_from_job}, q_idx {question_index}")

    quiz_instance_key = f'quiz_logic_instance_{user_id}_{chat_id}'
    quiz_instance = context.user_data.get(quiz_instance_key)

    if quiz_instance and quiz_instance.active and quiz_instance.quiz_id == quiz_id_from_job and quiz_instance.current_question_index == question_index:
        logger.info(f"[TimeoutWrapper] Processing timeout for user {user_id}, quiz {quiz_id_from_job}, q_idx {question_index}")
        await quiz_instance.process_timeout(bot=context.bot, question_index=question_index, message_id_to_edit=message_id_to_edit, question_was_image=question_was_image)
        # After processing timeout, check if quiz should continue or end
        if quiz_instance.current_question_index < quiz_instance.total_questions:
            await asyncio.sleep(2) # Pause before next question
            await quiz_instance.send_question(bot=context.bot, context=context, user_id=user_id)
        else:
            await asyncio.sleep(2)
            await quiz_instance.show_results(bot=context.bot, context=context, user_id=user_id)
    else:
        logger.warning(f"[TimeoutWrapper] Timeout for an old/inactive quiz or mismatched state. User {user_id}, Quiz {quiz_id_from_job}, Q_idx {question_index}. Instance active: {quiz_instance.active if quiz_instance else 'N/A'}")

