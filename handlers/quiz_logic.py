# -*- coding: utf-8 -*-
# handlers/quiz_logic.py (v24 - Pickle Refactor: Data-only QuizLogic)

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

    # Note: Methods below will now require bot and context to be passed as arguments

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
            await self.cleanup_quiz_data(context, user_id, "no_questions_on_start") # context needed for cleanup
            return END 
        
        return await self.send_question(bot, context, chat_id, user_id)
    
    def create_options_keyboard(self, options_data):
        keyboard = []
        arabic_alphabet_for_buttons = [chr(code) for code in range(0x0623, 0x0623 + 28)] 

        for i, option in enumerate(options_data):
            option_id = option.get("option_id", f"gen_opt_{i}") 
            option_text_original = option.get("option_text", "")
            button_text = ""

            if option.get("is_image_option"):
                image_display_char = option.get("image_option_display_label")
                if not image_display_char:
                    image_display_char = arabic_alphabet_for_buttons[i] if i < len(arabic_alphabet_for_buttons) else f"{i + 1}"
                button_text = f"اختر: {image_display_char}"
            elif isinstance(option_text_original, str) and not option_text_original.strip():
                button_text = f"خيار {i + 1}"
            elif isinstance(option_text_original, str) and (option_text_original.startswith("http://") or option_text_original.startswith("https://") ):
                button_text = f"خيار {i + 1} (صورة)"
            elif isinstance(option_text_original, str):
                button_text = option_text_original
            else:
                button_text = f"خيار {i + 1} (بيانات غير نصية)"
            
            button_text_str = str(button_text)
            if len(button_text_str.encode('utf-8')) > 64:
                temp_bytes = button_text_str.encode('utf-8')[:60]
                button_text = temp_bytes.decode('utf-8', 'ignore') + "..."

            if not button_text_str.strip():
                 button_text = f"خيار {i + 1}"

            callback_data = f"ans_{self.quiz_id}_{self.current_question_index}_{option_id}"
            keyboard.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
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
                    await bot.send_photo(chat_id=chat_id, photo=option_text_original, caption=display_label)
                    current_option_proc['is_image_option'] = True
                    current_option_proc['image_option_display_label'] = display_label
                    option_image_counter += 1
                    await asyncio.sleep(0.3) 
                except Exception as e_img_opt:
                    logger.error(f"[QuizLogic {self.quiz_id}] Failed to send image for option {i} (URL: {option_text_original}), q_id {q_id_log}: {e_img_opt}", exc_info=True)
                    current_option_proc['is_image_option'] = False
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
            remove_job_if_exists(timer_job_name, context) # context is needed here

            if context.job_queue:
                 context.job_queue.run_once(
                    question_timeout_callback_wrapper, # Wrapper function will be needed
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
        
        await query.answer() # Acknowledge callback

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
                await bot.edit_message_caption(chat_id=query.message.chat_id, message_id=self.last_question_message_id, caption=full_feedback_message, reply_markup=None, parse_mode='HTML')
            elif not self.last_question_is_image and query.message.text is not None:
                await bot.edit_message_text(text=full_feedback_message, chat_id=query.message.chat_id, message_id=self.last_question_message_id, reply_markup=None, parse_mode='HTML')
            else:
                 await safe_send_message(bot, chat_id=query.message.chat_id, text=feedback_text)
        except telegram.error.BadRequest as e:
            if "MESSAGE_NOT_MODIFIED" not in str(e).upper():
                await safe_send_message(bot, chat_id=query.message.chat_id, text=feedback_text)
        except Exception as e_edit:
            await safe_send_message(bot, chat_id=query.message.chat_id, text=feedback_text)

        self.current_question_index += 1
        await asyncio.sleep(1.5) 
        return await self.send_question(bot, context, query.message.chat_id, user_id)

async def question_timeout_callback_wrapper(context: CallbackContext):
    """Wrapper for the timeout callback to retrieve QuizLogic instance and pass bot/context."""
    job_data = context.job.data
    quiz_id_from_job = job_data["quiz_id"]
    user_id = job_data["user_id"]
    
    quiz_logic_instance = context.user_data.get("quiz_sessions", {}).get(quiz_id_from_job)
    if not quiz_logic_instance:
        logger.warning(f"[TimeoutWrapper] QuizLogic instance {quiz_id_from_job} not found for user {user_id}. Timeout job will not run.")
        return

    if not isinstance(quiz_logic_instance, QuizLogic):
        logger.error(f"[TimeoutWrapper] Found item for quiz_id {quiz_id_from_job} is not a QuizLogic instance. Type: {type(quiz_logic_instance)}")
        return

    await quiz_logic_instance.question_timeout_callback_actual(context.bot, context, job_data)


# Renamed original to _actual and it now takes bot, context
async def question_timeout_callback_actual(self, bot: Bot, context: CallbackContext, job_data):
    user_id = job_data["user_id"]
    chat_id = job_data["chat_id"]
    quiz_id_from_job = job_data["quiz_id"]
    question_index_from_job = job_data["question_index"]
    message_id_from_job = job_data["message_id"]
    question_was_image = job_data.get("question_was_image", False)

    if not self.active or quiz_id_from_job != self.quiz_id or question_index_from_job != self.current_question_index or str(user_id) != str(self.user_id):
        logger.warning(f"[QuizLogic {self.quiz_id}] Stale/mismatched timeout. Ignoring.")
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
        original_message = None
        if question_was_image:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id_from_job, reply_markup=None)
            original_message_edited_markup = await bot.edit_message_caption(chat_id=chat_id, message_id=message_id_from_job, caption=" ", parse_mode='HTML')
            original_content = original_message_edited_markup.caption if original_message_edited_markup else ""
        else:
            original_message = await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id_from_job, reply_markup=None)
            original_content = original_message.text if original_message else ""

        header_part = f"<b>السؤال {self.current_question_index + 1} من {self.total_questions}:</b>\n"
        if original_content and original_content.startswith(header_part):
            text_content_for_feedback = original_content[len(header_part):]
        else: 
            text_content_for_feedback = q_text_for_ans
        
        full_feedback_message = f"{header_part}{text_content_for_feedback}\n\n{feedback_text}"

        if question_was_image:
            await bot.edit_message_caption(chat_id=chat_id, message_id=message_id_from_job, caption=full_feedback_message, parse_mode='HTML')
        else:
            await bot.edit_message_text(text=full_feedback_message, chat_id=chat_id, message_id=message_id_from_job, parse_mode='HTML')

    except telegram.error.BadRequest as e:
        if "MESSAGE_NOT_MODIFIED" not in str(e).upper():
            await safe_send_message(bot, chat_id=chat_id, text=feedback_text)
    except Exception as e_timeout_edit:
        await safe_send_message(bot, chat_id=chat_id, text=feedback_text)

    self.current_question_index += 1
    await asyncio.sleep(1.5) 
    await self.send_question(bot, context, chat_id, user_id) 

