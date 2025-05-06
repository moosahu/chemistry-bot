# -*- coding: utf-8 -*-
"""Core logic for handling quizzes in the Chemistry Telegram Bot, now with a QuizLogic class."""

import random
import time
import uuid
import re
import asyncio
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import CallbackContext, JobQueue
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError

from config import (
    logger,
    MAIN_MENU, TAKING_QUIZ, SHOWING_RESULTS, QUIZ_MENU,
    FEEDBACK_DELAY, ENABLE_QUESTION_TIMER,
    NUM_OPTIONS # Used for fallback old structure
)
from utils.helpers import (
    safe_send_message, safe_edit_message_text, safe_delete_message,
    remove_job_if_exists, get_quiz_type_string, format_duration
)
from handlers.common import create_main_menu_keyboard # Assuming this is still relevant
from utils.api_client import fetch_from_api, transform_api_question
from database.manager import DB_MANAGER

QUESTION_TIMER_SECONDS = 180  # 3 minutes

class QuizLogic:
    """Handles the core logic for quizzes."""

    def __init__(self, context: CallbackContext):
        """Initialize QuizLogic with bot context."""
        self.context = context
        self.user_data = context.user_data
        self.bot = context.bot
        logger.debug(f"[QuizLogic] Initialized for user {self.user_data.get("_effective_user_id", "UNKNOWN")}")

    async def _send_or_edit_message(self, chat_id: int, text: str, reply_markup=None, photo_url: str | None = None, current_message_id: int | None = None):
        """Helper to send a new message or edit an existing one, managing media."""
        new_message = None
        if photo_url:
            media = InputMediaPhoto(media=photo_url, caption=text, parse_mode=ParseMode.HTML)
            if current_message_id:
                try:
                    await safe_delete_message(self.bot, chat_id, current_message_id)
                    new_message = await self.bot.send_photo(chat_id=chat_id, photo=photo_url, caption=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
                except BadRequest as e:
                    logger.warning(f"[QuizLogic] Failed to edit message {current_message_id} with photo, sending new: {e}")
                    new_message = await self.bot.send_photo(chat_id=chat_id, photo=photo_url, caption=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            else:
                new_message = await self.bot.send_photo(chat_id=chat_id, photo=photo_url, caption=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        else:
            if current_message_id:
                try:
                    new_message = await safe_edit_message_text(self.bot, chat_id=chat_id, message_id=current_message_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
                except BadRequest as e: # If message didn_t change or other issue
                    logger.warning(f"[QuizLogic] Failed to edit message {current_message_id}, sending new: {e}")
                    await safe_delete_message(self.bot, chat_id, current_message_id) # Clean up old message
                    new_message = await safe_send_message(self.bot, chat_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            else:
                new_message = await safe_send_message(self.bot, chat_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        return new_message.message_id if new_message else None

    def _build_question_keyboard(self, question_data: dict, quiz_id: str, question_index: int) -> InlineKeyboardMarkup:
        """Builds the InlineKeyboardMarkup for the question options."""
        buttons = []
        options = question_data.get("options", []) # New structure

        if options: # New options structure
            for i, option in enumerate(options):
                option_text = option.get("option_text")
                option_image = option.get("image_url")
                display_text = option_text if option_text else f"Image Option {i+1}" # Fallback if only image
                buttons.append([InlineKeyboardButton(display_text, callback_data=f"quiz_{quiz_id}_ans_{question_index}_{i}")])
        else: # Fallback to old structure (option1, option2, etc.)
            for i in range(NUM_OPTIONS):
                option_text = question_data.get(f"option{i+1}")
                option_image = question_data.get(f"option{i+1}_image")
                if option_text or option_image:
                    display_text = option_text if option_text else f"Image Option {i+1}"
                    buttons.append([InlineKeyboardButton(display_text, callback_data=f"quiz_{quiz_id}_ans_{question_index}_{i}")])
        
        buttons.append([InlineKeyboardButton("➡️ تخطي السؤال", callback_data=f"quiz_{quiz_id}_skip_{question_index}")])
        return InlineKeyboardMarkup(buttons)

    async def send_question(self, chat_id: int, user_id: int) -> None:
        """Sends the current question to the user."""
        quiz_data = self.user_data.get("current_quiz")
        if not quiz_data or quiz_data.get("finished"):
            logger.warning(f"[QuizLogic] send_question called for user {user_id} but no active quiz.")
            return

        q_idx = quiz_data["current_question_index"]
        question = quiz_data["questions"][q_idx]
        quiz_id = quiz_data["quiz_id"]

        question_text_main = question.get("question_text", "")
        question_image_url = question.get("image_url")

        header = f"<b>السؤال {q_idx + 1} من {quiz_data["total_questions"]}:</b>\n"
        full_question_text = header + question_text_main

        reply_markup = self._build_question_keyboard(question, quiz_id, q_idx)
        
        new_message_id = await self._send_or_edit_message(
            chat_id=chat_id,
            text=full_question_text,
            reply_markup=reply_markup,
            photo_url=question_image_url,
            current_message_id=quiz_data.get("last_message_id")
        )
        if new_message_id:
            quiz_data["last_message_id"] = new_message_id

        if ENABLE_QUESTION_TIMER:
            job_name = f"qtimer_{chat_id}_{user_id}_{quiz_id}_{q_idx}"
            remove_job_if_exists(job_name, self.context)
            
            timer_context_data = {
                "chat_id": chat_id,
                "user_id": user_id,
                "quiz_id": quiz_id,
                "question_index": q_idx,
            }
            self.context.job_queue.run_once(
                question_timer_callback,
                timedelta(seconds=QUESTION_TIMER_SECONDS),
                data=timer_context_data,
                name=job_name,
                chat_id=chat_id,
                user_id=user_id
            )
            logger.info(f"[QuizLogic] Question timer ({QUESTION_TIMER_SECONDS}s) started for q:{q_idx} quiz:{quiz_id} user:{user_id} (Job: {job_name})")

    async def start_quiz(self, update: Update) -> int:
        """Fetches questions, initializes quiz state, and sends the first question."""
        user = update.effective_user
        chat_id = update.effective_chat.id
        user_id = user.id
        self.user_data["_effective_user_id"] = user_id

        quiz_selection = self.user_data.get("quiz_selection")
        if not quiz_selection or "type" not in quiz_selection or "count" not in quiz_selection or "endpoint" not in quiz_selection:
            logger.error(f"[QuizLogic] start_quiz for user {user_id} without complete quiz_selection: {quiz_selection}")
            await safe_send_message(self.bot, chat_id, text="حدث خطأ، لم يتم تحديد تفاصيل الاختبار. يرجى المحاولة من القائمة الرئيسية.")
            kb = create_main_menu_keyboard(user_id)
            await safe_send_message(self.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
            return MAIN_MENU

        num_questions_req = quiz_selection["count"]
        questions_endpoint = quiz_selection["endpoint"]
        max_available = quiz_selection.get("max_questions", num_questions_req)
        num_questions = min(num_questions_req, max_available)

        if num_questions <= 0:
            logger.warning(f"[QuizLogic] No questions available ({max_available}) for user {user_id} for selection {quiz_selection}. Aborting quiz.")
            await safe_send_message(self.bot, chat_id, text="لا توجد أسئلة متاحة لهذا الاختيار حالياً. يرجى المحاولة لاحقاً أو اختيار قسم آخر.")
            kb = create_main_menu_keyboard(user_id)
            await safe_send_message(self.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
            return MAIN_MENU
        
        await safe_send_message(self.bot, chat_id, text=f"🔍 جارٍ إعداد اختبارك من {get_quiz_type_string(quiz_selection.get("type_display_name", ""))} بعدد {num_questions} أسئلة...", reply_markup=None)

        quiz_questions_raw = []
        if questions_endpoint == "random_api":
            all_fetched_questions = quiz_selection.get("fetched_questions", [])
            if len(all_fetched_questions) < num_questions:
                num_questions = len(all_fetched_questions)
            if num_questions > 0:
                 quiz_questions_raw = random.sample(all_fetched_questions, num_questions)
            quiz_selection.pop("fetched_questions", None)
        else:
            params = {"limit": num_questions}
            api_response = fetch_from_api(questions_endpoint, params=params)
            if api_response == "TIMEOUT" or not isinstance(api_response, list):
                logger.error(f"[QuizLogic] Failed to fetch questions from {questions_endpoint} for user {user_id}. Response: {api_response}")
                await safe_send_message(self.bot, chat_id, text="⚠️ تعذر تحميل أسئلة الاختبار. يرجى المحاولة مرة أخرى لاحقاً.")
                kb = create_main_menu_keyboard(user_id)
                await safe_send_message(self.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
                return MAIN_MENU
            quiz_questions_raw = api_response
            if len(quiz_questions_raw) > num_questions:
                quiz_questions_raw = random.sample(quiz_questions_raw, num_questions)
            elif len(quiz_questions_raw) < num_questions:
                num_questions = len(quiz_questions_raw)

        if num_questions == 0 or not quiz_questions_raw:
            logger.error(f"[QuizLogic] No valid questions obtained for user {user_id} from {questions_endpoint}. Aborting.")
            await safe_send_message(self.bot, chat_id, text="لم يتم العثور على أسئلة صالحة لهذا الاختبار. يرجى المحاولة مرة أخرى أو اختيار موضوع آخر.")
            kb = create_main_menu_keyboard(user_id)
            await safe_send_message(self.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
            return MAIN_MENU

        quiz_questions_transformed = []
        for q_data in quiz_questions_raw:
            transformed = transform_api_question(q_data)
            if transformed and (transformed.get("options") or transformed.get("correct_answer") is not None):
                quiz_questions_transformed.append(transformed)
            else:
                logger.warning(f"[QuizLogic] Skipping invalid question after transformation: {q_data}")
        
        num_questions = len(quiz_questions_transformed)
        if num_questions == 0:
            logger.error(f"[QuizLogic] No questions remained after transformation for user {user_id}. Aborting.")
            await safe_send_message(self.bot, chat_id, text="لم يتم العثور على أسئلة صالحة بعد المعالجة. يرجى المحاولة مرة أخرى.")
            kb = create_main_menu_keyboard(user_id)
            await safe_send_message(self.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
            return MAIN_MENU

        quiz_id = str(uuid.uuid4())
        self.user_data["current_quiz"] = {
            "quiz_id": quiz_id,
            "questions": quiz_questions_transformed,
            "total_questions": num_questions,
            "current_question_index": 0,
            "answers": [None] * num_questions,
            "score": 0,
            "start_time": datetime.now(),
            "finished": False,
            "last_message_id": None,
            "quiz_type_display": quiz_selection.get("type_display_name", "اختبار عام"),
            "quiz_scope_display": quiz_selection.get("scope_display_name", ""),
            "original_num_questions_requested": num_questions_req
        }
        logger.info(f"[QuizLogic] Quiz {quiz_id} started for user {user_id} with {num_questions} questions.")
        await self.send_question(chat_id, user_id)
        return TAKING_QUIZ

    async def handle_answer(self, update: Update, chosen_option_index: int) -> int:
        """Handles user_s answer to a question."""
        query = update.callback_query
        user = update.effective_user
        chat_id = update.effective_chat.id
        user_id = user.id

        quiz_data = self.user_data.get("current_quiz")
        if not quiz_data or quiz_data.get("finished"):
            await query.answer("الاختبار غير نشط أو انتهى.")
            return TAKING_QUIZ

        q_idx = quiz_data["current_question_index"]
        question_data = quiz_data["questions"][q_idx]

        is_correct = False
        correct_answer_text_or_image = "غير محدد"
        options_list = question_data.get("options")
        if options_list:
            if 0 <= chosen_option_index < len(options_list):
                is_correct = options_list[chosen_option_index].get("is_correct", False)
                correct_opt = next((opt for opt in options_list if opt.get("is_correct")), None)
                if correct_opt:
                    correct_answer_text_or_image = correct_opt.get("option_text") or "صورة صحيحة"
        else:
            correct_answer_str = str(question_data.get("correct_answer"))
            if correct_answer_str and str(chosen_option_index + 1) == correct_answer_str:
                is_correct = True
            correct_opt_text_key = f"option{correct_answer_str}"
            correct_opt_image_key = f"option{correct_answer_str}_image"
            # السطر المصحح والنهائي هنا:
            correct_answer_text_or_image = question_data.get(correct_opt_text_key) or ("صورة صحيحة" if question_data.get(correct_opt_image_key) else "غير محدد")

        quiz_data["answers"][q_idx] = chosen_option_index
        if is_correct:
            quiz_data["score"] += 1
            feedback_text = "🎉 إجابة صحيحة!"
        else:
            feedback_text = f"❌ إجابة خاطئة. الإجابة الصحيحة: {correct_answer_text_or_image}"
        
        await query.answer(text="تم تسجيل إجابتك.")
        if quiz_data.get("last_message_id"):
             await safe_edit_message_text(self.bot, chat_id, quiz_data["last_message_id"], text=feedback_text, reply_markup=None)
             await asyncio.sleep(FEEDBACK_DELAY)
        else:
            await safe_send_message(self.bot, chat_id, text=feedback_text)
            await asyncio.sleep(FEEDBACK_DELAY)

        job_name = f"qtimer_{chat_id}_{user_id}_{quiz_data["quiz_id"]}_{q_idx}"
        remove_job_if_exists(job_name, self.context)

        quiz_data["current_question_index"] += 1
        if quiz_data["current_question_index"] < quiz_data["total_questions"]:
            await self.send_question(chat_id, user_id)
            return TAKING_QUIZ
        else:
            return await self.finish_quiz(update, from_answer=True)

    async def handle_skip_question(self, update: Update, timed_out: bool = False, error_occurred: bool = False) -> int:
        """Handles skipping a question (either by user, timeout, or error)."""
        query = update.callback_query
        user = update.effective_user
        chat_id = update.effective_chat.id
        user_id = user.id

        quiz_data = self.user_data.get("current_quiz")
        if not quiz_data or quiz_data.get("finished"):
            if query: await query.answer("الاختبار غير نشط أو انتهى.")
            return MAIN_MENU

        q_idx = quiz_data["current_question_index"]
        quiz_id = quiz_data["quiz_id"]

        if q_idx >= quiz_data["total_questions"] or quiz_data["answers"][q_idx] is not None:
            logger.info(f"[QuizLogic] Question {q_idx + 1} already handled for quiz {quiz_id}, user {user_id}. Skip/Timeout ignored.")
            if query: await query.answer("هذا السؤال تم التعامل معه بالفعل.")
            return TAKING_QUIZ

        skip_message = ""
        if error_occurred:
            quiz_data["answers"][q_idx] = -3
            skip_message = f"تم تسجيل خطأ للسؤال {q_idx + 1}."
            logger.info(f"[QuizLogic] Question {q_idx + 1} marked as ERROR for user {user_id} in quiz {quiz_id}.")
        elif timed_out:
            quiz_data["answers"][q_idx] = -2
            skip_message = f"⏰ انتهى وقت السؤال {q_idx + 1}! تم اعتباره إجابة خاطئة."
            logger.info(f"[QuizLogic] Question {q_idx + 1} marked as TIMED OUT (WRONG) for user {user_id} in quiz {quiz_id}.")
        else:
            quiz_data["answers"][q_idx] = -1
            skip_message = f"تم تخطي السؤال {q_idx + 1}."
            logger.info(f"[QuizLogic] Question {q_idx + 1} SKIPPED by user {user_id} in quiz {quiz_id}.")

        if query: 
            await query.answer("تم تسجيل التخطي.")
        
        if quiz_data.get("last_message_id"):
            await safe_edit_message_text(self.bot, chat_id, quiz_data["last_message_id"], text=skip_message, reply_markup=None)
            await asyncio.sleep(FEEDBACK_DELAY)
        else:
            await safe_send_message(self.bot, chat_id, text=skip_message)
            await asyncio.sleep(FEEDBACK_DELAY)

        job_name = f"qtimer_{chat_id}_{user_id}_{quiz_id}_{q_idx}"
        remove_job_if_exists(job_name, self.context)

        quiz_data["current_question_index"] += 1
        if quiz_data["current_question_index"] < quiz_data["total_questions"]:
            await self.send_question(chat_id, user_id)
            return TAKING_QUIZ
        else:
            return await self.finish_quiz(update, from_skip=True)

    async def finish_quiz(self, update: Update, from_answer: bool = False, from_skip: bool = False) -> int:
        """Finishes the quiz, calculates results, saves to DB, and shows results."""
        user = update.effective_user
        chat_id = update.effective_chat.id
        user_id = user.id

        quiz_data = self.user_data.get("current_quiz")
        if not quiz_data or quiz_data.get("finished") and not (from_answer or from_skip):
            logger.warning(f"[QuizLogic] finish_quiz called for user {user_id} but no active/unfinished quiz.")
            kb = create_main_menu_keyboard(user_id)
            await safe_send_message(self.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
            return MAIN_MENU
        
        quiz_data["finished"] = True
        end_time = datetime.now()
        duration_seconds = (end_time - quiz_data["start_time"]).total_seconds()

        score = quiz_data["score"]
        total_q = quiz_data["total_questions"]
        percentage = (score / total_q * 100) if total_q > 0 else 0

        try:
            DB_MANAGER.add_quiz_result(
                user_id=user_id,
                quiz_type=quiz_data.get("quiz_type_display", "N/A"),
                quiz_scope=quiz_data.get("quiz_scope_display", "N/A"),
                score=score,
                total_questions=total_q,
                percentage=percentage,
                duration_seconds=int(duration_seconds),
                quiz_timestamp=quiz_data["start_time"]
            )
            logger.info(f"[QuizLogic] Quiz {quiz_data["quiz_id"]} results saved for user {user_id}.")
        except Exception as e:
            logger.error(f"[QuizLogic] Failed to save quiz results for user {user_id}: {e}")

        results_text = f"🏁 <b>نتائج الاختبار</b> 🏁\n\n"
        results_text += f"<b>الموضوع:</b> {quiz_data.get("quiz_type_display", "غير محدد")} - {quiz_data.get("quiz_scope_display", "")}\n"
        results_text += f"<b>النتيجة:</b> {score} / {total_q} ({percentage:.2f}%)\n"
        results_text += f"<b>الوقت المستغرق:</b> {format_duration(int(duration_seconds))}\n\n"
        results_text += "أداء رائع! يمكنك مراجعة إجاباتك أو بدء اختبار جديد."

        if quiz_data.get("last_message_id"):
            await safe_delete_message(self.bot, chat_id, quiz_data["last_message_id"])
            quiz_data["last_message_id"] = None

        results_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("العودة إلى قائمة الاختبارات", callback_data="main_quiz_menu")],
            [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="main_menu")]
        ])
        await safe_send_message(self.bot, chat_id, text=results_text, reply_markup=results_keyboard, parse_mode=ParseMode.HTML)
        
        return SHOWING_RESULTS

    async def return_to_main_menu(self, update: Update) -> int:
        """Cleans up quiz state and returns user to the main menu."""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        quiz_data = self.user_data.get("current_quiz")

        if quiz_data:
            if not quiz_data.get("finished"):
                 q_idx = quiz_data["current_question_index"]
                 quiz_id = quiz_data["quiz_id"]
                 job_name = f"qtimer_{chat_id}_{user_id}_{quiz_id}_{q_idx}"
                 remove_job_if_exists(job_name, self.context)
            
            if quiz_data.get("last_message_id"):
                await safe_delete_message(self.bot, chat_id, quiz_data["last_message_id"])

        self.user_data.pop("current_quiz", None)
        self.user_data.pop("quiz_selection", None)
        logger.info(f"[QuizLogic] Quiz data cleared for user {user_id} returning to main menu.")

        kb = create_main_menu_keyboard(user_id)
        await safe_send_message(self.bot, chat_id, text="القائمة الرئيسية:", reply_markup=kb)
        return MAIN_MENU

async def question_timer_callback(context: CallbackContext):
    """Handles the timeout for a single question. Calls the appropriate QuizLogic method."""
    job_data = context.job.data
    chat_id = job_data.get("chat_id")
    user_id = job_data.get("user_id")
    quiz_id = job_data.get("quiz_id")
    question_index_timed_out = job_data.get("question_index")

    logger.info(f"[GLOBAL TIMER] Callback for user {user_id}, quiz {quiz_id}, q_idx {question_index_timed_out}")

    if not hasattr(context, "dispatcher") or not context.dispatcher:
         logger.error("[GLOBAL TIMER] Dispatcher not found in context for question_timer_callback.")
         return
    
    user_data = context.dispatcher.user_data.get(user_id, {})
    current_quiz_data = user_data.get("current_quiz")

    if (current_quiz_data and 
        current_quiz_data.get("quiz_id") == quiz_id and
        current_quiz_data.get("current_question_index") == question_index_timed_out and 
        not current_quiz_data.get("finished") and 
        current_quiz_data["answers"][question_index_timed_out] is None):
        
        logger.info(f"[GLOBAL TIMER] Timeout confirmed for user {user_id}, quiz {quiz_id}, q_idx {question_index_timed_out}. Triggering skip.")
        
        class DummyUpdate:
            class DummyEffectiveUser:
                id = user_id
            class DummyEffectiveChat:
                id = chat_id
            effective_user = DummyEffectiveUser()
            effective_chat = DummyEffectiveChat()
            callback_query = None
        
        dummy_update = DummyUpdate()
        
        temp_logic_instance = QuizLogic(context)
        temp_logic_instance.user_data = user_data

        await temp_logic_instance.handle_skip_question(dummy_update, timed_out=True)
    else:
        logger.info(f"[GLOBAL TIMER] Quiz {quiz_id} for user {user_id} ended, or q_idx {question_index_timed_out} already handled. Timer ignored.")

logger.info("[QuizLogic Module] QuizLogic class and global timer callback defined.")
