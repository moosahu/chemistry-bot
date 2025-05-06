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
        logger.debug(f"[QuizLogic] Initialized for quiz {self.quiz_id}, user {self.user_id if self.user_id else 'UNKNOWN'}")

    def create_options_keyboard(self, options_data):
        keyboard = []
        for i, option in enumerate(options_data):
            option_id = option.get("option_id", i)
            callback_data = f"ans_{self.current_question_index}_{option_id}"
            keyboard.append([InlineKeyboardButton(option["option_text"], callback_data=callback_data)])
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
            except telegram.error.BadRequest as e:
                logger.error(f"Failed to send photo (BadRequest) for q_id {current_question_data.get('question_id', 'UNKNOWN')}: {e}. URL: {image_url}")
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

        else:
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
            self.question_start_time = time.time()
            logger.info(f"Question {self.current_question_index} sent (msg_id: {self.last_question_message_id}) for quiz {self.quiz_id}, user {user_id}.")
            
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
                        "attempt_start_time": self.question_start_time
                    }
                )
                 logger.info(f"Question timer ({self.question_time_limit}s) started for q:{self.current_question_index} quiz:{self.quiz_id} user:{user_id} (Job: {timer_job_name})")
            else:
                logger.error(f"JobQueue not found in context for quiz {self.quiz_id}, user {user_id}. Timer not started.")
        else:
            logger.error(f"Failed to send question {self.current_question_index} (text or image) for quiz {self.quiz_id} to user {user_id}. No message object returned.")
            try:
                await safe_send_message(self.bot, chat_id, "عذراً، حدث خطأ أثناء إرسال السؤال. سيتم إنهاء الاختبار الحالي.")
            except Exception as e_msg_err:
                logger.error(f"Failed to send error message to user {user_id} after question send failure: {e_msg_err}")
            return ConversationHandler.END

    async def handle_answer(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        
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
            await safe_send_message(self.bot, chat_id, "لقد استلمت إجابة لسؤال سابق. يتم عرض السؤال الحالي.")
            return

        current_question_data = self.questions_data[self.current_question_index]
        selected_option_id_str = option_id_str
        is_correct = False
        selected_option_text = "غير محدد"

        for opt in current_question_data.get("options", []):
            if str(opt.get("option_id", -1)) == selected_option_id_str:
                is_correct = opt.get("is_correct", False)
                selected_option_text = opt.get("option_text", "")
                break
        
        time_taken = time.time() - self.question_start_time

        self.answers.append({
            "question_id": current_question_data.get("question_id"),
            "question_text": current_question_data.get("question_text", "N/A"),
            "selected_option_id": selected_option_id_str,
            "selected_option_text": selected_option_text,
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
        q_text = str(q_text_from_data if q_text_from_data is not None else "")
        original_question_text = header + q_text

        await safe_edit_message_text(
            bot=self.bot,
            chat_id=chat_id,
            message_id=self.last_question_message_id,
            text=f"{original_question_text}\n\n<i>إجابتك: {selected_option_text}</i>\n<b>{feedback_text}</b>",
            reply_markup=None,
            parse_mode="HTML"
        )

        self.current_question_index += 1
        await self.send_question(chat_id, user_id)

    async def question_timeout_callback(self, context: CallbackContext):
        job_data = context.job.data
        quiz_id = job_data["quiz_id"]
        question_idx = job_data["question_index"]
        user_id = job_data["user_id"]
        chat_id = job_data["chat_id"]
        message_id = job_data["message_id"]

        if self.quiz_id != quiz_id or self.current_question_index != question_idx:
            logger.info(f"Timeout job for old quiz/question ({quiz_id}, q_idx {question_idx}) ignored. Current: ({self.quiz_id}, q_idx {self.current_question_index})")
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
        q_text = str(q_text_from_data if q_text_from_data is not None else "")
        original_question_text = header + q_text
        
        await safe_edit_message_text(
            bot=self.bot,
            chat_id=chat_id,
            message_id=message_id,
            text=f"{original_question_text}\n\n<i>انتهى الوقت المخصص للسؤال.</i>",
            reply_markup=None,
            parse_mode="HTML"
        )
        
        self.current_question_index += 1
        await self.send_question(chat_id, user_id)

    async def show_results(self, chat_id: int, user_id: int):
        total_answered = len(self.answers)
        correct_answers = self.score
        percentage = (correct_answers / self.total_questions) * 100 if self.total_questions > 0 else 0

        results_text = f"🏁 <b>نتائج الاختبار (معرف: {self.quiz_id})</b> 🏁\n\n"
        results_text += f"عدد الأسئلة الكلي: {self.total_questions}\n"
        results_text += f"عدد الإجابات الصحيحة: {correct_answers}\n"
        results_text += f"النسبة المئوية: {percentage:.2f}%\n\n"

        logger.info(f"Showing results for quiz {self.quiz_id} to user {user_id}. Score: {correct_answers}/{self.total_questions}")
        await safe_send_message(self.bot, chat_id, results_text, parse_mode="HTML")
        
    async def start_quiz(self, update: Update):
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        self.user_id = user_id

        if not self.questions_data or self.total_questions == 0:
            logger.error(f"Attempted to start quiz {self.quiz_id} for user {user_id} with no questions or zero total questions.")
            await safe_send_message(self.bot, chat_id, "عذراً، لا توجد أسئلة متاحة لهذا الاختبار أو لم يتم تحديد عدد الأسئلة. يرجى المحاولة مرة أخرى.")
            return ConversationHandler.END

        logger.info(f"Quiz {self.quiz_id} starting for user {user_id} with {self.total_questions} questions of type {self.quiz_type}.")
        await self.send_question(chat_id, user_id)
        return TAKING_QUIZ