QuizLogic.question_timeout_callback_actual = question_timeout_callback_actual # Assign as method

async def show_results(self, bot: Bot, context: CallbackContext, chat_id: int, user_id: int):
    if not self.active:
        return END
        
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
        elif ans.get("chosen_option_id") is None: 
             results_text += f"   الصحيحة كانت: {correct}\n"

    keyboard = [
        [InlineKeyboardButton("🧠 ابدأ اختبار جديد", callback_data="start_quiz")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_to_send_results_to = self.last_question_message_id
    edited_successfully = False

    if message_to_send_results_to and not self.last_question_is_image: 
        try:
            await bot.edit_message_text(
                text=results_text, chat_id=chat_id, message_id=message_to_send_results_to,
                reply_markup=reply_markup, parse_mode='HTML'
            )
            edited_successfully = True
        except Exception as e_edit_results:
            logger.warning(f"[QuizLogic {self.quiz_id}] Failed to edit results: {e_edit_results}. Sending new.")
    
    if not edited_successfully:
        await safe_send_message(bot, chat_id=chat_id, text=results_text, reply_markup=reply_markup, parse_mode='HTML')

    await self.cleanup_quiz_data(context, user_id, "quiz_completed_shown_results")
    return END 

QuizLogic.show_results = show_results # Assign as method

async def end_quiz(self, bot: Bot, context: CallbackContext, update: Update, manual_end: bool = False, reason_suffix: str = ""):
    user_id_effective = update.effective_user.id if update.effective_user else self.user_id
    chat_id_effective = update.effective_chat.id if update.effective_chat else None
    
    reason = f"manual_end_{reason_suffix}" if manual_end else f"auto_end_{reason_suffix}"
    if not self.active: 
        return END

    timer_job_name = f"qtimer_{user_id_effective}_{chat_id_effective if chat_id_effective else 'unknown_chat'}_{self.quiz_id}_{self.current_question_index}"
    remove_job_if_exists(timer_job_name, context)

    if manual_end and chat_id_effective:
        if self.last_question_message_id:
            try:
                await bot.edit_message_reply_markup(chat_id=chat_id_effective, message_id=self.last_question_message_id, reply_markup=None)
            except Exception as e_rem_markup:
                logger.warning(f"[QuizLogic {self.quiz_id}] Failed to remove markup on manual end: {e_rem_markup}")
        
        end_text = "تم إنهاء الاختبار يدوياً."
        if self.answers: 
            end_text = f"تم إنهاء الاختبار يدوياً. 🏁\n\nنتيجتك حتى الآن: {self.score} من {self.current_question_index} أسئلة تمت معالجتها.\n"
        
        keyboard = [[InlineKeyboardButton("🧠 ابدأ اختبار جديد", callback_data="start_quiz"), InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_send_message(bot, chat_id=chat_id_effective, text=end_text, reply_markup=reply_markup)
    
    await self.cleanup_quiz_data(context, user_id_effective, reason)
    return END

QuizLogic.end_quiz = end_quiz # Assign as method

async def cleanup_quiz_data(self, context: CallbackContext, user_id, reason: str = "unknown"):
    self.active = False
    logger.info(f"[QuizLogic {self.quiz_id}] Cleanup for user {user_id}. Reason: {reason}. Active set to False.")
    # Remove this specific quiz instance from the quiz_sessions dictionary
    if 'quiz_sessions' in context.user_data and self.quiz_id in context.user_data['quiz_sessions']:
        del context.user_data['quiz_sessions'][self.quiz_id]
        logger.info(f"[QuizLogic {self.quiz_id}] Instance removed from context.user_data['quiz_sessions'].")
    else:
        logger.warning(f"[QuizLogic {self.quiz_id}] Instance not found in context.user_data['quiz_sessions'] during cleanup for user {user_id}.")
    
    # Optional: Clear other specific quiz-related keys if they were set directly on user_data for this quiz_id
    # For example, if any job data or other flags were stored outside the QuizLogic object but associated with its quiz_id.
    # This part depends on how other parts of the application might be storing data.
    # For now, focusing on removing the QuizLogic object itself is the primary goal.

QuizLogic.cleanup_quiz_data = cleanup_quiz_data # Assign as method
